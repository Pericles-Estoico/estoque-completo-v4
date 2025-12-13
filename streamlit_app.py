import os
import json
import re
from io import BytesIO
from datetime import datetime

import pandas as pd
import streamlit as st

APP_TITLE = "COCKPIT DE CONTROLE — SILVA HOLDING"
CONFIG_PATH = "config_bom.json"


# -----------------------------
# Utilidades: Config persistente
# -----------------------------
def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def normalize_gid(value: str) -> str:
    """
    Aceita 'gid=123', '123', '  gid=123  ' etc, e retorna só o número.
    """
    if value is None:
        return ""
    s = str(value).strip()
    s = s.replace("GID", "gid").replace("Gid", "gid").strip()
    if "gid=" in s:
        s = s.split("gid=")[-1]
    s = re.sub(r"[^\d]", "", s)
    return s


def sheet_csv_url(spreadsheet_id: str, gid: str) -> str:
    gid = normalize_gid(gid)
    spreadsheet_id = str(spreadsheet_id).strip()
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"


@st.cache_data(show_spinner=False)
def read_google_sheet_csv(spreadsheet_id: str, gid: str) -> pd.DataFrame:
    url = sheet_csv_url(spreadsheet_id, gid)
    df = pd.read_csv(url, dtype=str).fillna("")
    return df


# -----------------------------
# Utilidades: limpeza e parsing
# -----------------------------
def _to_float_safe(x):
    if x is None:
        return 0.0
    s = str(x).strip()
    if s == "" or s.lower() == "nan":
        return 0.0
    s = s.replace(".", "").replace(",", ".")  # BR -> float
    try:
        return float(s)
    except Exception:
        return 0.0


def _to_int_safe(x):
    return int(round(_to_float_safe(x), 0))


def split_csv_like(cell: str):
    if cell is None:
        return []
    s = str(cell).strip()
    if s == "" or s.lower() == "nan":
        return []
    parts = [p.strip() for p in s.split(",")]
    return [p for p in parts if p != ""]


def infer_vendas_columns(df: pd.DataFrame):
    """
    Detecta coluna de código e quantidade em CSV/XLSX de vendas.
    Aceita variações comuns: codigo, Código, SKU, Produto, etc.
    """
    cols = list(df.columns)
    lower_map = {c: str(c).strip().lower() for c in cols}

    code_candidates = []
    qty_candidates = []

    for c in cols:
        lc = lower_map[c]
        if any(k in lc for k in ["codigo", "código", "sku", "cód", "ref", "refer"]):
            code_candidates.append(c)
        if any(k in lc for k in ["quantidade", "qtde", "qtd", "quant", "qte"]):
            qty_candidates.append(c)

    # fallback: primeira coluna como código, segunda como qty
    code_col = code_candidates[0] if code_candidates else (cols[0] if cols else None)
    qty_col = None

    # tenta achar qty col diferente da code
    for cand in qty_candidates:
        if cand != code_col:
            qty_col = cand
            break

    if qty_col is None and len(cols) >= 2:
        qty_col = cols[1]

    return code_col, qty_col


def load_vendas_file(uploaded) -> pd.DataFrame:
    """
    Lê CSV/XLSX com vendas e normaliza para colunas:
      - codigo
      - quantidade
    """
    name = uploaded.name.lower()

    if name.endswith(".csv"):
        raw = pd.read_csv(uploaded, dtype=str).fillna("")
    elif name.endswith(".xlsx") or name.endswith(".xls"):
        raw = pd.read_excel(uploaded, dtype=str).fillna("")
    else:
        raise ValueError("Formato de arquivo não suportado. Use CSV ou XLSX.")

    if raw.empty:
        return pd.DataFrame(columns=["codigo", "quantidade"])

    code_col, qty_col = infer_vendas_columns(raw)

    if code_col is None or qty_col is None:
        raise KeyError("Não consegui detectar as colunas de código e quantidade no arquivo de vendas.")

    vendas = raw[[code_col, qty_col]].copy()
    vendas.columns = ["codigo", "quantidade"]

    vendas["codigo"] = vendas["codigo"].astype(str).str.strip()
    vendas["quantidade"] = vendas["quantidade"].apply(_to_float_safe)

    vendas = vendas[vendas["codigo"] != ""]
    vendas = vendas.groupby("codigo", as_index=False)["quantidade"].sum()
    vendas["quantidade"] = vendas["quantidade"].apply(lambda x: int(round(x, 0)))

    return vendas


