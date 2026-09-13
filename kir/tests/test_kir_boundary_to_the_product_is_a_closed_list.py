"""KIR STANDS ALONE — and every one of its exits to the outside is named by
name.

WHY. The owner's word, 25.08.2026: "kukai and kir are different projects…
we're open-sourcing KIR after all, so we need to stay a bit separate."
Repeated more sharply on 27.08: "you merged the KIR project with Kukai and
that's a hell of a mistake. **Kukai is just one of the environments where
KIR runs**."

THIS IS A CEILING, NOT A BAN. KIR IS CALLED from the KUKAI window — the
connection is intended. What's bad is not the existence of exits but their
UNNOTICED GROWTH: "too much of the general stuff" is a quantity, and it
must be kept visible.

═══════════════════════════════════════════════════════════════════════════
THE HISTORY OF THE NUMBER, BECAUSE THE NUMBER IS THE SUBJECT
═══════════════════════════════════════════════════════════════════════════
  25.08  59 crossings   scope = `kukai/ir`, KIR inside the product package
  27.08  39 -> 34 -> 21 -> 0   moves, scope expansion, ports
  27.08  THE SPLIT: KIR shipped out as a separate package (`/opt/kir`), the
         product installs it via `pip install -e` and imports it as `kir`

🔴 AND THIS GUARD DID NOT SURVIVE THE SPLIT. It moved out along with the
package — carrying the constants of the OLD layout inside it — and turned
red ENTIRELY, 14 of 14. There was no one to notice: it is not in the
product's ledger, nor in the gate manifest. **A guard that nobody calls is
not a guard**; this exact shape was caught in others all day this shift, and
it bought itself last. The file was rewritten clean, not patched: the
subject got simpler, and the old scaffolding was a memory of the past, not
knowledge of the present.

THE SUBJECT IS NOW SINGLE: **does the `kir` package pull in anything at all
besides itself, the standard library, and its DECLARED dependencies.** The
boundary became the package's physical name, and the list of roots is no
longer needed.

🔴 07.09.2026: THE TEST DEBT IS NAMED, AND IT NOW HAS A NUMBER. Before this
day the registry knew of one hard exit, while a traversal found 52: the
tree had grown tests, each of which took a scene from `examples/` (the repo
root, which does not ship in the wheel) or a body from `OCP` (the
`requirements-geometry-occt.txt` profile), and not one of them was
recorded. The guard turned red on four assertions at once — that is, it
said "everything is bad," which is the same silence, only louder: it could
not distinguish a new exit from an old one. Now every exit stands in
`ВЫХОДЫ` with a cause, and EVERY NEW ONE turns red separately.

HOW THIS DEBT IS PAID DOWN, NOT REWRITTEN AWAY. A scene from `examples/`
moves into `kir/tests/fixtures/` (if only the suite needs it) or into
`kir/examples/` (if it is part of the language); this is exactly how nine
tools moved from `tools/` to `kir/instruments/` on 27.08. A body from `OCP`
is taken through the `kir.occt_geometry._kernel` door inside the test plus
a `skip` with a named cause — then, for someone without the profile, the
suite does not turn red, it stays silent out loud. Hard ones are paid off
first: they break COLLECTION, not just a call. The `ЖЁСТКИХ_ЗАМЕРЕНО` bar
only moves DOWN, and on any decrease the guard itself names how far down to
set it.

TWO KINDS, AND THE DIFFERENCE BETWEEN THEM IS DECISIVE:

    hard    an import executed AT LOAD TIME — top level or a class body. A
            separately installed KIR fails IMMEDIATELY.
    soft    an import inside a function. It fails ON CALL — that is, for
            the user, not at build time. Invisible to static analysis:
            exactly why the tree looked untangled for years without being
            so.

WHAT THIS FILE DOES NOT DO. It does not forbid exits and it rips nothing
out. It turns UNNOTICED DRIFT into NAMED DEBT. The decision on each one
belongs to the owner.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ПАКЕТ = Path(__file__).resolve().parents[1]          # .../kir
РЕПО = ПАКЕТ.parent                                  # .../opt/kir

#: Declared dependencies are the ones listed in `pyproject.toml`. A name not
#: there is an exit, even if the package happens to be installed alongside.
ОБЪЯВЛЕНЫ: frozenset[str] = frozenset({
    "shapely", "networkx", "pydantic", "httpx",      # dependencies
    "fastapi",                                       # extra `bridge`
    "pytest", "jsonschema",                          # extra `dev`
})

СТДЛИБ = frozenset(sys.stdlib_module_names)

#: Exit -> how many times. The key is a TRIPLE (file relative to the
#: package, name, kind).
#:
#: 🔴 THE KIND IS PART OF THE KEY, AND THAT WAS PAID FOR BY A RUN OF THE
#: PREVIOUS DRAFT. The pair `(file, name)` silently swallowed entries where
#: one file pulls one name BOTH ways: the registry declared 12 hard exits
#: where the traversal found 14.
ВЫХОДЫ: dict[tuple[str, str, str], int] = {
    # 🟢 THE CORE IS CLEAN. Everything below is TESTS, and that is a debt
    # of A DIFFERENT KIND: it never reaches the user at runtime, but it
    # gets in the way of running the suite where the product isn't present.
    #
    # 27.08.2026, AFTER MOVING THE INSTRUMENTS: it was 17 keys / 20 hits /
    # 7 hard — it became 5 / 5 / 1. Eight instruments (`capability_graph`,
    # `scope_audit`, `relift_offline`, `content_coverage`, `measure_header`,
    # `snapshot_janitor`, `compile_gate_offline`, `bounds_audit`) moved to
    # `kir/instruments/`: they were KIR's by COMPOSITION and the product's
    # only by storage location.
    #
    # The one remaining HARD exit — warming up the product's `load_dotenv`
    # in conftest. It is already wrapped in try/except with a NAMED
    # consequence: a standalone KIR says out loud that no environment
    # snapshot was taken, instead of pretending to be clean.
    ("tests/conftest.py", "kukai", "жёсткий"): 1,

    # ── THE MCP DOOR: FOUR EXTRA-EXITS, AND THE ARGUMENT IS MEASURED
    # (03.09.2026) ──
    #
    # `kir/mcp/` is neither the language nor the hand, but a DOOR
    # (`kir/mcp/BOUNDARY.md`), and it ships as a separate extra:
    # `pip install "kir-building[mcp]"`. An exit here is legitimate under
    # exactly two conditions, both VERIFIED, not merely claimed:
    #
    #   1. THE IMPORT IS LAZY. An AST traversal over `kir/mcp/`: foreign
    #      imports at MODULE level — ZERO, all eight sit in function
    #      bodies. So `import kir` without the extra pulls in nothing from
    #      them. Pinned by the test
    #      `test_дверь_тянет_чужое_только_лениво` below.
    #   2. ALL THREE NAMES ARRIVE WITH THE DECLARED EXTRA. Measured from
    #      the wheel metadata of `mcp==2.1.1` (`pip download --no-deps`):
    #          Requires-Dist: mcp-types==2.1.1
    #          Requires-Dist: anyio>=4.9
    #          Requires-Dist: uvicorn>=0.31.1; sys_platform != 'emscripten'
    #      That is, `pyproject` declares `mcp>=2.1,<3.0`, and `mcp_types`,
    #      `anyio`, and `uvicorn` arrive as ITS closure. For someone who
    #      installed the extra, the door works.
    #
    # 🔴 WHAT THIS ENTRY DOES NOT PERMIT: an exit from the CORE. The
    # conditions above hold for `kir/mcp/` and nothing else; the same
    # import in `kir/compiler.py` remains red, and rightly so.
    # ── THE CORE'S DOOR INTO THE OCCT GEOMETRY KERNEL: ONE EXIT
    # (07.09.2026) ──
    #
    # `OCP` (`cadquery-ocp-novtk`) is not in `dependencies` or in
    # `optional-dependencies`: it is installed via a SEPARATE profile,
    # `requirements-geometry-occt.txt`. So someone else may not have it —
    # and the core's promise, "installs and works WITHOUT extras," rests
    # not on a word but on TWO verifiable properties, both pinned by
    # `test_дверь_в_occt_одна_и_её_отсутствие_названо` below:
    #
    #   1. THE IMPORT IS LAZY — it sits in the body of
    #      `occt_geometry._kernel`. `import kir` without the profile pulls
    #      nothing; the absence arrives as the NAME
    #      `GeometryRefusal("kernel_unavailable")`, not as an
    #      `ImportError` from someone else's place.
    #   2. THERE IS ONE DOOR FOR THE WHOLE TREE. Measured 07.09.2026
    #      BEFORE the fix: CORE exits to `OCP` numbered FOUR —
    #      `clash/exact.py` (14 hits), `refine/deviation.py` (5),
    #      `clash/project_analysis.py` (2), `occt_geometry.py` (3) — and
    #      THREE of them bypassed the VERSION PIN that the door checks
    #      exactly once (`cadquery-ocp-novtk` == 7.9.3.1.1 and
    #      `OCP.__version__`). On a foreign OCCT build, an exact phase
    #      would compute silently and by different rules. The first three
    #      were untangled: they fetch names from `_kernel()` rather than
    #      opening their own door.
    #
    # 🔴 WHAT THIS ENTRY DOES NOT PERMIT: A SECOND exit of this kind. The
    # condition rests on ONE file, not on the name `OCP`: the same import
    # in `kir/compiler.py` or back in `clash/exact.py` remains red, and
    # rightly so.
    ("occt_geometry.py", "OCP", "мягкий"): 3,

    ("mcp/server.py", "anyio", "мягкий"): 1,
    ("mcp/server.py", "mcp", "мягкий"): 4,
    ("mcp/server.py", "mcp_types", "мягкий"): 1,
    ("mcp/server.py", "uvicorn", "мягкий"): 1,
    ("mcp/tests/test_the_app_is_wired.py", "mcp", "мягкий"): 1,
    ("mcp/tests/test_the_live_door_writes_only_where_it_may.py",
     "mcp_types", "мягкий"): 1,

    # A seventh key, BUT NOT A FIFTH NAME: `mcp` has been on the list
    # since 02.09, the number of foreign packages stayed at FOUR. There is
    # no way to untangle this exit in principle — the test's subject IS
    # the protocol: fifty of the door's instruments call
    # `server.dispatch` directly and know nothing about the wiring, and
    # `isError=False` for a refusal is born exactly at the translation
    # into a protocol result. Without a real SDK there would be nothing to
    # check.
    # Without the extra, the test is SKIPPED with a named cause (verified),
    # meaning the suite does not turn red for someone without `[mcp]`.
    ("mcp/tests/test_the_wire_carries_the_door.py", "mcp", "мягкий"): 1,

    # Soft ones: called inside tests, they don't break collection.
    # `bridge_reference_closure` pulls in `kukai.api.bridge_protocol` — it
    # is the product's BY COMPOSITION and stays there; the other three are
    # trivial, named so they don't dissolve unnoticed.
    ("tests/test_clash_in_the_receipt.py", "capability_map", "мягкий"): 1,
    ("tests/test_clash_in_the_receipt.py", "tools", "мягкий"): 1,
    ("tests/test_datums_multistory_net48.py", "bridge_reference_closure", "мягкий"): 1,

    # 🔴 REMOVED 28.08.2026: `tests/test_record_ratchet.py -> tests`. The
    # test loaded the HOST's dark journal by the short name `tests`; it
    # now finds it via `KIR_HOST_ROOT` and is SKIPPED with a cause when
    # the host's tree isn't there. The exit was not renamed, it was
    # REMOVED — and the registry must shrink in the same commit, otherwise
    # it is guarding something that no longer exists.
    #
    # 🔴 AND THE THREE EXITS IN `tools/` ARE ALSO GONE HERE, FOR THE SAME
    # REASON. On 27.08, `tools/kir_canon_state.py` and
    # `tools/unwired_census.py` arrived in the tree, and three tests
    # imported them by short name: `tools/` is NOT part of the installable
    # package, so these were real exits, and the hard count became three
    # instead of one. Both instruments moved to `kir/instruments/` — the
    # same place their nine neighbors went during the split — and thin
    # doors were left behind in `tools/` so the commands from the
    # briefing still work letter for letter. Untangling, not a registry
    # entry.

    # ═══ NAMED TEST DEBT, DECLARED 07.09.2026 (the lead's decision) ═══
    #
    # 🔴 BEFORE THIS DAY THE DEBT WAS INVISIBLE, AND THAT WAS ITS MAIN
    # FEATURE. The registry knew of ONE hard exit (`tests/conftest.py ->
    # kukai`), while a traversal found 52: the tree had grown tests, each
    # taking a scene from `examples/` or a body from `OCP`, and NOT ONE
    # was named. The guard turned red on four assertions at once, that
    # is, it said "everything is bad" — which is the same silence, only
    # louder. The debt is written down by name so it becomes a NUMBER
    # that must decrease, and so EVERY NEW exit turns red separately.
    #
    # ─── `examples` (105 hits across 49 keys) ───
    # CAUSE: the test takes a ready-made scene from `examples/`. The
    # directory sits at the REPO ROOT and does NOT ship in the wheel
    # (`[tool.setuptools.packages.find] include = ["kir*"]`), and neither
    # do the tests. So someone who installed the package has neither, and
    # none of this reaches them at runtime.
    # PAID DOWN BY: moving the scene into `kir/tests/fixtures/` (if only
    # the suite needs it) or into `kir/examples/` (if it is part of the
    # language), exactly as nine instruments moved from `tools/` to
    # `kir/instruments/` on 27.08.
    ("bureau/tests/test_a_bureau_of_models_holds_its_limits.py", "examples", "мягкий"): 2,
    ("bureau/tests/test_a_live_agent_answers_through_files.py", "examples", "мягкий"): 2,
    ("clash/tests/test_a_hull_overlap_is_not_a_body_overlap.py", "examples", "мягкий"): 1,
    ("clash/tests/test_a_repair_that_moves_the_world_not_the_parameter.py", "examples", "мягкий"): 10,
    ("clash/tests/test_project_bodies_reach_the_search.py", "examples", "мягкий"): 5,
    ("tests/test_a_fix_survives_a_restart.py", "examples", "мягкий"): 8,
    ("tests/test_a_recipe_resumes_where_it_stopped.py", "examples", "мягкий"): 1,
    ("tests/test_a_revision_check_is_paid_once.py", "examples", "мягкий"): 2,
    # 08.09.2026, wave 8 (scale-2): the scene and the analysis take one
    # snapshot — the test builds a real project using the `podium_passage`
    # example (a lazy import inside the fixture).
    ("viewer/tests/test_a_scene_and_its_analysis_take_one_snapshot.py", "examples", "мягкий"): 1,
    ("tests/test_a_section_keeps_its_source.py", "examples", "жёсткий"): 3,
    ("tests/test_a_stable_address_is_not_permission.py", "examples", "мягкий"): 1,
    ("tests/test_connector_compiler_conformance.py", "examples", "мягкий"): 2,
    ("tests/test_create_publication_identity.py", "examples", "мягкий"): 1,
    ("tests/test_create_type_discrepancy.py", "examples", "мягкий"): 3,
    ("tests/test_created_element_identity.py", "examples", "мягкий"): 2,
    ("tests/test_geometry_materialization.py", "examples", "мягкий"): 1,
    ("tests/test_level_update_residential_memory.py", "examples", "жёсткий"): 3,
    ("tests/test_occt_geometry.py", "examples", "мягкий"): 5,
    ("tests/test_occt_geometry_adversarial.py", "examples", "мягкий"): 3,
    ("tests/test_project_cli_lifecycle.py", "examples", "мягкий"): 1,
    ("tests/test_project_diff.py", "examples", "мягкий"): 1,
    ("tests/test_project_handoff.py", "examples", "мягкий"): 3,
    ("tests/test_project_refinement.py", "examples", "жёсткий"): 2,
    ("tests/test_project_refinement.py", "examples", "мягкий"): 1,
    ("tests/test_project_selection_adversarial.py", "examples", "жёсткий"): 1,
    ("tests/test_project_submission.py", "examples", "мягкий"): 2,
    ("tests/test_repair_merge_validation.py", "examples", "жёсткий"): 1,
    ("tests/test_residential_agent_acceptance.py", "examples", "жёсткий"): 2,
    ("tests/test_residential_agent_acceptance.py", "examples", "мягкий"): 1,
    ("tests/test_residential_agent_workflow.py", "examples", "жёсткий"): 2,
    ("tests/test_residential_level_iteration.py", "examples", "жёсткий"): 3,
    ("tests/test_residential_recipes.py", "examples", "жёсткий"): 3,
    ("tests/test_residential_typed_section.py", "examples", "жёсткий"): 3,
    ("tests/test_residential_with_podium.py", "examples", "жёсткий"): 1,
    ("tests/test_revit_connector_preparation.py", "examples", "мягкий"): 1,
    ("tests/test_section_identity_capture.py", "examples", "мягкий"): 1,
    ("tests/test_section_plan_acceptance.py", "examples", "жёсткий"): 1,
    ("tests/test_typed_section_conformance.py", "examples", "мягкий"): 3,
    ("viewer/tests/test_blend_preview.py", "examples", "жёсткий"): 1,
    ("viewer/tests/test_reference_surfaces.py", "examples", "жёсткий"): 1,
    ("viewer/tests/test_standalone_export.py", "examples", "жёсткий"): 1,
    ("viewer/tests/test_standalone_export.py", "examples", "мягкий"): 1,
    ("viewer/tests/test_standalone_input.py", "examples", "жёсткий"): 1,
    ("viewer/tests/test_standalone_input.py", "examples", "мягкий"): 1,
    ("viewer/tests/test_the_analysis_reaches_the_display.py", "examples", "мягкий"): 1,
    ("viewer/tests/test_the_untranslated_remainder_reaches_the_screen.py", "examples", "мягкий"): 4,

    # ─── `OCP` (51 hits across 12 keys) ───
    # CAUSE: the test builds or reads a REAL OCCT body — without the
    # kernel there would be nothing to check. `OCP` is installed via a
    # separate profile, `requirements-geometry-occt.txt`, and is not
    # listed in `dependencies`.
    # PAID DOWN BY: importing inside the test through the
    # `kir.occt_geometry._kernel` door (which already returns
    # `GeometryRefusal("kernel_unavailable")`) plus a `skip` with a NAMED
    # cause — then, for someone without the profile, the suite does not
    # turn red, it stays silent out loud. Hard (module-level) ones are
    # paid off first: they break COLLECTION, not just a call.
    ("clash/tests/test_a_hull_overlap_is_not_a_body_overlap.py", "OCP", "жёсткий"): 3,
    ("clash/tests/test_a_hull_overlap_is_not_a_body_overlap.py", "OCP", "мягкий"): 4,
    ("clash/tests/test_a_repair_that_breaks_a_run_is_refused_by_name.py", "OCP", "мягкий"): 2,
    ("clash/tests/test_a_silent_zero_is_not_a_clear_verdict.py", "OCP", "жёсткий"): 5,
    ("clash/tests/test_a_silent_zero_is_not_a_clear_verdict.py", "OCP", "мягкий"): 3,
    ("clash/tests/test_clearance_measurement_unavailable.py", "OCP", "мягкий"): 2,
    ("refine/tests/test_a_translated_shape_must_name_what_it_dropped.py", "OCP", "жёсткий"): 8,
    ("tests/test_geometry_materialization.py", "OCP", "мягкий"): 1,
    ("tests/test_geometry_materialization_adversarial.py", "OCP", "мягкий"): 2,
    ("tests/test_occt_geometry.py", "OCP", "мягкий"): 12,
    ("tests/test_occt_geometry_adversarial.py", "OCP", "мягкий"): 6,
    ("tests/test_residential_with_podium.py", "OCP", "мягкий"): 3,

    # ─── `tools` (0 hits) ───
    # CAUSE: the test calls a thin door in `tools/`, left there on 27.08
    # so that briefing commands still work letter for letter. The
    # directory itself is not part of the package.
    # PAID DOWN BY: calling the instrument from `kir/instruments/`, where
    # it moved to.
    # ─── 07.09.2026: THREE FILES UNTANGLED FROM COLLECTION, THE DEBT
    # STAYED SOFT ───
    # There used to be 6 HARD hits (e2e 2, source_change 3, gap 1): they
    # executed AT COLLECTION TIME and dropped the whole suite wherever
    # `examples/` was absent. They became lazy
    # (`importlib.import_module` inside the function body), and along
    # with them went the `skipif` discount that computed
    # `capture_walk.CORPUS` at module level — with that count in place, a
    # lazy import would have been lazy only in appearance. The CAUSE of
    # the debt is unchanged: a scene from `examples/`; the directory sits
    # at the repo root and does not ship in the wheel. PAID DOWN by
    # moving the scene into `kir/tests/fixtures/` or `kir/examples/`.
    ("tests/test_the_final_result_holds_end_to_end.py", "examples", "мягкий"): 4,

    ("clash/tests/test_a_second_analysis_is_paid_once_and_says_the_same.py", "examples", "мягкий"): 1,
    ("tests/test_a_source_change_names_all_three_sets.py", "examples", "мягкий"): 3,
}

#: 🔴 THE CORE'S THIRD CATEGORY — NAMED INDIVIDUALLY, NOT BY PACKAGE NAME
#: (07.09.2026). A CORE exit is legitimate exactly when the package
#: arrives as a DECLARED extra or profile, the import is LAZY, and the
#: absence is named as a REFUSAL. The key here is the whole triple, so
#: that same `OCP` from the second file stays flagged as dirt: the
#: exemption rests on the FILE, not on the word "geometry." Every entry
#: must carry a VERIFIABLE argument (the test below computes it, rather
#: than reading it) and must stand in the `ВЫХОДЫ` registry — otherwise a
#: door gets set up silently.
ДВЕРИ_ПРОФИЛЕЙ: frozenset[tuple[str, str, str]] = frozenset({
    ("occt_geometry.py", "OCP", "мягкий"),
})

#: 🔴 THE HARD-EXITS RATCHET. ONE DIRECTION ONLY — DOWN. Measured
#: 07.09.2026: 46.
#:
#: The number grew from 1 not through an edit but through THE TREE'S
#: GROWTH: 1 was measured on 27.08, when the only hard exit was warming
#: up `load_dotenv` in conftest. Dozens of tests then arrived with scenes
#: from `examples/` and bodies from `OCP`, and the bar never noticed,
#: because the guard turned red AS A WHOLE and read as "everything is
#: bad." The debt is named individually above; what stands here is its
#: TOTAL.
#:
#: 🔴 THIS NUMBER MUST NOT BE RAISED. A rise is caught by
#: `test_жёстких_не_больше_замеренного`, and it is cured by an entry in
#: `ВЫХОДЫ` with a cause, or by untangling — never by a new bar: a bar
#: that tracks the tree guards its own freshness, not the debt. A
#: decrease is caught by `test_храповик_затянут`, which NAMES how far
#: down to set it.
ЖЁСТКИХ_ЗАМЕРЕНО = 46

_КЛЮЧ = tuple[str, str, str]


def _выход(имя: str) -> bool:
    """Whether this name leads outside the package."""
    верх = имя.split(".")[0]
    return верх not in СТДЛИБ and верх not in ОБЪЯВЛЕНЫ and верх != "kir"


def _выходы_файла(путь: Path) -> list[_КЛЮЧ]:
    """All of the file's exits to the outside, with their kind.

    The kind follows nesting: an import is soft ONLY inside a function
    body. A class body executes at load time, so it counts as hard (fix
    27.08; there are zero such cases in the tree today, but an instrument
    waiting for its chance to lie is already broken).

    A relative import is RESOLVED, not skipped: `from ..llm import x`
    leads outside just the same, even though the word doesn't look like
    it points outward.
    """
    дерево = ast.parse(путь.read_text(encoding="utf-8", errors="surrogateescape"),
                       filename=str(путь))
    вложенные: set[int] = set()
    for узел in ast.walk(дерево):
        if isinstance(узел, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for под in ast.walk(узел):
                if isinstance(под, (ast.Import, ast.ImportFrom)):
                    вложенные.add(id(под))

    имя_файла = путь.relative_to(ПАКЕТ).as_posix()
    это_пакет = путь.name == "__init__.py"
    # The full dotted name of the module ITSELF: `kir/decompile/lift.py`
    # -> kir.decompile.lift
    части = ["kir"] + list(путь.relative_to(ПАКЕТ).with_suffix("").parts)
    if это_пакет:
        части.pop()                       # `kir/x/__init__.py` -> kir.x
    # The "current package" for a relative import: for a package, it is
    # itself; for a module, it is its directory. Level 1 means EXACTLY the
    # current package.
    свой = части if это_пакет else части[:-1]
    найдено: list[_КЛЮЧ] = []
    for узел in ast.walk(дерево):
        имена: list[str] = []
        if isinstance(узел, ast.Import):
            имена = [a.name for a in узел.names]
        elif isinstance(узел, ast.ImportFrom):
            if узел.level:
                # 🔴 IN `__init__.py`, LEVEL 1 IS THE PACKAGE ITSELF, not
                # its parent. The previous draft subtracted the same way
                # in both cases and declared `from .protocol import ...`
                # an exit to a nonexistent name — and a HARD one at that.
                # A false positive is more expensive than a miss: it
                # starts people fixing something that isn't broken.
                вычесть = узел.level - 1
                основа = свой[: len(свой) - вычесть] if len(свой) >= вычесть else []
                if узел.module:
                    основа = основа + узел.module.split(".")
                имена = [".".join(основа)] if основа else []
            elif узел.module:
                имена = [узел.module]
        род = "мягкий" if id(узел) in вложенные else "жёсткий"
        for имя in имена:
            if имя and _выход(имя):
                найдено.append((имя_файла, имя.split(".")[0], род))
    return найдено


#: The floor for the number of files the traversal MUST cover. Measured
#: 02.09.2026: the package gives **960** files. The floor is set with
#: margin (losing a whole subpackage is hundreds, not tens), because an
#: exact number would turn the guard red on every new file; the floor's
#: subject is not the tree's growth but LOSING THE SUBJECT.
ФАЙЛОВ_НЕ_МЕНЬШЕ = 700


def _обход() -> dict[_КЛЮЧ, int]:
    """🔴 THE DENOMINATOR LIVES INSIDE THE TRAVERSAL, NOT AT EACH TEST
    (02.09.2026).

    A traversal that lost its subject answers "no exits" — and three of
    the four assertions below pass VACUOUSLY: "no new ones," "the core is
    clean," "no more hard exits than measured." Only
    `test_реестр_не_несёт_призраков` goes red, and even that only while
    `ВЫХОДЫ` is NOT EMPTY — and this file's whole goal is for it to
    become empty. That is, on the day of success the guard would go
    vacuously green, and there would be nothing to notice it by.

    The cost of silence is greatest here in the whole tree: this guard is
    exactly the boundary the constitution calls a matter standing on a
    number. So the traversal itself refuses to return a result it cannot
    answer for.

    This shape was paid for twice on 02.09: the satellite traversal
    found 0 sites instead of six and TURNED RED precisely because it had
    a declared denominator; the emitter guard saw 35 names out of 72 and
    stayed green, because it checked only non-emptiness.
    """
    счёт: dict[_КЛЮЧ, int] = {}
    assert ПАКЕТ.is_dir(), f"пакета нет: {ПАКЕТ}"
    файлов = 0
    for путь in sorted(ПАКЕТ.rglob("*.py")):
        if "__pycache__" in путь.parts:
            continue
        файлов += 1
        for ключ in _выходы_файла(путь):
            счёт[ключ] = счёт.get(ключ, 0) + 1
    assert файлов >= ФАЙЛОВ_НЕ_МЕНЬШЕ, (
        f"\n🔴 ОБХОД ГРАНИЦЫ ПРОШЁЛ {файлов} файлов при поле "
        f"{ФАЙЛОВ_НЕ_МЕНЬШЕ} (замер 02.09.2026 — 960).\n"
        "Это заявление о ХОДОКЕ, а не о границе: столько файлов пакет не\n"
        "теряет от правки. Проверь `ПАКЕТ` и раскладку прежде, чем верить\n"
        "любому числу этого файла — при пустом обходе три утверждения из\n"
        "четырёх проходят ВАКУУМНО.")
    return счёт


class ГраницаЕстьЗакрытыйСписок(unittest.TestCase):

    def test_ни_одного_неназванного_выхода(self) -> None:
        """AN exit APPEARED that is not in the registry — red."""
        появились = sorted(set(_обход()) - set(ВЫХОДЫ))
        self.assertEqual(появились, [], msg=(
            "\n⚠️  НОВЫЙ ВЫХОД KIR НАРУЖУ, И ОН НЕ НАЗВАН.\n"
            "Это не запрет: связь с хостом предусмотрена. Но KIR стоит\n"
            "отдельно, и каждый выход — то, чего у чужого человека может не\n"
            "оказаться. Впиши в ВЫХОДЫ с доводом либо развяжи.\n"
            + "\n".join(f"    {ф} -> {и} ({р})" for ф, и, р in появились)))

    def test_дверь_тянет_чужое_только_лениво(self) -> None:
        """🔴 THE ARGUMENT FOR THE DOOR ENTRY — VERIFIABLE, NOT A WORD.

        The `kir/mcp/` exits were entered into the registry with the
        argument "the door ships as a separate extra, and `import kir`
        without it pulls in none of this." An argument nobody checks is
        just a word: on 02.09 I declared eleven names dark "because they
        are named in the lesson," removed a name from the lesson, and the
        guard stayed green.

        Here the argument is COMPUTED: for a foreign import under
        `kir/mcp/`, the nesting depth inside a function body must be
        NON-ZERO. A module-level import would mean that an install
        WITHOUT the extra fails on importing the door itself — exactly
        the core's promise that this whole file exists for.
        """
        import ast

        # 🔴 THE STANDARD LIBRARY IS ASKED OF PYTHON, NOT ENUMERATED. The
        # first draft carried a hand-written list, and it immediately
        # erred twice: `secrets` was declared foreign, and `pytest` was
        # declared legitimate. A hand-written list of names is a
        # dictionary, not a mechanism: it lies in both directions, and
        # silently.
        свои = {"kir", "__future__"}
        стандартные = set(sys.stdlib_module_names)

        дверь = ПАКЕТ / "mcp"
        self.assertTrue(дверь.is_dir(), f"двери нет: {дверь}")
        модульные: list[str] = []
        файлов = лениво = 0
        for путь in sorted(дверь.rglob("*.py")):
            # THE DOOR'S OWN TESTS ARE A DIFFERENT SUBJECT, and this is
            # not a favor: they don't ship to someone else (`WHEEL_KEEP`
            # cuts them out), and a module-level `pytest` import in them
            # is legitimate. The promise "installs without the extra"
            # rests on what actually SHIPS.
            if "__pycache__" in путь.parts or "tests" in путь.parts:
                continue
            файлов += 1
            дерево = ast.parse(путь.read_text(encoding="utf-8"))
            глубина = {0}

            class Обход(ast.NodeVisitor):
                def __init__(self) -> None:
                    self.в_теле = 0

                def visit_FunctionDef(self, узел):  # noqa: N802
                    self.в_теле += 1
                    self.generic_visit(узел)
                    self.в_теле -= 1

                visit_AsyncFunctionDef = visit_FunctionDef

                def _назвать(self, имя: str, узел) -> None:
                    nonlocal лениво
                    корень = (имя or "").split(".")[0]
                    if not корень or корень in свои or корень in стандартные:
                        return
                    if self.в_теле:
                        лениво += 1
                    else:
                        модульные.append(
                            f"{путь.relative_to(ПАКЕТ)}:{узел.lineno} -> {имя}")

                def visit_Import(self, узел):  # noqa: N802
                    for a in узел.names:
                        self._назвать(a.name, узел)

                def visit_ImportFrom(self, узел):  # noqa: N802
                    if узел.level == 0 and узел.module:
                        self._назвать(узел.module, узел)

            Обход().visit(дерево)
        # DENOMINATOR: an empty traversal would pass vacuously
        self.assertGreaterEqual(
            файлов, 5,
            f"обход двери прошёл {файлов} нетестовых файлов — при замере 03.09 их было 7")
        self.assertGreaterEqual(
            лениво, 5,
            f"ленивых чужих импортов найдено {лениво} — обход перестал их "
            "видеть, и «модульных ноль» ниже стало бы заявлением о ходоке")
        self.assertEqual(
            модульные, [],
            "\n🔴 ДВЕРЬ ТЯНЕТ ЧУЖОЕ НА УРОВНЕ МОДУЛЯ. Установка БЕЗ дополнения "
            "упадёт на импорте самой двери, а реестр выходов оправдывает эти "
            "имена ровно тем, что импорт ЛЕНИВЫЙ:\n    "
            + "\n    ".join(модульные))

    def test_дверь_в_occt_одна_и_её_отсутствие_названо(self) -> None:
        """🔴 THE ARGUMENT FOR THE `OCP` ENTRY — COMPUTED, NOT READ.

        `ДВЕРИ_ПРОФИЛЕЙ` lifts a CORE exit out from under the main
        assertion — meaning it is the MOST expensive exemption in the
        file. So all three of its premises are checked here, each by an
        instrument:

          1. the door is named and in the registry (otherwise it would
             have been set up bypassing `ВЫХОДЫ`);
          2. `OCP`, in the package's production code, is spoken by
             EXACTLY one file — this very one (measured 07.09.2026
             BEFORE the fix: four files, 24 hits);
          3. the import is LAZY, and without `OCP` the door returns a
             NAMED refusal, `GeometryRefusal("kernel_unavailable")`, not
             an `ImportError` from somewhere else.

        The third premise was paid for in the tree: `import kir` without
        the profile must come up clean, otherwise the whole point of the
        exemption is lost.
        """
        import ast
        import importlib
        import sys as _sys

        # ── 0. THE SET OF EXEMPTIONS IS CLOSED, AND CLOSED HERE.
        # Without this line, `ДВЕРИ_ПРОФИЛЕЙ` is a hole of general shape:
        # the next wave will write a third name into it, and a CORE exit
        # to a foreign package will slip out from under the main
        # assertion WITHOUT A SINGLE VERIFIED ARGUMENT. The argument
        # below is written about `OCP`, and only about it, so the set
        # must be about it too.
        self.assertEqual(sorted(ДВЕРИ_ПРОФИЛЕЙ),
                         [("occt_geometry.py", "OCP", "мягкий")], msg=(
            "\n🔴 В `ДВЕРИ_ПРОФИЛЕЙ` появилось послабление, доводу которого "
            "здесь НЕЧЕМ быть проверенным. Пиши довод-прибор рядом или убирай."))

        # ── 1. The door is named in the registry, not only here.
        призраки = sorted(ДВЕРИ_ПРОФИЛЕЙ - set(ВЫХОДЫ))
        self.assertEqual(призраки, [], msg=(
            "\n🔴 ДВЕРЬ ЯДРА ВЫВЕДЕНА ИЗ-ПОД ГЛАВНОГО УТВЕРЖДЕНИЯ, НО В РЕЕСТР\n"
            "НЕ ВПИСАНА. Тогда её число никто не сторожит: обращений может\n"
            f"стать хоть сто. {призраки}"))

        # ── 2. `OCP` is spoken by EXACTLY one production file.
        произносят: dict[str, int] = {}
        файлов = 0
        for путь in sorted(ПАКЕТ.rglob("*.py")):
            if "__pycache__" in путь.parts or "tests" in путь.parts:
                continue
            файлов += 1
            дерево = ast.parse(путь.read_text(encoding="utf-8", errors="surrogateescape"))
            сколько = 0
            for узел in ast.walk(дерево):
                if isinstance(узел, ast.Import):
                    сколько += sum(1 for a in узел.names if a.name.split(".")[0] == "OCP")
                elif isinstance(узел, ast.ImportFrom) and not узел.level and узел.module:
                    сколько += узел.module.split(".")[0] == "OCP"
            if сколько:
                произносят[путь.relative_to(ПАКЕТ).as_posix()] = сколько
        # DENOMINATOR: an empty traversal would hand back "one door"
        # vacuously.
        self.assertGreaterEqual(файлов, 200, (
            f"обход прошёл {файлов} нетестовых файлов — замер 07.09.2026 дал "
            "371; пол взят с запасом (потеря подпакета — это десятки), потому "
            "что при пустом обходе «дверь одна» стало бы заявлением о ХОДОКЕ, "
            "а не о дереве"))
        self.assertEqual(произносят, {"occt_geometry.py": 3}, msg=(
            "\n🔴 `OCP` ПРОИЗНОСИТ НЕ ОДИН ФАЙЛ. Дверь в OCCT одна на ДЕРЕВО, а\n"
            "не одна на модуль: второй `from OCP...` обходит пин версии,\n"
            "который дверь сверяет ровно один раз, и на чужой сборке OCCT\n"
            f"считает молча по другим правилам. Носители: {произносят}"))

        # ── 3. Laziness, and the NAME of the refusal, not an
        # ImportError from somewhere else.
        occt = importlib.import_module("kir.occt_geometry")
        дерево = ast.parse((ПАКЕТ / "occt_geometry.py").read_text(encoding="utf-8"))
        в_теле = set()
        for узел in ast.walk(дерево):
            if isinstance(узел, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for под in ast.walk(узел):
                    if isinstance(под, (ast.Import, ast.ImportFrom)):
                        в_теле.add(id(под))
        модульные = [
            узел.lineno for узел in ast.walk(дерево)
            if isinstance(узел, (ast.Import, ast.ImportFrom))
            and id(узел) not in в_теле
            and any(и.split(".")[0] == "OCP" for и in (
                [a.name for a in узел.names] if isinstance(узел, ast.Import)
                else ([узел.module] if узел.module and not узел.level else [])))]
        self.assertEqual(модульные, [], msg=(
            "\n🔴 ДВЕРЬ ТЯНЕТ `OCP` НА УРОВНЕ МОДУЛЯ: `import kir` без профиля\n"
            f"`requirements-geometry-occt.txt` упадёт на импорте. Строки: {модульные}"))

        занято = "OCP" in _sys.modules
        прежний = _sys.modules.get("OCP")
        occt._kernel.cache_clear()
        try:
            _sys.modules["OCP"] = None          # the profile is not installed
            with self.assertRaises(occt.GeometryRefusal) as поймано:
                occt._kernel()
            self.assertEqual(поймано.exception.code, "kernel_unavailable")
        finally:
            if занято:
                _sys.modules["OCP"] = прежний
            else:
                _sys.modules.pop("OCP", None)
            occt._kernel.cache_clear()

    def test_реестр_не_несёт_призраков(self) -> None:
        """An exit VANISHED but the entry remained — also red.

        One-sided completeness is half a guard: a registry that a subject
        left lies exactly as much as a registry missing a new one. And it
        hides good news: nobody will notice the untangling.
        """
        исчезли = sorted(set(ВЫХОДЫ) - set(_обход()))
        self.assertEqual(исчезли, [], msg=(
            "\n🟢 ВЫХОД РАЗВЯЗАН, А ЗАПИСЬ ОСТАЛАСЬ. Убери её из ВЫХОДЫ:\n"
            + "\n".join(f"    {ф} -> {и} ({р})" for ф, и, р in исчезли)))

    def test_ядро_не_выходит_наружу_вовсе(self) -> None:
        """🔴 THIS FILE'S MAIN ASSERTION.

        A test may call a product instrument — that is debt, and it is
        named. But the CORE that ships to someone else must be clean: an
        exit from it is not "an inconvenience for the run," it is a
        failure at the user's end.
        """
        # 🔴 A THIRD CATEGORY, NOT AN EXEMPTION (03.09.2026). The core's
        # promise is "installs and works WITHOUT extras." The `kir/mcp/`
        # door works only with its own extra and declares this in
        # `pyproject`; its exit does not break the core's promise — but
        # only for as long as the import is LAZY, and that is separately
        # pinned below. The same import in `kir/compiler.py` remains
        # dirt: the condition rests on the DIRECTORY, not on the word.
        грязь = sorted(k for k in _обход()
                       if "/tests/" not in k[0] and not k[0].startswith("tests/")
                       and not k[0].startswith("mcp/")
                       and k not in ДВЕРИ_ПРОФИЛЕЙ)
        self.assertEqual(грязь, [], msg=(
            "\n🔴 ЯДРО KIR ТЯНЕТ ЧУЖОЕ — отдельно поставленный язык сломается\n"
            "у пользователя, а не на сборке:\n"
            + "\n".join(f"    {ф} -> {и} ({р})" for ф, и, р in грязь)))

    def test_жёстких_не_больше_замеренного(self) -> None:
        """A RISE is red. The bar is never raised; the exit is named or
        untangled."""
        жёстких = sum(n for (_, _, р), n in _обход().items() if р == "жёсткий")
        self.assertLessEqual(жёстких, ЖЁСТКИХ_ЗАМЕРЕНО, msg=(
            f"\n🔴 ЖЁСТКИХ ВЫХОДОВ СТАЛО {жёстких}, ПЛАНКА {ЖЁСТКИХ_ЗАМЕРЕНО} "
            f"(+{жёстких - ЖЁСТКИХ_ЗАМЕРЕНО}).\n"
            "Жёсткий выход исполняется ПРИ ЗАГРУЗКЕ: он ломает СБОР набора там,\n"
            "где чужого пакета нет. Впиши его в `ВЫХОДЫ` с причиной либо\n"
            "развяжи. `ЖЁСТКИХ_ЗАМЕРЕНО` НЕ ПОДНИМАЙ: планка, идущая за\n"
            "деревом, стережёт свою свежесть, а не долг."))

    def test_храповик_затянут(self) -> None:
        """A DECREASE is red too, and the guard NAMES how far to lower
        the bar.

        Untangled but the bar left unlowered — the ratchet stopped
        holding: a slot opened up, and the next hard exit will slip in
        silently.
        """
        жёстких = sum(n for (_, _, р), n in _обход().items() if р == "жёсткий")
        self.assertGreaterEqual(жёстких, ЖЁСТКИХ_ЗАМЕРЕНО, msg=(
            f"\n🟢 ДОЛГ УБЫЛ: жёстких {жёстких}, планка {ЖЁСТКИХ_ЗАМЕРЕНО} "
            f"(−{ЖЁСТКИХ_ЗАМЕРЕНО - жёстких}).\n"
            f"ПЛАНКУ МОЖНО ОПУСТИТЬ ДО {жёстких} — сделай это ТЕМ ЖЕ коммитом,\n"
            "что развязал, и вычеркни из `ВЫХОДЫ` записи, которых больше нет\n"
            "(их назовёт `test_реестр_не_несёт_призраков`)."))


class ПриборУмеетСказатьНЕТ(unittest.TestCase):
    """FAIL CONTROL. A guard that doesn't turn red on a planted violation
    is a dummy, and this has already happened in this tree."""

    ИМЯ = "_контроль_границы_.py"

    def _разобрать(self, исходник: str) -> list[_КЛЮЧ]:
        файл = ПАКЕТ / self.ИМЯ
        файл.write_text(исходник, encoding="utf-8")
        try:
            return _выходы_файла(файл)
        finally:
            файл.unlink()

    def test_ловит_жёсткий(self) -> None:
        self.assertEqual(self._разобрать("from kukai.api.chat_ws import send\n"),
                         [(self.ИМЯ, "kukai", "жёсткий")])

    def test_ловит_мягкий_и_не_путает_его_с_жёстким(self) -> None:
        self.assertEqual(
            self._разобрать("def f():\n    import kukai.api\n    return kukai\n"),
            [(self.ИМЯ, "kukai", "мягкий")])

    def test_тело_класса_жёсткое(self) -> None:
        self.assertEqual(self._разобрать("class C:\n    import kukai\n"),
                         [(self.ИМЯ, "kukai", "жёсткий")])

    def test_ловит_соседа_по_репозиторию(self) -> None:
        """A module sitting next to the package is as much an exit as a
        foreign package."""
        self.assertEqual(self._разобрать("import tools\n"),
                         [(self.ИМЯ, "tools", "жёсткий")])

    def test_не_краснеет_на_своих_и_объявленных(self) -> None:
        """One's own package, the stdlib, and DECLARED dependencies are
        not exits. An instrument that caught its own home would be
        switched off within a day."""
        self.assertEqual(self._разобрать(
            "from kir.spec import OPS\n"
            "import kir\n"
            "from kir.clash import detect\n"
            "from kir.checker import engine\n"
            "import shapely\nimport networkx\nimport json\n"
            "from .spec import OPS\n"), [])

    def test_относительный_уход_ловится(self) -> None:
        """`from ..llm import x` leads outside without naming itself as
        such."""
        self.assertEqual(self._разобрать("from ..llm import turn_context\n"),
                         [(self.ИМЯ, "llm", "жёсткий")])


if __name__ == "__main__":
    unittest.main()
