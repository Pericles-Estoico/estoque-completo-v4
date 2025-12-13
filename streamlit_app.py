# streamlit_app.py
# -*- coding: utf-8 -*-

import io
import re
import math
import pandas as pd
import streamlit as st
from datetime import datetime
from typing import Dict, List, Tuple, Optional

st.set_page_config(page_title="Cockpit de Controle — Silva Holding", layout="wide")

# =========================
# Utils
# =========================

def norm_str(x) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    # normaliza múltiplos espaços
    s = re.sub(r"\s+", " ", s)
    return s

def to_float(x, default=0.0) -> float:
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return default
        s = str(x).strip()
        if s == "":
            return default
        # suporta "1,2" como decimal e também separador de lista
        # aqui interpretamos como número simples (decimal) se fizer sentido:
        s2 = s.replace(".", "").replace(",", ".") if re.fullmatch(r"[\d\.\,]+", s) else s
        return float(s2)
    except Exception:
        return default

def parse_list_str(s: str) -> List[str]:
    """Converte 'A,B,C' em ['A','B','C']."""
    s = norm_str(s)
    if not s:
        return []
    parts = [p.strip() for p in s.split(",")]
    return [p for p in parts if p]

def parse_list_nums(s: str) -> List[float]:
    """Converte '1,2,1' em [1,2,1]."""
    s = norm_str(s)
    if not s:
        return []
    parts = [p.strip() for p in s.split(",")]
    out = []
    for p in parts:
        if p == "":
            continue
        # aceita "1" ou "1.0" ou "1,0"
        out.append(to_float(p, default=0.0))
    return out

def status_from_gap(gap: float) -> str:
    if gap <= 0:
        return "OK"
    return "FALTANTE"

def gsheet_csv_url(spreadsheet_id: str, gid: str) -> str:
    # Export CSV por gid
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"

def read_sales_file(file) -> pd.DataFrame:
    name = file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        df = pd.read_excel(file)

    # normaliza colunas
    cols = {c: norm_str(c).lower() for c in df.columns}
    df = df.rename(columns=cols)

    # tolerância: codigo pode vir como "codigo", "código", "sku", "produto", etc
    codigo_candidates = ["codigo", "código", "sku", "cod", "product", "produto", "codigo_produto", "código_produto"]
    qtd_candidates = ["quantidade", "qtd", "qtde", "qte", "qty", "quant"]

    codigo_col = next((c for c in df.columns if c in codigo_candidates), None)
    qtd_col = next((c for c in df.columns if c in qtd_candidates), None)

    # fallback: tenta achar colunas que contenham "cod" e "qtd/quant"
    if codigo_col is None:
        codigo_col = next((c for c in df.columns if "cod" in c or "sku" in c), None)
    if qtd_col is None:
        qtd_col = next((c for c in df.columns if "qtd" in c or "quant" in c or "qty" in c), None)

    if codigo_col is None or qtd_col is None:
        raise KeyError(f"Não consegui identificar colunas de vendas. Achei colunas: {list(df.columns)}. "
                       f"Preciso de algo como 'codigo' e 'quantidade' (ou 'sku' e 'qtd').")

    vendas = df[[codigo_col, qtd_col]].copy()
    vendas.columns = ["codigo", "quantidade"]
    vendas["codigo"] = vendas["codigo"].astype(str).map(norm_str)
    vendas["quantidade"] = vendas["quantidade"].apply(lambda x: to_float(x, 0.0))
    vendas = vendas[vendas["codigo"] != ""]
    vendas = vendas.groupby("codigo", as_index=False)["quantidade"].sum()
    vendas["quantidade"] = vendas["quantidade"].astype(float)
    return vendas

# =========================
# Load Master Data (estoque + BOMs)
# =========================

