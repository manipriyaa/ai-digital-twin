"""Build the structured requirement map (data/processed/jd_requirements.json).

Requirements are data (config/requirement_specs.json), not code: adding one needs
no change here or in the preprocessing engine. This module:

1. parses the actual job description document,
2. validates every spec (ids, categories, importance, query lists),
3. grounds every spec: each ``jd_anchors`` quote must appear verbatim in a parsed
   JD block, and is replaced by {block_id, section, quote}. A missing anchor is an
   error, so requirements cannot drift away from the source document,
4. reports JD blocks that no requirement cites (coverage audit).

No scoring happens here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from . import config
from .jd_parser import iter_blocks, parse_job_description
from .normalize import normalize_text
from .utils import write_json

REQUIREMENT_CATEGORIES = (
    "technical_must_have", "technical_preference", "experience", "seniority",
    "career_risk", "domain_fit", "logistics", "behavioral",
)
EVIDENCE_TYPES = ("profile", "career", "skill", "education", "certification", "behavior")
ASSERTION_LEVELS = ("declared", "self_described", "demonstrated", "credential", "behavioral")
REQUIRED_KEYS = ("requirement_id", "category", "name", "importance", "jd_strength", "hard_constraint",
                 "description", "jd_anchors", "positive_queries", "negative_queries", "evidence_types")

# Sections whose blocks are requirement-bearing (used for the coverage audit).
_NON_REQUIREMENT_BLOCK_PREFIXES = ("Most JDs list", "This is the section most JDs skip", "That said, here are",
                                   "In practical terms", "The \"ideal candidate\"", "Good luck",
                                   "If you're reading this in the context")


class RequirementSpecError(ValueError):
    pass


def load_specs(path: Path | str = config.REQUIREMENT_SPECS_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_spec(spec: dict, categories: dict, strengths: dict) -> List[str]:
    problems = []
    rid = spec.get("requirement_id", "?")
    for key in REQUIRED_KEYS:
        if key not in spec:
            problems.append(f"{rid}: missing {key}")
    if problems:
        return problems
    if spec["category"] not in REQUIREMENT_CATEGORIES or spec["category"] not in categories:
        problems.append(f"{rid}: unknown category {spec['category']!r}")
    if spec["jd_strength"] not in strengths:
        problems.append(f"{rid}: unknown jd_strength {spec['jd_strength']!r}")
    if not isinstance(spec["importance"], (int, float)) or not 0 <= spec["importance"] <= 1:
        problems.append(f"{rid}: importance must be in [0, 1]")
    if not isinstance(spec["hard_constraint"], bool):
        problems.append(f"{rid}: hard_constraint must be boolean")
    if not spec["jd_anchors"]:
        problems.append(f"{rid}: needs at least one jd_anchor")
    for key in ("positive_queries", "negative_queries"):
        if not isinstance(spec[key], list) or not all(isinstance(q, str) and q.strip() for q in spec[key]):
            problems.append(f"{rid}: {key} must be a list of non-empty strings")
    if spec["category"] != "behavioral" and not spec["positive_queries"]:
        problems.append(f"{rid}: non-behavioural requirement needs positive_queries")
    for t in spec["evidence_types"]:
        if t not in EVIDENCE_TYPES:
            problems.append(f"{rid}: unknown evidence type {t!r}")
    for lvl in spec.get("supporting_assertion_levels", []):
        if lvl not in ASSERTION_LEVELS:
            problems.append(f"{rid}: unknown assertion level {lvl!r}")
    return problems


def _ground_anchor(anchor: str, blocks: List[tuple]) -> Optional[dict]:
    needle = normalize_text(anchor)
    for heading, block in blocks:
        if needle and needle in block["text"]:
            return {"block_id": block["block_id"], "section": heading, "quote": needle}
    return None


def build_requirement_map(jd_path: Path | str = config.JOB_DESCRIPTION_PATH,
                          specs_path: Path | str = config.REQUIREMENT_SPECS_PATH) -> dict:
    parsed = parse_job_description(jd_path)
    specs = load_specs(specs_path)
    blocks = list(iter_blocks(parsed))

    problems: List[str] = []
    seen_ids, seen_names = set(), set()
    requirements = []
    cited_blocks = set()
    for spec in specs["requirements"]:
        issues = validate_spec(spec, specs["categories"], specs["jd_strength_levels"])
        rid = spec.get("requirement_id")
        if rid in seen_ids:
            issues.append(f"{rid}: duplicate requirement_id")
        if spec.get("name") in seen_names:
            issues.append(f"{rid}: duplicate name {spec.get('name')!r}")
        seen_ids.add(rid)
        seen_names.add(spec.get("name"))
        if issues:
            problems.extend(issues)
            continue

        jd_evidence = []
        for anchor in spec["jd_anchors"]:
            grounded = _ground_anchor(anchor, blocks)
            if grounded is None:
                problems.append(f"{rid}: anchor not found in JD: {anchor[:80]!r}")
            else:
                jd_evidence.append(grounded)
                cited_blocks.add(grounded["block_id"])

        req = {k: v for k, v in spec.items() if k != "jd_anchors"}
        req["jd_evidence"] = jd_evidence
        requirements.append(req)

    unmodelled = []
    for item in specs.get("unmodelled_jd_content", []):
        grounded = _ground_anchor(item["anchor"], blocks)
        if grounded is None:
            problems.append(f"unmodelled anchor not found in JD: {item['anchor'][:80]!r}")
            continue
        cited_blocks.add(grounded["block_id"])
        unmodelled.append({**grounded, "reason": item["reason"]})

    if problems:
        raise RequirementSpecError("requirement specs failed validation:\n  " + "\n  ".join(problems))

    uncited = [{"block_id": b["block_id"], "section": h, "text": b["text"]}
               for h, b in blocks
               if b["block_id"] not in cited_blocks and not b["text"].startswith(_NON_REQUIREMENT_BLOCK_PREFIXES)]

    by_category = {}
    for r in requirements:
        by_category.setdefault(r["category"], []).append(r["requirement_id"])

    return {
        "source_document": parsed["source_document"],
        "source_sha256": parsed["source_sha256"],
        "role_title": parsed["role_title"],
        "header_fields": parsed["header_fields"],
        "query_semantics": {
            "positive_queries": "Concepts whose presence SUPPORTS fit on this requirement.",
            "negative_queries": "Concepts whose presence CONTRADICTS fit (for risk requirements: the risk pattern). "
                                "Retrieval probes for contradicting evidence; not automatic penalties.",
            "importance": "JD-stated emphasis in [0, 1]; a prior, not a learned weight. No scoring in Phase 1.",
            "hard_constraint": "The JD states this as a disqualifier. Not applied in Phase 1.",
            "supporting_assertion_levels": "Evidence assertion levels that may count as support. A declared "
                                           "skill alone never demonstrates a production requirement.",
        },
        "categories": specs["categories"],
        "jd_strength_levels": specs["jd_strength_levels"],
        "requirements_by_category": by_category,
        "requirements": requirements,
        "unmodelled_jd_content": unmodelled,
        "uncited_jd_blocks": uncited,
    }


def load_requirement_map(path: Path | str) -> dict:
    """Load a built jd_requirements.json (used by later phases and tests)."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    for r in data["requirements"]:
        if r["category"] not in REQUIREMENT_CATEGORIES:
            raise RequirementSpecError(f"{r['requirement_id']}: unknown category {r['category']!r}")
    return data


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Build the grounded JD requirement map.")
    ap.add_argument("--jd", type=Path, default=config.JOB_DESCRIPTION_PATH)
    ap.add_argument("--specs", type=Path, default=config.REQUIREMENT_SPECS_PATH)
    ap.add_argument("--output-dir", type=Path, default=config.PROCESSED_DIR)
    args = ap.parse_args(argv)
    req_map = build_requirement_map(args.jd, args.specs)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / config.JD_PARSED_FILE, parse_job_description(args.jd))
    write_json(args.output_dir / config.JD_REQUIREMENTS_FILE, req_map)
    reqs = req_map["requirements"]
    print(f"{req_map['role_title']}: {len(reqs)} requirements, "
          f"{sum(len(r['positive_queries']) for r in reqs)} positive / "
          f"{sum(len(r['negative_queries']) for r in reqs)} negative queries, "
          f"{len(req_map['uncited_jd_blocks'])} uncited JD blocks")
    for cat, ids in req_map["requirements_by_category"].items():
        print(f"  {cat:22s} {', '.join(ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
