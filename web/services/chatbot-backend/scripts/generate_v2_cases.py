"""Emit the static v2 benchmark suite as version-controlled JSONL.

One file per category under ``docs/benchmark/cases/v2/``. The committed JSONL is
the source of truth for any published result; rerun this only when templates
change, then review the diff.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.benchmarks.case_generator import build_cases_by_category  # noqa: E402
from app.benchmarks.cases_v2 import CATEGORIES, write_cases_jsonl  # noqa: E402

DEFAULT_OUT = ROOT.parents[2] / "docs" / "benchmark" / "cases" / "v2"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the v2 benchmark JSONL suite.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    grouped = build_cases_by_category()
    total = 0
    for index, category in enumerate(CATEGORIES, start=1):
        cases = grouped[category]
        path = out_dir / f"{index:02d}_{category}.jsonl"
        written = write_cases_jsonl(path, cases)
        total += written
        print(f"{category:22s} {written:3d} -> {path.name}")
    print(f"\nTotal: {total} cases across {len(CATEGORIES)} categories -> {out_dir}")


if __name__ == "__main__":
    main()
