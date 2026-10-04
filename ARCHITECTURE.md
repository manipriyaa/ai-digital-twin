# Architecture

Target pipeline (built one phase at a time; **only Phase 1 exists today**):

```
JOB DESCRIPTION ──► REQUIREMENT MAP ──► POSITIVE + NEGATIVE QUERIES           [Phase 1: map + queries]
                                              │
CANDIDATES ──► VALIDATE ──► NORMALISE ──► STRUCTURED EVIDENCE (+ provenance)  [Phase 1]
                                              │
                         HYBRID RETRIEVAL (dense + BM25)                       [later]
                                              │
               SUPPORTING / CONTRADICTING EVIDENCE per requirement             [later]
                                              │
        CAREER + TEMPORAL CONSISTENCY · BEHAVIOURAL SIGNALS · QUALITY FLAGS    [inputs built in Phase 1]
                                              │
                  FEATURE VECTOR ──► RANKER ──► TOP 100 ──► GROUNDED REASONING ──► CSV   [later]
```

## Principles

1. Evidence before reasoning.
2. Don't trust keywords alone.
3. Keep declared skills apart from demonstrated (production, recent) experience.
4. Keep both positive and negative evidence.
5. Keep temporal information.
6. Keep behavioural signals separate.
7. Make every ranking decision traceable to evidence.
8. Never invent missing information.
9. Be deterministic.
10. Design for 100K candidates on CPU only.

## Phase 1 modules (`src/`)

| Module | Responsibility |
|---|---|
| `config.py` | Paths, output names, reference date, JD-named consulting firms, data-quality tolerances. |
| `utils.py` | Streaming JSONL(.gz) reader, deterministic JSON writer, peak-RSS measurement. |
| `schema.py` | Validator compiled from `candidate_schema.json` (the file stays authoritative). Error → report-counter mapping. |
| `normalize.py` | Conservative text/title/company/skill/date normalisation; `normalize_candidate()` builds a defensive normalised view. |
| `evidence.py` | Structured evidence units: profile, career, skill, education, certification, behaviour. |
| `quality.py` | Data-quality flags (temporal, consistency, range checks). Flags only, never drops. |
| `company_stats.py` | Pool-level per-company statistics accumulated while streaming (memory grows with the number of companies). |
| `summary.py` | Compact candidate summary row and flat behavioural-signal row. |
| `preprocess.py` | Streaming orchestrator and CLI; writes outputs and the preprocessing report. |
| `jd_parser.py` | Parses `job_description.docx` (or `.md`) into addressable blocks `s<section>.b<block>`. |
| `requirement_map.py` | Validates and grounds `config/requirement_specs.json` against the parsed JD; writes `jd_requirements.json`. |

Requirements are **data**: `config/requirement_specs.json`. Adding or editing a requirement needs no code change. Every requirement must quote the JD verbatim (`jd_anchors`); the build fails otherwise.

## Data flow per candidate (streaming)

```
line ─► json.loads ─► validate (schema) ─┬─ unparseable / no valid id / duplicate id ─► invalid_records.jsonl
                                          └─ otherwise ─► normalize_candidate
                                                            ├─► run_quality_checks ─► flags
                                                            ├─► build_all_evidence  ─► evidence_chunks.jsonl
                                                            ├─► candidate summary   ─► candidate_summary.jsonl
                                                            └─► behavioural row     ─► behavioral_signals.jsonl
```

One candidate is in memory at a time. The only state that grows with N is the set of seen IDs used for duplicate detection (about 10 MB at 100K).

## Evidence unit contract

```json
{
  "evidence_id": "CAND_0000031:career:career_history[3]",
  "candidate_id": "CAND_0000031",
  "evidence_type": "career",
  "evidence_subtype": "career.role",
  "assertion_level": "demonstrated",
  "source_field": "career_history[3]",
  "source_index": 3,
  "source_line": 31,
  "text": "Applied ML Engineer at Zomato (Food Delivery, 5001-10000 employees), 2020-06-27 to 2021-07-22, 13 months. Owned the ranking layer ...",
  "metadata": {"company": "Zomato", "title": "Applied ML Engineer", "start_date": "2020-06-27",
               "end_date": "2021-07-22", "duration_months": 13, "is_current": false,
               "months_since_end": 58, "chronological_position": 0, "description_start": 106, "...": "..."}
}
```

`assertion_level` records what kind of claim a unit is:

| Level | Source | Can it prove production experience? |
|---|---|---|
| `declared` | skills list, headline, current-position line | No. A claim only. |
| `self_described` | profile summary | Weak, and often hedged ("self-learner level"). |
| `demonstrated` | dated role description | Yes, if the text shows it. Recency comes from `months_since_end`. |
| `credential` | education, certification | Not production experience. |
| `behavioral` | Redrob signals | Availability and engagement, not skill. |

The requirement map states, per requirement, which levels may count as support (`supporting_assertion_levels`). The production must-haves (R01, R02, R04, R09) accept `demonstrated` only.

## Interfaces for later phases (not implemented)

* **Retrieval (Phase 2):** index `evidence_chunks.jsonl[].text` (dense + BM25), run each requirement's `positive_queries` and `negative_queries`, and filter hits by `evidence_types` and `supporting_assertion_levels`. Hits carry `evidence_id` for grounding.
* **Features:** `candidate_summary.jsonl` and `behavioral_signals.jsonl` are compact per-candidate tables; quality flags are honeypot inputs.
* **Reasoning:** may only cite `evidence_id`s and the text behind them.
