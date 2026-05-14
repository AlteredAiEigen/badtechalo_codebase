#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable


def _iter_page_indices(count: int, *, progress: bool) -> Iterable[int]:
    """Iterate 0..count-1 with an optional tqdm bar on stderr."""
    indices = range(count)
    if count == 0 or not progress:
        return indices
    try:
        from tqdm import tqdm
    except ImportError:
        print(
            "tip: pip install tqdm for a progress bar",
            file=sys.stderr,
        )
        return indices
    return tqdm(
        indices,
        total=count,
        desc="Extracting",
        unit="page",
        file=sys.stderr,
        mininterval=0.15,
    )


def strip_noise_lines(text: str, patterns: list[re.Pattern[str]]) -> str:
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            lines.append("")
            continue
        drop = False
        for p in patterns:
            if p.search(s):
                drop = True
                break
        if not drop:
            lines.append(line)
    return "\n".join(lines).strip()


def column_major_blocks(page, gutter_ratio: float = 0.48) -> str:
    """Join text blocks in reading order for typical two-column textbook spreads."""
    mid = page.rect.width * gutter_ratio
    blocks = page.get_text("blocks")
    left: list[tuple[float, str]] = []
    right: list[tuple[float, str]] = []
    for b in blocks:
        if len(b) < 5:
            continue
        x0, y0, x1, y1, txt = b[0], b[1], b[2], b[3], b[4]
        if not (txt or "").strip():
            continue
        cx = (x0 + x1) / 2
        (left if cx < mid else right).append((y0, txt))
    left.sort(key=lambda t: t[0])
    right.sort(key=lambda t: t[0])
    parts = [t[1].strip() for t in left + right]
    return "\n\n".join(p for p in parts if p)

def column_major_blocks_with_figures(page, figures_meta, gutter_ratio: float = 0.48) -> str:
    """
    Merge text blocks and figure placeholders in correct reading order.
    """
    mid = page.rect.width * gutter_ratio

    blocks = page.get_text("blocks")

    merged = []

    # Add text blocks
    for b in blocks:
        if len(b) < 5:
            continue
        x0, y0, x1, y1, txt = b[:5]
        if not (txt or "").strip():
            continue

        cx = (x0 + x1) / 2
        col = 0 if cx < mid else 1  # 0=left, 1=right

        merged.append({
            "type": "text",
            "y": y0,
            "col": col,
            "content": txt.strip()
        })

    # Add figure placeholders
    for fig in figures_meta:
        x0, y0, x1, y1 = fig["bbox_pt"]
        cx = (x0 + x1) / 2
        col = 0 if cx < mid else 1

        merged.append({
            "type": "figure",
            "y": y0,
            "col": col,
            "content": f"[FIGURE_{fig['placement_index']}]"
        })

    # Sort: first column, then vertical position
    merged.sort(key=lambda x: (x["col"], x["y"]))

    # Combine
    parts = [item["content"] for item in merged]

    return "\n\n".join(parts)


def default_strip_patterns() -> list[re.Pattern[str]]:
    return [
        re.compile(r"^Reprint\s+20\d\d-\d\d\s*$", re.I),
        re.compile(r"^Curiosity\s*\|\s*Textbook of Science\s*\|\s*Grade\s+\d\s*$", re.I),
        re.compile(r"^PD\s+\d+[A-Z]?\s+[A-Z]{2}\s*$"),
        re.compile(r"^\d{1,3}\s*$"),
    ]


def save_page_placements(
    page,
    *,
    stem: str,
    page_number: int,
    out_dir: Path,
    dpi: int,
    min_side_px: float,
    max_page_coverage: float,
) -> list[dict[str, Any]]:
    """Rasterize each image placement on the page; return metadata dicts."""
    import fitz

    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    # page_area = page.rect.get_area() or 1.0
    page_area = (page.rect.width * page.rect.height) or 1.0
    figures: list[dict[str, Any]] = []

    for idx, img in enumerate(page.get_images(full=True)):
        xref = img[0]
        try:
            bbox = page.get_image_bbox(img)
        except Exception:
            continue
        ibox = bbox & page.rect
        if ibox.is_empty:
            continue
        # coverage = ibox.get_area() / page_area
        coverage = (ibox.width * ibox.height) / page_area
        if coverage > max_page_coverage:
            continue
        if min(ibox.width, ibox.height) * zoom < min_side_px:
            continue
        pix = page.get_pixmap(matrix=mat, clip=ibox, alpha=False)
        fn = f"{stem}_place_p{page_number:02d}_i{idx:02d}_xref{xref}.png"
        path = out_dir / fn
        pix.save(path.as_posix())
        figures.append(
            {
                "filename": fn,
                "xref": xref,
                "placement_index": idx,
                "bbox_pt": [round(ibox.x0, 2), round(ibox.y0, 2), round(ibox.x1, 2), round(ibox.y1, 2)],
            }
        )
    return figures


