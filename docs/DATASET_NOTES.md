# Dataset Notes

Source of truth: the files actually provided, copied unchanged into `data/raw/`.
Everything below comes from reading those files and inspecting the 50 sample records.
Inferences are labelled as such.

## 1. Files

| File (bundle README name) | Status in this repo | Notes |
|---|---|---|
| `candidate_schema.json` | ✅ `data/raw/candidate_schema.json` | JSON Schema draft-07; authoritative. |
| `job_description` (README says `.md`) | ✅ `data/raw/job_description.docx` | Provided as **.docx**. Parsed directly (stdlib zip+XML). |
| `redrob_signals_doc` (README says `.md`) | ✅ `data/raw/redrob_signals_doc.docx` | Contains the 23-signal table only (see §8). |
| `README` | ✅ `data/raw/README.docx` | Bundle overview. |
| `sample_candidates.json` | ✅ `data/raw/sample_candidates.json` | First 50 candidates, pretty-printed JSON array. Converted to `data/samples/sample_candidates.jsonl`. |
| `candidates.jsonl.gz` | ❌ **not provided yet** | README: 100,000 candidates, gzipped JSONL, ~52 MB compressed / ~465 MB uncompressed. |
| `submission_spec.md` | ❌ **not provided yet** | Rules, compute constraints, evaluation stages. |
| `validate_submission.py` | ❌ **not provided yet** | Format validator. |
| `sample_submission.csv` | ❌ **not provided yet** | Format reference. |
| `submission_metadata_template.yaml` | ❌ **not provided yet** | Submission metadata. |

SHA-256 of the provided files:

```
fe5b79aec6f5d01446edbf5e50298eeb651ef5f5d3850f025c6b965e405c43f1  candidate_schema.json
1e91dd0f5c6e4e1ecf0f5e26aecb9c3a759993ebf463162ec28c9f89b5f228ff  job_description.docx
35dd1f5d64fc9ef3b2f5d724ce545a8303b6fd4d9c0b91f2824274461627a345  redrob_signals_doc.docx
b40dea7233c95a9ccce2046ed042d3d2b7a4562f6dabc7c6d59ad31c8e907e8a  README.docx
b13c6611b32a2418a4fbe4e7b3ec66b0972c569c03d267c360cda914530a5c50  sample_candidates.json
```

## 2. Candidate count

* Full pool: **100,000** (bundle README: `wc -l candidates.jsonl # should print 100000`). Not yet verified because the file was not provided.
* Sample: **50** records, `CAND_0000001` … `CAND_0000050`, all valid against the schema.

## 3. Candidate schema (from `candidate_schema.json`)

Top-level required: `candidate_id`, `profile`, `career_history`, `education`, `skills`, `redrob_signals`.
Optional: `certifications`, `languages` (present in all 50 samples).
`additionalProperties` is not restricted anywhere.

| Field | Type / constraint |
|---|---|
| `candidate_id` | string, pattern `^CAND_[0-9]{7}$` |
| `profile` | object; required `anonymized_name, headline, summary, location, country, years_of_experience (0-50), current_title, current_company, current_company_size (enum), current_industry` |
| `career_history[]` | 1-10 items; required `company, title, start_date (date), end_date (date or null), duration_months (int ≥ 0), is_current (bool), industry, company_size (enum), description` |
| `education[]` | 0-5 items; required `institution, degree, field_of_study, start_year (1970-2030), end_year (1970-2035)`; optional `grade (string or null)`, `tier` (enum `tier_1..tier_4, unknown`) |
| `skills[]` | 0+ items; required `name, proficiency (beginner/intermediate/advanced/expert), endorsements (int ≥ 0)`; optional `duration_months` |
| `certifications[]` | required `name, issuer, year` |
| `languages[]` | required `language, proficiency (basic/conversational/professional/native)` |
| `redrob_signals` | object with 23 required signals (§5) |

Company-size enum: `1-10, 11-50, 51-200, 201-500, 501-1000, 1001-5000, 5001-10000, 10001+`.

## 4. Important fields for this JD

* **Demonstrated work:** `career_history[].description` (free text per role), `title`, `company`, `industry`, dates.
* **Self-description:** `profile.headline`, `profile.summary`.
* **Declared skills:** `skills[]` (name, proficiency, endorsements, duration_months). These are the keyword-stuffing trap surface.
* **Seniority:** `profile.years_of_experience`, role durations.
* **Logistics:** `profile.location`, `profile.country`, `redrob_signals.notice_period_days`, `willing_to_relocate`, `preferred_work_mode`.

## 5. Behavioural fields (`redrob_signals`, 23 signals)

