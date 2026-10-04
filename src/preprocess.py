"""Phase 1 streaming preprocessor.

    python -m src.preprocess --candidates data/raw/candidates.jsonl.gz \
        --output-dir data/processed --limit 0

For each input line: parse -> validate (candidate_schema.json) -> normalise ->
quality-check -> build evidence -> write outputs -> next line. Only one candidate is
in memory at a time; the only state that grows with N is the set of seen
candidate_ids (~100 bytes each) used for duplicate detection.

Record handling policy (never crash the run because of one record):
* Unparseable JSON, non-object, missing/invalid candidate_id, or duplicate
  candidate_id -> written to invalid_records.jsonl with the raw line and reasons;
  not emitted (no traceable identity / would break ID uniqueness).
* Valid candidate_id but other schema violations -> processed best-effort, emitted
  with schema_valid=false and the violations recorded. Never silently dropped.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from collections import Counter
from pathlib import Path
from typing import Dict, Optional

from . import config
from .evidence import EVIDENCE_TYPES, build_all_evidence
from .normalize import normalize_candidate
from .quality import QUALITY_CODES, run_quality_checks
from .schema import error_categories, is_valid_candidate_id, load_schema, validate_candidate
from .summary import build_behavioral_row, build_candidate_summary
from .utils import dumps, iter_raw_records, peak_rss_mb, write_json

VALIDATION_COUNTERS = (
    "json_parse_error", "not_an_object", "missing_candidate_id", "invalid_candidate_id",
    "duplicate_candidate_id", "missing_profile", "invalid_profile", "invalid_career_history",
    "invalid_education", "invalid_skills", "invalid_certifications", "invalid_languages",
    "invalid_behavioral_signals", "invalid_other", "processing_error",
)


class _Outputs:
    """Line-oriented output files, opened once and written incrementally."""

    def __init__(self, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        self.paths = {
            "candidate_summary": output_dir / config.CANDIDATE_SUMMARY_FILE,
            "evidence_chunks": output_dir / config.EVIDENCE_FILE,
            "behavioral_signals": output_dir / config.BEHAVIORAL_SIGNALS_FILE,
            "invalid_records": output_dir / config.INVALID_RECORDS_FILE,
        }
        self.handles = {k: open(p, "w", encoding="utf-8") for k, p in self.paths.items()}
        self.lines = Counter()

    def write(self, name: str, obj) -> None:
        self.handles[name].write(dumps(obj) + "\n")
        self.lines[name] += 1

    def close(self) -> Dict[str, dict]:
        for h in self.handles.values():
            h.close()
        return {p.name: {"lines": self.lines[k], "bytes": p.stat().st_size} for k, p in self.paths.items()}


def run(candidates_path: Path, output_dir: Path, limit: int = 0,
        reference_date: dt.date = config.DEFAULT_REFERENCE_DATE,
        schema_path: Path = config.CANDIDATE_SCHEMA_PATH, progress_every: int = 0) -> dict:
    schema = load_schema(str(schema_path))
    out = _Outputs(output_dir)
    counters = Counter({k: 0 for k in VALIDATION_COUNTERS})
    evidence_by_type = Counter({t: 0 for t in EVIDENCE_TYPES})
    evidence_by_level = Counter()
    issue_candidates, issue_occurrences, issue_severity = Counter(), Counter(), {}
    seen_ids: set = set()
    total = valid = emitted = emitted_invalid = quarantined = flagged = 0

    t0 = time.perf_counter()
    for line_no, raw_line in iter_raw_records(candidates_path):
        if limit and total >= limit:
            break
        total += 1

        def quarantine(reasons, errors=None, candidate_id=None):
            nonlocal quarantined
            quarantined += 1
            out.write("invalid_records", {"source_line": line_no, "candidate_id": candidate_id,
                                          "reasons": reasons, "schema_errors": errors or [],
                                          "raw": raw_line.rstrip("\n")})

        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            counters["json_parse_error"] += 1
            quarantine(["json_parse_error"], [["", str(exc)]])
            continue

        errors = validate_candidate(record, schema)
        cats = error_categories(errors)
        counters.update(cats)
        if not errors:
            valid += 1

        cid = record.get("candidate_id") if isinstance(record, dict) else None
        if not isinstance(record, dict) or not is_valid_candidate_id(cid):
            quarantine(cats, [list(e) for e in errors], cid if isinstance(cid, str) else None)
            continue
        if cid in seen_ids:
            counters["duplicate_candidate_id"] += 1
            issue_candidates["duplicate_candidate_id"] += 1
            issue_occurrences["duplicate_candidate_id"] += 1
            issue_severity["duplicate_candidate_id"] = "error"
            quarantine(["duplicate_candidate_id"] + cats, [list(e) for e in errors], cid)
            continue
        seen_ids.add(cid)

        try:
            cand = normalize_candidate(record)
            flags = run_quality_checks(cand, errors, reference_date)
            evidence = build_all_evidence(cand, line_no, reference_date)
            summary = build_candidate_summary(cand, line_no, not errors, cats, flags, len(evidence), reference_date)
            behavior = build_behavioral_row(cand, reference_date)
        except Exception as exc:  # one bad record must not stop a 100K run
            counters["processing_error"] += 1
            quarantine(["processing_error"] + cats, [["", f"{type(exc).__name__}: {exc}"]], cid)
            continue

        for unit in evidence:
            out.write("evidence_chunks", unit)
            evidence_by_type[unit["evidence_type"]] += 1
            evidence_by_level[unit["assertion_level"]] += 1
        out.write("candidate_summary", summary)
        out.write("behavioral_signals", behavior)
        emitted += 1
        if errors:
            emitted_invalid += 1

        if flags:
            flagged += 1
        for code in {f["code"] for f in flags}:
            issue_candidates[code] += 1
        for f in flags:
            issue_occurrences[f["code"]] += 1
            issue_severity.setdefault(f["code"], f["severity"])

        if progress_every and total % progress_every == 0:
            print(f"  processed {total:,} records ({time.perf_counter() - t0:.1f}s)", flush=True)

    elapsed = time.perf_counter() - t0
    files = out.close()
    total_evidence = sum(evidence_by_type.values())

    report = {
        "phase": 1,
        "input_file": candidates_path.name,
        "limit": limit,
        "reference_date": reference_date.isoformat(),
        "total_candidates": total,
        "valid_candidates": valid,
        "invalid_candidates": total - valid,
        "emitted_candidates": emitted,
        "emitted_schema_invalid_candidates": emitted_invalid,
        "quarantined_records": quarantined,
        "validation_counters": dict(counters),
        "total_evidence": total_evidence,
        "evidence_by_type": dict(evidence_by_type),
        "evidence_by_assertion_level": dict(sorted(evidence_by_level.items())),
        "candidates_with_any_quality_flag": flagged,
        "data_quality_issues": {
            code: {"candidates": issue_candidates[code], "occurrences": issue_occurrences[code],
                   "severity": issue_severity.get(code), "description": QUALITY_CODES[code]}
            for code in QUALITY_CODES if issue_occurrences[code]
        },
        "output_files": files,
        "run_stats": {  # timing varies between runs; everything above is deterministic
            "seconds": round(elapsed, 3),
            "records_per_sec": round(total / elapsed, 1) if elapsed else None,
            "evidence_per_sec": round(total_evidence / elapsed, 1) if elapsed else None,
            "peak_rss_mb": round(peak_rss_mb(), 1),
        },
    }
    write_json(output_dir / config.PREPROCESSING_REPORT_FILE, report)
    return report


def _parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Phase 1: stream, validate, normalise and evidence-ify candidates.")
    ap.add_argument("--candidates", type=Path, default=config.SAMPLE_CANDIDATES_JSONL,
                    help="candidates .jsonl / .jsonl.gz (or a small .json array)")
    ap.add_argument("--output-dir", type=Path, default=config.PROCESSED_DIR)
    ap.add_argument("--limit", type=int, default=0, help="process only the first N records; 0 = all")
    ap.add_argument("--reference-date", type=dt.date.fromisoformat, default=config.DEFAULT_REFERENCE_DATE,
                    help="dataset as-of date for derived 'days since' fields (YYYY-MM-DD)")
    ap.add_argument("--schema", type=Path, default=config.CANDIDATE_SCHEMA_PATH)
    ap.add_argument("--progress-every", type=int, default=0, help="print progress every N records")
    return ap.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    args = _parse_args(argv)
    report = run(args.candidates, args.output_dir, args.limit, args.reference_date, args.schema,
                 args.progress_every)
    stats = report["run_stats"]
    print(f"records={report['total_candidates']:,} valid={report['valid_candidates']:,} "
          f"emitted={report['emitted_candidates']:,} quarantined={report['quarantined_records']:,} "
          f"evidence={report['total_evidence']:,}")
    print(f"time={stats['seconds']}s  {stats['records_per_sec']:,} rec/s  "
          f"{stats['evidence_per_sec']:,} evidence/s  peak_rss={stats['peak_rss_mb']} MB")
    print(f"report -> {args.output_dir / config.PREPROCESSING_REPORT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
