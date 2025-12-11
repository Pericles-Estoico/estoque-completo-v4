import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import requests
from io import StringIO

# Configuração mobile-first
st.set_page_config(
    page_title="📦 Estoque Mobile",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed"  # Sidebar fechada no mobile
)

# CSS Mobile-First com UX/UI perfeito
st.markdown("""
<style>
    /* Reset e base */
    .main .block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
        padding-left: 1rem;
        padding-right: 1rem;
        max-width: 100%;
    }
    
    /* Header mobile */
    .mobile-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem 1rem;
        border-radius: 15px;
        color: white;
        text-align: center;
        margin-bottom: 1.5rem;
        box-shadow: 0 8px 32px rgba(0,0,0,0.1);
    }
    
    .mobile-header h1 {
        font-size: 1.8rem;
        margin: 0;
        font-weight: 700;
    }
    
    .mobile-header p {
        font-size: 0.9rem;
        margin: 0.5rem 0 0 0;
        opacity: 0.9;
    }
    
    /* Cards de métricas mobile */
    .metric-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 0.75rem;
        margin-bottom: 1.5rem;
    }
    
    .metric-card {
        background: white;
        padding: 1rem;
        border-radius: 12px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08);
        text-align: center;
        border-left: 4px solid;
        transition: transform 0.2s ease;
    }
    
    .metric-card:active {
        transform: scale(0.98);
    }
    
    .metric-ok { border-color: #28a745; }
    .metric-warning { border-color: #ffc107; }
    .metric-danger { border-color: #dc3545; }
    .metric-info { border-color: #17a2b8; }
    
    .metric-number {
        font-size: 1.8rem;
        font-weight: 700;
        margin: 0;
        line-height: 1;
    }
    
    .metric-label {
        font-size: 0.8rem;
        color: #666;
        margin: 0.25rem 0 0 0;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    /* Botões mobile */
    .mobile-buttons {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 0.75rem;
        margin-bottom: 1.5rem;
    }
    
    .mobile-btn {
        background: linear-gradient(135deg, #667eea, #764ba2);
        color: white;
        padding: 1rem;
        border-radius: 12px;
        text-align: center;
        text-decoration: none;
        font-weight: 600;
        font-size: 0.9rem;
        border: none;
        cursor: pointer;
        transition: all 0.2s ease;
        box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
    }
    
    .mobile-btn:active {
        transform: translateY(2px);
        box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
    }
    
    .mobile-btn-secondary {
        background: linear-gradient(135deg, #6c757d, #495057);
        box-shadow: 0 4px 15px rgba(108, 117, 125, 0.3);
    }
    
    /* Lista de produtos mobile */
    .product-list {
        background: white;
        border-radius: 15px;
        overflow: hidden;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08);
        margin-bottom: 1.5rem;
    }
    
    .product-item {
        padding: 1rem;
        border-bottom: 1px solid #f0f0f0;
        display: flex;
        align-items: center;
        justify-content: space-between;
        transition: background 0.2s ease;
    }
    
    .product-item:active {
        background: #f8f9fa;
    }
    
    .product-item:last-child {
        border-bottom: none;
    }
    
    .product-info {
        flex: 1;
    }
    
    .product-name {
        font-weight: 600;
        font-size: 0.95rem;
        margin: 0 0 0.25rem 0;
        color: #333;
    }
    
    .product-details {
        font-size: 0.8rem;
        color: #666;
        margin: 0;
    }
    
    .product-status {
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    
    .status-badge {
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    .status-ok { background: #d4edda; color: #155724; }
    .status-warning { background: #fff3cd; color: #856404; }
    .status-danger { background: #f8d7da; color: #721c24; }
    
    /* Filtros mobile */
    .mobile-filters {
        background: white;
        padding: 1rem;
        border-radius: 12px;
        margin-bottom: 1rem;
        box-shadow: 0 2px 10px rgba(0,0,0,0.05);
    }
    
    /* Alertas mobile */
    .alert-mobile {
        background: #fff3cd;
        border-left: 4px solid #ffc107;
        padding: 1rem;
        border-radius: 8px;
        margin-bottom: 1rem;
        font-size: 0.9rem;
    }
    
    .alert-danger-mobile {
        background: #f8d7da;
        border-left-color: #dc3545;
        color: #721c24;
    }
    
    .alert-success-mobile {
        background: #d4edda;
        border-left-color: #28a745;
        color: #155724;
    }
    
    /* Gráficos mobile */
    .chart-container-mobile {
        background: white;
        padding: 1rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08);
    }
    
    /* Relatórios mobile */
    .report-section-mobile {
        background: white;
        padding: 1.5rem;
        border-radius: 15px;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08);
    }
    
    .report-buttons {
        display: grid;
        grid-template-columns: 1fr;
        gap: 0.75rem;
    }
    
    .report-btn {
        background: linear-gradient(135deg, #28a745, #20c997);
        color: white;
        padding: 1rem;
        border-radius: 12px;
        text-align: center;
        font-weight: 600;
        border: none;
        cursor: pointer;
        transition: all 0.2s ease;
        box-shadow: 0 4px 15px rgba(40, 167, 69, 0.3);
    }
    
    .report-btn:active {
        transform: translateY(2px);
    }
    
    /* Configuração mobile */
    .config-mobile {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        border: 2px dashed #dee2e6;
    }
    
    /* Footer mobile */
    .footer-mobile {
        text-align: center;
        padding: 2rem 1rem;
        color: #666;
        font-size: 0.8rem;
        border-top: 1px solid #eee;
        margin-top: 2rem;
    }
    
    /* Responsividade */
    @media (max-width: 768px) {
        .metric-grid {
            grid-template-columns: repeat(2, 1fr);
        }
        
        .mobile-buttons {
            grid-template-columns: 1fr;
        }
        
        .product-item {
            flex-direction: column;
            align-items: flex-start;
            gap: 0.75rem;
        }
        
        .product-status {
            align-self: flex-end;
        }
    }
    
    /* Animações */
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(20px); }
        to { opacity: 1; transform: translateY(0); }
    }
    
    .fade-in {
        animation: fadeIn 0.3s ease-out;
    }
    
    /* Scrollbar customizada */
    ::-webkit-scrollbar {
        width: 4px;
    }
    
    ::-webkit-scrollbar-track {
        background: #f1f1f1;
    }
    
    ::-webkit-scrollbar-thumb {
        background: #c1c1c1;
        border-radius: 2px;
    }
    
    ::-webkit-scrollbar-thumb:hover {
        background: #a8a8a8;
    }
</style>
""", unsafe_allow_html=True)

