# streamlit_app.py
import streamlit as st
import pandas as pd
import requests
from io import StringIO
from datetime import datetime
import plotly.express as px
import math
import unicodedata

# ======================
# CONFIG
# ======================
st.set_page_config(
    page_title="Estoque Cockpit - Silva Holding",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ====== SEU ID (fixo) ======
# use só o ID, não a URL inteira
SPREADSHEET_ID = "1PpiMQingHf4llA03BiPIuPJPIZqul4grRU_emWDEK1o"

# ====== GIDs (fixos) ======
# Coloque os GIDs corretos das abas:
GID_TEMPLATE   = "603934707"   # template_estoque
GID_BOM_SIMPLES = "0"          # bom_produto_simples  (troque)
GID_BOM_KITS    = "0"          # bom_kits_conjuntos   (troque)

# Export do template_estoque (CSV)
SHEETS_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={GID_TEMPLATE}"

# Webhook Apps Script (mesmo que você já usa)
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbxTX9uUWnByw6sk6MtuJ5FbjV7zeBKYEoUPPlUlUDS738QqocfCd_NAlh9Eh25XhQywTw/exec"

# ======================
# HELPERS
# ======================
def safe_int(x, default=0):
    try:
        if x is None:
            return default
        if isinstance(x, float) and math.isnan(x):
            return default
        if isinstance(x, str) and x.strip().lower() in {"", "nan", "none", "null", "n/a"}:
            return default
        return int(float(str(x).replace(",", ".")))
    except Exception:
        return default

def parse_int_list(value):
    if value is None:
        return []
    if isinstance(value, float) and math.isnan(value):
        return []
    parts = [p.strip() for p in str(value).split(",")]
    out = []
    for p in parts:
        if not p:
            continue
        v = safe_int(p, None)
        if v is not None:
            out.append(v)
    return out

def normalize_key(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace('ß', 'ss')
    s = ''.join(ch for ch in s if ch.isalnum() or ch == '-')
    return s.upper().strip()

# ======================
# APPS SCRIPT CALLS
# ======================
def movimentar_estoque(codigo, quantidade, tipo, colaborador, test_mode=False):
    if test_mode:
        return {'success': True, 'message': 'Simulado', 'novo_estoque': 'SIMULAÇÃO'}
    try:
        payload = {
            'action': 'movimentar',
            'codigo': codigo,
            'quantidade': safe_int(quantidade, 0),
            'tipo': tipo,
            'colaborador': colaborador
        }
        r = requests.post(WEBHOOK_URL, json=payload, timeout=20)
        return r.json()
    except Exception as e:
        return {'success': False, 'message': f'Erro: {str(e)}'}

def append_bom_rows(destino: str, codigos: list[str], colaborador: str, test_mode=False):
    """
    destino: 'simples' ou 'kits'
    codigos: lista de códigos
    """
    if test_mode:
        return {'success': True, 'message': f'(TESTE) Simulado append {destino}', 'inserted': len(codigos), 'skipped': 0}

    try:
        payload = {
            'action': 'append_bom',
            'spreadsheet_id': SPREADSHEET_ID,
            'destino': destino,  # 'simples' | 'kits'
            'codigos': codigos,
            'colaborador': colaborador,
            'gid_simples': str(GID_BOM_SIMPLES),
            'gid_kits': str(GID_BOM_KITS),
            'timestamp': f"{datetime.now():%Y-%m-%d %H:%M:%S}"
        }
        r = requests.post(WEBHOOK_URL, json=payload, timeout=30)
        return r.json()
    except Exception as e:
        return {'success': False, 'message': f'Erro: {str(e)}'}

# ======================
# LOAD PRODUTOS (template_estoque)
# ======================
@st.cache_data(ttl=30)
def carregar_produtos():
    try:
        r = requests.get(SHEETS_URL, timeout=20)
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))

        req = ['codigo', 'nome', 'categoria', 'estoque_atual', 'estoque_min', 'estoque_max']
        for c in req:
            if c not in df.columns:
                if c == 'estoque_max':
                    df[c] = df.get('estoque_min', 0) * 2
                else:
                    df[c] = 0

        df['estoque_atual'] = pd.to_numeric(df['estoque_atual'], errors='coerce').fillna(0)
        df['estoque_min']   = pd.to_numeric(df['estoque_min'], errors='coerce').fillna(0)
        df['estoque_max']   = pd.to_numeric(df['estoque_max'], errors='coerce').fillna(0)

        for c in ['componentes', 'quantidades', 'eh_kit']:
            if c not in df.columns:
                df[c] = ''
            else:
                df[c] = df[c].astype(str).fillna('')

        df['codigo_key'] = df['codigo'].astype(str).map(normalize_key)
        return df
    except Exception as e:
        st.error(f"Erro ao carregar dados: {e}")
        return pd.DataFrame()

