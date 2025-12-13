# streamlit_app.py
# BOM Explosão (Produção) - Silva Holding
# Regras:
# 1) Se estoque suficiente do código pai -> NÃO explode
# 2) Se faltar (demanda > estoque) -> explode SOMENTE o faltante
# 3) Explode até insumos (Semi / Gola / Bordado / Extras / Componentes)
# 4) Se insumo faltar -> entra em LISTA_ACAO = "FABRICAR"
# 5) Não mostrar local -> apenas observação "PLATELEIRA ESTOQUE" quando faltar

import io
import os
import re
import json
import math
import time
import pandas as pd
import numpy as np
import requests
import streamlit as st
from datetime import datetime

APP_CONFIG_PATH = "app_config.json"

st.set_page_config(page_title="Cockpit de Controle — Silva Holding", layout="wide")

# ---------------------------
# Utils
# ---------------------------
def _clean_gid(gid_value: str) -> str:
    """Accepts 'gid=123', '123', or URL fragments and returns only digits string."""
    if gid_value is None:
        return ""
    s = str(gid_value).strip()
    m = re.search(r"(\d+)", s)
    return m.group(1) if m else ""

def _gsheet_csv_url(spreadsheet_id: str, gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"

@st.cache_data(show_spinner=False, ttl=60)
def read_gsheet_csv(spreadsheet_id: str, gid: str) -> pd.DataFrame:
    gid = _clean_gid(gid)
    url = _gsheet_csv_url(spreadsheet_id, gid)
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    content = r.content.decode("utf-8", errors="replace")
    return pd.read_csv(io.StringIO(content))

def load_saved_config() -> dict:
    if os.path.exists(APP_CONFIG_PATH):
        try:
            with open(APP_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_config(cfg: dict) -> None:
    with open(APP_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df

def guess_sales_columns(df: pd.DataFrame):
    """
    Detect columns for:
      - codigo (SKU / Código / codigo)
      - quantidade (quantidade / qtde / qtd / quantidade vendida / etc)
    """
    cols = list(df.columns)

    code_candidates = [
        "codigo", "código", "sku", "referencia", "referência",
        "produto", "produto_codigo", "cod", "cód", "codigo_produto"
    ]
    qty_candidates = [
        "quantidade", "qtde", "qtd", "qt", "qde", "qtd_vendida",
        "quantidade_vendida", "quantidade total", "quantidade_total"
    ]

    code_col = None
    qty_col = None

    # direct match
    for c in cols:
        if c in code_candidates:
            code_col = c
            break
    for c in cols:
        if c in qty_candidates:
            qty_col = c
            break

    # fuzzy contains
    if code_col is None:
        for c in cols:
            if "codigo" in c or "código" in c or "sku" in c:
                code_col = c
                break
    if qty_col is None:
        for c in cols:
            if "quant" in c or "qtde" in c or "qtd" in c:
                qty_col = c
                break

    return code_col, qty_col

def read_sales_file(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    elif name.endswith(".xlsx") or name.endswith(".xls"):
        df = pd.read_excel(uploaded_file)
    else:
        raise ValueError("Arquivo de vendas precisa ser CSV ou XLSX.")
    df = normalize_cols(df)
    code_col, qty_col = guess_sales_columns(df)

    if code_col is None or qty_col is None:
        raise KeyError(
            f"Não encontrei colunas de vendas. Achei colunas: {list(df.columns)}. "
            "Precisa ter algo como 'codigo/sku' e 'quantidade/qtde'."
        )

    out = df[[code_col, qty_col]].copy()
    out.columns = ["codigo", "quantidade"]

    # clean
    out["codigo"] = out["codigo"].astype(str).str.strip()
    out["quantidade"] = pd.to_numeric(out["quantidade"], errors="coerce").fillna(0)

    out = out[out["codigo"] != ""]
    out = out.groupby("codigo", as_index=False)["quantidade"].sum()
    out = out[out["quantidade"] > 0]
    return out

def split_list_field(value) -> list:
    """Splits comma-separated lists, tolerates NaN."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    s = str(value).strip()
    if s == "" or s.lower() == "nan":
        return []
    return [x.strip() for x in s.split(",") if x.strip()]

def split_qty_field(value) -> list:
    """Splits comma-separated qty lists into floats/ints."""
    items = split_list_field(value)
    out = []
    for it in items:
        try:
            out.append(float(str(it).replace(",", ".")))
        except Exception:
            out.append(0.0)
    return out

def safe_int(x) -> int:
    try:
        return int(float(x))
    except Exception:
        return 0

# ---------------------------
# BOM Engine
# ---------------------------
class BomEngine:
    def __init__(self, estoque_df, bom_simples_df, bom_kits_df):
        self.estoque = estoque_df.copy()
        self.bom_simples = bom_simples_df.copy()
        self.bom_kits = bom_kits_df.copy()

        self.estoque = normalize_cols(self.estoque)
        self.bom_simples = normalize_cols(self.bom_simples)
        self.bom_kits = normalize_cols(self.bom_kits)

        # expected columns
        # estoque: codigo, estoque_atual
        if "codigo" not in self.estoque.columns:
            raise KeyError("template_estoque precisa ter coluna 'codigo'.")
        if "estoque_atual" not in self.estoque.columns:
            raise KeyError("template_estoque precisa ter coluna 'estoque_atual'.")

        self.estoque["codigo"] = self.estoque["codigo"].astype(str).str.strip()
        self.estoque["estoque_atual"] = pd.to_numeric(self.estoque["estoque_atual"], errors="coerce").fillna(0)

        # Map for fast lookup
        self.stock_map = dict(zip(self.estoque["codigo"], self.estoque["estoque_atual"]))

        # Index BOMs
        if "codigo_final" not in self.bom_simples.columns:
            raise KeyError("bom_produto_simples precisa ter coluna 'codigo_final'.")
        if "codigo_final" not in self.bom_kits.columns:
            raise KeyError("bom_kits_conjuntos precisa ter coluna 'codigo_final'.")

        self.bom_simples["codigo_final"] = self.bom_simples["codigo_final"].astype(str).str.strip()
        self.bom_kits["codigo_final"] = self.bom_kits["codigo_final"].astype(str).str.strip()

        self.simples_map = {row["codigo_final"]: row for _, row in self.bom_simples.iterrows()}
        self.kits_map = {row["codigo_final"]: row for _, row in self.bom_kits.iterrows()}

        # outputs
        self.insumos_rows = []
        self.acao_rows = []

        # to avoid infinite loops
        self.visiting = set()

    def stock(self, codigo: str) -> float:
        return float(self.stock_map.get(str(codigo).strip(), 0))

    def shortfall(self, codigo: str, demand: float) -> float:
        """Explode only the missing quantity (demand - available), never negative."""
        available = self.stock(codigo)
        # if negative stock, treat as 0 available (so shortfall is full demand)
        available = max(0.0, available)
        return max(0.0, float(demand) - available)

    def add_insumo(self, parent, insumo_tipo, insumo_codigo, req_qtd, stock_qtd):
        faltante = max(0.0, req_qtd - max(0.0, stock_qtd))
        status = "OK" if faltante <= 0 else "FALTANDO"
        obs = "" if faltante <= 0 else "PLATELEIRA ESTOQUE"
        self.insumos_rows.append({
            "codigo_pai": parent,
            "tipo": insumo_tipo,
            "codigo_insumo": insumo_codigo,
            "qtd_necessaria": req_qtd,
            "estoque_atual": stock_qtd,
            "faltante": faltante,
            "status": status,
            "observacao": obs,
        })
        if faltante > 0:
            self.acao_rows.append({
                "acao": "FABRICAR",
                "tipo": insumo_tipo,
                "codigo": insumo_codigo,
                "quantidade": faltante,
                "observacao": "PLATELEIRA ESTOQUE",
                "origem": parent
            })

    def explode(self, codigo_final: str, demand: float, root_parent: str = None):
        """
        Explodes demand for codigo_final following rules.
        root_parent: original sales code for reporting trace.
        """
        codigo_final = str(codigo_final).strip()
        if root_parent is None:
            root_parent = codigo_final

        # Prevent cycles
        key = (codigo_final, root_parent)
        if key in self.visiting:
            return
        self.visiting.add(key)

        faltante = self.shortfall(codigo_final, demand)

        # Rule: if no shortfall, don't explode
        if faltante <= 0:
            self.visiting.remove(key)
            return

        # If it's a KIT/CONJUNTO, explode into components first
        if codigo_final in self.kits_map:
            row = self.kits_map[codigo_final]
            comps = split_list_field(row.get("componentes_codigos"))
            qtys = split_qty_field(row.get("componentes_qtds"))

            # pad qtys
            if len(qtys) < len(comps):
                qtys += [1.0] * (len(comps) - len(qtys))

            for comp, q in zip(comps, qtys):
                comp_demand = faltante * float(q if q is not None else 1.0)
                # each component is treated like a product: if has stock, no further explosion
                self.explode(comp, comp_demand, root_parent=root_parent)

            self.visiting.remove(key)
            return

        # If it's a SIMPLE product, explode to insumos
        if codigo_final in self.simples_map:
            row = self.simples_map[codigo_final]

            # Semi
            semi_cod = row.get("semi_codigo")
            semi_qtd = row.get("semi_qtd", 1)
            semi_cod = "" if semi_cod is None else str(semi_cod).strip()
            semi_qtd = float(semi_qtd) if str(semi_qtd).strip() != "" else 1.0

            if semi_cod:
                req = faltante * semi_qtd
                self.add_insumo(root_parent, "SEMI", semi_cod, req, self.stock(semi_cod))

            # Golas (lista)
            golas = split_list_field(row.get("gola_codigo"))
            gola_qtys = split_qty_field(row.get("gola_qtd"))

            if len(gola_qtys) < len(golas):
                gola_qtys += [1.0] * (len(golas) - len(gola_qtys))

            for g, q in zip(golas, gola_qtys):
                if g:
                    req = faltante * float(q)
                    self.add_insumo(root_parent, "GOLA", g, req, self.stock(g))

            # Bordado
            bcod = row.get("bordado_codigo")
            bqtd = row.get("bordado_qtd", 0)
            bcod = "" if bcod is None else str(bcod).strip()
            bqtd = float(bqtd) if str(bqtd).strip() != "" else 0.0
            if bcod and bqtd > 0:
                req = faltante * bqtd
                self.add_insumo(root_parent, "BORDADO", bcod, req, self.stock(bcod))

            # Extras (lista)
            extras = split_list_field(row.get("extras_codigos"))
            extras_qtys = split_qty_field(row.get("extras_qtds"))
            if len(extras_qtys) < len(extras):
                extras_qtys += [1.0] * (len(extras) - len(extras_qtys))

            for e, q in zip(extras, extras_qtys):
                if e:
                    req = faltante * float(q)
                    self.add_insumo(root_parent, "EXTRA", e, req, self.stock(e))

            self.visiting.remove(key)
            return

        # If no BOM registered for this code -> treat as "missing mapping"
        self.acao_rows.append({
            "acao": "CADASTRAR_BOM",
            "tipo": "PRODUTO",
            "codigo": codigo_final,
            "quantidade": faltante,
            "observacao": "Sem BOM cadastrada",
            "origem": root_parent
        })

        self.visiting.remove(key)

    def build_reports(self):
        insumos = pd.DataFrame(self.insumos_rows) if self.insumos_rows else pd.DataFrame(
            columns=["codigo_pai","tipo","codigo_insumo","qtd_necessaria","estoque_atual","faltante","status","observacao"]
        )
        acao = pd.DataFrame(self.acao_rows) if self.acao_rows else pd.DataFrame(
            columns=["acao","tipo","codigo","quantidade","observacao","origem"]
        )

        # Aggregate duplicates
        if not insumos.empty:
            insumos["qtd_necessaria"] = pd.to_numeric(insumos["qtd_necessaria"], errors="coerce").fillna(0)
            insumos["estoque_atual"] = pd.to_numeric(insumos["estoque_atual"], errors="coerce").fillna(0)
            insumos["faltante"] = pd.to_numeric(insumos["faltante"], errors="coerce").fillna(0)

            insumos = (insumos
                .groupby(["codigo_pai","tipo","codigo_insumo"], as_index=False)
                .agg({
                    "qtd_necessaria":"sum",
                    "estoque_atual":"first",
                    "faltante":"sum",
                    "observacao":"first"
                })
            )
            insumos["status"] = np.where(insumos["faltante"] > 0, "FALTANDO", "OK")

            # Order: faltantes first
            insumos = insumos.sort_values(["status","faltante"], ascending=[True, False])
            # Put FALTANDO on top
            insumos["status_order"] = np.where(insumos["status"]=="FALTANDO", 0, 1)
            insumos = insumos.sort_values(["status_order","faltante"], ascending=[True, False]).drop(columns=["status_order"])

        if not acao.empty:
            acao["quantidade"] = pd.to_numeric(acao["quantidade"], errors="coerce").fillna(0)
            acao = (acao
                .groupby(["acao","tipo","codigo","observacao"], as_index=False)
                .agg({
                    "quantidade":"sum",
                    "origem":lambda x: ", ".join(sorted(set([str(v) for v in x if str(v).strip() != ""])))[:500]
                })
            )
            acao = acao.sort_values(["acao","quantidade"], ascending=[True, False])

        return insumos, acao


def to_excel_bytes(insumos_df: pd.DataFrame, acao_df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        insumos_df.to_excel(writer, index=False, sheet_name="03_INSUMOS")
        acao_df.to_excel(writer, index=False, sheet_name="04_LISTA_ACAO")
    return output.getvalue()


# ---------------------------
# UI
# ---------------------------
saved = load_saved_config()

if "cfg" not in st.session_state:
    st.session_state.cfg = {
        "spreadsheet_id": saved.get("spreadsheet_id", ""),
        "gid_template_estoque": saved.get("gid_template_estoque", ""),
        "gid_bom_produto_simples": saved.get("gid_bom_produto_simples", ""),
        "gid_bom_kits_conjuntos": saved.get("gid_bom_kits_conjuntos", ""),
    }

tab1, tab2 = st.tabs(["📦 Explosão BOM (Produção)", "⚙️ Configuração / Diagnóstico"])

with tab2:
    st.markdown("### Configuração de Fonte de Dados")
    st.caption("Cole o Spreadsheet ID e os GIDs. Aceita 'gid=123' ou só '123'. Clique em **Salvar** e você não preenche mais.")

    c1, c2, c3, c4 = st.columns([2,1,1,1])
    with c1:
        spreadsheet_id = st.text_input("Spreadsheet ID (entre /d/ e /edit)", value=st.session_state.cfg["spreadsheet_id"])
    with c2:
        gid_template = st.text_input("GID da aba template_estoque", value=st.session_state.cfg["gid_template_estoque"])
    with c3:
        gid_simples = st.text_input("GID da aba bom_produto_simples", value=st.session_state.cfg["gid_bom_produto_simples"])
    with c4:
        gid_kits = st.text_input("GID da aba bom_kits_conjuntos", value=st.session_state.cfg["gid_bom_kits_conjuntos"])

    colA, colB = st.columns([1,3])
    with colA:
        if st.button("💾 Salvar configuração"):
            st.session_state.cfg.update({
                "spreadsheet_id": str(spreadsheet_id).strip(),
                "gid_template_estoque": _clean_gid(gid_template),
                "gid_bom_produto_simples": _clean_gid(gid_simples),
                "gid_bom_kits_conjuntos": _clean_gid(gid_kits),
            })
            save_config(st.session_state.cfg)
            st.success("Config salva. Agora você não precisa preencher toda hora (enquanto o app estiver rodando).")

    st.markdown("---")
    st.markdown("### Teste rápido de leitura (sem explosão)")

    if st.button("🔎 Validar leitura agora"):
        try:
            sid = str(spreadsheet_id).strip()
            if not sid:
                st.error("Preencha o Spreadsheet ID.")
            else:
                df_est = read_gsheet_csv(sid, _clean_gid(gid_template))
                df_s  = read_gsheet_csv(sid, _clean_gid(gid_simples))
                df_k  = read_gsheet_csv(sid, _clean_gid(gid_kits))

                st.success("Leitura OK ✅")
                st.write("template_estoque (amostra):", df_est.head(20))
                st.write("bom_produto_simples (amostra):", df_s.head(20))
                st.write("bom_kits_conjuntos (amostra):", df_k.head(20))

        except Exception as e:
            st.error(f"Erro ao ler/validar: {type(e).__name__}: {e}")

with tab1:
    st.markdown("## Explosão BOM (Produção)")
    st.caption("Suba a planilha de vendas (CSV/XLSX). O app explode apenas o faltante e gera relatório (Insumos + Lista de Ação).")

    cfg = st.session_state.cfg
    if not cfg.get("spreadsheet_id") or not cfg.get("gid_template_estoque"):
        st.warning("Vá em **Configuração / Diagnóstico** e salve Spreadsheet ID + GIDs primeiro.")
        st.stop()

    uploaded = st.file_uploader("Upload vendas (CSV/XLSX com colunas codigo/quantidade — Bling também serve)", type=["csv","xlsx","xls"])

    if uploaded:
        try:
            vendas = read_sales_file(uploaded)
            st.write("✅ Vendas lidas (amostra):", vendas.head(30))

            sid = cfg["spreadsheet_id"]
            df_est = read_gsheet_csv(sid, cfg["gid_template_estoque"])
            df_s   = read_gsheet_csv(sid, cfg["gid_bom_produto_simples"])
            df_k   = read_gsheet_csv(sid, cfg["gid_bom_kits_conjuntos"])

            engine = BomEngine(df_est, df_s, df_k)

            if st.button("🚀 Gerar relatório de explosão"):
                with st.spinner("Explodindo BOM..."):
                    for _, r in vendas.iterrows():
                        engine.explode(r["codigo"], float(r["quantidade"]), root_parent=r["codigo"])

                    insumos_df, acao_df = engine.build_reports()

                st.success("Relatório gerado ✅")

                st.markdown("### 03_INSUMOS")
                st.dataframe(insumos_df, use_container_width=True, height=380)

                st.markdown("### 04_LISTA_ACAO")
                st.dataframe(acao_df, use_container_width=True, height=320)

                xbytes = to_excel_bytes(insumos_df, acao_df)
                fname = f"relatorio_bom_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                st.download_button("⬇️ Baixar Excel (03_INSUMOS + 04_LISTA_ACAO)", data=xbytes, file_name=fname)

        except Exception as e:
            st.error(f"{type(e).__name__}: {e}")
            st.info("Dica: Se for Bling, confirme se existe uma coluna parecida com 'Código/SKU' e outra com 'Quantidade/Qtde'.")
