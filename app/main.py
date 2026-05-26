from app.config_env import REPO_ROOT, get_openai_key, load_all_dotenv, openai_key_diagnostics, get_mongodb_db_name

load_all_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAIError

from app.db.mongo import ping_mongo
from app.routers import assignments, auth, books, content, portal, submissions
from app.services.openai_client import get_openai_client

app = FastAPI(title="BadteChalo API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "https://badte.chalo.alteredai.care",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    if not ping_mongo():
        raise RuntimeError("MongoDB Atlas is not reachable. Check MONGODB_URI in backend/.env")


app.include_router(auth.router)
app.include_router(portal.router)
app.include_router(books.router)
app.include_router(content.router)
app.include_router(assignments.router)
app.include_router(submissions.router)


@app.get("/")
def root():
    return {"message": "Backend ready. Use /docs for API explorer.", "database": get_mongodb_db_name()}


@app.get("/health/mongo")
def health_mongo():
    return {"ok": ping_mongo(), "database": get_mongodb_db_name()}


@app.get("/health/config")
def health_config():
    load_all_dotenv()
    key = get_openai_key()
    app_dot = REPO_ROOT / "app" / ".env"
    root_dot = REPO_ROOT / ".env"
    diag = openai_key_diagnostics(key)
    return {
        "repo_root": str(REPO_ROOT.resolve()),
        "mongodb_ok": ping_mongo(),
        "mongodb_database": get_mongodb_db_name(),
        "openai_key_configured": bool(key),
        "openai_key_diagnostics": diag,
    }


def _connection_troubleshooting_hint() -> str:
    return (
        "Could not reach api.openai.com reliably (network or TLS). "
        "Try in order: (1) VPN/firewall allows HTTPS to api.openai.com. "
        "(2) Restart uvicorn after saving app/.env. "
        "(3) Corporate proxy: set HTTPS_PROXY. "
    )


@app.get("/health/openai")
def health_openai():
    load_all_dotenv()
    key = get_openai_key()
    if not key:
        return {"configured": False, "embeddings_ok": False, "chat_ok": False, "detail": "No OpenAI key found."}

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
        emb = client.embeddings.create(model="text-embedding-3-small", input="healthcheck")
        result["embeddings_ok"] = True
        result["embedding_dimensions"] = len(emb.data[0].embedding)
        chat = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Reply with exactly the single word: OK"}],
            max_tokens=16,
        )
        result["chat_ok"] = True
        result["chat_reply_preview"] = (chat.choices[0].message.content or "").strip()[:120]
    except OpenAIError as exc:
        result["detail"] = str(exc)
    except Exception as exc:  # noqa: BLE001
        result["detail"] = f"{type(exc).__name__}: {exc}"
    return result
