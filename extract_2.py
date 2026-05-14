import re
import json
import pdfplumber
from collections import Counter

PDF_PATH = "fecu101.pdf"
OUT_PATH = "topic_chunks.jsonl"
MAX_TOKENS = 500

chapter_re = re.compile(r'^\s*Chapter\s*\d+\b', re.IGNORECASE)
noise_re = re.compile(r'^(Reprint|Chapter\s+\d+\.indd|Page\s*\d+|\d+)$', re.IGNORECASE)

topic_re = re.compile(
    r'^\s*([A-Za-z][A-Za-z ]*?)?\s*(\d+(?:\.\d+)*):\s*(.+)$'
)

def clean_text(s):
    s = s.replace("\u00ad", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def approx_tokens(text):
    return max(1, len(text.split()))

def is_noise(line):
    if not line:
        return True
    if noise_re.match(line):
        return True
    if len(line) <= 2:
        return True
    return False

def is_bold(word):
    font = (word.get("fontname") or "").lower()
    return "bold" in font or "black" in font or "semibold" in font

def extract_lines(page):
    words = page.extract_words(extra_attrs=["fontname", "size"])
    if not words:
        return []

    words = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))

    lines = []
    current = []
    current_top = None

    for w in words:
        top = round(w["top"], 1)
        if current_top is None:
            current_top = top
            current = [w]
        elif abs(top - current_top) <= 2.5:
            current.append(w)
        else:
            lines.append(current)
            current = [w]
            current_top = top

    if current:
        lines.append(current)

    out = []
    for line_words in lines:
        text = clean_text(" ".join(w["text"] for w in line_words))
        bold_count = sum(1 for w in line_words if is_bold(w))
        avg_size = sum(float(w.get("size", 0)) for w in line_words) / len(line_words)
        out.append({
            "text": text,
            "bold_count": bold_count,
            "word_count": len(line_words),
            "avg_size": avg_size
        })
    return out

def detect_topic(line):
    m = topic_re.match(line)
    if not m:
        return None
    prefix = (m.group(1) or "").strip()
    number = m.group(2).strip()
    title = m.group(3).strip()
    full = f"{prefix} {number}: {title}".strip()
    return {
        "prefix": prefix,
        "number": number,
        "title": title,
        "full": full
    }

def looks_like_chapter(line):
    return bool(chapter_re.match(line))

def flush_chunk(chunks, chapter, topic, topic_count, page_start, lines):
    text = " ".join(lines).strip()
    if not text:
        return

    name = topic if topic_count == 1 else f"{topic} {topic_count}"
    chunks.append({
        "chapter": chapter,
        "topic": name,
        "page_start": page_start,
        "text": text,
        "tokens": approx_tokens(text)
    })

def chunk_pdf(pdf_path):
    chunks = []

    chapter_name = "Unknown Chapter"
    current_topic = chapter_name
    current_topic_count = 1
    current_lines = []
    current_page = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            lines = extract_lines(page)
            if not lines:
                continue

            body_sizes = [x["avg_size"] for x in lines if not is_noise(x["text"])]
            body_size = Counter(round(s, 1) for s in body_sizes).most_common(1)[0][0] if body_sizes else None

            for line_obj in lines:
                line = line_obj["text"]

                if is_noise(line):
                    continue

                if looks_like_chapter(line):
                    if current_lines:
                        flush_chunk(chunks, chapter_name, current_topic, current_topic_count, current_page or page_num, current_lines)
                        current_lines = []
                        current_topic_count = 1

                    chapter_name = line
                    current_topic = chapter_name
                    current_page = page_num
                    continue

                topic_info = detect_topic(line)

                if topic_info:
                    if current_lines:
                        flush_chunk(chunks, chapter_name, current_topic, current_topic_count, current_page or page_num, current_lines)
                        current_lines = []
                        current_topic_count = 1

                    current_topic = topic_info["title"]
                    current_page = page_num
                    continue

                if current_page is None:
                    current_page = page_num

                current_lines.append(line)

                if approx_tokens(" ".join(current_lines)) >= MAX_TOKENS:
                    flush_chunk(chunks, chapter_name, current_topic, current_topic_count, current_page, current_lines)
                    current_lines = []
                    current_topic_count += 1

        if current_lines:
            flush_chunk(chunks, chapter_name, current_topic, current_topic_count, current_page or 1, current_lines)

    return chunks

if __name__ == "__main__":
    chunks = chunk_pdf(PDF_PATH)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"Saved {len(chunks)} chunks to {OUT_PATH}")