import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402


@pytest.fixture(scope="session")
def sample_records():
    """The 50 real sample candidates shipped in the challenge bundle."""
    with open(config.RAW_DIR / "sample_candidates.json", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def record(sample_records):
    """A fresh deep copy of a real, schema-valid candidate (safe to mutate)."""
    return copy.deepcopy(sample_records[30])  # CAND_0000031: ML engineer, 4 roles


@pytest.fixture
def sample_jsonl(sample_records, tmp_path):
    path = tmp_path / "candidates.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for rec in sample_records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path
