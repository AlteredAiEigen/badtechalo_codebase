import os
import json
import re
import pdfplumber
from mistralai import Mistral

PDF_PATH = "fecu101.pdf"
OUT_PATH = "mistral_topic_chunks.jsonl"

API_KEY = os.environ.get("MISTRAL_API_KEY")
MODEL = "mistral-small-latest"

print(API_KEY)

client = Mistral(api_key=API_KEY)

def clean_text(text):
    text = text.replace("\u00ad", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text

def extract_pages(pdf_path):
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = clean_text(page.extract_text() or "")
            if text:
                pages.append({"page": i, "text": text})
    return pages

def ask_llm(text, chapter_name="Unknown Chapter"):
    prompt = f"""
You are segmenting textbook text for RAG.

Return only JSON:
{{
  "topic": "...",
  "content": "..."
}}

Rules:
- If there is a section heading, identify it and the contents of the section goes in that chunk.
- If there is a sub-section heading, identify it and the contents of the sub-section goes in seperate chunk.
- if heading not found, use the chapter name: {chapter_name} with increment number in topic.
- if content over size limit, split into multiple chunks and topic should be same as last chunk with increment number in topic.
- Do not invent text.

Text:
{text}
"""
    resp = client.chat.complete(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content

def safe_json(s):
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except:
        return None

def build_chunks():
    pages = extract_pages(PDF_PATH)
    chunks = []

    for p in pages:
        raw = ask_llm(p["text"])
        obj = safe_json(raw)
        if not obj:
            obj = {"topic": "Unknown Topic", "content": p["text"]}

        chunks.append({
            "page_start": p["page"],
            "topic": obj.get("topic", "Unknown Topic"),
            "text": obj.get("content", p["text"])
        })

    return chunks

if __name__ == "__main__":
    if not API_KEY:
        raise ValueError("Set MISTRAL_API_KEY environment variable")

    chunks = build_chunks()
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"Saved {len(chunks)} chunks to {OUT_PATH}")