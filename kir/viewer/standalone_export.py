"""An immutable, capability-gated display export; never a replacement KIR program.

The caller must materialize explicitly before this entrypoint. This module does
not read assets, run recipes/OCP, publish to a session, or execute Revit. It keeps
the original binary scene (including its per-element fidelity and omissions)
separate from opt-in approximate profile proxies. No proxy enters clash or the
compiler. A serialized artifact asserts derivation; hashes bind its bytes, not
native equivalence, recipe execution, or what a browser actually rendered.
"""
from __future__ import annotations

import base64
from collections.abc import Collection, Mapping
from dataclasses import dataclass
import hashlib
import json
import struct

from kir.clash_bundle import bundle_oid
from kir.geometry_materialization import GeometryMaterialization
from kir.project import _canonical, _hash, _object, _thaw
from kir.viewer.blend_preview import (BlendPreviewRefusal, REQUIRED_CONSUMER_CAPABILITY,
                                      preview_native_blend)
from kir.viewer.codec import SCENE_MAGIC, SCENE_SCHEMA


DISPLAY_SCHEMA = "kir-standalone-display/1"
DISPLAY_SCHEMA_V2 = "kir-standalone-display/2"
#: 🔴 A THIRD SCHEMA, NOT A FREE-FORM FIELD IN THE PREVIOUS ONE.
#: Reconnaissance 06.09.2026: every artifact container is closed by
#: `_fields()` for set equality, `claims` for exact dict equality, and the
#: same is repeated in the JS mirror; fields for arbitrary layers/tags — 0.
#: Showing the pair, the depth, and the analysis limits without touching the
#: schema is not possible, and "just add a key" here would mean breaking the
#: loader on both sides. The form taken is the same one this house has
#: already used twice: a consumer capability plus its own schema version.
DISPLAY_SCHEMA_V3 = "kir-standalone-display/3"
#: /4 is a superstructure over /3 by the same law: the remainder and
#: question containers always exist, empty if the capability to show them
#: is not declared. Otherwise a version would be needed for every
#: combination of the FOUR capabilities.
DISPLAY_SCHEMA_V4 = "kir-standalone-display/4"
MAX_SCENE_BYTES = 64 * 1024 * 1024
MAX_ARTIFACT_BYTES = 96 * 1024 * 1024


class StandaloneExportRefusal(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True, init=False)
class StandaloneDisplayArtifact:
    """Factory-only immutable export. No loader promotes JSON into execution evidence."""

    scene_bytes: bytes
    _descriptor: Mapping
    digest: str

    def __init__(self):
        raise TypeError("use export_standalone_scene with an explicit GeometryMaterialization")

    def to_dict(self) -> dict:
        result = _thaw(self._descriptor)
        result["scene"]["base64"] = base64.b64encode(self.scene_bytes).decode("ascii")
        return {**result, "artifact_digest": self.digest}

    def dumps(self) -> str:
        return _canonical(self.to_dict())


def _scene_index(blob: bytes) -> tuple[dict, list[dict]]:
    """Read our just-produced codec, not a public parser for arbitrary artifacts."""
    try:
        if blob[:len(SCENE_MAGIC)] != SCENE_MAGIC:
            raise ValueError("unexpected scene magic")
        length = struct.unpack_from("<I", blob, len(SCENE_MAGIC))[0]
        start = len(SCENE_MAGIC) + 4
        header = json.loads(blob[start:start + length])
        base = start + length
        if (header["schema"] != SCENE_SCHEMA or header["units"] != "mm"
                or base + header["body_bytes"] != len(blob)):
            raise ValueError("unexpected codec schema, units or body length")
        buffers = {}
        for span in header["buffers"]:
            offset, size = span["offset"], span["length"]
            if offset < 0 or size < 0 or base + offset + size > len(blob):
                raise ValueError("codec buffer exceeds its body")
            buffers[span["name"]] = blob[base + offset:base + offset + size]
        ids = buffers["ids"].decode("utf-8").splitlines()
        kinds, fidelity = buffers["elem_kind"], buffers["elem_fidelity"]
        if not (len(ids) == len(kinds) == len(fidelity) == header["elements"]):
            raise ValueError("codec element streams disagree")
        names = {value: key for key, value in header["kinds"].items()}
        fidelities = {value: key for key, value in header["fidelity_codes"].items()}
        rows = [{"display_id": oid, "scene_element_index": index,
                 "kind": names[kind], "fidelity_code": fid, "fidelity": fidelities[fid]}
                for index, (oid, kind, fid) in enumerate(zip(ids, kinds, fidelity, strict=True))]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate direct scene addresses")
        return header, rows
    except (ValueError, KeyError, TypeError, struct.error) as exc:
        raise StandaloneExportRefusal("unsupported_scene_codec", str(exc)) from exc


