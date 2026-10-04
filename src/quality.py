"""Per-candidate data-quality checks. They FLAG issues; nothing is dropped or fixed.

The bundle README says the pool contains ~80 "honeypots with subtly impossible
profiles". These flags are the raw material for detecting them in a later phase;
Phase 1 does not decide what a flag means for ranking.

Each flag: {"code", "severity" (info|warning|error), "source_field", "detail"}.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from . import config
from .normalize import months_between, parse_date

QUALITY_CODES = {
    "malformed_date": "A date field is missing or not a valid ISO date.",
    "end_before_start": "A role or education ends before it starts.",
    "start_after_reference_date": "A role starts after the dataset reference date.",
    "duration_mismatch": "duration_months disagrees with start/end dates.",
    "current_flag_inconsistent": "is_current disagrees with end_date (null <=> current).",
    "multiple_current_roles": "More than one role is marked current.",
    "no_current_role": "No role is marked current.",
    "overlapping_roles": "Two roles overlap by more than the tolerance.",
    "profile_current_role_mismatch": "profile.current_title/company differs from the current role.",
    "missing_current_company": "profile.current_company is empty.",
    "empty_profile": "Headline and summary are both empty.",
    "empty_career_history": "No career entries.",
    "empty_skills": "No skills listed.",
    "empty_education": "No education entries (allowed by schema; informational).",
    "invalid_experience": "years_of_experience missing or outside 0-50.",
    "experience_vs_career_mismatch": "Stated years_of_experience far from summed role durations.",
    "skill_duration_exceeds_experience": "A skill is used for longer than total experience allows.",
    "expert_skill_without_usage": "'expert' proficiency with under a year of use (spec honeypot example).",
    "career_before_education": "First role starts before any education starts.",
    "education_end_before_start": "Education end_year precedes start_year.",
    "duplicate_role_description": "Identical description text reused across roles.",
    "invalid_behavioral_value": "A behavioural signal is missing, mistyped or out of range.",
    "salary_min_gt_max": "expected_salary_range_inr_lpa.min > max.",
    "signup_after_last_active": "signup_date is after last_active_date.",
    "last_active_after_reference_date": "last_active_date is after the reference date.",
    "duplicate_candidate_id": "candidate_id seen earlier in the file.",
}


def _flag(code: str, severity: str, source_field: str, detail: str) -> Dict[str, str]:
    return {"code": code, "severity": severity, "source_field": source_field, "detail": detail}


def _check_career(cand: dict, ref: dt.date, flags: List[dict]) -> None:
    career = cand["career"]
    if not career:
        flags.append(_flag("empty_career_history", "warning", "career_history", "no roles"))
        return

    intervals = []
    current = []
    for role in career:
        sf = f"career_history[{role['index']}]"
        start = parse_date(role["start_date"])
        end = parse_date(role["end_date"])
        if start is None:
            flags.append(_flag("malformed_date", "error", f"{sf}.start_date", repr(role["raw_start_date"])))
        if role["raw_end_date"] is not None and end is None:
            flags.append(_flag("malformed_date", "error", f"{sf}.end_date", repr(role["raw_end_date"])))
        if role["is_current"] is not None and role["is_current"] != (role["raw_end_date"] is None):
            flags.append(_flag("current_flag_inconsistent", "warning", sf,
                               f"is_current={role['is_current']} end_date={role['raw_end_date']!r}"))
        if role["is_current"]:
            current.append(role)
        if start and start > ref:
            flags.append(_flag("start_after_reference_date", "error", f"{sf}.start_date", role["start_date"]))
        if start and end and end < start:
            flags.append(_flag("end_before_start", "error", sf, f"{role['start_date']} > {role['end_date']}"))
        effective_end = end if end else (ref if role["raw_end_date"] is None else None)
        if start and effective_end and role["duration_months"] is not None:
            expected = months_between(start, effective_end)
            if abs(expected - role["duration_months"]) > config.DURATION_TOLERANCE_MONTHS:
                flags.append(_flag("duration_mismatch", "warning", f"{sf}.duration_months",
                                   f"stated {role['duration_months']}, dates imply {expected}"))
        if start and effective_end and effective_end >= start:
            intervals.append((start, effective_end, sf))

    if len(current) > 1:
        flags.append(_flag("multiple_current_roles", "warning", "career_history",
                           ", ".join(f"career_history[{r['index']}]" for r in current)))
    elif not current:
        flags.append(_flag("no_current_role", "info", "career_history", "no role has is_current=true"))
    else:
        p = cand["profile"]
        role = current[0]
        if (p["current_company"] and role["company"] and p["current_company"] != role["company"]) or \
           (p["current_title"] and role["title"] and p["current_title"] != role["title"]):
            flags.append(_flag("profile_current_role_mismatch", "warning", f"career_history[{role['index']}]",
                               f"profile: {p['current_title']} @ {p['current_company']}; "
                               f"role: {role['title']} @ {role['company']}"))

    intervals.sort()
    for (s1, e1, f1), (s2, e2, f2) in zip(intervals, intervals[1:]):
        overlap = (min(e1, e2) - s2).days
        if overlap > config.OVERLAP_TOLERANCE_DAYS:
            flags.append(_flag("overlapping_roles", "warning", f"{f1}|{f2}", f"{overlap} days overlap"))

    seen: Dict[str, str] = {}
    for role in career:
        d = role["description"]
        if not d:
            continue
        sf = f"career_history[{role['index']}].description"
        if d in seen:
            flags.append(_flag("duplicate_role_description", "info", sf, f"same text as {seen[d]}"))
        else:
            seen[d] = sf


def _check_profile(cand: dict, flags: List[dict]) -> None:
    p = cand["profile"]
    if not p["headline"] and not p["summary"]:
        flags.append(_flag("empty_profile", "warning", "profile", "headline and summary empty"))
    if not p["current_company"]:
        flags.append(_flag("missing_current_company", "warning", "profile.current_company", "empty"))
    yoe = p["years_of_experience"]
    if yoe is None or not 0 <= yoe <= 50:
        flags.append(_flag("invalid_experience", "error", "profile.years_of_experience", repr(yoe)))
        return
    total_months = sum(r["duration_months"] for r in cand["career"] if r["duration_months"] is not None)
    if cand["career"] and abs(total_months / 12 - yoe) > config.EXPERIENCE_MISMATCH_TOLERANCE_YEARS:
        flags.append(_flag("experience_vs_career_mismatch", "warning", "profile.years_of_experience",
                           f"stated {yoe:g}y, roles sum to {total_months / 12:.1f}y"))
    limit = yoe * 12 + config.SKILL_DURATION_SLACK_MONTHS
    for s in cand["skills"]:
        if s["duration_months"] is not None and s["duration_months"] > limit:
            flags.append(_flag("skill_duration_exceeds_experience", "warning", f"skills[{s['index']}]",
                               f"{s['name']}: {s['duration_months']} months vs {yoe:g}y experience"))


def _check_skills_education(cand: dict, flags: List[dict]) -> None:
    if not cand["skills"]:
        flags.append(_flag("empty_skills", "warning", "skills", "no skills"))
    for s in cand["skills"]:
        if s["proficiency"] == "expert" and s["duration_months"] is not None \
                and s["duration_months"] < config.EXPERT_MIN_USAGE_MONTHS:
            flags.append(_flag("expert_skill_without_usage", "warning", f"skills[{s['index']}]",
                               f"{s['name']}: expert, {s['duration_months']} months used"))
    if not cand["education"]:
        flags.append(_flag("empty_education", "info", "education", "no education"))
    for e in cand["education"]:
        if e["start_year"] is not None and e["end_year"] is not None and e["end_year"] < e["start_year"]:
            flags.append(_flag("education_end_before_start", "error", f"education[{e['index']}]",
                               f"{e['start_year']} > {e['end_year']}"))
    starts = [parse_date(r["start_date"]) for r in cand["career"]]
    starts = [s for s in starts if s]
    edu_starts = [e["start_year"] for e in cand["education"] if e["start_year"] is not None]
    if starts and edu_starts and min(starts).year < min(edu_starts):
        flags.append(_flag("career_before_education", "info", "career_history|education",
                           f"first role {min(starts).isoformat()}, first education starts {min(edu_starts)}"))


def _check_signals(cand: dict, schema_errors: List[tuple], ref: dt.date, flags: List[dict]) -> None:
    signals = cand["signals"]
    for path, message in schema_errors:
        if path.startswith("redrob_signals"):
            flags.append(_flag("invalid_behavioral_value", "error", path, message))
    if signals is None:
        return
    sal = signals.get("expected_salary_range_inr_lpa")
    if isinstance(sal, dict):
        lo, hi = sal.get("min"), sal.get("max")
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > hi:
            flags.append(_flag("salary_min_gt_max", "info", "redrob_signals.expected_salary_range_inr_lpa",
                               f"min {lo} > max {hi}"))
    signup, active = parse_date(signals.get("signup_date")), parse_date(signals.get("last_active_date"))
    if signup and active and signup > active:
        flags.append(_flag("signup_after_last_active", "warning", "redrob_signals.signup_date",
                           f"signup {signup} > last_active {active}"))
    if active and active > ref:
        flags.append(_flag("last_active_after_reference_date", "warning", "redrob_signals.last_active_date",
                           active.isoformat()))


def run_quality_checks(cand: dict, schema_errors: List[tuple], reference_date: dt.date) -> List[dict]:
    flags: List[dict] = []
    _check_profile(cand, flags)
    _check_career(cand, reference_date, flags)
    _check_skills_education(cand, flags)
    _check_signals(cand, schema_errors, reference_date, flags)
    return flags


def flag_codes(flags: List[dict]) -> List[str]:
    return sorted({f["code"] for f in flags})


def severity_of(flags: List[dict]) -> Optional[str]:
    order = {"info": 0, "warning": 1, "error": 2}
    return max((f["severity"] for f in flags), key=order.__getitem__, default=None)

