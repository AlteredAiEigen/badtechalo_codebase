from app.config_env import REPO_ROOT, get_openai_key, load_all_dotenv, openai_key_diagnostics

load_all_dotenv()

from fastapi import FastAPI
from openai import OpenAIError

from app.db.database import init_db
from app.routers import assignments, books, content, submissions
from app.services.openai_client import get_openai_client

app = FastAPI(title="AI-Aware Assignment Platform API", version="0.1.0")


@app.on_event("startup")
def on_startup():
    init_db()


app.include_router(books.router)
app.include_router(content.router)
app.include_router(assignments.router)
app.include_router(submissions.router)


@app.get("/")
def root():
    return {"message": "Backend ready. Use /docs for API explorer."}


@app.get("/health/config")
def health_config():
    """Where the server looks for secrets (no key material returned)."""
    load_all_dotenv()
    key = get_openai_key()
    app_dot = REPO_ROOT / "app" / ".env"
    root_dot = REPO_ROOT / ".env"
    diag = openai_key_diagnostics(key)
    return {
        "repo_root": str(REPO_ROOT.resolve()),
        "app_dotenv_path": str(app_dot),
        "root_dotenv_path": str(root_dot),
        "app_dotenv_exists": app_dot.is_file(),
        "root_dotenv_exists": root_dot.is_file(),
        "openai_key_configured": bool(key),
        "openai_key_preview": (f"…{key[-6:]}" if len(key) >= 10 else ("(short)" if key else None)),
        "openai_key_diagnostics": diag,
        "note": "openai_key_configured only means non-empty locally. Use GET /health/openai to verify with OpenAI.",
    }


def _connection_troubleshooting_hint() -> str:
    return (
        "Could not reach api.openai.com reliably (network or TLS). "
        "Try in order: (1) VPN/firewall allows HTTPS to api.openai.com. "
        "(2) Restart uvicorn after saving app/.env — the API client uses the OS certificate store by default. "
        "(3) Corporate proxy: set HTTPS_PROXY (and HTTP_PROXY if needed). "
        "(4) Custom CA bundle: set SSL_CERT_FILE to your org root PEM. "
        "(5) Dev-only workaround: OPENAI_INSECURE_SSL=1 in app/.env (disables TLS verification; remove for production)."
    )


@app.get("/health/openai")
def health_openai():
    """
    Smoke-test OpenAI: one embedding + one tiny chat completion.
    Does not log or return any part of the API key.
    """
    load_all_dotenv()
    key = get_openai_key()
    if not key:
        return {
            "configured": False,
            "embeddings_ok": False,
            "chat_ok": False,
            "detail": "No OpenAI key found. Set OPENAI_API_KEY or OPENAI_KEY (e.g. in app/.env).",
        }

    result = {
        "configured": True,
        "embeddings_ok": False,
        "chat_ok": False,
        "embedding_model": "text-embedding-3-small",
        "chat_model": "gpt-4o-mini",
        "detail": None,
        "openai_key_diagnostics": openai_key_diagnostics(key),
    }
    try:
        client = get_openai_client()
        emb = client.embeddings.create(
            model="text-embedding-3-small",
            input="healthcheck",
        )
        vec = emb.data[0].embedding
        result["embeddings_ok"] = True
        result["embedding_dimensions"] = len(vec)

        chat = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": "Reply with exactly the single word: OK"}
            ],
            max_tokens=16,
        )
        reply = (chat.choices[0].message.content or "").strip()
        result["chat_ok"] = True
        result["chat_reply_preview"] = reply[:120]
    except OpenAIError as exc:
        result["detail"] = str(exc)
        err = str(exc).lower()
        if "401" in err or "invalid_api_key" in err or "incorrect api key" in err:
            result["how_to_fix"] = (
                "OpenAI rejected this key. Open https://platform.openai.com/api-keys , create a new "
                "secret key, copy the entire value (one line, no spaces or quotes), put it in app/.env as "
                "OPENAI_KEY=sk-... or OPENAI_API_KEY=sk-... , save, then restart uvicorn. "
                "If you ever pasted a key in chat or committed it, assume it is compromised and rotate."
            )
        if any(
            w in err
            for w in (
                "connection",
                "connect",
                "timeout",
                "ssl",
                "tls",
                "certificate",
                "10060",
                "10054",
                "refused",
                "unreachable",
            )
        ):
            result["how_to_fix_connection"] = _connection_troubleshooting_hint()
    except Exception as exc:  # noqa: BLE001
        result["detail"] = f"{type(exc).__name__}: {exc}"
        low = result["detail"].lower()
        if any(
            w in low
            for w in (
                "connection",
                "connect",
                "ssl",
                "certificate",
                "tls",
                "timed out",
                "timeout",
                "10060",
                "10054",
                "refused",
                "unreachable",
            )
        ):
            result["how_to_fix_connection"] = _connection_troubleshooting_hint()

    return result