def export_standalone_scene(materialization: GeometryMaterialization, *,
                            consumer_capabilities: Collection[str] = (),
                            clash_report: Mapping | None = None,
                            refinement_report=None) -> StandaloneDisplayArtifact:
    """Export a whole, unsessioned scene and separately attributed display proxies.

    Capabilities are the caller's explicit declaration, not browser attestation.
    Omissions cover direct named-output addresses, including datums/edits that
    need not have a 3D record. Extra generated scene addresses remain named but
    are not guessed back to an owner. Record counts never mean BIM coverage.
    Output budgets are post-build limits, not CPU/RSS isolation.
    """
    from kir.viewer.clash_findings import (CLASH_CAPABILITY, CLASH_CLAIMS,
                                           display_clash_findings)
    from kir.viewer.refinement_display import (REFINEMENT_CAPABILITY, REFINEMENT_CLAIMS,
                                               display_refinement)
    from kir.viewer.live_scene import scene_from_programs
    from kir.viewer.reference_surfaces import SURFACE_CAPABILITY, preview_reference_surfaces

    if type(materialization) is not GeometryMaterialization:
        raise StandaloneExportRefusal("explicit_materialization_required", "expected the typed materialization result, not a project/store/JSON")
    if (not isinstance(consumer_capabilities, Collection)
            or isinstance(consumer_capabilities, (str, bytes, Mapping))
            or any(not isinstance(item, str) for item in consumer_capabilities)):
        raise StandaloneExportRefusal("invalid_capabilities", "expected a collection of capability names")
    capabilities = sorted(set(consumer_capabilities))
    if set(capabilities) - {REQUIRED_CONSUMER_CAPABILITY, SURFACE_CAPABILITY,
                            CLASH_CAPABILITY, REFINEMENT_CAPABILITY}:
        raise StandaloneExportRefusal("unsupported_capability", "unknown display representation policy")
    surface_enabled = SURFACE_CAPABILITY in capabilities
    clash_enabled = CLASH_CAPABILITY in capabilities
    refinement_enabled = REFINEMENT_CAPABILITY in capabilities
    # A report without the capability is not "let's show it just in case",
    # it is a refusal: otherwise a consumer that cannot draw findings would
    # get them and say nothing.
    if clash_report is not None and not clash_enabled:
        raise StandaloneExportRefusal("clash_capability_absent",
                                      "находки анализа требуют объявленной способности показа")
    if refinement_report is not None and not refinement_enabled:
        raise StandaloneExportRefusal("refinement_capability_absent",
                                      "остаток и вопросы требуют объявленной способности показа")
    program = materialization.to_program()
    # No fixed zero origin: retain the codec's actual origin for float32
    # precision. Proxy coordinates remain project-mm; a consumer must subtract
    # this origin if it draws them in the binary scene's relative frame.
    blob, _ = scene_from_programs([program])
    if len(blob) > MAX_SCENE_BYTES:
        raise StandaloneExportRefusal("display_budget_exceeded", "binary scene exceeds the export byte limit")
    header, scene_records = _scene_index(blob)
    scene_by_id = {row["display_id"]: row for row in scene_records}
    definition_digests = {module.key: module.definition_digest for module in materialization.project.modules}
    surface_result = (preview_reference_surfaces(program, bulk=materialization.planned.bulk)
                      if surface_enabled else {"previews": [], "refusals": {}})
    surface_by_id = {preview["source"]["op_id"]: preview for preview in surface_result["previews"]}
    if len(surface_by_id) != len(surface_result["previews"]):
        raise StandaloneExportRefusal("invalid_surface_batch", "duplicate surface producer identity")
    operations, proxies, omissions, surfaces, surface_refusals = [], [], [], [], []
    for (instance, output, oid), operation in zip(
            materialization.project.addressed_outputs(), program["ops"], strict=True):
        display_id = bundle_oid(1, oid)
        source = {"op_id": oid, "display_id": display_id, "instance_key": instance.key,
                  "module_key": instance.module_key, "output_key": output.key,
                  "module_definition_digest": definition_digests[instance.module_key],
                  "op": operation["op"], "operation_sha256": _hash(operation),
                  "authored_output_sha256": _hash(output.to_dict())}
        if output.geometry is not None:
            source["geometry_reference"] = output.geometry.to_dict()
        selected_surface, surface_refusal = None, None
        if surface_enabled and operation["op"] in ("create_wall", "create_floor_by_contour"):
            preview = surface_by_id.get(oid)
            if preview is not None:
                if (preview["source"]["operation_sha256"] != source["operation_sha256"]
                        or preview["source"]["compiler_plan_digest"] != materialization.planned.plan_digest):
                    refusal = {"code": "materialization_plan_mismatch", "detail": "surface normalization differs from the materialized program"}
                elif display_id in scene_by_id and scene_by_id[display_id]["fidelity"] != "no_body":
                    refusal = {"code": "existing_scene_representation_preserved", "detail": "reference surfaces do not replace a known base representation"}
                else:
                    selected_surface = preview
                    surfaces.append({"display_id": display_id, "preview": preview})
            else:
                refusal = surface_result["refusals"].get(oid, {"code": "surface_not_produced", "detail": "no qualified surface result"})
            if selected_surface is None:
                surface_refusal = {"display_id": display_id, **refusal}
                surface_refusals.append(surface_refusal)
        if display_id in scene_by_id:
            source["display_status"] = "base_scene_record"
        elif selected_surface is not None:
            source["display_status"] = "authored_surface_record"
        elif operation["op"] == "create_solid_blend":
            if REQUIRED_CONSUMER_CAPABILITY not in capabilities:
                refusal = {"code": "capability_required", "required_capability": REQUIRED_CONSUMER_CAPABILITY}
            else:
                try:
                    preview = preview_native_blend(operation, ir_version=program["ir_version"]).to_dict()
                except BlendPreviewRefusal as exc:
                    refusal = {"code": exc.code, "detail": str(exc)}
                else:
                    proxies.append({"display_id": display_id, "preview": preview})
                    source["display_status"] = "approximate_proxy_record"
                    operations.append(source)
                    continue
            source["display_status"] = "omitted"
            omissions.append({**source, "scope": "direct_output_address", **refusal})
        else:
            source["display_status"] = "omitted"
            # Aggregate plan/clash counters are NOT per-operation evidence.
            # The binary scene retains their original scopes and diagnostics.
            reason = surface_refusal
            omissions.append({**source, "scope": "direct_output_address", **(
                {key: value for key, value in reason.items() if key != "display_id"}
                if reason is not None else {"code": "no_direct_scene_record"})})
        operations.append(source)
    known_ids = {row["display_id"] for row in operations}
    materialized = materialization.to_dict()
    descriptor = {
        "schema": DISPLAY_SCHEMA_V2 if surface_enabled else DISPLAY_SCHEMA,
        "source": {"project_id": materialization.project.project_id,
                   "project_revision_id": materialization.project.revision_id,
                   "project_schema": materialization.project.schema,
                   "parent_revision_id": materialization.project.parent_revision,
                   "ir_version": program["ir_version"], "plan_digest": materialization.planned.plan_digest,
                   "materialization_digest": materialized["materialization_digest"],
                   "program_sha256": _hash(program), "operations": operations,
                   "body_sources": materialized["sources"]},
        "scene": {"schema": header["schema"], "sha256": hashlib.sha256(blob).hexdigest(),
                  "size_bytes": len(blob), "encoding": "base64", "units": header["units"],
                  "origin_mm": header["origin_mm"], "counts": header["counts"],
                  "kind_codes": header["kinds"], "records": scene_records},
        "proxies": proxies, "omissions": omissions,
        "unattributed_scene_ids": [row["display_id"] for row in scene_records if row["display_id"] not in known_ids],
        "consumer_contract": {
            "declared_capabilities": capabilities,
            "required_proxy_capabilities": sorted(([REQUIRED_CONSUMER_CAPABILITY] if proxies else [])
                                                  + ([SURFACE_CAPABILITY] if surfaces else [])),
            "required_scene_kinds": sorted(name for name in header["kinds"] if header["counts"][name]),
            "base_scene_fidelity": "preserve_per_element_codes",
            "proxy_rendering": "visually_distinct_with_claims_visible",
            "coordinates": "binary_relative_to_scene_origin__proxies_project_mm",
        },
        "claims": {"scope": "authored_display_export", "authored_program": "unchanged",
                   "native_execution": "not_run", "native_equivalence": "not_claimed",
                   "bim_coverage": "not_claimed", "clash_coverage": "not_claimed",
                   "browser_rendering": "not_observed", "recipe_execution": "not_run",
                   "digest_scope": "byte_integrity_not_rebuild_determinism_or_execution_proof"},
    }
    if surface_enabled:
        descriptor.update(surfaces=surfaces, surface_refusals=surface_refusals)
    if clash_enabled:
        # The map is built FROM MATERIALIZATION: `operations` is assembled
        # right here from `addressed_outputs()`, and the "output_id →
        # display_id" pair is taken from there, not glued together from a
        # string.
        by_output = {row["op_id"]: row["display_id"] for row in operations}
        shown = display_clash_findings(clash_report or {}, sorted(known_ids),
                                       address_map=by_output)
        descriptor["schema"] = DISPLAY_SCHEMA_V3
        # /3 IS A SUPERSTRUCTURE over /2, not a fourth combination: the
        # surface containers are always present, empty if the capability to
        # show them is not declared. Otherwise a version would be needed for
        # every combination of three capabilities, and the closed list of
        # fields would stop being closed.
        descriptor.setdefault("surfaces", surfaces)
        descriptor.setdefault("surface_refusals", surface_refusals)
        descriptor.update(clash_findings=shown["findings"],
                          clash_analysis_limits=shown["analysis_limits"],
                          clash_claims=dict(CLASH_CLAIMS))
        # The capability is declared — meaning it is also required, even if
        # there are zero findings: "zero findings" and "findings are not
        # shown" must be distinguishable.
        descriptor["consumer_contract"]["required_proxy_capabilities"] = sorted(
            descriptor["consumer_contract"]["required_proxy_capabilities"] + [CLASH_CAPABILITY])
    if refinement_enabled:
        # The same map from materialization as for findings: the analysis
        # address is `output_id`, the display address is display-id, and
        # gluing them together by string is not allowed (measured 06.09:
        # without translation, 0 of 5 findings were shown).
        by_output = {row["op_id"]: row["display_id"] for row in operations}
        record = display_refinement(refinement_report or {}, sorted(known_ids),
                                    address_map=by_output) if refinement_report is not None else {
            "refinement": {}, "questions": [], "analysis_limits": []}
        descriptor["schema"] = DISPLAY_SCHEMA_V4
        descriptor.setdefault("surfaces", surfaces)
        descriptor.setdefault("surface_refusals", surface_refusals)
        descriptor.setdefault("clash_findings", [])
        descriptor.setdefault("clash_analysis_limits", [])
        descriptor.setdefault("clash_claims", dict(CLASH_CLAIMS))
        descriptor.update(refinement=record["refinement"],
                          refinement_questions=record["questions"],
                          refinement_analysis_limits=record["analysis_limits"],
                          refinement_claims=dict(REFINEMENT_CLAIMS))
        descriptor["consumer_contract"]["required_proxy_capabilities"] = sorted(
            descriptor["consumer_contract"]["required_proxy_capabilities"] + [REFINEMENT_CAPABILITY])
    payload = {**descriptor, "scene": {**descriptor["scene"], "base64": base64.b64encode(blob).decode("ascii")}}
    digest = _hash(payload)
    if len(_canonical({**payload, "artifact_digest": digest}).encode("utf-8")) > MAX_ARTIFACT_BYTES:
        raise StandaloneExportRefusal("display_budget_exceeded", "complete display artifact exceeds the export byte limit")
    result = object.__new__(StandaloneDisplayArtifact)
    object.__setattr__(result, "scene_bytes", blob)
    object.__setattr__(result, "_descriptor", _object(descriptor, "display_artifact"))
    object.__setattr__(result, "digest", digest)
    return result


