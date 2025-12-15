import io
import re
import json
import time
import pandas as pd
import streamlit as st

# Google APIs
import gspread
from google.oauth2.service_account import Credentials


# =========================
# Helpers: Secrets / Config
# =========================
def get_app_config_defaults():
    """
    Puxa defaults do st.secrets, se existirem.
    Espera:
      [app_config]
      spreadsheet_id = "..."
      gid_template_estoque = "..."
      gid_bom_produto_simples = "..."
      gid_bom_kits_conjuntos = "..."
    """
    cfg = {}
    try:
        cfg = dict(st.secrets.get("app_config", {}))
    except Exception:
        cfg = {}

    def clean_gid(x: str) -> str:
        x = str(x or "").strip()
        x = x.replace("gid=", "").strip()
        return x

    return {
        "spreadsheet_id": str(cfg.get("spreadsheet_id", "")).strip(),
        "gid_template_estoque": clean_gid(cfg.get("gid_template_estoque", "")),
        "gid_bom_produto_simples": clean_gid(cfg.get("gid_bom_produto_simples", "")),
        "gid_bom_kits_conjuntos": clean_gid(cfg.get("gid_bom_kits_conjuntos", "")),
    }


def get_gspread_client():
    """
    Lê credenciais do Service Account em st.secrets.
    Você pode ter colocado como chaves soltas (private_key, client_email, etc)
    OU como JSON completo dentro de alguma chave.
    """
    # Escopos necessários para ler planilhas
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    # Caso você queira no futuro adicionar botão de "jogar itens na planilha",
    # troque por:
    # scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

    # 1) Tentativa: chaves no root do secrets (como você mostrou no print)
    required_keys = [
        "type", "project_id", "private_key_id", "private_key",
        "client_email", "client_id",
        "auth_uri", "token_uri",
        "auth_provider_x509_cert_url", "client_x509_cert_url"
    ]
    if all(k in st.secrets for k in required_keys):
        info = {k: st.secrets[k] for k in required_keys}
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        return gspread.authorize(creds)

    # 2) Tentativa: JSON inteiro guardado em uma chave
    for k, v in st.secrets.items():
        if isinstance(v, str) and ("service_account" in v or '"client_email"' in v):
            try:
                info = json.loads(v)
                creds = Credentials.from_service_account_info(info, scopes=scopes)
                return gspread.authorize(creds)
            except Exception:
                pass

    raise RuntimeError(
        "Não encontrei credenciais válidas do Service Account em st.secrets. "
        "Coloque as chaves do JSON do Google (type, private_key, client_email etc) em Secrets."
    )


def gid_to_sheet_name(spreadsheet, gid: str) -> str:
    """
    Converte gid -> sheet title.
    (Sem isso, ficamos dependentes do nome exato da aba.)
    """
    gid = str(gid).strip()
    if gid == "":
        raise ValueError("GID vazio.")

    try:
        meta = spreadsheet.fetch_sheet_metadata()
        for s in meta.get("sheets", []):
            props = s.get("properties", {})
            if str(props.get("sheetId")) == gid:
                return props.get("title")
    except Exception as e:
        raise RuntimeError(f"Falha ao resolver GID->Nome da aba. Erro: {e}")

    raise ValueError(f"Não achei nenhuma aba com gid={gid} nesse Spreadsheet.")


@st.cache_data(ttl=60, show_spinner=False)
def load_sheet_as_df(spreadsheet_id: str, gid: str) -> pd.DataFrame:
    gc = get_gspread_client()
    sh = gc.open_by_key(spreadsheet_id)
    title = gid_to_sheet_name(sh, gid)
    ws = sh.worksheet(title)
    values = ws.get_all_values()
    if not values or len(values) < 2:
        return pd.DataFrame()

    header = values[0]
    rows = values[1:]
    df = pd.DataFrame(rows, columns=header)
    # remove colunas vazias
    df = df.loc[:, [c for c in df.columns if str(c).strip() != ""]]
    return df


# =========================
# Parsing (BOM cells)
# =========================
def split_csv_like(x):
    if x is None:
        return []
    s = str(x).strip()
    if s == "" or s.lower() == "nan":
        return []
    # aceita separador ","
    parts = [p.strip() for p in s.split(",")]
    return [p for p in parts if p != ""]


