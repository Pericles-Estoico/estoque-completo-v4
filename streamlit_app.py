elif tipo_analise == "Estrutura de Produto (BOM)":
    st.subheader("Estrutura de Produto (BOM)")
    st.markdown(
        """
    <div class="warning-box">
      Esta visão cruza a aba <b>estrutura_produto</b> com o estoque real da fábrica para responder:
      <ul>
        <li>Quantas peças finais cada estrutura permite produzir hoje?</li>
        <li>Quais componentes estão limitando a produção (gargalos)?</li>
        <li>Quais códigos de Semi / Gola / Bordado / extras não estão cadastrados no estoque?</li>
      </ul>
      <b>Novo:</b> você pode subir planilhas de vendas por canal para validar se existe no estoque e o que fabricar.
    </div>
    """,
        unsafe_allow_html=True,
    )

    estrutura_df = carregar_estrutura_produto()

    # =============================
    # HELPERS LOCAIS (BOM + VENDAS)
    # =============================
    estoque_by_key = {row["codigo_key"]: row for _, row in produtos_df.iterrows()}

    def get_prod_by_any_key(text):
        k = normalize_key(text)
        p = produtos_df[produtos_df["codigo_key"] == k]
        if not p.empty:
            return p.iloc[0]
        # tenta por nome
        p = produtos_df[produtos_df["nome_key"] == k]
        if not p.empty:
            return p.iloc[0]
        return None

    def split_codigos(codes_raw: str):
        if not codes_raw:
            return []
        return [c.strip() for c in str(codes_raw).split(",") if c.strip()]

    def bom_from_estrutura(codigo_final_txt: str):
        """
        Retorna lista de componentes para um produto final usando a aba estrutura_produto.
        Considera:
          - semi_codigo, gola_codigo, bordado_codigo (quando existirem como códigos reais)
          - componentes_codigos + quantidades
        """
        k = normalize_key(codigo_final_txt)
        linhas = estrutura_df[estrutura_df["codigo_final_key"] == k].copy()
        if linhas.empty:
            return []

        row = linhas.iloc[0]

        items = []

        # (A) SEMI / GOLA / BORDADO — só entra se parecer um "código" e não "Sem Gola"
        semi = str(row.get("semi_codigo", "")).strip()
        gola = str(row.get("gola_codigo", "")).strip()
        bord = str(row.get("bordado_codigo", "")).strip()

        def looks_like_code(x: str):
            x = str(x).strip().lower()
            if not x or x in {"sem gola", "sem bordado", "nao tem", "não tem", "none", "nan"}:
                return False
            return True

        if looks_like_code(semi):
            items.append(("Semi", semi, 1))
        if looks_like_code(gola):
            # sua planilha às vezes tem "Renda Gola (1 unidades) Renda Punho (2 unidades)"
            # aqui a gente tenta quebrar por espaços duplos e trata como "componente textual".
            # Melhor prática: padronizar isso como códigos separados em componentes_codigos.
            # Mesmo assim, vamos tentar:
            if "," in gola:
                for g in split_codigos(gola):
                    items.append(("Gola", g, 1))
            else:
                items.append(("Gola", gola, 1))

        if looks_like_code(bord):
            items.append(("Bordado", bord, 1))

        # (B) COMPONENTES EXTRAS
        cod_list = split_codigos(str(row.get("componentes_codigos", "")).strip())
        q_list = parse_int_list(str(row.get("quantidades", "")).strip())

        if len(q_list) < len(cod_list):
            q_list = q_list + [1] * (len(cod_list) - len(q_list))

        for cod, qtd in zip(cod_list, q_list):
            items.append(("Componente", cod, max(1, safe_int(qtd, 1))))

        return items

    def bom_from_template_kit(codigo_final_txt: str):
        """
        Se o produto for kit/conjunto pela template_estoque (eh_kit=sim),
        usa colunas componentes + quantidades.
        """
        p = get_prod_by_any_key(codigo_final_txt)
        if p is None:
            return []

        eh_kit = str(p.get("eh_kit", "")).strip().lower() == "sim"
        if not eh_kit:
            return []

        comps = split_codigos(str(p.get("componentes", "")).strip())
        quants = parse_int_list(str(p.get("quantidades", "")).strip())
        if len(quants) < len(comps):
            quants = quants + [1] * (len(comps) - len(quants))

        out = []
        for c, q in zip(comps, quants):
            out.append(("Item do Kit", c, max(1, safe_int(q, 1))))
        return out

    def avaliar_capacidade(componentes):
        """
        componentes: list[(tipo, codigo, qtd_por_final)]
        Retorna dataframe BOM com estoque e capacidade.
        """
        rows = []
        for tipo, cod, qtd_por in componentes:
            k = normalize_key(cod)
            prod = estoque_by_key.get(k)

            if prod is None:
                rows.append(
                    {
                        "Tipo": tipo,
                        "Código": cod,
                        "Produto": "NÃO CADASTRADO NO ESTOQUE",
                        "Categoria": "-",
                        "Qtd por peça final": qtd_por,
                        "Estoque atual": 0,
                        "Peças finais possíveis": 0,
                        "Situação": "❌ Não cadastrado",
                    }
                )
                continue

            est = safe_int(prod.get("estoque_atual", 0), 0)
            cap = est // max(1, int(qtd_por))
            situ = "✅ OK" if cap > 0 else "⚠️ Sem estoque"

            rows.append(
                {
                    "Tipo": tipo,
                    "Código": prod.get("codigo", cod),
                    "Produto": prod.get("nome", ""),
                    "Categoria": prod.get("categoria", ""),
                    "Qtd por peça final": int(qtd_por),
                    "Estoque atual": int(est),
                    "Peças finais possíveis": int(cap),
                    "Situação": situ,
                }
            )

        df = pd.DataFrame(rows)
        if df.empty:
            return df, 0, None
        gargalo = df.sort_values("Peças finais possíveis", ascending=True).iloc[0]
        capacidade_total = int(df["Peças finais possíveis"].min())
        return df, capacidade_total, gargalo

    def ler_vendas_upload(file):
        """
        Lê CSV/XLS/XLSX com colunas Código e Quantidade (aceita variações de header).
        Retorna df com colunas: codigo, quantidade
        """
        name = file.name.lower()
        if name.endswith(".csv"):
            df = None
            for enc in ["utf-8", "utf-8-sig", "latin1", "cp1252", "iso-8859-1"]:
                try:
                    file.seek(0)
                    df = pd.read_csv(file, encoding=enc)
                    break
                except Exception:
                    continue
            if df is None:
                raise ValueError("Não consegui ler o CSV. Salve como UTF-8.")
        elif name.endswith(".xlsx"):
            df = pd.read_excel(file, engine="openpyxl")
        elif name.endswith(".xls"):
            df = pd.read_excel(file, engine="xlrd")
        else:
            raise ValueError("Formato não suportado (use CSV/XLS/XLSX).")

        # normaliza headers
        def normcol(n):
            n = unicodedata.normalize("NFKD", str(n))
            n = "".join(ch for ch in n if not unicodedata.combining(ch))
            return n.lower().strip()

        df.rename(columns={c: normcol(c) for c in df.columns}, inplace=True)

        # tenta mapear
        col_code = None
        col_qty = None
        for c in df.columns:
            if c in {"codigo", "código", "sku", "cod", "id"}:
                col_code = c
            if c in {"quantidade", "qtd", "qtde", "qty"}:
                col_qty = c

        if col_code is None or col_qty is None:
            raise ValueError(f"Arquivo precisa de colunas Código e Quantidade. Colunas: {list(df.columns)}")

        out = df[[col_code, col_qty]].copy()
        out.columns = ["codigo", "quantidade"]
        out["codigo"] = out["codigo"].astype(str).str.strip()
        out["quantidade"] = out["quantidade"].apply(lambda x: safe_int(x, 0)).astype(int)
        out = out[(out["codigo"] != "") & (out["quantidade"] > 0)]
        out = out.groupby("codigo", as_index=False)["quantidade"].sum()
        return out

    # =============================
    # (1) UPLOAD DE VENDAS POR CANAL
    # =============================
    st.markdown("### 📤 Teste de Vendas por Canal (checar estoque + dizer o que fabricar)")

    colA, colB = st.columns([1, 2])
    with colA:
        canal = st.selectbox(
            "Canal",
            ["Shopee", "Shein", "Mercado Livre", "Site", "Atacado", "Outro"],
            index=0
        )
    with colB:
        arquivos = st.file_uploader(
            "Suba a planilha do canal (CSV/XLS/XLSX com Código + Quantidade)",
            type=["csv", "xls", "xlsx"],
            accept_multiple_files=True,
            key="vendas_canal_upload"
        )

    if arquivos:
        st.info(f"Arquivos recebidos: {len(arquivos)} | Canal: **{canal}**")

        # junta tudo em uma venda consolidada
        vendas_all = []
        erros = 0
        for f in arquivos:
            try:
                vendas_all.append(ler_vendas_upload(f))
            except Exception as e:
                erros += 1
                st.warning(f"Falha ao ler {f.name}: {e}")

        if vendas_all:
            vendas = pd.concat(vendas_all, ignore_index=True)
            vendas = vendas.groupby("codigo", as_index=False)["quantidade"].sum()

            # expande kits (se o canal manda kit, vira componentes)
            vendas_exp = expandir_kits(vendas, produtos_df)
            if "codigo_key" not in vendas_exp.columns:
                vendas_exp["codigo_key"] = vendas_exp["codigo"].map(normalize_key)

            # valida estoque do que foi vendido (após expansão)
            rel = []
            for _, r in vendas_exp.iterrows():
                key = r["codigo_key"]
                qtd = safe_int(r["quantidade"], 0)
                prod = estoque_by_key.get(key)

                if prod is None:
                    # não cadastrado: tentar BOM para desmembrar
                    codigo_original = r.get("codigo", "")
                    componentes = bom_from_template_kit(codigo_original)
                    if not componentes:
                        componentes = bom_from_estrutura(codigo_original)

                    if not componentes:
                        rel.append({
                            "Código": codigo_original,
                            "Produto": "NÃO CADASTRADO",
                            "Qtd vendida": qtd,
                            "Estoque atual": 0,
                            "Falta": qtd,
                            "Ação": "Cadastrar produto ou cadastrar BOM",
                            "Detalhe": "Sem estrutura encontrada"
                        })
                    else:
                        # desmembra: transforma venda do final em necessidade de componentes
                        for tipo, codc, qtd_por in componentes:
                            need = qtd * max(1, int(qtd_por))
                            kc = normalize_key(codc)
                            pc = estoque_by_key.get(kc)
                            estc = safe_int(pc.get("estoque_atual", 0), 0) if pc is not None else 0
                            falta = max(0, need - estc)
                            acao = "Produzir/Comprar" if falta > 0 else "OK"
                            rel.append({
                                "Código": f"[{codigo_original}] -> {codc}",
                                "Produto": (pc.get("nome", "NÃO CADASTRADO") if pc is not None else "NÃO CADASTRADO"),
                                "Qtd vendida": need,
                                "Estoque atual": estc,
                                "Falta": falta,
                                "Ação": acao,
                                "Detalhe": f"Desmembrado ({tipo})"
                            })
                else:
                    est = safe_int(prod.get("estoque_atual", 0), 0)
                    falta = max(0, qtd - est)
                    acao = "Produzir/Comprar" if falta > 0 else "OK"
                    rel.append({
                        "Código": prod.get("codigo", r.get("codigo", "")),
                        "Produto": prod.get("nome", ""),
                        "Qtd vendida": qtd,
                        "Estoque atual": est,
                        "Falta": falta,
                        "Ação": acao,
                        "Detalhe": "Produto simples (ou componente)"
                    })

            df_rel = pd.DataFrame(rel)

            st.markdown("#### ✅ Resultado do canal (o que está OK vs o que precisa fabricar)")
            st.dataframe(
                df_rel.sort_values(["Ação", "Falta"], ascending=[True, False]),
                use_container_width=True,
                height=420
            )

            st.download_button(
                "📥 Baixar relatório do canal (CSV)",
                df_rel.to_csv(index=False, encoding="utf-8-sig"),
                file_name=f"relatorio_canal_{normalize_key(canal)}_{datetime.now():%Y%m%d_%H%M%S}.csv",
                mime="text/csv"
            )

    st.markdown("---")

    # =============================
    # (2) BOM POR PRODUTO FINAL (manual)
    # =============================
    if estrutura_df.empty:
        st.warning("Aba 'estrutura_produto' vazia ou não encontrada. Confirme o nome da aba.")
    else:
        filtro = st.text_input(
            "🔍 Filtrar produto final (código ou nome)",
            "",
            placeholder="Ex.: Kit-4Pcs-Rococo-ML-RN",
        )

        if not filtro:
            st.info("Digite o código ou o nome do produto final para ver a estrutura.")
        else:
            # tenta BOM via KIT -> senão via ESTRUTURA
            componentes = bom_from_template_kit(filtro)
            origem = "template_estoque (kit/conjunto)" if componentes else None

            if not componentes:
                componentes = bom_from_estrutura(filtro)
                origem = "estrutura_produto (BOM)" if componentes else None

            prod_final = get_prod_by_any_key(filtro)
            codigo_final = prod_final["codigo"] if prod_final is not None else filtro
            nome_final = prod_final["nome"] if prod_final is not None else "(não encontrado no estoque)"
            categoria_final = prod_final["categoria"] if prod_final is not None else "-"

            st.markdown(
                f"### 🧩 Estrutura de: **{codigo_final} — {nome_final}**  "
                f"<br><small>Categoria: {categoria_final} | Origem: {origem or 'N/A'}</small>",
                unsafe_allow_html=True,
            )

            if not componentes:
                st.warning(
                    "Não encontrei estrutura para esse item.\n\n"
                    "✅ Se for produto simples, cadastre o código em `template_estoque`.\n"
                    "✅ Se for produto que depende de Semi/Gola/Bordado/Extras, cadastre o BOM na aba `estrutura_produto`.\n"
                    "✅ Se for kit/conjunto, marque `eh_kit=sim` e preencha `componentes` + `quantidades`."
                )
            else:
                df_bom, capacidade_total, gargalo = avaliar_capacidade(componentes)

                st.markdown(
                    f"#### 🔗 Gargalo da estrutura\n"
                    f"Com o estoque atual, dá pra produzir **até {capacidade_total} unidades** desse produto.",
                )

                if gargalo is not None:
                    st.info(
                        f"Gargalo: **{gargalo['Código']}** — {gargalo['Produto']} "
                        f"(capacidade {int(gargalo['Peças finais possíveis'])})"
                    )

                st.dataframe(
                    df_bom.sort_values("Peças finais possíveis", ascending=True),
                    use_container_width=True,
                    height=420,
                )

                st.download_button(
                    "📥 Baixar BOM (CSV)",
                    df_bom.to_csv(index=False, encoding="utf-8-sig"),
                    file_name=f"bom_{normalize_key(codigo_final)}_{datetime.now():%Y%m%d_%H%M%S}.csv",
                    mime="text/csv",
                )
