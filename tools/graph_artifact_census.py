#!/usr/bin/env python3
"""A census of graph artifacts by schema version. READ-ONLY.

Answers exactly one question: how many corpus decompiles sit at which
version of `building_graph.json`, and how many of them carry an
observation fingerprint.

🔴 WHY THIS INSTRUMENT IS NEEDED AT ALL. The `building-graph/1` -> `/2`
migration touches files that do NOT exist in this tree: the corpus is
machine-local and lives at the host's. "Old artifacts are still
readable" is a claim about SOMEONE ELSE's disk, and without a number it
remains a promise. The instrument turns it into a measurement, changing
nothing:

    WRITES 0 FILES. Not one. The corpus is only ever read.

🔴 THE ROOT IS A VARIABLE, NOT A LITERAL, and its absence is a NAMED
SKIP. An instrument without its own subject must be distinguishable
from an instrument without findings: a silent zero here would read as
"the corpus has no old artifacts", that is, our own blindness would
pass for a fact about the corpus. The same technique as in
`test_graph_artifact._CORPUS` and `test_asked_vs_built_is_judged`.

Run:

    KUKAI_DECOMPILE_DATA=<root> python3 tools/graph_artifact_census.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

#: The same root and the same variable as the package's corpus guards.
#: A second way to name the corpus would drift from the first on
#: exactly the day it gets moved.
CORPUS_ENV = "KUKAI_DECOMPILE_DATA"
ARTIFACT_NAME = "building_graph.json"
EXIT_OK, EXIT_BROKEN, EXIT_NO_CORPUS = 0, 1, 2


def corpus_root() -> Path | None:
    named = os.getenv(CORPUS_ENV)
    if named:
        root = Path(named)
        return root if root.is_dir() else None
    return None


def _schema_of(path: Path) -> tuple[str, bool | None]:
    """(version, whether there is a fingerprint), or named corruption.
    The file is not touched."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ("unreadable", None)
    if not isinstance(payload, dict):
        return ("not_an_object", None)
    schema = payload.get("schema")
    if not isinstance(schema, str):
        return ("schema_absent", None)
    return (schema, payload.get("observation") is not None)


def census(root: Path) -> dict:
    by_schema: dict[str, int] = {}
    with_fingerprint = 0
    runs = 0
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        artifact = entry / ARTIFACT_NAME
        if not artifact.is_file():
            continue
        runs += 1
        schema, fingerprint = _schema_of(artifact)
        by_schema[schema] = by_schema.get(schema, 0) + 1
        if fingerprint:
            with_fingerprint += 1
    return {
        "schema": "kir-graph-artifact-census/1",
        "corpus_root": str(root),
        "artifacts_read": runs,
        "by_schema": by_schema,
        "with_observation_fingerprint": with_fingerprint,
        # 🔴 THE LINE THE INSTRUMENT WAS WRITTEN THIS WAY, AND NOT
        # ANOTHER, FOR.
        "artifacts_written": 0,
        "corpus_is_read_only": True,
    }


def main(argv=None) -> int:
    root = corpus_root()
    if root is None:
        named = os.getenv(CORPUS_ENV)
        print(json.dumps({
            "schema": "kir-graph-artifact-census/1",
            "skipped": "corpus_unavailable",
            "reason": (f"{CORPUS_ENV}={named!r} — не каталог" if named else
                       f"{CORPUS_ENV} не задан"),
            "note": "это НЕ «старых артефактов нет», а отсутствие предмета",
        }, ensure_ascii=False, indent=1))
        return EXIT_NO_CORPUS
    try:
        print(json.dumps(census(root), ensure_ascii=False, indent=1))
    except OSError as error:
        print(json.dumps({"schema": "kir-graph-artifact-census/1",
                          "broken": str(error)}, ensure_ascii=False))
        return EXIT_BROKEN
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
