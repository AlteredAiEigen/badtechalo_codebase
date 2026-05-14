# AI-Aware Assignment Platform Backend

**New here? Read [PLATFORM_GUIDE.md](PLATFORM_GUIDE.md)** — plain-English explanation of env keys, ingestion, indexing, OpenAI smoke tests, and common failures.

## Quick Start (Internal Testing)

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set your OpenAI key (either variable name works):
   ```bash
   export OPENAI_API_KEY=sk-...   # preferred
   # or
   export OPENAI_KEY=sk-...
   ```
   Or create **`app/.env`** or **`.env`** at the repo root with one of those lines. The app loads **`.env`** then **`app/.env`** (the latter wins on duplicates). Restart uvicorn after editing.

3. Run the FastAPI backend:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

4. In another terminal, run the internal testing UI:
   ```bash
   streamlit run ui/streamlit_app.py
   ```

5. **Debugging “no OpenAI key”:**
   - The API only sees variables in **its process**. Use **`GET /health/config`** and **`GET /health/openai`** (see `/docs`).
   - Streamlit now loads **`app/.env`** the same way (`OPENAI_API_KEY` or **`OPENAI_KEY`**). Restart **both** uvicorn and Streamlit after editing `.env`.
6. **`POST /books/ingest-repo-pdf`** — ingest a PDF that already sits under this repo (e.g. `fecu1dd/fecu101.pdf`) without uploading bytes.
7. **`POST /books/{id}/index?max_pages=3`** — index only the first N pages for a faster smoke test.
8. Scripted e2e: `python scripts/e2e_fecu101.py` (requires API running + valid key).

The Streamlit **Dev console** sidebar shows local key detection and **`/health/config`** from the API.

If OpenAI returns **401**, the key is invalid, expired, or revoked—create a new key at [platform.openai.com/api-keys](https://platform.openai.com/api-keys), export `OPENAI_API_KEY`, and restart uvicorn. Never commit API keys or paste them into public chats.

All core APIs are available at http://localhost:8000/docs

## Architecture Notes
- Reuses existing `extract_pdf_for_rag.py` for textbook chunking + figure extraction.
- Two-stage LLM: gpt-4o for teacher planning, gpt-4o-mini for chunking & student scaffolds.
- Enforces process-first via mandatory attempt logging before any AI help.
- Temporary UI only for developer validation.
