"""Single-writer native Rat CLI with the information-boundary query."""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
from pathlib import Path

from ssr.crosscut.interface import Rat
from ssr.native.adapter import default_engine_python


def main():
    p = argparse.ArgumentParser(prog='python -m ssr.crosscut',description=__doc__)
    p.add_argument("--run", required=True, type=Path)
    p.add_argument("--engine-python", default=default_engine_python(),
                   help="directory containing the kickmix_engine package (default: $SSR_ENGINE_PYTHON)")
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--source", required=True)
    init.add_argument("--contract", help="JSON task-contract file (default: the full invsqrt contract)")
    sub.add_parser("observe")
    for command, field in (("query", "request"), ("step", "action"), ("rollback", None)):
        child = sub.add_parser(command)
        child.add_argument("--expected", required=True)
        if field:
            child.add_argument("--" + field, required=True)
    a = p.parse_args()
    if a.engine_python is None:
        p.error("--engine-python or SSR_ENGINE_PYTHON is required")
    a.run.mkdir(parents=True, exist_ok=True)
    with (a.run / "loop-writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            contract = json.loads(Path(a.contract).read_text()) if getattr(a, "contract", None) else None
            rat = Rat(a.run, a.engine_python, getattr(a, "source", None), contract)
            if a.command == "query":
                result = rat.query(json.loads(a.request), a.expected)
            elif a.command == "step":
                result = rat.step(json.loads(a.action), a.expected)
            elif a.command == "rollback":
                result = rat.back(a.expected)
            else:
                result = rat.observe()
            print(json.dumps(result, indent=2))
        except (ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"status": "error", "error": str(exc)}))
            raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