def saved_refinement_report(store, project=None):
    """The refinement report FROM THE SAVED state — or `None` with a reason.

    Returns `(report | None, reason | None)`. There is no `None` without a
    reason: "no edit has been registered" and "an edit exists but was not
    shown" must be distinguishable, or an empty display reads as "there is
    no remainder".

    🔴 A SEAM I DID NOT NEGOTIATE. The edit metadata key
    (`project_refinement._PENDING_KEY`) is private today: C2 has no public
    name that hands back "which edit is registered" — `open_questions` hands
    back only questions, and the report also needs `source_output_id` and
    `change`. The import is pinned by a test, so a rename breaks the build
    LOUDLY instead of turning the display into a silent zero. The request
    for a public name is recorded in `refine-loop/CONTRACT-AB2.md`.
    """
    from kir.project_refinement import (RefinementError, _PENDING_KEY,
                                        refine_after_source_change)

    head = project if project is not None else store.head()
    for instance in head.instances:
        pending = _thaw(instance.metadata.get(_PENDING_KEY)) if instance.metadata else None
        if not isinstance(pending, dict):
            continue
        try:
            return refine_after_source_change(
                store, head, source_output_id=pending["source_output_id"],
                change=pending["change"]), None
        except (RefinementError, KeyError, TypeError, ValueError) as exc:
            return None, f"правка заведена, но отчёт не построен: {type(exc).__name__}: {exc}"
    return None, "правка источника не заведена: показывать нечего, а не «остатка нет»"


