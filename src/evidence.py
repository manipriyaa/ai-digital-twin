"""Structured evidence units built from a normalised candidate.

One evidence unit = one meaningful, provenance-tagged fact source (a role, a skill,
a degree, a group of behavioural signals) rather than an arbitrary text window.

Every unit has the same envelope::

    evidence_id      deterministic: "<candidate_id>:<type>:<source_field>"
    candidate_id
    evidence_type    profile | career | skill | education | certification | behavior
    evidence_subtype e.g. profile.summary, behavior.responsiveness
    assertion_level  how strong the *kind* of evidence is (see ASSERTION_LEVELS)
    source_field     JSON path in the raw record, e.g. "career_history[2]"
    source_index     index in the source array, or null
    source_line      1-based line number in the input JSONL
    text             human-readable text used later for retrieval / grounding
    metadata         structured fields (dates, proficiency, raw signal values...)

The ``assertion_level`` is what keeps declared skills apart from demonstrated work.
No relevance judgement or scoring happens here.
"""
from __future__ import annotations

import datetime as dt
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional

from . import config
from .normalize import match_key, months_between, parse_date

# Ordered from weakest to strongest *kind* of claim. This is not a score; it tells
# later phases what sort of evidence a text came from.
ASSERTION_LEVELS = {
    "declared": "Listed by the candidate without context (skills list, headline, title).",
    "self_described": "Candidate's own narrative about themselves (profile summary).",
    "demonstrated": "Described work within a dated role (career_history description).",
    "credential": "Education or certification record.",
    "behavioral": "Platform-observed or self-reported Redrob signal.",
}

EVIDENCE_TYPES = ("profile", "career", "skill", "education", "certification", "behavior")

_CONSULTING_KEYS = {match_key(name) for name in config.JD_NAMED_CONSULTING_FIRMS}


def _unit(candidate_id: str, evidence_type: str, subtype: str, assertion_level: str,
          source_field: str, source_index: Optional[int], source_line: int,
          text: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "evidence_id": f"{candidate_id}:{evidence_type}:{source_field}",
        "candidate_id": candidate_id,
        "evidence_type": evidence_type,
        "evidence_subtype": subtype,
        "assertion_level": assertion_level,
        "source_field": source_field,
        "source_index": source_index,
        "source_line": source_line,
        "text": text,
        "metadata": metadata,
    }


def is_jd_named_consulting_firm(company: Optional[str]) -> bool:
    return match_key(company) in _CONSULTING_KEYS if company else False


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def build_profile_evidence(cand: dict, source_line: int) -> List[dict]:
    cid, p = cand["candidate_id"], cand["profile"]
    units = []
    if p["headline"]:
        units.append(_unit(cid, "profile", "profile.headline", "declared",
                           "profile.headline", None, source_line, p["headline"], {}))
    if p["summary"]:
        units.append(_unit(cid, "profile", "profile.summary", "self_described",
                           "profile.summary", None, source_line, p["summary"],
                           {"word_count": len(p["summary"].split())}))
    if p["current_title"] or p["current_company"]:
        parts = [f"Current title: {p['current_title'] or 'unknown'}"]
        if p["current_company"]:
            parts.append(f"at {p['current_company']}")
        ctx = ", ".join(x for x in (p["current_industry"],
                                    f"{p['current_company_size']} employees" if p["current_company_size"] else None) if x)
        text = " ".join(parts) + (f" ({ctx})" if ctx else "") + "."
        if p["location"] or p["country"]:
            text += f" Location: {', '.join(x for x in (p['location'], p['country']) if x)}."
        if p["years_of_experience"] is not None:
            text += f" Stated years of experience: {p['years_of_experience']:g}."
        units.append(_unit(cid, "profile", "profile.current_position", "declared",
                           "profile", None, source_line, text, {
                               "current_title": p["current_title"],
                               "current_company": p["current_company"],
                               "current_company_size": p["current_company_size"],
                               "current_industry": p["current_industry"],
                               "location": p["location"],
                               "country": p["country"],
                               "years_of_experience": p["years_of_experience"],
                               "is_jd_named_consulting_firm": is_jd_named_consulting_firm(p["current_company"]),
                           }))
    return units


# ---------------------------------------------------------------------------
# Career
# ---------------------------------------------------------------------------

def _chronological_order(career: List[dict]) -> Dict[int, int]:
    """Map original index -> chronological position (0 = earliest start).

    Roles with unknown start dates are placed last, by original index, so the
    ordering is deterministic.
    """
    keyed = sorted(career, key=lambda r: (r["start_date"] is None, r["start_date"] or "", r["index"]))
    return {r["index"]: pos for pos, r in enumerate(keyed)}


