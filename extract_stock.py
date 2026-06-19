"""Scan PDF stock-list reports in a folder and emit a JSON file of per-size stock.

For each PDF in the input folder we read every page, locate the five style
blocks per page, and inspect the filled cells in the per-size stock-indicator
row:

    light grey (RGB ~0.753)                 = Limited     -> 1
    black (0,0,0) or dark grey (RGB ~0.647) = Substantial -> 2
    no shading                              = No Stock    -> 0

The script is tailored to "Rieker Available Stock List" PDFs produced by the
report tool that generated `rAvailableStockListReport_*.pdf`.

Usage:
    python extract_stock.py [folder] [--out stock.json]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
from dataclasses import dataclass, asdict
from typing import Iterable

import pdfplumber

# --- layout constants ------------------------------------------------------
SIZE_LABELS = ["36", "37", "38", "39", "40", "41", "42", "43", "44", "45",
               "46", "47", "S", "M", "L", "XL", "Handbag"]
# x0 of each size-indicator cell (17pt wide squares); matched with ~2pt tolerance.
SIZE_CELL_X0 = [23.9, 44.0, 64.2, 84.4, 104.6, 124.8, 144.9, 165.1, 185.3,
                205.5, 225.7, 245.8, 285.3, 305.5, 325.7, 345.8, 387.1]
# Each page has up to 5 style blocks. The size-indicator row is the 2nd of the
# two 17-cell rows that belong to the block; these are its expected `top` (y from
# top of page, page height = 842pt).
BLOCK_INDICATOR_TOP = [157.4, 306.7, 455.9, 605.2, 754.4]
# Style-header text (Season / Style / Colour / price) anchors:
BLOCK_HEADER_TOP_RANGE = [(40, 140), (190, 290), (340, 440), (490, 590), (640, 740)]

COLOR_LIMITED = (0.75294, 0.75294, 0.75294)
# Substantial is rendered either as a black-filled cell or, occasionally,
# as a dark-grey one. Both map to stock level 2.
COLORS_SUBSTANTIAL = {(0.0, 0.0, 0.0), (0.64706, 0.64706, 0.64706)}


# --- data model ------------------------------------------------------------
@dataclass
class StockRow:
    code: str
    size: str
    stock: int  # 0=none, 1=limited, 2=substantial


# --- helpers ---------------------------------------------------------------
def _match_x(x: float) -> int | None:
    """Return the size index for an x0 value, or None if no match."""
    for i, x0 in enumerate(SIZE_CELL_X0):
        if abs(x - x0) < 2.0:
            return i
    return None


def _match_block(top: float) -> int | None:
    for i, t in enumerate(BLOCK_INDICATOR_TOP):
        if abs(top - t) < 4.0:
            return i
    return None


_STYLE_RE = re.compile(r"^Style:\s*(\S+)")


def _extract_codes(page) -> list[str]:
    """Return the style code for each of the up-to-5 blocks on the page."""
    codes: list[str] = ["" for _ in range(5)]
    words = page.extract_words()
    lines: dict[int, list] = {}
    for w in words:
        key = round(w["top"] / 2) * 2
        lines.setdefault(key, []).append(w)
    for top, ws in lines.items():
        ws.sort(key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in ws)
        bi = None
        for i, (lo, hi) in enumerate(BLOCK_HEADER_TOP_RANGE):
            if lo <= top <= hi:
                bi = i
                break
        if bi is None:
            continue
        m = _STYLE_RE.match(text)
        if m:
            codes[bi] = m.group(1)
    return codes


def extract_pdf(path: str) -> Iterable[StockRow]:
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            codes = _extract_codes(page)
            # Initialise stock matrix [5 blocks][17 sizes] = 0
            stock = [[0] * len(SIZE_LABELS) for _ in range(5)]
            for r in page.rects:
                if not r.get("fill"):
                    continue
                # Stock indicators are full 17x17 filled squares; everything
                # else (page background, 0.75pt cell borders, etc.) is ignored.
                if not (16 < r["width"] < 18 and 16 < r["height"] < 18):
                    continue
                nsc = r.get("non_stroking_color")
                if nsc == COLOR_LIMITED:
                    level = 1
                elif nsc in COLORS_SUBSTANTIAL:
                    level = 2
                else:
                    continue
                top = 842.0 - r["y1"]
                bi = _match_block(top)
                if bi is None:
                    continue
                si = _match_x(r["x0"])
                if si is None:
                    continue
                stock[bi][si] = level
            for bi, code in enumerate(codes):
                if not code:
                    continue
                for si, size in enumerate(SIZE_LABELS):
                    yield StockRow(code=code, size=size, stock=stock[bi][si])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default=".",
                    help="folder containing PDF reports (default: current dir)")
    ap.add_argument("--out", default="stock.json")
    args = ap.parse_args()

    pdfs = sorted(glob.glob(os.path.join(args.folder, "*.pdf")))
    if not pdfs:
        raise SystemExit(f"No PDFs found in {args.folder!r}")

    rows: list[StockRow] = []
    for p in pdfs:
        print(f"Parsing {os.path.basename(p)} ...")
        rows.extend(extract_pdf(p))

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in rows], f, indent=2)
    print(f"Wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