def export_saved_project_scene(store, *, exact: bool = True,
                               revision_id: str | None = None,
                               consumer_capabilities: Collection[str] = (),
                               refinement=None
                               ) -> tuple[StandaloneDisplayArtifact, Mapping]:
    """An end-to-end move: a saved project -> analysis -> a `/3` display
    artifact.

    🔴 WHY THIS FUNCTION EXISTS AT ALL. Acceptance testing on 06.09.2026
    found that the finding display is built, but there is not a single CALL
    to it anywhere in the tree: the export could accept a report, but no one
    connected the analysis to the display, and "0 findings shown" was held
    up not by a breakage but by the absence of a move. Here there is one
    named move; it introduces no logic of its own for analysis or display.

    Returns an "artifact, report" pair: the number of findings in the
    artifact and the number in the report must be checked against each
    other BY THE READER, not derived one from the other.
    """
    from kir.clash.project_analysis import analyze_revision
    from kir.viewer.clash_findings import CLASH_CAPABILITY
    from kir.viewer.refinement_display import REFINEMENT_CAPABILITY

    project = store.head()
    if revision_id is not None and project.revision_id != revision_id:
        raise StandaloneExportRefusal("revision_mismatch",
                                      "показывается голова хранилища; иной ревизии тут не берут")
    # 🔴 ONE REVISION SNAPSHOT FOR READING, ANALYSIS, AND THE SCENE
    # (08.09.2026, measurement S). There used to be two repetitions of the
    # same work, and both are named with a number at N=2000:
    # (1) bodies were read ONE AT A TIME (`get_asset` for each) — 2000
    #     transactions, each with its own `_read_state` and a full check of
    #     the head's assets: **22.79 s** against **0.229 s** for a single
    #     batch (99×);
    # (2) `analyze_project` reopened the store, read the same bodies again,
    #     and MATERIALIZED the project a SECOND time — even though the
    #     materialization was already built one line above, from the same
    #     bytes.
    # Here one set is read, and that same set travels into the analysis:
    # `analyze_revision` accepts a ready-made snapshot and CHECKS it against
    # the revision (revision identity, body digests for every address),
    # rather than taking it on faith.
    references = [output.geometry.bundle_sha256 for _, output, _ in project.geometry_references()]
    batch = getattr(store, "get_assets", None)
    if callable(batch) and references:
        loaded = batch(references)
        bundles = {digest: loaded[digest] for digest in references}
    else:
        bundles = {digest: store.get_asset(digest) for digest in references}
    from kir.geometry_materialization import materialize_project
    materialization = materialize_project(project, bundles)
    report = analyze_revision(project, lambda digest: bundles[digest] if digest in bundles
                              else store.get_asset(digest),
                              exact=exact, materialized=materialization)
    capabilities = sorted(set(consumer_capabilities) | {CLASH_CAPABILITY})
    # `refinement="auto"` — "take it from what's saved, if it is
    # registered"; a report object — "show EXACTLY this one"; `None` — the
    # capability is not declared at all, and the consumer sees the /3
    # schema, not empty /4 containers.
    refinement_report = None
    if refinement == "auto":
        refinement_report, reason = saved_refinement_report(store, project)
        if refinement_report is None:
            # The absence of an edit is not silence: the capability is
            # declared, the containers go out empty, and the reason travels
            # as a limitation line.
            refinement_report = {"revision_before": project.revision_id,
                                 "source_output_id": "—", "recomputed": [], "preserved": [],
                                 "needs_decision": [], "residue": [], "deviation": {},
                                 "lineage": {}, "decisions_digest": "—", "questions": [],
                                 "analysis_limits": [reason]}
    elif refinement is not None:
        refinement_report = refinement
    if refinement_report is not None:
        capabilities = sorted(set(capabilities) | {REFINEMENT_CAPABILITY})
    artifact = export_standalone_scene(materialization, consumer_capabilities=capabilities,
                                       clash_report=report.to_dict(),
                                       refinement_report=refinement_report)
    return artifact, report