# -----------------------------
# Leitura e normalização do estoque + BOMs
# -----------------------------
def normalize_template_estoque(df: pd.DataFrame) -> pd.DataFrame:
    # Esperado: colunas pelo menos "codigo" e "estoque_atual"
    cols = [c.strip().lower() for c in df.columns]
    colmap = {df.columns[i]: cols[i] for i in range(len(df.columns))}
    df2 = df.rename(columns=colmap).copy()

    # tenta localizar colunas
    possible_code = [c for c in df2.columns if "codigo" in c or "sku" in c]
    possible_stock = [c for c in df2.columns if "estoque_atual" in c or ("estoque" in c and "atual" in c) or c == "estoque"]

    if not possible_code:
        raise KeyError("template_estoque: não achei coluna de código (ex: 'codigo').")
    if not possible_stock:
        raise KeyError("template_estoque: não achei coluna de estoque (ex: 'estoque_atual').")

    df2 = df2[[possible_code[0], possible_stock[0]]].copy()
    df2.columns = ["codigo", "estoque_atual"]

    df2["codigo"] = df2["codigo"].astype(str).str.strip()
    df2["estoque_atual"] = df2["estoque_atual"].apply(_to_float_safe)

    df2 = df2[df2["codigo"] != ""]
    df2 = df2.groupby("codigo", as_index=False)["estoque_atual"].sum()

    return df2


def normalize_bom_produto_simples(df: pd.DataFrame) -> pd.DataFrame:
    # Mantém nomes exatamente como você definiu
    needed = [
        "codigo_final",
        "semi_codigo", "semi_qtd",
        "gola_codigo", "gola_qtd",
        "bordado_codigo", "bordado_qtd",
        "extras_codigos", "extras_qtds",
    ]
    got = [c.strip() for c in df.columns]
    if not set(needed).issubset(set(got)):
        raise KeyError(f"bom_produto_simples: colunas esperadas: {needed}")

    df2 = df[needed].copy().fillna("")
    df2["codigo_final"] = df2["codigo_final"].astype(str).str.strip()

    # quantidades como string -> float
    for col in ["semi_qtd", "bordado_qtd"]:
        df2[col] = df2[col].apply(_to_float_safe)

    # gola_qtd e extras_qtds são listas "1,2" etc (string)
    df2["gola_codigo"] = df2["gola_codigo"].astype(str).str.strip()
    df2["gola_qtd"] = df2["gola_qtd"].astype(str).str.strip()

    df2["extras_codigos"] = df2["extras_codigos"].astype(str).str.strip()
    df2["extras_qtds"] = df2["extras_qtds"].astype(str).str.strip()

    return df2[df2["codigo_final"] != ""]


def normalize_bom_kits_conjuntos(df: pd.DataFrame) -> pd.DataFrame:
    needed = ["codigo_final", "componentes_codigos", "componentes_qtds"]
    got = [c.strip() for c in df.columns]
    if not set(needed).issubset(set(got)):
        raise KeyError(f"bom_kits_conjuntos: colunas esperadas: {needed}")

    df2 = df[needed].copy().fillna("")
    df2["codigo_final"] = df2["codigo_final"].astype(str).str.strip()
    df2["componentes_codigos"] = df2["componentes_codigos"].astype(str).str.strip()
    df2["componentes_qtds"] = df2["componentes_qtds"].astype(str).str.strip()

    return df2[df2["codigo_final"] != ""]


