"""6/6 compile-gate runner — the prod-path gate (SPEC §5, discipline item 4).

Wraps emitted Execute-bodies with the SAME wrap_user_code the serving pipeline
uses and drives the host's live Roslyn compile service across all six Revit
versions. Exit code != 0 on any failure. Run:

    PYTHONPATH=backend backend/venv/bin/python -m kir.gate_runner

WHAT THESE NUMBERS ASSERT, AND WHAT THEY DO NOT ASSERT (12.08.2026). The
gate's question is **does the emitted C# compile on six versions of
Revit**, and the answer to it is honest: the arbiter here is the real
Autodesk reference assemblies, and their sha256 is printed alongside the
result. But everything that requires grounding is grounded against a
SYNTHETIC fixture (`GROUND_SNAPSHOT_ORIGIN` below), not against a real
document. So an "OK" from such a program is a claim about the fixture,
and the share of such compilations is now PRINTED alongside the count,
not merely remembered.

Why this is not pedantry: the SUITE zone measured on 12.08 that the
fixture lacked the `roof_types` pool, and `create_roof`/
`create_extrusion_roof` were not grounded by default anywhere. It got
away with a single red only because the pool is declared OPTIONAL; a
mandatory one in the same position would have brought down the whole gate
— and it would have looked like "the op is broken," not "the model is
poor." Fixture completeness is a property of THE GATE, not only of the
suite.
"""
# 🔴 PROVENANCE WAS MOVED OUT OF THE DOCSTRING ON 01.09.2026 — A DOOR
# AGAINST THE JOURNAL. A module docstring is a PUBLIC DOOR: `help()` prints
# it to the reader of the published package, and our machine's address
# tells them nothing. The knowledge is not erased — it is here, in the
# journal, where it belongs:
#     the host's live Roslyn compile service — `kukai-compile.service`,
#     reached at localhost:52412
from __future__ import annotations

import asyncio
import math
import os
from kir import env  # noqa: E402  (a submodule with no dependencies — introduces no cycle)
import random
import sys
import tempfile

env.set_default("KIR_REJECTIONS_PATH",
                os.path.join(tempfile.gettempdir(), "kir_gate_queue.jsonl"))

from kir.compile_client import CompileClient                     # noqa: E402
# 🔴 A HALF-MEASURE, AND IT IS NAMED AS SUCH (15.08.2026). There used to be
# a TOP-LEVEL import of the product here, because of which `kir/` — a
# package published as a separate repository — could not be imported
# without `kukai/llm`. The import has been made lazy: the package now
# imports cleanly, and the product is only needed to RUN the gate.
#
# WHY NOT THE MOVE THAT WOULD BE MORE HONEST. By subject, `wrap_user_code`
# belongs to the compiler: it is about the emitted C#. But its literals
# (`WRAPPER_HEADER`/`WRAPPER_FOOTER`) are pinned by an AST DRIFT GUARD that
# keeps THREE copies of the wrapper pairwise in sync (`chat_ws` legacy,
# `kukai/modeling/tests/bridge/test_exec_wrapper_sync.py`,
# `tests/test_revit_execution_pipeline.py`) and parses the SOURCE of that
# module. Moving the owner without redirecting this scheme either breaks
# the guard or SILENTLY weakens it — and three copies of one quantity is
# itself a named defect of the tree. This is a wave, not a one-line fix,
# and until it happens the import stays lazy.
def _wrap_user_code(code: str) -> str:
    wrap_user_code = ports.need(ports.EXECUTION).wrap_user_code
    return wrap_user_code(code)


wrap_user_code = _wrap_user_code
from kir import spec                                          # noqa: E402
# THE REVIT VERSION HAS ONE SOURCE. The literal `"2023"` in the parameter
# default was the SEVENTH place producing a version, and it was caught by
# the closed registry `tests/test_revit_version_has_one_source.py` —
# exactly what it was set up for.
from kir import revit_version as _rv                          # noqa: E402
from kir.compiler import compile_program                      # noqa: E402
from kir.op_contract import audit_contract_kernel             # noqa: E402
from kir.install_paths import (install_data_path,             # noqa: E402
                               install_root_refusal)
from kir.tests.test_golden import PROGRAMS                    # noqa: E402
from kir.tests.test_pbt import gen_program                    # noqa: E402
from kir import ports

N_PBT = 25
SEED = 62026

#: Where the gate takes its grounding snapshot from. A synthetic FIXTURE,
#: not a real document: it knowingly has fewer types, pools, and elements.
#: For the gate's question ("does the C# compile on six versions") this is
#: legitimate, because the question is about COMPILATION. But any "OK"
#: from a program that requires a snapshot is a claim about the fixture,
#: and the count itself must print that — see the summary block in
#: `main()`. The round-trip decompile-check has NO RIGHT to ground on the
#: fixture: there the question is "does the round trip reproduce THIS
#: building," and a poor model would produce discrepancies of its own
#: making (the director's decision of 12.08 — the snapshot of that run,
#: `open_model.profile.json`, is present in 73 of 80 runs — re-measured
#: 15.08.2026; the earlier record of "70 of 77" went stale along with the
#: corpus).
GROUND_SNAPSHOT_ORIGIN = "kir.tests.fixtures.GROUND_SNAPSHOT"

# ═════════════════════════════════════════════════════════════════════════
# SECOND STRIP: GROUNDING WITH A REAL DOCUMENT
#
# The first strip answers "does the C# compile on six versions" and
# grounds against the FIXTURE. The second answers a DIFFERENT question:
# "does this program ground against a document someone actually
# designed." The answers are independent and must not be added together:
# a program can compile on all six and have not a single real document it
# can be grounded against.
#
# NO BRIDGE AND NO LIVE REVIT ARE REQUIRED: every saved decompile carries
# an `open_model.profile.json`, and `OpenModelProfile.to_ground_snapshot()`
# (the `open_model` module) already knows how to turn it into a snapshot
# of the same shape as the fixture. Not a single new converter is written
# here — an existing one is queried.
#
# 🔴 A NUMBER THAT IS EASY TO READ WRONG. `required_pools` in the profile
# is a CONSTANT list of 36 names, stamped into every profile. "Union over
# the corpus = 36 = required" is therefore true and EMPTY: it speaks about
# the list, not about the content. Measured 15.08.2026 across 73 prod
# profiles: pools with NON-EMPTY entries — 28 of 36, and eight are never
# filled in ANY decompile (`area_load_types`, `area_reinforcement_types`,
# `foundation_symbols`, `line_load_types`, `point_load_types`,
# `rebar_bar_types`, `rebar_hook_types`, `truss_types`). The selection
# below asks for ENTRIES, not names.

#: The root of saved decompiles. The same address that `serving` and
#: `course.corpus` read — one variable name for the whole project.
#:
#: 🔴 IT USED TO BE A TRIPLE `dirname` FROM THIS FILE — after the split it
#: pointed into `/opt`. Counting STEPS UPWARD is correct for exactly one
#: layout, and this has already cost twice: the sandbox (`f518b05`) and
#: `install_paths`, where six telemetry feeds went silent and acceptance
#: started refusing pre-effect. The install root is asked of the
#: authority; an empty string when it is silent is honest — the existing
#: `is_dir` guards refuse, and `install_root_refusal()` names the REASON.
REAL_PROFILE_ROOT = env.get("KIR_DECOMPILE_DATA") or str(
    install_data_path("decompile") or "")

#: How to fetch the corpus if it is not in this tree. This lives RIGHT
#: NEXT TO the refusal, not in anyone's memory: "a guard with no
#: instrument must refuse in a category that cannot be mistaken for
#: 'nothing found'."
#:
#: 🔴 THE INSTALLATION ADDRESS IS NOT WRITTEN HERE. This file ships to
#: open source, and an absolute deployment path in executable code is a
#: leak, not a hint (`tests/test_authority_boundaries.py` holds this as a
#: prohibition, and it caught the first draft of this line). The hint
#: names the VARIABLE and the shape of the address; the concrete address
#: belongs to the installation and lives in its environment.
REAL_PROFILE_FETCH_HINT = (
    "профилей не найдено. Корпус машинно-локален и в чекаут не входит; "
    "укажите его адрес переменной KUKAI_DECOMPILE_DATA — она ждёт каталог, в "
    "котором лежат подкаталоги разборов с файлом open_model.profile.json")


def instrument_refusal_line(refused: int, subject: str = "настоящий документ",
                            why: str = "") -> str:
    """The machine string about an INSTRUMENT refusal — TOTAL, zero prints too.

    Owner's decision of 16.08.2026: the gate must distinguish three
    outcomes — green · red · INSTRUMENT REFUSAL — and the third must be
    impossible to mistake for the first. Hence totality: the function
    returns no empty string for ANY input whatsoever, because the absence
    of a string reads as "the question was never asked," while zero reads
    as "asked, and there is nothing to answer with."

    Factored out of the two printing branches for exactly this reason — so
    that a control has a subject: the branch with a live corpus cannot be
    run offline (it needs both the corpus and Roslyn), while the helper's
    totality can be checked with zero dependencies.
    """
    tail = f" — {why}" if why else ""
    return f"      ОТКАЗ ПРИБОРА ({subject}): {refused}{tail}"


def pools_required_by(program: dict) -> frozenset[str]:
    """The pools a program requires AFTER macro expansion.

    The REGISTRY is queried (`OpSpec.grounded`), not operation names: a
    pool with a `{category}` substitution is resolved by the value of the
    operation itself, because for a column the architectural and
    structural pools are DIFFERENT, and picking one would ground half the
    programs against the wrong catalog.

    Macro expansion is mandatory for the same reason it is mandatory for
    `_needs_snapshot`: the stack hides pipes, and it is precisely the
    hidden operation that carries the pool requirement.
    """
    from kir import macros as _macros

    ops = program.get("ops", [])
    try:
        ops = _macros.expand(ops)
    except Exception:          # noqa: BLE001 — the compiler will refuse and name the reason
        pass
    need: set[str] = set()
    for op in ops if isinstance(ops, list) else []:
        if not isinstance(op, dict):
            continue
        ospec = spec.OPS.get(op.get("op"))
        if ospec is None:
            continue
        for _param, pool, _required in ospec.grounded:
            if "{category}" in pool:
                pool = pool.format(
                    category=op.get("category") or "structural")
            need.add(pool)
    return frozenset(need)


def load_real_profiles(root: str = "") -> list[tuple[str, dict, frozenset[str]]]:
    """`(run name, snapshot, set of NON-EMPTY pools)`, ordered by run name.

    The order is determined by name: the gate must answer identically on
    two consecutive runs, and directory order is not that.

    A pool with empty `entries` is NOT INCLUDED in the set: it is declared
    and offers nothing, and grounding by name in an empty catalog is a
    refusal. Counting such a pool as "present" would mean getting green
    where there is nothing to choose from.
    """
    import glob as _glob
    import json as _json

    from kir.open_model import OpenModelProfile

    root = root or REAL_PROFILE_ROOT
    found: list[tuple[str, dict, frozenset[str]]] = []
    pattern = os.path.join(root, "*", "open_model.profile.json")
    for path in sorted(_glob.glob(pattern)):
        run = os.path.basename(os.path.dirname(path))
        try:
            with open(path, encoding="utf-8") as fh:
                profile = OpenModelProfile.from_dict(_json.load(fh))
            snapshot = profile.to_ground_snapshot()
        except Exception:      # noqa: BLE001 — a broken profile does not bring down the gate
            continue
        filled = frozenset(
            name for name, rows in snapshot.items()
            if isinstance(rows, list) and rows)
        found.append((run, snapshot, filled))
    return found


def ground_on_real_document(
        program: dict,
        profiles: list[tuple[str, dict, frozenset[str]]],
        *, revit_version: str = _rv.DEFAULT_VERSION
        ) -> tuple[str, dict] | str:
    """The first real document the program can be GROUNDED against, or a reason.

    Returns `(run name, snapshot)` or a reason string — three outcomes, not
    two, and that is exactly the distinction the function exists for:

    * `no profile with pools …` — not one corpus decompile carries the
      needed catalogs. This is a fact about the CORPUS;
    * `KIR-G101 …` / any refusal code — the catalogs exist, but the
      program is named by a vocabulary that these buildings do not have.
      This is a fact about the PROGRAM;
    * success — the program is grounded against a real building.

    WHY EXHAUSTIVE SEARCH, NOT "FIRST FIT". The first draft took the first
    profile whose pools were non-empty, and got 10 grounded out of 69 with
    29 `KIR-G101` refusals — all against one and the same building, which
    happened to come first alphabetically. It had pools, but its TYPE
    NAMES were its own. "Does the program ground against a real document"
    is a question about the EXISTENCE of such a document, so every
    candidate is tried. A choice made without a search is a choice made
    without an act of discrimination.
    """
    need = pools_required_by(program)
    if not need:
        # 🔴 FORM 18, CAUGHT BY A CONTROL RUN AGAINST ITSELF. A program
        # that needs NOT A SINGLE pool "grounds" against any profile,
        # including a knowingly empty one: `need <= filled` is always true
        # for the empty set. The first draft counted these as success and
        # inflated the count — green obtained with no act of
        # discrimination. There is nothing to ground here, and this is a
        # THIRD OUTCOME, not a variety of success.
        return "заземлять нечего: программа не требует ни одного пула"
    candidates = [(run, snap) for run, snap, filled in profiles
                  if need <= filled]
    if not candidates:
        missing = sorted(need - frozenset().union(
            *[filled for _r, _s, filled in profiles]) if profiles else need)
        return ("нет профиля с пулами: "
                + ", ".join(missing or sorted(need)))
    last = "?"
    for run, snapshot in candidates:
        try:
            out = compile_program(program, revit_version=revit_version,
                                  snapshot=snapshot, bulk=True)
        except Exception as exc:            # noqa: BLE001
            last = type(exc).__name__
            continue
        if out.ok:
            return run, snapshot
        last = out.diagnostics[0].code if out.diagnostics else "?"
    return f"{last}, перебрано профилей: {len(candidates)}"

SIZED_CABLE_TRAY_GATE_NAME = "auth_cable_tray_sized"
SIZED_CABLE_TRAY_GATE_MARKERS = (
    "RBS_CABLETRAY_WIDTH_PARAM",
    "RBS_CABLETRAY_HEIGHT_PARAM",
)


