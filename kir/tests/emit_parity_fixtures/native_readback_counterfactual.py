"""Reproduce the reviewed pre-native-readback emission for historical migration tests.

Only the finite retained emitter functions/constants are replaced. Current
emission is checked separately against its complete new byte manifest. Historical
migration assertions remain executable; no wildcard exemption disables a check.
"""
from contextlib import contextmanager
import hashlib
import importlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).parent
LEGACY_MANIFEST = HERE / "corpus_hashes_pre_native_readback.json"
LEGACY_GOLDENS = HERE / "golden_hashes_pre_native_readback.json"
SOURCE_PATH = HERE / "native_readback_legacy_sources.json"


@contextmanager
def before_native_readback_fixes():
    record = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    assert record["schema"] == "kir-native-readback-legacy-sources/1"
    specs = record["sources"]
    for row in specs:
        assert hashlib.sha256(row["source"].encode()).hexdigest() == row["sha256"]
        importlib.import_module(row["module"])
    modules = [m for name, m in tuple(sys.modules.items())
               if name.startswith("kir.") and m is not None]
    attrs = [(m, key, value) for m in modules for key, value in tuple(vars(m).items())]
    dictionaries = []
    seen = set()
    for _, key, value in attrs:
        if isinstance(value, dict) and id(value) not in seen and key != "__builtins__":
            seen.add(id(value)); dictionaries.append((value, tuple(value.items())))
    replacements = {}
    changes = []
    dictionary_changes = []
    try:
        for row in specs:
            module = importlib.import_module(row["module"])
            old = getattr(module, row["name"])
            exec(compile(row["source"], "<retained-emitter:" + row["module"] + "." + row["name"] + ">", "exec"), vars(module))
            new = getattr(module, row["name"])
            replacements[id(old)] = new
            changes.append((module, row["name"], old))
        for module, key, old in attrs:
            if id(old) in replacements:
                changes.append((module, key, old))
                setattr(module, key, replacements[id(old)])
        for mapping, items in dictionaries:
            for key, old in items:
                if id(old) in replacements:
                    dictionary_changes.append((mapping, key, old))
                    mapping[key] = replacements[id(old)]
        yield
    finally:
        for mapping, key, old in reversed(dictionary_changes):
            mapping[key] = old
        for module, key, old in reversed(changes):
            setattr(module, key, old)
