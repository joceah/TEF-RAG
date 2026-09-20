"""Validate the released public generation gold, indexes, and schema."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = ROOT / "data/generation"


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def validate(base: Path) -> list[str]:
    errors: list[str] = []
    schema = json.loads((base / "schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    for split in ("development", "validation", "test"):
        gold = rows(base / f"gold_{split}.jsonl")
        index = rows(base / f"gold_{split}_index.jsonl")
        if len(gold) != len(index):
            errors.append(f"{split}: gold/index count mismatch")
        for pos, obj in enumerate(gold):
            if list(validator.iter_errors(obj)):
                errors.append(f"{split}: schema error at row {pos}")
        for pos, obj in enumerate(index):
            if obj.get("split") != split or not isinstance(obj.get("query_ids"), list) or len(obj["query_ids"]) != 2:
                errors.append(f"{split}: malformed index row {pos}")
    expected = {
        "gold_test.jsonl": "dccf5a831b9b145d5aab26288088d14d2e9af6fafd06d4eced3a22983a7c9aea",
        "gold_test_index.jsonl": "8433880d300e541713aba7eae86564bcb705f6f9c638043a66d7262f5b195d35",
    }
    for name, digest in expected.items():
        if hashlib.sha256((base / name).read_bytes()).hexdigest() != digest:
            errors.append(f"{name}: SHA-256 mismatch")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    errors = validate(args.root)
    if errors:
        raise SystemExit("public generation validation failed:\n- " + "\n- ".join(errors))
    print("public generation validation passed: development/validation/test gold and indexes")


if __name__ == "__main__":
    main()