def register_sized_cable_tray_gate(programs: dict[str, dict]) -> None:
    """Put the sectioned cable-tray emitter branch in the live gate corpus."""
    if SIZED_CABLE_TRAY_GATE_NAME in programs:
        raise RuntimeError(f"duplicate gate program: {SIZED_CABLE_TRAY_GATE_NAME}")
    programs[SIZED_CABLE_TRAY_GATE_NAME] = {
        "ir_version": "1.0",
        "intent": "кабельный лоток 300x100",
        "ops": [{
            "op": "create_cable_tray",
            "id": "CT2",
            "p0_mm": [0, 5000, 3000],
            "p1_mm": [6000, 5000, 3000],
            "level": {"by": "element_id", "value": 42},
            "width_mm": 300,
            "height_mm": 100,
        }],
    }


def sized_cable_tray_branch_reached(csharp: str) -> bool:
    """True only when the emitted body contains both section operands."""
    return all(marker in csharp for marker in SIZED_CABLE_TRAY_GATE_MARKERS)

#: Representative ids for side-stage bodies. The emitted C# is invariant to
#: the NUMBER of ids by construction, so two are enough; what matters is
#: only that they are real numeric ids, not stand-ins — the numeric
#: parsing inside the body is real.
GATE_SIDE_STAGE_IDS = ["19227219", "456"]

#: Program -> the EARLIEST Revit version on which it builds at all. Below
#: that, `KIR-E003` is the CORRECT answer, not "a known hole": the
#: operation honestly said that on this version it has no counterpart in
#: the API. The gate must distinguish this from broken emission, otherwise
#: green would require silently building something else instead — exactly
#: the Goodhart effect this refusal was set up to fight.
#:
#: AS DATA, NOT AS A CONDITION (09.08.2026). Before this date there was a
#: list of names here and a hard-coded `ver == "2021"`, meaning exactly
#: one boundary could be expressed. The site wave brought a second: the
#: `Toposolid` class does not exist before 2024, so
#: `site_topography_toposolid` refuses on THREE versions, and the old form
#: would have recorded two of the three correct refusals as gate
#: failures. The boundary is a property of the operation, which is why it
#: sits as a number right next to the program.
E003_EXPECTED_BELOW: dict[str, str] = {
    # 2022: holes on a floor/foundation slab — the Floor.Create(loops) path.
    "auth_floor_holes": "2022",
    "auth_contour_l": "2022",
    "struct_foundation_slab_holes_2021": "2022",
    "struct_foundation_slab": "2022",
    # Arrived with the reconciliation of 13.08.2026 and brought down the
    # gate: the program was new, the list did not know it. Added BY
    # STRUCTURE, not by name — the name here is deceptively similar to its
    # neighbor, and that is not enough. Measured: both programs are the
    # SAME `create_foundation` with the same set of parameters, including
    # `holes`; both refuse on 2021 and both are green on 2022; the
    # diagnostic text matches byte for byte — "openings in a foundation
    # slab are not supported on Revit 2021." The boundary is the same one,
    # which is why the number is the same one.
    "struct_foundation_slab_two_holes": "2022",
    # 2022: Ceiling.Create; the legacy doc.Create.NewCeiling does not exist
    # on any of the six versions (measured), so there is nowhere to fall
    # back to.
    "arch_ceiling": "2022",
    "arch_ceiling_contour": "2022",
    # 2024: the Toposolid class does not exist earlier (CS0246 on
    # 2021/2022/2023 — measured by compilation on 09.08). The terrain
    # surface (site_topography_surface) does NOT belong here: it builds
    # 6/6, and these are different elements of different categories.
    "site_topography_toposolid": "2024",
    # 2025: and this boundary is the ONE AND ONLY whose cause lies NOT in
    # the Revit API but in the reference closure of the DEPLOYED plugin
    # (12.08.2026). The members exist on all six, and the gate compiled
    # the body 6/6 green — but the entire multi-story-run API is typed
    # `ISet<ElementId>`, and deployed/net48 does not reference
    # `System.dll`, and `ISet` is absent from its closure (declared 43
    # assemblies / 3003 types, deployed 42 / 2007 — the difference is
    # EXACTLY `System.dll`). The body compiled for us and would have
    # thrown CS0012 for the user. The refusal is lifted together with the
    # cause: the judge is not memory but
    # tests/test_emitted_csharp_client_closure.py, the deployed profile.
    "datums_multistory_stairs": "2025",
}

#: Stages whose C# ships to Revit but which are NOT in the pipeline
#: registry. Tier G is now the live stage ``geometry`` and is taken from
#: that same registry, so the honest remainder is empty. Any new bypass
#: stage must be named here.
UNREGISTERED_GATE_STAGES = frozenset()


def side_stage_gate_bodies(revit_version: str) -> dict[str, str]:
    """The C# of EVERY side stage, emitted FOR THIS Revit version.

    WHY THIS IS A FUNCTION, NOT A LIST OF IMPORTS INSIDE ``main``. Before
    30.07 there was a hand-written dictionary of four builders here:
    ``family_placement`` / ``group`` / ``curtain`` / ``sketch``. There were
    nine stages. Five of them — ``curve``, ``geometry``, and three new ones
    (annotations, MEP systems, tags) — the gate never saw, and one of them
    failed to build on a third of the shipped versions:

        CS1503: Argument 1: cannot convert from 'long' to
        'Autodesk.Revit.DB.BuiltInParameter'

    Decompiling a 59-story tower on R2023 repeated this refusal in a loop
    for an hour and a half with ``bridge_roundtrips=0``. The hand-written
    dictionary could not catch this by construction: for a stage to reach
    the gate, someone had to remember to add it.

    Now there is ONE source of builders — the pipeline registry. A stage
    added to the registry reaches the gate on its own; a stage added
    around the registry must be named in :data:`UNREGISTERED_GATE_STAGES`,
    otherwise the name check
    (``test_side_stage_contract.SideStageGateCoverageTests``) fails the
    build.

    EMISSION PER VERSION, NOT ONE TEXT SIX TIMES OVER: tags' C# depends on
    the version by construction (the ``TaggedLocalElementId`` /
    ``GetTaggedLocalElementIds`` seam at 2022). A gate that emits once
    would be checking one surface six times — a defect that
    ``tools/compile_gate_offline.py`` has already described in its own
    docstring.
    """
    from kir.decompile import pipeline as _pipe
    return {
        stage: builder(GATE_SIDE_STAGE_IDS)
        for stage, builder in _pipe._default_cs_builders(revit_version).items()
    }


def acceptance_gate_body() -> str:
    """Representative live L2 reread, compiled on every shipped Revit API."""

    from kir.acceptance import derive_expectation
    from kir.acceptance_live import build_scope_census_cs
    from kir.compiler import plan_program
    from kir.contracts import DocumentFingerprint

    planned = plan_program({
        "ir_version": "1.0",
        "ops": [
            {"op": "create_wall", "id": "W1",
             "p0_mm": [0, 0], "p1_mm": [6000, 0],
             "level": {"by": "name", "value": "Gate L1"}},
            {"op": "create_pipe", "id": "P1",
             "p0_mm": [0, 0, 2700], "p1_mm": [6000, 0, 2700],
             "level": {"by": "element_id", "value": 42},
             "diameter_mm": 50},
        ],
    })
    expectation = derive_expectation(
        planned, level_names_by_id={42: "Gate L1"})
    return build_scope_census_cs(
        expectation,
        DocumentFingerprint(
            title="KIR gate COPY",
            path_name="gate.rvt",
            project_uid="kir-gate-project",
        ),
        run_id="0" * 32,
        phase="before",
    )


def mutation_acceptance_gate_body(revit_version: str) -> str:
    """Representative atomic census + exact-mutation reread for one API."""

    from kir.acceptance import derive_expectation
    from kir.acceptance_mutation import derive_mutation_expectation
    from kir.acceptance_probe import build_acceptance_probe_cs
    from kir.compiler import plan_program
    from kir.contracts import DocumentFingerprint

    planned = plan_program({
        "ir_version": "1.0",
        "allow_destructive": True,
        "ops": [
            {"op": "create_wall", "id": "W1",
             "p0_mm": [0, 0], "p1_mm": [6000, 0],
             "level": {"by": "name", "value": "Gate L1"}},
            {"op": "set_param", "id": "S1",
             "target": {"by": "element_id", "value": 101},
             "param": "Comments", "value": "KIR gate"},
            {"op": "move_elements", "id": "M1",
             "targets": [{"by": "element_id", "value": 102}],
             "delta_mm": [100, 0, 500]},
            {"op": "change_type", "id": "T1",
             "target": {"by": "element_id", "value": 103},
             "type": {"by": "element_id", "value": 900}},
            {"op": "delete", "id": "D1",
             "target": {"by": "element_id", "value": 104}},
        ],
    })
    document = DocumentFingerprint(
        title="KIR gate COPY",
        path_name="gate.rvt",
        project_uid="kir-gate-project",
    )
    return build_acceptance_probe_cs(
        plan_digest=planned.plan_digest,
        scope_expectation=derive_expectation(planned),
        mutation_expectation=derive_mutation_expectation(planned),
        document=document,
        run_id="1" * 32,
        phase="before",
        revit_version=revit_version,
    )



#: The Revit assemblies the compile service actually references, hashed here
#: so a gate number stops being a number without an address. "1938 live
#: compile checks" says nothing about WHAT it compiled against, and until
#: now the service could not answer: prod `/health` returns COUNTS only —
#: no names, no digests — while the canary carries a `referenceManifestDigest`
#: and per-version digests prod does not know as concepts.
#:
#: Computed SIDEWAYS, from the same NuGet package the service loads
#: (`RoslynCompiler.LoadAllRevitVersions`), so this needs no endpoint, no
#: rebuild and no restart of a deployed service.
#:
#: BOUNDARY, stated here rather than in a report: this is a manifest of the
#: REVIT references only. The system (net8/net48) references are NOT in it
#: and cannot be, sideways: they come from the service process's own
#: TRUSTED_PLATFORM_ASSEMBLIES, a property of the runtime it was started
#: under — which is also why prod reads 48 and the canary 47. Their role is
#: PARITY WITH THE BRIDGE, and that is guarded separately by drift guards on
#: both sides (`AssemblyWhitelistSyncTests.cs`, `test_assembly_whitelist_sync.py`),
#: not by this manifest. Their absence here is a gap in DESCRIPTION, not in
#: protection. Approximating them would be worse than omitting them: an empty
#: column is visible, a substituted one is not.
_REVIT_REF_DLLS = ("RevitAPI.dll", "RevitAPIUI.dll", "AdWindows.dll",
                   "UIFramework.dll")


def revit_reference_manifest() -> tuple[dict[str, str], list[str]]:
    """(version -> digest, problems). Mirrors the service's own path logic."""
    # `os` is taken at MODULE level (line 13). There used to be a local
    # `import os` here, and test_authority_boundaries caught it: a
    # function-level name shadowing the module-level one — the very form
    # where two names for one module live in the same file and silently
    # drift apart when one of them is edited.
    import hashlib

    root = env.get("NUGET_PACKAGES") or os.path.expanduser(
        "~/.nuget/packages")
    base = os.path.join(root, "revit_all_main_versions_api_x64")
    manifest: dict[str, str] = {}
    problems: list[str] = []
    if not os.path.isdir(base):
        return manifest, [f"NuGet package dir absent: {base}"]
    for ver in spec.REVIT_VERSIONS:
        lib = os.path.join(base, f"{ver}.0.0", "lib",
                           "net8.0" if ver >= "2025" else "net48")
        if not os.path.isdir(lib):
            problems.append(f"{ver}: lib dir absent ({lib})")
            continue
        h = hashlib.sha256()
        missing = []
        for dll in _REVIT_REF_DLLS:          # order is part of the digest
            path = os.path.join(lib, dll)
            if not os.path.isfile(path):
                missing.append(dll)
                continue
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
        if missing:
            problems.append(f"{ver}: missing {', '.join(missing)}")
            continue
        manifest[ver] = h.hexdigest()
    return manifest, problems


def model_binding_guard_inputs() -> tuple[dict, object, dict]:
    """The (snapshot, profile, expected_document) triple the guard compiles.

    ONE source. The profile and the snapshot must be derived from the same
    object, because `compiler.py` recomputes the profile from whatever
    snapshot it is handed and refuses `KIR-G107` when the digests differ.
    Until 2026-08-11 this block built the profile from a mutated copy and
    passed the UNMUTATED original to `compile_program` — the pair was
    asserted in one place and read in another, and nothing forced them to
    agree. The gate then counted six checks for a body it never compiled.

    Returned as a triple rather than left inline so a test can compile the
    gate's OWN inputs; the harness is the consumer that went unmeasured.
    """
    import copy

    from kir.open_model import OpenModelProfile
    from kir.tests.fixtures import GROUND_SNAPSHOT

    snapshot = copy.deepcopy(GROUND_SNAPSHOT)
    for level in snapshot["levels"]:
        element_id = int(level["id"])
        level["unique_id"] = f"gate-level-{element_id}"
        level["version_guid"] = f"{element_id:032x}"
    snapshot["levels__total"] = len(snapshot["levels"])
    return (
        snapshot,
        OpenModelProfile.from_ground_snapshot(snapshot),
        {"title": "KIR gate COPY", "path_name": "",
         "project_uid": "kir-gate-project"},
    )


