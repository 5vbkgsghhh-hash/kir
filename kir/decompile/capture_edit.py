# -*- coding: utf-8 -*-
"""Offline editing of a saved building: open a capture, understand it, change it, ship it out.

🔴 WHAT THIS MODULE ASSERTS, AND WHAT IT DOES NOT. It does NOT declare L1 the building's archive:
the 07.09.2026 reconnaissance measurement on `sob62_r23_v3` — of 20 482 non-empty L0 fields, 11 625
(56.8 %) never reach L1, with OPS losing more than atoms do (60.3 % versus
46.3 %). So the source of truth here is the L0 ROW, and L1 is the language in which
an edit can be EXPRESSED. Every node holds a reference to its own L0 row, and everything the
language cannot express is named as a loss WITH AN ADDRESS, rather than staying silent.

The corpus is NEVER written to: `open_capture` only reads, and `save` refuses by
name any path whose ancestor holds A FOREIGN run (one with an `L0.jsonl`)
— by a rule, not by a directory's non-emptiness or filesystem permissions.
"""
from __future__ import annotations

import copy
import dataclasses
import gzip
import hashlib
import json
import math
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from kir.model.snapshot_io import snapshot_file_exists
from kir.revit_version import DEFAULT_VERSION

__all__ = ["Capture", "CaptureEditError", "EditResult", "ElementView", "Loss",
           "describe", "edit_element", "export_program", "losses", "open_capture",
           "resolve_type", "save", "type_catalog"]

#: The run's side indexes: without them the lift is poorer, and this is NAMED in `Capture`.
#: 🔴 `sketch` WAS ADDED ON 07.09.2026, AND THIS REFUTES AN EARLIER MEASUREMENT. Stage
#: A4 concluded "not one of `bench_A`'s 4223 elements has a contour, all 24
#: floors are atoms", and concluded it HONESTLY: `open_capture` was not supplying the lifter
#: `profile_index`, even though `sketch.index.json` lies in the run and carries 128 profile
#: rows. A measurement with it (`impl3/probe_sketch.py`): atoms 1292 -> 1234, ops
#: with OPENINGS 0 -> 21, among them floor 286551 with the ring
#: [[12000,2000],[24000,2000],[24000,9500],[12000,9500]]. That is, "no data"
#: was a property of OUR reading, not of the corpus.
_SIDE = ("family_placement", "curve", "curtain", "sketch")
#: What the index key is called at the lifter, and where the payload lies inside the file.
_SIDE_KWARG = {"family_placement": ("family_placement_index", None),
               "curve": ("wall_curve_index", None),
               "curtain": ("curtain_index", None),
               "sketch": ("profile_index", "profile_index")}
_EDITS_NAME = "capture_edits.jsonl"
_EDIT_SCHEMA = "kir-capture-edit/1"
_META_NAME = "capture_meta.json"
_META_SCHEMA = "kir-capture-meta/1"
#: The marker of an INCOMPLETE save. It lies in the staging directory the whole time
#: it is being assembled, and is removed as the LAST action before the rename.
#: A process killed mid-work leaves it in place, and `open_capture`
#: refuses by name, instead of accepting half the work as the work.
_PARTIAL_NAME = "capture_save_incomplete"
#: What the SOURCE VERSION is made of. Not just L0: the lift reads side
#: indexes (`_SIDE`) and the `profiles` mode, and both CHANGE the interpretation's result
#: on a byte-for-byte identical snapshot. The L0 dialect is deliberately NOT added here: it lies in
#: the snapshot's own basement, meaning it is already covered by its digest.
_SOURCE_SCHEMA = "kir-capture-source/1"
#: 🔴 THE REVISION OF THE DOCUMENT THE CAPTURE WAS TAKEN FROM. The file is placed by the
#: parse itself, it exists for 80 of 81 corpus runs (missing only for `демо-v3`), and
#: `serving.py:8818` judges the live model by it:
#: `active_revision != manifest.revision_proof.fingerprint`. Before
#: 07.09.2026 `capture_edit` DID NOT READ IT AT ALL, and this was not a gap but a second
#: answer to one question: feeding a saved capture a foreign
#: `revision.proof.json` (`bench_A` -> `k4_geom_wave2`, with L0 and the sidecars byte-for-byte
#: the same) went through SILENTLY — the edit replayed, and `integrity` kept
#: saying `pinned:source_version`. That is, the capture claimed to be bound to
#: the whole source while actually being bound to everything EXCEPT the revision.
#:
#: It is deliberately NOT added to `_source_version`: `source_version` answers the
#: question "will the SAME THING come up", and the revision does not affect the lift — the lifter
#: does not read it. It answers a different question — "was what we are editing taken
#: from that DOCUMENT REVISION" — and mixing the two questions into one digest would mean
#: answering both with one word.
_REVISION_NAME = "revision.proof.json"
_REVISION_SCHEMA = "kir-capture-revision/1"
#: The absence of a revision is a FACT, not an empty string. Runs older than the check and
#: slices without the file must be distinguishable from "a revision exists and it is this one".
_REVISION_ABSENT = "absent:no_revision_proof"
#: What a floor/ceiling opening edit can change.
_OPENING_FIELDS = ("opening_index", "opening_contour_mm")

#: What an edit of an opening IN A WALL can change. This is a DIFFERENT thing, not another
#: category of the same one, and so it has its own list.
#:
#: 🔴 THE 08.09.2026 ANALYSIS OF WHY `_OPENING_FIELDS` DOES NOT FIT HERE. An opening in a
#: floor is a RING in the inner loop of the CARRIER'S OWN sketch: what is edited is
#: the floor, the field `opening_contour_mm`, the `create_floor`/`create_ceiling` node.
#: A wall opening is a SEPARATE `Autodesk.Revit.DB.Opening` element with its own op,
#: `create_opening(variety="wall_rect")`, and its entire size and position are
#: given by TWO OPPOSITE CORNERS (`NewOpening(Wall, XYZ, XYZ)`).
#: Handing a wall opening to `_edit_opening` (by removing the category validator — the hypothesis
#: the wave tested first) would mean asking `_holes_of` of the opening's node
#: and getting `opening_contour_not_captured`: a refusal correct in letter and
#: false in cause.
#:
#: 🔴 WHY PREFIXED NAMES, NOT `p0_mm`/`p1_mm`. `p0_mm` is also an L0 row field
#: for anything given by a curve (for a wall, its ends), and a parameter of a dozen
#: ops. An edit key `p0_mm` would be an address with two different referents depending
#: on the category — exactly the kind of ambiguity `_DOOR_FIELDS` and `_OPENING_FIELDS`
#: are kept as separate lists over.
_WALL_OPENING_FIELDS = ("opening_p0_mm", "opening_p1_mm")

#: What the same two corners are called IN THE NODE. The pair "edit key -> op parameter"
#: lives in ONE place: were it to drift apart, it would write the edit past the parameter.
_WALL_OPENING_PARAM = {"opening_p0_mm": "p0_mm", "opening_p1_mm": "p1_mm"}

#: What this contract can change. The list is CLOSED: an unknown edit must
#: refuse BY NAME. "Nothing changed" in answer to a request to change —
#: the worst possible falsehood: it looks like success.
_DOOR_FIELDS = ("offset_mm", "sill_mm", "symbol")


class CaptureEditError(ValueError):
    """A refusal that has a code and an address. There is no silent refusal here."""

    def __init__(self, code: str, message: str, address: str | None = None):
        super().__init__(f"{code}: {message}")
        self.code, self.address = code, address


@dataclass(frozen=True)
class Loss:
    element_id: str
    unique_id: str | None
    fields: tuple
    why: str

    def to_dict(self) -> dict:
        return {"element_id": self.element_id, "unique_id": self.unique_id,
                "fields": list(self.fields), "why": self.why}


@dataclass(frozen=True)
class ElementView:
    element_id: str
    unique_id: str | None
    category: str | None
    l0_fields: dict
    l1_op: dict | None
    atom: dict | None
    losses: tuple
    #: `{field: state}` per the ledger: `represented | approximate |
    #: source_data | unknown`. A lost field's name without a state does not say
    #: WHOSE repair this is or how much of the fact survived; the default is empty so that
    #: old callers keep building.
    field_states: dict = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"element_id": self.element_id, "unique_id": self.unique_id,
                "category": self.category, "l0_fields": dict(self.l0_fields),
                "l1_op": self.l1_op, "atom": self.atom, "losses": list(self.losses),
                "field_states": dict(self.field_states)}


@dataclass(frozen=True)
class EditResult:
    changed_ops: tuple
    untouched_count: int
    refusal: dict | None = None
    #: What is known about an ACCEPTED edit and is not good news. This is not a refusal:
    #: "the panel overhangs the end" is a fact about the building, not a contract violation, and
    #: staying silent about it would mean handing over a success we know more about than
    #: we said. Appended AT THE TAIL with a default value: old callers
    #: (the acceptance instrument, the pins) read the three earlier fields byte-for-byte the same.
    notes: tuple = ()

    def to_dict(self) -> dict:
        return {"changed_ops": list(self.changed_ops),
                "untouched_count": self.untouched_count, "refusal": self.refusal,
                "notes": list(self.notes)}


@dataclass
class Capture:
    """An opened capture. `document` is the source of truth, `nodes` is the editing language."""

    path: Path
    lineage: str
    document: Any
    nodes: list
    by_source: dict
    edits: list = field(default_factory=list)
    side_indexes: tuple = ()
    missing_side_indexes: tuple = ()
    #: Side indexes that DO EXIST on disk but do not read (`{"index",
    #: "detail"}`). This is a THIRD state alongside "supplied" and "absent":
    #: equating corruption with absence would mean saying the data never existed,
    #: where it does exist and is corrupted. An empty tuple = none is corrupted.
    unreadable_side_indexes: tuple = ()
    #: sha256 of the L0 snapshot ON TOP OF WHICH the edits are built. An edit
    #: attached to a different building is not an edit but an address coincidence.
    source_sha256: str = ""
    #: Where `lineage` is taken from: `capture_meta.json` (pinned on save)
    #: or `directory_name` (original corpus run, no metadata yet).
    lineage_source: str = "directory_name"
    #: Capture type catalog; built once (`type_catalog`).
    catalog: dict = field(default_factory=dict, repr=False)
    #: Programs the compiler REFUSED to translate, and why. An empty
    #: list means "all of them translated," not "we didn't look."
    export_refusals: list = field(default_factory=list)
    #: The profile-reading mode THIS capture was raised under. It changes the
    #: lift (`bench_A` gets 21 nodes with opening rings versus zero), so it
    #: travels in the metadata together with the identity, rather than staying
    #: a habit of the caller.
    profiles: str = "editable"
    #: Version of the ENTIRE source: L0 + applicable sidecars + reading mode.
    source_version: str = ""
    #: sha256 of each applicable sidecar, by name. Needed so the refusal names
    #: WHICH one drifted, rather than "something changed."
    sidecar_digests: dict = field(default_factory=dict, repr=False)
    #: 🔴 WHAT EXACTLY IS PROVEN ABOUT THIS CAPTURE, IN WORDS, NOT BY DEFAULT.
    #: `unpinned:directory_name` — no metadata, identity taken from the
    #: directory name; `pinned:l0_only` — an OLD record: only the snapshot is
    #: pinned, sidecar substitution is not caught by it; `pinned:source_version`
    #: — the entire source is pinned. Silently granting an old record the new
    #: guarantee would mean reporting a guard that isn't there.
    integrity: str = "unpinned:directory_name"
    #: What the EDITS are pinned by: `none` — there are none; `before_value` —
    #: each one carries the expected previous value; `address_only` — there are
    #: lines with the old binding, where an address match was enough.
    edit_binding: str = "none"
    #: The DOCUMENT revision this capture was taken from (`revision.proof.json`),
    #: or `absent:…`/`unreadable:…` — three DIFFERENT states, not one empty
    #: string for all three.
    capture_revision: str = _REVISION_ABSENT
    #: What the edits are pinned to THE REVISION by: `none` — there are no
    #: edits; `pinned` — each one names the revision it relied on; `unpinned` —
    #: there are lines from an OLD record, made before 07.09.2026, where the
    #: revision wasn't named. The third state exists because "the edit doesn't
    #: know the revision" and "the edit knows the same revision" are different
    #: facts, and equating the former with the latter would mean reporting a
    #: guard that isn't in the old record.
    revision_binding: str = "none"

    @property
    def elements(self) -> dict:
        return {str(element.element_id): element for element in self.document.elements}


