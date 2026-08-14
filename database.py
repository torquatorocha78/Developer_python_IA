import sqlite3
import pandas as pd
from datetime import date
import unicodedata
from typing import List, Dict, Tuple, Any, Optional

DB_NAME = "patentes.db"


def conectar() -> sqlite3.Connection:
    """Retorna uma conexão configurada para o SQLite."""
    return sqlite3.connect(DB_NAME, check_same_thread=False)


def init_database() -> None:
    """Inicializa o banco de dados e aplica migrações de novas colunas."""
    with conectar() as conn:
        cur = conn.cursor()

        # Criar tabela de patentes caso não exista
        cur.execute("""
        CREATE TABLE IF NOT EXISTS patentes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero_patente TEXT UNIQUE,
            data_deposito DATE,
            data_concessao DATE,
            descricao TEXT,
            titular TEXT,
            gestor TEXT,
            status TEXT
        )
        """)

        # Obter colunas já existentes para fazer migração dinâmica se necessário
        colunas_existentes = {
            row[1] for row in cur.execute("PRAGMA table_info(patentes)").fetchall()
        }

        # Dicionário mapeando as novas colunas solicitadas
        novas_colunas = {
            "titulo": "TEXT",
            "inventores": "TEXT",
            "campus": "TEXT",
            "atributos": "TEXT",
            "id_externo": "TEXT",           # Coluna ID do Excel
            "modalidade_pi": "TEXT",        # Modalidade de PI
            "ano": "INTEGER",               # Ano
            "data_publicacao": "DATE",      # Datada Publicação
            "data_exame": "DATE",           # Data Exame
            "acordo_titularidade": "TEXT",  # ACORDO DE TITULARIDADE
            "procuracao": "TEXT",           # PROCURAÇÃO
            "termo_cessao": "TEXT",         # TERMO DE CESSÃO
            "ipc_classificacao": "TEXT"     # IPC- CLASSIFICAÇÃO
        }

        # Aplica ALTER TABLE de forma segura para cada nova coluna faltante
        for coluna, tipo in novas_colunas.items():
            if coluna not in colunas_existentes:
                cur.execute(f"ALTER TABLE patentes ADD COLUMN {coluna} {tipo}")

        # Tabela de anuidades
        cur.execute("""
        CREATE TABLE IF NOT EXISTS anuidades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patente_id INTEGER,
            numero_anuidade INTEGER,
            data_inicio_ordinario DATE,
            data_fim_ordinario DATE,
            data_inicio_extraordinario DATE,
            data_fim_extraordinario DATE,
            data_pagamento DATE,
            status TEXT,
            FOREIGN KEY (patente_id) REFERENCES patentes(id)
        )
        """)
        conn.commit()

    garantir_anuidades_existentes()


def obter_patentes() -> pd.DataFrame:
    """Retorna todas as patentes em um DataFrame do Pandas."""
    with conectar() as conn:
        df = pd.read_sql("SELECT * FROM patentes ORDER BY id", conn)
    return df


def _valor_limpo(valor: Any) -> Optional[Any]:
    if pd.isna(valor):
        return None
    if isinstance(valor, str):
        valor = valor.strip()
        return valor or None
    return valor


def _normalizar_coluna(coluna: str) -> str:
    """Normaliza nomes de colunas removendo acentos, pontuações e espaçamentos."""
    texto = str(coluna).strip().lower()
    texto = "".join(
        c for c in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(c)
    )
    for char in ["/", "\\", "-", ".", "(", ")", ":", ";", "_"]:
        texto = texto.replace(char, " ")
    return "_".join(texto.split())


def _normalizar_status(status: Any) -> str:
    status = _valor_limpo(status)
    if not status:
        return "Ativo"

    status_texto = str(status).strip()
    chave = _normalizar_coluna(status_texto)
    mapa = {
        "patente_concedida": "Patente Concedida",
        "patente_concedda": "Patente Concedida",
        "concedido": "Patente Concedida",
        "concessao": "Patente Concedida",
        "tramitando_normal": "Tramitando Normal",
        "infederimento": "Indeferimento",
        "indeferimento": "Indeferimento",
        "recurso_contra_indeferimento": "Recurso contra indeferimento",
        "pedido_de_exame": "Pedido de exame",
        "transferida_a_titularidade": "Transferida a titularidade",
        "arquivado": "Arquivado",
        "desistencia": "Desistência"
    }
    return mapa.get(chave, status_texto)