# -----------------------------
# Explosão BOM com sua regra suprema
# -----------------------------
class BomEngine:
    def __init__(self, estoque_df, bom_simples_df, bom_kits_df):
        self.estoque = {r["codigo"]: float(r["estoque_atual"]) for _, r in estoque_df.iterrows()}
        self.bom_simples = {r["codigo_final"]: r for _, r in bom_simples_df.iterrows()}
        self.bom_kits = {r["codigo_final"]: r for _, r in bom_kits_df.iterrows()}

        self.insumos_need = {}   # codigo -> {"categoria": "...", "necessario": float}
        self.acao_fabricar = {}  # codigo -> qtd_faltante (float)
        self.faltantes_produtos = {}  # codigo_final -> faltante (int)

    def stock(self, codigo: str) -> float:
        # Estoque negativo é tratado como 0 para decisão de explosão (não atende demanda)
        val = self.estoque.get(codigo, 0.0)
        return max(0.0, float(val))

    def add_insumo(self, codigo: str, categoria: str, qtd: float):
        if not codigo or str(codigo).strip() == "":
            return
        codigo = str(codigo).strip()
        if codigo not in self.insumos_need:
            self.insumos_need[codigo] = {"categoria": categoria, "necessario": 0.0}
        self.insumos_need[codigo]["necessario"] += float(qtd)

    def explode_demanda(self, codigo_final: str, demanda_qty: float):
        codigo_final = str(codigo_final).strip()
        if codigo_final == "" or demanda_qty <= 0:
            return

        disponivel = self.stock(codigo_final)
        faltante = max(0.0, float(demanda_qty) - float(disponivel))

        if faltante <= 0:
            # Regra suprema: tendo estoque suficiente -> não explode
            return

        # registra faltante do produto final (para relatório)
        self.faltantes_produtos[codigo_final] = self.faltantes_produtos.get(codigo_final, 0.0) + faltante

        # explode apenas o faltante
        self._explode_codigo(codigo_final, faltante)

    def _explode_codigo(self, codigo: str, qty_needed: float):
        """
        Explode recursivamente:
        - Se o código existir como kit/conjunto: explode componentes (cada componente passa pela regra de estoque)
        - Se o código existir como produto simples: explode até insumos (Semi/Gola/Bordado/Extras)
        - Se não existir em BOM: trata como "insumo puro" e cai para controle de estoque/ação.
        """
        codigo = str(codigo).strip()
        if codigo == "" or qty_needed <= 0:
            return

        # Antes de explodir qualquer filho: aplica regra no próprio codigo (se for um produto com estoque)
        # -> aqui, quem chama já passou faltante, então não re-checa.

        if codigo in self.bom_kits:
            row = self.bom_kits[codigo]
            comp_codes = split_csv_like(row["componentes_codigos"])
            comp_qtds = split_csv_like(row["componentes_qtds"])

            if len(comp_codes) != len(comp_qtds):
                # Se estiver desalinhado, explode o que conseguir
                min_len = min(len(comp_codes), len(comp_qtds))
                comp_codes = comp_codes[:min_len]
                comp_qtds = comp_qtds[:min_len]

            for cc, cq in zip(comp_codes, comp_qtds):
                cc = str(cc).strip()
                mult = _to_float_safe(cq)
                child_need = qty_needed * mult

                # regra suprema nos componentes:
                disponivel = self.stock(cc)
                child_falt = max(0.0, child_need - disponivel)
                if child_falt <= 0:
                    continue

                # explode componente faltante
                self._explode_codigo(cc, child_falt)

            return

        if codigo in self.bom_simples:
            row = self.bom_simples[codigo]

            # Semi
            semi_code = str(row["semi_codigo"]).strip()
            semi_qtd = _to_float_safe(row["semi_qtd"])
            if semi_code and semi_qtd > 0:
                self.add_insumo(semi_code, "SEMI", qty_needed * semi_qtd)

            # Golas (lista)
            gola_codes = split_csv_like(row["gola_codigo"])
            gola_qtds = split_csv_like(row["gola_qtd"])
            if len(gola_codes) != len(gola_qtds):
                min_len = min(len(gola_codes), len(gola_qtds))
                gola_codes = gola_codes[:min_len]
                gola_qtds = gola_qtds[:min_len]
            for gc, gq in zip(gola_codes, gola_qtds):
                gc = str(gc).strip()
                mult = _to_float_safe(gq)
                if gc and mult > 0:
                    self.add_insumo(gc, "GOLA", qty_needed * mult)

            # Bordado
            bord_code = str(row["bordado_codigo"]).strip()
            bord_qtd = _to_float_safe(row["bordado_qtd"])
            if bord_code and bord_code.lower() != "nan" and bord_code != "" and bord_qtd > 0:
                self.add_insumo(bord_code, "BORDADO", qty_needed * bord_qtd)

            # Extras (lista)
            extra_codes = split_csv_like(row["extras_codigos"])
            extra_qtds = split_csv_like(row["extras_qtds"])
            if len(extra_codes) != len(extra_qtds):
                min_len = min(len(extra_codes), len(extra_qtds))
                extra_codes = extra_codes[:min_len]
                extra_qtds = extra_qtds[:min_len]
            for ec, eq in zip(extra_codes, extra_qtds):
                ec = str(ec).strip()
                mult = _to_float_safe(eq)
                if ec and mult > 0:
                    self.add_insumo(ec, "EXTRA", qty_needed * mult)

            return

        # Se não está em BOM, assume que é um insumo “puro” (ou item sem cadastro de estrutura)
        # e vai para controle de estoque
        self.add_insumo(codigo, "INSUMO", qty_needed)

    def finalize_acoes(self):
        """
        Depois de consolidar insumos_need, calcula faltantes vs estoque e gera lista de FABRICAR.
        """
        for codigo, info in self.insumos_need.items():
            necessario = float(info["necessario"])
            disp = self.stock(codigo)
            falt = max(0.0, necessario - disp)
            if falt > 0:
                self.acao_fabricar[codigo] = self.acao_fabricar.get(codigo, 0.0) + falt

    def build_reports(self):
        self.finalize_acoes()

        # 01_FALTANTES_PRODUTOS
        falt_prod = pd.DataFrame(
            [{"codigo_final": k, "faltante": float(v)} for k, v in self.faltantes_produtos.items()]
        )
        if not falt_prod.empty:
            falt_prod = falt_prod.sort_values("faltante", ascending=False).reset_index(drop=True)

        # 03_INSUMOS
        ins_rows = []
        for codigo, info in self.insumos_need.items():
            necessario = float(info["necessario"])
            estoque_atual = self.stock(codigo)
            faltante = max(0.0, necessario - estoque_atual)

            if faltante <= 0:
                status = "OK"
            elif estoque_atual <= 0:
                status = "FALTA"
            else:
                status = "PARCIAL"

            ins_rows.append(
                {
                    "codigo": codigo,
                    "categoria": info["categoria"],
                    "necessario": round(necessario, 4),
                    "estoque_atual": round(estoque_atual, 4),
                    "faltante": round(faltante, 4),
                    "status": status,
                }
            )
        insumos = pd.DataFrame(ins_rows)
        if not insumos.empty:
            insumos = insumos.sort_values(["status", "faltante"], ascending=[True, False]).reset_index(drop=True)

        # 04_LISTA_ACAO
        ac_rows = []
        for codigo, falt in self.acao_fabricar.items():
            ac_rows.append(
                {
                    "acao": "FABRICAR",
                    "codigo": codigo,
                    "qtd_faltante": round(float(falt), 4),
                    "observacao": "PLATELEIRA ESTOQUE",
                }
            )
        acoes = pd.DataFrame(ac_rows)
        if not acoes.empty:
            acoes = acoes.sort_values("qtd_faltante", ascending=False).reset_index(drop=True)

        return falt_prod, insumos, acoes


