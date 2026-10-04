import copy
import datetime as dt
import json
import re
from pathlib import Path

import pytest

from src import config
from src.evidence import (BEHAVIOR_GROUPS, EVIDENCE_TYPES, build_all_evidence,
                          build_behavior_evidence, build_career_evidence, build_skill_evidence)
from src.normalize import (match_key, months_between, normalize_candidate, normalize_company,
                           normalize_date, normalize_skill, normalize_text, normalize_title)
from src.preprocess import run
from src.quality import run_quality_checks
from src.schema import load_schema

REF = config.DEFAULT_REFERENCE_DATE
ROOT = Path(__file__).resolve().parent.parent


def _evidence(record, line=7):
    return build_all_evidence(normalize_candidate(record), line, REF)


# --------------------------------------------------------------------- normalisation

def test_normalize_text_whitespace_and_nulls():
    assert normalize_text("  Senior   ML\tEngineer \n") == "Senior ML Engineer"
    assert normalize_text("Café Lead") == "Café Lead"   # NFC + Unicode space
    for empty in (None, "", "   ", 5, ["x"]):
        assert normalize_text(empty) is None


def test_titles_stay_distinguishable():
    titles = ["ML Engineer", "Machine Learning Engineer", "Senior ML Engineer"]
    assert len({normalize_title(t) for t in titles}) == 3
    assert len({match_key(t) for t in titles}) == 3
    assert normalize_company(" Mad  Street Den ") == "Mad Street Den"
    assert normalize_skill("Hugging Face  Transformers") == "Hugging Face Transformers"
    assert match_key("Sentence-Transformers") == match_key("sentence transformers")


@pytest.mark.parametrize("raw,expected", [
    ("2021-07-22", "2021-07-22"),
    (" 2021-07-22 ", "2021-07-22"),
    ("2021-02-30", None),       # impossible day
    ("2021-7-22", None),
    ("March 2021", None),
    ("2021-07", None),          # partial dates are not guessed
    ("22/07/2021", None),
    (None, None),
    (20210722, None),
])
def test_normalize_date(raw, expected):
    assert normalize_date(raw) == expected


def test_month_convention_reproduces_dataset_durations(sample_records):
    """duration_months in the data == (end - start).days // 30 (reference date for current roles)."""
    for rec in sample_records:
        for role in rec["career_history"]:
            start = dt.date.fromisoformat(role["start_date"])
            end = dt.date.fromisoformat(role["end_date"]) if role["end_date"] else REF
            assert months_between(start, end) == role["duration_months"]


# --------------------------------------------------------------------- evidence

def test_career_evidence(record):
    units = build_career_evidence(normalize_candidate(record), 31, REF)
    assert [u["source_field"] for u in units] == [f"career_history[{i}]" for i in range(4)]
    current, oldest = units[0], units[3]
    assert current["assertion_level"] == "demonstrated"
    assert current["metadata"]["is_current"] is True and current["metadata"]["end_date"] is None
    assert current["metadata"]["months_since_end"] == 0
    assert current["metadata"]["duration_months"] == 14
    assert oldest["metadata"]["chronological_position"] == 0
    assert oldest["metadata"]["start_date"] == "2020-06-27" and oldest["metadata"]["end_date"] == "2021-07-22"
    assert oldest["metadata"]["months_since_end"] == months_between(dt.date(2021, 7, 22), REF)
    # Structure is not flattened: title/company/description recoverable separately.
    for u, role in zip(units, record["career_history"]):
        assert u["metadata"]["title"] == role["title"] and u["metadata"]["company"] == role["company"]
        assert u["text"][u["metadata"]["description_start"]:] == role["description"]
    # CAND_0000031 reuses one description for three roles: linked, not dropped.
    assert units[1]["metadata"]["description_duplicate_of"] == units[0]["evidence_id"]


