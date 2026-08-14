import streamlit as st
import shlex
import subprocess
from pathlib import Path
from database import (
    init_db, create_project, list_projects, get_project, update_project_memory,
    save_file, list_files, get_file, save_message, list_messages,
    get_file_versions, rollback_file_to_version, get_workspace_path, sync_project_to_disk
)
from file_manager import extract_uploaded_files, generate_diff, create_project_zip, build_file_tree
from ai_engine import ask_gemini, parse_ai_commands

st.set_page_config(page_title="Python AI Agent Developer", page_icon="🤖", layout="wide")

init_db()

st.title("🤖 Python AI Agent Developer")
st.caption("Ambiente de desenvolvimento ativo por Agentes IA — Streamlit + Gemini")

# Inicialização dos estados da sessão
if "project_id" not in st.session_state:
    st.session_state.project_id = None
if "selected_file_id" not in st.session_state:
    st.session_state.selected_file_id = None
if "last_ai_raw" not in st.session_state:
    st.session_state.last_ai_raw = None
if "proposed_changes" not in st.session_state:
    st.session_state.proposed_changes = []
if "terminal_output" not in st.session_state:
    st.session_state.terminal_output = ""
if "terminal_error" not in st.session_state:
    st.session_state.terminal_error = ""
if "last_command" not in st.session_state:
    st.session_state.last_command = "python "

# Barra Lateral (Projetos e Exportações)
with st.sidebar:
    st.header("📁 Projetos")

    with st.form("new_project"):
        project_name = st.text_input("Nome do novo projeto")
        project_desc = st.text_area("Descrição", height=80)
        submitted = st.form_submit_button("Criar projeto", use_container_width=True)
        if submitted and project_name.strip():
            pid = create_project(project_name.strip(), project_desc.strip())
            st.session_state.project_id = pid
            st.rerun()

    projects = list_projects()
    if projects:
        project_labels = {f"{p['name']}  •  #{p['id']}": p["id"] for p in projects}
        current_pid = st.session_state.project_id

        default_index = 0
        if current_pid:
            for i, p in enumerate(projects):
                if p["id"] == current_pid:
                    default_index = i
                    break

        selected_label = st.selectbox("Projeto ativo", list(project_labels.keys()), index=default_index)
        st.session_state.project_id = project_labels[selected_label]

    st.divider()

    st.header("⚙️ Configurações de IA")
    model = st.selectbox(
        "Modelo Gemini",
        ["gemini-2.5-flash", "gemini-3.5-flash"],
        index=0,
        help="Modelos de alta performance para codificação e testes rápidos.",
    )

    if st.session_state.project_id:
        st.divider()
        st.header("📦 Exportar")
        try:
            zip_data = create_project_zip(st.session_state.project_id)
            st.download_button(
                label="📥 Baixar Projeto corrigido em ZIP",
                data=zip_data,
                file_name=f"projeto_{st.session_state.project_id}.zip",
                mime="application/zip",
                use_container_width=True
            )
        except Exception as e:
            st.error(f"Erro ao empacotar ZIP: {e}")

if not st.session_state.project_id:
    st.info("Crie ou selecione um projeto na barra lateral para começar.")
    st.stop()

# Sincroniza arquivos do banco em disco para as execuções locais
sync_project_to_disk(st.session_state.project_id)

project = get_project(st.session_state.project_id)

st.subheader(f"Projeto Ativo: {project['name']}")
if project["description"]:
    st.caption(project["description"])

# Definição das Abas principais estilo Cursor
tab_agent, tab_explorer, tab_runner, tab_memory, tab_history = st.tabs([
    "💻 Agente Workspace",
    "📂 Explorer (Estilo VS Code)",
    "🧪 Executar Código & Testes",
    "🧠 Memória do Projeto",
    "💬 Histórico Geral"
])

# Sandboxing de segurança para evitar execução de comandos destrutivos ou maliciosos
def execute_safe_command(cmd_str):
    # Lista negra de substrings de comandos perigosos
    dangerous_keywords = ["rm ", "mv ", "sudo", "chmod", "chown", "dd", "mkfs", "wget", "curl", "bash", "sh", ">", "|"]
    for word in dangerous_keywords:
        if word in cmd_str:
            return False, f"Comando bloqueado por segurança: Contém palavra-chave restrita '{word}'."

    args = shlex.split(cmd_str)
    if not args:
        return False, "Comando vazio."

    # Whitelist estrita de comandos executores
    allowed_executables = {"python", "python3", "pytest", "pip"}
    executable = Path(args[0]).name
    if executable not in allowed_executables:
        return False, f"Apenas execuções começando com {list(allowed_executables)} são permitidas."

    workspace_dir = get_workspace_path(st.session_state.project_id)
    try:
        sync_project_to_disk(st.session_state.project_id)

        result = subprocess.run(
            args,
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            timeout=30
        )
        output = result.stdout
        error_output = result.stderr
        success = result.returncode == 0
        return success, f"SAÍDA (stdout):\n{output}\n\nERROS / TRACEBACKS (stderr):\n{error_output}"
    except subprocess.TimeoutExpired:
        return False, "Erro: Execução excedeu o limite máximo de tempo (Timeout de 30s)."
    except Exception as e:
        return False, f"Erro de execução de processo: {str(e)}"