def calcular_semaforo(estoque_atual, estoque_min, estoque_max):
    if estoque_atual < estoque_min:
        return "🔴", "CRÍTICO", "#ff4444"
    elif estoque_atual <= estoque_min * 1.2:
        return "🟠", "BAIXO", "#ffaa00"
    elif estoque_atual > estoque_max:
        return "🔵", "EXCESSO", "#0088ff"
    else:
        return "🟢", "OK", "#00aa00"

def expandir_kits(df_fatura, produtos_df):
    key_to_code = dict(zip(produtos_df['codigo_key'], produtos_df['codigo'].astype(str)))

    kits = {}
    for _, row in produtos_df.iterrows():
        if str(row.get('eh_kit', '')).strip().lower() == 'sim':
            kit_key = row['codigo_key']
            comps = [normalize_key(c.strip()) for c in str(row.get('componentes', '')).split(',') if c.strip()]
            quants = parse_int_list(row.get('quantidades', ''))
            if comps and quants and len(comps) == len(quants):
                kits[kit_key] = list(zip(comps, quants))

    if not kits:
        df_f = df_fatura.copy()
        df_f['codigo_key'] = df_f['codigo'].map(normalize_key)
        df_f['codigo_canonical'] = df_f['codigo_key'].map(lambda k: key_to_code.get(k, ''))
        df_f['codigo'] = df_f['codigo_canonical'].where(df_f['codigo_canonical'] != '', df_f['codigo'])
        return df_f

    linhas = []
    for _, row in df_fatura.iterrows():
        qty = safe_int(row.get('quantidade', 0), 0)
        code_key = normalize_key(row['codigo'])
        if code_key in kits:
            for comp_key, comp_qty in kits[code_key]:
                linhas.append({'codigo_key': comp_key, 'quantidade': qty * safe_int(comp_qty, 0)})
        else:
            linhas.append({'codigo_key': code_key, 'quantidade': qty})

    df = pd.DataFrame(linhas).groupby('codigo_key', as_index=False)['quantidade'].sum()
    df['codigo_canonical'] = df['codigo_key'].map(lambda k: key_to_code.get(k, ''))
    df['codigo'] = df['codigo_canonical'].where(df['codigo_canonical'] != '', df['codigo_key'])
    return df