def build_excel_bytes(falt_prod, insumos, acoes) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        if falt_prod is None or falt_prod.empty:
            pd.DataFrame(columns=["codigo_final", "faltante"]).to_excel(writer, sheet_name="01_FALTANTES_PRODUTOS", index=False)
        else:
            falt_prod.to_excel(writer, sheet_name="01_FALTANTES_PRODUTOS", index=False)

        if insumos is None or insumos.empty:
            pd.DataFrame(columns=["codigo", "categoria", "necessario", "estoque_atual", "faltante", "status"]).to_excel(writer, sheet_name="03_INSUMOS", index=False)
        else:
            insumos.to_excel(writer, sheet_name="03_INSUMOS", index=False)

        if acoes is None or acoes.empty:
            pd.DataFrame(columns=["acao", "codigo", "qtd_faltante", "observacao"]).to_excel(writer, sheet_name="04_LISTA_ACAO", index=False)
        else:
            acoes.to_excel(writer, sheet_name="04_LISTA_ACAO", index=False)

    output.seek(0)
    return output.read()


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title=APP_TITLE, layout="wide")

st.markdown(
    f"""
    <div style="background:linear-gradient(180deg,#244c87,#1c3f73);padding:22px;border-radius:16px;color:white;">
      <div style="font-size:34px;font-weight:800;text-align:center;">{APP_TITLE}</div>
      <div style="text-align:center;opacity:0.85;margin-top:6px;">"Se parar para sentir o perfume das rosas, vem um caminhão e te atropela."</div>
    </div>
    """,
    unsafe_allow_html=True,
)

