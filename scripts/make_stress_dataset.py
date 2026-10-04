"""Build a synthetic stress-test pool from the 50 real sample candidates.

NOT a substitute for the real candidates.jsonl.gz. It exists to test that the
streaming engine scales (time, memory, disk) and survives malformed lines. Records
are copies of the real samples with fresh candidate_ids; a small, fixed set of
corrupted lines is injected at deterministic positions.

    python scripts/make_stress_dataset.py --n 100000 --out /tmp/stress.jsonl.gz
"""
from __future__ import annotations

import argparse
import copy
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "raw" / "sample_candidates.json"


def corruptions(base: dict):
    """(label, line) pairs covering each failure mode the preprocessor handles."""
    def mutate(fn):
        c = copy.deepcopy(base)
        fn(c)
        return json.dumps(c)

    return [
        ("json_parse_error", '{"candidate_id": "CAND_9999901", "profile": '),
        ("not_an_object", json.dumps(["not", "a", "candidate"])),
        ("missing_candidate_id", mutate(lambda c: c.pop("candidate_id"))),
        ("invalid_candidate_id", mutate(lambda c: c.__setitem__("candidate_id", "CAND_12AB"))),
        ("duplicate_candidate_id", mutate(lambda c: c.__setitem__("candidate_id", "CAND_0000001"))),
        ("missing_profile", mutate(lambda c: (c.pop("profile"), c.__setitem__("candidate_id", "CAND_9999902")))),
        ("invalid_career_history", mutate(lambda c: (c.__setitem__("career_history", "oops"),
                                                     c.__setitem__("candidate_id", "CAND_9999903")))),
        ("malformed_date", mutate(lambda c: (c["career_history"][0].__setitem__("start_date", "March 2021"),
                                             c.__setitem__("candidate_id", "CAND_9999904")))),
        ("invalid_skills", mutate(lambda c: (c["skills"].append({"name": "X", "proficiency": "guru"}),
                                             c.__setitem__("candidate_id", "CAND_9999905")))),
        ("invalid_behavioral_signals", mutate(lambda c: (
            c["redrob_signals"].__setitem__("recruiter_response_rate", 1.7),
            c.__setitem__("candidate_id", "CAND_9999906")))),
        ("missing_behavioral_signals", mutate(lambda c: (c.pop("redrob_signals"),
                                                         c.__setitem__("candidate_id", "CAND_9999907")))),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100_000, help="number of well-formed records")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--no-corruptions", action="store_true")
    args = ap.parse_args()

    samples = json.loads(SAMPLE.read_text(encoding="utf-8"))
    bad = [] if args.no_corruptions else corruptions(samples[0])
    every = max(args.n // (len(bad) + 1), 1) if bad else 0
    opener = gzip.open if args.out.suffix == ".gz" else open
    with opener(args.out, "wt", encoding="utf-8") as fh:
        for i in range(args.n):
            rec = dict(samples[i % len(samples)])
            rec["candidate_id"] = f"CAND_{i + 1:07d}"
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if bad and (i + 1) % every == 0 and (i + 1) // every <= len(bad):
                fh.write(bad[(i + 1) // every - 1][1] + "\n")
    print(f"wrote {args.n:,} records + {len(bad)} corrupted lines -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