def _main(argv=None) -> int:
    """`python -m kir.viewer.standalone_export <store> <scene.json>` — один ход."""
    import argparse
    import pathlib
    from kir.project_store import ProjectStore

    parser = argparse.ArgumentParser(description="сохранённый проект -> артефакт показа /3")
    parser.add_argument("store", help="каталог/файл сохранённого проекта")
    parser.add_argument("out", help="куда положить артефакт показа (JSON)")
    parser.add_argument("--no-exact", action="store_true", help="грубый анализ вместо точного")
    parser.add_argument("--no-refinement", action="store_true",
                        help="не объявлять способность показа остатка и вопросов")
    args = parser.parse_args(argv)
    store = ProjectStore.open(pathlib.Path(args.store))
    artifact, report = export_saved_project_scene(
        store, exact=not args.no_exact, refinement=None if args.no_refinement else "auto")
    target = pathlib.Path(args.out)
    target.write_text(artifact.dumps(), encoding="utf-8")
    data = artifact.to_dict()
    print(f"артефакт: {target} · схема {data['schema']}")
    print(f"  находок в отчёте {len(report.findings)}, показано {len(data['clash_findings'])}")
    for row in data["clash_findings"]:
        number = (f"{row['overlap_volume_mm3'] / 1e9:.3f} м³" if row["overlap_volume_mm3"]
                  else f"зазор {row['gap_mm']} мм" if row["gap_mm"] is not None else "—")
        print(f"    {row['status']} · {row['relation']} · {number}")
    for limit in data["clash_analysis_limits"]:
        print(f"  ограничение анализа: {limit}")
    record = data.get("refinement")
    if record:
        counts = record["counts"]
        print(f"  детализация: пересчитано {counts['recomputed']} · сохранено "
              f"{counts['preserved']} · нужно решение {counts['needs_decision']} "
              f"(всего {counts['total']}, не адресуемых сценой {counts['unaddressed']})")
        for row in data["refinement"]["residue"]:
            volume = "" if row["volume_mm3"] is None else f" · {row['volume_mm3']} мм³"
            print(f"    остаток: {row['what']} ×{row['count']} @ {row['address'][:12]}{volume}")
        deviation = record["deviation"]
        if deviation["value"] is not None:
            print(f"    отклонение: {deviation['measure']} = {deviation['value']} "
                  f"{deviation['unit']} (метод {deviation['method'] or 'не назван'})")
        for question in data["refinement_questions"]:
            print(f"    вопрос {question['question_id']} @ {question['address'][:12]}: "
                  + " | ".join(question["choices"]))
    for limit in data.get("refinement_analysis_limits", ()):
        print(f"  ограничение детализации: {limit}")
    return 0


