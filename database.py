import sqlite3
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "projects.db"

def get_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            path TEXT NOT NULL,
            content TEXT NOT NULL,
            extension TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(project_id, path),
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS file_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
        """)

        # Migração segura para adicionar coluna 'memory' em projetos legados
        try:
            conn.execute("ALTER TABLE projects ADD COLUMN memory TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass # Coluna já existe

def create_project(name, description=""):
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO projects(name, description, created_at, memory) VALUES (?, ?, ?, '')",
            (name, description, now),
        )
        return cur.lastrowid

def update_project_memory(project_id, memory):
    with get_connection() as conn:
        conn.execute(
            "UPDATE projects SET memory = ? WHERE id = ?",
            (memory, project_id)
        )

def list_projects():
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM projects ORDER BY id DESC"
        ).fetchall()]

def get_project(project_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return dict(row) if row else None

def get_workspace_path(project_id):
    path = DATA_DIR / "workspaces" / f"project_{project_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path

def sync_project_to_disk(project_id):
    project_files = list_files(project_id)
    workspace = get_workspace_path(project_id)

    # Remove arquivos órfãos em disco que não existem mais no banco
    db_paths = {f["path"] for f in project_files}
    for item in workspace.glob("**/*"):
        if item.is_file():
            rel_path = item.relative_to(workspace).as_posix()
            if rel_path not in db_paths:
                try:
                    item.unlink()
                except Exception:
                    pass

    # Grava e sincroniza os códigos no workspace físico
    for f in project_files:
        full_file = get_file(f["id"])
        if full_file:
            file_path = workspace / full_file["path"]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(full_file["content"], encoding="utf-8")

def save_file(project_id, path, content, extension=""):
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id, content FROM files WHERE project_id = ? AND path = ?",
            (project_id, path)
        ).fetchone()

        if existing:
            file_id = existing["id"]
            old_content = existing["content"]

            # Cria versão de backup apenas se houver alterações de conteúdo
            if old_content != content:
                v_row = conn.execute(
                    "SELECT COALESCE(MAX(version), 0) as max_v FROM file_versions WHERE file_id = ?",
                    (file_id,)
                ).fetchone()
                next_version = v_row["max_v"] + 1

                conn.execute(
                    "INSERT INTO file_versions(file_id, content, version, created_at) VALUES (?, ?, ?, ?)",
                    (file_id, old_content, next_version, now)
                )

            conn.execute("""
                UPDATE files SET content = ?, extension = ?, updated_at = ? WHERE id = ?
            """, (content, extension, now, file_id))
        else:
            cur = conn.execute("""
                INSERT INTO files(project_id, path, content, extension, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (project_id, path, content, extension, now, now))
            file_id = cur.lastrowid

    # Sincroniza workspace físico em disco
    sync_project_to_disk(project_id)

def list_files(project_id):
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, path, extension, updated_at FROM files WHERE project_id = ? ORDER BY path",
            (project_id,),
        ).fetchall()]

def get_file(file_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM files WHERE id = ?", (file_id,)
        ).fetchone()
        return dict(row) if row else None

def get_file_versions(file_id):
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM file_versions WHERE file_id = ? ORDER BY version DESC",
            (file_id,)
        ).fetchall()]

def rollback_file_to_version(file_id, version_id):
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as conn:
        v_row = conn.execute(
            "SELECT content FROM file_versions WHERE id = ?", (version_id,)
        ).fetchone()
        if not v_row:
            return False

        target_content = v_row["content"]

        f_row = conn.execute(
            "SELECT project_id, path, content, extension FROM files WHERE id = ?", (file_id,)
        ).fetchone()
        if not f_row:
            return False

        current_content = f_row["content"]
        project_id = f_row["project_id"]

        # Salva o estado atual na lista de versões antes do rollback
        v_row_max = conn.execute(
            "SELECT COALESCE(MAX(version), 0) as max_v FROM file_versions WHERE file_id = ?",
            (file_id,)
        ).fetchone()
        next_version = v_row_max["max_v"] + 1

        conn.execute(
            "INSERT INTO file_versions(file_id, content, version, created_at) VALUES (?, ?, ?, ?)",
            (file_id, current_content, next_version, now)
        )

        # Realiza rollback
        conn.execute(
            "UPDATE files SET content = ?, updated_at = ? WHERE id = ?",
            (target_content, now, file_id)
        )

    sync_project_to_disk(project_id)
    return True

def save_message(project_id, role, content):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO messages(project_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (project_id, role, content, datetime.now().isoformat(timespec="seconds")),
        )

def list_messages(project_id):
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM messages WHERE project_id = ? ORDER BY id",
            (project_id,),
        ).fetchall()]