def _side_path(directory: Path, name: str) -> Path | None:
    """Where the side index lives. ONE law for reading and for the digest.

    A second dictionary about the same thing would drift: a compressed index
    computed by one rule and read by another would give "version matches" for
    different geometry.
    """
    for candidate in (directory / f"{name}.index.json", directory / f"{name}.index.json.gz"):
        if candidate.exists():
            return candidate
    return None


def _read_index(directory: Path, name: str):
    """The side index, or `None`. Corruption IS NAMED, not left to fly out.

    🔴 OPENED BY THE SELF-REVIEW PROBE ON 07.09.2026, AND IT WAS RED. A broken
    sidecar (`{ this is not json`) dropped a `json.JSONDecodeError` DIRECTLY OUT
    OF `open_capture`: the reader got a parser-library traceback instead of an
    answer about the building, and there was nothing to distinguish "no file"
    from "file is corrupted."

    Corruption is NOT THE SAME as absence, and equating them silently is not
    allowed. So a pair `(value, trouble)` is returned: `("__unreadable__", reason)`
    names WHAT exactly is unreadable, the capture is raised WITHOUT this index,
    and the fields that needed it honestly get `unknown`. Replaying old edits is
    still refused by name regardless: `_sidecar_digests` counts the sha256 OF
    THE BYTES, and corruption changes `source_version`.
    """
    candidate = _side_path(directory, name)
    if candidate is None:
        return None, None
    opener = gzip.open if candidate.suffix == ".gz" else open
    try:
        with opener(candidate, "rt", encoding="utf-8") as handle:
            return json.load(handle), None
    except (json.JSONDecodeError, UnicodeDecodeError, OSError, EOFError) as error:
        return None, (f"{candidate.name}: не читается как JSON "
                      f"({type(error).__name__}); индекс не подан лифтеру, и "
                      f"поля, которым он был нужен, остаются unknown")


#: Categories for which the sketch profile is read BY DEFAULT — exactly those
#: whose editing this contract knows how to state.
#: 🔴 THIS IS NOT CAUTION, IT IS A MEASUREMENT. Opening the profile to ALL
#: categories, `bench_A` gets 41 programs instead of 18 and a NEW refusal
#: `KIR-L004`: roof 298459 stops being an atom, becomes `create_roof`, and
#: `set_curtain_panel`, which used to address it by a pinned `element_id`,
#: starts addressing it by a `ref` — but the `host` kind for this op is only
#: `wall`. Price: a program of 249 ops no longer translates, emitted ops go
#: 2860 -> 2640. With the filter on floors and ceilings all 21 nodes with
#: openings are in place, refusals unchanged (two `KIR-G103`), and emitted ops
#: go 2860 -> 2884. `profiles="all"` opens the full profile to whoever accepts
#: this price; it is named here as a number.
_PROFILE_CATEGORIES = ("OST_Floors", "OST_Ceilings")


def _profile_rows(payload, document, profiles: str) -> dict | None:
    if profiles == "none" or not isinstance(payload, Mapping):
        return None
    if profiles == "all":
        return dict(payload)
    keep = {str(element.element_id) for element in document.elements
            if element.category in _PROFILE_CATEGORIES}
    return {key: value for key, value in payload.items() if str(key) in keep}


def open_capture(path, *, profiles: str = "editable") -> Capture:
    """Read the capture and raise it. The directory is READ ONLY.

    `profiles` — how much sketch profile to hand the lifter: `"editable"`
    (floors and ceilings — what this contract knows how to edit), `"all"`
    (the whole index, at the named price — see `_PROFILE_CATEGORIES`), or
    `"none"` (as it was before 07.09.2026).
    """
    if profiles not in ("editable", "all", "none"):
        raise CaptureEditError("bad_profiles_mode",
                               f"profiles={profiles!r}: editable | all | none", str(path))
    from kir.decompile.extract import L0JSONLReader
    from kir.decompile.lift import lift_document_detailed

    directory = Path(path)
    l0 = directory / "L0.jsonl"
    # 🔴 NOT `l0.exists()`. The snapshot is allowed to lie COMPRESSED
    # (`L0.jsonl.gz`), and the bare name-based check answers "no" where the
    # file exists — and "no" here reads as "there is no corpus." The guard
    # `test_snapshot_existence_is_asked` has held this since 20.08.2026, and
    # it caught exactly this line.
    if not snapshot_file_exists(l0):
        raise CaptureEditError("capture_not_found", f"{directory}: L0.jsonl is absent",
                               str(directory))
    # Identity is asked BEFORE parsing: a set of edits bound to a DIFFERENT
    # building refuses by name, not after several seconds of reading someone
    # else's snapshot. The order here is part of the refusal, not an
    # optimization.
    if (directory / _PARTIAL_NAME).exists():
        # 🔴 HALF-DONE WORK DECLARED AS DONE WORK IS THE WORST OF OUTCOMES. The
        # 07.09.2026 recon measurement: a directory where L0 has already
        # landed but the metadata hasn't yet opened SILENTLY and got `lineage`
        # from the directory name, meaning an interrupted save was read as a
        # completed, different building.
        raise CaptureEditError(
            "capture_save_incomplete",
            f"{directory}: здесь лежит метка {_PARTIAL_NAME} — сохранение было "
            f"прервано и каталог не является завершённым capture", str(directory))
    digest = _snapshot_digest(directory)
    sidecars = _sidecar_digests(directory)
    version = _source_version(digest, sidecars, profiles)
    revision = _capture_revision(directory)
    lineage, lineage_source, integrity = _lineage_and_binding(
        directory, digest, sidecars, version, profiles, revision)
    document = L0JSONLReader(l0).materialize()
    present, missing, kwargs = [], [], {}
    unreadable: list = []
    for name in _SIDE:
        value, damage = _read_index(directory, name)
        if damage is not None:
            unreadable.append({"index": name, "detail": damage})
        keyword, inner = _SIDE_KWARG[name]
        if value is not None and inner is not None:
            value = _profile_rows(
                value.get(inner) if isinstance(value, Mapping) else None,
                document, profiles)
        (present if value is not None else missing).append(name)
        if value is not None:
            kwargs[keyword] = value
    nodes = [copy.deepcopy(node) for node in lift_document_detailed(document, **kwargs).nodes]
    by_source = {}
    for node in nodes:
        source = node.get("source_element_id") or (node.get("source") or {}).get("element_id")
        if source is not None:
            by_source.setdefault(str(source), node)
    capture = Capture(path=directory, lineage=lineage, document=document,
                      nodes=nodes, by_source=by_source,
                      side_indexes=tuple(present), missing_side_indexes=tuple(missing),
                      unreadable_side_indexes=tuple(
                          dict(row) for row in unreadable),
                      source_sha256=digest, lineage_source=lineage_source,
                      profiles=profiles, source_version=version,
                      sidecar_digests=sidecars, integrity=integrity,
                      capture_revision=revision)
    _apply_saved_edits(capture, directory / _EDITS_NAME)
    return capture


def _snapshot_path(directory: Path) -> Path | None:
    for candidate in (directory / "L0.jsonl", directory / "L0.jsonl.gz"):
        if candidate.exists():
            return candidate
    return None


def _snapshot_digest(directory: Path) -> str:
    """sha256 of the snapshot's BYTES. The building identity the edits are bound to."""
    path = _snapshot_path(directory)
    if path is None:
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _has_edits(directory: Path) -> bool:
    """Whether there is anything to REPLAY. The presence of an empty file does not count as an edit."""
    path = directory / _EDITS_NAME
    if not path.exists():
        return False
    with path.open(encoding="utf-8") as handle:
        return any(line.strip() for line in handle)