async def main() -> int:
    contract_problems = audit_contract_kernel()
    if contract_problems:
        print("FATAL: KIR operation contract kernel is inconsistent")
        for problem in contract_problems:
            print(f"  - {problem}")
        return 3

    client = CompileClient()
    if not await client.health():
        print("FATAL: compile service :52412 unavailable")
        return 2

    # `__ver__` is a REFERENCE PIN, NOT A PROGRAM FIELD, and both readers
    # of `PROGRAMS` must strip it. The loads wave introduced this key (the
    # loads reference is taken at 2023, because a free load lives only on
    # 2021-2023) and taught `test_golden` to strip it, but not this gate,
    # even though the same wave made an edit here — the E003 exception for
    # 2024+ below. The result: the gate fed the key into the envelope and
    # got KIR-P003 "unknown field" on ALL SIX versions, meaning the
    # exception the wave wrote never fired even once — the program failed
    # before it ever reached it.
    # THIS IS NOT MERGE ARITHMETIC BUT A REAL DEFECT ON THE BRANCH, and it
    # shows that the gate was never run to completion there: stripping the
    # key gives exactly what the wave intended — a build on 2021-2023 and
    # KIR-E003 on 2024-2026.
    programs: dict[str, dict] = {
        name: {k: v for k, v in prog.items() if k != "__ver__"}
        for name, prog in PROGRAMS.items()}
    rng = random.Random(SEED)
    for i in range(N_PBT):
        programs[f"pbt_{i:02d}"] = gen_program(rng)
    # Programs exercising every kind. A KIR program is capped at 20 ops, so
    # chunk instead of truncating: the old [:20] silently left the final kind
    # outside the live gate as soon as the registry grew to 21 entries.
    _kind_ops = [
        {"op": "query_count", "id": f"k{j}", "kind": kind}
        for j, kind in enumerate(sorted(spec.KINDS))
    ]
    for offset in range(0, len(_kind_ops), 20):
        programs[f"all_kinds_{offset // 20:02d}"] = {
            "ir_version": "1.0", "ops": _kind_ops[offset:offset + 20]}
    # fix/g102-disambiguate (2026-07-17): query_types — one program per
    # closed pool, proving every _TYPE_POOL_COLLECTOR_CS idiom (compiler.py)
    # actually compiles on all six versions (the two-table-lockstep guard
    # test_authoring.QueryTypes.test_all_sixteen_pools_compile_offline
    # proves offline; this is the same proof through the live gate).
    # CHUNKING WAS ADDED AT THE 09.08 MERGE, and the mistake was exactly
    # the one the `all_kinds_` block twenty lines above warns about: the
    # number of pools grew PAST TWENTY, and one program covering all pools
    # ran into MAX_OPS_PER_PROGRAM — the gate returned KIR-L001 on all six
    # versions.
    #
    # WHOSE MISTAKE THIS IS — MEASURED BY BRANCH, NOT ASSUMED (the number
    # is taken from each branch's own lock, `assertEqual(len(pools), N)`):
    # the common base — 19 pools (19 ops, the limit not crossed, gate
    # green); the framing wave — 20 (exactly the limit, still passes); the
    # loads wave — 23, meaning THE LIMIT WAS ALREADY CROSSED ON IT, on its
    # own branch, before any merge; the merged tree — 24.
    # So this is NOT merge arithmetic: the gate was already failing on the
    # loads branch itself, exactly as with `__ver__` above. Two
    # independent breaks of the same gate on one branch are a sign that
    # the gate was never run to completion there.
    # We chunk, not truncate: `[:20]` would silently leave the last pools
    # outside the live gate, buying green at the cost of coverage.
    _qt_pools = spec.OPS["query_types"].params[0].choices
    _qt_ops = [{"op": "query_types", "id": f"t{j}", "pool": p}
               for j, p in enumerate(_qt_pools)]
    for offset in range(0, len(_qt_ops), 20):
        programs[f"query_types_all_pools_{offset // 20:02d}"] = {
            "ir_version": "1.0",
            "intent": "какие типы существуют в каждом закрытом пуле",
            "ops": _qt_ops[offset:offset + 20]}
    # authoring family — grounded via the COMMITTED shared fixture (fixtures.py,
    # same snapshot unit tests and goldens use; a private harness copy is how
    # the 2026-07-16 checkpoint became non-reproducible from HEAD)
    from kir.tests.fixtures import GROUND_SNAPSHOT
    from kir.tests.test_authoring import _prog, _wall
    programs["auth_wall"] = _prog([_wall()], intent="стена 6м")
    programs["auth_mixed"] = _prog([
        _wall(),
        _wall(oid="W2", p0_mm=[0, 4000], p1_mm=[6000, 4000],
              type={"by": "name", "value": "ЖБ 200"}, height_mm=2800),
        {"op": "create_pipe", "id": "P1", "p0_mm": [0, 0, 2700],
         "p1_mm": [3000, 0, 2700], "level": {"by": "element_id", "value": 42},
         "diameter_mm": 50},
        {"op": "create_grid", "id": "G1", "p0_mm": [0, -1000],
         "p1_mm": [0, 9000], "name": "А"},
    ], intent="стены+труба+ось")
    register_sized_cable_tray_gate(programs)
    programs["auth_stack"] = {"ir_version": "1.0", "intent": "стек 5 этажей",
        "ops": [{"op": "stack", "id": "sec", "levels": 5, "h_mm": 3000,
                 "floor": [
                     {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                      "p1_mm": [6000, 0], "height_mm": 2800},
                     {"op": "create_pipe", "id": "P1", "p0_mm": [0, 0, 2700],
                      "p1_mm": [3000, 0, 2700], "diameter_mm": 50},
                 ]}]}
    programs["auth_grid_array"] = {"ir_version": "1.0", "intent": "сетка осей 4x3",
        "ops": [{"op": "grid_array", "id": "net", "nx": 4, "ny": 3,
                 "dx_mm": 6000, "dy_mm": 4500, "prefix_y": "А"}]}
    # FAMILY AUTHORING (21.08.2026) — the THIRD KIND of solo program and
    # the FIRST emission in the tree that does NOT write into `doc`. Three
    # lines, and none of them for symmetry: emission has three diverging
    # branches, and a branch the gate does not build is not checked by it
    # at all (the same argument as for the spiral run).
    #
    #   with instance    — `doc.Create.NewFamilyInstance` + two witnesses
    #                       in the project, which the other branch does
    #                       NOT have;
    #   without instance — the receipt must print
    #                       `schedulable_as_building_element: null` with a
    #                       reason, not `true`; in C# that is a different
    #                       constant;
    #   arc and opening   — the profile leads into `Arc.Create` and a
    #                       second `CurveArrArray` ring, meaning the
    #                       `CurveLoop -> CurveArray` conversion, which the
    #                       rectangle never touches.
    #
    # 🔴 THE VERSION AXIS HERE IS REAL, AND THIS IS THE ONLY OP IN THE
    # REGISTRY WHOSE BYTES THEMSELVES DIVERGE BETWEEN 2021 AND 2022+.
    # `FamilyManager.AddParameter` has TWO overloads with different
    # argument TYPES, and their windows overlap only at 2022. Verified by
    # mutating both directions (21.08): the modern spelling on 2021 gives
    # CS0103 `GroupTypeId`; the old spelling on 2026 gives CS0103
    # `BuiltInParameterGroup` plus CS0122 `ParameterType`. So the six OKs
    # below are bought with DIFFERENT text, and a single spelling would
    # never have been enough.
    _AF = {"family_name": "KIR_Ворота", "type_name": "Тип ворот",
           "flex_param": "Высота_KIR"}
    programs["auth_family_placed"] = {"ir_version": "1.0",
        "intent": "авторское семейство с экземпляром",
        "ops": [{"op": "author_family", "id": "AF1", **_AF,
                 "profile": {"outer": {"shape": "rect", "origin": [0, 0],
                                       "size_mm": [600, 400]}},
                 "height_mm": 800, "place_at": [1000, 2000, 0]}]}
    programs["auth_family_definition_only"] = {"ir_version": "1.0",
        "intent": "авторское семейство без экземпляра",
        "ops": [{"op": "author_family", "id": "AF2", **_AF,
                 "family_name": "KIR_Ворота_2",
                 "save_dir": "C:\\KIR",
                 "profile": {"outer": {"shape": "rect", "origin": [0, 0],
                                       "size_mm": [600, 400]}},
                 "height_mm": 800}]}
    programs["auth_family_arc_hole"] = {"ir_version": "1.0",
        "intent": "авторское семейство: дуга в профиле и проём",
        "ops": [{"op": "author_family", "id": "AF3", **_AF,
                 "family_name": "KIR_Ворота_3",
                 "profile": {
                     "outer": {"shape": "poly",
                               "points_mm": [[0, 0], [6000, 0], [6000, 4000],
                                             [0, 4000]],
                               "arcs": [{"edge": 1, "bulge": 0.4}]},
                     "holes": [{"shape": "rect", "origin": [1000, 1000],
                                "size_mm": [1200, 1200]}]},
                 "height_mm": 1800, "place_at": [0, 0, 0]}]}
    programs["auth_stairs"] = {"ir_version": "1.0", "intent": "лестничный марш",
        "ops": [{"op": "create_stairs", "id": "S1",
                 "p0_mm": [0, 0], "p1_mm": [5000, 0],
                 "base_level": {"by": "element_id", "value": 42},
                 "top_level": {"by": "element_id", "value": 43},
                 "width_mm": 1200}]}
    # 09.08: the SECOND form of the run for the same op — the spiral one
    # (StairsRun.CreateSpiralRun). A branch the gate does not build is not
    # checked by it at all; the version axis for the spiral is the same
    # (the method exists and is identical across 2021-2026 in the
    # reference assemblies), so the expectation is six OKs, with not a
    # single exception in the EXPECTED lists.
    programs["auth_stairs_spiral"] = {"ir_version": "1.0",
        "intent": "винтовая лестница",
        "ops": [{"op": "create_stairs", "id": "S1",
                 "spiral": {"center_mm": [3000.0, 3000.0], "radius_mm": 1500.0,
                            "start_angle_deg": 0.0,
                            "included_angle_deg": 270.0, "clockwise": False},
                 "base_level": {"by": "element_id", "value": 42},
                 "top_level": {"by": "element_id", "value": 43},
                 "width_mm": 1200}]}
    # THE STAIRS WAVE (10.08.2026): a landing from a sketch — the SECOND op
    # with its own whole-program template. Two lines, not one, because the
    # contour's emission branches are DIFFERENT: a rectangle prints six
    # `Line.CreateBound` calls (`bulge == 0`), while a polygon with an arc
    # leads into `Arc.Create` from three literal points, and a branch the
    # gate does not build is not checked by it at all — the same argument
    # by which the spiral run above was set up on 09.08.
    programs["auth_stairs_landing"] = {"ir_version": "1.0",
        "intent": "промежуточная площадка лестницы",
        "ops": [{"op": "create_stairs_landing", "id": "LG1",
                 "stairs": {"by": "element_id", "value": 4242},
                 "contour": {"outer": {"shape": "rect",
                                       "origin": [5000.0, 0.0],
                                       "size_mm": [2400.0, 1200.0]}},
                 "elevation_mm": 1500.0}]}
    # THE SECOND RUN (15.08.2026). TWO programs, and the second is not for
    # symmetry: run binding is a CLOSED Revit enum, and a branch the gate
    # does not build is not checked by it at all. `center` is the default;
    # `left` proves that the member's name reaches the C# and is not just
    # the default literal.
    programs["auth_stairs_run"] = {"ir_version": "1.0",
        "intent": "второй марш существующей лестницы",
        "ops": [{"op": "create_stairs_run", "id": "RN1",
                 "stairs": {"by": "element_id", "value": 4242},
                 "p0_mm": [0.0, 0.0], "p1_mm": [3000.0, 0.0],
                 "base_elevation_mm": 1500.0}]}
    programs["auth_stairs_run_left"] = {"ir_version": "1.0",
        "intent": "марш с левой привязкой",
        "ops": [{"op": "create_stairs_run", "id": "RN1",
                 "stairs": {"by": "element_id", "value": 4242},
                 "p0_mm": [0.0, 0.0], "p1_mm": [3000.0, 0.0],
                 "base_elevation_mm": 1500.0,
                 "justification": "left"}]}
    programs["auth_stairs_landing_arc"] = {"ir_version": "1.0",
        "intent": "площадка со скруглённой гранью",
        "ops": [{"op": "create_stairs_landing", "id": "LG1",
                 "stairs": {"by": "element_id", "value": 4242},
                 "contour": {"outer": {
                     "shape": "poly",
                     "points_mm": [[5000.0, 0.0], [7400.0, 0.0],
                                   [7400.0, 1200.0], [5000.0, 1200.0]],
                     "arcs": [{"edge": 1, "bulge": 0.3}]}},
                 "elevation_mm": 1500.0}]}
    # feat/native-groups: a native Revit group (create_group). Members are
    # PRE-GROUNDED authoring ops (the component-library bridge shape); the group
    # op grounds through with no snapshot dependency (grounded=()), and the two
    # placement deltas exercise the O0+delta emission on all six versions.
    def _grp_wall(oid, x0, y0, x1, y1):
        return {"op": "create_wall", "id": oid, "p0_mm": [x0, y0],
                "p1_mm": [x1, y1],
                "level": {"__grounded__": {"id": 42, "name": None,
                                           "via": "element_id"}},
                "height_mm": 3000.0,
                "type": {"__grounded__": {"id": None, "name": None,
                                          "via": "doc_default",
                                          "in_emit": "__doc_default__"}}}
    programs["auth_native_group"] = {"ir_version": "1.0",
        "intent": "типовой этаж как нативная группа",
        "ops": [{"op": "create_group", "id": "GRP1", "name": "Типовой этаж",
                 "members": [_grp_wall("W1", 30000, 23000, 36000, 23000),
                             _grp_wall("W2", 36000, 23000, 36000, 27000)],
                 "placements": [[0, 0, 6600], [0, 0, 13200]]}]}
    programs["mod_setparam_delete"] = {"ir_version": "1.0",
        "intent": "параметр + удаление", "allow_destructive": True,
        "ops": [
            {"op": "create_level", "id": "L1", "elev_mm": 12000, "name": "Тех"},
            {"op": "set_param", "id": "S1", "target": {"by": "ref", "value": "L1"},
             "param": "Комментарии", "value": "создан KIR"},
            {"op": "set_param", "id": "S2",
             "target": {"by": "element_id", "value": 7777},
             "param": "Смещение снизу", "value": {"value": 250, "unit": "mm"}},
            {"op": "delete", "id": "D1",
             "target": {"by": "element_id", "value": 8888}},
        ]}
    programs["auth_contour_arc"] = {"ir_version": "1.0", "intent": "контур с дугой",
        "ops": [{"op": "create_floor_by_contour", "id": "F1",
                 "contour": {"outer": {"shape": "poly",
                                       "points_mm": [[0,0],[8000,0],[8000,6000],[0,6000]],
                                       "arcs": [{"edge": 1, "radius_mm": 5000}]}},
                 "level": {"by": "element_id", "value": 42}}]}
    # CONTOUR through the round trip (28.07): a contour with an ARC and an
    # OFFSET FROM THE LEVEL — exactly the form the elevator now builds for
    # arced floors. The offset appears on 107 of 155 such floors in
    # "demo-v3," so the parameter's branch must compile on all six
    # versions, not only in the emission test.
    programs["auth_contour_arc_offset"] = {"ir_version": "1.0",
        "intent": "дуговой контур со смещением от уровня",
        "ops": [{"op": "create_floor_by_contour", "id": "F1",
                 "contour": {"outer": {"shape": "poly",
                                       "points_mm": [[13012.5, 58950.0],
                                                     [21287.0, 58950.0],
                                                     [14544.7, 55088.2]],
                                       "arcs": [{"edge": 2, "bulge": 0.2874}]}},
                 "level": {"by": "element_id", "value": 42},
                 "height_offset_mm": -700.0}]}
    programs["auth_pipe_system_tee"] = {"ir_version": "1.0", "intent": "тройник",
        "ops": [{"op": "create_pipe_system", "id": "SYS1", "level": {"by": "element_id", "value": 42},
                 "diameter_mm": 100,
                 "nodes": [{"id": "T", "xyz_mm": [0, 0, 0]}, {"id": "A", "xyz_mm": [3000, 0, 0]},
                           {"id": "B", "xyz_mm": [-3000, 0, 0]}, {"id": "C", "xyz_mm": [0, 3000, 0]}],
                 "segments": [{"from": "T", "to": "A"}, {"from": "T", "to": "B"}, {"from": "T", "to": "C"}]}]}
    from kir.tests.test_golden import PROGRAMS as _GP
    programs["auth_full_house"] = _GP["full_house_v1"]
    # wave/mep (2026-07-17): route_pipe_system / route_duct_system gate
    # coverage beyond the two golden programs (already included via PROGRAMS
    # above: route_pipe_system_riser_branch, route_duct_system_tee). Adds the
    # ring topology (CONNECT checklist's "кольцо — если домен допускает") and
    # a duct tee, so the 6-version gate exercises both fitting types
    # (elbow/tee) on BOTH domains, not just pipe.
    programs["auth_route_pipe_ring"] = {"ir_version": "1.0", "intent": "кольцевая сеть ВК",
        "ops": [{"op": "route_pipe_system", "id": "SYSR",
                 "level": {"by": "element_id", "value": 42}, "diameter_mm": 100,
                 "nodes": [{"id": "R1", "xyz_mm": [0, 0, 3000]}, {"id": "R2", "xyz_mm": [4000, 0, 3000]},
                           {"id": "R3", "xyz_mm": [4000, 4000, 3000]}, {"id": "R4", "xyz_mm": [0, 4000, 3000]}],
                 "segments": [{"from": "R1", "to": "R2"}, {"from": "R2", "to": "R3"},
                              {"from": "R3", "to": "R4"}, {"from": "R4", "to": "R1"}]}]}
    programs["auth_route_duct_chain"] = {"ir_version": "1.0", "intent": "магистраль ОВ",
        "ops": [{"op": "route_duct_system", "id": "SYSD",
                 "level": {"by": "element_id", "value": 42},
                 "nodes": [{"id": "D1", "xyz_mm": [0, 0, 3000]}, {"id": "D2", "xyz_mm": [6000, 0, 3000]},
                           {"id": "D3", "xyz_mm": [6000, 0, 2950]}],
                 "segments": [{"from": "D1", "to": "D2", "diameter_mm": 400},
                              {"from": "D2", "to": "D3", "diameter_mm": 200,
                               "slope_min_pct": 1.0}]}]}
    # fix/mep-fittings (2026-07-17): the exact live-semantic-test failure
    # shape — a straight (collinear) riser continuation used to force an
    # elbow onto a node with nothing to bend, and Revit refused at runtime
    # ("failed to insert elbow"). These two programs put the fixed
    # classify_junction branches ("connect" via Connector.ConnectTo, and
    # "transition" via NewTransitionFitting) through the real 6-version
    # compile gate, not just the offline unit/golden corpus — proving the
    # emit itself still compiles on every version with the new branches
    # live. auth_route_pipe_ring/auth_route_duct_chain above stay as the
    # pre-existing bend/branch coverage, unaffected by this fix.
    programs["auth_route_pipe_straight_riser"] = {
        "ir_version": "1.0", "intent": "прямой стояк ВК без изгиба (ConnectTo, не отвод)",
        "ops": [{"op": "route_pipe_system", "id": "SYSS",
                 "level": {"by": "element_id", "value": 42}, "diameter_mm": 100,
                 "nodes": [{"id": "S1", "xyz_mm": [0, 0, 0]}, {"id": "S2", "xyz_mm": [0, 0, 6000]},
                           {"id": "S3", "xyz_mm": [0, 0, 12000]}],
                 "segments": [{"from": "S1", "to": "S2"}, {"from": "S2", "to": "S3"}]}]}
    programs["auth_route_duct_straight_transition"] = {
        "ir_version": "1.0", "intent": "прямой переход диаметра ОВ на стыке (NewTransitionFitting)",
        "ops": [{"op": "route_duct_system", "id": "SYST",
                 "level": {"by": "element_id", "value": 42},
                 "nodes": [{"id": "S1", "xyz_mm": [0, 0, 3000]}, {"id": "S2", "xyz_mm": [5000, 0, 3000]},
                           {"id": "S3", "xyz_mm": [10000, 0, 3000]}],
                 "segments": [{"from": "S1", "to": "S2", "diameter_mm": 400},
                              {"from": "S2", "to": "S3", "diameter_mm": 250}]}]}
    # Curtain wall panels (design 2026-07-28). The gate must compile BOTH
    # forms of the host (a ref to the wall from this same program, and a
    # pinned element_id — the design writes `host: ref|element_id`) and
    # BOTH forms of the type selector (a name, which the emitter resolves
    # with a collector across two type namespaces, and a pinned
    # element_id). Address (0,0) is not "empty" but a 1×1 grid: exactly
    # the special case the design forbade treating as an excuse for
    # having no address.
    programs["auth_curtain_cell_grid"] = {"ir_version": "1.0",
        "intent": "витраж: разные типы в ячейках сетки существующей стены",
        "ops": [
            {"op": "set_curtain_panel", "id": "CP1",
             "host": {"by": "element_id", "value": 8145901}, "u": 0, "v": 0,
             "panel_type": {"by": "element_id", "value": 273445}},
            {"op": "set_curtain_panel", "id": "CP2",
             "host": {"by": "element_id", "value": 8145901}, "u": 2, "v": 1,
             "panel_type": {"by": "name", "value": "Стена НР_ВТ 200мм"}},
            {"op": "set_curtain_panel", "id": "CP3",
             "host": {"by": "element_id", "value": 8145901}, "u": 3, "v": 0,
             "panel_type": {"by": "name", "value": "Пустая панель"}},
        ]}
    # Curtain-wall grid lines (wave of 29.07): the gate must compile both
    # forms of the host (a ref to the wall from this same program, and a
    # pinned element_id) and BOTH directions — isUGridLine on AddGridLine
    # is a boolean, and a swapped branch is invisible except in the live
    # model.
    # RELATE, ADDRESS (wave of 09.08). The gate must run BOTH families of
    # nodes on all six versions, and here is exactly why the gate matters:
    # the address is resolved at compile time into a LITERAL, so a defect
    # in the resolver does not look like a compile error but like C# THAT
    # COMPILES CORRECTLY WITH THE WRONG NUMBER. The only thing the gate
    # proves here is that the path "address -> number -> emission" runs
    # through to the end on 2021-2026; WHICH number was derived is held by
    # the tests (`test_relate.py`, a byte-for-byte check against the
    # hand-built variant).
    #
    # The program is deliberately chained: the columns are addressed FROM
    # THE GRIDS, the beam FROM THE COLUMNS, the second wall FROM THE END OF
    # THE FIRST. Not a single coordinate of the beam or the joint appears
    # in the text, and that is the entire point of the measurement.
    programs["auth_address_grid_and_element"] = {"ir_version": "1.0",
        "intent": "адрес: колонны от осей, балка по верху колонн, стык стен",
        "ops": [
            {"op": "create_column", "id": "AC1", "xy": {"at_grid": ["1", "А"]},
             "level": {"by": "element_id", "value": 42},
             "top_level": {"by": "element_id", "value": 43},
             "symbol": {"by": "element_id", "value": 500}},
            {"op": "create_column", "id": "AC2",
             "xy": {"at_grid": [{"grid": "2", "offset_mm": 200,
                                 "toward": "1"}, "А"]},
             "level": {"by": "element_id", "value": 42},
             "top_level": {"by": "element_id", "value": 43},
             "symbol": {"by": "element_id", "value": 500}},
            {"op": "create_beam", "id": "AB1",
             "p0_mm": {"at_element": {"by": "ref", "value": "AC1"},
                       "point": "center", "z": "top"},
             "p1_mm": {"at_element": {"by": "ref", "value": "AC2"},
                       "point": "center", "z": "top"},
             "level": {"by": "element_id", "value": 43},
             "symbol": {"by": "element_id", "value": 1100}},
            {"op": "create_wall", "id": "AW1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "height_mm": 3000,
             "level": {"by": "element_id", "value": 42}},
            {"op": "create_wall", "id": "AW2",
             "p0_mm": {"at_element": {"by": "ref", "value": "AW1"},
                       "point": "end"},
             "p1_mm": [6000, 4500], "height_mm": 3000,
             "level": {"by": "element_id", "value": 42}},
        ]}
    # wave/shape: free-form geometry via a mesh. The mesh is generated by
    # MATH right here (a twisted tower), not brought in as a list of
    # literals: the gate must run the same form used live and stay
    # readable. 16 faces × 12 floors plus a cap and a base = 416 triangles
    # — a tenth of the measured MAX_TRIANGLES=4096 limit.
    def _twisted_tower_mesh(sides=16, storeys=12, r0=6000.0, r1=3500.0,
                            h=36000.0, twist=140.0):
        verts, tris = [], []
        for k in range(storeys + 1):
            f = k / storeys
            r = r0 + (r1 - r0) * f
            a0 = math.radians(twist * f)
            for j in range(sides):
                a = a0 + 2 * math.pi * j / sides
                verts.append([r * math.cos(a), r * math.sin(a), h * f])
        for k in range(storeys):
            for j in range(sides):
                a, b = k * sides + j, k * sides + (j + 1) % sides
                c, d = (k + 1) * sides + j, (k + 1) * sides + (j + 1) % sides
                tris += [[a, b, d], [a, d, c]]
        bot = len(verts); verts.append([0.0, 0.0, 0.0])
        top = len(verts); verts.append([0.0, 0.0, h])
        for j in range(sides):
            tris.append([bot, (j + 1) % sides, j])
            tris.append([top, storeys * sides + j,
                         storeys * sides + (j + 1) % sides])
        return verts, tris

    _ds_verts, _ds_tris = _twisted_tower_mesh()
    # wave/solid (09.08): a parametric solid. THREE programs, because
    # emission has three optional branches, and the gate must build every
    # one: a base elevation involves a contour transform, an arc in the
    # profile involves the Arc.Create branch, a full revolution changes the
    # expected end-face area to zero. A gate that built one branch out of
    # three would be "an instrument covering part of the range."
    programs["auth_solid_extrusion_plain"] = {
        "ir_version": "1.0", "intent": "выдавленное тело",
        "ops": [{"op": "create_solid_extrusion", "id": "SE1",
                 "profile": {"outer": {"shape": "rect", "origin": [0, 0],
                                       "size_mm": [4000, 3000]}},
                 "height_mm": 2500, "category": "generic_model",
                 "name": "призма"}]}
    programs["auth_solid_extrusion_arc_holes"] = {
        "ir_version": "1.0", "intent": "выдавливание с дугой, проёмами и отметкой",
        "ops": [{"op": "create_solid_extrusion", "id": "SE2",
                 "profile": {
                     "outer": {"shape": "poly",
                               "points_mm": [[0, 0], [6000, 0], [6000, 4000],
                                             [0, 4000]],
                               "arcs": [{"edge": 1, "bulge": 0.4}]},
                     "holes": [{"shape": "rect", "origin": [1000, 1000],
                                "size_mm": [1200, 1200]},
                               {"shape": "rect", "origin": [3000, 1500],
                                "size_mm": [900, 900]}]},
                 "height_mm": 1800, "base_z_mm": 3300, "category": "mass",
                 "name": "плита с проёмами"}]}
    # wave/mass (10.08): a wall on a sloped mass face. TWO programs,
    # because host resolution has TWO branches, and the gate must build
    # both: a mass that is ALREADY STANDING (`element_id` — the main
    # scenario), and a mass placed by this same program (`ref` to
    # place_family). A gate that built one branch out of two would be "an
    # instrument covering part of the range."
    programs["auth_face_wall_placed_mass"] = {
        "ir_version": "1.0", "intent": "стена по скату размещённой массы",
        "ops": [{"op": "place_family", "id": "M1",
                 "symbol": {"by": "family_type", "category": "OST_Furniture",
                            "family_name": "Стол офисный",
                            "type_name": "Стол 1200"},
                 "xyz": [1000, 2000, 0],
                 "level": {"by": "name", "value": "Этаж 1"}},
                {"op": "create_face_wall", "id": "FW2",
                 "host": {"by": "ref", "value": "M1"},
                 "face_normal": [0.0, -0.5, 0.5],
                 "location_line": "wall_centerline",
                 "type": {"by": "name", "value": "ЖБ 200"}}]}
    programs["auth_solid_revolves"] = {
        "ir_version": "1.0", "intent": "тело вращения: сектор и полный оборот",
        "ops": [{"op": "create_solid_revolve", "id": "SR1",
                 "profile": {"outer": {"shape": "rect", "origin": [1000, 0],
                                       "size_mm": [800, 2400]}},
                 "axis_xy_mm": [5000, 4000], "sweep_deg": 270,
                 "category": "generic_model", "name": "сектор кольца"},
                {"op": "create_solid_revolve", "id": "SR2",
                 "profile": {
                     "outer": {"shape": "poly",
                               "points_mm": [[600, 0], [2000, 0], [2000, 500],
                                             [1200, 500], [1200, 3000],
                                             [600, 3000]]},
                     "holes": [{"shape": "rect", "origin": [800, 1000],
                                "size_mm": [300, 800]}]},
                 "axis_xy_mm": [20000, 0], "sweep_deg": 360, "base_z_mm": -1500,
                 "category": "site", "name": "колонна вращения"}]}
    programs["auth_floor_holes"] = {"ir_version": "1.0", "intent": "плита с проёмом",
        "ops": [{"op": "create_floor", "id": "F1",
                 "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
                 "holes": [[[3000, 2000], [5000, 2000], [5000, 4000], [3000, 4000]]],
                 "level": {"by": "name", "value": "Этаж 1"}}]}
    # Documentation family (ops_annotation.py): create_dimension/create_tag/
    # create_text had ZERO live 6-version compile coverage before 28.07 — the
    # per_op gate finding that closed the in_view:{by:ref} CS0039 hole (see
    # expected_refusals below) surfaced that this whole op family had never
    # been driven through the real compile service, atomic OR per_op, at
    # all. in_view here stays element_id (the only legal form after the fix).
    # host: element_id (28.07, audit's most frequent external scenario:
    # «поставь окно в МОЮ стену»). No wall op in this program on purpose —
    # the whole point is a host the program never creates. Runtime frame
    # (doc.GetElement(...) as Wall, LocationCurve, Curve.Evaluate(t, true))
    # goes through the live 6-version compile gate here, atomic AND per_op
    # (the per_op axis below), same bar as everything else in this table.
    # No expected-refusal entry needed: element_id is now a legal host.
    programs["auth_hosted_element_id"] = {"ir_version": "1.0",
        "intent": "дверь и окно на чужой стене (host по element_id)",
        "ops": [
            {"op": "create_door", "id": "D1",
             "host": {"by": "element_id", "value": 8145901},
             "offset_mm": 1500, "sill_mm": -100,
             "symbol": {"by": "name", "value": "Дверь 900x2100"}},
            {"op": "create_window", "id": "Win1",
             "host": {"by": "element_id", "value": 8145901},
             "offset_mm": 3000, "sill_mm": 900,
             "symbol": {"by": "name", "value": "Окно 1200x1500"}},
        ]}
    # A8 (13.08.2026): A SYMBOL CREATED BY THIS SAME PROGRAM IS CONSUMED BY
    # THAT SAME PROGRAM.
    #
    # Before this fix, `family_symbol` was the ONE AND ONLY reference kind
    # in the entire language that had producers and ZERO consumers:
    # produced by 2 ops (`create_type`, `load_family`), consumed by none.
    # The three other kinds are each consumed by dozens (`level` 33,
    # `element` 16, `wall` 7) — meaning this was not "thin coverage" but an
    # UNCLOSED EDGE in the language's graph, and it could only be seen by a
    # census of producers against consumers.
    #
    # The consequence was not academic: a building could not be authored
    # in a document where its catalog does not yet exist. The `KIR-G104`
    # refusal ("pool is empty") could not name an executable next move,
    # because loading a family and referencing it within one program was
    # NOT POSSIBLE.
    #
    # The program below is proof that it now is, and it sits in the gate
    # precisely because offline compilation across six versions is the
    # one thing checkable here: the live transaction (whether Revit
    # accepts a freshly loaded symbol right away) remains a charge held
    # for the live window.
    programs["auth_load_family_then_place"] = {"ir_version": "1.0",
        "intent": "загрузить семейство и поставить его экземпляр в один ход",
        "ops": [
            {"op": "load_family", "id": "LF",
             "path": "C:\\Lib\\Doors\\M_Дверь.rfa",
             "type_name": "Дверь 900x2100"},
            {"op": "create_wall", "id": "W1",
             "p0_mm": [0, 0], "p1_mm": [6000, 0], "height_mm": 3000,
             "level": {"by": "element_id", "value": 42},
             "type": {"by": "element_id", "value": 100}},
            {"op": "create_door", "id": "D1",
             "host": {"by": "ref", "value": "W1"}, "offset_mm": 2000,
             "symbol": {"by": "ref", "value": "LF"}},
        ]}
    # CLASH-починка (28.07, оператор: ранний честный релиз): move_elements +
    # change_type. targets mixes ref (this program's own wall+pipe, so
    # ElementTransformUtils.MoveElements is proven on a LocationCurve pair
    # created in the SAME transaction) with element_id (an existing
    # element); change_type runs on the same created wall, byref, proving
    # the target_w path independent of host/type selector kind.
    # auth_move_and_change_type is NOT set here: it lives in `PROGRAMS`
    # and arrives through the seed above, so the golden pins exactly the
    # program the gate compiles.
    # families_create_type_full / families_load_family_whole are NOT set
    # here any more: they live in `PROGRAMS` and arrive through the seed
    # above. Keeping a literal here too would mean the gate compiles one
    # program while the golden pins another — silently — the moment the
    # name exists in both. One source.
    # ops_families gate (wave/families, 2026-07-17): create_type (FamilySymbol
    # duplication — the exact prod incident this wave fixes, RC columns coming
    # in as steel because no create_type existed) + load_family (Document.
    # LoadFamily/LoadFamilySymbol, wiki family-load-place.md FAM-034 pattern).
    programs["families_create_type_by_name_custom_params"] = {"ir_version": "1.0",
        "intent": "тип по имени источника с нестандартными именами параметров",
        "ops": [{"op": "create_type", "id": "T1",
                 "source_type": {"by": "name", "value": "К 300x300"},
                 "category": "structural", "new_name": "К 350x300",
                 "width_mm": 350, "param_width_name": "b"}]}
    programs["families_create_type_architectural"] = {"ir_version": "1.0",
        "intent": "архитектурная колонна нового сечения",
        "ops": [{"op": "create_type", "id": "T1",
                 "source_type": {"by": "element_id", "value": 501},
                 "category": "architectural", "new_name": "Колонна 400",
                 "width_mm": 400, "param_width_name": "Width"}]}
    programs["families_type_then_setparam_ref"] = {"ir_version": "1.0",
        "intent": "тип + правка комментария к типу по intra-program ref",
        "ops": [
            {"op": "create_type", "id": "T1",
             "source_type": {"by": "element_id", "value": 500},
             "category": "structural", "new_name": "ЖБ 400x400 v2",
             "width_mm": 400, "depth_mm": 400},
            {"op": "set_param", "id": "S1", "target": {"by": "ref", "value": "T1"},
             "param": "Комментарии типа", "value": "создан KIR"},
        ]}
    programs["families_load_family_named_type"] = {"ir_version": "1.0",
        "intent": "загрузить один именованный типоразмер",
        "ops": [{"op": "load_family", "id": "F1",
                 "path": r"C:\Lib\Doors\Standard.rfa", "type_name": "0900x2100"}]}
    rnga_fam = random.Random(SEED + 2)
    _fam_sources = [({"by": "element_id", "value": 500}, "structural"),
                    ({"by": "name", "value": "К 300x300"}, "structural"),
                    ({"by": "element_id", "value": 501}, "architectural")]
    for i in range(8):
        src, cat = rnga_fam.choice(_fam_sources)
        op = {"op": "create_type", "id": "T1", "source_type": src, "category": cat,
              "new_name": f"КИР-тип-{i}", "width_mm": float(rnga_fam.randint(50, 2000))}
        if rnga_fam.random() < 0.6:
            op["depth_mm"] = float(rnga_fam.randint(50, 2000))
        if rnga_fam.random() < 0.3:
            op["material"] = rnga_fam.choice(["Бетон", "Сталь", "Дерево"])
        programs[f"families_pbt_{i}"] = {"ir_version": "1.0",
            "intent": "families pbt", "ops": [op]}
    # wave/struct (2026-07-17): create_beam + create_foundation (both
    # varieties) gate coverage. struct_beam/struct_foundation_isolated/
    # struct_foundation_slab already included above via test_golden.PROGRAMS;
    # these add the version-axis edge case (slab holes refused pre-2022,
    # mirrors auth_floor_holes/auth_contour_l) plus a mixed authoring program
    # (beam + isolated footing sharing one txn/level, the realistic "колонна
    # + фундамент + балка" combo) and PBT coverage.
    programs["struct_foundation_slab_holes_2021"] = {"ir_version": "1.0",
        "intent": "плитный фундамент с проёмом (версионная граница)",
        "ops": [{"op": "create_foundation", "id": "F1", "variety": "slab",
                 "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
                 "holes": [[[3000, 2000], [5000, 2000], [5000, 4000], [3000, 4000]]],
                 "level": {"by": "name", "value": "Этаж 1"}}]}
    programs["struct_beam_and_isolated_footing"] = {"ir_version": "1.0",
        "intent": "колонна: фундамент + балка на одном уровне",
        "ops": [
            {"op": "create_foundation", "id": "F1", "variety": "isolated",
             "xy": [0, 0], "level": {"by": "element_id", "value": 42}},
            {"op": "create_foundation", "id": "F2", "variety": "isolated",
             "xy": [6000, 0], "level": {"by": "element_id", "value": 42}},
            {"op": "create_beam", "id": "B1", "p0_mm": [0, 0, 3000],
             "p1_mm": [6000, 0, 3000], "level": {"by": "element_id", "value": 42}},
        ]}
    # wave/wall-foundation (2026-08-09): struct_wall_foundation already
    # arrived above from test_golden.PROGRAMS and carries both host
    # branches. Here is what the reference cannot provide: a CHAIN of
    # several walls with their own footings in one transaction (each op
    # has its own host variable and its own witness — this is exactly how
    # a name collision between neighbors is caught, invisible in a
    # single-op program).
    programs["struct_wall_foundation_chain"] = {"ir_version": "1.0",
        "intent": "ленты под тремя стенами одной программой",
        "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [9000, 0],
             "level": {"by": "element_id", "value": 42}},
            {"op": "create_wall", "id": "W2", "p0_mm": [9000, 0], "p1_mm": [9000, 6000],
             "level": {"by": "element_id", "value": 42}},
            {"op": "create_wall_foundation", "id": "WF1",
             "wall": {"by": "ref", "value": "W1"},
             "type": {"by": "name", "value": "Ленточный 600x300"}},
            {"op": "create_wall_foundation", "id": "WF2",
             "wall": {"by": "ref", "value": "W2"}},
            {"op": "create_wall_foundation", "id": "WF3",
             "wall": {"by": "element_id", "value": 8145901},
             "type": {"by": "name", "value": "Ленточный 900x400"}},
        ]}
    # wave/framing (2026-08-09): a beam system and a truss. Neither has a
    # version axis (all four BeamSystem.Create overloads and the single
    # Truss.Create signature compile 6/6), so here the gate guards not a
    # version fork but what the reference cannot provide: an ARCED profile
    # (a Python-side fork on bulge inside a single emission) and SEVERAL
    # operations of one wave in one transaction — this is exactly how a
    # name collision between neighbors is caught, invisible in a
    # single-op program.
    programs["struct_beam_system_arc_profile"] = {"ir_version": "1.0",
        "intent": "балочная система по дуговому эскизу",
        "ops": [{"op": "create_beam_system", "id": "BS1",
                 "profile": {"outer": {"shape": "poly",
                                       "points_mm": [[0, 0], [9000, 0],
                                                     [9000, 6000], [0, 6000]],
                                       "arcs": [{"edge": 1, "radius_mm": 8000}]}},
                 "direction_edge": 0,
                 "level": {"by": "name", "value": "Этаж 1"},
                 "symbol": {"by": "name", "value": "Балка 200x400"}}]}
    # wave/reinforcement (2026-08-10): area reinforcement. It has no
    # version axis (both AreaReinforcement.Create overloads compile 6/6),
    # so here the gate guards not a version fork but exactly what a
    # single-op program cannot provide: BOTH forms of the host (a ref to a
    # slab from this same program and an element_id to one already
    # standing), BOTH branches of the type (document default and
    # by:name), both branches of the hook (omitted = no hooks, and
    # by:name), and SEVERAL such ops in one transaction — this is how a
    # name collision between neighbors is caught.
    rnga_reinf = random.Random(SEED + 7)
    for i in range(4):
        # THE ANGLE IS RANDOM, AND OUTSIDE 0..360 TOO. Direction is
        # periodic, it deliberately has no bounds in the registry, and
        # emission must print finite cos/sin for any input: an angle of
        # 725° or -30° are both legitimate programs.
        programs[f"struct_area_reinforcement_pbt_{i}"] = {"ir_version": "1.0",
            "intent": "армирование по области pbt",
            "ops": [{"op": "create_area_reinforcement", "id": "AR1",
                     "host": {"by": "element_id",
                              "value": rnga_reinf.randint(1000, 9_000_000)},
                     "direction_deg": rnga_reinf.uniform(-720.0, 720.0),
                     "bar_type": {"by": "element_id", "value": 1902}}]}
    rnga_framing = random.Random(SEED + 5)
    for i in range(6):
        x0 = rnga_framing.randint(-50000, 50000)
        if rnga_framing.random() < 0.5:
            w = rnga_framing.randint(2000, 20000)
            h = rnga_framing.randint(2000, 20000)
            programs[f"struct_beam_system_pbt_{i}"] = {"ir_version": "1.0",
                "intent": "балочная система pbt",
                "ops": [{"op": "create_beam_system", "id": "BS1",
                         "profile": {"outer": {"shape": "rect",
                                               "origin": [x0, x0],
                                               "size_mm": [w, h]}},
                         "level": {"by": "element_id", "value": 42}}]}
        else:
            programs[f"struct_truss_pbt_{i}"] = {"ir_version": "1.0",
                "intent": "ферма pbt",
                "ops": [{"op": "create_truss", "id": "TR1",
                         "p0_mm": [x0, x0],
                         "p1_mm": [x0 + rnga_framing.randint(3000, 30000), x0],
                         "level": {"by": "element_id", "value": 42}}]}
    rnga_struct = random.Random(SEED + 3)
    for i in range(8):
        x0 = rnga_struct.randint(-50000, 50000)
        z0 = rnga_struct.randint(0, 4000)
        if rnga_struct.random() < 0.5:
            programs[f"struct_beam_pbt_{i}"] = {"ir_version": "1.0", "intent": "балка pbt",
                "ops": [{"op": "create_beam", "id": "B1",
                         "p0_mm": [x0, x0, z0],
                         "p1_mm": [x0 + rnga_struct.randint(1000, 15000), x0, z0],
                         "level": {"by": "element_id", "value": 42}}]}
        else:
            w = rnga_struct.randint(2000, 20000)
            h = rnga_struct.randint(2000, 20000)
            programs[f"struct_foundation_pbt_{i}"] = {"ir_version": "1.0", "intent": "фундамент pbt",
                "ops": [{"op": "create_foundation", "id": "F1", "variety": "slab",
                         "outline": [[x0, x0], [x0 + w, x0], [x0 + w, x0 + h], [x0, x0 + h]],
                         "level": {"by": "element_id", "value": 42}}]}
    rnga = random.Random(SEED + 1)
    from kir.tests.test_authoring import NASTY
    for i in range(8):
        x0 = rnga.randint(-50000, 50000)
        programs[f"auth_pbt_{i}"] = _prog([
            _wall(oid=f"W{j}", p0_mm=[x0, j * 3000], p1_mm=[x0 + 5000, j * 3000],
                  height_mm=rnga.randint(1000, 6000))
            for j in range(rnga.randint(1, 4))
        ], intent=rnga.choice(NASTY))

    def _needs_snapshot(p: dict) -> bool:
        """By op FAMILY over the EXPANDED op list — macros hide pool-needing
        ops (a stack's pipes), so detection must run post-expansion; and never
        by program name (the checkpoint-return lesson)."""
        from kir import macros as _macros
        ops = p.get("ops", [])
        try:
            ops = _macros.expand(ops)
        except Exception:
            pass          # compiler will refuse; no snapshot decision needed
        for o in ops if isinstance(ops, list) else []:
            os_ = spec.OPS.get(o.get("op")) if isinstance(o, dict) else None
            if os_ is not None and os_.family in spec.WRITE_FAMILIES:
                return True
        return False

    # per_op axis (promoted from the scratch gate_per_op.py prototype,
    # 28.07): the atomic-only loop below left every emitter's per_op branch
    # — the SubTransaction wrapper closing over an emitter's own locals,
    # exactly the shape that produced the load_family CS0136 __ok_<s>
    # collision — compiled ZERO times by this gate; the only place per_op
    # ever ran live was a real A5/bulk rebuild. A KNOWN, already-tracked
    # per_op-only defect (fix pending, not yet landed) is counted as an
    # EXPECTED regression here — visible in the printed row, added to
    # known_gaps, and EXCLUDED from `failures` — never a silent green hole
    # (name not in the dict) and never an untracked plain failure (name in
    # the dict but still counted against the pass/fail bit).
    PER_OP_KNOWN_GAPS: dict[str, str] = {
        # name -> reason. Empty by construction (28.07): the two per_op
        # defects this same wave's per_op gate found — load_family CS0136
        # __ok_<s> collision, in_view:{by:ref} CS0039 — are BOTH fixed. This
        # dict is the mechanism for the NEXT one, not a resting place for
        # old bugs already closed.
    }
    #: Programs whose ops honestly REFUSE on 2024-2026 (see below). Names,
    #: not a "the program has a load" flag: the list must be readable by
    #: eye, exactly like the neighboring ceiling list.
    ANALYSIS_LOAD_PROGRAMS = frozenset({"analysis_loads"})

    checks = 0
    known_gaps = 0
    failures = 0
    sized_cable_tray_branch_checks = 0
    #: Bodies the Roslyn service actually answered about. DERIVED from the
    #: calls themselves (`_compile_check` below is the only door), never
    #: incremented beside an attempt — so a check that is skipped cannot
    #: inflate it. `checks` counts ATTEMPTS and the two differ by exactly
    #: `not_compiled`; the summary prints all three, because a number that
    #: cannot tell "passed" from "never attempted" is not a measurement.
    compiled = 0
    #: reason -> how many attempts ended without any C# reaching Roslyn.
    #: A skipped check is a named category in the summary, never absent.
    not_compiled: dict[str, int] = {}

    def _skip(reason: str) -> None:
        not_compiled[reason] = not_compiled.get(reason, 0) + 1

    async def _compile_check(wrapped: str, ver: str):
        """The ONLY path to the compile service, so `compiled` cannot lie."""
        nonlocal compiled
        res = await client.check(wrapped, ver)
        if res is None:
            _skip("compile-service-no-answer")
        else:
            compiled += 1
        return res

    async def _gate_row(name: str, prog: dict, snapshot, isolation: str) -> list[str]:
        nonlocal checks, known_gaps, failures, sized_cable_tray_branch_checks
        row: list[str] = []
        for ver in spec.REVIT_VERSIONS:
            checks += 1
            out = compile_program(prog, revit_version=ver,
                                  snapshot=snapshot,
                                  isolation=isolation)   # per-version emit (SPEC 11.2)
            # wave/arch: the CEILING's refusal on 2021 is not "a known
            # hole" but the correct answer. Ceiling.Create appeared in
            # 2022, and doc.Create.NewCeiling does not exist on any of the
            # six versions (measured by compilation), so there is nothing
            # to build a ceiling with on 2021. The gate must distinguish
            # "the operation honestly said it does not exist on this
            # version" from "emission broke": without this line, a green
            # gate would require the op to silently build something else
            # instead — exactly the Goodhart effect this refusal was set
            # up to fight.
            if ver < E003_EXPECTED_BELOW.get(name, "2021") \
                    and not out.ok \
                    and any(d.code == "KIR-E003" for d in out.diagnostics):
                row.append(f"{ver}:E003-EXPECTED")
                _skip("e003-expected-refusal")
                continue
            # wave/analysis (09.08): the same idea, but the version axis
            # points IN THE OTHER DIRECTION. A free (unhosted) load
            # EXISTS on 2021-2023 and was removed by Autodesk from the API
            # in 2024 (measured: overloads without `ElementId hostElemId`
            # give CS1503/CS1501 on all three newer versions). The
            # refusal on 2024-2026 is the operation's correct answer, not
            # broken emission, and the gate must tell these apart.
            if not out.ok and name in ANALYSIS_LOAD_PROGRAMS and ver >= "2024" \
                    and any(d.code == "KIR-E003" for d in out.diagnostics):
                row.append(f"{ver}:E003-EXPECTED")
                _skip("e003-expected-refusal")
                continue
            if not out.ok:
                if name in PER_OP_KNOWN_GAPS:
                    row.append(f"{ver}:KNOWN-GAP")
                    known_gaps += 1
                    _skip("known-gap-refusal")
                    continue
                print(f"FAIL {name}@{ver} [{isolation}]: KIR refused: "
                      f"{[d.code for d in out.diagnostics][:3]}")
                failures += 1
                row.append(f"{ver}:REFUSED")
                _skip("compiler-refused")
                continue
            if name == SIZED_CABLE_TRAY_GATE_NAME:
                if not sized_cable_tray_branch_reached(out.csharp):
                    print(f"FAIL {name}@{ver} [{isolation}]: sized cable-tray "
                          "emitter branch was not reached")
                    failures += 1
                    row.append(f"{ver}:BRANCH?")
                    _skip("emitter-branch-not-reached")
                    continue
                sized_cable_tray_branch_checks += 1
            wrapped = wrap_user_code(out.csharp)
            res = await _compile_check(wrapped, ver)
            if res is None:
                row.append(f"{ver}:SVC?")
                failures += 1
            elif res.success:
                row.append(f"{ver}:OK")
            elif name in PER_OP_KNOWN_GAPS:
                row.append(f"{ver}:KNOWN-GAP")
                known_gaps += 1
                for e in res.errors[:3]:
                    print(f"    {name} @{ver} [{isolation}, known gap: "
                          f"{PER_OP_KNOWN_GAPS[name]}] {e.code} L{e.line}: "
                          f"{e.message[:100]}")
            else:
                row.append(f"{ver}:FAIL")
                failures += 1
                for e in res.errors[:3]:
                    print(f"    {name} @{ver} [{isolation}] {e.code} L{e.line}: "
                          f"{e.message[:100]}")
        return row

    write_program_count = 0
    # Grounding is a property of THE GATE, not only of the suite (found
    # by the SUITE zone on 12.08). Everything that requires a snapshot is
    # grounded against the FIXTURE, so every such "OK" is a claim about
    # the fixture, not about a real document. We compute the share here so
    # it can be printed alongside the count, not left in anyone's memory.
    program_compilations = 0
    fixture_grounded = 0
    # SECOND STRIP. The corpus is read ONCE: 73 profiles cost ~1 s, and
    # inside the loop this would become a cost growing with the number of
    # programs — form 10.
    real_profiles = load_real_profiles()
    real_grounded = 0
    real_remainder: list[tuple[str, str]] = []
    # THE UNIT OF THE DENOMINATOR. `fixture_grounded` counts COMPILATIONS
    # (a writing program appears twice: atomic and per_op), while the
    # second strip counts PROGRAMS. Dividing one by the other means adding
    # different units — a named defect of this tree. So the second strip
    # has its own program counter.
    snapshot_programs = 0
    for name, prog in programs.items():
        needs_snapshot = _needs_snapshot(prog)
        snapshot = GROUND_SNAPSHOT if needs_snapshot else None
        program_compilations += 1
        if needs_snapshot:
            fixture_grounded += 1
        atomic_row = await _gate_row(name, prog, snapshot, "atomic")
        print(f"{name:24s} {' '.join(atomic_row)}")
        # A real document is a SEPARATE question, and its "OK" does not
        # replace the fixture's: a program can compile on all six and
        # have not a single building it can be grounded against. We count
        # both.
        if needs_snapshot and real_profiles:
            snapshot_programs += 1
            real = ground_on_real_document(prog, real_profiles)
            if isinstance(real, tuple):
                real_run, real_snapshot = real
                real_grounded += 1
                real_row = await _gate_row(
                    name, prog, real_snapshot, "atomic")
                print(f"{name + '@' + real_run:24.24s} {' '.join(real_row)}")
            else:
                real_remainder.append((name, real))
        # per_op is only a DIFFERENT emission for write-family programs (the
        # query/read path ignores isolation entirely — compiling it twice
        # would be redundant, not honest new coverage). `_needs_snapshot`
        # already computes exactly this predicate (post-macro-expansion, by
        # op family, never by program name — same discipline as its own
        # docstring), so it doubles as the per_op eligibility check.
        if needs_snapshot:
            write_program_count += 1
            program_compilations += 1
            fixture_grounded += 1
            per_op_row = await _gate_row(
                name, prog, snapshot, "per_op")
            print(f"{name + '_per_op':24s} {' '.join(per_op_row)}")

    expected_sized_tray_checks = len(spec.REVIT_VERSIONS) * 2
    if sized_cable_tray_branch_checks != expected_sized_tray_checks:
        print("FAIL sized cable-tray gate coverage: "
              f"{sized_cable_tray_branch_checks}/"
              f"{expected_sized_tray_checks} branch emissions")
        failures += 1

    # Expected-refusal gate: valuable invariants proven in CI, not left to be
    # accidental failures. (coordinator return, 2026-07-16)
    expected_refusals = {
        "auth_no_snapshot": (_prog([_wall()], intent="без снапшота"), None, "KIR-G103"),
        # 28.07 per_op gate finding: in_view:{by:ref} used to compile
        # (ok=True) into a GUARANTEED Roslyn CS0039.  Forward-reference
        # compatibility is now a typed-IR responsibility, so the invalid
        # non-referenceable view input must stop at KIR-T001 before grounding
        # or emission (also pinned in test_result_semantics.py).
        # The MEP wave, 09.08. Coincident points on a flexible run are a
        # refusal AT COMPILE TIME, not at the witness: Autodesk documents
        # that Revit DISCARDS such points, meaning it would build a run
        # with a different number of points. The witness would catch this
        # as a consequence, but the diagnosis would say "geometry did not
        # match"; the cause is visible earlier, and the gate holds
        # exactly that.
        "auth_flex_duplicate_point_refused": (
            {"ir_version": "1.0", "intent": "гибкая труба с совпадающими точками",
             "ops": [{"op": "create_flex_pipe", "id": "FPX",
                      "path": [[0, 0, 3000], [0, 0, 3000], [1000, 0, 3000]],
                      "level": {"by": "element_id", "value": 42}}]},
            GROUND_SNAPSHOT, "KIR-T002"),
        # RELATE, address from an element (09.08). A column's top WITHOUT
        # `top_level` is undefined in the program: the height comes from a
        # type the program does not know. The refusal must be OFFLINE and
        # typed — silently taking "bottom + something" would place the
        # beam at an elevation the witness would accept (it checks against
        # the same number).
        "auth_address_element_unbound_top_refused": (
            {"ir_version": "1.0", "intent": "балка по верху неприкреплённой колонны",
             "ops": [
                 {"op": "create_column", "id": "UC1", "xy": [0, 0],
                  "level": {"by": "element_id", "value": 42},
                  "symbol": {"by": "element_id", "value": 500}},
                 {"op": "create_beam", "id": "UB1",
                  "p0_mm": {"at_element": {"by": "ref", "value": "UC1"},
                            "point": "center", "z": "top"},
                  "p1_mm": [4000, 0, 3300],
                  "level": {"by": "element_id", "value": 42},
                  "symbol": {"by": "element_id", "value": 1100}}]},
            GROUND_SNAPSHOT, "KIR-G115"),
        "auth_in_view_ref_refused": (
            _prog([_wall(), {"op": "create_tag", "id": "TAG1",
                             "in_view": {"by": "ref", "value": "W1"},
                             "target": {"by": "ref", "value": "W1"},
                             "at": [3000, 800]}], intent="in_view ref"),
            GROUND_SNAPSHOT, "KIR-T001"),
    }
    for name, (prog, snap, want_code) in expected_refusals.items():
        out = compile_program(prog, revit_version="2026", snapshot=snap)
        codes = [d.code for d in out.diagnostics]
        if not out.ok and want_code in codes:
            print(f"{name:24s} EXPECTED-REFUSAL:{want_code} OK")
        else:
            print(f"FAIL {name}: want refusal {want_code}, got ok={out.ok} codes={codes}")
            failures += 1

    # serving ground-snapshot collector: emitted-adjacent C#, same 6/6 bar
    from kir.serving import _SNAPSHOT_CS
    wrapped_snap = wrap_user_code(_SNAPSHOT_CS)
    row = []
    for ver in spec.REVIT_VERSIONS:
        checks += 1
        res = await _compile_check(wrapped_snap, ver)
        if res is None:
            row.append(f"{ver}:SVC?"); failures += 1
        elif res.success:
            row.append(f"{ver}:OK")
        else:
            row.append(f"{ver}:FAIL"); failures += 1
            for e in res.errors[:3]:
                print(f"    snapshot_cs @{ver} {e.code} L{e.line}: {e.message[:100]}")
    print(f"{'serving_snapshot_cs':24s} {' '.join(row)}")

    # ── READING BODIES: EVERY COLLECTOR, ON SIX VERSIONS ────────────────────
    #
    # 🔴 WHY THIS SECTION, IN ONE INCIDENT. The probe-route wave (20.08)
    # introduced calls to `__RouteSkips` into the SHARED helpers
    # `_ELEMENT_HELPERS_CS`, and placed the declaration in a preamble that
    # only the full extractor emits. The second consumer of those same
    # helpers — `reextract.build_reextract_cs` — stopped compiling that
    # same minute, and the JUDGE OF WHAT WAS BUILT died along with it: for
    # 49 commits in a row, every live build got "built but NOT RE-READ."
    #
    # The refusal was loud and printed in EVERY receipt — and it still
    # lived for two days, because no gate ever asked the reading bodies
    # whether they compile. The emitted bodies were asked; the reading
    # ones were not.
    #
    # COVERAGE IS DERIVED, NOT ENUMERATED. Collectors are found by walking
    # the package; a collector with no entry in the argument table is a
    # gate FAILURE, not a skip. A hand-written list would silently drift
    # from the package at the very first new extractor, repeating exactly
    # the defect this section catches.
    # 🔴 THE TABLE AND THE WALK LIVE IN `decompile/read_bodies.py`, NOT
    # HERE. They were born in this file on 21.08 and belonged here while
    # there was only one asker. On 21.08 the consent registry came for
    # them — and copying the table would mean setting up a second carrier
    # of exactly the knowledge the registry exists for. They were moved
    # out; the gate now ASKS.
    from kir.decompile.read_bodies import (
        READ_BODY_ARGS as read_body_args,
        discover_read_bodies as _discover_read_bodies,
        is_versioned as _is_versioned,
        uncovered_read_bodies as _uncovered_read_bodies,
    )

    _builders = _discover_read_bodies()

    for _n in _uncovered_read_bodies():
        print(f"FAIL read_body {_n}: сборщик тела не покрыт воротами — "
              f"добавь аргументы в `READ_BODY_ARGS`")
        failures += 1

    import inspect as _insp

    for _n in sorted(set(_builders) & set(read_body_args)):
        # 🔴 A BODY PARAMETERIZED BY VERSION IS BUILT AGAIN FOR EACH ONE.
        # The first draft of this section built the body ONCE and compiled
        # it on all six — and declared as a product defect what was
        # actually an INSTRUMENT defect: `build_tag_extract_cs` without a
        # version takes the 2022+ branch (`GetTaggedLocalElements`, which
        # does not exist on 2021), and 2021 predictably failed to build.
        # Tags have not one single member that lives across all six
        # versions — so the question "does the body compile" without a
        # version DOES NOT HAVE meaning, rather than "has it with a
        # caveat."
        _versioned = _is_versioned(_builders[_n])
        _row = []
        _built_once = None
        if not _versioned:
            try:
                _built_once = _builders[_n](**read_body_args[_n])
            except Exception as _exc:      # noqa: BLE001
                print(f"FAIL read_body {_n}: сборка упала — "
                      f"{type(_exc).__name__}: {str(_exc)[:120]}")
                failures += 1
                continue
        for ver in spec.REVIT_VERSIONS:
            checks += 1
            if _versioned:
                try:
                    _body = _builders[_n](revit_version=ver,
                                          **read_body_args[_n])
                except Exception as _exc:      # noqa: BLE001
                    print(f"FAIL read_body {_n} @{ver}: сборка упала — "
                          f"{type(_exc).__name__}: {str(_exc)[:120]}")
                    _row.append(f"{ver}:BUILD?"); failures += 1
                    continue
            else:
                _body = _built_once
            _wrapped = wrap_user_code(_body)
            _res = await _compile_check(_wrapped, ver)
            if _res is None:
                _row.append(f"{ver}:SVC?"); failures += 1
            elif _res.success:
                _row.append(f"{ver}:OK")
            else:
                _row.append(f"{ver}:FAIL"); failures += 1
                for _e in _res.errors[:3]:
                    print(f"    {_n} @{ver} {_e.code} L{_e.line}: "
                          f"{_e.message[:100]}")
        print(f"{_n:34s} {' '.join(_row)}")

    # Open-model transaction guard: optional internal emission is outside the
    # legacy byte corpus, so compile it explicitly on all versions.  This also
    # proves the document guard and identity guard remain separated by valid
    # newlines before the first mutation.
    _guard_snapshot, _guard_profile, _guard_document = (
        model_binding_guard_inputs())
    row = []
    for ver in spec.REVIT_VERSIONS:
        checks += 1
        guarded = compile_program(
            programs["auth_wall"],
            revit_version=ver,
            snapshot=_guard_snapshot,
            expected_document=_guard_document,
            open_model_profile=_guard_profile,
        )
        if not guarded.ok:
            row.append(f"{ver}:REFUSED")
            failures += 1
            _skip("compiler-refused")
            # A refusal here used to print NOTHING while a Roslyn error
            # printed three lines, so the one failure mode the reader could
            # not see was the one that fired — and every reader guessed it
            # as a compile failure. Say the reason.
            print(f"FAIL model_binding_guard@{ver}: KIR refused: "
                  + "; ".join(f"{d.code} {d.message_ru}"
                              for d in guarded.diagnostics[:3]))
            continue
        res = await _compile_check(wrap_user_code(guarded.csharp), ver)
        if res is None:
            row.append(f"{ver}:SVC?"); failures += 1
        elif res.success:
            row.append(f"{ver}:OK")
        else:
            row.append(f"{ver}:FAIL"); failures += 1
            for e in res.errors[:3]:
                print(f"    model_binding_guard @{ver} {e.code} L{e.line}: "
                      f"{e.message[:100]}")
    print(f"{'model_binding_guard':24s} {' '.join(row)}")

    # Name<->ordinal tables, pinned against AUTODESK rather than against
    # ourselves. `WALL_LOCATION_LINE_ORDINALS` is read by BOTH the emitter
    # (authoring.py, `.Set(ORDINALS[name])`) and its witness (same lookup),
    # so the two cannot disagree: swap a name/ordinal PAIR and the user asks
    # for `wall_centerline`, Revit receives `CoreCenterline`, and the witness
    # confirms the value it just wrote. Measured 2026-08-12: that mutation
    # survives the whole test suite AND a green 6/6 gate. Every guard the
    # table had reads the table — including one that inverts a dict derived
    # by inverting it, which is a tautology true of any permutation.
    #
    # "Ask the authority" is our usual remedy and it fails here, because the
    # authority WAS our table. So ask an authority outside the repository:
    # the real RevitAPI assemblies. C# has no static_assert, but two `case`
    # labels with the same constant value is CS0152 — so a compile FAILURE
    # proves the equality, and a clean compile proves inequality. Both
    # directions are decidable, which is why this can also fail.
    #
    # SCOPE, measured, so this is not quoted later as a general shield:
    # `WALL_LOCATION_LINE_ORDINALS` is the ONLY such table in the registry
    # today. The form generalises; the coverage is one table.
    from kir.ops_authoring import WALL_LOCATION_LINE_ORDINALS

    #: our name -> the enum member Autodesk must agree it equals. CLOSED: a
    #: row added to the table without a member here fails the stage rather
    #: than being skipped, so the next addition forces a decision.
    _WALL_LL_CS_MEMBERS = {
        "wall_centerline": "WallCenterline",
        "core_centerline": "CoreCenterline",
        "finish_face_exterior": "FinishFaceExterior",
        "finish_face_interior": "FinishFaceInterior",
        "core_exterior": "CoreExterior",
        "core_interior": "CoreInterior",
    }

    def _enum_probe_cs(member: str, ordinal: int) -> str:
        return (
            "using Autodesk.Revit.DB;\n"
            "namespace Kukai { class UserCode { public void Execute() {\n"
            "    switch (0) {\n"
            f"        case (int)WallLocationLine.{member}: break;\n"
            f"        case {ordinal}: break;\n"
            "    }\n"
            "} } }\n")

    unmapped = sorted(set(WALL_LOCATION_LINE_ORDINALS) - set(_WALL_LL_CS_MEMBERS))
    if unmapped:
        print("FAIL wall-location-line enum pin: table rows with no Revit "
              f"member declared: {unmapped}")
        failures += 1
    row = []
    for ver in spec.REVIT_VERSIONS:
        agreed = 0
        for name, ordinal in sorted(WALL_LOCATION_LINE_ORDINALS.items()):
            member = _WALL_LL_CS_MEMBERS.get(name)
            if member is None:
                continue
            checks += 1
            res = await _compile_check(_enum_probe_cs(member, ordinal), ver)
            if res is None:
                print(f"FAIL wall_ll_enum@{ver} {name}: compile service "
                      "gave no answer")
                failures += 1
                continue
            if any(e.code == "CS0152" for e in res.errors):
                agreed += 1            # Autodesk says the pair is right
            elif res.success:
                print(f"FAIL wall_ll_enum@{ver}: Autodesk disagrees — "
                      f"{name} is NOT {ordinal} "
                      f"(WallLocationLine.{member} compiled beside case "
                      f"{ordinal} without a duplicate-label error)")
                failures += 1
            else:
                print(f"FAIL wall_ll_enum@{ver} {name}: inconclusive, "
                      f"{sorted({e.code for e in res.errors})}")
                failures += 1
        # The stage must be able to say NO: a deliberately wrong pair has to
        # COMPILE CLEANLY. Without this, "did not build" degrades into "did
        # not build for any reason" and the pin stops being an instrument.
        # The wrong ordinal is taken OUTSIDE the enum's value range, not from
        # a sibling row: a control drawn from the table stops being wrong the
        # moment the table is permuted, which is the coupling this whole stage
        # exists to break. 9999 is wrong under every permutation.
        checks += 1
        wrong = await _compile_check(
            _enum_probe_cs("WallCenterline", 9999), ver)
        if wrong is None or not wrong.success:
            print(f"FAIL wall_ll_enum@{ver}: CONTROL — a deliberately wrong "
                  "pair did not compile cleanly, so a passing pin proves "
                  f"nothing ({'no answer' if wrong is None else sorted({e.code for e in wrong.errors})})")
            failures += 1
            row.append(f"{ver}:CONTROL?")
            continue
        row.append(f"{ver}:{agreed}/{len(_WALL_LL_CS_MEMBERS)}")
    print(f"{'wall_ll_enum_pin':24s} {' '.join(row)}")

    # The independent acceptance body is not emitted by compile_program, so it
    # needs an explicit 6/6 proof just like the ground snapshot and decompile
    # side stages.  A Python shape test cannot detect a Revit API member drift.
    _acceptance_body = acceptance_gate_body()
    row = []
    for ver in spec.REVIT_VERSIONS:
        checks += 1
        res = await _compile_check(wrap_user_code(_acceptance_body), ver)
        if res is None:
            row.append(f"{ver}:SVC?"); failures += 1
        elif res.success:
            row.append(f"{ver}:OK")
        else:
            row.append(f"{ver}:FAIL"); failures += 1
            for e in res.errors[:3]:
                print(f"    acceptance_l2 @{ver} {e.code} L{e.line}: "
                      f"{e.message[:140]}")
    print(f"{'acceptance_l2':24s} {' '.join(row)}")

    # Mutation probes use LocationPoint/LocationCurve, GetParameters,
    # GetTypeId, UniqueId, and the version-split ElementId constructor.  They
    # are emitted per API version and must pass the same live compiler matrix.
    row = []
    for ver in spec.REVIT_VERSIONS:
        checks += 1
        res = await _compile_check(
            wrap_user_code(mutation_acceptance_gate_body(ver)), ver)
        if res is None:
            row.append(f"{ver}:SVC?"); failures += 1
        elif res.success:
            row.append(f"{ver}:OK")
        else:
            row.append(f"{ver}:FAIL"); failures += 1
            for e in res.errors[:3]:
                print(f"    acceptance_mutation @{ver} {e.code} L{e.line}: "
                      f"{e.message[:140]}")
    print(f"{'acceptance_mutation':24s} {' '.join(row)}")

    # DECOMPILE side-index bridge collectors: read-only Execute bodies emitted
    # by the extract builders.  Same 6/6 compile bar as serving_snapshot_cs —
    # the bridge round-trip is expensive, so a version-specific compile failure
    # must be caught here, not at a live-Revit run.  Bodies use only
    # representative ids/budgets (the emitted C# is id-count-invariant in
    # shape), and are EMITTED PER VERSION (see side_stage_gate_bodies).
    _side_rows: dict[str, list[str]] = {
        stage: [] for stage in side_stage_gate_bodies(spec.REVIT_VERSIONS[0])}
    for ver in spec.REVIT_VERSIONS:
        for _stage, _body in sorted(side_stage_gate_bodies(ver).items()):
            checks += 1
            res = await _compile_check(wrap_user_code(_body), ver)
            if res is None:
                _side_rows[_stage].append(f"{ver}:SVC?"); failures += 1
            elif res.success:
                _side_rows[_stage].append(f"{ver}:OK")
            else:
                _side_rows[_stage].append(f"{ver}:FAIL"); failures += 1
                for e in res.errors[:3]:
                    print(f"    боковая {_stage} @{ver} {e.code} L{e.line}: "
                          f"{e.message[:140]}")
    for _stage in sorted(_side_rows):
        print(f"{'боковая ' + _stage:24s} {' '.join(_side_rows[_stage])}")

    # THE BASE EXTRACTION BODY. Before 31.07 the gate compiled the side
    # stages and did NOT compile the main one: `build_category_batch_cs` —
    # the very code that reads every element of every decompile. The hole
    # was found when adding `CEILING_HEIGHTABOVELEVEL_PARAM`: the
    # parameter name was taken from the documentation, and Autodesk's
    # documentation diverges from its own assemblies (issue #78 —
    # `SpatialElementTag.SpatialElement` is documented in all six XML
    # versions and absent from all six DLLs). Asserting a member's
    # existence from its description is exactly what this gate guards
    # against.
    #
    # Three categories are enough, and this is MEASURED, not eyeballed:
    # the parameter block is shared across all categories (one set of
    # `__Put*Param` calls per element), only the collector differs. Wall,
    # ceiling, and floor take three different collectors and one shared
    # block.
    from kir.decompile.extract import build_category_batch_cs
    for _cat in ("OST_Walls", "OST_Ceilings", "OST_Floors"):
        _row: list[str] = []
        _body = build_category_batch_cs(_cat)
        for ver in spec.REVIT_VERSIONS:
            checks += 1
            res = await _compile_check(wrap_user_code(_body), ver)
            if res is None:
                _row.append(f"{ver}:SVC?"); failures += 1
            elif res.success:
                _row.append(f"{ver}:OK")
            else:
                _row.append(f"{ver}:FAIL"); failures += 1
                for e in res.errors[:3]:
                    print(f"    извлечение {_cat} @{ver} {e.code} L{e.line}: "
                          f"{e.message[:140]}")
        print(f"{'извлечение ' + _cat:24s} {' '.join(_row)}")

    # STAMP CLEANUP. The third hole of the same kind, found on 31.07: the
    # gate did not know about `_orphan_sweep_cs` at all. The cost of a
    # mistake in this generator is above average — it is the only one
    # that DELETES elements from the live model, and a version that fails
    # to build would only be discovered at the exact moment a human
    # clicked "undo what was built."
    #
    # Four variants cover every branch of the template: preview versus
    # deletion (different transaction blocks) and both prefix grammars —
    # an A5 run and the content hash of an ordinary program. The document
    # fingerprint guard is included, because it inserts its OWN C# into
    # both blocks.
    from kir.serving import DocumentFingerprint, _orphan_sweep_cs
    _fp = DocumentFingerprint(
        title="Ворота", path_name="gate.rvt", project_uid="gate-uid")
    _sweeps = {
        "a5 предпросмотр": ("kir:a5:" + "0" * 12 + ":" + "0" * 16 + ":", False),
        "a5 удаление": ("kir:a5:" + "0" * 12 + ":" + "0" * 16 + ":", True),
        "программа предпросмотр": ("kir:" + "0" * 8 + ":", False),
        "программа удаление": ("kir:" + "0" * 8 + ":", True),
    }
    for _label, (_prefix, _delete) in _sweeps.items():
        _row = []
        _body = _orphan_sweep_cs(
            _prefix, delete=_delete, document_fingerprint=_fp)
        for ver in spec.REVIT_VERSIONS:
            checks += 1
            res = await _compile_check(wrap_user_code(_body), ver)
            if res is None:
                _row.append(f"{ver}:SVC?"); failures += 1
            elif res.success:
                _row.append(f"{ver}:OK")
            else:
                _row.append(f"{ver}:FAIL"); failures += 1
                for e in res.errors[:3]:
                    print(f"    уборка {_label} @{ver} {e.code} L{e.line}: "
                          f"{e.message[:140]}")
        print(f"{'уборка ' + _label:24s} {' '.join(_row)}")

    # ── REFERENCE CLOSURE: A DECLARED ASSEMBLY MUST ACTUALLY LINK ───────────
    #
    # WHY THIS IS IN THE GATE, AND NOT A SEPARATE INSTRUMENT. The
    # instrument (`tools/closure_probe.py`) was written on 14.08 and
    # CALLED BY NO ONE — meaning it was one more discipline that can go
    # unscored. The suite lock in this tree rests on exactly the same
    # argument: a capability with no path to it from a real entry point
    # does not exist.
    #
    # WHAT IT CATCHES AND WHAT THE REST OF THE GATE DOES NOT. The gate
    # compiles OUR emission; if it never touches an assembly, the gate
    # will not see that assembly missing from the closure. The 09–13.08
    # incident had exactly this shape: `AdWindows`/`UIFramework` were
    # added to both sources, a guard compared source against source and
    # stayed green for four days, while the live service kept rejecting
    # `Autodesk.Windows`, because it had not been rebuilt. Here, for every
    # declared assembly, a body is sent that LINKS its type — meaning the
    # artifact is being asked, not the text.
    #
    # THE BOUNDARY IS NAMED: what is measured is the SERVICE's closure,
    # not the client's. The plugin compiles against what is loaded inside
    # the Revit process, and the gate cannot reach there — that is the
    # job of `tests/bridge_reference_closure.py`.
    try:
        _closure = ports.need(ports.REFERENCE_CLOSURE)
    except Exception as _exc:                 # noqa: BLE001
        # "The instrument failed to connect" is a REFUSAL, not a skip: a
        # silently skipped check reads as a passed one.
        print(f"замыкание ссылок     ПРИБОР НЕ ПОДКЛЮЧИЛСЯ: "
              f"{type(_exc).__name__}: {_exc}")
        failures += 1
    else:
        _declared = _closure.closure.reference_closure("declared")
        _assemblies = tuple(_declared.revit) + tuple(_declared.exact)
        _no_witness = [n for n in _assemblies if n not in _closure.WITNESS_TYPE]
        if _no_witness:
            print(f"замыкание ссылок     У СБОРОК НЕТ СВИДЕТЕЛЯ: {_no_witness} "
                  f"— список свидетелей закрыт намеренно")
            failures += 1
        for _asm in _assemblies:
            _row = []
            _probe_body = _closure._body(_closure.WITNESS_TYPE[_asm])
            for ver in spec.REVIT_VERSIONS:
                checks += 1
                # THE ONE AND ONLY PATH TO THE SERVICE IS `_compile_check`,
                # and this is not a style choice. The closure instrument
                # arrived by a merge on 16.08 from the prod line, where
                # there is NO accounting guard (measured: `origin/prod-live`
                # has zero occurrences of "does not equal the named skips,"
                # we have one). It called `client.check` directly, and its
                # 48 checks (8 assemblies × 6 versions) bypassed `compiled`
                # and bypassed the named skips — exactly the lie the
                # `_compile_check` docstring declares impossible. Each side
                # was sound on its own; it was their CONNECTION that broke.
                res = await _compile_check(wrap_user_code(_probe_body), ver)
                _known = (_asm, ver) in _closure.ACCEPTED_GAPS
                if res is None:
                    _row.append(f"{ver}:SVC?"); failures += 1
                elif res.success:
                    _row.append(f"{ver}:OK")
                elif _known:
                    # The named asymmetry is a decision, not a finding; it
                    # must be visible and it must not turn red.
                    _row.append(f"{ver}:~")
                else:
                    _row.append(f"{ver}:FAIL"); failures += 1
                    for e in res.errors[:2]:
                        print(f"    замыкание {_asm} @{ver} {e.code}: "
                              f"{e.message[:140]}")
            print(f"{'замыкание ' + _asm:24s} {' '.join(_row)}")

    await client.close()
    # ── CONSENT REGISTRY ─────────────────────────────────────────────────────
    #
    # 🔴 WHY IT IS IN THE GATE. As of 21.08.2026 the "two carriers of one
    # piece of knowledge" defect happened NINE times, and not one of the
    # nine was visible to grep, to an import, or to compilation: each
    # place was correct on its own, it was their DIFFERENCE that was
    # wrong. The registry is the one thing that asks about the
    # difference, and it costs 2–3 seconds on a five-minute gate.
    #
    # COUNTED AS A CHECK, BUT NOT AS A COMPILATION: Roslyn never sees
    # these bodies, so the contribution goes into `not_compiled` under
    # its own name — otherwise the check "attempts minus compiled = named
    # skips" would drift apart.
    try:
        from kir.agreements import check_all as _check_agreements
        _averdicts = _check_agreements()
    except Exception as _exc:      # noqa: BLE001
        print(f"FAIL agreements: реестр не поднялся — "
              f"{type(_exc).__name__}: {_exc}")
        failures += 1
        _averdicts = []
    _arow = []
    for _v in _averdicts:
        checks += 1
        not_compiled["agreement"] = not_compiled.get("agreement", 0) + 1
        if _v.ok:
            _arow.append(f"{_v.name.split('_')[0]}:OK")
            continue
        failures += 1
        if not _v.holds:
            _arow.append(f"{_v.name.split('_')[0]}:РАЗОШЛОСЬ")
            print(f"FAIL agreement {_v.name}: {_v.claim}")
            for _d in _v.detail:
                print(f"    → {_d}")
        else:
            _arow.append(f"{_v.name.split('_')[0]}:ПУСТОЕ")
            print(f"FAIL agreement {_v.name}: судья не может отказать — "
                  f"зелёный этого согласия не значит ничего")
    if _arow:
        print(f"{'agreements':24s} {' '.join(_arow)}")

    # Reconcile BEFORE the PASS/FAIL word is chosen, or the gate can print
    # PASS on the same line that records an accounting failure.
    if checks - compiled != sum(not_compiled.values()):
        print("FAIL gate accounting: attempts minus compiled "
              f"({checks - compiled}) does not equal the named skips "
              f"({sum(not_compiled.values())}) — a skip is going unnamed")
        failures += 1
    # `checks` counts ATTEMPTS; `compiled` counts bodies Roslyn answered.
    # They differ by exactly the skips, and every skip is named. Printing
    # only the attempt count is how "1896 live compile checks" came to
    # include 30 attempts that compiled nothing at all.
    #
    # THIS LINE GOES FIRST, AND THAT ORDER IS THE POINT. When it was printed
    # LAST, `tail -1` returned it — and it is byte-identical whether the gate
    # passed or failed, because a semantic failure (a wrong ordinal, a refused
    # program) changes no count here. A reader taking the last line got a
    # sentence that cannot say "no", and one of us nearly filed a red run as
    # green from exactly that. The VERDICT is now last, so the cheapest
    # possible reading is also the truthful one.
    print(f"\n      {checks} attempts = {compiled} compiled + "
          f"{checks - compiled} not compiled"
          + (" (" + ", ".join(f"{reason}: {count}" for reason, count
                              in sorted(not_compiled.items())) + ")"
             if not_compiled else ""))
    # The address of every number above. Printed BEFORE the verdict so the
    # verdict stays last, and printed even when incomplete — a manifest that
    # silently omits a version would be the defect this exists to close.
    _manifest, _mproblems = revit_reference_manifest()
    if _manifest:
        print("      Revit refs (" + ", ".join(_REVIT_REF_DLLS) + "), sha256/12:")
        print("        " + "  ".join(f"{v}:{d[:12]}"
                                     for v, d in sorted(_manifest.items())))
    for _p in _mproblems:
        print(f"      Revit refs UNAVAILABLE — {_p}")
    if not _manifest and not _mproblems:
        print("      Revit refs: manifest empty and no reason given — "
              "treat every count above as unaddressed")
    print("      system refs: NOT in this manifest (they belong to the "
          "service runtime); their role is Bridge parity, guarded by the "
          "drift guards on both sides")
    # THE SUBJECT of every number above, not just its address. Printed
    # BEFORE the verdict, by the same rule as the manifest: the verdict
    # stays last. Found by the SUITE zone on 12.08 — the fixture lacked
    # the `roof_types` pool, and it got away cheaply only because the
    # pool is declared optional; a mandatory one in the same position
    # would have brought down the whole gate, and it would have looked
    # like "the op is broken." Fixture pool completeness is pinned by a
    # SET comparison against `spec.OPS` (the SUITE zone), not a length
    # comparison: the producer and the fixture each had 35 pools with 34
    # matching names, and any "how many" check would have confirmed
    # completeness.
    print(f"      заземление: {fixture_grounded} из {program_compilations} "
          f"компиляций программ идут против ФИКСТУРЫ "
          f"{GROUND_SNAPSHOT_ORIGIN} — не против настоящего документа. "
          f"Их «OK» есть утверждение о фикстуре")
    # THE SECOND STRIP is NEXT TO the line above, not instead of it:
    # these are answers to DIFFERENT questions, and replacing one with
    # the other would lose both.
    if not real_profiles:
        # A refusal, not a zero. A zero here would read as "the programs
        # don't hold up against real documents," when the truth is "we
        # did not look."
        print(f"      настоящий документ: ОТКАЗ ПРИБОРА — "
              f"{REAL_PROFILE_FETCH_HINT}")
        # 🔴 A MACHINE STRING, PRINTED ON BOTH BRANCHES, INCLUDING ZERO. A
        # human reads the prose above, while grep collects the run
        # summary, and it must tell "not checked" apart from "checked and
        # clean" WITHOUT parsing Russian text. Owner's decision of
        # 16.08.2026: an instrument refusal must be impossible to mistake
        # for green, so the counter is always present, not only when it
        # is non-zero.
        print(instrument_refusal_line(1, why="корпуса нет"))
    else:
        print(f"      настоящий документ: {real_grounded} из "
              f"{snapshot_programs} ПРОГРАММ, требующих снимка, заземлены "
              f"РАЗБОРОМ настоящего здания ({len(real_profiles)} профилей "
              f"корпуса) и собраны на шести версиях с ним. Знаменатель здесь "
              f"— программы, а не компиляции: строкой выше их "
              f"{fixture_grounded}, потому что пишущая входит дважды "
              f"(atomic и per_op)")
        # CLOSED, BUT NOT COMPLETE: empty here would mean "we don't
        # know," not "there is no remainder." Completeness is
        # unreachable — the list is bounded by the corpus, which can be
        # anything on this machine.
        for pname, why in real_remainder:
            print(f"        · {pname:32.32s} {why}")
        # The paired line to the refusal above. Zero is printed EXACTLY
        # HERE, not omitted: whoever reads the summary must see that the
        # question WAS ASKED and the answer was "nothing to add," not
        # that the line does not exist at all.
        print(instrument_refusal_line(0))
    print(f"{'PASS' if failures == 0 else 'FAIL'}: "
          f"{len(programs)} programs (atomic) "
          f"+ {write_program_count} write programs (per_op), "
          f"x {len(spec.REVIT_VERSIONS)} versions each "
          f"+ {len(expected_refusals)} expected-refusal check(s), "
          f"{sized_cable_tray_branch_checks} sized-tray branch emission(s), "
          f"{compiled} live compile checks, "
          f"{known_gaps} known per_op gap(s) tracked separately, "
          f"{failures} failures")
    return 0 if failures == 0 else 1


