import os
import re
import streamlit as st
from google import genai

def get_api_key():
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
        if key:
            return key
    except Exception:
        pass

    return os.getenv("GEMINI_API_KEY", "")

def ask_gemini(prompt, model="gemini-3.5-flash"):
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY não configurada. Configure .streamlit/secrets.toml "
            "ou a variável de ambiente GEMINI_API_KEY."
        )

    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=model,
        contents=prompt,
    )

    text = getattr(response, "text", None)
    if not text:
        raise RuntimeError("A API Gemini retornou uma resposta vazia.")

    return text

def parse_ai_commands(text):
    """
    Varre a resposta da IA em busca de blocos <write_file path="nome">...</write_file>
    e retorna uma lista de dicionários contendo o caminho e o novo código sugerido.
    """
    pattern = re.compile(r'<write_file\s+path=["\'](.*?)["\']\s*>(.*?)</write_file>', re.DOTALL)
    matches = pattern.findall(text)
    commands = []
    for match in matches:
        commands.append({
            "action": "write",
            "path": match[0].strip(),
            "content": match[1]
        })
    return commands