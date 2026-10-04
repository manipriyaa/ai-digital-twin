"""Pool-level company statistics, accumulated during the streaming pass.

The schema has no company founding date, but submission_spec.md gives a honeypot
example: "8 years of experience at a company founded 3 years ago". The only way to
detect that from this data is to compare a role's start against when everyone else
in the pool started at that company. This module collects the raw material for that:
per company, how many roles start in each year, plus observed industries and sizes.

Nothing is judged here. Memory grows with the number of distinct companies, not
the number of candidates. Output is deterministic (sorted keys).
"""
from __future__ import annotations

from collections import Counter
from typing import Dict

from .evidence import is_jd_named_consulting_firm
from .normalize import match_key


class CompanyStats:
    def __init__(self) -> None:
        self._companies: Dict[str, dict] = {}

    def add(self, cand: dict) -> None:
        for role in cand["career"]:
            key = match_key(role["company"])
            if key is None:
                continue
            entry = self._companies.get(key)
            if entry is None:
                entry = self._companies[key] = {
                    "names": Counter(), "role_count": 0, "current_role_count": 0,
                    "start_years": Counter(), "earliest_start_date": None,
                    "industries": Counter(), "company_sizes": Counter(),
                }
            entry["names"][role["company"]] += 1
            entry["role_count"] += 1
            if role["is_current"]:
                entry["current_role_count"] += 1
            if role["start_date"]:
                entry["start_years"][role["start_date"][:4]] += 1
                if entry["earliest_start_date"] is None or role["start_date"] < entry["earliest_start_date"]:
                    entry["earliest_start_date"] = role["start_date"]
            if role["industry"]:
                entry["industries"][role["industry"]] += 1
            if role["company_size"]:
                entry["company_sizes"][role["company_size"]] += 1

    def __len__(self) -> int:
        return len(self._companies)

    def to_json(self) -> dict:
        companies = {}
        for key in sorted(self._companies):
            e = self._companies[key]
            companies[key] = {
                "display_name": sorted(e["names"].items(), key=lambda kv: (-kv[1], kv[0]))[0][0],
                "role_count": e["role_count"],
                "current_role_count": e["current_role_count"],
                "earliest_start_date": e["earliest_start_date"],
                "start_year_histogram": dict(sorted(e["start_years"].items())),
                "industries": dict(sorted(e["industries"].items())),
                "company_sizes": dict(sorted(e["company_sizes"].items())),
                "is_jd_named_consulting_firm": is_jd_named_consulting_firm(key),
            }
        return {
            "note": "Observed in the candidate pool only; not ground truth about the companies. "
                    "earliest_start_date can itself come from an impossible (honeypot) profile, so "
                    "later phases should use the histogram, not the minimum alone.",
            "company_count": len(companies),
            "companies": companies,
        }
