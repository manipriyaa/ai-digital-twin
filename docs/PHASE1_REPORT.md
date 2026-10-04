# Phase 1 Report: Dataset Understanding, Preprocessing & Requirement Intelligence

## 1. What was implemented

* **Dataset inspection** of all provided bundle files: schema, JD, README, signals doc, submission spec, validator, sample submission, metadata template and 50 sample candidates. Written up in [`DATASET_NOTES.md`](DATASET_NOTES.md), with submission rules checked against the spec and validator.
* **Streaming preprocessor** (`python -m src.preprocess`). Parse → validate → normalise → quality-check → evidence → write, one candidate at a time. Accepts `.jsonl`, `.jsonl.gz` and the small `.json` sample array. `--limit N` (0 = all).
* **Schema validation** compiled from the provided `candidate_schema.json`. Parity-tested against the reference `jsonschema` library and 14.6× faster than it (2,000 records: 0.135 s vs 1.975 s). Patterns use ECMA end-of-input semantics, so `"CAND_0000001\n"` is rejected.
* **Validation counters** and a **quarantine file** for records that cannot be safely emitted.
* **Conservative normalisation** (whitespace, Unicode NFC, ISO dates; null for unknown values).
* **Structured evidence units** with provenance and an **assertion level** for profile, career, skill, education, certification and behaviour.
* **Candidate summaries** (compact) and a **flat behavioural-signal table** (23 signals as individual columns).
* **Data-quality checks**: 26 flag codes; flags only, no deletion. This includes the spec's own honeypot example, "expert" skills with under a year of use.
* **Company statistics** (`company_stats.json`): per company, the pool's role-start-year histogram, industries and sizes. This is the reference for the spec's other honeypot example, "8 years at a company founded 3 years ago".
* **JD parser** for the actual `job_description.docx` (stdlib only), with addressable blocks.
* **Requirement map**: 24 requirements defined as data, each grounded in verbatim JD quotes and validated at build time.
* **Tests**: 56 pytest tests, all passing. They include a check that the official `validate_submission.py` accepts the bundled sample submission.

## 2. Dataset size

| | Count | Source |
|---|---|---|
| Full pool | 100,000 (per README) | `candidates.jsonl.gz`, **not provided yet**, so not processed |
| Sample | 50 | `sample_candidates.json`, processed; all 50 schema-valid |
| Sample roles / skills / education / certifications | 147 / 470 / 72 / 22 | |

## 3. Evidence count (50-sample run, `data/samples/processed/`)

| Type | Units | Assertion level |
|---|---|---|
| profile | 150 (headline, summary, current position × 50) | declared / self_described |
| career | 147 (one per role) | demonstrated |
| skill | 470 (one per declared skill) | declared |
| education | 72 | credential |
| certification | 22 | credential |
| behavior | 300 (6 signal groups × 50) | behavioral |
| **total** | **1,161** (about 23 per candidate) | |

## 4. Evidence types

* **profile**: `profile.headline`, `profile.summary` (kept separate: a declared one-liner vs a self-description) and `profile.current_position` (title, company, industry, size, location, stated experience).
* **career**: one unit per role. Text = "Title at Company (industry, size), start to end, N months. Description". Metadata keeps every structured field: dates, `duration_months` and the date-derived value, `is_current`, `months_since_end` (recency), `chronological_position`, `is_jd_named_consulting_firm`, `description_start` (the exact offset of the original description) and `description_duplicate_of` (reused text).
* **skill**: one unit per declared skill, with proficiency, endorsements, duration, the platform assessment score where one exists (with its source path), and `lexical_mentions`: the narrative fields where the skill string literally appears (a pointer, not proof).
* **education / certification**: degree, field, institution, years, grade, tier / name, issuer, year.
* **behavior**: 6 groups (activity, responsiveness, market_demand, logistics, verification, technical_activity). Raw values are keyed by signal name, self-reported signals and sentinel values (`-1`) are marked, and derived `days_since_*` fields are labelled as derived. All 23 signals also appear as individual columns in `behavioral_signals.jsonl`. No combined behaviour score is computed.

## 5. Requirement map (`data/processed/jd_requirements.json`)

24 requirements in all 8 categories, with 106 positive and 86 negative queries. Each one cites the JD block it comes from.