def _file_digest(path: Path) -> str:
    """sha256 of the file's BYTES, streamed. The file is not loaded into memory whole."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _sidecar_digests(directory: Path) -> dict:
    """sha256 of each APPLICABLE sidecar — the ones that actually travel to the lifter."""
    out = {}
    for name in _SIDE:
        path = _side_path(directory, name)
        if path is not None:
            out[name] = _file_digest(path)
    return out


def _source_version(digest: str, sidecars: Mapping, profiles: str) -> str:
    """Version of the ENTIRE source, not just one L0.

    🔴 WHY ONE L0 IS NOT ENOUGH — A MEASUREMENT, NOT A WORRY. The 07.09.2026
    recon substituted `sketch.index.json` for `{"profile_index":{}}` in a saved
    capture while `L0.jsonl` stayed byte-for-byte the same: `bench_A` lost all
    21 nodes with opening rings, while `source_sha256` stayed unchanged and the
    open went through SILENTLY. That is, an old opening edit would replay
    against DIFFERENT geometry, while the version would claim the building was
    the same.
    """
    payload = json.dumps({"schema": _SOURCE_SCHEMA, "l0": digest,
                          "profiles": profiles, "sidecars": dict(sidecars)},
                         ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _capture_revision(directory: Path) -> str:
    """The revision of the document the capture was taken from, in ONE line.

    Three outcomes, and they are DISTINGUISHABLE: `absent:…` — there is no file
    (the run is older, or this is a slice without one); `unreadable:…` — the
    file exists and doesn't read; otherwise
    `document-revision/1|<change_stamp>|<fingerprint>` — exactly what decompile
    put there. Equating "absent" with "unreadable" would mean saying there was
    no data where it exists and is corrupted — the same defect already named
    for the side indexes (`_read_index`).
    """
    path = directory / _REVISION_NAME
    if not path.exists():
        return _REVISION_ABSENT
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as error:
        return f"unreadable:{type(error).__name__}"
    if not isinstance(payload, Mapping):
        return f"unreadable:{type(payload).__name__}"
    schema = payload.get("schema_version")
    stamp = payload.get("change_stamp")
    finger = payload.get("fingerprint")
    if not all(isinstance(item, str) and item for item in (schema, stamp, finger)):
        return "unreadable:incomplete_revision_proof"
    return f"{schema}|{stamp}|{finger}"


def _lineage_and_binding(directory: Path, digest: str, sidecars: Mapping,
                         version: str, profiles: str, revision: str = "") -> tuple:
    """`lineage` from PINNED metadata, otherwise from the run's name.

    🔴 WHAT IS FIXED HERE (owner finding 4, second half). `lineage` used to be
    derived FROM THE DIRECTORY NAME, and `lineage` travels in the program's
    envelope and takes part in the stamp of EVERY element: meaning `mv work
    work2` changed the identity of the exported program without touching
    anything in the building. Now the directory name is only the INITIAL
    value, and `save` PINS it into `capture_meta.json`; a capture opened from
    there is called by the same name it was called by, no matter how many
    times the directory gets renamed.

    The same place holds the `source_sha256` of the source L0: edits attached
    to a DIFFERENT building are not edits but an address coincidence, and
    opening such a set refuses BY NAME, rather than silently editing someone
    else's house.
    """
    meta_path = directory / _META_NAME
    if not meta_path.exists():
        # 🔴 AN EDITS FILE WITHOUT METADATA IS NOT EDITS, IT IS ADDRESSES
        # WITHOUT A BUILDING. Review 6 measurement: drop one
        # `capture_edits.jsonl` into SOMEONE ELSE'S snapshot (without bringing
        # metadata) — and the edit went through silently, `offset_mm` of door
        # 286533 changed from 3000.0 to 3300.0 in someone else's house. The
        # guard stood exactly where the attacker was obliged to helpfully
        # bring the evidence.
        if (directory / _EDITS_NAME).exists():
            raise CaptureEditError(
                "capture_meta_missing",
                f"{directory}: есть {_EDITS_NAME}, но нет {_META_NAME}; правки без "
                f"закреплённого снимка приложились бы к любому зданию с теми же "
                f"адресами", str(directory))
        return _lineage_of(directory), "directory_name", "unpinned:directory_name"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CaptureEditError("capture_meta_corrupt", f"{meta_path}: {exc}",
                               str(meta_path)) from exc
    if not isinstance(meta, Mapping) or meta.get("schema") != _META_SCHEMA:
        raise CaptureEditError(
            "capture_meta_corrupt",
            f"{meta_path}: ожидалась схема {_META_SCHEMA}, получено "
            f"{(meta or {}).get('schema') if isinstance(meta, Mapping) else type(meta).__name__}",
            str(meta_path))
    lineage = meta.get("lineage")
    if not isinstance(lineage, str) or not lineage:
        raise CaptureEditError("capture_meta_corrupt",
                               f"{meta_path}: в метаданных нет `lineage`", str(meta_path))
    bound = meta.get("source_sha256")
    if not isinstance(bound, str) or not bound.strip():
        # 🔴 `source_sha256` IS A REQUIRED SCHEMA FIELD, not decoration. Review
        # 6 measurement: metadata WITHOUT it was accepted, and along with it a
        # FOREIGN `lineage` was accepted — and it travels in the program's
        # envelope and in the stamp of every element, meaning the export would
        # get the name of a different building.
        raise CaptureEditError(
            "capture_meta_incomplete",
            f"{meta_path}: в метаданных нет `source_sha256`; без него `lineage` и правки "
            f"не привязаны ни к какому снимку", str(meta_path))
    if digest and str(bound) != digest:
        raise CaptureEditError(
            "edits_belong_to_another_capture",
            f"{meta_path}: правки закреплены за снимком {str(bound)[:16]}…, а в "
            f"этом каталоге лежит {digest[:16]}…. Адреса элементов у двух зданий "
            f"совпадают по построению, поэтому правка приложилась бы МОЛЧА к "
            f"чужому дому", str(meta_path))
    pinned_version = meta.get("source_version")
    if not isinstance(pinned_version, str) or not pinned_version.strip():
        # 🔴 AN OLD RECORD IS READ WITH ITS OWN, LESSER GUARANTEE. Refusing it
        # would mean declaring unreadable every capture saved before this fix;
        # granting it `pinned:source_version` would mean reporting a guard
        # that isn't in it. It pinned exactly the snapshot — that's exactly
        # what it's called, and the caller reads this in words
        # (`Capture.integrity`).
        return lineage, _META_NAME, "pinned:l0_only"
    pinned_revision = meta.get("capture_revision")
    if (isinstance(pinned_revision, str) and pinned_revision
            and revision and pinned_revision != revision):
        # 🔴 A REFUSAL BY NAME, NOT BY SOURCE VERSION. The document revision
        # doesn't take part in the lift, so `source_version` doesn't catch it:
        # the 07.09.2026 measurement substituted the revision file of a saved
        # `bench_A` for the revision `k4_geom_wave2` (L0 and sidecars
        # byte-for-byte the same) — the open went through silently, `integrity`
        # kept saying `pinned:source_version`.
        raise CaptureEditError(
            "capture_revision_moved",
            f"{meta_path}: capture сохранён из ревизии документа "
            f"{pinned_revision!r}, а рядом лежит доказательство ревизии "
            f"{revision!r}. Снимок и боковые индексы те же, но ревизия — это "
            f"ответ на другой вопрос: ИЗ ЧЕГО снято то, что мы правим",
            str(meta_path))
    if pinned_version != version:
        pinned_sidecars = meta.get("sidecars")
        moved = []
        if isinstance(pinned_sidecars, Mapping):
            for name in sorted(set(pinned_sidecars) | set(sidecars)):
                if pinned_sidecars.get(name) != sidecars.get(name):
                    moved.append(name)
        pinned_profiles = meta.get("profiles")
        if moved:
            raise CaptureEditError(
                "source_sidecar_changed",
                f"{meta_path}: применимые sidecars {moved} изменились под уже "
                f"записанными правками. L0 тот же, но подъём читает их, значит "
                f"старые правки легли бы на ДРУГУЮ геометрию", str(meta_path))
        if isinstance(pinned_profiles, str) and pinned_profiles != profiles:
            # The reading mode is the CALLER's choice, and re-reading the
            # building under a different mode is legitimate. What isn't
            # legitimate is replaying SOMEONE ELSE's old edits under it. What
            # is checked is the file's NON-EMPTINESS, not its presence: `save`
            # always puts down `capture_edits.jsonl`, and checking presence
            # would make the refusal land on a capture that has zero edits.
            if _has_edits(directory):
                raise CaptureEditError(
                    "interpretation_mode_changed",
                    f"{meta_path}: правки записаны в режиме profiles="
                    f"{pinned_profiles!r}, а capture открывают в {profiles!r}; "
                    f"режим меняет подъём, значит правки проигрались бы по другой "
                    f"интерпретации", str(meta_path))
            return lineage, _META_NAME, "pinned:l0_only"
        raise CaptureEditError(
            "source_version_changed",
            f"{meta_path}: версия исходника закреплена как {pinned_version[:16]}…, "
            f"а сейчас складывается {version[:16]}…", str(meta_path))
    return lineage, _META_NAME, "pinned:source_version"


def _lineage_of(directory: Path) -> str:
    """Stable name of the program's kind — the run's name.

    🔴 WITHOUT IT, EDITING ONE NUMBER REWRITES THE WHOLE MODEL. Recon
    measurement: shifting one door changed 502 lines of C#, 498 of them the
    `kir:<program digest>:<element>` stamp in the comment of EVERY element.
    With a stable `lineage`, those lines are 0, and the changed ones are 4.
    Neighbors stay byte for byte, and that's a property of the emission, not
    our carefulness.

    The directory name is fit ONLY as an initial value: after that `save`
    pins it into `capture_meta.json` (see `_lineage_and_binding`).
    """
    name = "".join(character if character.isalnum() or character in "._-" else "-"
                   for character in directory.name)
    return f"capture-{name}" if name else "capture"


def _before_values(capture: Capture, key: str, change: Mapping) -> dict:
    """What the edit EXPECTED to find at this address. One law for both write
    and check.

    🔴 WITHOUT IT, AN ADDRESS IS NOT A BINDING, IT IS A COINCIDENCE. An edit
    line used to carry only `element_id` and `change`: a numeric address
    coincides between two buildings by construction, and the edit landed on
    any value without saying anything about it. Here it names the PREVIOUS
    value, and on a check, a mismatch is a refusal by name, not a silent
    overwrite.
    """
    node = capture.by_source.get(key)
    element = capture.elements.get(key)
    if node is None or element is None:
        return {}
    out: dict = {}
    if element.category == "OST_Doors":
        params = node.get("params") or {}
        for name in change:
            if name in _DOOR_FIELDS:
                out[name] = copy.deepcopy(params.get(name))
        return out
    if element.category == "OST_SWallRectOpening":
        # Previous angles are read FROM THE NODE by the same name mapping the
        # edit uses to write them there: a second dictionary about the same
        # thing would drift from the first.
        params = node.get("params") or {}
        for name in change:
            if name in _WALL_OPENING_PARAM:
                out[name] = copy.deepcopy(params.get(_WALL_OPENING_PARAM[name]))
        return out
    if set(change) & set(_OPENING_FIELDS):
        holes, _ = _holes_of(node)
        index = change.get("opening_index", 0)
        if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(holes):
            out["opening_index"] = index
            out["opening_contour_mm"] = copy.deepcopy(_points_of(holes[index]))
    return out


def _canon(value) -> str:
    """A comparable form: a list and a tuple of the same content are one
    value.

    🔴 THE NUMBER IS CANONICALIZED, OTHERWISE THE GUARD GOES RED FROM THE
    RECORD'S SHAPE. 07.09.2026 self-review measurement: `_canon(2100) !=
    _canon(2100.0)` and `_canon(-0.0) != _canon(0.0)`, while L0 carries both
    integers and fractionals, and `-0.0` comes from geometry. A false
    `edit_before_value_mismatch` on a value that did NOT change is worse than
    a miss: it stops work over nothing. There is NO tolerance here and there
    won't be: a float round-trip through JSON in Python is exact (verified by
    the same measurement), and a tolerance would mask a real edit of
    2100.0 -> 2100.000001.
    """
    def canon(item):
        if isinstance(item, bool):
            return item
        if isinstance(item, (int, float)):
            number = float(item)
            return 0.0 if number == 0.0 else number
        if isinstance(item, Mapping):
            return {str(key): canon(sub) for key, sub in item.items()}
        if isinstance(item, (list, tuple)):
            return [canon(sub) for sub in item]
        return item

    return json.dumps(canon(value), ensure_ascii=False, sort_keys=True, default=str)


def _apply_saved_edits(capture: Capture, path: Path) -> None:
    if not path.exists():
        return
    bindings: list = []
    revisions: list = []
    # 🔴 THE ONE FILE THIS MODULE WRITES ITSELF MUST BE NAMED WHEN IT IS
    # CORRUPTED. Review A4-3 showed by execution: `{this is not json}` raised
    # `JSONDecodeError`, and a line without `element_id` raised `KeyError:
    # 'element_id'`; both without a code, without an address, and bypassing
    # `CaptureEditError`, meaning the caller could not tell "the edits file is
    # broken" from "the module is broken." The address here is the file's LINE
    # (`<path>:<number>`), because that is exactly what will need fixing.
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        address = f"{path}:{number}"
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CaptureEditError("edits_file_corrupt", f"{address}: {exc}",
                                   address) from exc
        if not isinstance(row, Mapping):
            raise CaptureEditError(
                "edits_file_corrupt",
                f"{address}: строка правки обязана быть объектом, получено "
                f"{type(row).__name__}", address)
        if row.get("schema") != _EDIT_SCHEMA:
            raise CaptureEditError("unsupported_edit_schema", row.get("schema", "<none>"),
                                   address)
        missing = [name for name in ("element_id", "change") if name not in row]
        if missing:
            raise CaptureEditError(
                "edits_file_corrupt",
                f"{address}: в строке правки нет обязательных ключей {missing}", address)
        if not isinstance(row["change"], Mapping):
            raise CaptureEditError(
                "edits_file_corrupt",
                f"{address}: `change` обязан быть объектом, получено "
                f"{type(row['change']).__name__}", address)
        # 🔴 AN EDIT MUST KNOW WHICH REVISION IT RELIED ON. `before` guards the
        # VALUE under the address, but the value can coincide between two
        # revisions of the same house by construction — then the edit would
        # land on a different document without saying anything about it. A
        # line from an old record doesn't name the revision: this is a
        # separate state (`unpinned`), not a refusal, otherwise every capture
        # saved before 07.09.2026 would become unreadable.
        stamped = row.get("capture_revision")
        if isinstance(stamped, str) and stamped:
            revisions.append("pinned")
            if stamped != capture.capture_revision:
                raise CaptureEditError(
                    "capture_revision_moved",
                    f"{address}: правка сделана на ревизии документа "
                    f"{stamped!r}, а этот capture снят из {capture.capture_revision!r}; "
                    f"адреса и значения у двух ревизий одного дома совпадают по "
                    f"построению, поэтому проиграть её значило бы править другой "
                    f"документ", str(row["element_id"]))
        else:
            revisions.append("unpinned")
        before = row.get("before")
        if isinstance(before, Mapping) and before:
            bindings.append("before_value")
            current = _before_values(capture, str(row["element_id"]), row["change"])
            differ = sorted(name for name in before
                            if _canon(current.get(name)) != _canon(before[name]))
            if differ:
                raise CaptureEditError(
                    "edit_before_value_mismatch",
                    f"{address}: правка ожидала по адресу {row['element_id']} "
                    f"{ {name: before[name] for name in differ} }, а там лежит "
                    f"{ {name: current.get(name) for name in differ} }; значение "
                    f"под правкой уехало, и перезаписать его молча значило бы "
                    f"править не то, что правили",
                    str(row["element_id"]))
        else:
            bindings.append("address_only")
        result = edit_element(capture, row["element_id"], row["change"], _replay=True)
        if result.refusal is not None:
            raise CaptureEditError("saved_edit_no_longer_applies",
                                   json.dumps(result.refusal, ensure_ascii=False),
                                   row["element_id"])
        # 🔴 THE EDIT IS REMEMBERED ON REPLAY TOO. The first edition didn't do
        # this, and the measurement caught it: another process saw `offset_mm
        # 3300.0` (edit applied) but `edits 0` — meaning a REPEAT save would
        # silently lose the history. The `_replay` flag only suppresses the
        # WRITE from `edit_element`, so as not to duplicate the line; the edit
        # ledger is kept here.
        capture.edits.append(dict(row))
    if bindings:
        capture.edit_binding = ("before_value" if set(bindings) == {"before_value"}
                                else "address_only")
    if revisions:
        capture.revision_binding = ("pinned" if set(revisions) == {"pinned"}
                                    else "unpinned")