def load_from_gsheets(spreadsheet_id: str, gid_estoque: str, gid_simples: str, gid_kits: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    estoque_url = gsheet_csv_url(spreadsheet_id, gid_estoque)
    simples_url = gsheet_csv_url(spreadsheet_id, gid_simples)
    kits_url = gsheet_csv_url(spreadsheet_id, gid_kits)

    estoque = pd.read_csv(estoque_url)
    bom_simples = pd.read_csv(simples_url)
    bom_kits = pd.read_csv(kits_url)
    return estoque, bom_simples, bom_kits

def load_from_excel(file) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    xls = pd.ExcelFile(file)
    # nomes esperados conforme sua estrutura
    estoque = pd.read_excel(xls, "template_estoque")
    bom_simples = pd.read_excel(xls, "bom_produto_simples")
    bom_kits = pd.read_excel(xls, "bom_kits_conjuntos")
    return estoque, bom_simples, bom_kits

def normalize_estoque(df: pd.DataFrame) -> pd.DataFrame:
    # Espera ter pelo menos: codigo e estoque_atual (do seu template_estoque)
    cols = {c: norm_str(c).lower() for c in df.columns}
    df = df.rename(columns=cols)

    # tenta identificar colunas relevantes
    codigo_col = None
    estoque_col = None

    for c in df.columns:
        if c in ["codigo", "código"]:
            codigo_col = c
        if c in ["estoque_atual", "estoque", "saldo", "qtd_estoque"]:
            estoque_col = c

    if codigo_col is None:
        # fallback
        codigo_col = next((c for c in df.columns if "cod" in c), None)
    if estoque_col is None:
        estoque_col = next((c for c in df.columns if "estoque" in c or "saldo" in c), None)

    if codigo_col is None or estoque_col is None:
        raise KeyError(f"Template de estoque precisa ter colunas de 'codigo' e 'estoque_atual'. Achei: {list(df.columns)}")

    out = df[[codigo_col, estoque_col]].copy()
    out.columns = ["codigo", "estoque_atual"]
    out["codigo"] = out["codigo"].astype(str).map(norm_str)
    out["estoque_atual"] = out["estoque_atual"].apply(lambda x: to_float(x, 0.0))
    out = out[out["codigo"] != ""]
    # Se houver duplicado, soma (mais seguro)
    out = out.groupby("codigo", as_index=False)["estoque_atual"].sum()
    return out

def normalize_bom_simples(df: pd.DataFrame) -> pd.DataFrame:
    cols = {c: norm_str(c).lower() for c in df.columns}
    df = df.rename(columns=cols)

    required = ["codigo_final", "semi_codigo", "semi_qtd", "gola_codigo", "gola_qtd", "bordado_codigo", "bordado_qtd", "extras_codigos", "extras_qtds"]
    for c in required:
        if c not in df.columns:
            df[c] = ""

    out = df[required].copy()
    out["codigo_final"] = out["codigo_final"].astype(str).map(norm_str)
    out["semi_codigo"] = out["semi_codigo"].astype(str).map(norm_str)
    out["semi_qtd"] = out["semi_qtd"].apply(lambda x: to_float(x, 0.0))

    out["gola_codigo"] = out["gola_codigo"].astype(str).map(norm_str)
    out["gola_qtd"] = out["gola_qtd"].astype(str).map(norm_str)

    out["bordado_codigo"] = out["bordado_codigo"].astype(str).map(norm_str)
    out["bordado_qtd"] = out["bordado_qtd"].apply(lambda x: to_float(x, 0.0))

    out["extras_codigos"] = out["extras_codigos"].astype(str).map(norm_str)
    out["extras_qtds"] = out["extras_qtds"].astype(str).map(norm_str)

    out = out[out["codigo_final"] != ""]
    return out

def normalize_bom_kits(df: pd.DataFrame) -> pd.DataFrame:
    cols = {c: norm_str(c).lower() for c in df.columns}
    df = df.rename(columns=cols)

    required = ["codigo_final", "componentes_codigos", "componentes_qtds"]
    for c in required:
        if c not in df.columns:
            df[c] = ""

    out = df[required].copy()
    out["codigo_final"] = out["codigo_final"].astype(str).map(norm_str)
    out["componentes_codigos"] = out["componentes_codigos"].astype(str).map(norm_str)
    out["componentes_qtds"] = out["componentes_qtds"].astype(str).map(norm_str)
    out = out[out["codigo_final"] != ""]
    return out

# =========================
# Explosion Engine
# =========================

class BomEngine:
    def __init__(self, estoque_df: pd.DataFrame, bom_simples_df: pd.DataFrame, bom_kits_df: pd.DataFrame):
        self.estoque = estoque_df.set_index("codigo")["estoque_atual"].to_dict()
        self.bom_simples = bom_simples_df.set_index("codigo_final").to_dict(orient="index")
        self.bom_kits = bom_kits_df.set_index("codigo_final").to_dict(orient="index")
        self.logs: List[str] = []

        # acumuladores
        self.faltantes_pai: Dict[str, Dict[str, float]] = {}
        self.insumos_req: Dict[Tuple[str, str], float] = {}  # (tipo, codigo) -> requerido

    def estoque_of(self, codigo: str) -> float:
        return float(self.estoque.get(codigo, 0.0))

    def add_insumo(self, tipo: str, codigo: str, qtd: float):
        codigo = norm_str(codigo)
        if not codigo or qtd <= 0:
            return
        k = (tipo, codigo)
        self.insumos_req[k] = float(self.insumos_req.get(k, 0.0) + qtd)

    def explode_demanda(self, codigo: str, demanda: float, is_top_level: bool = True):
        codigo = norm_str(codigo)
        if codigo == "" or demanda <= 0:
            return

        estoque = self.estoque_of(codigo)
        faltante = max(demanda - estoque, 0.0)

        if is_top_level:
            self.faltantes_pai[codigo] = {
                "demanda": float(demanda),
                "estoque_atual": float(estoque),
                "faltante": float(faltante),
            }

        # Regra suprema: se tem estoque suficiente do pai, NÃO explode
        if faltante <= 0:
            self.logs.append(f"[OK] {codigo}: demanda {demanda} <= estoque {estoque} → NÃO explode")
            return

        self.logs.append(f"[EXPLODE] {codigo}: demanda {demanda}, estoque {estoque}, faltante {faltante}")

        # 1) Se for kit/conjunto: explode em componentes (que viram demanda)
        if codigo in self.bom_kits:
            row = self.bom_kits[codigo]
            comp_codes = parse_list_str(row.get("componentes_codigos", ""))
            comp_qtds = parse_list_nums(row.get("componentes_qtds", ""))

            if len(comp_codes) != len(comp_qtds):
                self.logs.append(f"[ERRO] Kit {codigo}: componentes_codigos ({len(comp_codes)}) != componentes_qtds ({len(comp_qtds)})")
                return

            for cc, qq in zip(comp_codes, comp_qtds):
                req = faltante * float(qq)
                self.logs.append(f"  ↳ componente {cc} x {qq} → demanda {req}")
                self.explode_demanda(cc, req, is_top_level=False)
            return

        # 2) Se for produto simples: explode até insumos
        if codigo in self.bom_simples:
            row = self.bom_simples[codigo]

            # SEMI
            semi = norm_str(row.get("semi_codigo", ""))
            semi_q = float(to_float(row.get("semi_qtd", 0.0), 0.0))
            if semi:
                self.add_insumo("SEMI", semi, faltante * semi_q)
                self.logs.append(f"  ↳ SEMI {semi} x {semi_q} → {faltante * semi_q}")

            # GOLAS (lista) — qtds são "pares" conforme sua regra
            gola_codes = parse_list_str(row.get("gola_codigo", ""))
            gola_qtds = parse_list_nums(row.get("gola_qtd", ""))

            if gola_codes or gola_qtds:
                if len(gola_codes) != len(gola_qtds):
                    self.logs.append(f"[ERRO] Simples {codigo}: gola_codigo ({len(gola_codes)}) != gola_qtd ({len(gola_qtds)})")
                else:
                    for gc, gq in zip(gola_codes, gola_qtds):
                        self.add_insumo("GOLA", gc, faltante * float(gq))
                        self.logs.append(f"  ↳ GOLA {gc} x {gq} → {faltante * float(gq)}")

            # BORDADO (1 item)
            bord = norm_str(row.get("bordado_codigo", ""))
            bord_q = float(to_float(row.get("bordado_qtd", 0.0), 0.0))
            if bord:
                self.add_insumo("BORDADO", bord, faltante * bord_q)
                self.logs.append(f"  ↳ BORDADO {bord} x {bord_q} → {faltante * bord_q}")

            # EXTRAS (lista)
            extras_codes = parse_list_str(row.get("extras_codigos", ""))
            extras_qtds = parse_list_nums(row.get("extras_qtds", ""))

            if extras_codes or extras_qtds:
                if len(extras_codes) != len(extras_qtds):
                    self.logs.append(f"[ERRO] Simples {codigo}: extras_codigos ({len(extras_codes)}) != extras_qtds ({len(extras_qtds)})")
                else:
                    for ec, eq in zip(extras_codes, extras_qtds):
                        self.add_insumo("EXTRA", ec, faltante * float(eq))
                        self.logs.append(f"  ↳ EXTRA {ec} x {eq} → {faltante * float(eq)}")
            return

        # 3) Se não está cadastrado em kit nem simples
        self.logs.append(f"[ALERTA] {codigo} não encontrado em BOM (nem kit, nem simples). Nada a explodir.")

    def build_insumos_df(self) -> pd.DataFrame:
        rows = []
        for (tipo, codigo), requerido in sorted(self.insumos_req.items(), key=lambda x: (x[0][0], x[0][1])):
            est = self.estoque_of(codigo)
            gap = max(requerido - est, 0.0)
            rows.append({
                "tipo": tipo,
                "insumo_codigo": codigo,
                "requerido": float(requerido),
                "estoque_atual": float(est),
                "faltante": float(gap),
                "status": "OK" if gap <= 0 else "FALTANTE",
            })
        return pd.DataFrame(rows)

    def build_lista_acao_df(self) -> pd.DataFrame:
        ins = self.build_insumos_df()
        if ins.empty:
            return pd.DataFrame(columns=["acao", "item", "qtd", "observacao"])
        falt = ins[ins["faltante"] > 0].copy()
        falt["acao"] = "FABRICAR"
        falt["item"] = falt["insumo_codigo"]
        falt["qtd"] = falt["faltante"]
        falt["observacao"] = "PLATELEIRA ESTOQUE"
        return falt[["acao", "item", "qtd", "observacao", "tipo"]].sort_values(["tipo", "qtd"], ascending=[True, False])

    def build_faltantes_pai_df(self) -> pd.DataFrame:
        rows = []
        for codigo, d in self.faltantes_pai.items():
            rows.append({
                "codigo_final": codigo,
                "demanda": d["demanda"],
                "estoque_atual": d["estoque_atual"],
                "faltante": d["faltante"],
                "status": "OK" if d["faltante"] <= 0 else "FALTANTE",
            })
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values(["status", "faltante"], ascending=[True, False])
        return df

# =========================
# UI
# =========================

st.markdown(
    """
    <div style="padding:16px;border-radius:12px;background:linear-gradient(90deg,#123b7a,#0b2f5c);color:white;">
      <div style="font-size:32px;font-weight:800;text-align:center;">COCKPIT DE CONTROLE — SILVA HOLDING</div>
      <div style="text-align:center;opacity:.9;margin-top:6px;">"Se parar para sentir o perfume das rosas, vem um caminhão e te atropela."</div>
    </div>
    """,
    unsafe_allow_html=True
)

st.write("")
tab1, tab2 = st.tabs(["📦 Explosão BOM (Produção)", "⚙️ Configuração / Diagnóstico"])

with tab2:
    st.subheader("Configuração de Fonte de Dados")
    fonte = st.radio("Como ler a planilha template_estoque?", ["Google Sheets (recomendado)", "Upload de Excel (template_estoque + BOMs)"], horizontal=True)

    spreadsheet_id = ""
    gid_estoque = ""
    gid_simples = ""
    gid_kits = ""
    uploaded_master = None

    if fonte == "Google Sheets (recomendado)":
        st.caption("Informe o Spreadsheet ID e os GIDs de cada aba.")
        spreadsheet_id = st.text_input("Spreadsheet ID (entre /d/ e /edit)", value="")
        c1, c2, c3 = st.columns(3)
        with c1:
            gid_estoque = st.text_input("GID da aba template_estoque", value="")
        with c2:
            gid_simples = st.text_input("GID da aba bom_produto_simples", value="")
        with c3:
            gid_kits = st.text_input("GID da aba bom_kits_conjuntos", value="")

        st.caption("Dica: no link do Google Sheets aparece `gid=...` para cada aba.")
    else:
        uploaded_master = st.file_uploader("Upload do Excel master (com abas template_estoque, bom_produto_simples, bom_kits_conjuntos)", type=["xlsx"])

    st.markdown("---")
    st.subheader("Teste rápido de leitura (sem explosão)")
    if st.button("🔍 Validar leitura agora"):
        try:
            if fonte == "Google Sheets (recomendado)":
                if not spreadsheet_id or not gid_estoque or not gid_simples or not gid_kits:
                    st.warning("Preencha Spreadsheet ID e os 3 GIDs.")
                else:
                    estoque_raw, simples_raw, kits_raw = load_from_gsheets(spreadsheet_id, gid_estoque, gid_simples, gid_kits)
                    estoque = normalize_estoque(estoque_raw)
                    simples = normalize_bom_simples(simples_raw)
                    kits = normalize_bom_kits(kits_raw)
                    st.success("Leitura OK ✅")
                    st.write("template_estoque (amostra):")
                    st.dataframe(estoque.head(20), use_container_width=True)
                    st.write("bom_produto_simples (amostra):")
                    st.dataframe(simples.head(20), use_container_width=True)
                    st.write("bom_kits_conjuntos (amostra):")
                    st.dataframe(kits.head(20), use_container_width=True)
            else:
                if uploaded_master is None:
                    st.warning("Suba o Excel master.")
                else:
                    estoque_raw, simples_raw, kits_raw = load_from_excel(uploaded_master)
                    estoque = normalize_estoque(estoque_raw)
                    simples = normalize_bom_simples(simples_raw)
                    kits = normalize_bom_kits(kits_raw)
                    st.success("Leitura OK ✅")
                    st.dataframe(estoque.head(20), use_container_width=True)
        except Exception as e:
            st.error(f"Erro ao ler/validar: {e}")

with tab1:
    st.subheader("Explosão BOM para Produção (com sua regra suprema)")
    st.caption("Tendo estoque suficiente do produto final → NÃO explode. Se faltar → explode só o faltante até nível de insumos.")

    colA, colB = st.columns([2, 1])
    with colA:
        sales_file = st.file_uploader("Upload vendas (CSV/XLSX com colunas codigo/quantidade ou sku/qtd)", type=["csv", "xlsx"])
    with colB:
        st.write("")
        st.write("")
        run = st.button("🔥 Rodar Explosão BOM", use_container_width=True)

    if run:
        try:
            if sales_file is None:
                st.warning("Suba o arquivo de vendas primeiro.")
                st.stop()

            # Lê master
            if fonte == "Google Sheets (recomendado)":
                if not spreadsheet_id or not gid_estoque or not gid_simples or not gid_kits:
                    st.warning("Vá em Configuração e preencha Spreadsheet ID e os 3 GIDs.")
                    st.stop()
                estoque_raw, simples_raw, kits_raw = load_from_gsheets(spreadsheet_id, gid_estoque, gid_simples, gid_kits)
            else:
                if uploaded_master is None:
                    st.warning("Vá em Configuração e suba o Excel master.")
                    st.stop()
                estoque_raw, simples_raw, kits_raw = load_from_excel(uploaded_master)

            estoque = normalize_estoque(estoque_raw)
            bom_simples = normalize_bom_simples(simples_raw)
            bom_kits = normalize_bom_kits(kits_raw)

            vendas = read_sales_file(sales_file)

            engine = BomEngine(estoque, bom_simples, bom_kits)

            # explode para cada item vendido
            for _, r in vendas.iterrows():
                engine.explode_demanda(r["codigo"], float(r["quantidade"]), is_top_level=True)

            df_pai = engine.build_faltantes_pai_df()
            df_ins = engine.build_insumos_df()
            df_acao = engine.build_lista_acao_df()
            df_logs = pd.DataFrame({"log": engine.logs})

            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("SKUs vendidos", len(vendas))
            with c2:
                st.metric("Pais faltantes", int((df_pai["faltante"] > 0).sum()) if not df_pai.empty else 0)
            with c3:
                st.metric("Insumos faltantes", int((df_ins["faltante"] > 0).sum()) if not df_ins.empty else 0)

            st.markdown("### 01 — Faltantes do Produto Final")
            st.dataframe(df_pai, use_container_width=True)

            st.markdown("### 03 — Insumos Requeridos (Explodidos)")
            if not df_ins.empty:
                def color_status(row):
                    if row["faltante"] <= 0:
                        return ["background-color: #e7f6ea"] * len(row)
                    # parcial x total: se estoque > 0 e faltante > 0 => laranja
                    if row["estoque_atual"] > 0 and row["faltante"] > 0:
                        return ["background-color: #fff3cd"] * len(row)
                    # estoque 0 e faltante > 0 => vermelho
                    return ["background-color: #f8d7da"] * len(row)

                st.dataframe(df_ins.style.apply(color_status, axis=1), use_container_width=True)
            else:
                st.info("Sem insumos a explodir/sem faltantes.")

            st.markdown("### 04 — Lista de Ação (FABRICAR)")
            st.dataframe(df_acao, use_container_width=True)

            st.markdown("### Logs")
            st.dataframe(df_logs.tail(300), use_container_width=True)

            # Excel download
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                df_pai.to_excel(writer, index=False, sheet_name="01_FALTANTES_PAI")
                df_ins.to_excel(writer, index=False, sheet_name="03_INSUMOS")
                df_acao.to_excel(writer, index=False, sheet_name="04_LISTA_ACAO")
                vendas.to_excel(writer, index=False, sheet_name="VENDAS_AGREGADAS")
                df_logs.to_excel(writer, index=False, sheet_name="LOGS")

            output.seek(0)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.download_button(
                label="⬇️ Baixar Relatório Excel Completo",
                data=output,
                file_name=f"relatorio_bom_{stamp}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

        except Exception as e:
            st.error(f"Erro ao rodar: {e}")
            st.stop()
