#!/usr/bin/env python3
"""Extract PDF text (JSONL) and optional figures. Default output: extracted_Data/."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from extract_pdf_for_rag import extract_pdf_for_rag_run

_REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_EXPORT_ROOT = _REPO_ROOT / "extracted_Data"

EXAMPLES = """Examples:
  %(prog)s fecu1dd/fecu101.pdf
      Creates extracted_Data/fecu101/fecu101_rag.jsonl

  %(prog)s fecu1dd/fecu101.pdf --figures
      Also creates extracted_Data/fecu101/fecu101_figures/

  %(prog)s fecu1dd/fecu101.pdf -o build/
      Writes build/fecu101_rag.jsonl (override; not under extracted_Data)

  %(prog)s fecu1dd/fecu101.pdf -o build/out.jsonl --figures
      Writes build/out.jsonl and build/fecu101_figures/

Full flags (gutter, figure coverage, etc.): python extract_pdf_for_rag.py --help
"""


def resolve_jsonl_path(pdf: Path, output: Path | None) -> Path:
    stem = pdf.stem
    if output is None:
        dest_dir = DEFAULT_EXPORT_ROOT / stem
        dest_dir.mkdir(parents=True, exist_ok=True)
        return dest_dir / f"{stem}_rag.jsonl"
    output = output.expanduser().resolve()
    suf = output.suffix.lower()
    if suf in (".jsonl", ".json"):
        return output
    output.mkdir(parents=True, exist_ok=True)
    return output / f"{stem}_rag.jsonl"


def resolve_figures_dir(pdf: Path, jsonl_path: Path, with_figures: bool) -> Path | None:
    if not with_figures:
        return None
    return jsonl_path.parent / f"{pdf.stem}_figures"


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="extract_data.py",
        description=__doc__,
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "pdf",
        type=Path,
        help="Input PDF file",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help=f"JSONL file path, OR a folder for <stem>_rag.jsonl (default: {DEFAULT_EXPORT_ROOT}/<stem>/)",
    )
    parser.add_argument(
        "-f",
        "--figures",
        action="store_true",
        help="Save composited figure PNGs under <stem>_figures/ beside the JSONL",
    )
    parser.add_argument(
        "--no-strip",
        action="store_true",
        help="Keep repeated headers/footers in text",
    )
    parser.add_argument(
        "--pretty-print",
        action="store_true",
        help="Single indented JSON file instead of JSONL lines",
    )
    parser.add_argument(
        "--figure-dpi",
        type=int,
        default=150,
        help="DPI for figure PNGs when using --figures (default: 150)",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable the per-page progress bar",
    )
    args = parser.parse_args()

    pdf = args.pdf.resolve()
    if not pdf.is_file():
        print(f"error: PDF not found: {pdf}", file=sys.stderr)
        return 1

    try:
        import fitz  # noqa: F401
    except ImportError:
        print("error: pip install pymupdf", file=sys.stderr)
        return 1

    jsonl_path = resolve_jsonl_path(pdf, args.output)
    figures_dir = resolve_figures_dir(pdf, jsonl_path, args.figures)

    print(f"PDF:   {pdf}", file=sys.stderr)
    print(f"JSONL: {jsonl_path}", file=sys.stderr)
    if figures_dir is not None:
        print(f"Figures: {figures_dir}/", file=sys.stderr)

    return extract_pdf_for_rag_run(
        pdf,
        jsonl_path,
        no_strip=args.no_strip,
        pretty_print=args.pretty_print,
        figures_dir=figures_dir,
        figure_dpi=args.figure_dpi,
        progress=not args.no_progress,
    )


if __name__ == "__main__":
    raise SystemExit(main())
