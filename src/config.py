"""Central configuration: paths, dataset constants and reference date.

Nothing here is a scoring weight. Phase 1 only describes and structures data.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
SAMPLES_DIR = PROJECT_ROOT / "data" / "samples"
CONFIG_DIR = PROJECT_ROOT / "config"

CANDIDATE_SCHEMA_PATH = RAW_DIR / "candidate_schema.json"
JOB_DESCRIPTION_PATH = RAW_DIR / "job_description.docx"
REQUIREMENT_SPECS_PATH = CONFIG_DIR / "requirement_specs.json"
SAMPLE_CANDIDATES_JSONL = SAMPLES_DIR / "sample_candidates.jsonl"

# Output file names (written into --output-dir).
CANDIDATE_SUMMARY_FILE = "candidate_summary.jsonl"
EVIDENCE_FILE = "evidence_chunks.jsonl"
BEHAVIORAL_SIGNALS_FILE = "behavioral_signals.jsonl"
INVALID_RECORDS_FILE = "invalid_records.jsonl"
PREPROCESSING_REPORT_FILE = "preprocessing_report.json"
JD_PARSED_FILE = "jd_parsed.json"
JD_REQUIREMENTS_FILE = "jd_requirements.json"
COMPANY_STATS_FILE = "company_stats.json"

# "As-of" date of the dataset snapshot, inferred from sample_candidates.json: with
# the dataset's month convention (days // 30), every current role's duration_months
# is reproduced exactly for any reference date in 2026-05-27..2026-06-14, and the
# latest last_active_date is 2026-05-25. Derived "days/months since" fields are
# relative to this date. Override with --reference-date.
DEFAULT_REFERENCE_DATE = dt.date(2026, 6, 1)

CANDIDATE_ID_PATTERN = r"^CAND_[0-9]{7}$"

# Consulting / IT-services firms named verbatim in the JD ("Things we explicitly do
# NOT want"). The JD says "etc."; we do not extend the list on our own.
JD_NAMED_CONSULTING_FIRMS = (
    "TCS",
    "Infosys",
    "Wipro",
    "Accenture",
    "Cognizant",
    "Capgemini",
)

# Data-quality tolerances (flag only, never drop).
DURATION_TOLERANCE_MONTHS = 1
OVERLAP_TOLERANCE_DAYS = 31
EXPERIENCE_MISMATCH_TOLERANCE_YEARS = 2.0
SKILL_DURATION_SLACK_MONTHS = 12
# submission_spec.md honeypot example: "'expert' proficiency in 10 skills with 0 years used".
EXPERT_MIN_USAGE_MONTHS = 12