def _run_naming_a_missing_port() -> int:
    """Gate run. A missing host port is a NAMED refusal, not a traceback.

    🔴 WHY THIS WAS SET UP (30.08.2026, another person's gate, team 04).
    The CONTENT of the refusal was already declared honest by the canon:
    "named, carrying the port's name, no stand-ins" (`kir/CLAUDE.md`, the
    section on host ports), and the `PortMissing` text is witness to that
    — it names both the missing port and what was supplied. The canon was
    silent about the FORM OF DELIVERY, and silence is not a blessing: the
    other person got `EXIT=1` and ZERO characters on `stdout`, while the
    whole honest answer went to `stderr` as a nine-frame traceback — that
    is, the refusal EXISTED but was NOT HEARD.

    THE REFUSAL TEXT IS NOT REWRITTEN: it is inserted verbatim. What gets
    fixed is the delivery.

    THE RETURN CODE IS DISTINGUISHABLE, AND THE DISTINCTION HERE IS NOT
    COSMETIC:
        0  the gate judged and found no refusals
        1  the gate DID JUDGE and found refusals
        2  the gate DID NOT JUDGE AT ALL — the host did not supply the capability
    Collapsing 2 into 1 would mean saying "the gate found refusals" where
    it never sat in judgment at all; this tree has already paid for
    exactly this distinction.

    ONLY `PortMissing` IS CAUGHT. Any other exception must fail exactly as
    it always did: turning every failure into a polite refusal would hide
    the real ones. And it is caught only at the COMMAND boundary —
    whoever calls `main()` from code gets the exception, as before.
    """
    try:
        return asyncio.run(main())
    except ports.PortMissing as отказ:
        print(f"🔴 ОТКАЗ: ворота 6/6 НЕ ПРОГНАНЫ — {отказ}")
        print("   Это не находка ворот: они не судили ни одной программы. "
              "Ворота просят у хозяина ПОРТ, а не службу, и без поставщика "
              "судить нечем.")
        print(f"   Поставленные порты: {', '.join(ports.supplied()) or '—'}")
        print("   Поставить способность:  "
              "kir.ports.register(<имя порта>, <фабрика>)  — до прогона.")
        return 2


if __name__ == "__main__":
    sys.exit(_run_naming_a_missing_port())