| ID | Category | Name | Imp. | JD strength | Hard | +Q | −Q | Evidence types | JD blocks |
|---|---|---|---|---|---|---|---|---|---|
| R01 | technical_must_have | production_embeddings_retrieval | 1.0 | must_have |  | 10 | 9 | career, profile | s2.b4, s5.b1 |
| R02 | technical_must_have | production_vector_db_or_hybrid_search | 1.0 | must_have |  | 9 | 6 | career, profile | s5.b2 |
| R03 | technical_must_have | strong_python | 1.0 | must_have |  | 5 | 4 | career, profile, skill | s5.b3 |
| R04 | technical_must_have | ranking_evaluation_frameworks | 1.0 | must_have |  | 7 | 4 | career, profile | s2.b5, s5.b4 |
| R05 | technical_preference | llm_fine_tuning | 0.5 | preferred |  | 5 | 4 | career, profile | s6.b1 |
| R06 | technical_preference | learning_to_rank | 0.5 | preferred |  | 5 | 3 | career, profile | s6.b2 |
| R07 | experience | production_applied_ml_experience | 0.9 | ideal_profile |  | 5 | 5 | career, profile | s1.b5, s10.b2, s3.b4 |
| R08 | experience | product_company_experience | 0.7 | explicit_exclusion |  | 4 | 4 | career | s7.b4 |
| R09 | experience | shipped_search_ranking_recommendation | 0.9 | ideal_profile |  | 7 | 4 | career, profile | s10.b3, s11.b3 |
| R10 | seniority | experience_band | 0.6 | soft_preference |  | 4 | 4 | career, profile | h.b4, s10.b2, s3.b1 |
| R11 | career_risk | recent_production_coding | 0.8 | probable_disqualifier |  | 4 | 4 | career, profile | s3.b5 |
| R12 | career_risk | not_framework_only_llm_profile | 0.8 | probable_disqualifier |  | 4 | 7 | career, profile | s3.b4, s7.b3 |
| R13 | domain_fit | nlp_ir_over_unrelated_ai_domains | 0.8 | explicit_exclusion |  | 5 | 5 | career, profile | s7.b5 |
| R14 | logistics | location_relocation_fit | 0.5 | soft_preference |  | 3 | 3 | profile, behavior | h.b2, s10.b5, s8.b1 |
| R15 | logistics | notice_period | 0.4 | soft_preference |  | 2 | 2 | behavior | s8.b2 |
| R16 | behavioral | availability_and_responsiveness | 0.7 | ideal_profile |  | 0 | 0 | behavior | s10.b6, s11.b4 |
| R17 | career_risk | title_hopping | 0.6 | explicit_exclusion |  | 2 | 2 | career | s7.b2 |
| R18 | career_risk | not_research_only | 1.0 | disqualifier | yes | 3 | 4 | career, profile, education | s3.b3 |
| R19 | domain_fit | role_alignment_not_keyword_list | 0.9 | explicit_exclusion |  | 3 | 7 | career, profile, skill | s11.b2, s11.b3 |
| R20 | technical_preference | hrtech_recruiting_marketplace_exposure | 0.3 | preferred |  | 5 | 0 | career, profile | s6.b3 |
| R21 | technical_preference | distributed_systems_inference_optimization | 0.3 | preferred |  | 4 | 0 | career, profile | s6.b4 |
| R22 | technical_preference | open_source_ai_contributions | 0.3 | preferred |  | 3 | 1 | career, profile, behavior | s6.b5 |
| R23 | career_risk | external_validation_of_work | 0.3 | explicit_exclusion |  | 4 | 2 | career, profile, certification, behavior | s7.b6 |
| R24 | experience | shipper_product_mindset | 0.4 | soft_preference |  | 3 | 2 | career, profile | s1.b6, s1.b7 |

**Differences from the brief's example list (R01-R17), all from checking against the actual JD:**

* R01-R17 keep the brief's numbering and meaning.
* R13 (CV/speech/robotics without NLP/IR) is categorised `domain_fit` rather than `career_risk`.
* **Added from the JD:**
  * R18: research-only career. The JD's only "*we will not move forward*" line, so `hard_constraint: true`.
  * R19: keyword list vs actual role. The JD's own trap warning, e.g. a "Marketing Manager" who lists AI skills.
  * R20-R22: HR-tech, distributed systems/inference and open-source preferences.
  * R23: closed-source for 5+ years without external validation.
  * R24: shipper mindset.
