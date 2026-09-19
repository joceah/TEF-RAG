from __future__ import annotations
import argparse
import json
from pathlib import Path

from tef_rag_v6.generation_eval_cli import DEFAULT_PRIVATE, METHODS, evaluate, freeze, preflight, run_generation


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preflight", "generate", "freeze", "evaluate"))
    parser.add_argument("--all", action="store_true", help="generate all five methods in one formal session")
    parser.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE)
    args = parser.parse_args(argv)
    if args.action == "preflight":
        result = preflight()
    elif args.action == "generate":
        if not args.all:
            raise SystemExit("formal generate requires --all")
        result = run_generation(METHODS)
    elif args.action == "freeze":
        result = freeze()
    else:
        result = evaluate(args.private_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