# 1. AGENTE WORKSPACE TAB
with tab_agent:
    st.markdown("### 🤖 O que o Agente de Programação deve fazer?")

    # Injetor rápido para envio de tracebacks vindos do terminal
    default_prompt_val = ""
    if "quick_fix_traceback" in st.session_state and st.session_state.quick_fix_traceback:
        default_prompt_val = (
            f"Ocorreu um erro de execução. Por favor analise o traceback abaixo e corrija o(s) arquivo(s) afetado(s):\n\n"
            f"```\n{st.session_state.quick_fix_traceback}\n```"
        )
        del st.session_state.quick_fix_traceback

    prompt = st.text_area(
        "Prompt",
        height=180,
        value=default_prompt_val,
        placeholder="Descreva as modificações, erros, novos scripts ou funcionalidades desejadas...",
        key="main_prompt"
    )

    col_b1, col_b2, col_b3, col_b4 = st.columns(4)
    selected_action = None
    if col_b1.button("🔎 Analisar Código", use_container_width=True):
        selected_action = "analisar"
    if col_b2.button("💻 Criar / Alterar Código", use_container_width=True):
        selected_action = "codigo"
    if col_b3.button("🐞 Corrigir Erros", use_container_width=True):
        selected_action = "corrigir"
    if col_b4.button("🚀 Otimizar", use_container_width=True):
        selected_action = "melhorar"

    if selected_action:
        if not prompt.strip():
            st.warning("Descreva o seu objetivo no prompt antes de executar.")
        else:
            project_files = list_files(st.session_state.project_id)
            context_parts = []
            for f in project_files:
                content = get_file(f["id"])
                if content:
                    context_parts.append(f"### ARQUIVO: {f['path']}\n```\n{content['content']}\n```")
            context = "\n\n".join(context_parts)

            # Recupera as diretrizes permanentes de memória do projeto
            proj_memory = project.get("memory", "")
            memory_context = f"\nREGRAS E MEMÓRIA PERMANENTE DO PROJETO:\n{proj_memory}\n" if proj_memory else ""

            action_instruction = {
                "analisar": "Analise o problema, identifique causas e descreva de forma concisa quais arquivos precisam mudar.",
                "codigo": "Desenvolva a solução completa. Sempre que alterar ou criar um arquivo, insira seu conteúdo integral entre tags: <write_file path=\"caminho/do/arquivo\">CONTEUDO COMPLETO DO ARQUIVO</write_file>.",
                "corrigir": "Analise o traceback ou bug indicado, explique a correção e aplique-a nos arquivos usando obrigatoriamente a estrutura: <write_file path=\"caminho/do/arquivo\">CONTEUDO INTEGRAL CORRIGIDO</write_file>.",
                "melhorar": "Refatore e aperfeiçoe o código. Se fizer alterações, entregue os arquivos reestruturados na tag <write_file path=\"caminho/do/arquivo\">CONTEUDO</write_file>."
            }[selected_action]

            final_prompt = f"""
Você é um Engenheiro de Software Python Sênior especialista em desenvolvimento rápido de agentes autônomos.
Seu objetivo é guiar e evoluir o projeto do usuário.

REGRAS CRÍTICAS PARA ALTERAÇÃO DE ARQUIVOS:
- Sempre que criar, alterar ou corrigir um arquivo, encapsule TODO o conteúdo do arquivo dentro de:
  <write_file path="nome_do_arquivo_com_caminho_relativo">
  CONTEÚDO COMPLETO AQUI
  </write_file>
- Nunca omita partes de códigos com '...' ou marque como 'restante do código igual'. Escreva o arquivo COMPLETO.
- Você pode propor modificações em múltiplos arquivos num único turno de resposta.

CONTEXTO DE MEMÓRIA DO PROJETO:
{memory_context}

PROBLEMA DO USUÁRIO:
{prompt}

TAREFA:
{action_instruction}

ARQUIVOS ATUAIS DO PROJETO:
{context if context else "(nenhum arquivo foi enviado ainda)"}

Responda em português de forma clara e instrutiva.
"""
            with st.spinner("O Agente IA está analisando os arquivos e gerando solução..."):
                try:
                    raw_answer = ask_gemini(final_prompt, model=model)
                    save_message(st.session_state.project_id, "user", prompt)
                    save_message(st.session_state.project_id, "assistant", raw_answer)

                    st.session_state.last_ai_raw = raw_answer
                    st.session_state.proposed_changes = parse_ai_commands(raw_answer)
                    st.success("Resposta gerada!")
                except Exception as e:
                    st.error(f"Erro ao consultar a IA: {e}")

    # Exibição de resposta do Agente e Bloco de Aprovação de Alterações
    if st.session_state.last_ai_raw:
        st.markdown("### 💬 Resposta do Agente")
        st.markdown(st.session_state.last_ai_raw)

        if st.session_state.proposed_changes:
            st.divider()
            st.subheader("🛠️ Modificações Propostas pelo Agente")
            st.info("Revise com cuidado a diferença (diff) abaixo antes de aplicar as mudanças diretamente no projeto.")

            all_files_by_path = {f["path"]: get_file(f["id"]) for f in list_files(st.session_state.project_id)}

            for change in st.session_state.proposed_changes:
                filepath = change["path"]
                new_code = change["content"]

                old_code = ""
                is_new_file = True
                if filepath in all_files_by_path:
                    old_code = all_files_by_path[filepath]["content"]
                    is_new_file = False

                with st.expander(f"📝 Ver alteração para: `{filepath}`" + (" (Novo Arquivo)" if is_new_file else " (Modificado)"), expanded=True):
                    if is_new_file:
                        st.code(new_code, language="python")
                    else:
                        diff_text = generate_diff(old_code, new_code, filepath)
                        st.code(diff_text, language="diff")

                    # Botão para aplicar apenas este arquivo individualmente
                    col_app_btn, _ = st.columns([1.5, 3.5])
                    if col_app_btn.button(f"Aplicar mudanças em {filepath}", key=f"apply_ind_{filepath}"):
                        ext = Path(filepath).suffix.lower()
                        save_file(st.session_state.project_id, filepath, new_code, ext)
                        st.success(f"Arquivo `{filepath}` atualizado!")
                        st.session_state.proposed_changes = [c for c in st.session_state.proposed_changes if c["path"] != filepath]
                        st.rerun()

            st.markdown("---")
            if st.button("🚀 Aplicar TODAS as alterações sugeridas", type="primary", use_container_width=True):
                for change in st.session_state.proposed_changes:
                    filepath = change["path"]
                    new_code = change["content"]
                    ext = Path(filepath).suffix.lower()
                    save_file(st.session_state.project_id, filepath, new_code, ext)

                st.success("Todos os arquivos foram atualizados! Versões de backup prontas para Rollback.")
                st.session_state.proposed_changes = []
                st.rerun()