# ── description ───────────────────────────────────────────────────────────────
def _l0_fields(element) -> dict:
    out = {}
    for item in dataclasses.fields(element):
        value = getattr(element, item.name)
        if value in (None, (), [], {}, ""):
            continue
        out[item.name] = value
    return out


class _OneElement:
    """A one-line L0 for the ledger: the counting law is taken from ANOTHER, not one's own."""

    __slots__ = ("elements",)

    def __init__(self, element) -> None:
        self.elements = (element,)


def _field_states(element, node: dict | None, nodes=None) -> dict:
    """`{field: state}` from the NEIGHBOR's LEDGER, not from one's own formula.

    🔴 THE OWN INLINE FORMULA WAS REMOVED ON 07.09.2026, AND THIS IS A
    MEASUREMENT. `_reaches` used to stand here: "the name is in the node OR
    the value's text occurs in the node's text." Neither arm proves what is
    being asked, and a measurement of eight probes on `bench_A` gave SIX wrong
    verdicts out of eight: `type_name` with a DIFFERENT value — "arrived";
    `rotation_deg=0.0` next to an unrelated zero — "arrived"; a correct
    conversion `3048 mm -> 10.0 feet` — "lost."

    Two laws about the same subject in one tree drift apart silently, so
    there is exactly one law here — `kir.decompile.field_ledger`. Its absence
    is called a REFUSAL, not quietly replaced by a second count.

    🔴 ALL NODES ARE PASSED, AND THIS IS A RED CAUGHT BY THE ACCEPTANCE
    INSTRUMENT. The first edition built the ledger on ONE node — and the
    door's reference to the wall (`host: {"ref": …}`) had NOTHING TO RESOLVE
    IT BY: `describe()` declared `host_id` lost, while `losses()` on the same
    capture called it represented. Measurement: losses for door `bench_A`
    286533 — 12 versus 11. Two answers about the same subject; the L0 line is
    a single one, while resolving the reference must be done across the WHOLE
    building. `nodes=None` is left only for callers without a capture: it
    gives the old, NARROW answer, and this is visible from the parameter's
    name, not from silence.
    """
    if node is None:
        # There is no node at all: the ledger counts such an element as a
        # separate number and does not issue it a line. Everything non-empty
        # is counted as lost, and this is not a guess.
        return {name: "unknown" for name in _l0_fields(element)}
    try:
        from kir.decompile.field_ledger import field_ledger
    except Exception as error:  # noqa: BLE001
        raise CaptureEditError(
            "field_ledger_absent",
            f"ведомость полей недоступна ({type(error).__name__}); считать "
            f"потери своей формулой значило бы завести второй закон об одном "
            f"предмете", str(getattr(element, "element_id", ""))) from error
    ledger = field_ledger(_OneElement(element),
                          list(nodes) if nodes is not None else [node])
    row = next((item for item in ledger.rows
                if item.element_id == str(element.element_id)), None)
    if row is None:
        return {name: "unknown" for name in _l0_fields(element)}
    states = {name: "represented" for name in row.kept}
    states.update({item.field: item.state for item in row.lost})
    return states


def _lost_fields(element, node: dict | None, nodes=None) -> tuple:
    """Which NON-EMPTY L0 fields did not arrive at the node EXACTLY (`represented`)."""
    return tuple(sorted(name for name, state in
                        _field_states(element, node, nodes).items()
                        if state != "represented"))


def describe(capture: Capture, element_id) -> ElementView:
    """What is known about the element: the L0 line, the L1 node, and what is missing between them."""
    key = str(element_id)
    element = capture.elements.get(key)
    if element is None:
        raise CaptureEditError("unknown_element", f"{key}: absent from this capture", key)
    node = capture.by_source.get(key)
    kind = (node or {}).get("kind")
    states = _field_states(element, node, capture.nodes)
    return ElementView(
        element_id=key, unique_id=getattr(element, "unique_id", None),
        category=element.category, l0_fields=_l0_fields(element),
        l1_op=node if kind == "op" else None, atom=node if kind == "atom" else None,
        losses=tuple(sorted(name for name, state in states.items()
                            if state != "represented")),
        field_states=dict(sorted(states.items())))


def losses(capture: Capture) -> list:
    """Losses by address. The ledger is the NEIGHBOR's (`field_ledger`), when
    there is one.

    🔴 THE COUNTING LAW HERE IS EXACTLY ONE (07.09.2026). Before that day, a
    fallback path `own_formula` lived alongside it — "the name is in the node
    OR the value's text occurs in the node's text." It answered the SAME
    question with a DIFFERENT number, and two laws about the same subject in
    one tree diverge silently. The fallback path is removed; unavailability of
    the ledger is a NAMED REFUSAL (`field_ledger_absent`), not a quiet second
    count.
    """
    try:
        from kir.decompile.field_ledger import field_ledger
    except Exception as error:  # noqa: BLE001
        raise CaptureEditError(
            "field_ledger_absent",
            f"ведомость полей недоступна ({type(error).__name__}); прежний "
            f"запасной путь считал ПО ПОДСТРОКЕ и давал другой ответ на тот же "
            f"вопрос — второй закон об одном предмете убран 07.09.2026", "") from error
    # The neighbor's ledger carries the KIND of cause for each lost field
    # (`op_language | atom | derived`), not one per element. Here the kinds
    # are folded into one `why` line — as their LIST, not by picking the
    # first one: picking one would mean hiding the rest.
    ledger = field_ledger(capture.document, capture.nodes)
    out = []
    for row in ledger.rows:
        if not row.lost:
            continue
        why = ",".join(sorted({item.why for item in row.lost}))
        out.append(Loss(element_id=str(row.element_id), unique_id=row.unique_id,
                        fields=tuple(item.field for item in row.lost), why=why))
    return sorted(out, key=lambda item: item.element_id)


# ── edit ─────────────────────────────────────────────────────────────────
def _refuse(code: str, detail: str, address: str) -> EditResult:
    return EditResult(changed_ops=(), untouched_count=0,
                      refusal={"code": code, "detail": detail, "address": address})


def _finite(value) -> float | None:
    """A number one can compute over. `bool` is NOT counted as a number HERE."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _contract_bounds(field_name: str) -> tuple:
    """Absolute bounds of the parameter — belong to THE LANGUAGE, not to a
    second dictionary here.

    🔴 A SECOND DICTIONARY ABOUT THE SAME THING WOULD DRIFT, AND THE
    MEASUREMENT SAYS WHERE TO. `sill_mm` on `create_door` deliberately allows
    a NEGATIVE value (min −100 000): the mark is measured from the LEVEL of
    the host wall, and in `sob62_r23_v3`, 140 of 151 such doors are like this
    (131 at exactly −100 mm). A rule "sill ≥ 0," written here on its own,
    would refuse 92.7 % of the doors of a real building — this is exactly the
    defect the `ops_authoring` fix once addressed. So the bounds are taken
    from `spec.OPS`, and are NOT rewritten here.
    """
    try:
        from kir import spec
        for param in spec.OPS["create_door"].params:
            if param.name == field_name:
                return param.min_val, param.max_val
    except Exception:  # noqa: BLE001 — the language is unavailable: the bounds are simply unknown
        return None, None
    return None, None


def _door_host_geometry(capture: Capture, element) -> dict:
    """What is known about the door's host, AS A NUMBER. What is unknown is named explicitly."""
    params = dict(getattr(element, "params", None) or {})
    known = {"host_id": None, "length_mm": None, "bottom_mm": None, "top_mm": None,
             "leaf_width_mm": _finite(params.get("FAMILY_WIDTH_PARAM")),
             "leaf_height_mm": _finite(params.get("FAMILY_HEIGHT_PARAM")),
             "unknown": []}
    host = capture.elements.get(str(getattr(element, "host_id", "") or ""))
    if host is None:
        known["unknown"].append("host")
        return known
    known["host_id"] = str(host.element_id)
    node_params = (capture.by_source.get(str(host.element_id)) or {}).get("params") or {}
    # Length is computed by the SAME law as the compiler's
    # (`hosted_offset_check`): an arc — by radius and angles, a straight one —
    # by its ends. One law, two sites.
    arc = node_params.get("arc")
    if isinstance(arc, Mapping):
        radius = _finite(arc.get("radius_mm"))
        start, end = _finite(arc.get("start_angle_rad")), _finite(arc.get("end_angle_rad"))
        if None not in (radius, start, end):
            known["length_mm"] = abs(radius * (end - start))
    if known["length_mm"] is None:
        p0 = node_params.get("p0_mm") or getattr(host, "p0_mm", None)
        p1 = node_params.get("p1_mm") or getattr(host, "p1_mm", None)
        if p0 and p1 and len(p0) >= 2 and len(p1) >= 2:
            x0, y0, x1, y1 = _finite(p0[0]), _finite(p0[1]), _finite(p1[0]), _finite(p1[1])
            if None not in (x0, y0, x1, y1):
                known["length_mm"] = math.hypot(x1 - x0, y1 - y0)
    if known["length_mm"] is None:
        known["unknown"].append("host_length")
    host_params = dict(getattr(host, "params", None) or {})
    bottom = _finite(node_params.get("base_offset_mm"))
    if bottom is None:
        bottom = _finite(host_params.get("WALL_BASE_OFFSET"))
    known["bottom_mm"] = 0.0 if bottom is None else bottom
    height = _finite(node_params.get("height_mm"))
    if height is None:
        height = _finite(host_params.get("WALL_USER_HEIGHT_PARAM"))
    if height is None:
        known["unknown"].append("host_height")
    else:
        known["top_mm"] = known["bottom_mm"] + height
    return known


