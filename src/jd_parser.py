"""Parse the provided job description into addressable text blocks.

Reads the actual job_description.docx with the standard library only (a .docx is a
zip of WordprocessingML). A Markdown JD (the bundle README mentions
job_description.md) is supported too. Each paragraph / list item becomes a block
with a stable id (``s<section>.b<block>``) so every requirement can cite the exact
JD text it came from.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import List, Optional

from . import config
from .normalize import normalize_text
from .utils import write_json

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_paragraphs(path: Path) -> List[tuple]:
    """Return [(style, text)] for body paragraphs and table rows, in document order."""
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    body = root.find(f"{_W}body")
    out = []
    for el in body:
        if el.tag == f"{_W}p":
            style_el = el.find(f"{_W}pPr/{_W}pStyle")
            style = style_el.get(f"{_W}val") if style_el is not None else "Normal"
            text = normalize_text("".join(t.text or "" for t in el.iter(f"{_W}t")))
            if text:
                out.append((style, text))
        elif el.tag == f"{_W}tbl":
            for row in el.iter(f"{_W}tr"):
                cells = [normalize_text("".join(t.text or "" for t in tc.iter(f"{_W}t"))) or ""
                         for tc in row.iter(f"{_W}tc")]
                if any(cells):
                    out.append(("TableRow", " | ".join(cells)))
    return out


def _markdown_paragraphs(path: Path) -> List[tuple]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            out.append(("Title" if level == 1 and not out else f"Heading{level - 1 or 1}", normalize_text(m.group(2))))
        elif re.match(r"^\s*[-*]\s+", line):
            out.append(("ListBullet", normalize_text(re.sub(r"^\s*[-*]\s+", "", line))))
        elif re.match(r"^\s*\d+[.)]\s+", line):
            out.append(("ListNumber", normalize_text(re.sub(r"^\s*\d+[.)]\s+", "", line))))
        elif normalize_text(line):
            out.append(("Normal", normalize_text(line)))
    return [p for p in out if p[1]]


def parse_job_description(path: Path | str = config.JOB_DESCRIPTION_PATH) -> dict:
    path = Path(path)
    raw = path.read_bytes()
    paragraphs = _docx_paragraphs(path) if path.suffix == ".docx" else _markdown_paragraphs(path)

    title: Optional[str] = None
    header: List[dict] = []
    sections: List[dict] = []
    current: Optional[dict] = None
    for style, text in paragraphs:
        if style == "Title" and title is None:
            title = text
            continue
        if style.startswith("Heading"):
            level = int(re.sub(r"\D", "", style) or 1)
            current = {"section_id": f"s{len(sections) + 1}", "heading": text, "level": level, "blocks": []}
            sections.append(current)
            continue
        if current is None:  # lines between title and first heading (company, location...)
            block_id = f"h.b{len(header) + 1}"
            header.append({"block_id": block_id, "style": style, "text": text})
            continue
        block_id = f"{current['section_id']}.b{len(current['blocks']) + 1}"
        current["blocks"].append({"block_id": block_id, "style": style, "text": text})

    header_fields = {}
    for b in header:
        m = re.match(r"^([A-Za-z ]+):\s*(.+)$", b["text"])
        if m:
            header_fields[m.group(1).strip().lower().replace(" ", "_")] = m.group(2).strip()

    return {
        "source_document": path.name,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "title": title,
        "role_title": re.sub(r"^Job Description:\s*", "", title or "") or None,
        "header_fields": header_fields,
        "header_blocks": header,
        "sections": sections,
    }


def iter_blocks(parsed: dict):
    """Yield (section_heading, block) for header and section blocks, in order."""
    for b in parsed["header_blocks"]:
        yield "(header)", b
    for s in parsed["sections"]:
        for b in s["blocks"]:
            yield s["heading"], b


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Parse the job description into addressable blocks.")
    ap.add_argument("--jd", type=Path, default=config.JOB_DESCRIPTION_PATH)
    ap.add_argument("--output-dir", type=Path, default=config.PROCESSED_DIR)
    args = ap.parse_args(argv)
    parsed = parse_job_description(args.jd)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / config.JD_PARSED_FILE, parsed)
    n = sum(len(s["blocks"]) for s in parsed["sections"]) + len(parsed["header_blocks"])
    print(f"{parsed['role_title']}: {len(parsed['sections'])} sections, {n} blocks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