# ── DECOMPILE display: the same scene bytes, the same reader ───────────────
#: 🔴 WHY A SECOND FACTORY, IF THE FRAME IS ONE (08.09.2026). It exists
#: exactly so that the frame stays one. A decompile of an existing building
#: is not an authored project: it has no project revision, no plan, no
#: materialization, no program, and `export_standalone_scene` requires
#: exactly these (`GeometryMaterialization` refuses immediately with
#: `explicit_materialization_required`). The decompile DOES have a scene,
#: though, built by THE SAME packer
#: (`kir.viewer.scene.scene_from_directory` -> `SceneBuilder`), meaning its
#: bytes are read by `_scene_index` letter for letter, the same way as a
#: project's bytes.
#:
#: So exactly ONE thing is described here — a DESCRIPTOR wrapped around
#: ready-made bytes, and it deliberately uses the same `kir-standalone-
#: display/1` schema as a project with no capabilities: the frame's reader
#: (`frontend/standalone/src/scene-reader.js`) is left WITHOUT A SINGLE
#: EDIT, meaning no second law about display gets introduced. The same
#: day's measurement: `bench_A` — 51 scene records, `k4_geom_wave2` — 3,
#: `mnvnk_k1_layers_walls` — 2.
#:
#: 🔴 WHAT THIS DESCRIPTOR DOES NOT DO, AND WHY THAT MATTERS MORE THAN WHAT
#: IT DOES. It DOES NOT MAKE UP project fields. There would be one way for
#: it to pass `kir.viewer.standalone.load_display_artifact` — by naming
#: `project_schema`, `plan_digest`, `materialization_digest`, and
#: `program_sha256`, which a decompile does not have; that would be a lie
#: with a precise address, and worse — a decompile's `project_id` would
#: collide in the `/project-status.json` panel with the name of a REAL
#: project, and the building's frame would mistake a neighbor's Store
#: snapshot for its own. Instead, `source` names the decompile with its own
#: closed schema, and the factory checks its own product ITSELF
#: (`_capture_descriptor_is_readable`) — against the same list the frame's
#: reader asks.
CAPTURE_SOURCE_SCHEMA = "kir-standalone-display-capture-source/1"
#: The closed list of the /1 descriptor's fields. It is also the single
#: point where a discrepancy with a project display would become visible as
#: A NUMBER, not a guess.
_DISPLAY_V1_FIELDS = ("schema", "source", "scene", "proxies", "omissions",
                      "unattributed_scene_ids", "consumer_contract", "claims")