def _door_number(field_name: str, value, key: str, geometry: dict) -> tuple:
    """(value, refusal, flags) for `offset_mm`/`sill_mm`. Bounds — the host's.

    🔴 WHY THE UPPER BOUND IS BY LENGTH, NOT BY "LENGTH − LEAF WIDTH." The rule
    "offset ≤ length − width" sounds convincing and is REFUTED BY THE CORPUS:
    in `sob62_r23_v3` it is violated by 89 of 151 existing doors, and the
    reason is mechanical — `offset_mm` sets the door's CENTER, and a 1570 mm
    door standing in the middle of a 2400 mm wall lies entirely inside but
    exceeds "length minus width" (830 mm). Even the centered form of the rule
    (leaf entirely inside) refuses 4 real doors out of 151. The refusal here
    is the COMPILER's law (`hosted_offset_check`: `offset > length` →
    `KIR-T002`), which does not refuse A SINGLE existing door of either run;
    an overhanging leaf is called a FLAG, because it is a fact about the
    building, not a violation.
    """
    number = _finite(value)
    if number is None:
        if isinstance(value, bool):
            return None, _refuse("bad_change_value",
                                 f"{field_name}={value!r}: bool — не измерение; "
                                 f"миллиметры называются числом", key), ()
        if isinstance(value, (int, float)):
            return None, _refuse("non_finite_value",
                                 f"{field_name}={value!r}: NaN/inf — не длина. Такое "
                                 f"значение доезжает до экспорта и рвёт свёртку "
                                 f"безымянно, поэтому отказ ставится ЗДЕСЬ", key), ()
        return None, _refuse("bad_change_value", f"{field_name} must be a number", key), ()

    # First — the HOST: its bounds are narrower, and the refusal names the
    # subject in its own words ("wall 286530, length 7500"), not the
    # language's abstract range. The language's bounds remain the fallback
    # line: they are the only ones when there is nothing to say about the
    # host.
    notes = []
    host_id = geometry.get("host_id")
    low, high = _contract_bounds(field_name)
    beyond = None
    if (low is not None and number < low) or (high is not None and number > high):
        beyond = _refuse("value_out_of_contract",
                         f"{field_name}={number}: язык допускает {low}..{high} "
                         f"(`spec.OPS['create_door']`)", key)
    if field_name == "offset_mm":
        length = geometry.get("length_mm")
        if length is None:
            notes.append("host_length_unknown: длина хозяина "
                         f"{host_id or '<хозяина нет>'} не известна из capture; "
                         "проверены только границы языка")
            return (number, None, tuple(notes)) if beyond is None else (None, beyond, ())
        if number < 0.0 or number > length:
            return None, _refuse(
                "offset_out_of_host",
                f"offset_mm={number}: хозяин {host_id} длиной {length:.0f} мм, "
                f"допустимо 0..{length:.0f}", key), ()
        width = geometry.get("leaf_width_mm")
        if width is not None:
            overhang = max(width / 2.0 - number, number - (length - width / 2.0))
            if overhang > 0.0:
                notes.append(f"leaf_overhangs_host: полотно {width:.0f} мм при "
                             f"offset {number:.0f} выходит за торец хозяина "
                             f"{host_id} на {overhang:.0f} мм")
        return (number, None, tuple(notes)) if beyond is None else (None, beyond, ())

    bottom, top = geometry.get("bottom_mm"), geometry.get("top_mm")
    leaf = geometry.get("leaf_height_mm") or 0.0
    if top is not None and number >= top:
        return None, _refuse(
            "sill_out_of_host",
            f"sill_mm={number}: хозяин {host_id} кончается на {top:.0f} мм от "
            f"своего уровня — дверь оказалась бы целиком выше стены", key), ()
    if bottom is not None and number + leaf <= bottom:
        return None, _refuse(
            "sill_out_of_host",
            f"sill_mm={number}: низ хозяина {host_id} на {bottom:.0f} мм, высота "
            f"полотна {leaf:.0f} мм — дверь оказалась бы целиком ниже стены", key), ()
    if bottom is not None and number < bottom:
        notes.append(f"sill_below_host_bottom: отметка {number:.0f} ниже низа "
                     f"хозяина {host_id} ({bottom:.0f} мм) — дверь пересекает "
                     "стену не целиком")
    if top is not None and number + leaf > top:
        notes.append(f"head_above_host_top: верх двери {number + leaf:.0f} выше "
                     f"верха хозяина {host_id} ({top:.0f} мм)")
    return (number, None, tuple(notes)) if beyond is None else (None, beyond, ())


def type_catalog(capture: Capture) -> dict:
    """Catalog of types ACTUALLY present in the capture. ONE for all readers.

    🔴 ONE CATALOG IS EXACTLY THE FIX FOR OWNER FINDING (4). Before
    07.09.2026, the selector's meaning depended on WHO read it: the edit
    validator looked at `value` (name), while materialization looked at `_id`
    (`materialize.py:1396` translates `{by:"name", …, "_id":ID}` into
    `{by:"element_id", value:ID}` and does NOT READ the name AT ALL). Hence two
    untruths at once: the validator accepted `{by:"name", value:"A"}` without
    `_id`, and the export dropped it («_id None is not an integer»);
    `{by:"name", value:"A", _id:102}` was checked by the validator as «A»,
    while the export set type 102. Now there is ONE translation: `resolve_type`
    returns the CANONICAL selector, in which the name and `_id` refer to the
    same type, and it also serves as the export guard
    (`_symbol_disagreements`).

    Returns `{"by_name": {имя: {id}}, "by_id": {id: имя},
                 "categories": {id: {категории}}, "name_categories": {имя: {категории}}}`.
    """
    if capture.catalog:
        return capture.catalog
    by_name: dict[str, set] = {}
    by_id: dict[str, str] = {}
    categories: dict[str, set] = {}
    name_categories: dict[str, set] = {}
    for element in capture.document.elements:
        name = getattr(element, "type_name", None)
        identifier = getattr(element, "type_id", None)
        if name:
            name_categories.setdefault(str(name), set()).add(element.category)
        if identifier is None or identifier == "":
            continue
        key = str(identifier)
        categories.setdefault(key, set()).add(element.category)
        if name:
            by_name.setdefault(str(name), set()).add(key)
            by_id[key] = str(name)
    capture.catalog = {"by_name": by_name, "by_id": by_id, "categories": categories,
                       "name_categories": name_categories}
    return capture.catalog


def resolve_type(capture: Capture, value, key: str, *, category: str) -> tuple:
    """Type selector -> the CANONICAL `{by:"name", value:<имя>, _id:<id>}`.

    This translation is used by BOTH the edit validator AND the export guard:
    as long as there is one, "checked type A" and "set type A" cannot
    diverge.

    What is checkable here, and what isn't: the capture knows exactly the
    types that ARE PRESENT in it (32 in `bench_A`, 2 of them door types). "The
    type exists in the model" cannot be proven offline, and the refusal says
    exactly what was measured.
    """
    if not isinstance(value, Mapping):
        return None, _refuse("bad_change_value", "symbol must be a selector mapping",
                             key), ()
    by = value.get("by")
    if not value or by is None:
        return None, _refuse("bad_change_value",
                             f"symbol={dict(value)!r}: селектор обязан назвать `by` "
                             f"(name | element_id) и значение", key), ()
    catalog = type_catalog(capture)
    if by == "default":
        # 🔴 IT USED TO BE ACCEPTED WITH A FLAG — AND DROPPED THE EXPORT.
        # `same_document` translates the type selector ONLY through `_id`; for
        # a "document default" there is no `_id`, and there's nowhere for it
        # to come from offline. A flag instead of a refusal meant "accepted,"
        # while the export threw `MaterializeError`.
        return None, _refuse(
            "symbol_unresolvable_offline",
            "symbol.by='default': умолчание документа известно только живой "
            "модели, а экспорт `same_document` адресует тип его `_id`. Назови "
            "тип по имени или по element_id", key), ()
    if by not in ("name", "element_id", "family_type"):
        return None, _refuse("unsupported_symbol_form",
                             f"symbol.by={by!r}: офлайн-правка адресует тип по "
                             f"name или element_id", key), ()
    target = value.get("value")
    if target is None or (isinstance(target, str) and not str(target).strip()):
        return None, _refuse("bad_change_value",
                             f"symbol={dict(value)!r}: у селектора нет значения", key), ()
    target = str(target).strip()
    if by == "element_id":
        resolved_id = target
        if resolved_id not in catalog["by_id"]:
            return None, _refuse(
                "unknown_symbol",
                f"symbol element_id {target!r}: такого типа нет среди "
                f"{len(catalog['by_id'])} стоящих в capture", key), ()
        resolved_name = catalog["by_id"][resolved_id]
    else:
        ids = sorted(catalog["by_name"].get(target, ()))
        if not ids:
            doors = sorted(name for name, cats in catalog["name_categories"].items()
                           if category in cats)
            return None, _refuse(
                "unknown_symbol",
                f"symbol {target!r}: такого типа нет среди "
                f"{len(catalog['by_name'])} стоящих в capture; типы категории "
                f"{category} здесь: {doors[:8]}", key), ()
        if len(ids) > 1:
            # 🔴 A NAME BEHIND WHICH THERE ARE TWO TYPES IS NOT AN ADDRESS.
            # Picking the first one would mean setting a type the author never
            # named, and not saying so.
            return None, _refuse(
                "symbol_ambiguous",
                f"symbol {target!r}: имя носят {len(ids)} типа ({ids}); назови "
                f"тип по element_id — по имени он офлайн не адресуется", key), ()
        resolved_id, resolved_name = ids[0], target
    declared = value.get("_id")
    if declared is not None and str(declared).strip() != str(resolved_id):
        # Exactly the pair the owner named a finding: the name says one thing,
        # `_id` another, and the export listens to `_id`. Silently taking
        # either of the two means silently building the wrong thing.
        return None, _refuse(
            "selector_inconsistent",
            f"symbol {dict(value)!r}: по каталогу capture имя {resolved_name!r} — "
            f"это тип {resolved_id}, а селектор объявил _id {declared}. Экспорт "
            f"адресует тип по _id, проверка шла по имени — они означали бы "
            f"разные типы", key), ()
    found = catalog["categories"].get(str(resolved_id), set())
    if category not in found:
        return None, _refuse(
            "symbol_category_mismatch",
            f"symbol {target!r}: это тип категории {sorted(found)}, а не {category}",
            key), ()
    return {"by": "name", "value": resolved_name, "_id": resolved_id}, None, ()


def _door_symbol(capture: Capture, value, key: str) -> tuple:
    return resolve_type(capture, value, key, category="OST_Doors")


def _symbol_disagreements(capture: Capture) -> list:
    """Nodes where the type name and `_id` mean DIFFERENT things. The export
    guard, the same catalog.

    Exactly what can be checked is checked: an `_id` known to the catalog must
    carry the name declared next to it. An `_id` unknown to the catalog is not
    judged — the capture only sees types that ARE PRESENT, and staying silent
    about its existence is more honest than declaring it nonexistent.
    """
    catalog = type_catalog(capture)
    bad = []

    def walk(value, node, path):
        if isinstance(value, Mapping):
            if value.get("by") in ("name", "family_type") and "_id" in value:
                declared, name = str(value.get("_id")), value.get("value")
                known = catalog["by_id"].get(declared)
                if known is not None and name is not None and str(name) != known:
                    bad.append({"element_id": str(node.get("source_element_id")
                                                  or node.get("_id")),
                                "path": path, "value": str(name), "_id": declared,
                                "catalog_name": known})
            for item_key, item in value.items():
                walk(item, node, f"{path}.{item_key}" if path else str(item_key))
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                walk(item, node, f"{path}[{index}]")

    for node in capture.nodes:
        walk(node.get("params") or {}, node, "params")
    return bad