def test_unknown_dates_stay_null(record):
    record["career_history"][1]["end_date"] = "sometime"
    unit = build_career_evidence(normalize_candidate(record), 1, REF)[1]
    assert unit["metadata"]["end_date"] is None
    assert unit["metadata"]["months_since_end"] is None
    assert unit["metadata"]["duration_months_from_dates"] is None


def test_skill_evidence_is_declared_not_demonstrated(record):
    units = build_skill_evidence(normalize_candidate(record), 31)
    assert len(units) == len(record["skills"])
    assert {u["assertion_level"] for u in units} == {"declared"}
    by_name = {u["metadata"]["name"]: u for u in units}
    faiss = by_name["FAISS"]["metadata"]
    assert (faiss["proficiency"], faiss["endorsements"], faiss["duration_months"]) == ("advanced", 19, 35)
    assert faiss["platform_assessment_score"] == 68.4
    assert faiss["platform_assessment_source"] == "redrob_signals.skill_assessment_scores['FAISS']"
    # Lexical cross-references point at narrative fields only when the term really appears.
    assert by_name["Feature Engineering"]["metadata"]["lexical_mentions"] == ["profile.summary"]
    assert by_name["Embeddings"]["metadata"]["lexical_mentions"] == []


def test_skill_mentions_respect_word_boundaries(record):
    record["skills"] = [{"name": "Go", "proficiency": "beginner", "endorsements": 0, "duration_months": 1},
                        {"name": "XGBoost", "proficiency": "beginner", "endorsements": 0, "duration_months": 1}]
    record["profile"]["summary"] = "Good at Google-scale systems."
    units = build_skill_evidence(normalize_candidate(record), 1)
    assert units[0]["metadata"]["lexical_mentions"] == []          # "Go" not inside "Good"/"Google"
    assert "career_history[0].description" in units[1]["metadata"]["lexical_mentions"]


def test_behavioral_evidence_separate_and_complete(record):
    units = build_behavior_evidence(normalize_candidate(record), 31, REF)
    assert [u["evidence_subtype"] for u in units] == [f"behavior.{g}" for g in BEHAVIOR_GROUPS]
    assert {u["evidence_type"] for u in units} == {"behavior"}
    covered = [n for u in units for n in u["metadata"]["signals"]]
    schema_signals = load_schema()["properties"]["redrob_signals"]["required"]
    assert sorted(covered) == sorted(schema_signals) and len(covered) == 23
    for u in units:  # raw values preserved exactly
        for name, value in u["metadata"]["signals"].items():
            assert value == record["redrob_signals"][name]
    activity = units[0]["metadata"]["derived"]
    assert activity["days_since_last_active"] == (REF - dt.date.fromisoformat("2026-05-24")).days


def test_behavior_sentinels(record):
    record["redrob_signals"]["github_activity_score"] = -1
    units = build_behavior_evidence(normalize_candidate(record), 1, REF)
    tech = next(u for u in units if u["evidence_subtype"] == "behavior.technical_activity")
    assert tech["metadata"]["sentinel_values"] == ["github_activity_score"]
    assert "no GitHub linked" in tech["text"]
    assert tech["metadata"]["signals"]["github_activity_score"] == -1


def _resolve(record, source_field):
    """Follow a provenance path back into the raw record."""
    if source_field.startswith("redrob_signals#"):
        return record["redrob_signals"]
    node = record
    for name, idx in re.findall(r"([A-Za-z_]+)(?:\[(\d+)\])?", source_field):
        node = node[name]
        if idx:
            node = node[int(idx)]
    return node


