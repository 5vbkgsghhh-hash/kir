"""Inert display-file validation: the format of a saved scene, and nothing else.

🔴 13.09.2026. THE BROWSER WINDOW WAS REMOVED BY THE OWNER'S WORD («убрать
точно»), and with it the loopback inspector server that used to live at the end
of this file, `kir/viewer/assets.py` and `kir/app/**`. What stays is the part
that was never about a window: reading a display artifact, checking its bytes,
schema and addresses, and joining it to one saved-project snapshot. Those are
read by `standalone_export`, by the reference-surface and clash-display checks,
and by anything that needs to know whether a saved scene still describes the
project it names.

Loading asserts byte/schema/address integrity, NOT recipe/native execution or
geometry equivalence. No Project, GeometryMaterialization or display factory is
reconstructed. The original HTTP artifact bytes are retained; Python canonical
preview bytes cross to JS explicitly so 1.0/-0.0 are never rehashed by stringify.
Optional Store status matches declared output/module/body source claims to a
stored authored snapshot, not to historical compiler or native execution proof.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import struct
from typing import Mapping

from kir import spec
from kir.project import (PROJECT_SCHEMA, PROJECT_SCHEMA_V2, _canonical, _digest, _hash,
                         _key, _object, _thaw, output_id)
from kir.viewer.blend_preview import PREVIEW_SCHEMA, PREVIEW_POLICY, REQUIRED_CONSUMER_CAPABILITY
from kir.viewer.codec import SCENE_MAGIC, SCENE_SCHEMA, STRIDE
from kir.viewer.standalone_export import (DISPLAY_SCHEMA, DISPLAY_SCHEMA_V2, DISPLAY_SCHEMA_V3,
                                          DISPLAY_SCHEMA_V4,
                                          MAX_ARTIFACT_BYTES, MAX_SCENE_BYTES)
from kir.viewer.reference_surfaces import SURFACE_SCHEMA, SURFACE_POLICY, SURFACE_CAPABILITY, SURFACE_CLAIMS
from kir.viewer.refinement_display import (REFINEMENT_CAPABILITY, REFINEMENT_CLAIMS,
                                           REFINEMENT_RECORD_SCHEMA, SET_NAMES)
from kir.viewer.clash_findings import (CLASH_CAPABILITY, CLASH_CLAIMS, FINDING_RELATIONS,
                                       FINDING_STATUSES, HULL_SOURCES)


TRANSPORT_SCHEMA = "kir-standalone-transport/1"
TRANSPORT_SCHEMA_V2 = "kir-standalone-transport/2"
TRANSPORT_SCHEMA_V3 = "kir-standalone-transport/3"
TRANSPORT_SCHEMA_V4 = "kir-standalone-transport/4"
PROJECT_STATUS_SCHEMA = "kir-standalone-project-status/1"
MAX_STATUS_BYTES = 2 * 1024 * 1024
_KINDS = {"box": 0, "capsule": 1, "prism": 2, "mesh": 3}
_FIDELITIES = {"exact": 0, "shaped": 1, "box_only": 2, "degenerate": 3, "no_body": 4}


class DisplayInputRefusal(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


def _require(condition, message):
    if not condition:
        raise DisplayInputRefusal("invalid_display_artifact", message)


def _json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result
    def constant(value):
        raise DisplayInputRefusal("invalid_display_artifact", f"nonfinite JSON number: {value}")
    value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=pairs, parse_constant=constant)
    stack = [(value, 0)]
    visited = 0
    while stack:
        item, depth = stack.pop()
        visited += 1
        _require(depth <= 64 and visited <= 2_000_000, "JSON nesting/item budget exceeded")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, float):
            _require(math.isfinite(item), "nonfinite JSON number")
    return value


def _fields(value, fields, path):
    _require(isinstance(value, dict) and set(value) == set(fields.split()), f"{path}: unsupported fields")


def _integer(value):
    return type(value) is int and 0 <= value <= 2**32 - 1


def _scene(blob):
    _require(len(blob) <= MAX_SCENE_BYTES and blob[:8] == SCENE_MAGIC, "scene magic/size differs")
    length = struct.unpack_from("<I", blob, 8)[0]
    base = 12 + length
    _require(base <= len(blob) and base % 4 == 0, "scene header length/alignment differs")
    header = _json(blob[12:base])
    _require(header["schema"] == SCENE_SCHEMA and header["units"] == "mm", "scene schema/units differ")
    _require(_canonical(header["kinds"]) == _canonical(_KINDS)
             and _canonical(header["fidelity_codes"]) == _canonical(_FIDELITIES), "unknown scene kind/fidelity contract")
    for name in ("categories", "levels"):
        _require(isinstance(header[name], list) and all(isinstance(value, str) for value in header[name]),
                 f"{name}: expected string table (list[str])")
    _require(len(header["origin_mm"]) == 3 and all(type(x) in (int, float) and math.isfinite(x) for x in header["origin_mm"]), "invalid scene origin")
    counts, n = header["counts"], header["elements"]
    _fields(counts, "box capsule prism mesh mesh_triangles mesh_vertices", "scene.counts")
    _require(_integer(n) and all(_integer(x) for x in counts.values()), "invalid scene counts")
    _require(_integer(header["body_bytes"]) and header["body_bytes"] == len(blob) - base, "scene body length differs")
    buffers, offset = {}, 0
    for span in header["buffers"]:
        _fields(span, "name offset length stride", "scene.buffer")
        name, size, stride = span["name"], span["length"], span["stride"]
        _require(name not in buffers and name in {*STRIDE, "ids", "labels"}, "unknown/duplicate scene buffer")
        _require(_integer(size) and _integer(span["offset"]) and span["offset"] == offset
                 and _integer(stride) and stride == STRIDE.get(name, 1), "scene buffer layout differs")
        alignment = 4 if stride % 4 == 0 else 2 if stride == 2 else 1
        _require(size % stride == 0 and (base + offset) % alignment == 0 and offset + size <= len(blob) - base, "scene buffer range/alignment differs")
        buffers[name] = blob[base + offset:base + offset + size]
        offset += size
    _require(set(buffers) == {*STRIDE, "ids", "labels"} and offset == len(blob) - base, "missing/trailing scene buffers")
    for name, stride in STRIDE.items():
        if name.startswith("elem_"):
            _require(len(buffers[name]) == n * stride, f"{name}: element count differs")
    # SceneBuilder joins records with literal LF, not Unicode line breaks.
    # The element count distinguishes an empty scene from one empty label.
    _require(n != 0 or not (buffers["ids"] or buffers["labels"]), "empty scene has string records")
    ids = buffers["ids"].decode("utf-8").split("\n") if n else []
    labels = buffers["labels"].decode("utf-8").split("\n") if n else []
    _require(len(ids) == len(labels) == n and len(set(ids)) == n and all(ids), "scene IDs/labels differ")
    for name in ("box", "capsule", "prism_z", "prism_xy", "mesh_vtx"):
        _require(all(math.isfinite(x[0]) for x in struct.iter_unpack("<f", buffers[name])), f"{name}: nonfinite coordinate")
    _require(len(buffers["box"]) == counts["box"] * 24 and len(buffers["capsule"]) == counts["capsule"] * 28
             and len(buffers["prism_z"]) == counts["prism"] * 8 and len(buffers["mesh_vtx"]) == counts["mesh_vertices"] * 12
             and len(buffers["mesh_tri"]) == counts["mesh_triangles"] * 12, "primitive counts differ")
    for row in struct.iter_unpack("<6f", buffers["box"]):
        _require(all(x >= 0 for x in row[3:]), "negative box half extent")
    for row in struct.iter_unpack("<7f", buffers["capsule"]):
        _require(row[6] >= 0, "negative capsule radius")
    for low, high in struct.iter_unpack("<2f", buffers["prism_z"]):
        _require(low <= high, "inverted prism interval")
    arrays = {}
    for name, count, total in (("prism_ofs", counts["prism"], len(buffers["prism_xy"]) // 8),
                                ("mesh_ofs", counts["mesh"], counts["mesh_triangles"]),
                                ("mesh_vofs", counts["mesh"], counts["mesh_vertices"])):
        values = [x[0] for x in struct.iter_unpack("<I", buffers[name])]
        _require(len(values) == count + 1 and values[0] == 0 and values[-1] == total
                 and all(a < b for a, b in zip(values, values[1:])), f"{name}: invalid prefix sums")
        arrays[name] = values
    for start, end in zip(arrays["prism_ofs"], arrays["prism_ofs"][1:]):
        _require(end - start >= 3, "prism has fewer than three vertices")
    for slot in range(counts["mesh"]):
        t0, t1 = arrays["mesh_ofs"][slot:slot + 2]
        v0, v1 = arrays["mesh_vofs"][slot:slot + 2]
        _require(all(v0 <= x[0] < v1 for x in struct.iter_unpack("<I", buffers["mesh_tri"][t0 * 12:t1 * 12])), "mesh index crosses its vertex slot")
    slots = [x[0] for x in struct.iter_unpack("<I", buffers["elem_slot"])]
    kinds = list(buffers["elem_kind"])
    for name, kind in _KINDS.items():
        starts = [slot for slot, code in zip(slots, kinds) if code == kind]
        _require((not starts and counts[name] == 0) or (starts and starts[0] == 0 and starts[-1] < counts[name]
                 and all(a < b for a, b in zip(starts, starts[1:]))), f"{name}: incomplete/overlapping element slots")
    _require(all(x in _KINDS.values() for x in kinds) and all(x in _FIDELITIES.values() for x in buffers["elem_fidelity"]), "unknown element kind/fidelity")
    for name, table in (("elem_cat", header["categories"]), ("elem_level", header["levels"])):
        _require(all(x[0] < len(table) for x in struct.iter_unpack("<H", buffers[name])), f"{name}: string table index exceeds bounds")
    rows = [{"display_id": oid, "scene_element_index": index, "kind": next(k for k, v in _KINDS.items() if v == kinds[index]),
             "fidelity_code": fid, "fidelity": next(k for k, v in _FIDELITIES.items() if v == fid)}
            for index, (oid, fid) in enumerate(zip(ids, buffers["elem_fidelity"]))]
    return header, rows


@dataclass(frozen=True, slots=True)
class ValidatedDisplayInput:
    """Inert byte integrity result, not an executed authoring/materialization result."""
    original_bytes: bytes
    data: Mapping
    transport: Mapping


def _validate_clash_findings(data, *, known_ids: set) -> None:
    """Check the finding records just as strictly as surfaces and proxies.

    🔴 WHY ADDRESSES ARE CHECKED AGAINST THE SCENE. A finding whose side is
    not shown cannot be drawn; accepting it silently would mean showing a
    list in which part of the lines point at nothing. Such ones are shipped
    out to `clash_analysis_limits` back at emission time
    (`clash_findings.py`), and are not supposed to arrive here — and if they
    did, that is a refusal, not "let's skip it".
    """
    _require(data["clash_claims"] == dict(CLASH_CLAIMS), "unsupported clash claims")
    for item in data["clash_analysis_limits"]:
        _require(isinstance(item, str) and item.strip(), "invalid clash analysis limit")
    seen = set()
    for row in data["clash_findings"]:
        _fields(row, "finding_id display_id_a display_id_b status relation depth_mm "
                     "overlap_volume_mm3 gap_mm hull_source_a hull_source_b refusal_ru "
                     "required_clearance_mm deficit_mm clearance_source", "clash finding")
        _require(isinstance(row["finding_id"], str) and row["finding_id"].strip()
                 and row["finding_id"] not in seen, "invalid or duplicate finding id")
        seen.add(row["finding_id"])
        _require(row["status"] in FINDING_STATUSES, "unsupported finding status")
        _require(row["relation"] is None or row["relation"] in FINDING_RELATIONS, "unsupported finding relation")
        for side in ("hull_source_a", "hull_source_b"):
            _require(row[side] in HULL_SOURCES, "unsupported hull source")
        for side in ("display_id_a", "display_id_b"):
            _require(isinstance(row[side], str) and row[side] in known_ids, "finding side is not addressed by this scene")
        for key in ("depth_mm", "overlap_volume_mm3", "gap_mm"):
            value = row[key]
            _require(value is None or (type(value) in (int, float) and not isinstance(value, bool)
                                       and math.isfinite(float(value))), f"invalid {key}")
        _require(row["refusal_ru"] is None or (isinstance(row["refusal_ru"], str) and row["refusal_ru"].strip()),
                 "invalid refusal text")
        # The numbers must agree with the relation: `clear` with a volume,
        # or `intersect` without one, is an edited record, not a finding.
        for key in ("required_clearance_mm", "deficit_mm"):
            value = row[key]
            _require(value is None or (type(value) in (int, float) and not isinstance(value, bool)
                                       and math.isfinite(float(value)) and float(value) >= 0.0),
                     f"invalid {key}")
        _require(row["clearance_source"] is None
                 or (isinstance(row["clearance_source"], str) and row["clearance_source"].strip()),
                 "invalid clearance source")
        # A violated clearance must name the REQUIREMENT, the DEFICIT, and
        # the CARRIER: otherwise "violated" is a word with no number and no
        # owner of the decision.
        _require(row["status"] != "clearance_violated"
                 or (row["required_clearance_mm"] is not None and row["deficit_mm"] is not None
                     and row["clearance_source"] and row["gap_mm"] is not None),
                 "a violated clearance must name its requirement, deficit and source")
        if row["relation"] == "clear":
            _require(not row["overlap_volume_mm3"], "clear finding cannot carry an overlap volume")
        elif row["relation"] in ("intersect", "contained"):
            # 🔴 THE VOLUME REQUIREMENT APPLIES TO A PROVEN FINDING, NOT TO
            # ANY FINDING (measured 07.09.2026). The old line required a
            # volume for EVERY intersection, and a coarse phase became
            # unshowable in principle: `exact=False` on
            # `examples/podium_passage.py` gives 5 `possible /
            # intersect|contained` findings with `overlap_volume_mm3 = None`
            # (a BOUNDING-BOX comparison has no volume and cannot have one),
            # and the loader rejected the WHOLE artifact —
            # `invalid_display_artifact: intersecting finding must carry its
            # volume`. That is, the application could show only exact
            # analysis, and "we looked coarsely" could not be expressed at
            # all. `possible` is exactly that claim: "the hulls intersected,
            # the bodies were not judged", and a volume number on it would
            # have been MADE UP. The proven kinds (`confirmed`,
            # `clearance_violated`) must still name a volume: for them it is
            # MEASURED by the exact phase.
            _require(bool(row["overlap_volume_mm3"]) or row["status"] == "possible",
                     "a proven intersection must carry its volume")


def _validate_refinement(data, *, known_ids: set) -> None:
    """Check the refinement records just as strictly as findings and
    surfaces.

    🔴 WHAT EXACTLY IS GUARDED, AND WHY EXACTLY THIS.

    1. THE THREE SETS DO NOT OVERLAP. An output landing in two of them would
       mean it was both recomputed and preserved at the same time — that is,
       nothing definite is said about it.
    2. THE SUM OF THE COUNTERS MATCHES `total`. The count is taken from the
       REPORT, before address translation; without this equality an output
       could disappear silently.
    3. NO MORE IS SHOWN THAN WAS DECLARED. Showing more than was counted
       means showing something made up.
    4. A DEVIATION NUMBER WITHOUT A NAMED MEASURE IS NOT ACCEPTED. A measure
       is what the number is denominated in; without it "−5000000" means
       nothing.
    5. A QUESTION WITH NO OPTIONS IS NOT A QUESTION. The choice is made by
       the human, and they must choose from the declared list.
    """
    _require(data["refinement_claims"] == dict(REFINEMENT_CLAIMS), "unsupported refinement claims")
    for item in data["refinement_analysis_limits"]:
        _require(isinstance(item, str) and item.strip(), "invalid refinement analysis limit")
    record = data["refinement"]
    if record:
        _fields(record, "schema source_display_id revision_before revision_after recomputed "
                        "preserved needs_decision counts residue deviation decisions_digest",
                "refinement")
        _require(record["schema"] == REFINEMENT_RECORD_SCHEMA, "unsupported refinement record schema")
        for key in ("source_display_id", "revision_before", "decisions_digest"):
            _require(isinstance(record[key], str) and record[key].strip(), f"invalid {key}")
        _require(record["revision_after"] is None
                 or (isinstance(record["revision_after"], str) and record["revision_after"].strip()),
                 "invalid revision_after")
        _fields(record["counts"], "recomputed preserved needs_decision total unaddressed", "counts")
        for key, value in record["counts"].items():
            _require(type(value) is int and value >= 0, f"invalid counts.{key}")
        shown = {}
        for name in SET_NAMES:
            rows = record[name]
            _require(type(rows) is list and all(type(item) is str and item in known_ids
                                                for item in rows), f"invalid {name} addresses")
            _require(len(rows) == len(set(rows)), f"duplicate address in {name}")
            _require(len(rows) <= record["counts"][name],
                     f"{name}: показано больше, чем насчитано отчётом")
            shown[name] = set(rows)
        _require(not (shown["recomputed"] & shown["preserved"])
                 and not (shown["recomputed"] & shown["needs_decision"])
                 and not (shown["preserved"] & shown["needs_decision"]),
                 "the three sets must be disjoint")
        counts = record["counts"]
        _require(counts["recomputed"] + counts["preserved"] + counts["needs_decision"]
                 == counts["total"], "the three counts must sum to the declared total")
        _require(counts["unaddressed"] <= counts["total"], "unaddressed exceeds the total")
        _require(counts["total"] - counts["unaddressed"]
                 == sum(len(shown[name]) for name in SET_NAMES),
                 "shown addresses do not match total minus unaddressed")
        for row in record["residue"]:
            _fields(row, "address what count volume_mm3", "residue row")
            _require(isinstance(row["address"], str) and row["address"].strip()
                     and isinstance(row["what"], str) and row["what"].strip(), "invalid residue address/what")
            _require(type(row["count"]) is int and row["count"] >= 0, "invalid residue count")
            _require(row["volume_mm3"] is None
                     or (type(row["volume_mm3"]) in (int, float) and not isinstance(row["volume_mm3"], bool)
                         and math.isfinite(float(row["volume_mm3"]))), "invalid residue volume")
        deviation = record["deviation"]
        _fields(deviation, "measure value unit method", "deviation")
        for key in ("measure", "unit", "method"):
            _require(deviation[key] is None or (isinstance(deviation[key], str)
                                                and deviation[key].strip()), f"invalid deviation.{key}")
        value = deviation["value"]
        numbers = value if type(value) is list else ([] if value is None else [value])
        for item in numbers:
            _require(type(item) in (int, float) and not isinstance(item, bool)
                     and math.isfinite(float(item)), "invalid deviation value")
        _require(value is None or deviation["measure"] is not None,
                 "a deviation number must name its measure")
    else:
        _require(not data["refinement_questions"],
                 "questions without a refinement record have nothing to address")
    seen = set()
    for question in data["refinement_questions"]:
        _fields(question, "question_id address choices why", "question")
        _require(isinstance(question["question_id"], str) and question["question_id"].strip()
                 and question["question_id"] not in seen, "invalid or duplicate question id")
        seen.add(question["question_id"])
        _require(isinstance(question["address"], str) and question["address"].strip(),
                 "invalid question address")
        _require(type(question["choices"]) is list and question["choices"]
                 and all(isinstance(item, str) and item.strip() for item in question["choices"])
                 and len(question["choices"]) == len(set(question["choices"])),
                 "a question must carry a closed, non-empty list of distinct choices")
        _require(isinstance(question["why"], str) and question["why"].strip(), "invalid question reason")


def load_display_artifact(raw: bytes) -> ValidatedDisplayInput:
    try:
        _require(type(raw) is bytes and len(raw) <= MAX_ARTIFACT_BYTES, "expected bounded UTF-8 bytes")
        data = _json(raw)
        _require(isinstance(data, dict) and data.get("schema") in (
            DISPLAY_SCHEMA, DISPLAY_SCHEMA_V2, DISPLAY_SCHEMA_V3,
            DISPLAY_SCHEMA_V4), "unsupported display schema")
        has_refinement = data["schema"] == DISPLAY_SCHEMA_V4
        has_clash = data["schema"] in (DISPLAY_SCHEMA_V3, DISPLAY_SCHEMA_V4)
        # /3 is a superstructure over /2, /4 over /3: combinations of
        # capabilities do not spawn versions, or one would be needed for
        # every single combination.
        has_surfaces = data["schema"] in (DISPLAY_SCHEMA_V2, DISPLAY_SCHEMA_V3, DISPLAY_SCHEMA_V4)
        fields = "schema source scene proxies omissions unattributed_scene_ids consumer_contract claims artifact_digest"
        _fields(data, fields + (" surfaces surface_refusals" if has_surfaces else "")
                + (" clash_findings clash_analysis_limits clash_claims" if has_clash else "")
                + (" refinement refinement_questions refinement_analysis_limits refinement_claims"
                   if has_refinement else ""), "artifact")
        if has_surfaces:
            _require(type(data["surfaces"]) is list and type(data["surface_refusals"]) is list, "surface records must be arrays")
        if has_clash:
            _require(type(data["clash_findings"]) is list
                     and type(data["clash_analysis_limits"]) is list, "clash records must be arrays")
        if has_refinement:
            _require(type(data["refinement"]) is dict
                     and type(data["refinement_questions"]) is list
                     and type(data["refinement_analysis_limits"]) is list,
                     "refinement containers must be an object and arrays")
        _digest(data["artifact_digest"], "artifact_digest")
        _require(_hash({k: v for k, v in data.items() if k != "artifact_digest"}) == data["artifact_digest"], "artifact digest differs")
        source, scene, contract = data["source"], data["scene"], data["consumer_contract"]
        _fields(source, "project_id project_revision_id project_schema parent_revision_id ir_version plan_digest materialization_digest program_sha256 operations body_sources", "source")
        _key(source["project_id"], "project_id")
        _require(source["project_schema"] in (PROJECT_SCHEMA, PROJECT_SCHEMA_V2)
                 and source["ir_version"] == spec.IR_VERSION, "unsupported source schema/version")
        for key in ("project_revision_id", "plan_digest", "materialization_digest", "program_sha256"):
            _digest(source[key], key)
        if source["parent_revision_id"] is not None:
            _digest(source["parent_revision_id"], "parent_revision_id")
        _fields(scene, "schema sha256 size_bytes encoding units origin_mm counts kind_codes records base64", "scene")
        blob = base64.b64decode(scene["base64"], validate=True)
        _require(scene["encoding"] == "base64" and _integer(scene["size_bytes"]) and scene["size_bytes"] == len(blob)
                 and scene["sha256"] == hashlib.sha256(blob).hexdigest(), "scene byte digest/size differs")
        header, rows = _scene(blob)
        for key in ("schema", "units", "origin_mm", "counts"):
            _require(_canonical(scene[key]) == _canonical(header[key]), f"scene.{key} differs from binary")
        _require(_canonical(scene["kind_codes"]) == _canonical(header["kinds"])
                 and _canonical(scene["records"]) == _canonical(rows), "scene element bindings differ")
        _fields(contract, "declared_capabilities required_proxy_capabilities required_scene_kinds base_scene_fidelity proxy_rendering coordinates", "consumer_contract")
        expected_caps = sorted(([REQUIRED_CONSUMER_CAPABILITY] if data["proxies"] else [])
                               + ([SURFACE_CAPABILITY] if has_surfaces and data["surfaces"] else []))
        declared = contract["declared_capabilities"]
        allowed = {REQUIRED_CONSUMER_CAPABILITY, SURFACE_CAPABILITY} if has_surfaces else {REQUIRED_CONSUMER_CAPABILITY}
        if has_clash:
            allowed = allowed | {CLASH_CAPABILITY}
            expected_caps = sorted(expected_caps + [CLASH_CAPABILITY])
        if has_refinement:
            allowed = allowed | {REFINEMENT_CAPABILITY}
            expected_caps = sorted(expected_caps + [REFINEMENT_CAPABILITY])
        _require(type(declared) is list and all(type(cap) is str for cap in declared)
                 and declared == sorted(set(declared)) and not set(declared) - allowed
                 and (not has_surfaces or SURFACE_CAPABILITY in declared
                      # For /3, surface containers always exist; the
                      # capability is required only if something is in them.
                      or (has_clash and not data["surfaces"]))
                 and (not has_clash or CLASH_CAPABILITY in declared
                      # For /4, finding containers always exist; the
                      # capability is required only if something is in them.
                      or (has_refinement and not data["clash_findings"]))
                 and (not has_refinement or REFINEMENT_CAPABILITY in declared)
                 and contract["required_proxy_capabilities"] == expected_caps
                 and set(expected_caps) <= set(declared), "missing/unsupported proxy capability")
        _require(contract["required_scene_kinds"] == sorted(k for k in _KINDS if header["counts"][k])
                 and contract["base_scene_fidelity"] == "preserve_per_element_codes"
                 and contract["proxy_rendering"] == "visually_distinct_with_claims_visible"
                 and contract["coordinates"] == "binary_relative_to_scene_origin__proxies_project_mm", "unsupported consumer contract")
        operations = {}
        for row in source["operations"]:
            fields = "op_id display_id instance_key module_key output_key module_definition_digest op operation_sha256 authored_output_sha256 display_status"
            _fields(row, fields + (" geometry_reference" if "geometry_reference" in row else ""), "source.operation")
            for key in ("operation_sha256", "authored_output_sha256", "module_definition_digest"):
                _digest(row[key], key)
            _key(row["module_key"], "module_key")
            _require(isinstance(row["op"], str) and row["op"], "invalid source operation label")
            _require(row["op_id"] == output_id(source["project_id"], row["instance_key"], row["output_key"])
                     and row["display_id"] == "p1/" + row["op_id"] and row["display_id"] not in operations, "source output address differs")
            operations[row["display_id"]] = row
        base_ids = {row["display_id"] for row in rows}
        proxy_ids, proxy_payloads = set(), []
        for record in data["proxies"]:
            _fields(record, "display_id preview", "proxy")
            oid, preview = record["display_id"], record["preview"]
            _require(oid in operations and oid not in base_ids | proxy_ids, "duplicate/foreign proxy address")
            _fields(preview, "schema policy required_consumer_capability source representation units mesh_space mesh interpolation claims preview_digest", "preview")
            _require(preview["schema"] == PREVIEW_SCHEMA and preview["policy"] == PREVIEW_POLICY
                     and preview["required_consumer_capability"] == REQUIRED_CONSUMER_CAPABILITY
                     and preview["representation"] == "approximate_profile_proxy" and preview["units"] == "mm"
                     and preview["mesh_space"] == "project", "unsupported proxy policy")
            _fields(preview["source"], "op_id operation_sha256 ir_version compiler_plan_digest", "preview.source")
            _require(operations[oid]["op"] == "create_solid_blend" and preview["source"]["op_id"] == operations[oid]["op_id"]
                     and preview["source"]["operation_sha256"] == operations[oid]["operation_sha256"]
                     and preview["source"]["ir_version"] == source["ir_version"], "proxy source binding differs")
            _digest(preview["source"]["compiler_plan_digest"], "preview plan digest")
            _require(preview["claims"] == {"profile_endpoints": "copied_from_normalized_authored_profiles",
                "native_equivalence": "unverified", "native_execution": "not_run", "containment": "not_claimed",
                "mesh_error_bound": "not_measured", "clash_eligibility": "none", "bim_semantics": "not_claimed",
                "side_surface": "display_interpolation_not_native_contract"}, "unsupported proxy claims")
            _fields(preview["mesh"], "vertices_mm triangles", "proxy.mesh")
            vertices, triangles = preview["mesh"]["vertices_mm"], preview["mesh"]["triangles"]
            _require(3 <= len(vertices) <= 4096 and 1 <= len(triangles) <= 4096, "proxy mesh budget exceeded")
            _require(all(isinstance(p, list) and len(p) == 3 and all(type(x) in (int, float) and math.isfinite(x) for x in p) for p in vertices), "invalid proxy vertices")
            _require(all(isinstance(t, list) and len(t) == 3 and all(type(i) is int and 0 <= i < len(vertices) for i in t) for t in triangles), "invalid proxy indices")
            payload = _canonical({k: v for k, v in preview.items() if k != "preview_digest"}).encode("utf-8")
            _require(hashlib.sha256(payload).hexdigest() == preview["preview_digest"], "proxy digest differs")
            proxy_payloads.append({"display_id": oid, "sha256": preview["preview_digest"], "payload_base64": base64.b64encode(payload).decode("ascii")})
            proxy_ids.add(oid)
        surface_ids, surface_payloads, refused_surfaces = set(), [], set()
        if has_surfaces:
            base_by_id = {row["display_id"]: row for row in rows}
            source_by_op = {row["op_id"]: row for row in source["operations"]}
            source_position = {row["op_id"]: index for index, row in enumerate(source["operations"])}
            surface_kinds = {"create_wall": "wall_axis_surface", "create_floor_by_contour": "floor_datum_surface"}
            for record in data["surfaces"]:
                _fields(record, "display_id preview", "surface")
                oid, preview = record["display_id"], record["preview"]
                _require(oid in operations and oid not in surface_ids | proxy_ids, "duplicate/foreign surface address")
                row = operations[oid]
                _require(row["op"] in surface_kinds and "geometry_reference" not in row
                         and (oid not in base_by_id or base_by_id[oid]["fidelity"] == "no_body"),
                         "surface cannot replace a known body or incompatible source")
                _fields(preview, "schema policy required_consumer_capability source representation surface_kind units mesh_space mesh claims preview_digest", "surface.preview")
                _require(preview["schema"] == SURFACE_SCHEMA and preview["policy"] == SURFACE_POLICY
                         and preview["required_consumer_capability"] == SURFACE_CAPABILITY
                         and preview["representation"] == "authored_reference_surface"
                         and preview["surface_kind"] == surface_kinds[row["op"]]
                         and preview["units"] == "mm" and preview["mesh_space"] == "project"
                         and preview["claims"] == dict(SURFACE_CLAIMS), "unsupported reference surface policy/claims")
                origin = preview["source"]
                _fields(origin, "op_id operation_sha256 ir_version compiler_plan_digest dependencies", "surface.source")
                _require(origin["op_id"] == row["op_id"] and origin["operation_sha256"] == row["operation_sha256"]
                         and origin["ir_version"] == source["ir_version"]
                         and origin["compiler_plan_digest"] == source["plan_digest"], "surface source/plan binding differs")
                dependencies = origin["dependencies"]
                _require(type(dependencies) is list and 1 <= len(dependencies) <= 2, "surface requires literal level dependencies")
                _require(preview["surface_kind"] != "floor_datum_surface" or len(dependencies) == 1,
                         "floor surface requires exactly one level dependency")
                seen, last = set(), -1
                for dependency in dependencies:
                    _fields(dependency, "op_id operation_sha256", "surface.dependency")
                    dep = source_by_op.get(dependency["op_id"])
                    _require(dep is not None and dep["op"] == "create_level" and dep["op_id"] not in seen
                             and dep["operation_sha256"] == dependency["operation_sha256"]
                             and last < source_position[dep["op_id"]] < source_position[row["op_id"]],
                             "surface dependency identity/digest/order differs")
                    last = source_position[dep["op_id"]]
                    seen.add(dep["op_id"])
                _fields(preview["mesh"], "vertices_mm triangles", "surface.mesh")
                vertices, triangles = preview["mesh"]["vertices_mm"], preview["mesh"]["triangles"]
                _require(type(vertices) is list and type(triangles) is list
                         and 3 <= len(vertices) <= 4096 and 1 <= len(triangles) <= 4096, "surface mesh budget exceeded")
                _require(all(type(p) is list and len(p) == 3 and all(type(x) in (int, float) and math.isfinite(x) for x in p)
                             for p in vertices), "invalid surface vertices")
                _require(all(type(t) is list and len(t) == 3 and len(set(t)) == 3
                             and all(type(i) is int and 0 <= i < len(vertices) for i in t) for t in triangles), "invalid surface triangles")
                payload = _canonical({key: value for key, value in preview.items() if key != "preview_digest"}).encode("utf-8")
                _require(hashlib.sha256(payload).hexdigest() == preview["preview_digest"], "surface digest differs")
                surface_payloads.append({"display_id": oid, "sha256": preview["preview_digest"],
                                         "payload_base64": base64.b64encode(payload).decode("ascii")})
                surface_ids.add(oid)
            for refusal in data["surface_refusals"]:
                _fields(refusal, "display_id code detail", "surface.refusal")
                oid = refusal["display_id"]
                _require(oid in operations and operations[oid]["op"] in surface_kinds
                         and oid not in surface_ids | refused_surfaces
                         and type(refusal["code"]) is str and bool(refusal["code"])
                         and type(refusal["detail"]) is str, "invalid surface refusal")
                refused_surfaces.add(oid)
            # Coverage completeness is asked only where the surface
            # machinery WAS RUNNING. For /3 without the declared surface-
            # display capability the containers are empty by construction,
            # and demanding coverage from them would mean judging something
            # that never ran.
            surfaces_ran = SURFACE_CAPABILITY in contract["declared_capabilities"]
            _require(not surfaces_ran or surface_ids | refused_surfaces
                     == {oid for oid, row in operations.items() if row["op"] in surface_kinds},
                     "surface result/refusal coverage differs")
            _require(surfaces_ran or not (surface_ids | refused_surfaces),
                     "surface records without the declared capability")
        omitted = {}
        for row in data["omissions"]:
            oid = row["display_id"]
            _require(oid in operations and oid not in omitted and row["scope"] == "direct_output_address"
                     and isinstance(row["code"], str) and row["code"], "invalid omission")
            _require(all(_canonical(row[key]) == _canonical(value) for key, value in operations[oid].items()), "omission source differs")
            omitted[oid] = row
        for oid, row in operations.items():
            expected = ("base_scene_record" if oid in base_ids else "approximate_proxy_record" if oid in proxy_ids
                        else "authored_surface_record" if oid in surface_ids else "omitted")
            _require(row["display_status"] == expected and ((oid in omitted) == (expected == "omitted")), "output display status differs")
        _require(data["unattributed_scene_ids"] == [row["display_id"] for row in rows if row["display_id"] not in operations], "unattributed scene addresses differ")
        references = {row["op_id"]: row["geometry_reference"] for row in operations.values() if "geometry_reference" in row}
        body_sources = {row["op_id"]: row for row in source["body_sources"]}
        _require(set(references) == set(body_sources) and len(body_sources) == len(source["body_sources"]), "body source addresses differ")
        for oid, ref in references.items():
            _fields(ref, "kind bundle_sha256 body_sha256", "geometry_reference")
            _require(ref["kind"] == "occt_brep_mesh" and ref["bundle_sha256"] == body_sources[oid]["source_bundle_sha256"]
                     and ref["body_sha256"] == body_sources[oid]["source_body_sha256"], "body source digests differ")
            _digest(ref["bundle_sha256"], "bundle digest")
            _digest(ref["body_sha256"], "body digest")
        _require(data["claims"] == {"scope": "authored_display_export", "authored_program": "unchanged", "native_execution": "not_run",
            "native_equivalence": "not_claimed", "bim_coverage": "not_claimed", "clash_coverage": "not_claimed",
            "browser_rendering": "not_observed", "recipe_execution": "not_run",
            "digest_scope": "byte_integrity_not_rebuild_determinism_or_execution_proof"}, "unsupported artifact claims")
        transport = {"schema": TRANSPORT_SCHEMA_V4 if has_refinement else
                     TRANSPORT_SCHEMA_V3 if has_clash else
                     TRANSPORT_SCHEMA_V2 if has_surfaces else TRANSPORT_SCHEMA,
                     "artifact_sha256": hashlib.sha256(raw).hexdigest(),
                     "artifact_size_bytes": len(raw), "proxy_payloads": proxy_payloads,
                     "validation": "inert_bytes_schema_addresses_not_native_execution"}
        if has_surfaces:
            transport["surface_payloads"] = surface_payloads
        if has_clash:
            _validate_clash_findings(data, known_ids=set(operations))
        if has_refinement:
            _validate_refinement(data, known_ids=set(operations))
        return ValidatedDisplayInput(raw, _object(data, "display_input"), _object(transport, "transport"))
    except DisplayInputRefusal:
        raise
    except (ValueError, KeyError, TypeError, IndexError, OverflowError, RecursionError, struct.error, binascii.Error) as exc:
        raise DisplayInputRefusal("invalid_display_artifact", str(exc)) from exc


def _project_status(validated, project_store):
    """Join frozen display identity to one mutable Store snapshot, never Revit.

    Historical revision lookup is separately immutable and uses the same pinned
    store identity. No per-stream/head calls or cross-page snapshot merge occur.
    Source matching does not prove the saved display mesh describes that body.
    """
    from kir.project_store import ProjectStore, ProjectStoreError

    #: 🔴 The guard that used to stand in `make_server`: a display join never
    #: takes a writable handle. It moved here with the window's removal
    #: (13.09.2026) rather than being deleted with it — the property is about
    #: the join, and the server was only its first caller.
    if (project_store is not None and isinstance(project_store, ProjectStore)
            and project_store.readonly is not True):
        raise DisplayInputRefusal("readonly_store_required",
                                  "attach an explicitly read-only ProjectStore handle")
    source = validated.data["source"]
    result = {"schema": PROJECT_STATUS_SCHEMA,
        "artifact_sha256": validated.transport["artifact_sha256"],
        "project_id": source["project_id"], "displayed_revision_id": source["project_revision_id"],
        "state": "not_attached", "source_binding": "not_checked", "status": None, "diagnostic": None}
    if project_store is None:
        return result
    try:
        status = project_store.status(limit=20)  # the ONLY mutable snapshot
        if (status.get("schema") != "kir-project-status/1" or status.get("store_id") != project_store.store_id
                or status.get("project_id") != project_store.project_id
                or status.get("snapshot_scope") != "one_local_read_transaction" or status.get("read_only") is not True
                or status["native"]["live_model_observed"] is not False
                or status["native"]["whole_project_acceptance"] != "not_established"
                or type(status["native"]["streams"]) is not list or len(status["native"]["streams"]) > 20):
            raise DisplayInputRefusal("store_status_contract_mismatch", "unsupported status contract")
        if source["project_id"] != status["project_id"]:
            raise DisplayInputRefusal("display_store_mismatch", "display and store project differ")
        revision = project_store.get(source["project_revision_id"])
        if (revision.project_id != source["project_id"] or revision.schema != source["project_schema"]
                or revision.parent_revision != source["parent_revision_id"] or revision.ir_version != source["ir_version"]):
            raise DisplayInputRefusal("display_store_mismatch", "display source snapshot differs")
        addresses = revision.addressed_outputs()
        if len(addresses) != len(source["operations"]):
            raise DisplayInputRefusal("display_store_mismatch", "display source coverage differs")
        for (instance, output, oid), row in zip(addresses, source["operations"], strict=True):
            expected = {"op_id": oid, "display_id": "p1/" + oid, "instance_key": instance.key,
                "module_key": instance.module_key, "output_key": output.key,
                "module_definition_digest": instance.module_digest, "op": output.operation["op"],
                "authored_output_sha256": _hash(output.to_dict())}
            if any(row.get(key) != value for key, value in expected.items()):
                raise DisplayInputRefusal("display_store_mismatch", "display output/order/owner differs")
            if output.geometry is None:
                if ("geometry_reference" in row or row["operation_sha256"] != _hash({**_thaw(output.operation), "id": oid})):
                    raise DisplayInputRefusal("display_store_mismatch", "display authored operation differs")
            elif _canonical(row.get("geometry_reference")) != _canonical(output.geometry.to_dict()):
                raise DisplayInputRefusal("display_store_mismatch", "display body source differs")
        result.update(state="available", source_binding="matched_immutable_authoring_snapshot", status=status)
        if len(_canonical(result).encode("utf-8")) > MAX_STATUS_BYTES:
            raise DisplayInputRefusal("store_status_budget_exceeded", "status page exceeds viewer budget")
    except DisplayInputRefusal as error:
        result.update(state="unavailable", source_binding="not_checked", status=None, diagnostic=error.code)
    except (ProjectStoreError, OSError, ValueError, TypeError, KeyError, AttributeError):
        # Never leak local paths, source text, or stale positive status on failure.
        result.update(state="unavailable", source_binding="not_checked", status=None, diagnostic="store_status_unavailable")
    return result