* **R12 merges two JD statements**: recent LangChain-to-OpenAI projects (a *probable* disqualifier) and "framework enthusiasts".
* **R08 encodes the exception** that a current consulting job is fine if the candidate has prior product-company experience. The six firm names are the JD's own; the JD says "etc.", so the list is marked non-exhaustive.
* **R10** records that 5-9 years is "a range, not a requirement" (`band_is_hard: false`).
* **R14** separates JD-stated cities from our interpretation (Delhi NCR members, Tier-1 city list), which is labelled `interpretation_not_from_jd`.
* **Unmodelled JD content**, listed with reasons: writing/async culture, decision style, motivation statements. None of these is observable in the candidate schema.
* `importance` is the JD's stated emphasis (must-have 1.0, preferred 0.3-0.5, …). It is a prior, not a tuned weight. **No scoring is implemented.**

## 6. Data-quality issues

On the real 50-record sample (`data/samples/processed/preprocessing_report.json`), 31 of 50 candidates carry at least one flag:

| Flag | Candidates | Severity |
|---|---|---|
| duplicate_role_description | 15 | info |
| salary_min_gt_max | 13 | info |
| skill_duration_exceeds_experience | 7 | warning |
| career_before_education | 2 | info |
| signup_after_last_active | 2 | warning |

No malformed dates, overlaps, duration mismatches or invalid values occur in the sample. The checks exist and are tested on constructed records: overlapping roles, end-before-start, duration mismatch, multiple/no current role, profile vs current-role mismatch, empty sections, invalid experience, out-of-range signals, last-active after the reference date, and duplicate IDs.

The README says the full pool hides **~80 honeypots with subtly impossible profiles**. These flags are the raw material for detecting them. Phase 1 does not decide what any flag means for ranking.

## 7. Performance

Measured on this 4-core container, single process. The real 100K file was not provided, so scale was measured on a **synthetic stress set**: `scripts/make_stress_dataset.py` writes 100,000 copies of the 50 real samples with fresh IDs plus 11 injected malformed lines. Its gzipped size is 53.8 MB, close to the real file's ~52 MB.

| `--limit` | Records | Evidence units | Time | Records/s | Evidence/s | Peak RSS |
|---|---|---|---|---|---|---|
| 100 | 100 | 2,322 | 0.13 s | 785 | 18,235 | 14.1 MB |
| 1,000 | 1,000 | 23,220 | 1.19 s | 840 | 19,515 | 13.4 MB |
| 10,000 | 10,000 | 232,178 | 12.1 s | 827 | 19,200 | 14.6 MB |
| 0 (all) | 100,011 | 2,322,164 | **108.9 s** | 918 | 21,325 | **24.3 MB** |

Full run outputs: `evidence_chunks.jsonl` 1.53 GB (2.32 M lines), `candidate_summary.jsonl` 163 MB, `behavioral_signals.jsonl` 92 MB, `invalid_records.jsonl` 5 lines. Robustness at scale:

* All 11 injected faults were handled without a crash.
* 5 were quarantined: bad JSON, non-object, missing ID, invalid ID, duplicate ID.
* 6 were emitted and flagged: missing profile, string career_history, malformed date, invalid proficiency, out-of-range response rate, missing signals.
* The counters match exactly: `json_parse_error 1, not_an_object 1, missing_candidate_id 1, invalid_candidate_id 1, duplicate_candidate_id 1, missing_profile 1, invalid_career_history 2, invalid_skills 1, invalid_behavioral_signals 2`.

* Memory is flat. The only state that grows is the seen-ID set used for duplicate detection.
* Disk use (1.78 GB) is within the 5 GB intermediate budget. Evidence is 86 % of it.
* Profiling showed the cost spread across JSON decode/encode, normalisation, evidence building and validation, with no single hotspot left. Optimisations applied, each verified to give byte-identical output: a compiled schema validator with lazily built paths, a substring prefilter plus cached regex for skill mentions, and split/join whitespace collapsing (proven equivalent to `\s+` on 20K adversarial strings).
* No multiprocessing, per the brief. The work is embarrassingly parallel by line if it is ever needed. The spec allows pre-computation to exceed the 5-minute window if it is documented or scripted. Only the step that writes the CSV must fit. Even so, the whole preprocessing (≈ 2 min) could run inside the window if Stage 3 required it.

## 8. Design decisions

* **The schema file stays authoritative.** The validator is generated from it at runtime and refuses to load a schema that uses keywords it doesn't implement, so it can't silently skip a constraint.
* **Record policy.** Records that cannot be safely identified are quarantined with their raw line and line number: unparseable JSON, non-objects, missing/invalid ID, duplicate ID. Records with a valid ID but other violations are **emitted, flagged and counted**, never silently dropped.
* **Reference date 2026-06-01**, inferred from the data (DATASET_NOTES §6) and overridable. The dataset's own month convention (`days // 30`) is used, so derived durations agree with the data.
* **Deterministic outputs.** Evidence IDs are readable paths (`CAND_x:career:career_history[2]`), key order is fixed, and nothing depends on hash order or time. `run_stats` (timing) is the only non-deterministic report section. A test checks two runs are byte-identical.
* **No dependencies at runtime.** Standard library only: the JD is parsed with zipfile and XML, so `python-docx` isn't needed.
* **Requirements as data.** New requirements or query lists need no code change, and anchors to the JD are enforced.