# 2. EXPLORER (ESTILO VS CODE) TAB
with tab_explorer:
    st.markdown("### 📂 Arquivos no Workspace")

    with st.expander("📥 Enviar novos arquivos/zip para o projeto", expanded=False):
        uploads = st.file_uploader(
            "Selecione códigos, documentações ou arquivos ZIP",
            type=["py", "txt", "json", "csv", "xlsx", "xls", "docx", "pdf", "zip", "md", "toml", "yaml", "yml"],
            accept_multiple_files=True,
            key="uploader"
        )
        if st.button("Salvar Uploads", use_container_width=True):
            if uploads:
                count = 0
                for uploaded in uploads:
                    extracted = extract_uploaded_files(uploaded)
                    for item in extracted:
                        save_file(
                            st.session_state.project_id,
                            item["path"],
                            item["content"],
                            item["extension"],
                        )
                        count += 1
                st.success(f"{count} arquivo(s) salvos com sucesso!")
                st.rerun()

    files = list_files(st.session_state.project_id)
    if not files:
        st.info("Nenhum arquivo cadastrado. Peça para a IA criar códigos!")
    else:
        tree = build_file_tree(files)
        col_tree, col_viewer = st.columns([2, 3])

        with col_tree:
            st.markdown("**Árvore de Diretórios (Selecione um arquivo)**")

            def render_tree(node, depth=0):
                for name, value in sorted(node.items()):
                    if "id" not in value:
                        # Pasta
                        with st.expander(f"📁 {' ' * (depth*2)}{name}", expanded=True):
                            render_tree(value, depth + 1)
                    else:
                        # Arquivo
                        file_id = value["id"]
                        icon = "📄"
                        if value["extension"] == ".py":
                            icon = "🐍"
                        elif value["extension"] in [".json", ".yaml", ".toml"]:
                            icon = "⚙️"
                        elif value["extension"] == ".md":
                            icon = "📝"

                        if st.button(f"{icon} {name}", key=f"tree_f_{file_id}", use_container_width=True):
                            st.session_state.selected_file_id = file_id

            render_tree(tree)

        with col_viewer:
            if st.session_state.selected_file_id:
                selected = get_file(st.session_state.selected_file_id)
                if selected:
                    st.markdown(f"#### Editando: `{selected['path']}`")

                    edited_code = st.text_area(
                        "Visualização de Código",
                        value=selected["content"],
                        height=400,
                        key=f"editor_{selected['id']}"
                    )

                    c_ed1, c_ed2 = st.columns(2)
                    if c_ed1.button("Salvar alterações manuais", use_container_width=True, type="primary"):
                        save_file(
                            st.session_state.project_id,
                            selected["path"],
                            edited_code,
                            selected["extension"]
                        )
                        st.success("Arquivo atualizado e nova versão salva no histórico!")
                        st.rerun()

                    # Lista de Versões e Reversão (Rollback)
                    st.markdown("##### 📜 Histórico de Versões")
                    versions = get_file_versions(selected["id"])
                    if not versions:
                        st.caption("Apenas a versão original registrada.")
                    else:
                        for v in versions:
                            col_v1, col_v2 = st.columns([3, 1])
                            col_v1.caption(f"Versão #{v['version']} - Modificada em {v['created_at']}")
                            if col_v2.button("Restaurar", key=f"roll_{v['id']}"):
                                if rollback_file_to_version(selected["id"], v["id"]):
                                    st.success(f"Restaurado para a versão #{v['version']}!")
                                    st.rerun()