def _holes_of(node: dict | None) -> tuple:
    """(list of openings, path to it) for a raised floor/ceiling.

    There are TWO forms, and they are mutually exclusive by the lifter's
    construction (KIR-P007): a polygonal profile travels as `outline` +
    `holes`, an arc-based one as `contour` with `outer`/`holes`. Reading both
    in one place is mandatory: two readings of the same fact would drift apart
    exactly where the profile is rare.
    """
    params = (node or {}).get("params") or {}
    contour = params.get("contour")
    if isinstance(contour, Mapping) and isinstance(contour.get("holes"), list):
        return contour["holes"], "params.contour.holes"
    if isinstance(params.get("holes"), list):
        return params["holes"], "params.holes"
    return (), ""


def _ring(value, key: str) -> tuple:
    """A contour ring: a list of points [x, y] in mm. Refusal — by name."""
    from kir import geom as _geom

    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None, _refuse("bad_change_value",
                             f"opening_contour_mm: контур — это список из ≥3 точек "
                             f"[x, y] в мм, получено {type(value).__name__}", key)
    if len(value) > _geom.MAX_HOLE_RING_POINTS:
        return None, _refuse(
            "value_out_of_contract",
            f"opening_contour_mm: {len(value)} точек, язык принимает до "
            f"{_geom.MAX_HOLE_RING_POINTS} в кольце отверстия", key)
    ring = []
    for index, point in enumerate(value):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            return None, _refuse("bad_change_value",
                                 f"opening_contour_mm[{index}]: точка — это [x, y]", key)
        x, y = _finite(point[0]), _finite(point[1])
        if x is None or y is None:
            return None, _refuse("non_finite_value",
                                 f"opening_contour_mm[{index}]={list(point)!r}: "
                                 f"NaN/inf/не-число — не координата", key)
        ring.append([x, y])
    return ring, None


def _edit_opening(capture: Capture, element, node, change, key, untouched, replay):
    """Editing the CONTOUR of an opening in a raised floor/ceiling.

    🔴 THERE IS A POSITIVE SCENARIO, AND IT IS NOT SYNTHETIC. Stage A4 refused
    honestly ("no contour on any of 4223"), but it measured a document raised
    WITHOUT the sketch index: `open_capture` was not handing `profile_index`
    to the lifter. With it, `bench_A` has 21 nodes carrying real opening
    rings — for example floor 286551 with the ring [[12000,2000],[24000,2000],
    [24000,9500],[12000,9500]]. There is still NO guessing by bounding box
    here: the ring that IS EDITED is the one that EXISTS, and it is checked by
    the same law (`geom.check_holes_relation`) the forward pass checks it
    with.
    """
    from kir import geom as _geom

    unknown = sorted(set(change) - set(_OPENING_FIELDS))
    if unknown:
        return _refuse("unsupported_floor_field",
                       f"this contract edits {', '.join(_OPENING_FIELDS)} on a lifted "
                       f"slab; got {unknown}", key)
    if (node or {}).get("kind") != "op":
        return _refuse("floor_is_opaque_atom",
                       f"{element.element_id} lifted as an opaque atom: the slab has "
                       f"no contour operation to edit", key)
    holes, path = _holes_of(node)
    if not holes:
        return _refuse(
            "opening_contour_not_captured",
            f"перекрытие {element.element_id} поднято опом "
            f"{node.get('op_name')!r}, но отверстий в его профиле нет: править "
            f"нечего, а построить отверстие по габариту значило бы выдумать его", key)
    index = change.get("opening_index", 0)
    if isinstance(index, bool) or not isinstance(index, int):
        return _refuse("bad_change_value",
                       f"opening_index={index!r}: номер отверстия — целое", key)
    if not 0 <= index < len(holes):
        return _refuse("opening_index_out_of_range",
                       f"opening_index={index}: у перекрытия {element.element_id} "
                       f"отверстий {len(holes)} ({path})", key)
    if "opening_contour_mm" not in change:
        return _refuse("empty_change",
                       "opening_index без opening_contour_mm ничего не меняет", key)
    ring, refusal = _ring(change["opening_contour_mm"], key)
    if refusal is not None:
        return refusal
    outer = _points_of(_outline_of(node)[0])
    if outer is None:
        return _refuse("opening_contour_not_captured",
                       f"у перекрытия {element.element_id} нет внешнего кольца: "
                       f"проверить вложенность отверстия нечем", key)
    candidate = []
    for position, hole in enumerate(holes):
        points = _points_of(hole)
        if points is None:
            return _refuse("opening_contour_not_captured",
                           f"отверстие {position} у {element.element_id} задано не "
                           f"кольцом точек ({type(hole).__name__}) — править нечем", key)
        candidate.append(ring if position == index else [list(p) for p in points])
    # THE FORWARD PASS'S LAW, NOT ONE'S OWN. `check_holes_relation` is the
    # same thing the lifter and the compiler judge the profile with; a
    # homegrown "is it inside" check would give a second answer to one
    # question.
    diagnostics: list = []
    normalized_outer = _geom.ring_normalize([list(p) for p in outer],
                                            str(element.element_id), "outline", diagnostics)
    normalized = [_geom.ring_normalize(list(hole), str(element.element_id),
                                       f"holes[{position}]", diagnostics)
                  for position, hole in enumerate(candidate)]
    if normalized_outer is None or any(item is None for item in normalized) or diagnostics:
        return _refuse("opening_contour_invalid",
                       f"кольцо не проходит закон прямого хода: "
                       f"{[str(d) for d in diagnostics][:3]}", key)
    if not _geom.check_holes_relation(normalized_outer, normalized,
                                      str(element.element_id), diagnostics):
        return _refuse(
            "opening_outside_outline",
            f"новое кольцо не лежит целиком внутри контура перекрытия "
            f"{element.element_id} (или пересекает соседнее отверстие): "
            f"{[str(d) for d in diagnostics][:3]}", key)
    before = _before_values(capture, key, change)
    existing = holes[index]
    if isinstance(existing, Mapping):
        # The contour form carries the SHAPE KIND; a ring made of straight
        # segments is `poly` without arcs. Leaving someone else's `arcs` with
        # new points would mean building a shape the author never named.
        holes[index] = {"shape": "poly", "points_mm": ring}
    else:
        holes[index] = ring
    if not replay:
        capture.edits.append({"schema": _EDIT_SCHEMA, "element_id": key,
                              "change": dict(change), "before": before,
                              "capture_revision": capture.capture_revision})
        capture.edit_binding = ("before_value"
                                if capture.edit_binding in ("none", "before_value")
                                else "address_only")
        capture.revision_binding = ("pinned"
                                    if capture.revision_binding in ("none", "pinned")
                                    else "unpinned")
    return EditResult(changed_ops=(str(node.get("_id")),), untouched_count=untouched,
                      notes=(f"opening_contour_changed: {path}[{index}] у "
                             f"{node.get('op_name')} перекрытия {element.element_id}",))


def _wall_opening_corner(name: str, value, key: str):
    """An opening's corner — a `pt_xyz` POINT BY THE FORWARD PASS'S LAW, not by
    a homegrown yardstick.

    🔴 THE LAW IS TAKEN FROM THE COMPILER, NOT REWRITTEN FROM SCRATCH.
    `authoring_validation._pt_ok(v, dims=(3,))` is exactly what the compiler
    uses to judge a `pt_xyz`-kind parameter on EVERY op in the registry: shape
    (a list of three numbers) and the scene limit (`COORD_LIMIT_MM`, which
    catches meters used instead of millimeters). A homegrown check here would
    give a SECOND answer to one question and would drift from it exactly where
    the limit is rare.

    Three-dimensionality is not nitpicking, it is stated by the op itself: "a
    flat point would silently drift to elevation 0, and an opening's height in
    a wall is exactly Z: the sill and the lintel" (`ops_opening.py`).
    """
    from kir import authoring_validation as _av

    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None, _refuse(
            "bad_change_value",
            f"{name}: угол проёма в стене — это [x, y, z] в мм (три числа), "
            f"получено {type(value).__name__} длины "
            f"{len(value) if isinstance(value, (list, tuple)) else '-'}", key)
    point = [_finite(component) for component in value]
    if any(component is None for component in point):
        return None, _refuse(
            "non_finite_value",
            f"{name}={list(value)!r}: NaN/inf/не-число — не координата", key)
    if not _av._pt_ok(point, dims=(3,)):
        return None, _refuse(
            "value_out_of_contract",
            f"{name}={point!r}: точка не проходит закон прямого хода для "
            f"pt_xyz (форма или предел сцены {_av._COORD_LIMIT_MM:.0f} мм — "
            f"почти всегда ошибка ЕДИНИЦ, метры вместо миллиметров)", key)
    return point, None


