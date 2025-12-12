import streamlit as st
import pandas as pd
import requests
from io import StringIO
import math
import unicodedata
from datetime import datetime

st.set_page_config(
    page_title="Teste Explosão BOM — Silva Holding",
    layout="wide"
)

SHEETS_URL = "https://docs.google.com/spreadsheets/d/1PpiMQingHf4llA03BiPIuPJPIZqul4grRU_emWDEK1o/export?format=csv"

# ======================
# HELPERS
# ======================
def safe_int(x, default=0):
    try:
        return int(float(str(x).replace(",", ".")))
    except:
        return default

def parse_int_list(value):
    if pd.isna(value):
        return []
    return [safe_int(v) for v in str(value).split(",") if str(v).strip()]

def normalize_key(s):
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s if c.isalnum() or c == "-").upper().strip()

# ======================
# LOAD ESTOQUE
# ======================
@st.cache_data
def carregar_estoque():
    r = requests.get(SHEETS_URL)
    df = pd.read_csv(StringIO(r.text))

    for c in ["codigo", "nome", "categoria", "estoque_atual", "componentes", "quantidades"]:
        if c not in df.columns:
            df[c] = ""

    df["estoque_atual"] = pd.to_numeric(df["estoque_atual"], errors="coerce").fillna(0).astype(int)
    df["codigo_key"] = df["codigo"].apply(normalize_key)
    return df

# ======================
# BOM EXPLOSION
# ======================
def explode_bom(codigo, quantidade, estoque_df, resultado):
    mapa = {r["codigo_key"]: r for _, r in estoque_df.iterrows()}
    key = normalize_key(codigo)

    row = mapa.get(key)
    if row is None:
        resultado[key] = resultado.get(key, 0) + quantidade
        return

    estoque = row["estoque_atual"]
    consome = min(estoque, quantidade)
    falta = quantidade - consome

    if falta <= 0:
        return

    comps = [normalize_key(c) for c in str(row["componentes"]).split(",") if c.strip()]
    quants = parse_int_list(row["quantidades"])

    if not comps or len(comps) != len(quants):
        resultado[key] = resultado.get(key, 0) + falta
        return

    for c, q in zip(comps, quants):
        explode_bom(c, falta * q, estoque_df, resultado)

# ======================
# UI
# ======================
st.title("🧪 TESTE — Explosão de BOM (Somente Faltantes)")

estoque_df = carregar_estoque()

uploaded = st.file_uploader(
    "Upload vendas (CSV/XLSX com colunas codigo / quantidade)",
    type=["csv", "xlsx"]
)

if uploaded:
    if uploaded.name.endswith(".csv"):
        vendas = pd.read_csv(uploaded)
    else:
        vendas = pd.read_excel(uploaded)

    vendas.columns = vendas.columns.str.lower().str.strip()
    vendas["quantidade"] = vendas["quantidade"].apply(safe_int)

    vendas = vendas.groupby("codigo", as_index=False)["quantidade"].sum()

    resultado_insumos = {}

    for _, r in vendas.iterrows():
        explode_bom(r["codigo"], r["quantidade"], estoque_df, resultado_insumos)

    linhas = []
    mapa = {r["codigo_key"]: r for _, r in estoque_df.iterrows()}

    for k, need in resultado_insumos.items():
        row = mapa.get(k, {})
        est = safe_int(row.get("estoque_atual", 0))
        falta = max(0, need - est)

        status = "🟢 OK" if falta == 0 else ("🟠 PARCIAL" if est > 0 else "🔴 FABRICAR")

        linhas.append({
            "Insumo": row.get("codigo", k),
            "Categoria": row.get("categoria", "INSUMO"),
            "Necessário": need,
            "Estoque": est,
            "Falta": falta,
            "Status": status
        })

    df_res = pd.DataFrame(linhas).sort_values(["Status", "Falta"], ascending=[True, False])

    st.subheader("Resultado — Insumos")
    st.dataframe(df_res, use_container_width=True)

    st.download_button(
        "📥 Baixar CSV",
        df_res.to_csv(index=False, encoding="utf-8-sig"),
        file_name=f"teste_explosao_{datetime.now():%Y%m%d_%H%M%S}.csv"
    )