| # | Signal | Range | Kind |
|---|---|---|---|
| 1 | profile_completeness_score | 0-100 | observed |
| 2 | signup_date | date | observed |
| 3 | last_active_date | date | observed |
| 4 | open_to_work_flag | bool | self-reported |
| 5 | profile_views_received_30d | int ≥ 0 | observed |
| 6 | applications_submitted_30d | int ≥ 0 | observed |
| 7 | recruiter_response_rate | 0-1 | observed |
| 8 | avg_response_time_hours | ≥ 0 | observed (doc: "median time to respond") |
| 9 | skill_assessment_scores | dict skill → 0-100 | observed (platform assessments) |
| 10 | connection_count | int ≥ 0 | observed |
| 11 | endorsements_received | int ≥ 0 | observed |
| 12 | notice_period_days | 0-180 | self-reported |
| 13 | expected_salary_range_inr_lpa | {min, max} ≥ 0 | self-reported |
| 14 | preferred_work_mode | remote/hybrid/onsite/flexible | self-reported |
| 15 | willing_to_relocate | bool | self-reported |
| 16 | github_activity_score | -1..100 (**-1 = no GitHub linked**) | observed |
| 17 | search_appearance_30d | int ≥ 0 | observed |
| 18 | saved_by_recruiters_30d | int ≥ 0 | observed |
| 19 | interview_completion_rate | 0-1 | observed |
| 20 | offer_acceptance_rate | -1..1 (**-1 = no offer history**) | observed |
| 21 | verified_email | bool | observed |
| 22 | verified_phone | bool | observed |
| 23 | linkedin_connected | bool | observed |

"Kind" is our own label: whether the candidate states the value or the platform observes it.
The signals doc says these signals are meant as "a multiplier or modifier on top of skill-match scoring".

## 6. Date fields

* `career_history[].start_date`, `end_date` (ISO `YYYY-MM-DD`; `end_date` null for the current role).
* `education[].start_year`, `end_year` (integers).
* `certifications[].year`.
* `redrob_signals.signup_date`, `last_active_date`.

**Inferred dataset conventions** (verified on all 147 sample roles):
* `duration_months == (end_date - start_date).days // 30`.
* For current roles the same rule reproduces `duration_months` exactly for a reference ("as-of") date anywhere in **2026-05-27 … 2026-06-14**. We use **2026-06-01** (`config.DEFAULT_REFERENCE_DATE`, overridable). The latest `last_active_date` in the sample is 2026-05-25.

## 7. Known constraints (from README + JD + task brief)

* About 100K candidates; CPU only; no network during ranking; 5 min runtime; 16 GB RAM; 5 GB intermediate disk.
* Exactly 100 output rows, `candidate_id,rank,score,reasoning`; ranks 1-100 once each; scores non-increasing; deterministic ties; reasoning 1-2 grounded sentences.
* README traps: **keyword stuffers**, **plain-language "Tier 5"s**, **behavioural twins**, and **~80 honeypots with subtly impossible profiles**. **Honeypot rate > 10 % in the top 100 = disqualified.**
* Three submissions max, no leaderboard; a sandbox link and interview are part of evaluation.

## 8. Submission constraints

`submission_spec.md` and `validate_submission.py` have **not** been provided, so the exact validator rules are unverified. The README points to spec Sections 2-3 (format), 3 (compute) and 10 (metadata/sandbox). The constraints above come from the task brief and README. We must re-check them against the real spec before Phase-final.

## 9. Data-quality observations (50-record sample)

All 50 records pass the schema. Content-level anomalies, which are flagged and never dropped:

| Observation | Candidates |
|---|---|
| `expected_salary_range_inr_lpa.min > max` | 13 / 50 |
| Same description text reused across roles of one candidate | 15 / 50 |
| A skill's `duration_months` exceeds total experience by > 12 months (e.g. 1.1 years of experience, 36-month skill) | 7 / 50 |
| `signup_date` after `last_active_date` | 2 / 50 |
| First role starts before the first education starts | 2 / 50 |
| Overlapping roles / duration mismatches / bad dates | 0 / 50 |

Qualitative observations that matter for design:

* **Titles and descriptions often disagree.** Examples: "Accountant @ Wipro" with a customer-support description; "Customer Support @ TCS" with a consulting business-analyst description. Text was likely generated per field. Title and description are therefore kept as separate structured fields.
* **Skills lists look partly random relative to the role.** For example, CAND_0000001 (a data engineer) lists *Milvus, Fine-tuning LLMs, TTS, Speech Recognition* as "advanced". This is the keyword-stuffing trap the JD warns about.
* **Strong candidates may describe the work in plain language.** CAND_0000031 (Recommendation Systems Engineer) declares "Embeddings — expert", but the word "embeddings" never appears in their role descriptions, which still describe the right work (learning-to-rank, offline/online correlation, migrating keyword search to embedding retrieval). This is the "Tier 5" case.
* **Summaries often contain self-assessment cues:** "self-learner level", "haven't done it in a professional capacity yet", "curious about how AI tools could augment my work". These are useful negative evidence for later phases.
* Sample titles are mostly non-AI (Operations Manager, Business Analyst, Mechanical Engineer…). Only one sample (CAND_0000031) is an obvious strong fit, consistent with the JD's "narrow profile".
* 33 / 50 have `github_activity_score = -1`; 34 / 50 have `offer_acceptance_rate = -1`. These sentinels must not be read as low scores.
* 40 / 50 have no `skill_assessment_scores`.
* Countries: India 36, USA 4, UAE 3, UK 2, Germany 2, Australia 2, Canada 1. Locations look like `"City, State"` for India and `"City"` elsewhere.
* Education years can be odd relative to the career (e.g. an M.Tech 2017-2022 alongside full-time roles). This is informational only.
* The signals doc refers to "trap candidates and signal envelopes" (README), but the provided `redrob_signals_doc.docx` has only the 23-signal table. If there is a fuller version, it should be added.