def _edit_wall_opening(capture: Capture, element, node, change, key, untouched, replay):
    """Editing the SIZE AND POSITION of an opening in a wall — two opposite
    corners.

    🔴 WHAT IS EDITED HERE AND WHY THAT IS ENOUGH. `create_opening` of kind
    `wall_rect` is `NewOpening(Wall, XYZ, XYZ)`, and it has no other shape
    inputs at all: the two corners ARE both the size and the position of the
    opening. So the contract needs neither a second field nor a guess — what
    is edited is exactly what the opening is stated by.

    🔴 WHAT IS DELIBERATELY NOT HERE: A CHECK THAT "THE OPENING IS INSIDE THE
    WALL." The temptation is great — the host is right there, it has ends and
    a height. But the forward pass's emitter REFUSED to pin down the shift
    along the wall, and refused it by measurement: "Revit projects the given
    points onto the wall's location plane, and absolute X/Y legitimately drift
    by up to half its thickness. Promising them would mean rolling back a
    CORRECT opening — the exact defect of create_beam" (`opening_emit.py`). A
    homegrown containment check here would refuse exactly the edits the
    forward pass considers correct: it would be a THIRD law about one
    quantity, and the blindest of the three. The opening is judged by the C#
    witness — by the top and bottom elevations and the width along the wall,
    with the `bbox_mm` tolerance of the op itself.
    """
    unknown = sorted(set(change) - set(_WALL_OPENING_FIELDS))
    if unknown:
        return _refuse(
            "unsupported_wall_opening_field",
            f"this contract edits {', '.join(_WALL_OPENING_FIELDS)} on a lifted "
            f"wall opening; got {unknown}", key)
    if (node or {}).get("kind") != "op":
        # 🔴 THE REFUSAL NAMES THE CAUSE, NOT THE CATEGORY. Before 08.09.2026,
        # what arrived here was `unsupported_category` — «this contract edits
        # doors and floor openings only», — and that was an untruth about the
        # cause: the category HAS BEEN IN the lifter's table since 04.09, it
        # has an op, what's missing is the BOUNDARY in the snapshot. Such a
        # refusal sent the reader to look for a different category instead of
        # re-capturing the snapshot.
        reason = ((node or {}).get("reason") or {})
        detail = str(reason.get("detail") or "")
        return _refuse(
            "wall_opening_not_captured",
            f"проём {key} поднят АТОМОМ, править нечего: слепок несёт только "
            f"габаритную коробку (`bbox_min_mm`/`bbox_max_mm`), а границы "
            f"проёма (`Opening.IsRectBoundary` + `Opening.BoundaryRect`) в нём "
            f"нет. Коробка — ОБОЛОЧКА в осях мира, прямоугольник проёма лежит "
            f"в плоскости СТЕНЫ: на стене, не параллельной осям, углы коробки "
            f"не являются углами проёма, и выдать их за них значило бы "
            f"вырезать ДРУГОЙ проём и назвать это правкой. Лечится "
            f"ПЕРЕСЪЁМКОЙ слепка читателем границы (`extract."
            f"_opening_boundary_reader_cs`, заведён 04.09.2026), а не "
            f"контрактом правки. Причина атома: "
            f"{reason.get('code') or 'не названа'}"
            + (f" — {detail}" if detail else ""), key)
    if node.get("op_name") != "create_opening":
        return _refuse(
            "wall_opening_is_not_an_opening_op",
            f"проём {key} поднят опом {node.get('op_name')!r}, а не "
            f"create_opening: править два угла нечему", key)
    params = node.setdefault("params", {})
    variety = params.get("variety")
    if variety != "wall_rect":
        # `host_face` — an opening BY PROFILE, it has no corners at all; the
        # other two kinds are not taken by the registry
        # (`ops_opening.VARIETIES_NOT_TAKEN`).
        return _refuse(
            "wall_opening_variety_not_editable",
            f"проём {key} поднят родом {variety!r}: два противоположных угла "
            f"есть только у variety='wall_rect' (NewOpening(Wall, XYZ, XYZ)); "
            f"род host_face задан ПРОФИЛЕМ, и правка углов сказала бы о нём "
            f"не то", key)
    # 🔴 CHECK EVERYTHING FIRST, THEN APPLY — the same law as for the door. A
    # partial result declared a refusal is the same untruth as a bad edit
    # declared a success.
    checked = {}
    for name, value in change.items():
        point, refusal = _wall_opening_corner(name, value, key)
        if refusal is not None:
            return refusal
        checked[_WALL_OPENING_PARAM[name]] = point
    # A DEGENERATE RECTANGLE IS A REFUSAL, AND THE NUMBER IS TAKEN FROM THE
    # FORWARD PASS. The C# witness computes exactly three quantities from
    # these same two corners (`opening_emit._emit_wall_rect`): the Z band and
    # the width along the wall. Any of them being zero is not a small opening,
    # it is NOT AN OPENING: Revit will refuse via its own ShortCurveTolerance
    # already inside the transaction, meaning the refusal will arrive from a
    # place with nothing to read it from. The `_MIN_SEGMENT_MM` threshold is
    # the very one the compiler judges a short segment with.
    from kir.authoring_validation import _MIN_SEGMENT_MM

    p0 = checked.get("p0_mm", params.get("p0_mm"))
    p1 = checked.get("p1_mm", params.get("p1_mm"))
    if not (isinstance(p0, (list, tuple)) and len(p0) == 3
            and isinstance(p1, (list, tuple)) and len(p1) == 3):
        return _refuse(
            "wall_opening_corner_missing",
            f"у проёма {key} после правки нет обоих углов "
            f"(p0_mm={p0!r}, p1_mm={p1!r}): NewOpening(Wall, XYZ, XYZ) "
            f"требует оба", key)
    height = abs(float(p1[2]) - float(p0[2]))
    width = math.hypot(float(p1[0]) - float(p0[0]), float(p1[1]) - float(p0[1]))
    if height < _MIN_SEGMENT_MM or width < _MIN_SEGMENT_MM:
        return _refuse(
            "wall_opening_degenerate",
            f"прямоугольник проёма вырожден: высота {height:.3f} мм, ширина "
            f"вдоль стены {width:.3f} мм, а прямой ход не строит отрезок "
            f"короче {_MIN_SEGMENT_MM} мм (ShortCurveTolerance Ревита). "
            f"Это не маленький проём, а отсутствие проёма", key)
    # The previous value is captured BEFORE the write: after `update` it's
    # already gone.
    before = _before_values(capture, key, change)
    params.update(checked)
    if not replay:
        capture.edits.append({"schema": _EDIT_SCHEMA, "element_id": key,
                              "change": dict(change), "before": before,
                              "capture_revision": capture.capture_revision})
        capture.edit_binding = ("before_value"
                                if capture.edit_binding in ("none", "before_value")
                                else "address_only")
        capture.revision_binding = ("pinned"
                                    if capture.revision_binding in ("none", "pinned")
                                    else "unpinned")
    return EditResult(
        changed_ops=(str(node.get("_id")),), untouched_count=untouched,
        notes=(f"wall_opening_changed: {sorted(checked)} у create_opening"
               f"(wall_rect) проёма {element.element_id}; высота {height:.1f} мм, "
               f"ширина вдоль стены {width:.1f} мм",))


def _points_of(value):
    """Ring points from BOTH forms: a raw list, or a shape `{shape, points_mm}`."""
    if isinstance(value, Mapping):
        points = value.get("points_mm")
        return points if isinstance(points, list) else None
    return value if isinstance(value, list) else None


def _outline_of(node) -> tuple:
    params = (node or {}).get("params") or {}
    contour = params.get("contour")
    if isinstance(contour, Mapping):
        return contour.get("outer"), "params.contour.outer"
    if isinstance(params.get("outline"), list):
        return params["outline"], "params.outline"
    return None, ""


def edit_element(capture: Capture, element_id, change: Mapping[str, Any],
                 *, _replay: bool = False) -> EditResult:
    """An addressed edit of one element. Everything this contract cannot do is a REFUSAL BY NAME."""
    key = str(element_id)
    element = capture.elements.get(key)
    if element is None:
        return _refuse("unknown_element", "element is absent from this capture", key)
    if not isinstance(change, Mapping) or not change:
        return _refuse("empty_change", "a change must name at least one field", key)
    node = capture.by_source.get(key)
    untouched = len(capture.elements) - 1

    if element.category == "OST_Doors":
        if (node or {}).get("kind") != "op":
            return _refuse("door_is_opaque_atom",
                           "this door did not lift into an operation; there is nothing to edit", key)
        unknown = sorted(set(change) - set(_DOOR_FIELDS))
        if unknown:
            return _refuse("unsupported_door_field",
                           f"this contract edits {', '.join(_DOOR_FIELDS)}; got {unknown}", key)
        # 🔴 CHECK EVERYTHING FIRST, THEN APPLY. The first edition wrote
        # values as it parsed and returned a refusal HALFWAY THROUGH: the edit
        # `{offset_mm: 3300, symbol: {}}` left the new offset in the node and
        # called itself a refusal. A partial result declared a refusal is the
        # same untruth as a bad edit declared a success.
        geometry = _door_host_geometry(capture, element)
        checked, notes = {}, []
        for name, value in change.items():
            if name in ("offset_mm", "sill_mm"):
                number, refusal, said = _door_number(name, value, key, geometry)
            else:
                number, refusal, said = _door_symbol(capture, value, key)
            if refusal is not None:
                return refusal
            checked[name] = number
            notes.extend(said)
        # The previous value is captured BEFORE the write: after `update` it's
        # already gone, and "expected previous" would become a copy of the new
        # value — a binding to nothing.
        before = _before_values(capture, key, change)
        params = node.setdefault("params", {})
        params.update(checked)
        if not _replay:
            capture.edits.append({"schema": _EDIT_SCHEMA, "element_id": key,
                                  "change": dict(change), "before": before,
                                  "capture_revision": capture.capture_revision})
            capture.edit_binding = ("before_value"
                                    if capture.edit_binding in ("none", "before_value")
                                    else "address_only")
            capture.revision_binding = ("pinned"
                                        if capture.revision_binding in ("none", "pinned")
                                        else "unpinned")
        return EditResult(changed_ops=(str(node.get("_id")),), untouched_count=untouched,
                          notes=tuple(notes))

    if element.category in ("OST_Floors", "OST_Ceilings") and set(change) & set(_OPENING_FIELDS):
        return _edit_opening(capture, element, node, change, key, untouched, _replay)

    # 🔴 AN OPENING IN A WALL IS DISPATCHED BY CATEGORY, NOT BY THE EDIT'S
    # FIELDS, and this is not a matter of taste. For a floor, the branch is
    # separated by intersection with `_OPENING_FIELDS` because ONE category
    # (`OST_Floors`) has two edit subjects: the slab itself and the ring in
    # its profile. For a wall opening the subject is exactly one — itself —
    # and branching by fields would mean an edit `{"offset_mm": 100}` on an
    # opening silently falls through into the general refusal instead of
    # saying WHAT this contract can do for an opening.
    if element.category == "OST_SWallRectOpening":
        return _edit_wall_opening(capture, element, node, change, key,
                                  untouched, _replay)

    if str(element.category or "").endswith("FloorOpening") or element.category == "OST_Floors":
        # 🔴 THERE IS NO GUESSING BY BOUNDING BOX HERE, AND THIS IS A
        # DECISION, NOT A GAP. Measurement on `bench_A`: all 24 floors were
        # raised as ATOMS, while for the opening, `opening_boundary_mm` and
        # `opening_is_rect` are empty in 0 of 4223 elements — not one of them
        # has a contour. The opening's bounding box DOES exist, and the
        # temptation to pass it off as a contour is great: a bbox rectangle
        # looks like a real answer. But a bbox is an ENVELOPE, not a contour:
        # it has no rotation, no arcs, and no notion that the opening could be
        # non-rectangular. Passing it off as a contour would mean building a
        # different opening and calling it an edit.
        host = capture.elements.get(str(getattr(element, "host_id", "") or ""))
        if getattr(element, "opening_boundary_mm", None):
            return _refuse("opening_contour_not_implemented",
                           "the capture carries a contour, but this contract does not yet "
                           "translate it; guessing is refused instead", key)
        if host is not None and (capture.by_source.get(str(host.element_id)) or {}
                                 ).get("kind") == "atom":
            return _refuse("floor_is_opaque_atom",
                           f"host floor {host.element_id} lifted as an opaque atom: the slab "
                           "has no contour operation to edit", key)
        return _refuse("opening_contour_not_captured",
                       "L0 carries only a bounding box for this opening; a contour was never "
                       "captured, and a box is not a contour", key)

    return _refuse("unsupported_category",
                   f"{element.category}: this contract edits doors, floor/ceiling "
                   f"openings and wall openings only", key)


# ── save and export ─────────────────────────────────────────────────────
def _is_capture_dir(directory: Path) -> bool:
    try:
        return snapshot_file_exists(directory / "L0.jsonl")
    except OSError:
        return False