# Funções auxiliares (mesmas do app principal)
@st.cache_data(ttl=60)
def carregar_planilha(url):
    if not url:
        return pd.DataFrame()
    
    try:
        if '/edit' in url:
            csv_url = url.replace('/edit#gid=0', '/export?format=csv').replace('/edit', '/export?format=csv')
        else:
            csv_url = url
        
        response = requests.get(csv_url, timeout=10)
        response.raise_for_status()
        
        df = pd.read_csv(StringIO(response.text))
        
        required_cols = ['codigo', 'nome', 'categoria', 'estoque_atual', 'estoque_min', 'estoque_max', 'custo_unitario']
        missing_cols = [col for col in required_cols if col not in df.columns]
        
        if missing_cols:
            st.error(f"❌ Colunas faltando: {missing_cols}")
            return pd.DataFrame()
        
        df = df.dropna(subset=['codigo', 'nome'])
        df['estoque_atual'] = pd.to_numeric(df['estoque_atual'], errors='coerce').fillna(0)
        df['estoque_min'] = pd.to_numeric(df['estoque_min'], errors='coerce').fillna(0)
        df['estoque_max'] = pd.to_numeric(df['estoque_max'], errors='coerce').fillna(0)
        df['custo_unitario'] = pd.to_numeric(df['custo_unitario'], errors='coerce').fillna(0)
        
        return df
        
    except Exception as e:
        st.error(f"❌ Erro ao carregar: {str(e)}")
        return pd.DataFrame()

def adicionar_status(df):
    if df.empty:
        return df
    
    df['status'] = df.apply(lambda row: 
        'CRÍTICO' if row['estoque_atual'] <= row['estoque_min']
        else 'ATENÇÃO' if row['estoque_atual'] <= row['estoque_min'] * 1.5
        else 'OK', axis=1)
    
    df['semaforo'] = df['status'].map({
        'OK': '🟢',
        'ATENÇÃO': '🟡', 
        'CRÍTICO': '🔴'
    })
    
    return df

