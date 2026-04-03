#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crawler.schema_contract import flatten_record_for_schema, get_schema_contract  # noqa: E402


@dataclass(slots=True)
class MatrixRow:
    label: str
    dataset: str
    required_total: int
    required_filled: int
    properties_total: int
    properties_filled: int
    required_missing: list[str]
    missing_sample: list[str]


def _read_first_record(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"{path} is empty")
    payload = json.loads(lines[0])
    if not isinstance(payload, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return payload


def _build_row(label: str, path: Path) -> MatrixRow:
    record = _read_first_record(path)
    contract = get_schema_contract(record)
    flat = flatten_record_for_schema(record)
    required_missing = [name for name in contract.required_fields if flat.get(name) in (None, "", [], {})]
    missing = [name for name in contract.property_names if flat.get(name) in (None, "", [], {})]
    return MatrixRow(
        label=label,
        dataset=contract.dataset_name,
        required_total=len(contract.required_fields),
        required_filled=len(contract.required_fields) - len(required_missing),
        properties_total=len(contract.property_names),
        properties_filled=len(contract.property_names) - len(missing),
        required_missing=required_missing,
        missing_sample=missing[:30],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build schema coverage matrix from existing record outputs")
    parser.add_argument(
        "--record",
        action="append",
        nargs=2,
        metavar=("LABEL", "PATH"),
        help="Pair of label and records.jsonl path",
    )
    args = parser.parse_args()

    if not args.record:
        raise SystemExit("at least one --record LABEL PATH is required")

    rows = [_build_row(label, Path(path)) for label, path in args.record]
    print(json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