def extract_pdf_for_rag_run(
    pdf_path: Path,
    output_jsonl: Path,
    *,
    gutter: float = 0.48,
    no_strip: bool = False,
    pretty_print: bool = False,
    figures_dir: Path | None = None,
    figure_dpi: int = 150,
    figure_min_side: float = 48.0,
    figure_max_page_coverage: float = 0.92,
    progress: bool = True,
) -> int:
    """Write JSONL (+ optional figure PNGs). Shared by ``extract_data.py`` and this CLI."""
    import fitz  # PyMuPDF

    pdf_path = pdf_path.resolve()
    output_jsonl = output_jsonl.resolve()
    if not pdf_path.is_file():
        print(f"error: PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    patterns: list[re.Pattern[str]] = [] if no_strip else default_strip_patterns()
    source_id = pdf_path.stem
    records: list[dict] = []

    figures_root: Path | None = None
    if figures_dir is not None:
        figures_root = figures_dir.resolve()
        figures_root.mkdir(parents=True, exist_ok=True)

    with fitz.open(pdf_path) as doc:
        meta = {
            "format": (doc.metadata or {}).get("format"),
            "page_count": doc.page_count,
        }
        if figures_root is not None:
            meta["figures_dir"] = str(figures_root)
            meta["figure_dpi"] = figure_dpi
        for i in _iter_page_indices(doc.page_count, progress=progress):
            page = doc[i]
            # text = column_major_blocks(page, gutter_ratio=gutter)
            figures = []

            if figures_root is not None:
                figures = save_page_placements(
                    page,
                    stem=source_id,
                    page_number=i + 1,
                    out_dir=figures_root,
                    dpi=figure_dpi,
                    min_side_px=figure_min_side,
                    max_page_coverage=figure_max_page_coverage,
                )

            text = column_major_blocks_with_figures(page, figures, gutter_ratio=gutter)


            if patterns:
                text = strip_noise_lines(text, patterns)
            rec: dict[str, Any] = {
                "source_file": pdf_path.name,
                "source_id": source_id,
                "page": i + 1,
                "page_index": i,
                "text": text,
                # "figures": [],
                "figures": figures,
            }
            if figures_root is not None:
                rec["figures"] = save_page_placements(
                    page,
                    stem=source_id,
                    page_number=i + 1,
                    out_dir=figures_root,
                    dpi=figure_dpi,
                    min_side_px=figure_min_side,
                    max_page_coverage=figure_max_page_coverage,
                )
            records.append(rec)

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    if pretty_print:
        payload = {"metadata": meta, "pages": records}
        output_jsonl.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        first_line = json.dumps(
            {"document_metadata": meta, "source_id": source_id},
            ensure_ascii=False,
        )
        lines = [first_line]
        for rec in records:
            lines.append(json.dumps(rec, ensure_ascii=False))
        output_jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")

    total_figures = sum(len(r.get("figures") or []) for r in records)
    print(
        f"Wrote {len(records)} page records -> {output_jsonl}",
        file=sys.stderr,
    )
    if figures_root is not None:
        print(
            f"Figure PNGs: {total_figures} files under {figures_root}",
            file=sys.stderr,
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="Path to PDF")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Output JSONL path (one record per page)",
    )
    parser.add_argument(
        "--gutter",
        type=float,
        default=0.48,
        metavar="RATIO",
        help="Columns split at width * this value (default: 0.48)",
    )
    parser.add_argument(
        "--no-strip",
        action="store_true",
        help="Keep repeated headers/footers (Reprint line, running titles, lone page nums)",
    )
    parser.add_argument(
        "--pretty-print",
        action="store_true",
        help="Pretty-print one JSON array instead of JSONL (easier to inspect, worse for streaming)",
    )
    parser.add_argument(
        "--figures-dir",
        type=Path,
        default=None,
        help="Directory for composited figure PNGs (optional); adds a figures[] list per page record",
    )
    parser.add_argument(
        "--figure-dpi",
        type=int,
        default=150,
        help="DPI for figure clips when --figures-dir is set (default: 150)",
    )
    parser.add_argument(
        "--figure-min-side",
        type=float,
        default=48.0,
        metavar="PX",
        help="Min width/height in pixels for a placement clip (default: 48)",
    )
    parser.add_argument(
        "--figure-max-page-coverage",
        type=float,
        default=0.92,
        metavar="RATIO",
        help="Skip clips covering more than this fraction of the page (default: 0.92)",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable the per-page progress bar",
    )
    args = parser.parse_args()

    try:
        import fitz  # noqa: F401 - PyMuPDF required by extract_pdf_for_rag_run
    except ImportError:
        print("error: pip install pymupdf", file=sys.stderr)
        return 1

    return extract_pdf_for_rag_run(
        args.pdf.resolve(),
        args.output.resolve(),
        gutter=args.gutter,
        no_strip=args.no_strip,
        pretty_print=args.pretty_print,
        figures_dir=args.figures_dir.resolve() if args.figures_dir else None,
        figure_dpi=args.figure_dpi,
        figure_min_side=args.figure_min_side,
        figure_max_page_coverage=args.figure_max_page_coverage,
        progress=not args.no_progress,
    )


if __name__ == "__main__":
    raise SystemExit(main())
