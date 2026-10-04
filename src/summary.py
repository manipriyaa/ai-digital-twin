"""Compact candidate-level records.

* ``build_candidate_summary`` -> one small row per candidate for fast loading later
  (no full descriptions or skill lists; those live in evidence_chunks.jsonl).
* ``build_behavioral_row``    -> the 23 Redrob signals as individual flat columns,
  raw values preserved, plus a few clearly-labelled derived fields. No combined
  "behaviour score" is computed.
"""
from __future__ import annotations

import datetime as dt
from typing import List

from .evidence import BEHAVIOR_GROUPS, is_jd_named_consulting_firm
from .normalize import months_between, parse_date

SIGNAL_NAMES = [n for names in BEHAVIOR_GROUPS.values() for n in names]


def _career_stats(cand: dict, reference_date: dt.date) -> dict:
    career = cand["career"]
    chrono = sorted(career, key=lambda r: (r["start_date"] is None, r["start_date"] or "", r["index"]))
    starts = [parse_date(r["start_date"]) for r in career]
    starts = [s for s in starts if s]
    durations = [r["duration_months"] for r in career if r["duration_months"] is not None]
    current = [r for r in career if r["is_current"]]
    companies = {r["company"] for r in career if r["company"]}
    return {
        "career_count": len(career),
        "first_role_start": min(starts).isoformat() if starts else None,
        "career_span_months": months_between(min(starts), reference_date) if starts else None,
        "sum_role_months": sum(durations) if durations else None,
        "current_role_months": current[0]["duration_months"] if len(current) == 1 else None,
        "distinct_companies": len(companies),
        "roles_shorter_than_18_months": sum(1 for d in durations if d < 18),
        "title_sequence": [r["title"] for r in chrono],
        "company_sequence": [r["company"] for r in chrono],
        "industries": sorted({r["industry"] for r in career if r["industry"]}),
        "jd_named_consulting_roles": sum(1 for r in career if is_jd_named_consulting_firm(r["company"])),
    }


def build_candidate_summary(cand: dict, source_line: int, schema_valid: bool, schema_error_categories: List[str],
                            flags: List[dict], evidence_count: int, reference_date: dt.date) -> dict:
    p = cand["profile"]
    s = cand["signals"] or {}
    last_active = parse_date(s.get("last_active_date"))
    summary = {
        "candidate_id": cand["candidate_id"],
        "source_line": source_line,
        "schema_valid": schema_valid,
        "schema_error_categories": schema_error_categories,
        "current_title": p["current_title"],
        "current_company": p["current_company"],
        "current_industry": p["current_industry"],
        "current_company_size": p["current_company_size"],
        "location": p["location"],
        "country": p["country"],
        "years_of_experience": p["years_of_experience"],
        "headline": p["headline"],
        "summary_text": p["summary"],
    }
    summary.update(_career_stats(cand, reference_date))
    summary.update({
        "skill_count": len(cand["skills"]),
        "expert_skill_count": sum(1 for s in cand["skills"] if s["proficiency"] == "expert"),
        "education_count": len(cand["education"]),
        "certification_count": len(cand["certifications"]),
        "languages": [l["language"] for l in cand["languages"] if l["language"]],
        "behavioral_available": cand["signals"] is not None,
        "open_to_work_flag": s.get("open_to_work_flag"),
        "last_active_date": s.get("last_active_date"),
        "days_since_last_active": (reference_date - last_active).days if last_active else None,
        "notice_period_days": s.get("notice_period_days"),
        "willing_to_relocate": s.get("willing_to_relocate"),
        "preferred_work_mode": s.get("preferred_work_mode"),
        "evidence_count": evidence_count,
        "quality_flags": sorted({f["code"] for f in flags}),
    })
    return summary


def build_behavioral_row(cand: dict, reference_date: dt.date) -> dict:
    s = cand["signals"] or {}
    row = {"candidate_id": cand["candidate_id"], "behavioral_available": cand["signals"] is not None}
    for name in SIGNAL_NAMES:
        value = s.get(name)
        if name == "expected_salary_range_inr_lpa":
            value = value if isinstance(value, dict) else {}
            row["expected_salary_min_inr_lpa"] = value.get("min")
            row["expected_salary_max_inr_lpa"] = value.get("max")
        else:
            row[name] = value
    last_active, signup = parse_date(s.get("last_active_date")), parse_date(s.get("signup_date"))
    assessments = s.get("skill_assessment_scores")
    gh, oar = s.get("github_activity_score"), s.get("offer_acceptance_rate")
    row["derived"] = {
        "reference_date": reference_date.isoformat(),
        "days_since_last_active": (reference_date - last_active).days if last_active else None,
        "days_since_signup": (reference_date - signup).days if signup else None,
        "github_linked": None if gh is None else gh != -1,
        "has_offer_history": None if oar is None else oar != -1,
        "assessment_count": len(assessments) if isinstance(assessments, dict) else None,
    }
    return row