# 3. TERMINAL AND CODE RUNNER TAB (Execução e capturas)
with tab_runner:
    st.markdown("### 🧪 Terminal do Workspace")
    st.caption("Rode scripts locais e testes unitários com segurança do Sandbox. Ex: `python main.py` ou `pytest`")

    cmd_input = st.text_input(
        "Executar comando no terminal",
        value=st.session_state.last_command,
        placeholder="python script.py"
    )
    st.session_state.last_command = cmd_input

    if st.button("⚡ Executar comando", use_container_width=True, type="primary"):
        with st.spinner("Executando processo..."):
            success, output = execute_safe_command(cmd_input)
            st.session_state.terminal_output = output
            if not success:
                st.session_state.terminal_error = output
            else:
                st.session_state.terminal_error = ""

    if st.session_state.terminal_output:
        st.markdown("**Resultado da Execução:**")
        st.code(st.session_state.terminal_output, language="bash")

        # Se houver erro ou traceback, exibe atalho de autocorreção
        if "Traceback" in st.session_state.terminal_output or "Error" in st.session_state.terminal_output or st.session_state.terminal_error:
            st.error("⚠️ Detectamos erros na execução do código do projeto!")

            if st.button("🤖 Enviar erro detectado para Correção do Agente", type="primary", use_container_width=True):
                st.session_state.quick_fix_traceback = st.session_state.terminal_output
                st.info("Traceback de erro copiado! Abra a aba 'Agente Workspace' para iniciar a correção automática.")
                st.rerun()

# 4. PERMANENT MEMORY TAB (Configurações persistentes)
with tab_memory:
    st.markdown("### 🧠 Memória Permanente do Projeto")
    st.write(
        "Forneça diretrizes técnicas de arquitetura que a IA sempre lembrará de seguir ao criar soluções."
    )

    current_memory = project.get("memory", "")
    new_memory = st.text_area(
        "Instruções e Memória de Contexto",
        value=current_memory,
        height=300,
        placeholder="Exemplo:\n- Sempre escreva testes unitários utilizando pytest.\n- Utilize sempre o banco de dados SQLite local.\n- Prefira funções puras e de responsabilidade única."
    )

    if st.button("Gravar Memória", use_container_width=True):
        update_project_memory(st.session_state.project_id, new_memory)
        st.success("Memória do projeto gravada e integrada no motor de prompts!")
        st.rerun()

# 5. GENERAL MESSAGES HISTORY TAB
with tab_history:
    st.markdown("### 💬 Histórico de Conversas")
    messages = list_messages(st.session_state.project_id)
    if not messages:
        st.info("Nenhuma interação registrada neste projeto ainda.")
    else:
        for msg in messages:
            with st.chat_message("user" if msg["role"] == "user" else "assistant"):
                st.markdown(msg["content"])