# Header Mobile
st.markdown("""
<div class="mobile-header fade-in">
    <h1>📦 Controle de Estoque</h1>
    <p>Dashboard Mobile Otimizado</p>
</div>
""", unsafe_allow_html=True)

# URL do Google Sheets (FIXO)
sheets_url = "https://docs.google.com/spreadsheets/d/1PpiMQingHf4llA03BiPIuPJPIZqul4grRU_emWDEK1o/export?format=csv"

# Mostrar configuração
st.success("✅ Planilha configurada automaticamente!")
st.markdown("🔗 [Editar planilha no Google Sheets](https://docs.google.com/spreadsheets/d/1PpiMQingHf4llA03BiPIuPJPIZqul4grRU_emWDEK1o/edit?usp=sharing)")

if sheets_url != st.session_state.get('sheets_url', ''):
    st.session_state['sheets_url'] = sheets_url
    st.cache_data.clear()

# Botões de controle
col_ctrl1, col_ctrl2 = st.columns(2)
with col_ctrl1:
    if st.button("🔄 Atualizar", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

with col_ctrl2:
    auto_refresh = st.checkbox("🔄 Auto 30s", value=False)

# Verificar configuração
if not sheets_url:
    st.markdown("""
    <div class="config-mobile fade-in">
        <h3>🚀 Configuração Inicial</h3>
        <p><strong>1.</strong> Crie uma planilha no Google Sheets</p>
        <p><strong>2.</strong> Compartilhe como "Anyone with link can view"</p>
        <p><strong>3.</strong> Cole a URL acima</p>
        <br>
        <p><strong>Colunas necessárias:</strong></p>
        <code>codigo | nome | categoria | estoque_atual | estoque_min | estoque_max | custo_unitario</code>
    </div>
    """, unsafe_allow_html=True)
    
    # Template para download
    template_data = {
        'codigo': ['P001', 'P002', 'P003'],
        'nome': ['Produto A', 'Produto B', 'Produto C'],
        'categoria': ['Eletrônicos', 'Roupas', 'Casa'],
        'estoque_atual': [150, 30, 80],
        'estoque_min': [50, 40, 60],
        'estoque_max': [300, 200, 250],
        'custo_unitario': [25.50, 15.75, 32.00]
    }
    template_df = pd.DataFrame(template_data)
    
    st.subheader("📄 Template da Planilha")
    st.dataframe(template_df, use_container_width=True)
    
    csv_template = template_df.to_csv(index=False)
    st.download_button(
        label="📥 Baixar Template",
        data=csv_template,
        file_name="template_estoque.csv",
        mime="text/csv",
        use_container_width=True
    )
    st.stop()

# Carregar dados
with st.spinner("📊 Carregando dados..."):
    produtos_df = carregar_planilha(sheets_url)

if produtos_df.empty:
    st.error("❌ Não foi possível carregar dados. Verifique a URL e permissões.")
    st.stop()

produtos_df = adicionar_status(produtos_df)

# Status da conexão
st.success(f"✅ {len(produtos_df)} produtos carregados • {datetime.now().strftime('%H:%M:%S')}")

# Métricas principais (mobile grid)
total_produtos = len(produtos_df)
produtos_ok = len(produtos_df[produtos_df['status'] == 'OK'])
produtos_atencao = len(produtos_df[produtos_df['status'] == 'ATENÇÃO'])
produtos_criticos = len(produtos_df[produtos_df['status'] == 'CRÍTICO'])

st.markdown(f"""
<div class="metric-grid fade-in">
    <div class="metric-card metric-info">
        <div class="metric-number">{total_produtos}</div>
        <div class="metric-label">Total</div>
    </div>
    <div class="metric-card metric-ok">
        <div class="metric-number">{produtos_ok}</div>
        <div class="metric-label">OK</div>
    </div>
    <div class="metric-card metric-warning">
        <div class="metric-number">{produtos_atencao}</div>
        <div class="metric-label">Atenção</div>
    </div>
    <div class="metric-card metric-danger">
        <div class="metric-number">{produtos_criticos}</div>
        <div class="metric-label">Crítico</div>
    </div>
</div>
""", unsafe_allow_html=True)

# Navegação por abas mobile
tab1, tab2, tab3 = st.tabs(["📦 Produtos", "📊 Gráficos", "📋 Relatórios"])

with tab1:
    # Filtros mobile
    st.markdown('<div class="mobile-filters">', unsafe_allow_html=True)
    
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        categoria_filter = st.selectbox(
            "📂 Categoria:",
            ['Todas'] + sorted(produtos_df['categoria'].unique().tolist()),
            key="mobile_cat"
        )
    
    with col_f2:
        status_filter = st.selectbox(
            "🚦 Status:",
            ['Todos', 'CRÍTICO', 'ATENÇÃO', 'OK'],
            key="mobile_status"
        )
    
    busca_produto = st.text_input("🔍 Buscar:", placeholder="Nome ou código...", key="mobile_search")
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Aplicar filtros
    df_filtrado = produtos_df.copy()
    
    if categoria_filter != 'Todas':
        df_filtrado = df_filtrado[df_filtrado['categoria'] == categoria_filter]
    
    if status_filter != 'Todos':
        df_filtrado = df_filtrado[df_filtrado['status'] == status_filter]
    
    if busca_produto:
        mask = (df_filtrado['nome'].str.contains(busca_produto, case=False, na=False) | 
                df_filtrado['codigo'].str.contains(busca_produto, case=False, na=False))
        df_filtrado = df_filtrado[mask]
    
    # Lista de produtos mobile
    if len(df_filtrado) > 0:
        st.markdown('<div class="product-list fade-in">', unsafe_allow_html=True)
        
        for _, produto in df_filtrado.iterrows():
            status_class = {
                'OK': 'status-ok',
                'ATENÇÃO': 'status-warning', 
                'CRÍTICO': 'status-danger'
            }.get(produto['status'], 'status-ok')
            
            st.markdown(f"""
            <div class="product-item">
                <div class="product-info">
                    <div class="product-name">{produto['semaforo']} {produto['nome']}</div>
                    <div class="product-details">{produto['codigo']} • {produto['categoria']} • Estoque: {produto['estoque_atual']}/{produto['estoque_min']}</div>
                </div>
                <div class="product-status">
                    <span class="status-badge {status_class}">{produto['status']}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)
        st.caption(f"📊 Mostrando {len(df_filtrado)} de {len(produtos_df)} produtos")
    else:
        st.info("🔍 Nenhum produto encontrado com os filtros aplicados")

with tab2:
    # Gráfico de distribuição mobile
    st.markdown('<div class="chart-container-mobile fade-in">', unsafe_allow_html=True)
    
    status_counts = produtos_df['status'].value_counts()
    
    fig_pie = px.pie(
        values=status_counts.values,
        names=status_counts.index,
        color=status_counts.index,
        color_discrete_map={
            'OK': '#28a745',
            'ATENÇÃO': '#ffc107',
            'CRÍTICO': '#dc3545'
        },
        title="📊 Distribuição por Status"
    )
    fig_pie.update_traces(textposition='inside', textinfo='percent+label')
    fig_pie.update_layout(
        height=300, 
        showlegend=False,
        font=dict(size=12),
        title_x=0.5
    )
    st.plotly_chart(fig_pie, use_container_width=True)
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Gráfico por categoria mobile
    st.markdown('<div class="chart-container-mobile fade-in">', unsafe_allow_html=True)
    
    categoria_stats = produtos_df.groupby('categoria').agg({
        'estoque_atual': 'sum',
        'codigo': 'count'
    }).reset_index()
    categoria_stats.columns = ['Categoria', 'Estoque Total', 'Qtd Produtos']
    
    fig_bar = px.bar(
        categoria_stats,
        x='Categoria',
        y='Estoque Total',
        title="📦 Estoque por Categoria",
        color='Estoque Total',
        color_continuous_scale='viridis'
    )
    fig_bar.update_layout(
        height=300,
        title_x=0.5,
        font=dict(size=12)
    )
    st.plotly_chart(fig_bar, use_container_width=True)
    
    st.markdown('</div>', unsafe_allow_html=True)

with tab3:
    # Seção de relatórios mobile
    st.markdown('<div class="report-section-mobile fade-in">', unsafe_allow_html=True)
    st.markdown("### 📋 Relatórios para Impressão")
    
    # Relatório de produtos críticos
    if st.button("🔴 Produtos Críticos", use_container_width=True, key="rel1"):
        produtos_criticos = produtos_df[produtos_df['status'] == 'CRÍTICO'].copy()
        
        if len(produtos_criticos) > 0:
            produtos_criticos['qtd_faltante'] = produtos_criticos['estoque_min'] - produtos_criticos['estoque_atual']
            produtos_criticos['valor_reposicao'] = produtos_criticos['qtd_faltante'] * produtos_criticos['custo_unitario']
            
            relatorio = produtos_criticos[['codigo', 'nome', 'categoria', 'estoque_atual', 'estoque_min', 'qtd_faltante', 'valor_reposicao']].copy()
            relatorio.columns = ['Código', 'Produto', 'Categoria', 'Atual', 'Mín', 'Faltante', 'Valor']
            
            st.markdown("#### 🔴 PRODUTOS CRÍTICOS")
            st.markdown(f"**📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}**")
            st.markdown(f"**📊 Total:** {len(produtos_criticos)} produtos")
            st.markdown(f"**💰 Valor reposição:** R$ {relatorio['Valor'].sum():,.2f}")
            
            st.dataframe(relatorio, use_container_width=True)
            
            csv_data = relatorio.to_csv(index=False)
            st.download_button(
                label="💾 Baixar CSV",
                data=csv_data,
                file_name=f"criticos_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        else:
            st.success("✅ Nenhum produto crítico!")
    
    # Relatório geral
    if st.button("📊 Relatório Geral", use_container_width=True, key="rel2"):
        relatorio_geral = produtos_df.copy()
        relatorio_geral['valor_estoque'] = relatorio_geral['estoque_atual'] * relatorio_geral['custo_unitario']
        
        relatorio_final = relatorio_geral[['codigo', 'nome', 'categoria', 'estoque_atual', 'estoque_min', 'status', 'valor_estoque']].copy()
        relatorio_final.columns = ['Código', 'Produto', 'Categoria', 'Atual', 'Mín', 'Status', 'Valor']
        
        st.markdown("#### 📊 RELATÓRIO GERAL")
        st.markdown(f"**📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}**")
        
        col_res1, col_res2 = st.columns(2)
        with col_res1:
            st.metric("Produtos", len(produtos_df))
            st.metric("Valor Total", f"R$ {relatorio_final['Valor'].sum():,.2f}")
        with col_res2:
            st.metric("Unidades", f"{relatorio_final['Atual'].sum():,.0f}")
            ocupacao = (produtos_df['estoque_atual'] / produtos_df['estoque_max'] * 100).mean()
            st.metric("Ocupação", f"{ocupacao:.1f}%")
        
        st.dataframe(relatorio_final, use_container_width=True)
        
        csv_data = relatorio_final.to_csv(index=False)
        st.download_button(
            label="💾 Baixar CSV",
            data=csv_data,
            file_name=f"geral_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True
        )
    
    st.markdown('</div>', unsafe_allow_html=True)

# Alertas críticos (sempre visível)
produtos_criticos_lista = produtos_df[produtos_df['status'] == 'CRÍTICO']
if len(produtos_criticos_lista) > 0:
    st.markdown(f"""
    <div class="alert-danger-mobile fade-in">
        <strong>🚨 {len(produtos_criticos_lista)} produto(s) crítico(s)!</strong><br>
        Necessária reposição urgente de estoque.
    </div>
    """, unsafe_allow_html=True)

# Auto-refresh
if auto_refresh:
    import time
    time.sleep(30)
    st.rerun()

# Footer mobile
st.markdown("""
<div class="footer-mobile">
    <strong>📦 Sistema de Controle de Estoque Mobile</strong><br>
    Versão otimizada para dispositivos móveis<br>
    <small>Última atualização: {}</small>
</div>
""".format(datetime.now().strftime("%d/%m/%Y %H:%M:%S")), unsafe_allow_html=True)