#: What a DECOMPILE display does not assert. It differs from a project's by
#: two lines, and both are substantive: there is no authored program here
#: at all, and the bodies are hulls.
CAPTURE_DISPLAY_CLAIMS = {
    "scope": "decompile_display_export",
    "authored_program": "not_involved_this_is_an_independent_reading",
    "bodies": "hulls_not_solids_each_contains_the_element_and_is_usually_larger",
    "native_execution": "not_run", "native_equivalence": "not_claimed",
    "bim_coverage": "not_claimed", "clash_coverage": "not_claimed",
    "browser_rendering": "not_observed", "recipe_execution": "not_run",
    "digest_scope": "byte_integrity_not_rebuild_determinism_or_execution_proof",
}


@dataclass(frozen=True, slots=True, init=False)
class CaptureDisplayArtifact:
    """The decompile display's bytes and its manifest. Assembled only by
    the factory."""

    artifact_bytes: bytes
    transport: Mapping
    digest: str
    bodies: int

    def __init__(self):
        raise TypeError("use export_decompile_scene with ready scene bytes")


def _capture_descriptor_is_readable(payload: Mapping, header: Mapping) -> None:
    """One's own product — checked against the list the frame will use to
    interrogate it.

    🔴 WHAT IS CHECKED HERE IS WHAT THE READER REFUSES SILENTLY.
    `decodeDisplay` drops the display with one line, `invalid_display_input`,
    and no address: a human would see an empty frame, not a reason. Here the
    same conditions are named BEFORE sending, and by name.
    """
    fields = tuple(k for k in payload if k != "artifact_digest")
    if sorted(fields) != sorted(_DISPLAY_V1_FIELDS):
        raise StandaloneExportRefusal(
            "capture_descriptor_fields_differ",
            f"поля дескриптора разошлись со схемой /1: "
            f"{sorted(set(fields) ^ set(_DISPLAY_V1_FIELDS))}")
    # 🔴 THE DISPLAY'S CENSUS IS CHECKED AGAINST THE BYTE HEADER, NOT AGAINST
    # ITSELF. Checking `records` against `_scene_index(blob)` would be a
    # tautology (that is where they were taken from); the header instead
    # carries ITS OWN element count, computed by the scene packer. A
    # truncated census would travel to the frame silently: the reader does
    # not check the length of `records` against `counts`.
    records = payload["scene"]["records"]
    if len(records) != int(header["elements"]):
        raise StandaloneExportRefusal(
            "capture_scene_records_differ",
            f"записей показа {len(records)}, а элементов в байтах сцены "
            f"{header['elements']}")
    kinds = sorted(name for name in header["kinds"] if header["counts"][name])
    if payload["consumer_contract"]["required_scene_kinds"] != kinds:
        raise StandaloneExportRefusal(
            "capture_scene_kinds_differ",
            f"перечень родов сцены разошёлся с байтами: "
            f"{payload['consumer_contract']['required_scene_kinds']} != {kinds}")
    if payload["proxies"] or payload["omissions"]:
        raise StandaloneExportRefusal(
            "capture_display_has_no_proxies",
            "показ разбора не строит ни приближённых профилей, ни пропусков "
            "авторских выходов: их источник — материализация, которой нет")