def _parse_data(valor: Any) -> Optional[str]:
    valor = _valor_limpo(valor)
    if valor is None:
        return None
    if hasattr(valor, "date") and not isinstance(valor, str):
        return valor.date().isoformat()

    texto = str(valor).strip()
    if not texto:
        return None

    try:
        partes = texto.replace("-", "/").split("/")
        if len(partes) == 3 and all(p.isdigit() for p in partes):
            primeiro, segundo = int(partes[0]), int(partes[1])
            dayfirst = primeiro > 12 or segundo <= 12
            data = pd.to_datetime(texto, dayfirst=dayfirst, errors="raise")
        else:
            data = pd.to_datetime(texto, dayfirst=True, errors="raise")
        return data.date().isoformat()
    except Exception:
        return texto


def adicionar_patente(
    numero: str,
    data_dep: str,
    data_conc: Optional[str],
    descricao: Optional[str],
    titular: Optional[str],
    gestor: Optional[str] = None,
    status_patente: str = "Ativo",
    titulo: Optional[str] = None,
    inventores: Optional[str] = None,
    campus: Optional[str] = None,
    atributos: Optional[str] = None,
    id_externo: Optional[str] = None,
    modalidade_pi: Optional[str] = None,
    ano: Optional[int] = None,
    data_publicacao: Optional[str] = None,
    data_exame: Optional[str] = None,
    acordo_titularidade: Optional[str] = None,
    procuracao: Optional[str] = None,
    termo_cessao: Optional[str] = None,
    ipc_classificacao: Optional[str] = None
) -> Tuple[bool, str]:
    """Insere uma patente e gera suas 20 anuidades usando uma única transação rápida."""
    conn = conectar()
    cur = conn.cursor()

    try:
        # Início da transação explícita
        cur.execute("BEGIN TRANSACTION")

        cur.execute(
            """
            INSERT INTO patentes
            (numero_patente, data_deposito, data_concessao, descricao, titular, gestor, status,
             titulo, inventores, campus, atributos, id_externo, modalidade_pi, ano, 
             data_publicacao, data_exame, acordo_titularidade, procuracao, termo_cessao, ipc_classificacao)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                numero, data_dep, data_conc, descricao, titular, gestor, _normalizar_status(status_patente),
                titulo, inventores, campus, atributos, id_externo, modalidade_pi, ano,
                data_publicacao, data_exame, acordo_titularidade, procuracao, termo_cessao, ipc_classificacao
            ),
        )
        patente_id = cur.lastrowid

        # Geração em lote das 20 anuidades na mesma transação
        inicio = pd.to_datetime(data_dep)
        lote_anuidades = []
        for i in range(1, 21):
            ini_ord = inicio + pd.DateOffset(years=i - 1)
            fim_ord = ini_ord + pd.DateOffset(months=3)
            ini_ext = fim_ord
            fim_ext = ini_ext + pd.DateOffset(months=3)

            lote_anuidades.append((
                patente_id, i, ini_ord.date().isoformat(), fim_ord.date().isoformat(),
                ini_ext.date().isoformat(), fim_ext.date().isoformat(), "pendente"
            ))

        cur.executemany(
            """
            INSERT INTO anuidades
            (patente_id, numero_anuidade, data_inicio_ordinario, data_fim_ordinario,
             data_inicio_extraordinario, data_fim_extraordinario, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            lote_anuidades
        )

        conn.commit()
        return True, "Patente cadastrada com sucesso"

    except Exception as e:
        conn.rollback()
        return False, f"Erro ao adicionar patente: {str(e)}"
    finally:
        conn.close()


def _calcular_datas_anuidade(data_dep: str, numero_anuidade: int) -> Tuple[date, date, date, date]:
    inicio = pd.to_datetime(data_dep)
    ini_ord = inicio + pd.DateOffset(years=numero_anuidade - 1)
    fim_ord = ini_ord + pd.DateOffset(months=3)
    ini_ext = fim_ord
    fim_ext = ini_ext + pd.DateOffset(months=3)
    return ini_ord.date(), fim_ord.date(), ini_ext.date(), fim_ext.date()


def _garantir_anuidades_patente(cur: sqlite3.Cursor, patente_id: int, data_dep: str) -> None:
    if not data_dep:
        return

    cur.execute(
        "SELECT numero_anuidade FROM anuidades WHERE patente_id = ?",
        (patente_id,),
    )
    existentes = {row[0] for row in cur.fetchall()}

    lote_inserir = []
    for numero_anuidade in range(1, 21):
        if numero_anuidade in existentes:
            continue

        ini_ord, fim_ord, ini_ext, fim_ext = _calcular_datas_anuidade(data_dep, numero_anuidade)
        lote_inserir.append((
            patente_id, numero_anuidade, ini_ord.isoformat(), fim_ord.isoformat(),
            ini_ext.isoformat(), fim_ext.isoformat(), "pendente"
        ))

    if lote_inserir:
        cur.executemany(
            """
            INSERT INTO anuidades
            (patente_id, numero_anuidade, data_inicio_ordinario, data_fim_ordinario,
             data_inicio_extraordinario, data_fim_extraordinario, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            lote_inserir
        )


def garantir_anuidades_existentes() -> None:
    """Verifica e cria anuidades faltantes para todas as patentes registradas."""
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, data_deposito FROM patentes")
        patentes = cur.fetchall()

        for patente_id, data_dep in patentes:
            if data_dep:
                _garantir_anuidades_patente(cur, patente_id, data_dep)
        conn.commit()


def atualizar_patente(
    patente_id: int,
    numero: str,
    data_dep: str,
    data_conc: Optional[str],
    descricao: Optional[str],
    titular: Optional[str],
    gestor: Optional[str] = None,
    status_patente: str = "Ativo",
    titulo: Optional[str] = None,
    inventores: Optional[str] = None,
    campus: Optional[str] = None,
    atributos: Optional[str] = None,
    id_externo: Optional[str] = None,
    modalidade_pi: Optional[str] = None,
    ano: Optional[int] = None,
    data_publicacao: Optional[str] = None,
    data_exame: Optional[str] = None,
    acordo_titularidade: Optional[str] = None,
    procuracao: Optional[str] = None,
    termo_cessao: Optional[str] = None,
    ipc_classificacao: Optional[str] = None
) -> Tuple[bool, str]:
    """Atualiza de forma robusta todos os dados de uma patente existente."""
    with conectar() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE patentes
                SET numero_patente = ?, data_deposito = ?, data_concessao = ?,
                    descricao = ?, titular = ?, gestor = ?, status = ?,
                    titulo = ?, inventores = ?, campus = ?, atributos = ?,
                    id_externo = ?, modalidade_pi = ?, ano = ?, data_publicacao = ?,
                    data_exame = ?, acordo_titularidade = ?, procuracao = ?,
                    termo_cessao = ?, ipc_classificacao = ?
                WHERE id = ?
                """,
                (
                    numero, data_dep, data_conc, descricao, titular, gestor, _normalizar_status(status_patente),
                    titulo, inventores, campus, atributos, id_externo, modalidade_pi, ano,
                    data_publicacao, data_exame, acordo_titularidade, procuracao, termo_cessao, ipc_classificacao,
                    patente_id
                ),
            )
            conn.commit()
            return True, "Patente atualizada com sucesso"
        except Exception as e:
            return False, f"Erro ao atualizar patente: {str(e)}"


def salvar_patente_importada(dados: Dict[str, Any], cur: sqlite3.Cursor) -> Tuple[bool, str]:
    """Salva ou atualiza a patente diretamente usando o cursor da transação ativa."""
    cur.execute("SELECT id FROM patentes WHERE numero_patente = ?", (dados["numero"],))
    existente = cur.fetchone()

    if existente:
        patente_id = existente[0]
        cur.execute(
            """
            UPDATE patentes
            SET data_deposito = ?, data_concessao = ?, descricao = ?, titular = ?, gestor = ?, status = ?,
                titulo = ?, inventores = ?, campus = ?, atributos = ?, id_externo = ?, modalidade_pi = ?,
                ano = ?, data_publicacao = ?, data_exame = ?, acordo_titularidade = ?, procuracao = ?,
                termo_cessao = ?, ipc_classificacao = ?
            WHERE id = ?
            """,
            (
                dados["data_dep"], dados["data_conc"], dados["descricao"], dados["titular"], dados["gestor"],
                _normalizar_status(dados["status_patente"]), dados["titulo"], dados["inventores"], dados["campus"],
                dados["atributos"], dados["id_externo"], dados["modalidade_pi"], dados["ano"], dados["data_publicacao"],
                dados["data_exame"], dados["acordo_titularidade"], dados["procuracao"], dados["termo_cessao"],
                dados["ipc_classificacao"], patente_id
            )
        )
        # Garante que as anuidades existem para o registro atualizado
        _garantir_anuidades_patente(cur, patente_id, dados["data_dep"])
        return True, "Patente existente atualizada"
    else:
        cur.execute(
            """
            INSERT INTO patentes
            (numero_patente, data_deposito, data_concessao, descricao, titular, gestor, status,
             titulo, inventores, campus, atributos, id_externo, modalidade_pi, ano, 
             data_publicacao, data_exame, acordo_titularidade, procuracao, termo_cessao, ipc_classificacao)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dados["numero"], dados["data_dep"], dados["data_conc"], dados["descricao"], dados["titular"], dados["gestor"],
                _normalizar_status(dados["status_patente"]), dados["titulo"], dados["inventores"], dados["campus"],
                dados["atributos"], dados["id_externo"], dados["modalidade_pi"], dados["ano"], dados["data_publicacao"],
                dados["data_exame"], dados["acordo_titularidade"], dados["procuracao"], dados["termo_cessao"],
                dados["ipc_classificacao"]
            )
        )
        patente_id = cur.lastrowid
        _garantir_anuidades_patente(cur, patente_id, dados["data_dep"])
        return True, "Nova patente importada"


def obter_anuidades(patente_id: int) -> pd.DataFrame:
    patente_id = int(patente_id)
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("SELECT data_deposito FROM patentes WHERE id = ?", (patente_id,))
        patente = cur.fetchone()
        if patente:
            _garantir_anuidades_patente(cur, patente_id, patente[0])
            conn.commit()

        df = pd.read_sql(
            "SELECT * FROM anuidades WHERE patente_id = ? ORDER BY numero_anuidade",
            conn,
            params=(patente_id,),
        )

    hoje = date.today()

    def normalizar_status(row):
        if row.get("status"):
            s = str(row["status"]).lower()
            if s in ("nao_pagar", "pago"):
                return s
        if row.get("data_fim_extraordinario"):
            try:
                if pd.to_datetime(row["data_fim_extraordinario"]).date() < hoje:
                    return "pago"
            except Exception:
                pass
        return "pendente"

    df["status"] = df.apply(normalizar_status, axis=1)
    return df


def atualizar_status_anuidade(patente_id: int, numero_anuidade: int, novo_status: str, data_pagamento: Optional[str] = None) -> None:
    patente_id = int(patente_id)
    numero_anuidade = int(numero_anuidade)
    novo_status = novo_status.lower()

    with conectar() as conn:
        cur = conn.cursor()
        if novo_status == "pago":
            cur.execute(
                """
                UPDATE anuidades
                SET data_pagamento = ?, status = 'pago'
                WHERE patente_id = ? AND numero_anuidade = ?
                """,
                (data_pagamento, patente_id, numero_anuidade),
            )
        elif novo_status == "nao_pagar":
            cur.execute(
                """
                UPDATE anuidades
                SET data_pagamento = NULL, status = 'nao_pagar'
                WHERE patente_id = ? AND numero_anuidade = ?
                """,
                (patente_id, numero_anuidade),
            )
        else:
            cur.execute(
                """
                UPDATE anuidades
                SET status = ?
                WHERE patente_id = ? AND numero_anuidade = ?
                """,
                (novo_status, patente_id, numero_anuidade),
            )
        conn.commit()


def deletar_patente(patente_id: int) -> None:
    patente_id = int(patente_id)
    with conectar() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM anuidades WHERE patente_id = ?", (patente_id,))
        cur.execute("DELETE FROM patentes WHERE id = ?", (patente_id,))
        conn.commit()


def importar_excel(arquivo_excel) -> List[Tuple[str, bool, str]]:
    """Importa patentes em lote de maneira transacional e ultra rápida."""
    resultados = []
    conn = conectar()
    cur = conn.cursor()

    try:
        cur.execute("BEGIN TRANSACTION")
        df = pd.read_excel(arquivo_excel)
        colunas = {_normalizar_coluna(col): col for col in df.columns}

        def campo(*nomes: str) -> Optional[str]:
            for nome in nomes:
                coluna = colunas.get(_normalizar_coluna(nome))
                if coluna is not None:
                    return coluna
            return None

        # Mapeamento estrito e inteligível para capturar 100% das novas colunas informadas
        mapa = {
            "id_externo": campo("id"),
            "numero": campo("processo", "numero_patente", "numero de patente", "patente"),
            "data_dep": campo("deposito", "depósito", "data_deposito", "data_depósito", "data do deposito"),
            "data_conc": campo("data da concessao", "data da concessão", "data_concessao", "data concessao"),
            "titulo": campo("titulo", "título"),
            "descricao": campo("resumo", "descricao", "descrição"),
            "inventores": campo("nome dos inventores", "inventores", "nome_dos_inventores", "nome do inventor"),
            "titular": campo("depositante/ titular", "depositante titular", "titular", "depositante", "proprietario"),
            "gestor": campo("gestor"),
            "status": campo("status do pedido", "status", "situacao", "situação"),
            "campus": campo("campus"),
            "atributos": campo("atributos", "atributo"),
            "modalidade_pi": campo("modalidade de pi", "modalidade pi", "modalidade"),
            "ano": campo("ano"),
            "data_publicacao": campo("datada publicacao", "datada publicação", "data da publicacao", "data publicacao"),
            "data_exame": campo("data exame", "data_exame", "exame"),
            "acordo_titularidade": campo("acordo de titularidade", "acordo titularidade"),
            "procuracao": campo("procuracao", "procuração"),
            "termo_cessao": campo("termo de cessao", "termo de cessão", "termo cessao"),
            "ipc_classificacao": campo("ipc classificacao", "ipc classificação", "ipc- classificacao", "ipc- classificação", "ipc")
        }

        for idx, row in df.iterrows():
            numero = _valor_limpo(row.get(mapa["numero"])) if mapa["numero"] else None
            data_dep = _parse_data(row.get(mapa["data_dep"])) if mapa["data_dep"] else None

            if not numero or not data_dep:
                resultados.append((
                    str(numero or f"Linha {idx+2}"),
                    False,
                    "Processo (Número da Patente) ou Data de Depósito ausente."
                ))
                continue

            # Converte com segurança campos numéricos (como Ano)
            ano_val = row.get(mapa["ano"]) if mapa["ano"] else None
            try:
                ano_val = int(float(ano_val)) if pd.notna(ano_val) else None
            except Exception:
                ano_val = None

            dados = {
                "numero": str(numero).strip(),
                "data_dep": data_dep,
                "data_conc": _parse_data(row.get(mapa["data_conc"])) if mapa["data_conc"] else None,
                "descricao": _valor_limpo(row.get(mapa["descricao"])) if mapa["descricao"] else None,
                "titular": _valor_limpo(row.get(mapa["titular"])) if mapa["titular"] else None,
                "gestor": _valor_limpo(row.get(mapa["gestor"])) if mapa["gestor"] else None,
                "status_patente": _normalizar_status(row.get(mapa["status"])) if mapa["status"] else "Ativo",
                "titulo": _valor_limpo(row.get(mapa["titulo"])) if mapa["titulo"] else None,
                "inventores": _valor_limpo(row.get(mapa["inventores"])) if mapa["inventores"] else None,
                "campus": _valor_limpo(row.get(mapa["campus"])) if mapa["campus"] else None,
                "atributos": _valor_limpo(row.get(mapa["atributos"])) if mapa["atributos"] else None,
                "id_externo": _valor_limpo(str(row.get(mapa["id_externo"]))) if mapa["id_externo"] else None,
                "modalidade_pi": _valor_limpo(row.get(mapa["modalidade_pi"])) if mapa["modalidade_pi"] else None,
                "ano": ano_val,
                "data_publicacao": _parse_data(row.get(mapa["data_publicacao"])) if mapa["data_publicacao"] else None,
                "data_exame": _parse_data(row.get(mapa["data_exame"])) if mapa["data_exame"] else None,
                "acordo_titularidade": _valor_limpo(row.get(mapa["acordo_titularidade"])) if mapa["acordo_titularidade"] else None,
                "procuracao": _valor_limpo(row.get(mapa["procuracao"])) if mapa["procuracao"] else None,
                "termo_cessao": _valor_limpo(row.get(mapa["termo_cessao"])) if mapa["termo_cessao"] else None,
                "ipc_classificacao": _valor_limpo(row.get(mapa["ipc_classificacao"])) if mapa["ipc_classificacao"] else None
            }

            ok, msg = salvar_patente_importada(dados, cur)
            resultados.append((dados["numero"], ok, msg))

        conn.commit()  # Commita todo o lote de uma única vez
    except Exception as e:
        conn.rollback()
        resultados.append(("ERRO_GERAL", False, f"Falha crítica na transação: {str(e)}"))
    finally:
        conn.close()

    return resultados


def analisar_inconsistencias_excel(arquivo_excel) -> List[str]:
    df = pd.read_excel(arquivo_excel)
    problemas = []

    colunas_originais = list(df.columns)
    colunas_normalizadas = {_normalizar_coluna(col): col for col in colunas_originais}

    obrigatorias = ["processo", "deposito"]
    # Equivalentes aceitáveis
    has_processo = "processo" in colunas_normalizadas or "numero_patente" in colunas_normalizadas or "patente" in colunas_normalizadas
    has_deposito = "deposito" in colunas_normalizadas or "data_deposito" in colunas_normalizadas

    if not has_processo:
        problemas.append("Coluna obrigatória 'Processo' (Número da Patente) não foi encontrada.")
    if not has_deposito:
        problemas.append("Coluna obrigatória 'Depósito' (Data de Depósito) não foi encontrada.")

    return problemas
