"""Small I/O helpers: streaming readers, deterministic JSON writing, resource usage."""
from __future__ import annotations

import gzip
import json
import resource
import sys
from pathlib import Path
from typing import IO, Iterator, Tuple


def open_text(path: Path | str) -> IO[str]:
    """Open a text file, transparently handling .gz."""
    path = Path(path)
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "r", encoding="utf-8")


def iter_raw_records(path: Path | str) -> Iterator[Tuple[int, str]]:
    """Yield (line_number, raw_line) for every non-blank line of a JSONL(.gz) file.

    Only one line is held in memory at a time. Line numbers are 1-based and count
    blank lines too, so they always point at the physical line in the source file.

    A ``.json`` file holding a JSON array (e.g. sample_candidates.json) is also
    accepted for convenience; it is small, so it is loaded whole and each element is
    re-serialised. Its "line number" is the 1-based array index.
    """
    path = Path(path)
    if path.suffix == ".json":
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            raise ValueError(f"{path} must contain a JSON array of candidates")
        for i, obj in enumerate(data, start=1):
            yield i, json.dumps(obj, ensure_ascii=False)
        return
    with open_text(path) as fh:
        for line_no, line in enumerate(fh, start=1):
            if line.strip():
                yield line_no, line


def dumps(obj) -> str:
    """Deterministic compact JSON (key order = insertion order, which our code fixes)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def write_json(path: Path | str, obj) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def peak_rss_mb() -> float:
    """Peak resident set size of this process in MB (Linux reports KB, macOS bytes)."""
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024