def build_career_evidence(cand: dict, source_line: int, reference_date: dt.date) -> List[dict]:
    cid = cand["candidate_id"]
    order = _chronological_order(cand["career"])
    first_seen_description: Dict[str, str] = {}
    units = []
    for role in cand["career"]:
        idx = role["index"]
        source_field = f"career_history[{idx}]"
        start, end = parse_date(role["start_date"]), parse_date(role["end_date"])
        is_current = role["is_current"]

        months_from_dates = None
        if start and end:
            months_from_dates = months_between(start, end)
        elif start and is_current and role["raw_end_date"] is None:
            months_from_dates = months_between(start, reference_date)

        if is_current and role["raw_end_date"] is None:
            months_since_end = 0
        elif end:
            months_since_end = months_between(end, reference_date)
        else:
            months_since_end = None  # unknown; never guessed

        desc = role["description"]
        duplicate_of = None
        if desc:
            duplicate_of = first_seen_description.get(desc)
            first_seen_description.setdefault(desc, f"{cid}:career:{source_field}")

        period = f"{role['start_date'] or 'unknown start'} to " + (
            "present" if is_current and role["raw_end_date"] is None else (role["end_date"] or "unknown end"))
        ctx = ", ".join(x for x in (role["industry"],
                                    f"{role['company_size']} employees" if role["company_size"] else None) if x)
        header = (f"{role['title'] or 'Unknown title'} at {role['company'] or 'unknown company'}"
                  + (f" ({ctx})" if ctx else "") + f", {period}"
                  + (f", {role['duration_months']} months" if role["duration_months"] is not None else "") + ".")
        text = f"{header} {desc}" if desc else header

        units.append(_unit(cid, "career", "career.role", "demonstrated" if desc else "declared",
                           source_field, idx, source_line, text, {
                               "company": role["company"],
                               "title": role["title"],
                               "industry": role["industry"],
                               "company_size": role["company_size"],
                               "start_date": role["start_date"],
                               "end_date": role["end_date"],
                               "duration_months": role["duration_months"],
                               "duration_months_from_dates": months_from_dates,
                               "is_current": is_current,
                               "months_since_end": months_since_end,
                               "chronological_position": order[idx],
                               "is_jd_named_consulting_firm": is_jd_named_consulting_firm(role["company"]),
                               "description_start": len(header) + 1 if desc else None,
                               "description_word_count": len(desc.split()) if desc else 0,
                               "description_duplicate_of": duplicate_of,
                           }))
    return units


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

@lru_cache(maxsize=8192)
def _mention_pattern(key: str) -> re.Pattern:
    # ``key`` and the searched text are both match_key()-normalised, so separators
    # are already single spaces; we only need alphanumeric word boundaries.
    return re.compile(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])")


def _text_sources(cand: dict) -> List[tuple]:
    """(source_field, match_key-normalised text) for narrative fields a skill may appear in."""
    out = []
    for role in cand["career"]:
        if role["description"]:
            out.append((f"career_history[{role['index']}].description", match_key(role["description"])))
    if cand["profile"]["summary"]:
        out.append(("profile.summary", match_key(cand["profile"]["summary"])))
    return out


def build_skill_evidence(cand: dict, source_line: int) -> List[dict]:
    cid = cand["candidate_id"]
    signals = cand["signals"] or {}
    assessments = signals.get("skill_assessment_scores")
    assessments = assessments if isinstance(assessments, dict) else {}
    assessment_by_key = {match_key(k): (k, v) for k, v in assessments.items()}
    texts = _text_sources(cand)

    units = []
    for skill in cand["skills"]:
        if not skill["name"]:
            continue
        idx = skill["index"]
        parts = [p for p in (
            f"{skill['proficiency']} proficiency" if skill["proficiency"] else None,
            f"{skill['duration_months']} months" if skill["duration_months"] is not None else None,
            f"{skill['endorsements']} endorsements" if skill["endorsements"] is not None else None,
        ) if p]
        text = f"Declared skill: {skill['name']}" + (f" ({', '.join(parts)})" if parts else "") + "."

        # Lexical corroboration only: where the same skill string appears in the
        # candidate's own narrative. This is a pointer for later phases, not proof.
        mentions = []
        if skill["key"] and len(skill["key"]) >= 2:
            key = skill["key"]
            mentions = [field for field, body in texts
                        if key in body and _mention_pattern(key).search(body)]  # cheap prefilter first

        assessed = assessment_by_key.get(skill["key"])
        units.append(_unit(cid, "skill", "skill.declared", "declared",
                           f"skills[{idx}]", idx, source_line, text, {
                               "name": skill["name"],
                               "skill_key": skill["key"],
                               "proficiency": skill["proficiency"],
                               "endorsements": skill["endorsements"],
                               "duration_months": skill["duration_months"],
                               "lexical_mentions": mentions,
                               "platform_assessment_score": assessed[1] if assessed else None,
                               "platform_assessment_source": (
                                   f"redrob_signals.skill_assessment_scores[{assessed[0]!r}]" if assessed else None),
                           }))
    return units


# ---------------------------------------------------------------------------
# Education and certifications
# ---------------------------------------------------------------------------

