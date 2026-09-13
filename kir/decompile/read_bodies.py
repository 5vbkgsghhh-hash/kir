"""READ BODIES: ONE CARRIER FOR EVERYONE WHO ASKS ABOUT THEM.

The bodies with which KIR READS Revit (as opposed to the bodies with which it
WRITES) are the `build_*_cs` functions of the `kir.decompile` package. Two
askers already query them: the gate (`gate_runner`, "does it compile on all
six versions") and the agreements registry (`kir.agreements`, "does the body
declare every helper it calls"). A third will ask too.

🔴 WHY THIS FILE EXISTS AT ALL. The argument table lived inside
`gate_runner`. The agreements registry needs it too, and the most natural
move would be to copy it. That is exactly the defect the registry itself
catches: two carriers of the same knowledge, silently drifting apart at the
very first new builder. The first thing the registry did was demand that the
table it came for be pulled out.

COVERAGE IS DERIVED, NOT ENUMERATED. Builders are found by walking the
package; a builder with no entry in `READ_BODY_ARGS` is a REFUSAL to the
asker, not an omission. A hand-written list would silently drift from the
package.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any, Callable

#: Arguments on which the body builds MEANINGFULLY. The values do not matter
#: in themselves — what matters is that the body comes out non-empty and
#: syntactically complete.
#: A body with no entry here drops the asker.
READ_BODY_ARGS: dict[str, dict[str, Any]] = {
    "build_reextract_cs": {"ids": ["101", "202"]},
    "build_room_reextract_cs": {"ids": ["101", "202"]},
    "build_category_batch_cs": {"category": "OST_Walls"},
    "build_category_probe_cs": {"category": "OST_Walls"},
    "build_metadata_cs": {},
    "build_annotation_extract_cs": {"element_ids": ["101"]},
    "build_curve_extract_cs": {"element_ids": ["101"]},
    "build_dimension_extract_cs": {"element_ids": ["101"]},
    "build_family_placement_extract_cs": {"element_ids": ["101"]},
    "build_curtain_extract_cs": {"wall_ids": ["101"]},
    "build_group_extract_cs": {},
    "build_geometry_extract_cs": {"element_ids": ["101"]},
    "build_join_extract_cs": {"element_ids": ["101"]},
    "build_mep_system_extract_cs": {"element_ids": ["101"]},
    "build_profile_extract_cs": {"element_ids": ["101"]},
    "build_sketch_extract_cs": {"element_ids": ["101"]},
    "build_tag_extract_cs": {"element_ids": ["101"]},
    # 🔴 FOUND 21.08 AND HAD NEVER COMPILED. The family recipe extraction —
    # a full-fledged read body (16 KB of C#, `EditFamily` + `GenericForm`) —
    # slipped past the gate only because it is called `family_recipe_cs`,
    # while the rule looked for `build_*_cs`. The rule was a SECOND CARRIER
    # of the notion "read body": the truth is "this function emits C# that
    # reads Revit", but the guard watched a NAMING CONVENTION. Exactly the
    # defect this gate section was set up to catch — inside the section
    # itself.
    "family_recipe_cs": {"limit": 5},
}

#: FUNCTIONS THAT EMIT A FRAGMENT, NOT A BODY. Compiling them on their own
#: is meaningless: `_xyz_mm_cs` returns `new XYZ(...)`, and Roslyn will say
#: exactly what it says about any expression outside a method.
#:
#: An entry here is NOT an omission but a statement "this is not a body,
#: and here is why". A function that lands in neither this nor
#: `READ_BODY_ARGS` drops the gate.
READ_BODY_FRAGMENTS: dict[str, str] = {
    "source_binding_cs":
        "привязка источника — общий кусок ВНУТРИ каждого тела; свой закон "
        "«одно тело — один документ» проверяется по тексту эмиссии",
    "tag_target_block_cs":
        "единственный кусок, РАЗНЫЙ на шести версиях; выделен, чтобы шов "
        "проверялся отдельно, и живёт внутри build_tag_extract_cs",
}


def discover_read_bodies() -> dict[str, Callable[..., str]]:
    """All read-body builders found by WALKING the package.

    Only a function DECLARED in its own module is taken: a re-export (`from
    … import build_x_cs`) gives the same name in a second module and would
    double the asker's work without adding a single check.
    """
    import kir.decompile as _dc

    out: dict[str, Callable[..., str]] = {}
    for mod in pkgutil.iter_modules(_dc.__path__):
        if mod.name in ("tests",):
            continue
        try:
            m = importlib.import_module(f"kir.decompile.{mod.name}")
        except Exception:      # noqa: BLE001 — a foreign module does not bring down the asker
            continue
        for n in dir(m):
            # 🔴 THE RULE IS "PUBLIC AND ENDS WITH _cs", NOT
            # "STARTS WITH build_". The previous rule looked for the prefix
            # and missed `family_recipe_cs`: 16 KB of read C#, never
            # compiled once. The prefix is a naming convention, while the
            # gate's question is about SUBSTANCE. Private ones
            # (`_route_cs`, `_xyz_mm_cs`) are excluded by the leading
            # underscore: they are fragments by construction.
            if not n.startswith("_") and n.endswith("_cs"):
                f = getattr(m, n)
                if callable(f) and getattr(f, "__module__", "") == m.__name__:
                    out.setdefault(n, f)
    return out


def uncovered_read_bodies() -> list[str]:
    """Found by the walk and NOT accounted for: neither a body nor a declared fragment."""
    return sorted(set(discover_read_bodies())
                  - set(READ_BODY_ARGS) - set(READ_BODY_FRAGMENTS))


def is_versioned(fn: Callable[..., str]) -> bool:
    """A body parameterized by the Revit version must build for every one of them.

    Building once and checking on all six would mean checking ONE branch
    six times. `build_tag_extract_cs` without a version takes the 2022+
    branch, and 2021 predictably fails to build: the family has no single
    member living across all six versions.
    """
    return "revit_version" in inspect.signature(fn).parameters


def build_all(*, revit_version: str | None = None) -> dict[str, str]:
    """Build every covered body. The key is the builder's name, the value is the C#.

    The version is mandatory for bodies that accept it; ignored for the
    rest. A builder that raises an exception does NOT make it into the
    result — the asker sees its absence and decides for itself whether
    that is a refusal.
    """
    out: dict[str, str] = {}
    for name, fn in sorted(discover_read_bodies().items()):
        args = READ_BODY_ARGS.get(name)
        if args is None:
            continue      # a fragment or uncovered — not our concern here
        try:
            if is_versioned(fn):
                if revit_version is None:
                    continue
                out[name] = fn(revit_version=revit_version, **args)
            else:
                out[name] = fn(**args)
        except Exception:      # noqa: BLE001
            continue
    return out