def processar_faturamento(arquivo_upload, produtos_df):
    try:
        nome = arquivo_upload.name.lower()
        if nome.endswith('.csv'):
            df_fatura = None
            for enc in ['utf-8', 'utf-8-sig', 'latin1', 'iso-8859-1', 'cp1252', 'windows-1252']:
                try:
                    arquivo_upload.seek(0)
                    df_tmp = pd.read_csv(arquivo_upload, encoding=enc)
                    if df_tmp is not None and len(df_tmp.columns) > 0:
                        df_fatura = df_tmp
                        break
                except:
                    continue
            if df_fatura is None:
                return None, None, "Não foi possível ler o CSV (tente salvar como UTF-8)."
        elif nome.endswith('.xlsx'):
            df_fatura = pd.read_excel(arquivo_upload, engine='openpyxl')
        elif nome.endswith('.xls'):
            df_fatura = pd.read_excel(arquivo_upload, engine='xlrd')
        else:
            return None, None, "Formato não suportado (use CSV/XLS/XLSX)."

        def normcol(n):
            n = unicodedata.normalize('NFKD', str(n)).encode('ASCII', 'ignore').decode('ASCII')
            return n.lower().strip()
        df_fatura.rename(columns={c: normcol(c) for c in df_fatura.columns}, inplace=True)

        if 'codigo' not in df_fatura.columns:
            return None, None, f"Arquivo sem coluna 'Código'. Colunas: {list(df_fatura.columns)}"
        if 'quantidade' not in df_fatura.columns:
            return None, None, f"Arquivo sem coluna 'Quantidade'. Colunas: {list(df_fatura.columns)}"

        df_fatura['codigo'] = df_fatura['codigo'].astype(str).str.strip()
        df_fatura['quantidade'] = df_fatura['quantidade'].apply(lambda x: safe_int(x, 0)).astype(int)
        df_fatura = df_fatura[(df_fatura['codigo'] != '') & (df_fatura['quantidade'] > 0)]
        df_fatura = df_fatura.groupby('codigo', as_index=False)['quantidade'].sum().reset_index(drop=True)

        df_fatura = expandir_kits(df_fatura, produtos_df)
        if 'codigo_key' not in df_fatura.columns:
            df_fatura['codigo_key'] = df_fatura['codigo'].map(normalize_key)

        estoque_keys = set(produtos_df['codigo_key'])
        df_fatura['encontrado'] = df_fatura['codigo_key'].isin(estoque_keys)

        est_map = {}
        for _, r in produtos_df.iterrows():
            k = r['codigo_key']
            est_map[k] = {'nome': r.get('nome', 'N/A'), 'estoque_atual': pd.to_numeric(r.get('estoque_atual', 0), errors='coerce'), 'codigo': r.get('codigo', '')}

        prods_ok = df_fatura[df_fatura['encontrado']].copy().reset_index(drop=True)
        if not prods_ok.empty:
            prods_ok['nome'] = prods_ok['codigo_key'].map(lambda k: est_map[k]['nome'])
            prods_ok['estoque_atual'] = prods_ok['codigo_key'].map(lambda k: est_map[k]['estoque_atual']).fillna(0)
            prods_ok['codigo_canonical'] = prods_ok['codigo_key'].map(lambda k: est_map[k]['codigo']).fillna(prods_ok['codigo'])
            prods_ok['estoque_atual'] = pd.to_numeric(prods_ok['estoque_atual'], errors='coerce').fillna(0)
            prods_ok['quantidade'] = pd.to_numeric(prods_ok['quantidade'], errors='coerce').fillna(0)
            prods_ok['estoque_final'] = prods_ok['estoque_atual'] - prods_ok['quantidade']

        prods_nok = df_fatura[~df_fatura['encontrado']].copy().reset_index(drop=True)
        if not prods_nok.empty:
            prods_nok = prods_nok[['codigo', 'quantidade', 'codigo_key']]

        return prods_ok, prods_nok, None
    except Exception as e:
        return None, None, f"Erro ao processar: {str(e)}"

# ======================
# UI STYLE
# ======================
st.markdown("""
<style>
.metric-card{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);padding:.9rem;border-radius:10px;color:#fff;text-align:center;margin:.5rem 0}
.status-card{padding:.8rem;border-radius:8px;margin:.3rem 0;border-left:4px solid}
.critico{border-color:#ff4444;background:#ffe6e6}
.baixo{border-color:#ffaa00;background:#fff8e6}
.ok{border-color:#00aa00;background:#e6ffe6}
.excesso{border-color:#0088ff;background:#e6f3ff}
.cockpit-header{background:linear-gradient(90deg,#1e3c72 0%,#2a5298 100%);color:#fff;padding:1rem;border-radius:10px;text-align:center;margin-bottom:1rem}
.warning-box{background:#fff3cd;border-left:4px solid #ffc107;padding:1rem;border-radius:5px;margin:1rem 0}
.success-box{background:#d4edda;border-left:4px solid #28a745;padding:1rem;border-radius:5px;margin:1rem 0}
.error-box{background:#f8d7da;border-left:4px solid #dc3545;padding:1rem;border-radius:5px;margin:1rem 0}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="cockpit-header">
  <h1>COCKPIT DE CONTROLE — SILVA HOLDING</h1>
  <p>"Se parar para sentir o perfume das rosas, vem um caminhão e te atropela."</p>
</div>
""", unsafe_allow_html=True)

# ======================
# DATA
# ======================
produtos_df = carregar_produtos()
if produtos_df.empty:
    st.error("Não foi possível carregar os dados.")
    st.stop()

produtos_df['semaforo'], produtos_df['status'], produtos_df['cor'] = zip(*produtos_df.apply(
    lambda r: calcular_semaforo(r['estoque_atual'], r['estoque_min'], r['estoque_max']), axis=1
))
produtos_df['falta_para_min']   = (produtos_df['estoque_min'] - produtos_df['estoque_atual']).clip(lower=0)
produtos_df['falta_para_max']   = (produtos_df['estoque_max'] - produtos_df['estoque_atual']).clip(lower=0)
produtos_df['excesso_sobre_max']= (produtos_df['estoque_atual'] - produtos_df['estoque_max']).clip(lower=0)
produtos_df['diferenca_min_max']= produtos_df['estoque_max'] - produtos_df['estoque_min']

