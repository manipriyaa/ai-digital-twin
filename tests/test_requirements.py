import json

import pytest

from src import config
from src.jd_parser import iter_blocks, parse_job_description
from src.requirement_map import (REQUIREMENT_CATEGORIES, RequirementSpecError, build_requirement_map,
                                 load_requirement_map, load_specs)
from src.utils import write_json


@pytest.fixture(scope="module")
def parsed_jd():
    return parse_job_description(config.JOB_DESCRIPTION_PATH)


@pytest.fixture(scope="module")
def req_map():
    return build_requirement_map()


def test_jd_parsed_from_actual_document(parsed_jd):
    assert parsed_jd["source_document"] == "job_description.docx"
    assert parsed_jd["role_title"] == "Senior AI Engineer — Founding Team"
    assert parsed_jd["header_fields"]["experience_required"].startswith("5–9 years")
    headings = [s["heading"] for s in parsed_jd["sections"]]
    assert "Things you absolutely need" in headings
    must = next(s for s in parsed_jd["sections"] if s["heading"] == "Things you absolutely need")
    assert len(must["blocks"]) == 4
    assert len({b["block_id"] for _, b in iter_blocks(parsed_jd)}) == sum(1 for _ in iter_blocks(parsed_jd))


def test_requirement_map_structure(req_map):
    reqs = req_map["requirements"]
    ids = [r["requirement_id"] for r in reqs]
    assert len(ids) == len(set(ids)) == 24
    assert ids == sorted(ids)
    for r in reqs:
        assert r["category"] in REQUIREMENT_CATEGORIES
        assert 0 <= r["importance"] <= 1
        assert isinstance(r["hard_constraint"], bool)
        assert r["jd_evidence"], r["requirement_id"]
        assert r["evidence_types"]
        if r["category"] != "behavioral":
            assert r["positive_queries"] and r["description"]
    assert {r["category"] for r in reqs} == set(REQUIREMENT_CATEGORIES)
    must = [r["requirement_id"] for r in reqs if r["category"] == "technical_must_have"]
    assert must == ["R01", "R02", "R03", "R04"]
    assert [r["requirement_id"] for r in reqs if r["hard_constraint"]] == ["R18"]


def test_core_requirements_have_negative_concepts(req_map):
    by_id = {r["requirement_id"]: r for r in req_map["requirements"]}
    for rid in ("R01", "R02", "R04", "R07", "R09", "R11", "R12", "R13", "R18", "R19"):
        assert len(by_id[rid]["negative_queries"]) >= 3, rid
    assert any("tutorial" in q for q in by_id["R01"]["negative_queries"])


def test_production_requirements_need_demonstrated_evidence(req_map):
    """Declared skills alone may never satisfy production must-haves."""
    by_id = {r["requirement_id"]: r for r in req_map["requirements"]}
    for rid in ("R01", "R02", "R04", "R09"):
        assert by_id[rid]["supporting_assertion_levels"] == ["demonstrated"]
        assert "skill" not in by_id[rid]["evidence_types"]


def test_every_requirement_quote_is_verbatim_in_jd(req_map, parsed_jd):
    blocks = {b["block_id"]: b["text"] for _, b in iter_blocks(parsed_jd)}
    for r in req_map["requirements"]:
        for ev in r["jd_evidence"]:
            assert ev["quote"] in blocks[ev["block_id"]]
    assert req_map["source_sha256"] == parsed_jd["source_sha256"]


def test_ungrounded_requirement_is_rejected(tmp_path):
    specs = load_specs()
    specs["requirements"][0]["jd_anchors"] = ["Must have 10 years of Rust and a Kubernetes certification."]
    path = tmp_path / "specs.json"
    write_json(path, specs)
    with pytest.raises(RequirementSpecError, match="anchor not found"):
        build_requirement_map(config.JOB_DESCRIPTION_PATH, path)


def test_invalid_spec_is_rejected(tmp_path):
    specs = load_specs()
    specs["requirements"][1]["category"] = "vibes"
    specs["requirements"][2]["importance"] = 3
    path = tmp_path / "specs.json"
    write_json(path, specs)
    with pytest.raises(RequirementSpecError) as exc:
        build_requirement_map(config.JOB_DESCRIPTION_PATH, path)
    assert "unknown category" in str(exc.value) and "importance" in str(exc.value)


def test_new_requirement_added_through_config_only(tmp_path):
    specs = load_specs()
    specs["requirements"].append({
        "requirement_id": "R99", "category": "technical_preference", "name": "async_writing",
        "importance": 0.2, "jd_strength": "soft_preference", "hard_constraint": False,
        "description": "Writes a lot, async-first.", "jd_anchors": ["We work async-first and write a lot."],
        "positive_queries": ["design docs"], "negative_queries": [], "evidence_types": ["profile"],
    })
    path = tmp_path / "specs.json"
    write_json(path, specs)
    built = build_requirement_map(config.JOB_DESCRIPTION_PATH, path)
    assert built["requirements"][-1]["requirement_id"] == "R99"


def test_requirement_map_round_trip(req_map, tmp_path):
    path = tmp_path / config.JD_REQUIREMENTS_FILE
    write_json(path, req_map)
    loaded = load_requirement_map(path)
    assert loaded == json.loads(json.dumps(req_map))
    assert build_requirement_map() == req_map  # deterministic