def export_decompile_scene(blob: bytes, *, address: str, revision_id: str,
                           built_from: str) -> CaptureDisplayArtifact:
    """Ready-made decompile scene bytes -> a display artifact + manifest.

    `blob` is what `kir.viewer.scene.scene_from_directory` returned; not a
    single number about the geometry is recomputed here, the census is
    taken from the bytes themselves (`_scene_index`). `address` is what the
    tab addresses the building by, `revision_id` is the version of the
    WHOLE decompile source (`capture.source_version`, sha256 over L0 +
    sidecar + read mode), `built_from` is the on-disk directory the scene
    was built from.
    """
    if type(blob) is not bytes or not blob:
        raise StandaloneExportRefusal("explicit_scene_bytes_required",
                                      "ожидались готовые байты сцены разбора")
    if len(blob) > MAX_SCENE_BYTES:
        raise StandaloneExportRefusal("display_budget_exceeded",
                                      "binary scene exceeds the export byte limit")
    for name, value in (("address", address), ("revision_id", revision_id),
                        ("built_from", built_from)):
        if not isinstance(value, str) or not value:
            raise StandaloneExportRefusal(
                "capture_address_required",
                f"{name}: показ разбора обязан назвать, ЧТО он показывает")
    header, scene_records = _scene_index(blob)
    descriptor = {
        "schema": DISPLAY_SCHEMA,
        "source": {
            # The schema is named IN THE SOURCE ITSELF: a reader that
            # expected a project must recognize a decompile by a field, not
            # by the absence of fields.
            "schema": CAPTURE_SOURCE_SCHEMA,
            "kind": "decompile_capture",
            # Two fields the frame prints (`main.js`): the name and the
            # revision. The name carries a `capture:` PREFIX deliberately —
            # it travels to the screen next to project names, and the value
            # itself must make the distinction.
            "project_id": f"capture:{address}",
            "project_revision_id": revision_id,
            "built_from": built_from,
            # 🔴 AN EMPTY LIST HERE IS A FACT, NOT A GAP, which is why a
            # line stands next to it: a decompile has no authored outputs at
            # all, so there cannot be any "unshown outputs" either.
            # Everything the scene does NOT show is named by per-category
            # numbers in the application's response
            # (`kir.app.capture_scene.scene_of`), not by emptiness here.
            "operations": [],
            "operations_ru": ("у разбора нет авторских выходов: сцена — "
                              "НЕЗАВИСИМОЕ ЧТЕНИЕ документа, а не заявление "
                              "программы, и адрес каждого тела — id элемента "
                              "снимка, а не адрес выхода проекта"),
            "assertion": "independent",
            "assertion_ru": ("НЕЗАВИСИМОЕ чтение модели (разбор), не "
                             "заявление программы"),
        },
        "scene": {"schema": header["schema"],
                  "sha256": hashlib.sha256(blob).hexdigest(),
                  "size_bytes": len(blob), "encoding": "base64",
                  "units": header["units"], "origin_mm": header["origin_mm"],
                  "counts": header["counts"], "kind_codes": header["kinds"],
                  "records": scene_records},
        "proxies": [], "omissions": [],
        # Every decompile body is "not attributed to an authored output" —
        # and this is exactly the same field a project display uses to name
        # extra scene addresses.
        "unattributed_scene_ids": [row["display_id"] for row in scene_records],
        "consumer_contract": {
            "declared_capabilities": [],
            "required_proxy_capabilities": [],
            "required_scene_kinds": sorted(name for name in header["kinds"]
                                           if header["counts"][name]),
            "base_scene_fidelity": "preserve_per_element_codes",
            "proxy_rendering": "visually_distinct_with_claims_visible",
            "coordinates": "binary_relative_to_scene_origin__proxies_project_mm",
        },
        "claims": dict(CAPTURE_DISPLAY_CLAIMS),
    }
    payload = {**descriptor,
               "scene": {**descriptor["scene"],
                         "base64": base64.b64encode(blob).decode("ascii")}}
    _capture_descriptor_is_readable(payload, header)
    digest = _hash(payload)
    raw = _canonical({**payload, "artifact_digest": digest}).encode("utf-8")
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise StandaloneExportRefusal("display_budget_exceeded",
                                      "complete display artifact exceeds the export byte limit")
    from kir.viewer.standalone import TRANSPORT_SCHEMA  # there is one owner of the schema
    transport = {"schema": TRANSPORT_SCHEMA,
                 "artifact_sha256": hashlib.sha256(raw).hexdigest(),
                 "artifact_size_bytes": len(raw), "proxy_payloads": [],
                 "validation": "inert_bytes_schema_addresses_not_native_execution"}
    result = object.__new__(CaptureDisplayArtifact)
    object.__setattr__(result, "artifact_bytes", raw)
    object.__setattr__(result, "transport", _object(transport, "capture_transport"))
    object.__setattr__(result, "digest", digest)
    object.__setattr__(result, "bodies", len(scene_records))
    return result


__all__ = ["DISPLAY_SCHEMA", "DISPLAY_SCHEMA_V2", "DISPLAY_SCHEMA_V3", "DISPLAY_SCHEMA_V4",
           "StandaloneDisplayArtifact", "StandaloneExportRefusal",
           "export_standalone_scene", "export_saved_project_scene",
           "saved_refinement_report",
           "CAPTURE_DISPLAY_CLAIMS", "CAPTURE_SOURCE_SCHEMA",
           "CaptureDisplayArtifact", "export_decompile_scene"]


if __name__ == "__main__":
    raise SystemExit(_main())
