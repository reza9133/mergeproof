#!/usr/bin/env python3
"""Inline ``mergeproof_pure.py`` and ``mergeproof.py`` into
``contracts/bounty_escrow.py`` so the result is one self-contained file.

GenLayer's default deploy path (CLI, Studio's "Add From File", and most
deploy scripts) takes a single Python file per contract, so a project
split across modules for readability needs to be flattened before it is
deployed. This script does that flattening deterministically.

Usage:
    python scripts/bundle.py

Writes:
    dist/bounty_escrow.bundle.py
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "contracts" / "bounty_escrow.py"
OUTPUT = ROOT / "dist" / "bounty_escrow.bundle.py"

# Each entry: (import line to replace, source file, lines to drop from
# that source because the surrounding contract file already provides
# them once the pieces are spliced together).
PARTS = [
    (
        "from mergeproof_pure import combined_score",
        ROOT / "mergeproof_pure.py",
        set(),
    ),
    (
        "from mergeproof import GitHubOracle, ERROR_EXPECTED, ERROR_EXTERNAL, ERROR_TRANSIENT",
        ROOT / "mergeproof.py",
        {
            "from genlayer import *",
            "import json",
            "from mergeproof_pure import derive_ci_status, safe_confidence",
        },
    ),
]


def _inline(source_path: pathlib.Path, drop: set, label: str) -> str:
    lines = [ln for ln in source_path.read_text().splitlines() if ln.strip() not in drop]
    body = "\n".join(lines).strip()
    return f"# ---- inlined from {source_path.name} ----\n{body}\n# ---- end {label} ----"


def main() -> None:
    contract_src = CONTRACT.read_text()

    for import_line, source_path, drop in PARTS:
        if import_line not in contract_src:
            raise SystemExit(f"expected to find this line in {CONTRACT}:\n  {import_line}")
        contract_src = contract_src.replace(import_line, _inline(source_path, drop, source_path.stem))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(contract_src)
    line_count = contract_src.count("\n") + 1
    print(f"wrote {OUTPUT} ({len(contract_src)} bytes, {line_count} lines)")


if __name__ == "__main__":
    main()
