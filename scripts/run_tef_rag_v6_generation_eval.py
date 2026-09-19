from __future__ import annotations
import argparse
import json
from pathlib import Path

from tef_rag_v6.generation_eval_cli import DEFAULT_PRIVATE, METHODS, evaluate, freeze, preflight, run_generation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preflight", "generate", "freeze", "evaluate"))
    parser.add_argument("--method", choices=METHODS)
    parser.add_argument("--all", action="store_true", help="generate all methods query-major; recommended formal mode")
    parser.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE)
    args = parser.parse_args()
    if args.action == "preflight":
        result = preflight()
    elif args.action == "generate":
        chosen = METHODS if args.all else ((args.method,) if args.method else None)
        if chosen is None:
            raise SystemExit("generate requires --all or --method")
        result = run_generation(chosen)
    elif args.action == "freeze":
        result = freeze()
    else:
        result = evaluate(args.private_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