tabs = st.tabs(["📦 Explosão BOM (Produção)", "⚙️ Configuração / Diagnóstico"])

# -----------------------------
# TAB 2 - Config
# -----------------------------
with tabs[1]:
    st.subheader("Configuração de Fonte de Dados")

    cfg = load_config()
    if "source_type" not in cfg:
        cfg["source_type"] = "gsheets"

    source_type = st.radio(
        "Como ler a planilha template_estoque?",
        ["Google Sheets (recomendado)", "Upload de Excel (template_estoque + BOMs)"],
        index=0 if cfg["source_type"] == "gsheets" else 1,
        horizontal=True,
    )
    cfg["source_type"] = "gsheets" if source_type.startswith("Google") else "excel"

    st.divider()

    if cfg["source_type"] == "gsheets":
        st.caption("Informe o Spreadsheet ID e os GIDs de cada aba. Depois de validar, o app **salva automaticamente** e você não preenche mais.")
        spreadsheet_id = st.text_input(
            "Spreadsheet ID (entre /d/ e /edit)",
            value=cfg.get("spreadsheet_id", ""),
        )
        gid_template = st.text_input(
            "GID da aba template_estoque",
            value=cfg.get("gid_template_estoque", ""),
        )
        gid_simples = st.text_input(
            "GID da aba bom_produto_simples",
            value=cfg.get("gid_bom_produto_simples", ""),
        )
        gid_kits = st.text_input(
            "GID da aba bom_kits_conjuntos",
            value=cfg.get("gid_bom_kits_conjuntos", ""),
        )

        colA, colB = st.columns([1, 3])
        with colA:
            validate = st.button("🔎 Validar leitura agora", use_container_width=True)

        if validate:
            try:
                df_template = read_google_sheet_csv(spreadsheet_id, gid_template)
                df_simples = read_google_sheet_csv(spreadsheet_id, gid_simples)
                df_kits = read_google_sheet_csv(spreadsheet_id, gid_kits)

                # Normaliza e testa
                template_ok = normalize_template_estoque(df_template)
                simples_ok = normalize_bom_produto_simples(df_simples)
                kits_ok = normalize_bom_kits_conjuntos(df_kits)

                # salva config (AQUI está o “NÃO PREENCHER TODA HORA”)
                cfg["spreadsheet_id"] = spreadsheet_id.strip()
                cfg["gid_template_estoque"] = normalize_gid(gid_template)
                cfg["gid_bom_produto_simples"] = normalize_gid(gid_simples)
                cfg["gid_bom_kits_conjuntos"] = normalize_gid(gid_kits)
                cfg["last_validated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                save_config(cfg)

                st.success("Leitura OK ✅ Configuração salva automaticamente. Você não precisa preencher de novo.")
                st.write("template_estoque (amostra):")
                st.dataframe(template_ok.head(10), use_container_width=True)
                st.write("bom_produto_simples (amostra):")
                st.dataframe(simples_ok.head(10), use_container_width=True)
                st.write("bom_kits_conjuntos (amostra):")
                st.dataframe(kits_ok.head(10), use_container_width=True)

            except Exception as e:
                st.error(f"Erro ao ler/validar: {type(e).__name__}: {e}")
                st.info("Dica: no link do Google Sheets aparece `gid=...` para cada aba. Cole só o número ou `gid=123`.")

    else:
        st.warning("Modo Excel ainda não implementado neste build (você está usando Google Sheets).")

    st.divider()
    st.caption("Config atual carregada do arquivo:")
    st.code(json.dumps(load_config(), ensure_ascii=False, indent=2), language="json")


# -----------------------------
# TAB 1 - Explosão
# -----------------------------
with tabs[0]:
    st.subheader("Explosão BOM (Produção)")

    cfg = load_config()
    if not cfg or cfg.get("source_type") != "gsheets":
        st.warning("Configure a fonte de dados em **Configuração / Diagnóstico** e valide a leitura.")
        st.stop()

    st.info("Regra suprema: tem estoque do código pai suficiente → não explode. Se faltar, explode **só o faltante** até insumos.")

    up = st.file_uploader("Upload vendas (CSV/XLSX com colunas codigo / quantidade)", type=["csv", "xlsx", "xls"])
    if up is None:
        st.stop()

    try:
        vendas = load_vendas_file(up)
    except Exception as e:
        st.error(f"Falha ao ler arquivo de vendas: {type(e).__name__}: {e}")
        st.stop()

    with st.spinner("Lendo planilhas do Google Sheets..."):
        df_template = read_google_sheet_csv(cfg["spreadsheet_id"], cfg["gid_template_estoque"])
        df_simples = read_google_sheet_csv(cfg["spreadsheet_id"], cfg["gid_bom_produto_simples"])
        df_kits = read_google_sheet_csv(cfg["spreadsheet_id"], cfg["gid_bom_kits_conjuntos"])

        estoque_df = normalize_template_estoque(df_template)
        bom_simples_df = normalize_bom_produto_simples(df_simples)
        bom_kits_df = normalize_bom_kits_conjuntos(df_kits)

    st.write("Vendas (consolidado):")
    st.dataframe(vendas, use_container_width=True)

    if st.button("🚀 Explodir BOM e gerar relatório", use_container_width=True):
        engine = BomEngine(estoque_df, bom_simples_df, bom_kits_df)

        for _, r in vendas.iterrows():
            engine.explode_demanda(r["codigo"], float(r["quantidade"]))

        falt_prod, insumos, acoes = engine.build_reports()

        st.subheader("01_FALTANTES_PRODUTOS")
        st.dataframe(falt_prod if falt_prod is not None else pd.DataFrame(), use_container_width=True)

        st.subheader("03_INSUMOS")
        st.dataframe(insumos if insumos is not None else pd.DataFrame(), use_container_width=True)

        st.subheader("04_LISTA_ACAO")
        st.dataframe(acoes if acoes is not None else pd.DataFrame(), use_container_width=True)

        xbytes = build_excel_bytes(falt_prod, insumos, acoes)
        fname = f"relatorio_bom_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        st.download_button(
            "📥 Baixar Relatório Excel",
            data=xbytes,
            file_name=fname,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