def save(capture: Capture, path) -> Path:
    """Save the capture TOGETHER with the edits into a NEW directory. The
    corpus is not touched.

    🔴 "WE DON'T WRITE TO THE CORPUS" IS A RULE, NOT LUCK. Review A4-4 showed
    by execution: `save` into an EMPTY corpus subdirectory was stopped by
    filesystem PERMISSIONS (`PermissionError`, without a code or an address),
    not by the contract; a non-empty directory was saved by its
    non-emptiness. Both are a property of the machine, not of the module:
    under a different owner, the same call would have written into someone
    else's run. The rule here names the SUBJECT: a target that has a snapshot
    (`L0.jsonl`) as an ancestor is someone else's run, and writing into it is
    refused BY NAME.
    """
    target = Path(path)
    if target.exists() and any(target.iterdir()):
        raise CaptureEditError("target_not_empty", f"{target}: refusing to overwrite",
                               str(target))
    resolved = target.resolve()
    source = capture.path.resolve()
    for parent in resolved.parents:
        if not _is_capture_dir(parent):
            continue
        code = "target_inside_source" if parent == source else "target_inside_capture"
        raise CaptureEditError(
            code,
            f"{resolved}: путь лежит ВНУТРИ прогона {parent} (там есть L0.jsonl); "
            f"сохранение обязано идти в НОВЫЙ каталог рядом, а не в чужой снимок",
            str(resolved))
    # 🔴 IT IS ASSEMBLED NEXT TO IT, IT MOVES IN WITH ONE MOTION. 07.09.2026
    # recon measurement: a directory where `L0.jsonl` had already landed but
    # `capture_meta.json` had not yet, `open_capture` took for a COMPLETED
    # save and took `lineage` from the directory name. Now everything is
    # assembled into a neighboring intermediate directory marked
    # `capture_save_incomplete`, and only the whole thing is renamed into
    # place — `os.replace` within one directory, meaning there's no window in
    # which the target is half-full.
    # 🔴 PERMISSIONS ARE ALSO A REFUSAL, NOT A TRACEBACK (07.09.2026
    # self-review probe). Measurement on a target without write permission: it
    # threw `PermissionError: [Errno 13] … /ro/.out.partial-3778667` — a raw
    # library exception, WITHOUT a code, and with the address of a TEMPORARY
    # directory the caller never named. It is impossible to tell "nowhere to
    # write" from "inside someone else's run" and from "target is busy" by
    # such an answer, and they are treated differently.
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise CaptureEditError(
            "target_not_writable",
            f"{target.parent}: каталог назначения не создать "
            f"({type(error).__name__}: {error.strerror or error})",
            str(target)) from error
    # A PID is shared by concurrent saves and proves no ownership of old data.
    # Bound only the diagnostic prefix, not the public destination name. Normal
    # mkdir retains the existing umask policy when staging becomes the target.
    staging = target.parent / f".{target.name[:24]}.partial-{uuid4().hex}"
    try:
        staging.mkdir()  # exclusive: no adoption or deletion on a name collision
    except OSError as error:
        raise CaptureEditError(
            "target_not_writable",
            f"{target.parent}: в этот каталог писать нельзя "
            f"({type(error).__name__}: {error.strerror or error}); сохранение "
            f"собирается РЯДОМ с целью, поэтому право нужно на её родителя",
            str(target)) from error
    try:
        (staging / _PARTIAL_NAME).write_text(
            f"сохранение {resolved} собирается; каталог не является capture\n",
            encoding="utf-8")
        _copy_capture_tree(capture.path, staging, capture.path.resolve())
        with (staging / _EDITS_NAME).open("w", encoding="utf-8") as handle:
            for row in capture.edits:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        _write_meta(capture, staging)
        (staging / _PARTIAL_NAME).unlink()
        # 🔴 "PROVEN EMPTY ABOVE" IS TRUE ONLY WITHOUT A NEIGHBOR, AND THIS IS
        # A RED CAUGHT BY ITS OWN GUARD ON 07.09.2026. The `target_not_empty`
        # check stands at the START, and assembly takes seconds: two processes
        # both pass it, and the loser meets a FULL target here, put there by
        # its neighbor. `rmdir` on a non-empty directory gives `OSError:
        # Directory not empty` — a raw traceback instead of a code, and the
        # caller has nothing to distinguish "busy" from "broken" with. A
        # single run did not see this (6 pairs out of 6 green); a run UNDER
        # LOAD caught it, where the window is wider: [0, 1] instead of [0, 2].
        #
        # The check stays at the start — it is cheaper and answers earlier;
        # here the same refusal BY THE SAME NAME closes the window between the
        # check and the move-in. Exactly one wins, and the loser gets a CODE.
        try:
            if target.exists():
                target.rmdir()          # empty means the target is still free
            os.replace(staging, target)
        except OSError as error:
            raise CaptureEditError(
                "target_not_empty",
                f"{target}: пока сохранение собиралось, цель занял кто-то "
                f"другой ({type(error).__name__}: {error.strerror or error}); "
                f"перезаписать её значило бы снести чужое сохранение",
                str(target)) from error
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target


def _copy_capture_tree(source_dir: Path, dest_dir: Path, root: Path) -> None:
    """Copy the capture WHOLE and do not step outside it.

    🔴 TWO 07.09.2026 RECON MEASUREMENTS, BOTH BY EXECUTION. (1) The previous
    `save` only took top-level `item.is_file()`, while `bench_A` carries a
    nested sidecar `lift_cache/<sha>.json` of 2 727 173 bytes: "saved" meant
    "part of it saved." (2) A symlink `stolen.json -> /etc/hostname`, placed
    into the capture, passed `is_file()` and traveled out WITH ITS CONTENTS —
    the attachment's path stepped outside the capture and carried off an
    arbitrary file from the machine.

    The rule names the SUBJECT: the real write path must lie under the
    capture's root. A symlink pointing inside the root is legitimate and is
    copied by its contents; pointing outside — a refusal by name. Files go
    through `copy2`, i.e. streamed: attachments are not loaded into memory
    whole.
    """
    root_real = os.path.realpath(root)
    for item in sorted(source_dir.iterdir()):
        if source_dir == root and item.name in (_EDITS_NAME, _META_NAME, _PARTIAL_NAME):
            continue
        real = os.path.realpath(item)
        if real != root_real and not real.startswith(root_real + os.sep):
            raise CaptureEditError(
                "capture_path_escapes",
                f"{item}: настоящий путь {real} лежит ВНЕ capture {root_real}; "
                f"копировать его значило бы увезти произвольный файл компьютера",
                str(item))
        if item.is_symlink() and item.is_dir():
            # 🔴 A DIRECTORY SYMLINK IS NOT A CAPTURE ATTACHMENT. 07.09.2026
            # self-review measurement: `loop -> .` (a link to the capture
            # itself) passed the check for stepping outside the root — its
            # `realpath` EQUALS the root — and the walk entered it as a real
            # directory. Someone else's tree would travel out by the same
            # route. A refusal by name, not recursion and not a copy.
            raise CaptureEditError(
                "capture_directory_is_a_symlink",
                f"{item}: каталог-ссылка на {os.path.realpath(item)}; обходить её "
                f"значило бы либо зациклиться, либо увезти чужое дерево",
                str(item))
        if item.is_dir():
            (dest_dir / item.name).mkdir()
            _copy_capture_tree(item, dest_dir / item.name, root)
        elif item.is_file():
            shutil.copy2(item, dest_dir / item.name)


def _write_meta(capture: Capture, target: Path) -> None:
    """Identity and the SOURCE VERSION are pinned here, not derived from the name."""
    digest = capture.source_sha256 or _snapshot_digest(target)
    sidecars = dict(capture.sidecar_digests) or _sidecar_digests(target)
    version = capture.source_version or _source_version(digest, sidecars, capture.profiles)
    (target / _META_NAME).write_text(
        json.dumps({"schema": _META_SCHEMA, "lineage": capture.lineage,
                    "source_sha256": digest, "edits": len(capture.edits),
                    "profiles": capture.profiles, "sidecars": sidecars,
                    "source_version": version,
                    "capture_revision": capture.capture_revision,
                    "revision_schema": _REVISION_SCHEMA},
                   ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8")


def _first_non_finite(nodes) -> tuple | None:
    """The first address where a node carries NaN/inf: (element, path, value)."""
    def walk(value, path):
        if isinstance(value, bool):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return path, value
        if isinstance(value, Mapping):
            for name, item in value.items():
                found = walk(item, f"{path}.{name}" if path else str(name))
                if found is not None:
                    return found
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                found = walk(item, f"{path}[{index}]")
                if found is not None:
                    return found
        return None

    for node in nodes:
        found = walk(node.get("params") or {}, "params")
        if found is not None:
            return str(node.get("source_element_id") or node.get("_id")), found[0], found[1]
    return None


def export_program(capture: Capture, *, revit_version: str = DEFAULT_VERSION):
    """Export the reconstruction: materialize same_document -> envelope with `lineage` -> C#."""
    from kir.compiler import compile_program
    from kir.decompile.fold import fold_document, iter_l1_leaves
    from kir.decompile.materialize import leaves_to_program

    # 🔴 A DEFENSE, NOT A SECOND ENTRY CHECK. The entry is closed off in
    # `edit_element` (`non_finite_value`), but nodes also arrive from the lift
    # and from a saved edits file; review A4-2 caught exactly this path:
    # `NaN` reached `fold_document` and flew out as a `FoldError` without a
    # code and without the element's address, bypassing `export_refusals`.
    # Here the name and the address exist before the fold.
    address = _first_non_finite(capture.nodes)
    if address is not None:
        raise CaptureEditError(
            "non_finite_value",
            f"узел элемента {address[0]}: {address[1]} = {address[2]!r} — NaN/inf "
            f"не сворачивается в программу", address[0])
    # 🔴 THE SAME RESOLVER THE VALIDATOR USES STANDS HERE TOO.
    # `same_document` materialization addresses the type by ITS `_id` and does
    # not read the name at all (`materialize.py:1396`). So a mismatch between
    # the name and `_id` is a program that will build something OTHER than
    # what its own text says, and catching it is the duty of whoever has the
    # catalog, i.e. the capture. Only the `_id` known to the catalog is
    # judged: there is nothing to say about a foreign capture, and staying
    # silent about it is more honest than making something up.
    disagreements = _symbol_disagreements(capture)
    if disagreements:
        first = disagreements[0]
        raise CaptureEditError(
            "selector_inconsistent",
            f"{len(disagreements)} селектор(ов) называют тип одним, а адресуют "
            f"другим; первый — элемент {first['element_id']}, {first['path']}: "
            f"имя {first['value']!r} при _id {first['_id']} (в каталоге этот _id "
            f"носит имя {first['catalog_name']!r}). Экспорт ставит тип по _id",
            first["element_id"])
    try:
        tree = fold_document(capture.document, capture.nodes)
        result = leaves_to_program(list(iter_l1_leaves(tree)), mode="same_document")
    except CaptureEditError:
        raise
    except Exception as exc:  # noqa: BLE001 — someone else's refusal must be given a name
        raise CaptureEditError("export_fold_failed",
                               f"{type(exc).__name__}: {str(exc)[:300]}",
                               str(capture.path)) from exc
    programs = [{**program, "lineage": capture.lineage} for program in result.programs]
    if not programs:
        raise CaptureEditError("nothing_to_export", "materialization produced no program",
                               str(capture.path))
    # 🔴 A COMPILER REFUSAL DOES NOT SILENTLY TURN INTO AN EMPTY STRING.
    # Measurement on `bench_A`: of 18 programs, 16 translate, and two (12
    # `create_duct` each) require a SNAPSHOT of the live model to resolve
    # names — `KIR-G103`. Their source is empty, and without this list,
    # "empty" would read as "nothing to write," i.e. as success. Each refusal
    # carries the program number, codes, and the first message.
    capture.export_refusals = []
    sources = []
    for index, program in enumerate(programs):
        try:
            artifact = compile_program(program, revit_version=revit_version)
        except Exception as exc:  # noqa: BLE001 — a compiler crash is also addressable
            raise CaptureEditError(
                "export_compile_failed",
                f"программа {index} ({len(program.get('ops') or ())} опов): "
                f"{type(exc).__name__}: {str(exc)[:300]}", str(capture.path)) from exc
        source = getattr(artifact, "csharp", None) or getattr(artifact, "code", "") or ""
        if not source:
            capture.export_refusals.append({
                "program": index, "ops": len(program.get("ops") or ()),
                "revit_version": revit_version,
                "codes": sorted({getattr(item, "code", "?")
                                 for item in (artifact.diagnostics or ())}),
                "detail": (str(getattr(next(iter(artifact.diagnostics or ()), None),
                                       "message_ru", "")) or "")[:200]})
        sources.append(source)
    return programs, sources
