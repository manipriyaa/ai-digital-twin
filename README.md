# EvidenceGraph-RAG: Redrob Candidate Discovery & Ranking

An evidence-first candidate intelligence system for the Redrob *Intelligent Candidate Discovery & Ranking Challenge*. It ranks a 100K-candidate pool against the **Senior AI Engineer — Founding Team** JD on CPU only, and every decision is traceable to candidate evidence.

**Status: Phase 1 complete** (dataset understanding, preprocessing, structured evidence, requirement map). Retrieval, scoring, ranking and submission are later phases and are **not** implemented. See [`ARCHITECTURE.md`](ARCHITECTURE.md), [`docs/DATASET_NOTES.md`](docs/DATASET_NOTES.md) and [`docs/PHASE1_REPORT.md`](docs/PHASE1_REPORT.md).

## Setup

Runtime needs only the Python standard library (3.9+). Tests need `pytest`; the schema-parity test also uses `jsonschema`.

```bash
pip install -r requirements.txt
```

Put the challenge bundle files in `data/raw/`: `candidate_schema.json`, `job_description.docx`, `sample_candidates.json` and the rest are already there. Add `candidates.jsonl.gz` yourself; it is git-ignored.

## Run Phase 1

```bash
# 1. Requirement map from the actual JD -> data/processed/jd_requirements.json (+ jd_parsed.json)
python -m src.requirement_map --jd data/raw/job_description.docx --output-dir data/processed

# 2. Preprocess the full pool (streams; .jsonl or .jsonl.gz)
python -m src.preprocess --candidates data/raw/candidates.jsonl.gz --output-dir data/processed --limit 0

#    sample modes
python -m src.preprocess --candidates data/raw/candidates.jsonl.gz --output-dir data/processed --limit 100
python -m src.preprocess --candidates data/raw/candidates.jsonl.gz --output-dir data/processed --limit 1000
python -m src.preprocess --candidates data/samples/sample_candidates.jsonl --output-dir data/samples/processed

# 3. Tests
python -m pytest -q
```

Options: `--limit N` (0 = all), `--reference-date YYYY-MM-DD` (dataset as-of date, default 2026-06-01), `--progress-every N`, `--schema PATH`.

## Outputs

| File | Content |
|---|---|
| `candidate_summary.jsonl` | One compact row per candidate: current role, location, experience, career stats, logistics, quality-flag codes. |
| `evidence_chunks.jsonl` | Structured evidence units (profile, career, skill, education, certification, behaviour) with provenance. |
| `behavioral_signals.jsonl` | All 23 Redrob signals as individual columns (raw values) plus labelled derived fields. |
| `company_stats.json` | Per-company role counts, start-year histogram, industries, sizes (pool-level reference for impossible tenures). |
| `invalid_records.jsonl` | Quarantined lines (unparseable, missing/invalid/duplicate ID) with the raw line and reasons. |
| `preprocessing_report.json` | Counts, validation counters, evidence by type and assertion level, data-quality issues, timing. |
| `jd_parsed.json` | JD as addressable blocks (`s5.b1` = "Things you absolutely need", first bullet). |
| `jd_requirements.json` | 24 requirements grounded in JD quotes: category, importance, positive/negative queries, evidence types. |

Committed reference outputs for the 50 sample candidates are in `data/samples/processed/`.

## Layout

```
config/requirement_specs.json   requirement definitions (data, not code)
data/raw/                       challenge bundle files (source of truth)
data/samples/                   sample JSONL + sample outputs
data/processed/                 run outputs (full-run files git-ignored)
docs/                           dataset notes, phase reports
scripts/make_stress_dataset.py  synthetic scale/robustness test input (not real data)
src/                            pipeline modules
tests/                          pytest suite
```
