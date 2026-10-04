import copy

import pytest

from src.schema import (error_categories, is_valid_candidate_id, load_schema,
                        validate_candidate)


@pytest.mark.parametrize("cid,ok", [
    ("CAND_0000001", True),
    ("CAND_9999999", True),
    ("CAND_000001", False),      # 6 digits
    ("CAND_00000001", False),    # 8 digits
    ("cand_0000001", False),     # case
    ("CAND_00000A1", False),
    (" CAND_0000001", False),
    ("CAND_0000001\n", False),
    (1234567, False),
    (None, False),
])
def test_candidate_id_validation(cid, ok):
    assert is_valid_candidate_id(cid) is ok


def test_all_real_samples_are_schema_valid(sample_records):
    schema = load_schema()
    assert all(validate_candidate(r, schema) == [] for r in sample_records)


def test_missing_required_fields_are_categorised(record):
    for field, category in [("candidate_id", "missing_candidate_id"), ("profile", "missing_profile"),
                            ("career_history", "invalid_career_history"), ("skills", "invalid_skills"),
                            ("education", "invalid_education"), ("redrob_signals", "invalid_behavioral_signals")]:
        rec = copy.deepcopy(record)
        rec.pop(field)
        errors = validate_candidate(rec)
        assert (field, "required field missing") in errors
        assert category in error_categories(errors)


def test_nested_violations(record):
    record["candidate_id"] = "CAND_12"
    record["career_history"][1]["start_date"] = "March 2021"
    record["skills"][0]["proficiency"] = "guru"
    record["redrob_signals"]["recruiter_response_rate"] = 1.5
    record["redrob_signals"]["skill_assessment_scores"]["FAISS"] = 140
    record["profile"]["years_of_experience"] = True  # bool is not a number in JSON Schema
    paths = {p for p, _ in validate_candidate(record)}
    assert paths == {"candidate_id", "career_history[1].start_date", "skills[0].proficiency",
                     "redrob_signals.recruiter_response_rate", "redrob_signals.skill_assessment_scores.FAISS",
                     "profile.years_of_experience"}
    assert error_categories(validate_candidate(record)) == [
        "invalid_behavioral_signals", "invalid_candidate_id", "invalid_career_history",
        "invalid_profile", "invalid_skills"]


def test_non_object_and_wrong_container_types(record):
    assert error_categories(validate_candidate(["x"])) == ["not_an_object"]
    record["career_history"] = "oops"
    assert "invalid_career_history" in error_categories(validate_candidate(record))


def test_patterns_use_end_of_input_semantics(record):
    record["career_history"][0]["start_date"] = "2025-04-02\n"
    assert [p for p, _ in validate_candidate(record)] == ["career_history[0].start_date"]


def test_null_end_date_allowed_but_null_start_date_not(record):
    record["career_history"][0]["end_date"] = None
    assert validate_candidate(record) == []
    record["career_history"][0]["start_date"] = None
    assert validate_candidate(record) != []


def test_agrees_with_reference_jsonschema(sample_records):
    """Our fast validator must accept/reject exactly what jsonschema does."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = load_schema()
    ref = jsonschema.Draft7Validator(schema, format_checker=jsonschema.FormatChecker())

    variants = []
    for rec in sample_records[:10]:
        variants.append(rec)
        for mutate in (
            lambda r: r.pop("profile"),
            lambda r: r.__setitem__("candidate_id", "CAND_1"),
            lambda r: r["career_history"].clear(),                       # minItems 1
            lambda r: r["career_history"][0].__setitem__("duration_months", -3),
            lambda r: r["career_history"][0].__setitem__("end_date", "2021-02-30"),
            lambda r: r["education"].extend([r["education"][0]] * 5),     # maxItems 5
            lambda r: r["redrob_signals"].__setitem__("github_activity_score", -2),
            lambda r: r["redrob_signals"].__setitem__("preferred_work_mode", "office"),
            lambda r: r["redrob_signals"]["expected_salary_range_inr_lpa"].pop("max"),
            lambda r: r["skills"].append({"name": "X", "proficiency": "expert", "endorsements": 1.0}),
        ):
            v = copy.deepcopy(rec)
            mutate(v)
            variants.append(v)

    for v in variants:
        ours = {p for p, _ in validate_candidate(v, schema)}
        theirs = {".".join(str(x) for x in e.absolute_path) for e in ref.iter_errors(v)}
        assert bool(ours) == bool(theirs), (ours, theirs)


def test_schema_loader_rejects_unsupported_keywords(tmp_path):
    bad = tmp_path / "schema.json"
    bad.write_text('{"type": "object", "oneOf": [{"type": "object"}]}')
    with pytest.raises(ValueError, match="unsupported"):
        load_schema(str(bad))
