from pathlib import Path
from io import BytesIO
import zipfile
import difflib

TEXT_EXTENSIONS = {
    ".py", ".txt", ".md", ".json", ".csv", ".toml", ".yaml", ".yml",
    ".ini", ".cfg", ".xml", ".html", ".css", ".js", ".ts", ".sql",
    ".sh", ".bat", ".env", ".gitignore"
}

def _decode(data):
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")

def read_bytes(name, data):
    ext = Path(name).suffix.lower()

    if ext in TEXT_EXTENSIONS:
        return _decode(data)

    if ext in {".xlsx", ".xls"}:
        try:
            import pandas as pd
            sheets = pd.read_excel(BytesIO(data), sheet_name=None)
            chunks = []
            for sheet, df in sheets.items():
                chunks.append(f"### PLANILHA: {sheet}\n{df.to_csv(index=False)}")
            return "\n\n".join(chunks)
        except Exception as e:
            return f"[Não foi possível ler a planilha: {e}]"

    if ext == ".docx":
        try:
            from docx import Document
            doc = Document(BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as e:
            return f"[Não foi possível ler o DOCX: {e}]"

    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(data))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            return f"[Não foi possível ler o PDF: {e}]"

    return f"[Arquivo binário não convertido: {name}]"

def extract_uploaded_files(uploaded_file):
    name = uploaded_file.name
    data = uploaded_file.getvalue()

    if Path(name).suffix.lower() != ".zip":
        return [{
            "path": name,
            "content": read_bytes(name, data),
            "extension": Path(name).suffix.lower(),
        }]

    result = []
    with zipfile.ZipFile(BytesIO(data)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue

            safe_path = Path(info.filename)
            if safe_path.is_absolute() or ".." in safe_path.parts:
                continue

            file_data = z.read(info)
            result.append({
                "path": safe_path.as_posix(),
                "content": read_bytes(info.filename, file_data),
                "extension": safe_path.suffix.lower(),
            })

    return result

def generate_diff(old_content, new_content, filename):
    """Gera visualização de diferenças unificadas entre códigos."""
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    diff = list(difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"Antigo: {filename}",
        tofile=f"Novo: {filename}",
        lineterm=""
    ))
    return "\n".join(diff)

def create_project_zip(project_id):
    """Gera pacote ZIP em memória com todos os arquivos ativos do projeto."""
    from database import list_files, get_file
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        files = list_files(project_id)
        for f in files:
            full_file = get_file(f["id"])
            if full_file:
                zip_file.writestr(full_file["path"], full_file["content"])
    return zip_buffer.getvalue()

def build_file_tree(files_list):
    """
    Transforma a lista flat de arquivos em um dicionário aninhado (árvore).
    """
    tree = {}
    for f in files_list:
        parts = f["path"].split("/")
        current = tree
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                current[part] = f
            else:
                current = current.setdefault(part, {})
    return tree