# ======================
# SIDEBAR
# ======================
st.sidebar.header("🎛️ CONTROLES DE VOO")
test_mode = st.sidebar.checkbox("✏️ Modo Teste (simulação)", value=False)
st.sidebar.info("Quando Modo Teste está ativo, nada é escrito na planilha. Só simula.")

categorias = ['Todas'] + sorted(produtos_df['categoria'].unique().tolist())
categoria_filtro = st.sidebar.selectbox("📂 Categoria", categorias)

status_opcoes = ['Todos', 'CRÍTICO', 'BAIXO', 'OK', 'EXCESSO']
status_filtro = st.sidebar.selectbox("🚦 Status", status_opcoes)

tipo_analise = st.sidebar.radio(
    "Tipo de Análise",
    ["Visão Geral", "Análise Mín/Máx", "Movimentação", "Baixa por Faturamento", "Relatório de Faltantes"]
)

df_filtrado = produtos_df.copy()
if categoria_filtro != 'Todas':
    df_filtrado = df_filtrado[df_filtrado['categoria'] == categoria_filtro]
if status_filtro != 'Todos':
    df_filtrado = df_filtrado[df_filtrado['status'] == status_filtro]

# ======================
# VISÃO GERAL
# ======================
if tipo_analise == "Visão Geral":
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1: st.markdown(f"""<div class="metric-card"><h3>PRODUTOS</h3><h2>{len(df_filtrado)}</h2></div>""", unsafe_allow_html=True)
    with col2: st.markdown(f"""<div class="metric-card"><h3>ESTOQUE TOTAL</h3><h2>{int(df_filtrado['estoque_atual'].sum()):,}</h2></div>""", unsafe_allow_html=True)
    with col3: st.markdown(f"""<div class="metric-card"><h3>CRÍTICOS</h3><h2>{len(df_filtrado[df_filtrado['status']=='CRÍTICO'])}</h2></div>""", unsafe_allow_html=True)
    with col4: st.markdown(f"""<div class="metric-card"><h3>BAIXOS</h3><h2>{len(df_filtrado[df_filtrado['status']=='BAIXO'])}</h2></div>""", unsafe_allow_html=True)
    with col5: st.markdown(f"""<div class="metric-card"><h3>OK</h3><h2>{len(df_filtrado[df_filtrado['status']=='OK'])}</h2></div>""", unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Distribuição por Status")
        vc = df_filtrado['status'].value_counts()
        st.plotly_chart(
            px.pie(values=vc.values, names=vc.index).update_layout(height=320),
            use_container_width=True
        )
    with c2:
        st.subheader("Estoque por Categoria")
        cat = df_filtrado.groupby('categoria')['estoque_atual'].sum().sort_values(ascending=False)
        st.plotly_chart(px.bar(x=cat.index, y=cat.values).update_layout(height=320, showlegend=False),
                        use_container_width=True)

# ======================
# ANÁLISE MÍN/MÁX
# ======================
elif tipo_analise == "Análise Mín/Máx":
    st.subheader("Análise Estoque Mínimo/Máximo")
    c1, c2 = st.columns(2)
    with c1:
        analise_tipo = st.selectbox("Tipo de Análise", ["Falta para Mínimo", "Falta para Máximo", "Excesso sobre Máximo", "Diferença Mín-Máx"])
    with c2:
        only_diff = st.checkbox("Mostrar apenas com diferença > 0", value=True)

    df_ = df_filtrado.copy()
    if analise_tipo == "Falta para Mínimo":
        col = 'falta_para_min'; titulo = 'Falta p/ Mín'
        if only_diff: df_ = df_[df_['falta_para_min'] > 0]
    elif analise_tipo == "Falta para Máximo":
        col = 'falta_para_max'; titulo = 'Falta p/ Máx'
        if only_diff: df_ = df_[df_['falta_para_max'] > 0]
    elif analise_tipo == "Excesso sobre Máximo":
        col = 'excesso_sobre_max'; titulo = 'Excesso s/ Máx'
        if only_diff: df_ = df_[df_['excesso_sobre_max'] > 0]
    else:
        col = 'diferenca_min_max'; titulo = 'Diferença Mín-Máx'
        if only_diff: df_ = df_[df_['diferenca_min_max'] > 0]

    if df_.empty:
        st.info("Sem resultados para os filtros.")
    else:
        tbl = df_[['codigo','nome','categoria','estoque_atual','estoque_min','estoque_max',col,'status']].rename(
            columns={'estoque_atual':'Atual','estoque_min':'Mínimo','estoque_max':'Máximo', col:titulo, 'status':'Status', 'codigo':'Código','nome':'Produto','categoria':'Categoria'}
        )
        for c in ['Atual','Mínimo','Máximo',titulo]:
            tbl[c] = pd.to_numeric(tbl[c], errors='coerce').fillna(0).astype(int)
        st.dataframe(tbl.sort_values(titulo, ascending=False), use_container_width=True, height=520)

# ======================
# MOVIMENTAÇÃO
# ======================
elif tipo_analise == "Movimentação":
    st.subheader("Movimentação de Estoque")
    colaborador = st.selectbox("👤 Colaborador", ['Pericles','Maria','Camila','Cris VantiStella'])
    busca = st.text_input("🔍 Buscar", placeholder="Código ou nome...")
    if not busca or len(busca) < 2:
        st.info("Digite pelo menos 2 caracteres.")
    else:
        found = df_filtrado[
            df_filtrado['codigo'].str.contains(busca, case=False, na=False) |
            df_filtrado['nome'].str.contains(busca, case=False, na=False)
        ]
        if found.empty:
            st.warning("Nada encontrado.")
        else:
            for _, p in found.head(10).iterrows():
                with st.expander(f"{p['semaforo']} {p['codigo']} — {p['nome']}"):
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.metric("Atual", f"{int(p['estoque_atual'])}")
                        st.metric("Mín", f"{int(p['estoque_min'])}")
                        st.metric("Máx", f"{int(p['estoque_max'])}")
                    with c2:
                        qtd_e = st.number_input("Quantidade (Entrada)", min_value=1, value=1, key=f"ent_{p['codigo']}")
                        if st.button("+ Entrada", key=f"btn_ent_{p['codigo']}"):
                            r = movimentar_estoque(p['codigo'], qtd_e, 'entrada', colaborador, test_mode=test_mode)
                            st.success(f"{r.get('message','OK')} | Novo estoque: {r.get('novo_estoque')}")
                            if not test_mode and r.get('success'):
                                st.cache_data.clear(); st.rerun()
                    with c3:
                        max_s = max(1, int(p['estoque_atual']))
                        qtd_s = st.number_input("Quantidade (Saída)", min_value=1, max_value=max_s, value=1, key=f"sai_{p['codigo']}")
                        if st.button("- Saída", key=f"btn_sai_{p['codigo']}"):
                            r = movimentar_estoque(p['codigo'], qtd_s, 'saida', colaborador, test_mode=test_mode)
                            st.success(f"{r.get('message','OK')} | Novo estoque: {r.get('novo_estoque')}")
                            if not test_mode and r.get('success'):
                                st.cache_data.clear(); st.rerun()

# ======================
# BAIXA POR FATURAMENTO + BOTÃO ENVIAR PARA BOM
# ======================
elif tipo_analise == "Baixa por Faturamento":
    st.subheader("Baixa por Faturamento")
    st.markdown("""
    <div class="success-box">
      <strong>Fluxo:</strong><br>
      1) Upload (CSV/XLS/XLSX com <em>Código</em> e <em>Quantidade</em>)<br>
      2) Preview (encontrados x não encontrados)<br>
      3) (Opcional) Enviar não encontrados para BOM<br>
      4) Aplicar baixa (se quiser)
    </div>
    """, unsafe_allow_html=True)

    st.info("Modo Teste está **{}**.".format("ATIVO (simulação)" if test_mode else "DESATIVADO (vai alterar planilha)"))
    colaborador_fatura = st.selectbox("👤 Colaborador responsável", ['Pericles','Maria','Camila','Cris VantiStella'], key="colab_fatura")
    arquivo = st.file_uploader("📁 Arquivo de faturamento", type=['csv','xls','xlsx'])

    if arquivo:
        with st.spinner("Processando arquivo..."):
            ok, nok, err = processar_faturamento(arquivo, produtos_df)

        if err:
            st.error(err)
        else:
            c1, c2, c3 = st.columns(3)
            with c1: st.metric("Total de Linhas", len(ok)+len(nok))
            with c2: st.metric("Produtos Encontrados", len(ok))
            with c3: st.metric("Não Encontrados", len(nok))

            # ---------- NÃO ENCONTRADOS + BOTÃO ENVIAR PARA BOM ----------
            if not nok.empty:
                st.markdown("""<div class="error-box"><b>ATENÇÃO:</b> Códigos não encontrados no estoque.</div>""", unsafe_allow_html=True)
                tbl_nok = nok[['codigo','quantidade','codigo_key']].rename(columns={'codigo':'Código','quantidade':'Quantidade','codigo_key':'Chave Normalizada'})
                st.dataframe(tbl_nok, use_container_width=True, height=260)

                st.markdown("### ✅ Resolver agora: criar linhas no BOM com placeholders")
                destino = st.radio(
                    "Onde você quer cadastrar esses códigos?",
                    ["Produto simples (bom_produto_simples)", "Kit/Conjunto (bom_kits_conjuntos)"],
                    horizontal=False
                )

                cods = tbl_nok['Código'].astype(str).str.strip().tolist()
                cods = [c for c in cods if c]

                if st.button("📌 ENVIAR PARA BOM (criar linhas vazias)", type="primary", use_container_width=True):
                    dest_key = "simples" if destino.startswith("Produto simples") else "kits"
                    res = append_bom_rows(dest_key, cods, colaborador_fatura, test_mode=test_mode)
                    if res.get('success'):
                        st.success(f"OK. Inseridos: {res.get('inserted',0)} | Já existiam: {res.get('skipped',0)}")
                        st.info("Agora é só ir na planilha e preencher Componentes/Quantidades/Nomes.")
                    else:
                        st.error(res.get('message', 'Falha ao enviar para BOM'))

            # ---------- PREVIEW ENCONTRADOS ----------
            if not ok.empty:
                st.markdown("---"); st.subheader("Preview da Baixa")
                prev = ok[['codigo_canonical','nome','estoque_atual','quantidade','estoque_final']].copy()
                prev.columns = ['Código','Produto','Estoque Atual','Qtd a Baixar','Estoque Final']
                for c in ['Estoque Atual','Qtd a Baixar','Estoque Final']:
                    prev[c] = pd.to_numeric(prev[c], errors='coerce').fillna(0).astype(int)
                prev['Status'] = prev['Estoque Final'].apply(lambda x: 'Negativo' if x < 0 else ('Zerado' if x == 0 else 'OK'))
                st.dataframe(prev, use_container_width=True, height=520)

                label_btn = "🧪 SIMULAR baixas (modo teste)" if test_mode else "✅ APLICAR baixas (alterar planilha)"
                if st.button(label_btn, type="secondary", use_container_width=True):
                    sucesso, erro = 0, 0
                    prog = st.progress(0); txt = st.empty()
                    total = len(ok)
                    for i, row in ok.iterrows():
                        txt.text(f"Processando {i+1}/{total}: {row.get('codigo_canonical', row['codigo'])}")
                        res = movimentar_estoque(row.get('codigo_canonical', row['codigo']),
                                                 row['quantidade'], 'saida', colaborador_fatura, test_mode=test_mode)
                        if res.get('success'):
                            sucesso += 1
                        else:
                            erro += 1
                        prog.progress((i+1)/total)
                    prog.empty(); txt.empty()
                    st.success(f"Concluído. Sucessos: {sucesso} | Erros: {erro}")
                    if not test_mode:
                        st.cache_data.clear(); st.rerun()

# ======================
# RELATÓRIO DE FALTANTES
# ======================
elif tipo_analise == "Relatório de Faltantes":
    st.subheader("Relatório de Produtos Faltantes")
    st.markdown("""<div class="warning-box">
    Upload vendas (Código/Quantidade). O app expande kits e checa estoque.
    </div>""", unsafe_allow_html=True)
    st.file_uploader("📁 Arquivo de vendas", type=['csv','xls','xlsx'], key="faltantes_up")

st.markdown("---")
c1, c2 = st.columns(2)
with c1:
    if st.button("🔄 Atualizar Dados"):
        st.cache_data.clear(); st.rerun()
with c2:
    st.write(f"**Última atualização:** {datetime.now():%H:%M:%S}")
