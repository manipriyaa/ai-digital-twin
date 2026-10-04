"""Deterministic, conservative normalisation helpers.

Rules:
* Never invent values: unknown/invalid input becomes ``None``.
* Preserve meaning and case: "ML Engineer", "Machine Learning Engineer" and
  "Senior ML Engineer" stay distinct. We only clean whitespace and Unicode form.
* ``*_key`` helpers produce lowercase matching keys; callers keep the display value
  alongside, so the original wording is never lost.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from typing import Any, Optional

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\Z")


def _collapse_ws(text: str) -> str:
    """Collapse every run of whitespace (incl. Unicode spaces) to one space and strip.

    ``str.split()`` with no argument splits on exactly the characters for which
    ``str.isspace()`` is true, the same set ``re`` uses for ``\\s`` in str patterns,
    and is much faster than a regex substitution.
    """
    return " ".join(text.split())


def normalize_text(value: Any) -> Optional[str]:
    """NFC-normalise, collapse whitespace runs to one space, strip. Empty -> None."""
    if value is None or not isinstance(value, str):
        return None
    text = value if value.isascii() else unicodedata.normalize("NFC", value)
    return _collapse_ws(text) or None


def normalize_title(value: Any) -> Optional[str]:
    """Display form of a job title. Case and wording are preserved."""
    return normalize_text(value)


def normalize_company(value: Any) -> Optional[str]:
    """Display form of a company name. Legal suffixes are kept (no guessing)."""
    return normalize_text(value)


def normalize_skill(value: Any) -> Optional[str]:
    """Display form of a skill name, e.g. "Hugging Face Transformers"."""
    return normalize_text(value)


def match_key(value: Any) -> Optional[str]:
    """Lowercase key for exact-ish matching: casefold, unify '-', '_', '/' to spaces.

    "Sentence-Transformers" and "sentence transformers" share a key; "ML Engineer"
    and "Machine Learning Engineer" do not (no synonym expansion here).
    """
    text = normalize_text(value)
    if text is None:
        return None
    text = text.casefold().replace("-", " ").replace("_", " ").replace("/", " ")
    return _collapse_ws(text) or None


def normalize_date(value: Any) -> Optional[str]:
    """Return an ISO ``YYYY-MM-DD`` string, or ``None`` if missing/malformed.

    We deliberately do not guess partial or free-form dates.
    """
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not _DATE_RE.match(value):
        return None
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return None
    return value


def parse_date(value: Any) -> Optional[dt.date]:
    iso = normalize_date(value)
    return dt.date.fromisoformat(iso) if iso else None


def months_between(start: dt.date, end: dt.date) -> int:
    """Months from start to end using the dataset's own convention: ``days // 30``.

    Verified on sample_candidates.json: this reproduces duration_months exactly for
    all 97 completed roles, and for all 50 current roles with a reference date in
    2026-05-27..2026-06-14. Can be negative if end < start.
    """
    return (end - start).days // 30


def to_number(value: Any) -> Optional[float]:
    """Return a float for int/float inputs (not bool); otherwise None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def to_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def to_bool(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


# ---------------------------------------------------------------------------
# Record-level normalisation
# ---------------------------------------------------------------------------

def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def normalize_candidate(raw: dict) -> dict:
    """Return a normalised view of one raw candidate.

    Defensive by design: a malformed sub-field becomes ``None`` (or the item is
    skipped) instead of raising, so one bad record cannot stop a 100K run. Every
    list item keeps ``index`` = its position in the *original* array, which is what
    provenance paths such as ``career_history[2]`` refer to.
    """
    profile = _dict(raw.get("profile"))
    signals = raw.get("redrob_signals")

    career = []
    for i, item in enumerate(_list(raw.get("career_history"))):
        if not isinstance(item, dict):
            continue
        career.append({
            "index": i,
            "company": normalize_company(item.get("company")),
            "title": normalize_title(item.get("title")),
            "start_date": normalize_date(item.get("start_date")),
            "end_date": normalize_date(item.get("end_date")),
            "raw_start_date": item.get("start_date"),
            "raw_end_date": item.get("end_date"),
            "duration_months": to_int(item.get("duration_months")),
            "is_current": to_bool(item.get("is_current")),
            "industry": normalize_text(item.get("industry")),
            "company_size": normalize_text(item.get("company_size")),
            "description": normalize_text(item.get("description")),
        })

    education = []
    for i, item in enumerate(_list(raw.get("education"))):
        if not isinstance(item, dict):
            continue
        education.append({
            "index": i,
            "institution": normalize_text(item.get("institution")),
            "degree": normalize_text(item.get("degree")),
            "field_of_study": normalize_text(item.get("field_of_study")),
            "start_year": to_int(item.get("start_year")),
            "end_year": to_int(item.get("end_year")),
            "grade": normalize_text(item.get("grade")),
            "tier": normalize_text(item.get("tier")),
        })

    skills = []
    for i, item in enumerate(_list(raw.get("skills"))):
        if not isinstance(item, dict):
            continue
        skills.append({
            "index": i,
            "name": normalize_skill(item.get("name")),
            "key": match_key(item.get("name")),
            "proficiency": normalize_text(item.get("proficiency")),
            "endorsements": to_int(item.get("endorsements")),
            "duration_months": to_int(item.get("duration_months")),
        })

    certifications = []
    for i, item in enumerate(_list(raw.get("certifications"))):
        if not isinstance(item, dict):
            continue
        certifications.append({
            "index": i,
            "name": normalize_text(item.get("name")),
            "issuer": normalize_text(item.get("issuer")),
            "year": to_int(item.get("year")),
        })

    languages = []
    for i, item in enumerate(_list(raw.get("languages"))):
        if not isinstance(item, dict):
            continue
        languages.append({
            "index": i,
            "language": normalize_text(item.get("language")),
            "proficiency": normalize_text(item.get("proficiency")),
        })

    return {
        "candidate_id": raw.get("candidate_id"),
        "profile": {
            "anonymized_name": normalize_text(profile.get("anonymized_name")),
            "headline": normalize_text(profile.get("headline")),
            "summary": normalize_text(profile.get("summary")),
            "location": normalize_text(profile.get("location")),
            "country": normalize_text(profile.get("country")),
            "years_of_experience": to_number(profile.get("years_of_experience")),
            "current_title": normalize_title(profile.get("current_title")),
            "current_company": normalize_company(profile.get("current_company")),
            "current_company_size": normalize_text(profile.get("current_company_size")),
            "current_industry": normalize_text(profile.get("current_industry")),
        },
        "career": career,
        "education": education,
        "skills": skills,
        "certifications": certifications,
        "languages": languages,
        "signals": signals if isinstance(signals, dict) else None,
    }
