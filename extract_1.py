import re
import json
from pathlib import Path

import pdfplumber

PDF_PATH = "fecu101.pdf"
OUT_PATH = "topic_chunks.jsonl"
MAX_TOKENS = 500

chapter_re = re.compile(r'^Chapter\s*(\d+)', re.IGNORECASE)
page_marker_re = re.compile(r'^\s*\d+\s*$')
noise_re = re.compile(r'^(Reprint|Chapter\s+\d+\.indd|[|])', re.IGNORECASE)


def clean_line(s):
    s = s.replace("\u00ad", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def approx_tokens(text):
    return max(1, len(text.split()))


def is_noise(line):
    if not line:
        return True
    if page_marker_re.match(line):
        return True
    if noise_re.match(line):
        return True
    if len(line) <= 2 and not line.isalpha():
        return True
    return False


def is_heading(line):
    if is_noise(line):
        return False
    if chapter_re.search(line):
        return False
    if len(line) > 90:
        return False

    words = line.split()

    if len(words) <= 2 and line.endswith("?"):
        return True

    if len(words) <= 7 and not line.endswith((".", ":", ";")):
        return True

    return False


def flush_chunk(chunks, chapter_title, topic, page_start, lines, chapter_name):
    text = " ".join(lines).strip()
    if not text:
        return

    chunks.append({
        "chapter": chapter_title,
        "topic": topic or chapter_name,
        "page_start": page_start,
        "text": text,
        "tokens": approx_tokens(text)
    })


def chunk_pdf(pdf_path):
    chunks = []
    chapter_title = None
    chapter_name = None
    current_topic = None
    current_page = None
    current_lines = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            raw = page.extract_text() or ""
            lines = [clean_line(x) for x in raw.splitlines()]

            for line in lines:
                if is_noise(line):
                    continue

                m = chapter_re.search(line)
                if m:
                    if current_lines:
                        flush_chunk(chunks, chapter_title, current_topic or chapter_name, current_page, current_lines, chapter_name)
                        current_lines = []

                    chapter_name = line
                    chapter_title = line
                    current_topic = None
                    current_page = page_num
                    continue

                if chapter_title is None:
                    chapter_title = "Unknown Chapter"
                    chapter_name = chapter_title

                if is_heading(line):
                    if current_lines:
                        flush_chunk(chunks, chapter_title, current_topic or chapter_name, current_page, current_lines, chapter_name)
                        current_lines = []

                    current_topic = line
                    current_page = page_num
                    continue

                if current_page is None:
                    current_page = page_num

                current_lines.append(line)

                if approx_tokens(" ".join(current_lines)) >= MAX_TOKENS:
                    flush_chunk(chunks, chapter_title, current_topic or chapter_name, current_page, current_lines, chapter_name)
                    current_lines = []
                    current_page = page_num

        if current_lines:
            flush_chunk(chunks, chapter_title, current_topic or chapter_name, current_page, current_lines, chapter_name)

    return chunks


if __name__ == "__main__":
    chunks = chunk_pdf(PDF_PATH)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"Saved {len(chunks)} chunks to {OUT_PATH}")