def test_provenance_resolves_to_raw_record(sample_records):
    for line, rec in enumerate(sample_records, start=1):
        units = _evidence(rec, line)
        ids = [u["evidence_id"] for u in units]
        assert len(ids) == len(set(ids))
        for u in units:
            assert u["candidate_id"] == rec["candidate_id"] and u["source_line"] == line
            assert u["evidence_type"] in EVIDENCE_TYPES
            assert u["evidence_id"] == f"{rec['candidate_id']}:{u['evidence_type']}:{u['source_field']}"
            target = _resolve(rec, u["source_field"])
            if u["evidence_type"] in ("career", "skill", "education", "certification"):
                assert u["source_index"] is not None
                assert target is rec[u["source_field"].split("[")[0]][u["source_index"]]
            if u["evidence_subtype"] in ("profile.headline", "profile.summary"):
                assert normalize_text(target) == u["text"]
            if u["evidence_type"] == "skill":
                assert u["metadata"]["name"] == normalize_text(target["name"])


def test_no_evidence_is_invented_for_missing_sections(record):
    record["skills"] = []
    record["education"] = []
    record["certifications"] = []
    record["profile"]["summary"] = ""
    units = _evidence(record)
    types = {u["evidence_subtype"] for u in units}
    assert "profile.summary" not in types
    assert not {"skill", "education", "certification"} & {u["evidence_type"] for u in units}


# --------------------------------------------------------------------- quality

def test_quality_flags(record):
    ch = record["career_history"]
    ch[1]["end_date"] = "2025-08-01"                 # overlaps the current role (starts 2025-04-02)
    ch[2]["duration_months"] = 99                    # disagrees with dates
    ch[3]["start_date"], ch[3]["end_date"] = "2021-07-22", "2020-06-27"   # ends before start
    record["redrob_signals"]["expected_salary_range_inr_lpa"] = {"min": 30, "max": 10}
    record["redrob_signals"]["signup_date"] = "2026-05-30"
    record["profile"]["current_company"] = ""
    codes = {f["code"] for f in run_quality_checks(normalize_candidate(record), [], REF)}
    assert {"overlapping_roles", "duration_mismatch", "end_before_start", "salary_min_gt_max",
            "signup_after_last_active", "missing_current_company",
            "skill_duration_exceeds_experience", "duplicate_role_description"} <= codes


def test_expert_skill_without_usage_flag(record):
    """submission_spec.md honeypot example: 'expert' proficiency with 0 years used."""
    record["skills"][0].update(proficiency="expert", duration_months=0)
    flags = run_quality_checks(normalize_candidate(record), [], REF)
    hit = [f for f in flags if f["code"] == "expert_skill_without_usage"]
    assert len(hit) == 1 and hit[0]["source_field"] == "skills[0]"


def test_no_expert_without_usage_in_real_sample(sample_records):
    for rec in sample_records:
        codes = {f["code"] for f in run_quality_checks(normalize_candidate(rec), [], REF)}
        assert "expert_skill_without_usage" not in codes


def test_clean_record_has_no_error_flags(sample_records):
    flags = run_quality_checks(normalize_candidate(sample_records[30]), [], REF)
    assert not [f for f in flags if f["severity"] == "error"]


# --------------------------------------------------------------------- pipeline

def _read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def test_sample_preprocessing_with_limit(sample_jsonl, tmp_path):
    report = run(sample_jsonl, tmp_path / "out10", limit=10)
    assert report["total_candidates"] == 10 and report["emitted_candidates"] == 10
    summaries = _read_jsonl(tmp_path / "out10" / config.CANDIDATE_SUMMARY_FILE)
    assert [s["candidate_id"] for s in summaries] == [f"CAND_{i:07d}" for i in range(1, 11)]

    report = run(sample_jsonl, tmp_path / "all", limit=0)
    assert report["total_candidates"] == report["valid_candidates"] == 50
    assert report["invalid_candidates"] == 0 and report["quarantined_records"] == 0
    assert set(report["evidence_by_type"]) == set(EVIDENCE_TYPES)
    assert all(report["evidence_by_type"][t] > 0 for t in EVIDENCE_TYPES)
    evidence = _read_jsonl(tmp_path / "all" / config.EVIDENCE_FILE)
    assert len(evidence) == report["total_evidence"]

    summary = summaries[0]
    for key in ("current_title", "current_company", "location", "years_of_experience", "summary_text",
                "career_count", "skill_count", "education_count", "behavioral_available", "quality_flags"):
        assert key in summary
    stats = json.loads((tmp_path / "all" / config.COMPANY_STATS_FILE).read_text())
    assert stats["company_count"] == report["distinct_companies"] > 0
    acme = stats["companies"]["acme corp"]
    assert acme["role_count"] == sum(acme["start_year_histogram"].values())
    assert stats["companies"]["cognizant"]["is_jd_named_consulting_firm"] is True
    behavior_rows = _read_jsonl(tmp_path / "all" / config.BEHAVIORAL_SIGNALS_FILE)
    assert len(behavior_rows) == 50 and "recruiter_response_rate" in behavior_rows[0]


