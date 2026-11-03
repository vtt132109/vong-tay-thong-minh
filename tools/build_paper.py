#!/usr/bin/env python
"""Build docs/paper/BioBand_paper.pdf from docs/paper/paper.html + paper.css.

Uses headless Microsoft Edge (or Chrome) to print the HTML to PDF, prints the
page count and exits non-zero if the count is outside 6-8 pages.

    .venv-ds/Scripts/python.exe tools/build_paper.py
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "docs" / "paper" / "paper.html"
PDF = ROOT / "docs" / "paper" / "BioBand_paper.pdf"
MIN_PAGES, MAX_PAGES = 6, 8

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_browser() -> str:
    for b in BROWSERS:
        if Path(b).exists():
            return b
    for name in ("msedge", "chrome", "google-chrome", "chromium"):
        p = shutil.which(name)
        if p:
            return p
    sys.exit("No Edge/Chrome found")


def count_pages(pdf: Path) -> int:
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(pdf)).pages)
    except ImportError:
        data = pdf.read_bytes()
        n = len(re.findall(rb"/Type\s*/Page(?![s\w])", data))
        if n == 0:
            sys.exit("cannot count pages (install pypdf)")
        return n


def main() -> int:
    if not HTML.exists():
        sys.exit(f"missing {HTML}")
    browser = find_browser()
    if PDF.exists():
        PDF.unlink()
    with tempfile.TemporaryDirectory(prefix="biopaper_") as prof:
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            f"--user-data-dir={prof}",
            "--no-pdf-header-footer",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=10000",
            f"--print-to-pdf={PDF}",
            HTML.as_uri(),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if not PDF.exists() or PDF.stat().st_size == 0:
        print(r.stdout, r.stderr, sep="\n")
        sys.exit("PDF was not produced")
    n = count_pages(PDF)
    print(f"{PDF}  ({PDF.stat().st_size / 1024:.0f} KB)")
    print(f"pages: {n}")
    if not (MIN_PAGES <= n <= MAX_PAGES):
        print(f"ERROR: page count {n} outside {MIN_PAGES}-{MAX_PAGES}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
