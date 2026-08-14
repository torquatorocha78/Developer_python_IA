import streamlit as st
import pandas as pd
from datetime import datetime
import database as db
import utils
import ai_analyzer
import report_generator

st.set_page_config(
    page_title="Gestão de Patentes do IFSC",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Inicializa o banco de dados
db.init_database()


def data_para_input(valor):
    if valor is None or pd.isna(valor) or valor == "":
        return None
    try:
        return pd.to_datetime(valor).date()
    except Exception:
        return None


def texto(valor):
    if valor is None or pd.isna(valor):
        return ""
    return str(valor)

st.markdown("""
<style>
    .status-verde { color: #00CC00; font-weight: bold; }
    .status-amarelo { color: #FFCC00; font-weight: bold; }
    .status-vermelho { color: #FF0000; font-weight: bold; }
    .status-pago { color: #0099FF; font-weight: bold; }
    .title-ifsc { text-align: center; color: #003366; }
</style>
""", unsafe_allow_html=True)

# Logo e Título Principal
st.markdown('<h1 class="title-ifsc">🏛️ Gestão de Patentes do IFSC</h1>', unsafe_allow_html=True)
st.markdown('<p style="text-align: center; color: #666;">Instituto Federal de Educação, Ciência e Tecnologia de Santa Catarina</p>', unsafe_allow_html=True)
st.divider()

st.sidebar.title("⚙️ Navegação")
pagina = st.sidebar.radio("Selecione uma página:", 
    ["📊 Dashboard", "➕ Adicionar Patente", "📁 Minhas Patentes", "📤 Importar Excel", "🤖 Análise IA", "📄 Gerar Relatórios"])

if pagina == "📊 Dashboard":
    st.title("📊 Dashboard de Patentes")

    df_patentes = db.obter_patentes()

    if len(df_patentes) == 0:
        st.info("📭 Nenhuma patente cadastrada ainda. Adicione uma patente para começar!")
    else:
        total_patentes = len(df_patentes)
        hoje = datetime.now().date()

        def data_anuidade(valor):
            try:
                return pd.to_datetime(valor).date()
            except Exception:
                return None

        def dados_prazo_ordinario(anu):
            if anu['status'] == 'nao_pagar' or anu['data_pagamento']:
                return None

            inicio_ord = data_anuidade(anu['data_inicio_ordinario'])
            fim_ord = data_anuidade(anu['data_fim_ordinario'])
            if not inicio_ord or not fim_ord or not (inicio_ord <= hoje <= fim_ord):
                return None

            dias_restantes = (fim_ord - hoje).days
            status = 'amarelo' if dias_restantes <= 30 else 'verde'
            return status, dias_restantes

        dados_dashboard = []

        for _, patente in df_patentes.iterrows():
            anuidades = db.obter_anuidades(patente['id'])
            for _, anu in anuidades.iterrows():
                prazo = dados_prazo_ordinario(anu)
                if not prazo:
                    continue

                status, dias_restantes = prazo
                emoji = utils.criar_emoji_status(status)
                dados_dashboard.append({
                    "ID": patente['id'],
                    "Processo": patente['numero_patente'],
                    "Título": patente.get('titulo') or "-",
                    "Deposito": utils.formatar_data(patente['data_deposito']),
                    "Status": f"{emoji} {status.upper()}",
                    "Anuidade": anu['numero_anuidade'],
                    "Fim Prazo Ordinário": utils.formatar_data(anu['data_fim_ordinario']),
                    "Dias p/ Vencer": dias_restantes,
                    "Gestor": patente.get('gestor', 'N/A'),
                    "Campus": patente.get('campus') or "-"
                })

        alertas_verde = sum(1 for item in dados_dashboard if '✅' in item["Status"])
        alertas_amarelo = sum(1 for item in dados_dashboard if '⚠️' in item["Status"])

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("📚 Total de Patentes", total_patentes)

        with col2:
            st.metric("📅 Em Prazo Ordinário", len(dados_dashboard))

        with col3:
            st.metric("✅ Normal", alertas_verde, delta="green")

        with col4:
            st.metric("⚠️ Atenção", alertas_amarelo, delta="orange")

        st.divider()

        st.subheader("Anuidades em Prazo Ordinário")

        df_dashboard = pd.DataFrame(dados_dashboard)

        def colorir_status(row):
            if '⚠️' in str(row['Status']):
                return ['background-color: #ffffcc'] * len(row)
            elif '✅' in str(row['Status']):
                return ['background-color: #ccffcc'] * len(row)
            else:
                return [''] * len(row)

        if df_dashboard.empty:
            st.info("Nenhuma anuidade está em prazo ordinário neste momento.")
        else:
            df_dashboard = df_dashboard.sort_values("Dias p/ Vencer")
            st.dataframe(
                df_dashboard.style.apply(colorir_status, axis=1),
                use_container_width=True,
                hide_index=True
            )

elif pagina == "➕ Adicionar Patente":
    st.title("➕ Adicionar Nova Patente")

    with st.form("form_nova_patente"):
        tab1, tab2, tab3 = st.tabs(["📌 Informações Básicas", "⚖️ Documentos e Atribuições", "📅 Prazos e Datas"])

        with tab1:
            col1, col2 = st.columns(2)
            with col1:
                id_externo = st.text_input("ID do Sistema (Opcional)", placeholder="Ex: 123")
                numero_patente = st.text_input("Número do Processo / Patente (Obrigatório)", placeholder="Ex: BR1020220000001")
                titulo = st.text_input("Título", placeholder="Título da patente")
                gestor = st.text_input("Gestor", placeholder="Ex: IFSC", value="IFSC")
            with col2:
                status_patente = st.selectbox(
                    "Status do Pedido",
                    ["Ativo", "Patente Concedida", "Tramitando Normal", "Indeferimento", "Recurso contra indeferimento", "Pedido de exame", "Arquivado", "Desistência"]
                )
                titular = st.text_input("Depositante / Titular", placeholder="Ex: IFSC")
                inventores = st.text_area("Nome dos Inventores", placeholder="Separe os nomes por / ou linha")
                campus = st.text_input("Campus", placeholder="Ex: Florianópolis")

        with tab2:
            col3, col4 = st.columns(2)
            with col3:
                modalidade_pi = st.text_input("Modalidade de PI", placeholder="Ex: Patente de Invenção")
                ipc_classificacao = st.text_input("IPC - Classificação", placeholder="Ex: H01L 21/00")
                acordo_titularidade = st.text_input("Acordo de Titularidade", placeholder="Ex: Sim, Não, Pendente")
            with col4:
                procuracao = st.text_input("Procuração", placeholder="Ex: Entregue, Não se aplica")
                termo_cessao = st.text_input("Termo de Cessão", placeholder="Ex: Assinado")
                atributos = st.text_area("Atributos Complementares", placeholder="Tags ou observações rápidas")

        with tab3:
            col5, col6 = st.columns(2)
            with col5:
                data_deposito = st.date_input("Data do Depósito (Obrigatório)")
                ano = st.number_input("Ano do Depósito", min_value=1990, max_value=2100, value=datetime.now().year)
                data_publicacao = st.date_input("Data da Publicação", value=None)
            with col6:
                data_concessao = st.date_input("Data da Concessão", value=None)
                data_exame = st.date_input("Data do Exame", value=None)

        descricao = st.text_area("Resumo / Descrição da Patente", placeholder="Descreva brevemente o objeto da patente")

        enviar = st.form_submit_button("✅ Cadastrar Patente", use_container_width=True, type="primary")

        if enviar:
            if not numero_patente or not data_deposito:
                st.error("❌ Por favor, preencha o campo de Processo (Número da Patente) e a Data do Depósito.")
            else:
                data_dep_str = data_deposito.strftime("%Y-%m-%d")
                data_conc_str = data_concessao.strftime("%Y-%m-%d") if data_concessao else None
                data_pub_str = data_publicacao.strftime("%Y-%m-%d") if data_publicacao else None
                data_ex_str = data_exame.strftime("%Y-%m-%d") if data_exame else None

                sucesso, mensagem = db.adicionar_patente(
                    numero=numero_patente,
                    data_dep=data_dep_str,
                    data_conc=data_conc_str,
                    descricao=descricao,
                    titular=titular,
                    gestor=gestor,
                    status_patente=status_patente,
                    titulo=titulo,
                    inventores=inventores,
                    campus=campus,
                    atributos=atributos,
                    id_externo=id_externo,
                    modalidade_pi=modalidade_pi,
                    ano=int(ano),
                    data_publicacao=data_pub_str,
                    data_exame=data_ex_str,
                    acordo_titularidade=acordo_titularidade,
                    procuracao=procuracao,
                    termo_cessao=termo_cessao,
                    ipc_classificacao=ipc_classificacao
                )

                if sucesso:
                    st.success(f"🎉 {mensagem}")
                    st.balloons()
                else:
                    st.error(f"❌ {mensagem}")

elif pagina == "📁 Minhas Patentes":
    st.title("📁 Gerenciar Patentes")

    df_patentes = db.obter_patentes()

    if len(df_patentes) == 0:
        st.info("📭 Nenhuma patente cadastrada. Vá em 'Adicionar Patente' ou 'Importar Excel' para começar.")
    else:
        busca = st.text_input("🔍 Filtrar por número, título, inventor, gestor, campus ou classificação:")
        df_filtrado = df_patentes.copy()
        if busca:
            termo = busca.lower()
            colunas_busca = ["numero_patente", "titulo", "inventores", "gestor", "campus", "ipc_classificacao", "id_externo"]
            mascara = pd.Series(False, index=df_filtrado.index)
            for coluna in colunas_busca:
                if coluna in df_filtrado:
                    mascara = mascara | df_filtrado[coluna].fillna("").astype(str).str.lower().str.contains(termo, regex=False)
            df_filtrado = df_filtrado[mascara]

        if len(df_filtrado) == 0:
            st.warning("Nenhuma patente correspondente aos filtros aplicados.")
            st.stop()

        opcoes = {
            f"{row['numero_patente']} - {row.get('titulo') or 'Sem título'}": row['numero_patente']
            for _, row in df_filtrado.iterrows()
        }
        patente_label = st.selectbox("Selecione uma patente para detalhar:", list(opcoes.keys()))
        patente_selecionada = opcoes[patente_label]

        patente_dados = df_patentes[df_patentes['numero_patente'] == patente_selecionada].iloc[0]
        patente_id = patente_dados['id']

        # Grid de Exibição das Novas Colunas
        st.subheader("📋 Detalhes da Patente")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("🔑 ID", patente_dados.get('id_externo') or "N/A")
            st.metric("🏛️ Processo", patente_dados['numero_patente'])
        with col2:
            st.metric("📅 Data do Depósito", utils.formatar_data(patente_dados['data_deposito']))
            st.metric("📅 Data da Concessão", utils.formatar_data(patente_dados['data_concessao']) if patente_dados['data_concessao'] else "Pendente")
        with col3:
            st.metric("🎯 Status do Pedido", patente_dados.get('status', 'Ativo'))
            st.metric("🔬 Modalidade de PI", patente_dados.get('modalidade_pi') or "N/A")
        with col4:
            st.metric("👤 Depositante / Titular", patente_dados['titular'] if patente_dados['titular'] else "N/A")
            st.metric("🏷️ IPC Classificação", patente_dados.get('ipc_classificacao') or "N/A")

        st.divider()

        with st.expander("📄 Ver Outros Atributos e Documentos"):
            col_doc1, col_doc2, col_doc3 = st.columns(3)
            with col_doc1:
                st.write(f"🤝 **Acordo de Titularidade:** {patente_dados.get('acordo_titularidade') or '-'}")
                st.write(f"🏫 **Campus:** {patente_dados.get('campus') or '-'}")
            with col_doc2:
                st.write(f"🛡️ **Procuração:** {patente_dados.get('procuracao') or '-'}")
                st.write(f"📅 **Data Exame:** {utils.formatar_data(patente_dados.get('data_exame'))}")
            with col_doc3:
                st.write(f"📝 **Termo de Cessão:** {patente_dados.get('termo_cessao') or '-'}")
                st.write(f"📅 **Data Publicação:** {utils.formatar_data(patente_dados.get('data_publicacao'))}")

        if patente_dados.get('descricao'):
            st.info(f"**Resumo / Descrição:**\n{patente_dados['descricao']}")

        st.divider()

        # Formulário de Edição
        with st.expander("✏️ Editar dados desta patente"):
            with st.form(f"form_editar_{patente_id}"):
                tab_edit1, tab_edit2, tab_edit3 = st.tabs(["📌 Básicos", "⚖️ Documentação", "📅 Datas"])

                with tab_edit1:
                    col_e1, col_e2 = st.columns(2)
                    with col_e1:
                        edit_id_externo = st.text_input("ID Externo", value=texto(patente_dados.get('id_externo')))
                        edit_numero = st.text_input("Número do Processo / Patente", value=texto(patente_dados.get('numero_patente')))
                        edit_titulo = st.text_input("Título", value=texto(patente_dados.get('titulo')))
                        edit_gestor = st.text_input("Gestor", value=texto(patente_dados.get('gestor')))
                    with col_e2:
                        edit_titular = st.text_area("Depositante / Titular", value=texto(patente_dados.get('titular')), height=90)
                        edit_inventores = st.text_area("Nome dos Inventores", value=texto(patente_dados.get('inventores')), height=90)
                        edit_status = st.text_input("Status do Pedido", value=texto(patente_dados.get('status')))
                        edit_campus = st.text_input("Campus", value=texto(patente_dados.get('campus')))

                with tab_edit2:
                    col_e3, col_e4 = st.columns(2)
                    with col_e3:
                        edit_modalidade = st.text_input("Modalidade de PI", value=texto(patente_dados.get('modalidade_pi')))
                        edit_ipc = st.text_input("IPC Classificação", value=texto(patente_dados.get('ipc_classificacao')))
                        edit_acordo = st.text_input("Acordo de Titularidade", value=texto(patente_dados.get('acordo_titularidade')))
                    with col_e4:
                        edit_procuracao = st.text_input("Procuração", value=texto(patente_dados.get('procuracao')))
                        edit_cessao = st.text_input("Termo de Cessão", value=texto(patente_dados.get('termo_cessao')))
                        edit_atributos = st.text_area("Atributos", value=texto(patente_dados.get('atributos')), height=90)

                with tab_edit3:
                    col_e5, col_e6 = st.columns(2)
                    with col_e5:
                        edit_data_dep = st.date_input("Data do Depósito", value=data_para_input(patente_dados.get('data_deposito')))
                        edit_ano = st.number_input("Ano", value=int(patente_dados.get('ano')) if patente_dados.get('ano') else datetime.now().year)
                        edit_data_pub = st.date_input("Data de Publicação", value=data_para_input(patente_dados.get('data_publicacao')))
                    with col_e6:
                        edit_data_conc = st.date_input("Data de Concessão", value=data_para_input(patente_dados.get('data_concessao')))
                        edit_data_exame = st.date_input("Data do Exame", value=data_para_input(patente_dados.get('data_exame')))

                edit_descricao = st.text_area("Resumo/Descrição", value=texto(patente_dados.get('descricao')), height=130)

                salvar = st.form_submit_button("💾 Salvar Alterações", use_container_width=True, type="primary")

                if salvar:
                    if not edit_numero or not edit_data_dep:
                        st.error("Preencha pelo menos o número do processo e a data do depósito.")
                    else:
                        ok, msg = db.atualizar_patente(
                            patente_id=patente_id,
                            numero=edit_numero,
                            data_dep=edit_data_dep.strftime("%Y-%m-%d") if edit_data_dep else None,
                            data_conc=edit_data_conc.strftime("%Y-%m-%d") if edit_data_conc else None,
                            descricao=edit_descricao,
                            titular=edit_titular,
                            gestor=edit_gestor,
                            status_patente=edit_status,
                            titulo=edit_titulo,
                            inventores=edit_inventores,
                            campus=edit_campus,
                            atributos=edit_atributos,
                            id_externo=edit_id_externo,
                            modalidade_pi=edit_modalidade,
                            ano=int(edit_ano) if edit_ano else None,
                            data_publicacao=edit_data_pub.strftime("%Y-%m-%d") if edit_data_pub else None,
                            data_exame=edit_data_exame.strftime("%Y-%m-%d") if edit_data_exame else None,
                            acordo_titularidade=edit_acordo,
                            procuracao=edit_procuracao,
                            termo_cessao=edit_cessao,
                            ipc_classificacao=edit_ipc
                        )
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

        st.divider()

        st.subheader("📊 Detalhamento de Anuidades")

        anuidades = db.obter_anuidades(patente_id)

        if anuidades.empty:
            st.warning("Nenhuma anuidade encontrada para esta patente. Verifique a data de depósito cadastrada.")
        else:
            dados_tabela = []
            for _, anu in anuidades.iterrows():
                if anu['status'] == 'nao_pagar':
                    emoji = '⛔'
                    status_display = 'NÃO PAGAR'
                    dias_restantes = '-'
                else:
                    status = utils.calcular_status_anuidade(
                        anu['data_inicio_ordinario'],
                        anu['data_fim_ordinario'],
                        anu['data_inicio_extraordinario'],
                        anu['data_fim_extraordinario'],
                        anu['data_pagamento']
                    )

                    dias_restantes = utils.obter_dias_restantes(
                        anu['data_fim_ordinario'],
                        anu['data_pagamento']
                    )

                    emoji = utils.criar_emoji_status(status)
                    status_display = status.upper()

                dados_tabela.append({
                    "Anuidade": anu['numero_anuidade'],
                    "Inicio Ordinario": utils.formatar_data(anu['data_inicio_ordinario']),
                    "Fim Ordinario": utils.formatar_data(anu['data_fim_ordinario']),
                    "Dias Restantes": dias_restantes if dias_restantes != '-' else ("Pago" if anu['data_pagamento'] else '-'),
                    "Status": f"{emoji} {status_display}",
                    "Data Pagamento": utils.formatar_data(anu['data_pagamento']) if anu['data_pagamento'] else "-"
                })

            df_tabela = pd.DataFrame(dados_tabela)

            def colorir_linhas(row):
                if '⛔' in str(row['Status']):
                    return ['background-color: #e6e6e6'] * len(row)
                elif '❌' in str(row['Status']):
                    return ['background-color: #ffcccc'] * len(row)
                elif '⚠️' in str(row['Status']):
                    return ['background-color: #ffffcc'] * len(row)
                elif '✅' in str(row['Status']):
                    return ['background-color: #ccffcc'] * len(row)
                elif '💰' in str(row['Status']):
                    return ['background-color: #ccddff'] * len(row)
                else:
                    return [''] * len(row)

            st.dataframe(
                df_tabela.style.apply(colorir_linhas, axis=1),
                use_container_width=True,
                hide_index=True
            )

            st.divider()

            st.subheader("💰 Registrar Pagamento / Marcar Anuidade")

            col1, col2, col3, col4 = st.columns(4)

            with col1:
                num_anuidade = st.selectbox(
                    "Selecione a anuidade",
                    anuidades['numero_anuidade'].tolist(),
                    key="select_anuidade"
                )

            with col2:
                data_pagamento_input = st.date_input(
                    "Data do Pagamento",
                    key="data_pag"
                )

            with col3:
                if st.button("✅ Registrar Pagamento", use_container_width=True):
                    db.atualizar_status_anuidade(
                        patente_id,
                        num_anuidade,
                        "pago",
                        data_pagamento_input.strftime("%Y-%m-%d")
                    )
                    st.success("✅ Pagamento registrado com sucesso!")
                    st.rerun()

            with col4:
                if st.button("🚫 Marcar Não Pagar", use_container_width=True):
                    db.atualizar_status_anuidade(
                        patente_id,
                        num_anuidade,
                        "nao_pagar"
                    )
                    st.success("✅ Anuidade marcada como não pagar!")
                    st.rerun()

        st.divider()

        if st.button("🗑️ Deletar Patente", use_container_width=True, type="secondary"):
            if st.checkbox("Tenho certeza que desejo deletar esta patente definitivamente?"):
                db.deletar_patente(patente_id)
                st.success("✅ Patente deletada com sucesso!")
                st.rerun()

elif pagina == "📤 Importar Excel":
    st.title("📤 Importar Patentes do Excel")

    st.info("""
    📋 O sistema aceita a importação automática das colunas da sua planilha original:
    - **ID** (Identificador do sistema)
    - **Status do Pedido** (Normalizado para Ativo, Patente Concedida, etc.)
    - **Processo** (Mapeado automaticamente para o Número da Patente)
    - **Modalidade de PI**
    - **Data da concessão**
    - **Depósito** (Formato: DD/MM/YYYY ou YYYY-MM-DD)
    - **Ano**
    - **Datada Publicação**
    - **Data Exame**
    - **ACORDO DE TITULARIDADE**
    - **PROCURAÇÃO**
    - **TERMO DE CESSÃO**
    - **GESTOR**
    - **Depositante/ Titular**
    - **Título**
    - **NOME DOS INVENTORES**
    - **Resumo** (Armazenado na descrição do sistema)
    - **IPC- CLASSIFICAÇÃO**
    """)

    arquivo_excel = st.file_uploader(
        "Selecione um arquivo Excel (.xlsx)",
        type="xlsx"
    )

    if arquivo_excel:
        st.subheader("🔎 Análise Preliminar da Planilha")
        problemas = db.analisar_inconsistencias_excel(arquivo_excel)

        if problemas:
            for problema in problemas:
                st.warning(problema)
        else:
            st.success("✅ Estrutura da planilha verificada com sucesso!")

        arquivo_excel.seek(0)

        if st.button("📥 Importar Dados", use_container_width=True, type="primary"):
            with st.spinner("Efetuando importação em lote de alta performance..."):
                resultados = db.importar_excel(arquivo_excel)

            st.subheader("📊 Relatório de Importação")

            sucesso_count = sum(1 for _, sucesso, _ in resultados if sucesso)
            erro_count = len(resultados) - sucesso_count

            col1, col2 = st.columns(2)
            with col1:
                st.metric("✅ Importadas com Sucesso", sucesso_count)
            with col2:
                st.metric("❌ Inconsistências / Erros", erro_count)

            dados_resultados = []
            for patente, sucesso, mensagem in resultados:
                dados_resultados.append({
                    "Identificador / Processo": patente,
                    "Status": "✅ Sucesso" if sucesso else "❌ Erro",
                    "Ação / Mensagem": mensagem
                })

            df_resultados = pd.DataFrame(dados_resultados)
            st.dataframe(df_resultados, use_container_width=True, hide_index=True)

            if sucesso_count > 0:
                st.success(f"🎉 {sucesso_count} patente(s) importada(s)/atualizada(s) no sistema!")
                st.balloons()

elif pagina == "🤖 Análise IA":
    st.title("🤖 Análise Inteligente de Patentes")
    st.markdown("""Utilize a IA para fazer perguntas e análises sobre suas patentes.""")

    df_patentes = db.obter_patentes()

    if len(df_patentes) == 0:
        st.warning("⚠️ Nenhuma patente cadastrada. Primeiro, adicione algumas patentes.")
    else:
        st.divider()

        col1, col2 = st.columns([3, 1])

        with col1:
            pergunta = st.text_input(
                "Faça uma pergunta sobre suas patentes:",
                placeholder="Ex: Quantas patentes foram concedidas? Quais estão vencidas? Qual é o status das patentes do IFSC?"
            )

        with col2:
            analizar = st.button("🔍 Analisar", use_container_width=True)

        if analizar and pergunta:
            with st.spinner("Analisando dados..."):
                resposta = ai_analyzer.analisar_pergunta(df_patentes, pergunta)
                st.markdown("### 📋 Resposta:")
                st.info(resposta)

        st.divider()

        st.subheader("📊 Análises Rápidas")

        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("📈 Estatísticas Gerais", use_container_width=True):
                stats = ai_analyzer.gerar_estatisticas(df_patentes)
                st.markdown(stats)

        with col2:
            if st.button("🎯 Patentes por Gestor", use_container_width=True):
                gestores = ai_analyzer.patentes_por_gestor(df_patentes)
                st.markdown(gestores)

        with col3:
            if st.button("⚠️ Alertas Urgentes", use_container_width=True):
                alertas = ai_analyzer.gerar_alertas(df_patentes)
                st.markdown(alertas)

elif pagina == "📄 Gerar Relatórios":
    st.title("📄 Geração de Relatórios em PDF")

    df_patentes = db.obter_patentes()

    if len(df_patentes) == 0:
        st.warning("⚠️ Nenhuma patente cadastrada. Primeiro, adicione algumas patentes.")
    else:
        st.subheader("Escolha o tipo de relatório:")

        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("📋 Relatório Completo", use_container_width=True):
                with st.spinner("Gerando relatório completo..."):
                    pdf = report_generator.gerar_relatorio_completo(df_patentes)
                    st.download_button(
                        "📥 Baixar Relatório Completo",
                        data=pdf,
                        file_name="relatorio_completo.pdf",
                        mime="application/pdf"
                    )

        with col2:
            if st.button("📊 Relatório de Anuidades", use_container_width=True):
                with st.spinner("Gerando relatório de anuidades..."):
                    pdf = report_generator.gerar_relatorio_anuidades(df_patentes)
                    st.download_button(
                        "📥 Baixar Relatório Anuidades",
                        data=pdf,
                        file_name="relatorio_anuidades.pdf",
                        mime="application/pdf"
                    )

        with col3:
            if st.button("⚠️ Relatório de Alertas", use_container_width=True):
                with st.spinner("Gerando relatório de alertas..."):
                    pdf = report_generator.gerar_relatorio_alertas(df_patentes)
                    st.download_button(
                        "📥 Baixar Relatório Alertas",
                        data=pdf,
                        file_name="relatorio_alertas.pdf",
                        mime="application/pdf"
                    )

        st.divider()

        st.subheader("📊 Exportação de Dados")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("📥 Exportar para Excel", use_container_width=True):
                excel_buffer = report_generator.exportar_para_excel(df_patentes)
                st.download_button(
                    "📥 Baixar Excel",
                    data=excel_buffer,
                    file_name="patentes_export.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

        with col2:
            if st.button("📤 Exportar para CSV", use_container_width=True):
                csv_buffer = report_generator.exportar_para_csv(df_patentes)
                st.download_button(
                    "📥 Baixar CSV",
                    data=csv_buffer,
                    file_name="patentes_export.csv",
                    mime="text/csv"
                )
