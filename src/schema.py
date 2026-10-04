"""Candidate validation driven by the provided candidate_schema.json.

The official schema file is the single source of truth. We interpret the subset of
JSON-Schema (draft-07) keywords that file actually uses, which is much faster than a
general validator when run over 100K records. ``tests/test_schema.py`` checks that
this validator agrees with the reference ``jsonschema`` library on the sample data.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from . import config

ValidationError = Tuple[str, str]  # (json path, message)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\Z")


def _ecma_pattern(pattern: str) -> re.Pattern:
    """Compile a JSON-Schema (ECMA-262) pattern for Python.

    In Python ``$`` also matches just before a trailing newline, so
    "CAND_0000001\\n" would pass ``^CAND_[0-9]{7}$``. ECMA's ``$`` (no multiline flag)
    means end of input, i.e. Python's ``\\Z``.
    """
    if pattern.endswith("$") and not pattern.endswith("\\$"):
        pattern = pattern[:-1] + r"\Z"
    return re.compile(pattern)


_CANDIDATE_ID_RE = _ecma_pattern(config.CANDIDATE_ID_PATTERN)

SUPPORTED_KEYWORDS = {
    "$schema", "title", "description", "type", "required", "properties", "items",
    "additionalProperties", "enum", "minimum", "maximum", "pattern", "minItems",
    "maxItems", "format",
}


@lru_cache(maxsize=4)
def load_schema(path: str | Path = config.CANDIDATE_SCHEMA_PATH) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    unsupported = _collect_keywords(schema) - SUPPORTED_KEYWORDS
    if unsupported:
        # Fail loudly rather than silently skipping a constraint.
        raise ValueError(f"candidate schema uses unsupported keywords: {sorted(unsupported)}")
    return schema


def _collect_keywords(node: Any) -> set:
    keys: set = set()
    if isinstance(node, dict):
        for k, v in node.items():
            keys.add(k)
            if k == "properties":
                for sub in v.values():
                    keys |= _collect_keywords(sub)
            elif k in ("items", "additionalProperties") and isinstance(v, dict):
                keys |= _collect_keywords(v)
    return keys


def is_valid_candidate_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_CANDIDATE_ID_RE.match(value))


def _is_iso_date(value: str) -> bool:
    if not _DATE_RE.match(value):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


# JSON type -> predicate. ``type(v) is X`` is used because json.loads only produces
# exact built-in types, and it keeps bool out of integer/number.
_TYPE_CHECKS = {
    "string": lambda v: type(v) is str,
    "boolean": lambda v: type(v) is bool,
    "null": lambda v: v is None,
    "object": lambda v: type(v) is dict,
    "array": lambda v: type(v) is list,
    "integer": lambda v: type(v) is int or (type(v) is float and v.is_integer()),
    "number": lambda v: type(v) is int or type(v) is float,
}


def _format_path(parts: List[Any]) -> str:
    out = ""
    for part in parts:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def _compile(node: Dict[str, Any]) -> Callable[[Any, List[Any], List[ValidationError]], None]:
    """Turn one schema node into a checking closure (compiled once per schema).

    The JSON path is a mutable list of parts that is only formatted when an error
    is recorded, which keeps the common (valid) path cheap.
    """
    expected = node.get("type")
    type_names = expected if isinstance(expected, list) else ([expected] if expected else [])
    type_preds = [_TYPE_CHECKS[t] for t in type_names]
    single_pred = type_preds[0] if len(type_preds) == 1 else None
    enum = node.get("enum")
    minimum, maximum = node.get("minimum"), node.get("maximum")
    pattern = _ecma_pattern(node["pattern"]) if "pattern" in node else None
    is_date = node.get("format") == "date"
    required = node.get("required", [])
    props = {k: _compile(v) for k, v in node.get("properties", {}).items()}
    extra = _compile(node["additionalProperties"]) if isinstance(node.get("additionalProperties"), dict) else None
    min_items, max_items = node.get("minItems"), node.get("maxItems")
    items = _compile(node["items"]) if isinstance(node.get("items"), dict) else None
    has_bounds = minimum is not None or maximum is not None
    has_str_checks = pattern is not None or is_date

    def check(value: Any, path: List[Any], errors: List[ValidationError]) -> None:
        if (not single_pred(value)) if single_pred is not None else \
                (type_preds and not any(pred(value) for pred in type_preds)):
            errors.append((_format_path(path), f"expected type {expected}, got {type(value).__name__}"))
            return
        if enum is not None and value not in enum:
            errors.append((_format_path(path), f"value {value!r} not in enum {enum}"))
        vtype = type(value)
        if has_bounds and (vtype is int or vtype is float):
            if minimum is not None and value < minimum:
                errors.append((_format_path(path), f"{value} < minimum {minimum}"))
            if maximum is not None and value > maximum:
                errors.append((_format_path(path), f"{value} > maximum {maximum}"))
        elif has_str_checks and vtype is str:
            if pattern is not None and not pattern.search(value):
                errors.append((_format_path(path), f"{value!r} does not match {pattern.pattern}"))
            if is_date and not _is_iso_date(value):
                errors.append((_format_path(path), f"{value!r} is not an ISO date"))
        elif vtype is dict:
            for key in required:
                if key not in value:
                    errors.append((_format_path(path + [key]), "required field missing"))
            for key, sub_value in value.items():
                sub_check = props.get(key, extra)
                if sub_check is not None:
                    path.append(key)
                    sub_check(sub_value, path, errors)
                    path.pop()
        elif vtype is list:
            if min_items is not None and len(value) < min_items:
                errors.append((_format_path(path), f"has {len(value)} items, minItems {min_items}"))
            if max_items is not None and len(value) > max_items:
                errors.append((_format_path(path), f"has {len(value)} items, maxItems {max_items}"))
            if items is not None:
                for i, item in enumerate(value):
                    path.append(i)
                    items(item, path, errors)
                    path.pop()

    return check


_COMPILED: Dict[int, Callable] = {}


def validate_candidate(record: Any, schema: Dict[str, Any] | None = None) -> List[ValidationError]:
    """Return a list of (path, message) schema violations; empty means valid."""
    schema = schema or load_schema()
    check = _COMPILED.get(id(schema))
    if check is None:
        check = _COMPILED[id(schema)] = _compile(schema)
    errors: List[ValidationError] = []
    check(record, [], errors)
    return errors


# Map the top-level field of an error path to a report counter.
_SECTION_COUNTERS = {
    "candidate_id": "invalid_candidate_id",
    "profile": "invalid_profile",
    "career_history": "invalid_career_history",
    "education": "invalid_education",
    "skills": "invalid_skills",
    "certifications": "invalid_certifications",
    "languages": "invalid_languages",
    "redrob_signals": "invalid_behavioral_signals",
}


def error_categories(errors: List[ValidationError]) -> List[str]:
    """Collapse schema errors into sorted, de-duplicated report-counter names."""
    cats = set()
    for path, message in errors:
        if path == "":
            cats.add("not_an_object")
            continue
        top = re.split(r"[.\[]", path, maxsplit=1)[0]
        if path == top and message == "required field missing":
            if top == "candidate_id":
                cats.add("missing_candidate_id")
            elif top == "profile":
                cats.add("missing_profile")
            else:
                cats.add(_SECTION_COUNTERS.get(top, "invalid_other"))
        else:
            cats.add(_SECTION_COUNTERS.get(top, "invalid_other"))
    return sorted(cats)