def test_malformed_records_do_not_crash_the_run(sample_records, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("stress", ROOT / "scripts" / "make_stress_dataset.py")
    stress = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stress)

    path = tmp_path / "mixed.jsonl"
    bad = stress.corruptions(sample_records[0])
    with open(path, "w", encoding="utf-8") as fh:
        for rec in sample_records[:5]:
            fh.write(json.dumps(rec) + "\n")
        fh.write("\n")  # blank line is skipped, not an error
        for _, line in bad:
            fh.write(line + "\n")

    report = run(path, tmp_path / "out")
    c = report["validation_counters"]
    assert report["total_candidates"] == 5 + len(bad)
    for key in ("json_parse_error", "not_an_object", "missing_candidate_id", "invalid_candidate_id",
                "duplicate_candidate_id", "missing_profile", "invalid_career_history",
                "invalid_skills", "invalid_behavioral_signals"):
        assert c[key] >= 1, key
    # Unidentifiable or duplicate records are quarantined with their raw line ...
    quarantined = _read_jsonl(tmp_path / "out" / config.INVALID_RECORDS_FILE)
    assert len(quarantined) == report["quarantined_records"] == 5
    assert all(q["raw"] and q["source_line"] > 5 for q in quarantined)
    # ... identifiable-but-invalid ones are kept and flagged, never silently dropped.
    summaries = {s["candidate_id"]: s for s in _read_jsonl(tmp_path / "out" / config.CANDIDATE_SUMMARY_FILE)}
    assert report["emitted_candidates"] == 5 + 6
    assert summaries["CAND_9999907"]["behavioral_available"] is False
    assert summaries["CAND_9999904"]["schema_valid"] is False
    assert "malformed_date" in summaries["CAND_9999904"]["quality_flags"]


def test_output_is_deterministic(sample_jsonl, tmp_path):
    reports = [run(sample_jsonl, tmp_path / name) for name in ("a", "b")]
    for name in (config.CANDIDATE_SUMMARY_FILE, config.EVIDENCE_FILE, config.BEHAVIORAL_SIGNALS_FILE,
                 config.INVALID_RECORDS_FILE, config.COMPANY_STATS_FILE):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    for r in reports:
        r.pop("run_stats")
    assert reports[0] == reports[1]


def test_phase1_does_not_implement_later_phases():
    """Guard rail: no embeddings / ANN / BM25 / learned ranking / LLM calls in Phase 1."""
    forbidden = re.compile(r"^\s*(import|from)\s+(faiss|sentence_transformers|torch|transformers|rank_bm25|"
                           r"lightgbm|xgboost|sklearn|openai|anthropic|requests|httpx)\b", re.M)
    for path in (ROOT / "src").glob("*.py"):
        assert not forbidden.search(path.read_text(encoding="utf-8")), path.name


def test_bundled_validator_accepts_sample_submission():
    """The official validator and sample are intact (used as the format contract later)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("validator", config.RAW_DIR / "validate_submission.py")
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    assert validator.validate_submission(config.RAW_DIR / "sample_submission.csv") == []