def parse_number_list(x):
    """
    Converte "1,2, 3" -> [1.0, 2.0, 3.0]
    Aceita também "1" -> [1.0]
    """
    parts = split_csv_like(x)
    out = []
    for p in parts:
        p2 = p.replace(" ", "").replace(",", ".")
        # Se vier "1.2.3" evita explodir
        try:
            out.append(float(p2))
        except Exception:
            # tenta extrair número
            m = re.findall(r"[-+]?\d*\.?\d+", p2)
            out.append(float(m[0]) if m else 0.0)
    return out


def safe_float(x, default=0.0):
    if x is None:
        return default
    s = str(x).strip()
    if s == "" or s.lower() == "nan":
        return default
    s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        m = re.findall(r"[-+]?\d*\.?\d+", s)
        return float(m[0]) if m else default


# =========================
# Sales file normalization
# =========================
def read_sales_file(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    elif name.endswith(".xlsx") or name.endswith(".xls"):
        df = pd.read_excel(uploaded_file)
    else:
        raise ValueError("Formato inválido. Use CSV ou XLSX.")

    # normaliza colunas
    df.columns = [str(c).strip().lower() for c in df.columns]

    # tenta achar "codigo" e "quantidade"
    code_candidates = ["codigo", "código", "sku", "produto", "cod", "code"]
    qty_candidates = ["quantidade", "qtd", "qtde", "qty", "quant", "qtd_vendida", "vendido"]

    code_col = next((c for c in df.columns if c in code_candidates), None)
    qty_col = next((c for c in df.columns if c in qty_candidates), None)

    if code_col is None or qty_col is None:
        # tentativa por contains
        for c in df.columns:
            if code_col is None and "cod" in c:
                code_col = c
            if qty_col is None and ("qtd" in c or "quant" in c):
                qty_col = c

    if code_col is None or qty_col is None:
        raise KeyError("Não encontrei colunas de vendas. Preciso de colunas: codigo / quantidade.")

    df = df[[code_col, qty_col]].copy()
    df.columns = ["codigo", "quantidade"]

    df["codigo"] = df["codigo"].astype(str).str.strip()
    df["quantidade"] = df["quantidade"].apply(lambda x: safe_float(x, 0)).astype(float)

    df = df[df["codigo"].str.len() > 0]
    df = df[df["quantidade"] > 0]

    # agrupa
    df = df.groupby("codigo", as_index=False)["quantidade"].sum()
    df["quantidade"] = df["quantidade"].round(3)
    return df


# =========================
# Stock / BOM indexing
# =========================
def build_stock_map(df_template: pd.DataFrame) -> dict:
    """
    Espera colunas: codigo, estoque_atual
    """
    if df_template.empty:
        return {}

    cols = [c.lower().strip() for c in df_template.columns]
    df_template.columns = cols

    if "codigo" not in df_template.columns or "estoque_atual" not in df_template.columns:
        # tenta variações
        possible_code = next((c for c in df_template.columns if "codigo" in c), None)
        possible_stock = next((c for c in df_template.columns if "estoque" in c), None)
        if possible_code and possible_stock:
            df_template = df_template.rename(columns={possible_code: "codigo", possible_stock: "estoque_atual"})
        else:
            raise KeyError("Aba template_estoque precisa ter colunas: codigo e estoque_atual.")

    df = df_template.copy()
    df["codigo"] = df["codigo"].astype(str).str.strip()
    df["estoque_atual"] = df["estoque_atual"].apply(lambda x: safe_float(x, 0)).astype(float)

    stock = {}
    for _, r in df.iterrows():
        code = r["codigo"]
        qty = float(r["estoque_atual"])
        stock[code] = qty

    return stock


def index_bom_simples(df_simple: pd.DataFrame) -> dict:
    """
    Retorna dict: codigo_final -> row dict
    """
    if df_simple.empty:
        return {}
    df = df_simple.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    required = ["codigo_final", "semi_codigo", "semi_qtd", "gola_codigo", "gola_qtd", "bordado_codigo", "bordado_qtd", "extras_codigos", "extras_qtds"]
    for col in required:
        if col not in df.columns:
            # aceita ausência de extras/bordado
            if col in ["bordado_codigo", "bordado_qtd", "extras_codigos", "extras_qtds"]:
                df[col] = ""
            else:
                raise KeyError(f"Aba bom_produto_simples precisa da coluna: {col}")

    out = {}
    for _, r in df.iterrows():
        code = str(r["codigo_final"]).strip()
        if not code or code.lower() == "nan":
            continue
        out[code] = dict(r)
    return out


def index_bom_kits(df_kits: pd.DataFrame) -> dict:
    """
    Retorna dict: codigo_final -> (componentes_codigos list, componentes_qtds list)
    """
    if df_kits.empty:
        return {}
    df = df_kits.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    required = ["codigo_final", "componentes_codigos", "componentes_qtds"]
    for col in required:
        if col not in df.columns:
            raise KeyError(f"Aba bom_kits_conjuntos precisa da coluna: {col}")

    out = {}
    for _, r in df.iterrows():
        code = str(r["codigo_final"]).strip()
        if not code or code.lower() == "nan":
            continue
        comps = split_csv_like(r["componentes_codigos"])
        qtds = parse_number_list(r["componentes_qtds"])
        # se qtds vier menor, completa com 1
        if len(qtds) < len(comps):
            qtds = qtds + [1.0] * (len(comps) - len(qtds))
        out[code] = (comps, qtds[: len(comps)])
    return out


# =========================
# BOM Explosion logic
# =========================
def available_stock(stock_map: dict, code: str) -> float:
    """
    Estoque "usável": se negativo, considera 0.
    """
    q = float(stock_map.get(code, 0.0))
    return max(0.0, q)


def explode_product(
    code: str,
    qty_needed: float,
    stock_map: dict,
    bom_simple_idx: dict,
    bom_kits_idx: dict,
    req_insumos: dict,
    debug_rows: list,
    missing_bom: dict,
    visited_stack=None
):
    """
    Explode BOM para produzir qty_needed unidades do 'code' (faltante).
    Regra: aqui já assumimos que precisa produzir qty_needed.
    Para KIT: explode em componentes, mas só explode componente se ele não tiver estoque suficiente.
    Para simples: explode em semi/gola/bordado/extras.
    Se code não estiver em nenhuma BOM: entra em missing_bom.
    """
    if visited_stack is None:
        visited_stack = []

    # evita loop infinito por cadastro errado
    if code in visited_stack:
        missing_bom[code] = missing_bom.get(code, 0.0) + qty_needed
        debug_rows.append({"tipo": "loop_bom", "codigo": code, "qtd": qty_needed, "detalhe": "Loop detectado"})
        return

    visited_stack = visited_stack + [code]

    # 1) Se for KIT/CONJUNTO
    if code in bom_kits_idx:
        comps, qtds = bom_kits_idx[code]
        debug_rows.append({"tipo": "explode_kit", "codigo": code, "qtd": qty_needed, "detalhe": f"{len(comps)} comps"})
        for comp_code, comp_per in zip(comps, qtds):
            comp_need = float(qty_needed) * float(comp_per)
            comp_have = available_stock(stock_map, comp_code)
            comp_falt = max(0.0, comp_need - comp_have)

            debug_rows.append({
                "tipo": "kit_comp",
                "codigo_pai": code,
                "codigo": comp_code,
                "precisa": comp_need,
                "tem": comp_have,
                "faltante": comp_falt
            })

            # Se tem componente suficiente, NÃO explode
            if comp_falt <= 0:
                continue

            # Se falta componente, explode o componente (recursivo)
            explode_product(
                comp_code, comp_falt, stock_map, bom_simple_idx, bom_kits_idx,
                req_insumos, debug_rows, missing_bom, visited_stack
            )
        return

    # 2) Se for simples com insumos
    if code in bom_simple_idx:
        r = bom_simple_idx[code]

        semi_code = str(r.get("semi_codigo", "")).strip()
        semi_qtd = safe_float(r.get("semi_qtd", 0), 0)

        gola_codes = split_csv_like(r.get("gola_codigo", ""))
        gola_qtds = parse_number_list(r.get("gola_qtd", ""))

        bord_code = str(r.get("bordado_codigo", "")).strip()
        bord_qtd = safe_float(r.get("bordado_qtd", 0), 0)

        extra_codes = split_csv_like(r.get("extras_codigos", ""))
        extra_qtds = parse_number_list(r.get("extras_qtds", ""))

        # Ajustes de tamanhos
        if len(gola_qtds) < len(gola_codes):
            gola_qtds = gola_qtds + [1.0] * (len(gola_codes) - len(gola_qtds))
        if len(extra_qtds) < len(extra_codes):
            extra_qtds = extra_qtds + [1.0] * (len(extra_codes) - len(extra_qtds))

        debug_rows.append({"tipo": "explode_simples", "codigo": code, "qtd": qty_needed, "detalhe": "insumos"})

        def add_req(insumo_code: str, per_unit: float, categoria: str):
            insumo_code = str(insumo_code).strip()
            if not insumo_code or insumo_code.lower() == "nan":
                return
            total = float(qty_needed) * float(per_unit)
            key = (categoria, insumo_code)
            req_insumos[key] = req_insumos.get(key, 0.0) + total

        # semi
        add_req(semi_code, semi_qtd, "SEMI")

        # gola
        for gc, gq in zip(gola_codes, gola_qtds):
            add_req(gc, gq, "GOLA")

        # bordado
        if bord_code and bord_code.lower() != "nan":
            add_req(bord_code, bord_qtd, "BORDADO")

        # extras
        for ec, eq in zip(extra_codes, extra_qtds):
            add_req(ec, eq, "EXTRA")

        return

    # 3) Sem BOM cadastrada
    missing_bom[code] = missing_bom.get(code, 0.0) + qty_needed
    debug_rows.append({"tipo": "sem_bom", "codigo": code, "qtd": qty_needed, "detalhe": "Não cadastrado em BOM"})


# =========================
# Report builder
# =========================
def build_reports(vendas_df, stock_map, bom_simple_idx, bom_kits_idx):
    debug_rows = []
    req_insumos = {}  # (categoria, codigo) -> requerido
    missing_bom = {}  # codigo -> qtd

    # 1) Faltantes de produto final (regra: se tem estoque suficiente, não explode)
    faltantes_rows = []
    for _, r in vendas_df.iterrows():
        code = str(r["codigo"]).strip()
        demanda = float(r["quantidade"])
        tem = available_stock(stock_map, code)
        falt = max(0.0, demanda - tem)

        faltantes_rows.append({
            "codigo": code,
            "demanda": demanda,
            "estoque_atual": tem,
            "faltante": falt
        })

        # explode só o faltante
        if falt > 0:
            explode_product(
                code=code,
                qty_needed=falt,
                stock_map=stock_map,
                bom_simple_idx=bom_simple_idx,
                bom_kits_idx=bom_kits_idx,
                req_insumos=req_insumos,
                debug_rows=debug_rows,
                missing_bom=missing_bom
            )

    df_faltantes = pd.DataFrame(faltantes_rows)
    df_faltantes = df_faltantes.sort_values(["faltante", "demanda"], ascending=[False, False]).reset_index(drop=True)

    # 2) Insumos agregados
    ins_rows = []
    for (cat, ins_code), req in req_insumos.items():
        tem = available_stock(stock_map, ins_code)
        falt = max(0.0, float(req) - float(tem))
        if falt <= 0:
            status = "OK"
        elif tem > 0:
            status = "PARCIAL"
        else:
            status = "FALTANDO"

        ins_rows.append({
            "categoria": cat,
            "codigo": ins_code,
            "requerido": float(req),
            "estoque_atual": tem,
            "faltante": falt,
            "status": status
        })

    df_insumos = pd.DataFrame(ins_rows)
    if not df_insumos.empty:
        df_insumos = df_insumos.sort_values(["status", "faltante", "requerido"], ascending=[True, False, False]).reset_index(drop=True)

    # 3) Lista de ação (FABRICAR)
    acao_rows = []

    # insumos faltantes
    if not df_insumos.empty:
        for _, r in df_insumos.iterrows():
            if float(r["faltante"]) > 0:
                acao_rows.append({
                    "acao": "FABRICAR",
                    "tipo": "INSUMO",
                    "categoria": r["categoria"],
                    "codigo": r["codigo"],
                    "quantidade": float(r["faltante"]),
                    "observacao": "PLATELEIRA ESTOQUE"
                })

    # produtos sem BOM cadastrada
    for code, qty in missing_bom.items():
        acao_rows.append({
            "acao": "CADASTRAR_BOM",
            "tipo": "PRODUTO",
            "categoria": "N/A",
            "codigo": code,
            "quantidade": float(qty),
            "observacao": "Sem BOM cadastrada (bom_produto_simples / bom_kits_conjuntos)"
        })

    df_acao = pd.DataFrame(acao_rows)
    if not df_acao.empty:
        df_acao = df_acao.sort_values(["acao", "tipo", "quantidade"], ascending=[True, True, False]).reset_index(drop=True)

    df_debug = pd.DataFrame(debug_rows)

    return df_faltantes, df_insumos, df_acao, df_debug


def to_excel_bytes(dfs: dict) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in dfs.items():
            if df is None:
                continue
            if isinstance(df, pd.DataFrame):
                df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
    return output.getvalue()


# =========================
# UI
# =========================
st.set_page_config(page_title="Cockpit de Controle — Silva Holding", layout="wide")

st.markdown(
    """
    <div style="background: linear-gradient(90deg,#1e3a8a,#0f172a); padding: 22px; border-radius: 14px; margin-bottom: 14px;">
      <div style="color: #fff; font-size: 34px; font-weight: 800; text-align: center;">
        COCKPIT DE CONTROLE — SILVA HOLDING
      </div>
      <div style="color: #dbeafe; text-align: center; margin-top: 6px;">
        "Se parar para sentir o perfume das rosas, vem um caminhão e te atropela."
      </div>
    </div>
    """,
    unsafe_allow_html=True
)

defaults = get_app_config_defaults()

tab1, tab2 = st.tabs(["📦 Explosão BOM (Produção)", "⚙️ Configuração / Diagnóstico"])

with tab2:
    st.subheader("Configuração de Fonte de Dados")

    st.caption("✅ Dica: se você já colocou `app_config` em Secrets, isso fica preenchido automaticamente. Não é pra você sofrer todo dia.")

    fonte = st.radio("Como ler a planilha template_estoque?", ["Google Sheets (recomendado)", "Upload de Excel (template_estoque + BOMs)"], index=0)

    if fonte == "Google Sheets (recomendado)":
        spreadsheet_id = st.text_input("Spreadsheet ID (entre /d/ e /edit)", value=defaults["spreadsheet_id"])
        gid_template_estoque = st.text_input("GID da aba template_estoque", value=defaults["gid_template_estoque"])
        gid_bom_produto_simples = st.text_input("GID da aba bom_produto_simples", value=defaults["gid_bom_produto_simples"])
        gid_bom_kits_conjuntos = st.text_input("GID da aba bom_kits_conjuntos", value=defaults["gid_bom_kits_conjuntos"])

        st.divider()
        st.markdown("### Teste rápido de leitura (sem explosão)")

        if st.button("🔎 Validar leitura agora"):
            try:
                df_template = load_sheet_as_df(spreadsheet_id, gid_template_estoque)
                df_simple = load_sheet_as_df(spreadsheet_id, gid_bom_produto_simples)
                df_kits = load_sheet_as_df(spreadsheet_id, gid_bom_kits_conjuntos)

                st.success("Leitura OK ✅")

                st.markdown("**template_estoque (amostra):**")
                st.dataframe(df_template.head(20), use_container_width=True)

                st.markdown("**bom_produto_simples (amostra):**")
                st.dataframe(df_simple.head(20), use_container_width=True)

                st.markdown("**bom_kits_conjuntos (amostra):**")
                st.dataframe(df_kits.head(20), use_container_width=True)

                st.info("✅ Se isso passou, você NÃO precisa preencher toda hora. Está vindo do Secrets.")

            except Exception as e:
                st.error(f"Erro ao ler/validar: {e}")

    else:
        st.warning("Modo Upload de Excel ainda não implementado aqui (porque seu padrão ideal é Google Sheets).")

with tab1:
    st.subheader("Explosão BOM para Produção")
    st.caption("Regra suprema: se tem estoque suficiente do produto final → não explode. Se faltar → explode só o faltante até insumos.")

    st.markdown("### 1) Carregar vendas (CSV/XLSX com colunas codigo/quantidade)")
    vendas_file = st.file_uploader("Upload vendas (CSV/XLSX com colunas codigo / quantidade)", type=["csv", "xlsx", "xls"])

    st.markdown("### 2) Fonte dos dados (Google Sheets)")
    spreadsheet_id = st.text_input("Spreadsheet ID", value=defaults["spreadsheet_id"], key="prod_spreadsheet_id")
    gid_template_estoque = st.text_input("GID template_estoque", value=defaults["gid_template_estoque"], key="prod_gid_template")
    gid_bom_produto_simples = st.text_input("GID bom_produto_simples", value=defaults["gid_bom_produto_simples"], key="prod_gid_simple")
    gid_bom_kits_conjuntos = st.text_input("GID bom_kits_conjuntos", value=defaults["gid_bom_kits_conjuntos"], key="prod_gid_kits")

    st.divider()

    if vendas_file is None:
        st.info("Suba o arquivo de vendas para eu explodir a BOM.")
        st.stop()

    try:
        vendas_df = read_sales_file(vendas_file)
    except Exception as e:
        st.error(f"Erro lendo arquivo de vendas: {e}")
        st.stop()

    if vendas_df.empty:
        st.warning("Arquivo de vendas veio vazio ou sem quantidades > 0.")
        st.stop()

    with st.spinner("Lendo planilhas do Google Sheets..."):
        try:
            df_template = load_sheet_as_df(spreadsheet_id, gid_template_estoque)
            df_simple = load_sheet_as_df(spreadsheet_id, gid_bom_produto_simples)
            df_kits = load_sheet_as_df(spreadsheet_id, gid_bom_kits_conjuntos)
        except Exception as e:
            st.error(f"Falha ao ler Google Sheets: {e}")
            st.stop()

    try:
        stock_map = build_stock_map(df_template)
        bom_simple_idx = index_bom_simples(df_simple)
        bom_kits_idx = index_bom_kits(df_kits)
    except Exception as e:
        st.error(f"Erro preparando índices: {e}")
        st.stop()

    st.markdown("### Vendas (agrupadas)")
    st.dataframe(vendas_df, use_container_width=True, height=260)

    if st.button("🔥 Gerar Explosão BOM (Produção)"):
        with st.spinner("Explodindo BOM..."):
            df_faltantes, df_insumos, df_acao, df_debug = build_reports(
                vendas_df=vendas_df,
                stock_map=stock_map,
                bom_simple_idx=bom_simple_idx,
                bom_kits_idx=bom_kits_idx
            )

        st.success("Explosão concluída ✅")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("### 01) Faltantes de produto final")
            st.dataframe(df_faltantes, use_container_width=True, height=320)

        with c2:
            st.markdown("### 04) Lista de ação")
            st.dataframe(df_acao, use_container_width=True, height=320)

        st.markdown("### 03) Insumos requeridos (até nível de Semi / Gola / Bordado / Extras)")
        st.dataframe(df_insumos, use_container_width=True, height=360)

        with st.expander("99) Debug (para caçar erro de lógica)"):
            st.dataframe(df_debug, use_container_width=True, height=420)

        # Download Excel
        report_bytes = to_excel_bytes({
            "01_FALTANTES_PRODUTOS": df_faltantes,
            "03_INSUMOS": df_insumos,
            "04_LISTA_ACAO": df_acao,
            "99_DEBUG": df_debug
        })

        ts = time.strftime("%Y%m%d_%H%M%S")
        st.download_button(
            label="📥 Baixar relatório (Excel)",
            data=report_bytes,
            file_name=f"relatorio_bom_{ts}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        st.info("Observação: Estoques negativos em template_estoque são tratados como 0 (disponível = 0).")
