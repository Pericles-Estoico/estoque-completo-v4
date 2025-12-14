import streamlit as st
import pandas as pd
import numpy as np
import re
import unicodedata
from datetime import datetime
from io import BytesIO

st.set_page_config(page_title="Cockpit — Explosão BOM (Produção)", layout="wide")

# =========================
# Helpers
# =========================
def strip_accents(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))

def norm_col(c: str) -> str:
    c = strip_accents(c).lower().strip()
    c = re.sub(r"\s+", "_", c)
    c = re.sub(r"[^a-z0-9_]", "", c)
    return c

def parse_gid(raw: str) -> str:
    if raw is None:
        return ""
    raw = str(raw).strip()
    raw = raw.replace("gid=", "").strip()
    raw = re.sub(r"[^\d]", "", raw)
    return raw

def safe_str(x):
    if pd.isna(x):
        return ""
    return str(x).strip()

def split_csv_like(s: str):
    s = safe_str(s)
    if not s:
        return []
    return [i.strip() for i in s.split(",") if i.strip()]

def split_nums_like(s: str):
    s = safe_str(s)
    if not s:
        return []
    out = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part.replace(",", ".")))
        except:
            # se vier lixo, vira 0
            out.append(0.0)
    return out

def to_int_safe(x):
    try:
        return int(round(float(x)))
    except:
        return 0

def bytes_xlsx(sheets: dict) -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
    return bio.getvalue()

# =========================
# Persistência por URL (não pedir toda hora)
# =========================
query = st.query_params

def get_q(name, default=""):
    v = query.get(name)
    if v is None:
        return default
    if isinstance(v, list):
        return v[0] if v else default
    return v

# Defaults (puxa da URL, se existir)
DEFAULT_SPREADSHEET_ID = get_q("sid", "")
DEFAULT_GID_TEMPLATE = get_q("gid_template", "")
DEFAULT_GID_BOM_SIMPLES = get_q("gid_simples", "")
DEFAULT_GID_BOM_KITS = get_q("gid_kits", "")

# =========================
# UI - navegação
# =========================
tab1, tab2 = st.tabs(["📦 Explosão BOM (Produção)", "⚙️ Configuração / Diagnóstico"])