def build_education_evidence(cand: dict, source_line: int) -> List[dict]:
    cid = cand["candidate_id"]
    units = []
    for edu in cand["education"]:
        idx = edu["index"]
        what = " in ".join(x for x in (edu["degree"], edu["field_of_study"]) if x) or "Education"
        text = what + (f", {edu['institution']}" if edu["institution"] else "")
        years = "–".join(str(y) for y in (edu["start_year"], edu["end_year"]) if y is not None)
        if years:
            text += f" ({years})"
        if edu["grade"]:
            text += f", grade {edu['grade']}"
        text += "."
        units.append(_unit(cid, "education", "education.degree", "credential",
                           f"education[{idx}]", idx, source_line, text, {
                               k: edu[k] for k in ("institution", "degree", "field_of_study",
                                                   "start_year", "end_year", "grade", "tier")
                           }))
    return units


def build_certification_evidence(cand: dict, source_line: int) -> List[dict]:
    cid = cand["candidate_id"]
    units = []
    for cert in cand["certifications"]:
        if not cert["name"]:
            continue
        idx = cert["index"]
        extra = ", ".join(str(x) for x in (cert["issuer"], cert["year"]) if x is not None)
        text = f"Certification: {cert['name']}" + (f" ({extra})" if extra else "") + "."
        units.append(_unit(cid, "certification", "certification.record", "credential",
                           f"certifications[{idx}]", idx, source_line, text,
                           {k: cert[k] for k in ("name", "issuer", "year")}))
    return units


# ---------------------------------------------------------------------------
# Behavioural signals (kept separate from technical evidence)
# ---------------------------------------------------------------------------

# Group -> ordered signal names. Every one of the 23 schema signals appears once.
BEHAVIOR_GROUPS = {
    "activity": ["signup_date", "last_active_date", "open_to_work_flag",
                 "applications_submitted_30d", "profile_completeness_score"],
    "responsiveness": ["recruiter_response_rate", "avg_response_time_hours",
                       "interview_completion_rate", "offer_acceptance_rate"],
    "market_demand": ["profile_views_received_30d", "search_appearance_30d",
                      "saved_by_recruiters_30d", "connection_count", "endorsements_received"],
    "logistics": ["notice_period_days", "expected_salary_range_inr_lpa",
                  "preferred_work_mode", "willing_to_relocate"],
    "verification": ["verified_email", "verified_phone", "linkedin_connected"],
    "technical_activity": ["github_activity_score", "skill_assessment_scores"],
}

# Signals the candidate states themselves vs. ones the platform observes.
SELF_REPORTED_SIGNALS = {"open_to_work_flag", "notice_period_days", "expected_salary_range_inr_lpa",
                         "preferred_work_mode", "willing_to_relocate"}

# Documented sentinel values (schema / redrob_signals_doc).
SENTINELS = {"github_activity_score": (-1, "no GitHub linked"),
             "offer_acceptance_rate": (-1, "no prior offer history")}


def _fmt(name: str, value: Any) -> str:
    if name in SENTINELS and value == SENTINELS[name][0]:
        return f"{name}=-1 ({SENTINELS[name][1]})"
    if name == "expected_salary_range_inr_lpa" and isinstance(value, dict):
        return f"{name}={value.get('min')}-{value.get('max')} LPA"
    if name == "skill_assessment_scores" and isinstance(value, dict):
        if not value:
            return f"{name}=none taken"
        return f"{name}=" + "; ".join(f"{k}: {v}" for k, v in sorted(value.items()))
    return f"{name}={value}"


def _days_before(reference_date: dt.date, iso: Any) -> Optional[int]:
    d = parse_date(iso)
    return (reference_date - d).days if d else None


def build_behavior_evidence(cand: dict, source_line: int, reference_date: dt.date) -> List[dict]:
    cid, signals = cand["candidate_id"], cand["signals"]
    if signals is None:
        return []
    units = []
    for group, names in BEHAVIOR_GROUPS.items():
        present = [n for n in names if n in signals]
        if not present:
            continue
        # Raw values keyed by signal name; each value's provenance is
        # "redrob_signals.<name>" (see signal_source_prefix).
        sig_values = {n: signals[n] for n in present}
        self_reported = [n for n in present if n in SELF_REPORTED_SIGNALS]
        sentinel_hits = [n for n in present if n in SENTINELS and signals[n] == SENTINELS[n][0]]
        derived = {}
        if group == "activity":
            derived = {"days_since_last_active": _days_before(reference_date, signals.get("last_active_date")),
                       "days_since_signup": _days_before(reference_date, signals.get("signup_date"))}
        text = f"Redrob {group.replace('_', ' ')} signals: " + "; ".join(_fmt(n, signals[n]) for n in present) + "."
        units.append(_unit(cid, "behavior", f"behavior.{group}", "behavioral",
                           f"redrob_signals#{group}", None, source_line, text,
                           {"signals": sig_values, "signal_source_prefix": "redrob_signals.",
                            "self_reported": self_reported, "sentinel_values": sentinel_hits,
                            "derived": derived}))
    return units


def build_all_evidence(cand: dict, source_line: int, reference_date: dt.date) -> List[dict]:
    return (build_profile_evidence(cand, source_line)
            + build_career_evidence(cand, source_line, reference_date)
            + build_skill_evidence(cand, source_line)
            + build_education_evidence(cand, source_line)
            + build_certification_evidence(cand, source_line)
            + build_behavior_evidence(cand, source_line, reference_date))