## 9. Why structured evidence instead of fixed-size text chunks

* A fixed window can **split one role across chunks** or **merge two roles**. Then "built FAISS retrieval" can't be tied to a specific employer, title or date, and recency and tenure can't be computed.
* A candidate's facts already have natural units: a role, a skill, a degree, a signal group. Each one maps to exactly one place in the source record, so every retrieval hit is **citable** (`evidence_id` → `source_field` → raw value).
* Each unit carries typed metadata (dates, `is_current`, `months_since_end`, proficiency). Later phases can filter or weight by time and evidence kind without re-parsing text.
* Units are short and topical (career units: median 69 words, max 86 on the sample), which suits both BM25 and sentence-embedding models without further splitting.

## 10. Why skills are separated from demonstrated experience

The JD says the dataset contains a deliberate trap: skill lists full of AI keywords. The sample confirms it. CAND_0000001, a data engineer, lists *Milvus — advanced* and *Fine-tuning LLMs — advanced*. Meanwhile the strongest sample candidate (CAND_0000031) never writes "embeddings" in their role descriptions, yet those descriptions show the actual retrieval and ranking work. So:

* Skills become `declared` units, kept apart from `demonstrated` career units.
* Each requirement lists `supporting_assertion_levels`. The production must-haves (R01, R02, R04, R09) accept **only `demonstrated`** evidence, and skill units are excluded from their `evidence_types`.
* Recency is explicit (`months_since_end`, `is_current`), so "recent production work" (R11: last 18 months) can be checked against dates rather than guessed.
* Platform assessment scores are attached to skills as a separate, observed signal, not merged into the declared claim.

## 11. Why provenance is preserved

Every unit records `candidate_id`, `evidence_id`, `source_field`, `source_index` and `source_line`. A test resolves every unit of all 50 samples back to the raw record. This makes it possible to answer "*why did the system think this candidate has production retrieval experience?*" by showing the exact role description. It supports debugging, manual review, evaluation and, later, reasoning text that may only cite evidence that exists. That is the main defence against hallucinated candidate facts.

## 12. Deliberately NOT implemented in Phase 1

No embeddings, no FAISS/ANN index, no BM25, no reranking, no learning-to-rank/LightGBM, no feature weighting or scores, no ranking, no LLM calls, no submission CSV. A test (`test_phase1_does_not_implement_later_phases`) fails if `src/` imports faiss, sentence-transformers, torch, transformers, rank_bm25, lightgbm, xgboost, sklearn, openai, anthropic, requests or httpx. Importance values and hard-constraint markers are **descriptive only**.

## 13. Open items before later phases

1. Upload `candidates.jsonl.gz` and run `--limit 0` on the real pool; record the real counts and flags.
2. ~~Submission spec, validator, sample submission, metadata template~~: provided and documented (DATASET_NOTES §7-8). Implications for later phases:
   * The written score must be tie-broken by `candidate_id` ascending, because the validator enforces it.
   * 80 % of the metric weight is on the top 50, so precision at the very top matters most.
   * Reasoning is checked for specific facts, honest concerns, no hallucination, variety and rank consistency. Evidence IDs and provenance make this possible.
   * Git history is reviewed for real iteration, so each phase should be its own commit.
   * A `rank.py` single command, `submission_metadata.yaml` and a sandbox are required deliverables (final phase).
3. Confirm whether a fuller `redrob_signals_doc` exists (the README mentions trap and envelope sections).

## 14. What Phase 2 will build

**Retrieval over evidence:**

* A BM25 index and a dense embedding index (CPU sentence-embedding model, precomputed offline) over `evidence_chunks.jsonl` text.
* A hybrid retriever that runs each requirement's positive and negative queries, restricted by `evidence_types` and `supporting_assertion_levels`.
* Output: per candidate × requirement, the top supporting and contradicting `evidence_id`s with retrieval scores.

Phase 2 stops at retrieved, provenance-carrying evidence: no final scores, ranking or reasoning yet. It will be checked on the sample: for example, CAND_0000031 should surface R01/R04/R06/R09 support from its career units, and keyword-stuffed profiles should surface R19 contradictions.