with tab2:
    st.subheader("Configuração de Fonte de Dados")

    fonte = st.radio("Como ler a planilha?", ["Google Sheets (recomendado)", "Upload de Excel (template_estoque + BOMs)"], horizontal=True)

    cfg_col1, cfg_col2, cfg_col3 = st.columns(3)
    with cfg_col1:
        spreadsheet_id = st.text_input("Spreadsheet ID (entre /d/ e /edit)", value=DEFAULT_SPREADSHEET_ID, placeholder="Ex: 1PpiMQingHf4llA03BiPIuPJPIZqul4grRU_emWDEK1o")
        gid_template = st.text_input("GID da aba template_estoque", value=DEFAULT_GID_TEMPLATE, placeholder="Ex: 1456159896")
    with cfg_col2:
        gid_simples = st.text_input("GID da aba bom_produto_simples", value=DEFAULT_GID_BOM_SIMPLES, placeholder="Ex: 140150541")
    with cfg_col3:
        gid_kits = st.text_input("GID da aba bom_kits_conjuntos", value=DEFAULT_GID_BOM_KITS, placeholder="Ex: 1285786936")

    # limpa gid=
    gid_template = parse_gid(gid_template)
    gid_simples = parse_gid(gid_simples)
    gid_kits = parse_gid(gid_kits)

    # botão salvar (joga pra URL)
    if st.button("💾 Salvar configuração (não pedir mais)", use_container_width=True):
        st.query_params["sid"] = spreadsheet_id
        st.query_params["gid_template"] = gid_template
        st.query_params["gid_simples"] = gid_simples
        st.query_params["gid_kits"] = gid_kits
        st.success("Configuração salva. Agora ela fica gravada na URL do seu navegador.")

    st.markdown("---")
    st.subheader("Como achar o Spreadsheet ID e o GID")

    st.markdown(
        """
**Spreadsheet ID:** é o trecho do link entre `/d/` e `/edit`  
Exemplo:  
`https://docs.google.com/spreadsheets/d/SEU_ID_AQUI/edit?gid=...`

**GID:** é o número que aparece no final do link quando você clica na aba  
Exemplo:  
`.../edit?gid=1456159896` → o GID é `1456159896` (sem escrever `gid=` no campo, mas se colar com `gid=` eu limpo automaticamente).
"""
    )

    st.markdown("---")
    st.subheader("Teste rápido de leitura (sem explosão)")

    @st.cache_data(show_spinner=False, ttl=300)
    def read_google_sheet(spreadsheet_id: str, gid: str) -> pd.DataFrame:
        # leitura por CSV export público (funciona se a planilha estiver acessível)
        # se estiver privada, vai dar erro 400/403
        url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"
        return pd.read_csv(url)

    def normalize_df_columns(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.columns = [norm_col(c) for c in df.columns]
        return df

    if st.button("🔎 Validar leitura agora"):
        try:
            if not spreadsheet_id or not gid_template or not gid_simples or not gid_kits:
                st.error("Preencha Spreadsheet ID e os 3 GIDs.")
            else:
                df_t = read_google_sheet(spreadsheet_id, gid_template)
                df_s = read_google_sheet(spreadsheet_id, gid_simples)
                df_k = read_google_sheet(spreadsheet_id, gid_kits)

                df_t = normalize_df_columns(df_t)
                df_s = normalize_df_columns(df_s)
                df_k = normalize_df_columns(df_k)

                st.success("Leitura OK ✅")

                st.write("template_estoque (amostra):")
                st.dataframe(df_t.head(10), use_container_width=True)

                st.write("bom_produto_simples (amostra):")
                st.dataframe(df_s.head(10), use_container_width=True)

                st.write("bom_kits_conjuntos (amostra):")
                st.dataframe(df_k.head(10), use_container_width=True)

        except Exception as e:
            st.error(f"Erro ao ler/validar: {e}")
            st.info("Se der HTTP 400/403: a planilha pode não estar acessível/publicada para leitura por link. Ajuste as permissões.")

# =========================
# Motor BOM
# =========================
def detect_sales_columns(df: pd.DataFrame):
    dfc = df.copy()
    dfc.columns = [norm_col(c) for c in dfc.columns]

    # possíveis nomes
    code_candidates = ["codigo", "cdigo", "sku", "produto", "codprod", "codigo_produto"]
    qty_candidates = ["quantidade", "qtde", "qtd", "qty", "quant", "qte"]

    code_col = None
    qty_col = None

    for c in dfc.columns:
        if c in code_candidates or "codigo" in c or "sku" in c:
            code_col = c
            break

    for c in dfc.columns:
        if c in qty_candidates or "quant" in c or "qtd" in c:
            qty_col = c
            break

    return dfc, code_col, qty_col

def explode_need_for_product(
    codigo_final: str,
    need_qty: int,
    estoque_map: dict,
    bom_simples_map: dict,
    bom_kits_map: dict,
    rows_insumos: list,
    rows_acao: list,
    visited=None,
):
    """
    Regra suprema:
    - Se estoque do codigo_final >= need_qty => não explode
    - Se falta => explode somente faltante
    - Explode até insumos
    - Se faltar insumo => FABRICAR
    - Se faltar BOM => CADASTRAR_BOM
    """

    if visited is None:
        visited = set()

    key = (codigo_final, need_qty)
    if key in visited:
        return
    visited.add(key)

    estoque_atual = estoque_map.get(codigo_final, 0)

    if estoque_atual >= need_qty:
        # não explode
        return

    faltante = max(0, need_qty - max(0, estoque_atual))

    # se não tem estrutura cadastrada
    if codigo_final not in bom_simples_map and codigo_final not in bom_kits_map:
        rows_acao.append({
            "codigo": codigo_final,
            "qtd_necessaria": need_qty,
            "estoque_atual": estoque_atual,
            "faltante": faltante,
            "acao": "CADASTRAR_BOM",
            "observacao": "Sem BOM cadastrada (bom_produto_simples ou bom_kits_conjuntos)."
        })
        return

    # se for kit/conjunto (tem componentes)
    if codigo_final in bom_kits_map:
        comp_codes = bom_kits_map[codigo_final]["componentes_codigos"]
        comp_qtds = bom_kits_map[codigo_final]["componentes_qtds"]

        if len(comp_codes) != len(comp_qtds):
            rows_acao.append({
                "codigo": codigo_final,
                "qtd_necessaria": need_qty,
                "estoque_atual": estoque_atual,
                "faltante": faltante,
                "acao": "CADASTRAR_BOM",
                "observacao": "componentes_codigos e componentes_qtds com tamanhos diferentes."
            })
            return

        # explode somente o faltante do kit
        for cc, qq in zip(comp_codes, comp_qtds):
            child_need = int(round(faltante * qq))
            explode_need_for_product(
                codigo_final=cc,
                need_qty=child_need,
                estoque_map=estoque_map,
                bom_simples_map=bom_simples_map,
                bom_kits_map=bom_kits_map,
                rows_insumos=rows_insumos,
                rows_acao=rows_acao,
                visited=visited,
            )
        return

    # simples => insumos
    b = bom_simples_map[codigo_final]

    def add_insumo(tipo, codigo_insumo, qtd_por_peca):
        codigo_insumo = safe_str(codigo_insumo)
        if not codigo_insumo:
            return

        qtd_total = int(round(faltante * float(qtd_por_peca)))
        est = estoque_map.get(codigo_insumo, 0)
        falt_i = max(0, qtd_total - max(0, est))

        status = "OK" if falt_i == 0 else ("PARCIAL" if est > 0 else "FALTANDO")

        rows_insumos.append({
            "codigo_pai": codigo_final,
            "tipo": tipo,
            "codigo_insumo": codigo_insumo,
            "qtd_necessaria": qtd_total,
            "estoque_atual": est,
            "faltante": falt_i,
            "observacao": "" if falt_i == 0 else "PLATELEIRA ESTOQUE",
            "status": status
        })

        if falt_i > 0:
            rows_acao.append({
                "codigo": codigo_insumo,
                "qtd_necessaria": qtd_total,
                "estoque_atual": est,
                "faltante": falt_i,
                "acao": "FABRICAR",
                "observacao": f"Insumo necessário para {codigo_final} (faltante do pai = {faltante})."
            })

    # SEMI
    add_insumo("SEMI", b.get("semi_codigo", ""), b.get("semi_qtd", 0))

    # GOLA (lista)
    gola_codes = split_csv_like(b.get("gola_codigo", ""))
    gola_qtds = split_nums_like(b.get("gola_qtd", ""))

    if gola_codes and gola_qtds and len(gola_codes) == len(gola_qtds):
        for gc, gq in zip(gola_codes, gola_qtds):
            add_insumo("GOLA", gc, gq)
    elif gola_codes and not gola_qtds:
        # se não veio qtd, assume 1 por item
        for gc in gola_codes:
            add_insumo("GOLA", gc, 1)
    elif gola_codes and gola_qtds and len(gola_codes) != len(gola_qtds):
        rows_acao.append({
            "codigo": codigo_final,
            "qtd_necessaria": need_qty,
            "estoque_atual": estoque_atual,
            "faltante": faltante,
            "acao": "CADASTRAR_BOM",
            "observacao": "gola_codigo e gola_qtd com tamanhos diferentes."
        })

    # BORDADO (1)
    add_insumo("BORDADO", b.get("bordado_codigo", ""), b.get("bordado_qtd", 0))

    # EXTRAS (lista)
    extras_codes = split_csv_like(b.get("extras_codigos", ""))
    extras_qtds = split_nums_like(b.get("extras_qtds", ""))

    if extras_codes and extras_qtds and len(extras_codes) == len(extras_qtds):
        for ec, eq in zip(extras_codes, extras_qtds):
            add_insumo("EXTRA", ec, eq)
    elif extras_codes and not extras_qtds:
        for ec in extras_codes:
            add_insumo("EXTRA", ec, 1)
    elif extras_codes and extras_qtds and len(extras_codes) != len(extras_qtds):
        rows_acao.append({
            "codigo": codigo_final,
            "qtd_necessaria": need_qty,
            "estoque_atual": estoque_atual,
            "faltante": faltante,
            "acao": "CADASTRAR_BOM",
            "observacao": "extras_codigos e extras_qtds com tamanhos diferentes."
        })

# =========================
# Main tab
# =========================
with tab1:
    st.subheader("Explosão BOM (Produção)")
    st.caption("Regra: tendo estoque suficiente do produto final → NÃO explode. Se faltar → explode só o faltante e desce até insumos.")

    st.markdown("### 1) Upload de vendas (CSV/XLSX com colunas de código + quantidade)")
    sales_file = st.file_uploader("Envie arquivo de vendas", type=["csv", "xlsx"])

    st.markdown("### 2) Fonte de dados (usa o que você salvou em Configuração)")
    st.info("Dica: vá em ⚙️ Configuração/Diagnóstico e clique em **Salvar configuração** (fica gravado na URL).")

    # pega da URL atual
    spreadsheet_id = get_q("sid", "")
    gid_template = parse_gid(get_q("gid_template", ""))
    gid_simples = parse_gid(get_q("gid_simples", ""))
    gid_kits = parse_gid(get_q("gid_kits", ""))

    if not spreadsheet_id or not gid_template or not gid_simples or not gid_kits:
        st.warning("Configuração incompleta. Vá em ⚙️ Configuração/Diagnóstico e salve o Spreadsheet ID + GIDs.")
        st.stop()

    @st.cache_data(show_spinner=False, ttl=300)
    def read_google_sheet(spreadsheet_id: str, gid: str) -> pd.DataFrame:
        url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"
        return pd.read_csv(url)

    def normalize_df_columns(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.columns = [norm_col(c) for c in df.columns]
        return df

    # lê sheets
    try:
        df_stock = normalize_df_columns(read_google_sheet(spreadsheet_id, gid_template))
        df_simple = normalize_df_columns(read_google_sheet(spreadsheet_id, gid_simples))
        df_kits = normalize_df_columns(read_google_sheet(spreadsheet_id, gid_kits))
    except Exception as e:
        st.error(f"Falha ao ler Google Sheets: {e}")
        st.info("Se deu HTTP 400/403: verifique se a planilha está acessível/publicada para leitura por link.")
        st.stop()

    # valida colunas essenciais
    if "codigo" not in df_stock.columns or "estoque_atual" not in df_stock.columns:
        st.error("template_estoque precisa ter colunas: codigo, estoque_atual")
        st.stop()

    # mapa estoque
    df_stock["estoque_atual"] = pd.to_numeric(df_stock["estoque_atual"], errors="coerce").fillna(0).astype(int)
    estoque_map = dict(zip(df_stock["codigo"].astype(str), df_stock["estoque_atual"]))

    # mapas BOM
    bom_simples_map = {}
    for _, r in df_simple.iterrows():
        cf = safe_str(r.get("codigo_final", ""))
        if not cf:
            continue
        bom_simples_map[cf] = {
            "semi_codigo": safe_str(r.get("semi_codigo", "")),
            "semi_qtd": pd.to_numeric(r.get("semi_qtd", 0), errors="coerce") if safe_str(r.get("semi_qtd", "")) != "" else 0,
            "gola_codigo": safe_str(r.get("gola_codigo", "")),
            "gola_qtd": safe_str(r.get("gola_qtd", "")),
            "bordado_codigo": safe_str(r.get("bordado_codigo", "")),
            "bordado_qtd": pd.to_numeric(r.get("bordado_qtd", 0), errors="coerce") if safe_str(r.get("bordado_qtd", "")) != "" else 0,
            "extras_codigos": safe_str(r.get("extras_codigos", "")),
            "extras_qtds": safe_str(r.get("extras_qtds", "")),
        }

    bom_kits_map = {}
    for _, r in df_kits.iterrows():
        cf = safe_str(r.get("codigo_final", ""))
        if not cf:
            continue
        bom_kits_map[cf] = {
            "componentes_codigos": split_csv_like(r.get("componentes_codigos", "")),
            "componentes_qtds": split_nums_like(r.get("componentes_qtds", "")),
        }

    if sales_file is None:
        st.stop()

    # lê vendas
    if sales_file.name.lower().endswith(".csv"):
        vendas = pd.read_csv(sales_file)
    else:
        vendas = pd.read_excel(sales_file)

    vendas_norm, code_col, qty_col = detect_sales_columns(vendas)

    if code_col is None or qty_col is None:
        st.error(f"Não consegui detectar colunas de código/quantidade no upload. Colunas encontradas: {list(vendas_norm.columns)}")
        st.stop()

    vendas_norm[code_col] = vendas_norm[code_col].astype(str).str.strip()
    vendas_norm[qty_col] = pd.to_numeric(vendas_norm[qty_col], errors="coerce").fillna(0).astype(int)

    vendas_grp = vendas_norm.groupby(code_col, as_index=False)[qty_col].sum()
    vendas_grp.columns = ["codigo", "quantidade"]

    st.markdown("### 3) Rodar explosão")
    if st.button("🚀 Explodir BOM e gerar relatório", use_container_width=True):
        rows_insumos = []
        rows_acao = []

        # explode cada item vendido
        for _, r in vendas_grp.iterrows():
            cod = safe_str(r["codigo"])
            qty = int(r["quantidade"])
            if not cod or qty <= 0:
                continue

            explode_need_for_product(
                codigo_final=cod,
                need_qty=qty,
                estoque_map=estoque_map,
                bom_simples_map=bom_simples_map,
                bom_kits_map=bom_kits_map,
                rows_insumos=rows_insumos,
                rows_acao=rows_acao,
            )

        df_ins = pd.DataFrame(rows_insumos)
        df_act = pd.DataFrame(rows_acao)

        if df_ins.empty:
            df_ins = pd.DataFrame(columns=["codigo_pai","tipo","codigo_insumo","qtd_necessaria","estoque_atual","faltante","observacao","status"])

        if df_act.empty:
            df_act = pd.DataFrame(columns=["codigo","qtd_necessaria","estoque_atual","faltante","acao","observacao"])

        # ordenação: faltantes desc
        df_act["faltante"] = pd.to_numeric(df_act["faltante"], errors="coerce").fillna(0).astype(int)
        df_act = df_act.sort_values(["acao","faltante"], ascending=[True, False])

        df_ins["faltante"] = pd.to_numeric(df_ins["faltante"], errors="coerce").fillna(0).astype(int)
        df_ins = df_ins.sort_values(["status","faltante"], ascending=[True, False])

        # aba 01_RESUMO (quantos codigos das vendas, quantos com BOM, quantos sem BOM)
        cod_vendas = set(vendas_grp["codigo"].astype(str))
        cod_com_bom = {c for c in cod_vendas if (c in bom_simples_map or c in bom_kits_map)}
        cod_sem_bom = sorted(list(cod_vendas - cod_com_bom))

        df_resumo = pd.DataFrame({
            "metrica": ["itens_unicos_vendas","itens_com_bom","itens_sem_bom"],
            "valor": [len(cod_vendas), len(cod_com_bom), len(cod_sem_bom)]
        })

        df_sem_bom = pd.DataFrame({"codigo_sem_bom": cod_sem_bom})

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = bytes_xlsx({
            "01_RESUMO": df_resumo,
            "02_SEM_BOM": df_sem_bom,
            "03_INSUMOS": df_ins,
            "04_LISTA_ACAO": df_act
        })

        st.success("Relatório gerado ✅")
        st.download_button(
            "⬇️ Baixar relatório Excel",
            data=out,
            file_name=f"relatorio_bom_{ts}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

        st.markdown("### Prévia rápida")
        st.write("Ações (top 30):")
        st.dataframe(df_act.head(30), use_container_width=True)

        st.write("Insumos (top 30):")
        st.dataframe(df_ins.head(30), use_container_width=True)
