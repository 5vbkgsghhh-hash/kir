"""Typed capabilities of the already-open Revit document.

The KIR compiler has always grounded symbolic selectors against one batched
``ground_snapshot`` bridge read.  This module turns that loose dictionary into
a versioned contract without introducing a second catalog:

* the existing snapshot remains the compiler-facing wire shape;
* every catalog row can additionally carry Revit's ``UniqueId`` and
  ``VersionGuid`` so an ``ElementId`` is not mistaken for durable identity;
* every pool carries an observed total, making truncation/completeness a proof
  rather than an assumption;
* the profile is bound to :class:`DocumentFingerprint` and, when persisted by
  a revision-guarded caller, :class:`RevisionProof`;
* same-document preflight checks pinned selectors before the first write.

Compatibility is deliberately fail-closed.  Legacy unversioned snapshots are
still accepted and can ground exactly as before, but missing identity/count
evidence keeps ``authoritative`` false.  An explicit unknown schema version is
refused.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from kir import env  # noqa: E402  (a dependency-free submodule — introduces no cycle)
import re
from bisect import bisect_left
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from kir.contracts import (
    ContractSchemaError,
    DocumentFingerprint,
    ElementIdentityProof,
    RevisionProof,
)
from kir.emit_utils import ELEMENT_ID_MAX
# 🔴 THE LAYER-THICKNESS BOUNDS ARE TAKEN FROM THE REGISTRY, NOT REWRITTEN HERE.
# 2026-08-24, bought live: a literal "strictly greater than zero" used to
# stand here, while `registry_base.WALL_LAYER_MIN_MM` equals zero
# DELIBERATELY and for a reason — "a Membrane layer in Revit has ZERO
# thickness by construction; a ban would reject a legitimate membrane and
# would be our own invention." Two carriers of one law drifted apart, and
# drifted in the direction that closes off the product: EVERY writing
# program on a live document with a membrane got a refusal at the ground
# stage. Measured: "Project2", Revit 2026 — `layers[2] = (0.0, 'Membrane',
# 'Барьер проникновению воздуха')`, refusal on 100% of writing turns.
from kir.registry_base import WALL_LAYER_MAX_MM, WALL_LAYER_MIN_MM


OPEN_MODEL_PROFILE_SCHEMA_VERSION = "open-model-profile/1"
OPEN_MODEL_PREFLIGHT_SCHEMA_VERSION = "open-model-preflight/1"
_VERSION_GUID_RE = re.compile(r"[0-9a-f]{32}\Z")


class OpenModelProfileError(ValueError):
    """A live/serialized model profile is malformed or overclaims evidence."""


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise OpenModelProfileError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise OpenModelProfileError(f"{field_name} keys must be strings")
    return dict(value)


def _string(
    value: Any,
    field_name: str,
    *,
    nonempty: bool = False,
) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        suffix = "a non-empty string" if nonempty else "a string"
        raise OpenModelProfileError(f"{field_name} must be {suffix}")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _string(value, field_name, nonempty=True)


def _optional_evidence_string(value: Any, field_name: str) -> str | None:
    """Treat a bridge catch-path's empty string as absent evidence."""

    if value in (None, ""):
        return None
    return _string(value, field_name, nonempty=True)


def _strict_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise OpenModelProfileError(f"{field_name} must be a JSON boolean")
    return value


def _number(value: Any, field_name: str) -> float:
    """A DOCUMENT number -> `float`. `bool` and a string are a NAMED refusal, not 1.0.

    🔴 A BOOLEAN WAS BECOMING A MILLIMETER (2026-09-04). `TypeSection.from_dict`
    had bare `float(...)` calls, and parsing WAS INVENTING a value that no one
    had measured. Measured before the fix, verbatim:

        sizes=[[True, 2]]          ->  ACCEPTED as (1.0, 2.0)
        layers=[{width_mm: True}]  ->  ACCEPTED as a 1.0 mm layer
        layers=[{width_mm: "200"}] ->  ACCEPTED as a 200.0 mm layer
        sizes=[[None, 2]]          ->  a bare TypeError past the profile dict

    🔴 WHY `__post_init__`, WHICH HAS A CHECK, DID NOT CATCH THIS.
    It checks what was PASSED TO IT, and what was passed was already `1.0` —
    a legitimate positive number. The coercion stood ABOVE the judge and
    deprived it of its subject. It was caught only by accident and only from
    one side: `sizes=[[1, False]]` went red — but not as a `bool`, rather
    because `float(False)` equals zero, and zero is not positive. The same
    falsity asymmetry named in F-079: `True` passed, `False` was rejected,
    and neither one was actually a check.

    The shape of the condition is taken ready-made from `validate_surface`
    (`kir/surface.py`) and from this same file's `__post_init__`; calling out
    `bool` on its own line does not change the meaning of the check — in
    Python it is a subclass of `int`, and without it `True` remains a number.

    FINITENESS AND RANGE ARE DELIBERATELY NOT CHECKED HERE: `__post_init__`
    checks those, and this is exactly the separation the fix was made for —
    parsing TRANSLATES, the judge JUDGES, and the translator must not create
    a value that was not in the input.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OpenModelProfileError(
            f"{field_name} must be a number, got {value!r} "
            f"({type(value).__name__})")
    return float(value)


def _element_id(value: Any, field_name: str) -> int:
    if (isinstance(value, bool) or not isinstance(value, int)
            or not 1 <= value <= ELEMENT_ID_MAX):
        raise OpenModelProfileError(
            f"{field_name} must be an ElementId within 1..{ELEMENT_ID_MAX}")
    return value


#: Profile pools whose `id` is NOT an ElementId. The list is CLOSED, BUT NOT
#: COMPLETE: empty here means "we don't know of such a pool," not "there are
#: no others."
#:
#: 🔴 WHY (measured 2026-08-18 on the owner's live tower, Revit 2023). Parsing
#: `13A-RD-AR-K2_v33` refused ENTIRELY at the first step:
#: `ground_snapshot.worksets[0].id must be an ElementId within 1..…`.
#: The cause is not in the model: it has **3142 worksets, and the first
#: user one carries id = 0** (`!00_Связи_Base`, kind `UserWorkset`; min=0,
#: max=28560, not a single negative). `WorksetId` is a DIFFERENT identifier
#: space, it starts at zero, and applying `ElementId`'s lower bound to it is
#: an error of KIND, not of strictness. The cost was proportionate: a
#: workshared document could not be parsed AT ALL, and worksharing is the
#: norm for a real project.
_NON_ELEMENT_ID_POOLS = frozenset({"worksets"})


def _workset_id(value: Any, field_name: str) -> int:
    """`WorksetId` is non-negative, and zero is LEGITIMATE.

    The lower bound is exactly 0, not "any integer": Revit's `-1` is
    `WorksetId.InvalidWorksetId`, i.e. "there is no workset." Letting it
    through would mean accepting an ABSENCE as an address.
    """
    if (isinstance(value, bool) or not isinstance(value, int)
            or not 0 <= value <= ELEMENT_ID_MAX):
        raise OpenModelProfileError(
            f"{field_name} must be a WorksetId within 0..{ELEMENT_ID_MAX} "
            f"(-1 is Revit's InvalidWorksetId, not an address)")
    return value


#: CLOSED table of spaces. The check lives in ONE place deliberately: before
#: 08-18 the lower bound was checked TWICE — while parsing the row and in
#: `__post_init__` — and fixing one half left the other rejecting the same
#: value. Two checks of one quantity, with nothing forcing them to agree —
#: this project's own named defect.
_ID_SPACES = {"element": _element_id, "workset": _workset_id}


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OpenModelProfileError(
            f"{field_name} must be a non-negative integer")
    return value


def _strings(value: Any, field_name: str) -> tuple[str, ...]:
    if (not isinstance(value, Sequence)
            or isinstance(value, (str, bytes, bytearray))):
        raise OpenModelProfileError(
            f"{field_name} must be a list of strings")
    result = tuple(
        _string(item, f"{field_name}[{index}]", nonempty=True)
        for index, item in enumerate(value)
    )
    if len(result) != len(set(result)):
        raise OpenModelProfileError(f"{field_name} contains duplicates")
    return result


def _optional_vec2(value: Any, field_name: str) -> tuple[float, float] | None:
    if value is None:
        return None
    if (not isinstance(value, Sequence)
            or isinstance(value, (str, bytes, bytearray))
            or len(value) != 2):
        raise OpenModelProfileError(f"{field_name} must contain two numbers")
    result: list[float] = []
    for index, item in enumerate(value):
        if (isinstance(item, bool) or not isinstance(item, (int, float))
                or not math.isfinite(float(item))):
            raise OpenModelProfileError(
                f"{field_name}[{index}] must be a finite number")
        result.append(float(item))
    return result[0], result[1]


def _canonical_object_json(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    row = _mapping(value, field_name)
    try:
        return json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise OpenModelProfileError(
            f"{field_name} must contain only finite JSON values") from exc


#: Kinds of type section. The list is CLOSED: a pool row either leaves here
#: with exactly one kind, or carries no section at all — there is no "similar" kind.
#:
#: `plate`         — a body of constant thickness around its reference
#:                   surface (a wall around an axis, a slab around an elevation);
#: `round`         — a round section of a declared DIAMETER;
#: `rect`          — a rectangular section (width, height);
#: `nominal_table` — a "nominal -> outer" table, read from the type. One row
#:                   by itself does not define a body: a body appears when the
#:                   program NAMES a nominal, and the table translates it into
#:                   an outer size.
SECTION_KINDS = ("plate", "round", "rect", "nominal_table")

#: Maximum rows in the nominal table of ONE type. A pipe segment carries the
#: whole size range; the ceiling keeps the snapshot's weight down, and
#: hitting it is NAMED (`sizes_truncated`), because a truncated table and a
#: missing table are different facts: with the former a nominal may not be
#: found, and that is not "no data."
SECTION_MAX_SIZES = 64


def _список_или_отказ(значение: Any, поле: str) -> Sequence[Any]:
    """A list, or a NAMED refusal. Absence remains absence.

    Introduced in place of three `X or ()` (F-079): `or` erased a wrong value
    BEFORE the type check, and falsy values (`0`, `{}`, `""`) passed as
    "empty," while truthy ones (`42`) were honestly rejected. One field, two
    answers by falsiness — that is not a check, it is a coincidence.
    """
    if значение is None:
        return ()
    if (not isinstance(значение, Sequence)
            or isinstance(значение, (str, bytes, bytearray))):
        raise OpenModelProfileError(f"{поле} must be a list")
    return значение


@dataclass(frozen=True, slots=True)
class TypeSection:
    """TYPE geometry: exactly what bounds the body of an element of this type.

    WHY THIS IS HERE. Measured 09-08 against the registry (`spec.OPS`, 48
    operations): not one creation operation carries wall thickness, slab
    thickness, or column section — `create_wall` declares an axis and a
    height, `create_cable_tray` only an axis. All these numbers live in the
    TYPE, and the type is resolved against the LIVE document exactly at the
    ground stage. So the only place where the section is knowable at all is
    here, and before this wave the pool row carried only `{id, name}`.

    THE HONESTY OF THE `uniform` FIELD. A number by itself does not grant the
    right to build a prism: a wall with a composition that varies by height, a
    sloped wall, a wall with protrusions — a single-thickness prism does NOT
    contain their body, i.e. it allows a clash to be MISSED. So the entry
    carries two fields at once: a number, and a verdict on whether it bounds
    the body. `uniform=False` without `blockers` is impossible — the reason
    must be NAMED, otherwise "there is no body" is indistinguishable from "we
    didn't look."

    Units are millimeters, as in the whole snapshot.
    """

    kind: str
    source: str
    thickness_mm: float | None = None
    diameter_mm: float | None = None
    width_mm: float | None = None
    height_mm: float | None = None
    #: The type size's own extent along Z relative to the INSERTION POINT, mm.
    #: The sign matters: on a real column the base goes BELOW its elevation
    #: (measured 09-08 on Snowdon: 4 columns out of 114 extended past the
    #: shell by exactly 254.0 mm downward — this is the family's geometry, not
    #: a bug in the program).
    local_z_min_mm: float | None = None
    local_z_max_mm: float | None = None
    #: Pairs `(nominal_mm, outer_mm)`, sorted by nominal.
    sizes: tuple[tuple[float, float], ...] = ()
    sizes_truncated: bool = False
    uniform: bool = False
    blockers: tuple[str, ...] = ()
    #: THE LAYER COMPOSITION, outside to inside, as returned by
    #: `CompoundStructure.GetLayers()`. One triple per layer:
    #: `(thickness_mm, function, material_name | None)`.
    #:
    #: 🔴 WHY SEPARATE FROM `thickness_mm`, AND WHY ONE NUMBER IS NOT ENOUGH.
    #: Measured 2026-08-23: a wall type cannot be reproduced in A FOREIGN
    #: document, because there is nothing to reproduce — the profile knew only
    #: the TOTAL thickness. An op that created a type from a single thickness
    #: would give the wall the right name and the right volume with the WRONG
    #: layer stack, and there would be nothing to catch it with: the
    #: `create_wall` witness is silent about the type, `verify.json` does not
    #: read layers, and the clash shell takes `WallType.Width` and would come out
    #: CORRECT. A silently-wrong outcome.
    #:
    #: 🔴 THE LINK TO THE MATERIAL IS BY NAME, NOT BY `unique_id` AND NOT BY
    #: `ElementId`. The consumer of this entry is creating the type in ANOTHER
    #: document, where the source's id means nothing (exactly what the
    #: `fresh_document` name dialect was built for). A material's `unique_id` in
    #: a clean document will also be different: it is stable for a COPY of an
    #: element, not for a same-named material created anew. The name is the only
    #: thing that carries over.
    #:
    #: `None` in the third field means a layer WITHOUT a material, and this is a
    #: legitimate Revit state (`MaterialId == InvalidElementId`), not "we didn't read it."
    layers: tuple[tuple[float, str, str | None], ...] = ()
    #: `True` if the composition was asked for and COULD NOT be read.
    #: Distinguishes "there are no layers" from "we didn't look": an empty
    #: `layers` without this flag on an old snapshot means exactly the latter.
    layers_unreadable: bool = False

    def __post_init__(self) -> None:
        if self.kind not in SECTION_KINDS:
            raise OpenModelProfileError(
                f"type_section.kind must be one of {SECTION_KINDS}")
        _string(self.source, "type_section.source", nonempty=True)
        for field_name, value in (
            ("thickness_mm", self.thickness_mm),
            ("diameter_mm", self.diameter_mm),
            ("width_mm", self.width_mm),
            ("height_mm", self.height_mm),
        ):
            if value is None:
                continue
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(float(value)) or float(value) <= 0.0):
                raise OpenModelProfileError(
                    f"type_section.{field_name} must be a positive number")
        for field_name, value in (("local_z_min_mm", self.local_z_min_mm),
                                  ("local_z_max_mm", self.local_z_max_mm)):
            if value is None:
                continue
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))):
                raise OpenModelProfileError(
                    f"type_section.{field_name} must be a finite number")
        if ((self.local_z_min_mm is None) != (self.local_z_max_mm is None)):
            raise OpenModelProfileError(
                "type_section local z bounds must both be present or absent")
        if (self.local_z_min_mm is not None
                and float(self.local_z_min_mm) > float(self.local_z_max_mm)):
            raise OpenModelProfileError(
                "type_section.local_z_min_mm must not exceed local_z_max_mm")
        if not isinstance(self.sizes, tuple):
            raise OpenModelProfileError("type_section.sizes must be a tuple")
        previous = None
        for index, pair in enumerate(self.sizes):
            if (not isinstance(pair, tuple) or len(pair) != 2
                    or any(isinstance(item, bool)
                           or not isinstance(item, (int, float))
                           or not math.isfinite(float(item))
                           or float(item) <= 0.0 for item in pair)):
                raise OpenModelProfileError(
                    f"type_section.sizes[{index}] must be two positive numbers")
            if previous is not None and float(pair[0]) <= previous:
                raise OpenModelProfileError(
                    "type_section.sizes must be sorted by unique nominal")
            previous = float(pair[0])
        _strict_bool(self.sizes_truncated, "type_section.sizes_truncated")
        _strict_bool(self.uniform, "type_section.uniform")
        # LAYERS. EVERY field of the triple is checked, BUT USING THE
        # REGISTRY'S BOUNDS, not its own: this is a profile of an OBSERVED
        # document, and applying to it the contract of what WE OURSELVES
        # write means declaring a legitimate Revit entry a defect. Zero
        # thickness on `Membrane` is exactly that.
        if not isinstance(self.layers, tuple):
            raise OpenModelProfileError("type_section.layers must be a tuple")
        for index, layer in enumerate(self.layers):
            if not isinstance(layer, tuple) or len(layer) != 3:
                raise OpenModelProfileError(
                    f"type_section.layers[{index}] must be a triple "
                    "(width_mm, function, material_name|None)")
            width, function, material = layer
            if (isinstance(width, bool) or not isinstance(width, (int, float))
                    or not math.isfinite(float(width))
                    or float(width) < WALL_LAYER_MIN_MM
                    or float(width) > WALL_LAYER_MAX_MM):
                # A REFUSAL MUST PRINT THE MEASURED VALUE, NOT JUST THE
                # EXPECTED ONE (canon form 43). The previous text named the
                # field and stayed silent about the value — and this refusal
                # shuts out the ENTIRE LIVE ENTRY, and the value here is the
                # only evidence: it shows whether this is our own defect or a
                # legitimate Revit entry. It did show that the defect was
                # OURS: `0.0 (function='Membrane')`.
                raise OpenModelProfileError(
                    f"type_section.layers[{index}].width_mm must be within "
                    f"[{WALL_LAYER_MIN_MM}, {WALL_LAYER_MAX_MM}] mm, "
                    f"got {width!r} (function={function!r}, "
                    f"material={material!r})")
            _string(function, f"type_section.layers[{index}].function",
                    nonempty=True)
            if material is not None:
                _string(material, f"type_section.layers[{index}].material",
                        nonempty=True)
        _strict_bool(self.layers_unreadable, "type_section.layers_unreadable")
        # "We read it and couldn't" is incompatible with "here is the
        # composition": two answers to one question — the same disease as
        # `uniform` together with `blockers`.
        if self.layers and self.layers_unreadable:
            raise OpenModelProfileError(
                "type_section cannot carry layers and be unreadable at once")
        blockers = _strings(self.blockers, "type_section.blockers")
        if blockers != tuple(sorted(blockers)):
            raise OpenModelProfileError(
                "type_section.blockers must be sorted")
        # The census's law, carried over to one row: "does not bound" without
        # a reason is the same silence this whole module protects against.
        if self.uniform and blockers:
            raise OpenModelProfileError(
                "type_section cannot be uniform and blocked at once")
        if not self.uniform and not blockers and self.kind != "nominal_table":
            raise OpenModelProfileError(
                "non-uniform type_section must name its blockers")

    def to_dict(self) -> dict[str, Any]:
        """The canonical row. Empty fields are OMITTED, not nulled: a
        snapshot without a section must stay byte-for-byte the same (see the fingerprints)."""
        row: dict[str, Any] = {"kind": self.kind, "source": self.source}
        for key, value in (
            ("thickness_mm", self.thickness_mm),
            ("diameter_mm", self.diameter_mm),
            ("width_mm", self.width_mm),
            ("height_mm", self.height_mm),
        ):
            if value is not None:
                row[key] = float(value)
        if self.local_z_min_mm is not None:
            row["local_z_min_mm"] = float(self.local_z_min_mm)
            row["local_z_max_mm"] = float(self.local_z_max_mm)
        if self.sizes:
            row["sizes"] = [[float(a), float(b)] for a, b in self.sizes]
        if self.sizes_truncated:
            row["sizes_truncated"] = True
        if self.uniform:
            row["uniform"] = True
        if self.blockers:
            row["blockers"] = list(self.blockers)
        # 🔴 OMITTED, NOT NULLED — like everything above. A snapshot taken
        # before this wave must serialize BYTE FOR BYTE as before; an empty
        # `layers` list in the row would shift the fingerprints of the whole corpus.
        if self.layers:
            row["layers"] = [
                {"width_mm": float(width), "function": function,
                 **({} if material is None else {"material": material})}
                for width, function, material in self.layers
            ]
            row["layer_count"] = len(self.layers)
        if self.layers_unreadable:
            row["layers_unreadable"] = True
        return row

    @classmethod
    def from_dict(cls, value: Any, *,
                  field_name: str = "type_section") -> "TypeSection":
        row = _mapping(value, field_name)
        # 🔴 ABSENCE IS NOT THE SAME AS INVALID (F-079, confirmed by execution
        # on 2026-09-04). `row.get("sizes") or ()` used to stand here, and
        # this ERASED an invalid value BEFORE the type check — an asymmetry by falsiness:
        #
        #     sizes=42   ->  named refusal «sizes must be a list»
        #     sizes=0    ->  ACCEPTED as sizes=()      <- same field, same harm
        #     layers=0   ->  ACCEPTED as "there are no layers"
        #     layers={}  ->  ACCEPTED as "there are no layers"
        #
        # A profile is evidence about the TYPE of a live document: "there are
        # no layers" and "the layers could not be read" are different
        # assertions, and the second one must be named. The key being absent
        # entirely is the legitimate answer "taken before the layers wave,"
        # and it remains so.
        raw_sizes = _список_или_отказ(row.get("sizes"), f"{field_name}.sizes")
        sizes: list[tuple[float, float]] = []
        for index, pair in enumerate(raw_sizes):
            if (not isinstance(pair, Sequence)
                    or isinstance(pair, (str, bytes, bytearray))
                    or len(pair) != 2):
                raise OpenModelProfileError(
                    f"{field_name}.sizes[{index}] must be a pair")
            sizes.append((
                _number(pair[0], f"{field_name}.sizes[{index}][0]"),
                _number(pair[1], f"{field_name}.sizes[{index}][1]")))
        raw_blockers = _список_или_отказ(row.get("blockers"),
                                         f"{field_name}.blockers")
        # LAYERS. A missing key means "taken before the layers wave," and
        # this is an ANSWER, not a zero: an old profile must be read back with the exact same value.
        raw_layers = _список_или_отказ(row.get("layers"), f"{field_name}.layers")
        layers: list[tuple[float, str, str | None]] = []
        for index, layer in enumerate(raw_layers):
            row_layer = _mapping(layer, f"{field_name}.layers[{index}]")
            material = row_layer.get("material")
            layers.append((
                _number(row_layer.get("width_mm"),
                        f"{field_name}.layers[{index}].width_mm"),
                _string(row_layer.get("function"),
                        f"{field_name}.layers[{index}].function",
                        nonempty=True),
                None if material is None else _string(
                    material, f"{field_name}.layers[{index}].material",
                    nonempty=True),
            ))
        # 🔴 A DECLARED WITNESS IS CHECKED, NOT REWRITTEN. The emitter puts
        # `layer_count` next to the layers (`open_model.py` C#), and the
        # reader was ignoring it: ONE layer with `layer_count: 999` was
        # accepted and, on the round trip, serialized back as `layer_count:
        # 1`. Evidence that gets silently corrected stops being evidence.
        # 🔴 `bool` WAS NOT AN EXCEPTION BUT A HOLE IN THIS SAME LAW (2026-09-04).
        # The condition `not isinstance(заявлено, bool)` did not reject a
        # boolean — it TOOK IT OUT of the check entirely: `layer_count: true`
        # with one layer was accepted silently (measured), and the declared
        # witness, the very reason the check was set up, disappeared by
        # exactly the means it is supposed to guard against. The tree's idiom
        # — `isinstance(x, bool) or not isinstance(x, int)` — rejects a
        # boolean rather than pardoning it.
        заявлено = row.get("layer_count")
        if заявлено is not None:
            if isinstance(заявлено, bool) or not isinstance(заявлено, int):
                raise OpenModelProfileError(
                    f"{field_name}.layer_count must be an integer")
            if заявлено != len(layers):
                raise OpenModelProfileError(
                    f"{field_name}.layer_count says {заявлено}, "
                    f"but {len(layers)} layers are present")
        return cls(
            kind=_string(row.get("kind"), f"{field_name}.kind", nonempty=True),
            source=_string(
                row.get("source"), f"{field_name}.source", nonempty=True),
            thickness_mm=row.get("thickness_mm"),
            diameter_mm=row.get("diameter_mm"),
            width_mm=row.get("width_mm"),
            height_mm=row.get("height_mm"),
            local_z_min_mm=row.get("local_z_min_mm"),
            local_z_max_mm=row.get("local_z_max_mm"),
            sizes=tuple(sizes),
            sizes_truncated=_strict_bool(
                row.get("sizes_truncated", False),
                f"{field_name}.sizes_truncated"),
            uniform=_strict_bool(
                row.get("uniform", False), f"{field_name}.uniform"),
            blockers=_strings(list(raw_blockers), f"{field_name}.blockers"),
            layers=tuple(layers),
            layers_unreadable=_strict_bool(
                row.get("layers_unreadable", False),
                f"{field_name}.layers_unreadable"),
        )

    def outer_for_nominal_mm(self, nominal_mm: float,
                             *, tol_mm: float = 0.5) -> float | None:
        """A nominal -> the OUTER size from the TYPE's table, or `None`.

        There is no coefficient here, and there cannot be one: the
        translation exists exactly because the document itself printed it
        (`PipeSegment.GetSizes`). A nominal that is not in the table is NOT
        approximated by this function — "almost matched" is the same
        invention as a conversion factor.

        `tol_mm` is the tolerance for comparing TWO NUMBERS IN MILLIMETERS
        that arrived by different paths (the program writes 100.0, the
        document stores feet and converts back). 0.5 mm is chosen as half the
        smallest step in the size range, not as "small": neighboring DN
        nominals are at least 4 mm apart (DN6/DN8), so this tolerance cannot
        confuse two nominals.
        """
        if (isinstance(nominal_mm, bool)
                or not isinstance(nominal_mm, (int, float))
                or not math.isfinite(float(nominal_mm))):
            return None
        target = float(nominal_mm)
        for nominal, outer in self.sizes:
            if abs(nominal - target) <= tol_mm:
                return outer
        return None


def prune_ground_snapshot(snapshot: Any) -> dict[str, Any]:
    """A snapshot -> only what is needed for the BODY: elevations and type sections.

    Lives here because the snapshot dialect belongs to this module, and a
    whole snapshot cannot be carried through the session: the
    `family_symbols` pool can run to thousands of rows, and 99% of its fields
    (`unique_id`, `version_guid`, counters) have no effect on the shell at all.

    An empty dict and the ABSENCE of a dict are different facts, and here
    they are different values: empty means "we asked, there are no
    sections," absence means "we didn't ask." The reader must tell them apart.
    """
    if not isinstance(snapshot, Mapping):
        return {}
    out: dict[str, Any] = {}
    for pool, rows in snapshot.items():
        if not isinstance(pool, str) or not isinstance(rows, list):
            continue
        keep: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            if pool == "levels":
                if row.get("elevation_mm") is None:
                    continue
                keep.append({"id": row.get("id"), "name": row.get("name"),
                             "elevation_mm": row["elevation_mm"]})
            elif isinstance(row.get("section"), Mapping):
                keep.append({"id": row.get("id"), "name": row.get("name"),
                             "section": dict(row["section"])})
        if keep:
            out[pool] = keep
    return out


def required_grounding_pools() -> tuple[str, ...]:
    """Return the exact pool universe declared by the live OpSpec registry."""

    from kir import spec

    pools: set[str] = set()
    for op_spec in spec.OPS.values():
        # A UNION, NOT A SINGLE DECLARATION: for a pool decided by a
        # parameter, the snapshot must carry ALL possible ones — it is taken before the run.
        for pool in op_spec.grounded_pools:
            if "{category}" in pool:
                pools.update(pool.format(category=value) for value in (
                    "structural", "architectural"))
            else:
                pools.add(pool)
    # ``at_grid`` is a contour sublanguage selector, not an OpSpec parameter.
    pools.add("grids")
    return tuple(sorted(pools))


@dataclass(frozen=True, slots=True)
class ModelCatalogEntry:
    """One selectable Revit datum/type/symbol with exact live identity."""

    element_id: int
    name: str
    unique_id: str | None = None
    version_guid: str | None = None
    class_name: str | None = None
    category: str | None = None
    family_name: str | None = None
    type_name: str | None = None
    params_json: str | None = None
    p0_mm: tuple[float, float] | None = None
    p1_mm: tuple[float, float] | None = None
    #: TYPE geometry (the sections wave). NOT part of `binding_digest`: that
    #: signs the row's IDENTITY, while the section is its content. A
    #: snapshot taken before this wave must produce the same fingerprint as before.
    section: "TypeSection | None" = None
    #: The level elevation in mm — only on rows of the `levels` pool. Without
    #: it, a program that declared a wall on a level has NOT A SINGLE Z
    #: elevation, and it has no body by construction, no matter how many thicknesses the type knows.
    elevation_mm: float | None = None
    #: FAMILY PLACEMENT TYPE — the trait by which a candidate can be unfit BY
    #: CONSTRUCTION, not by taste: an adaptive op needs `Adaptive`, a beam
    #: needs `CurveDriven*`, `place_family` places only point-based ones.
    #:
    #: 🔴 2026-08-24, FOUND LIVE, AND THIS IS THE THIRD CASE OF ONE PATTERN IN
    #: ONE DAY. The trait was added by the C# emission (`8b3e5f64`, same day)
    #: exactly for the refusal that presents candidates. The profile was NOT
    #: MODELING it — and with `KUKAI_IR_OPEN_MODEL_PREFLIGHT=1` turned on
    #: (also 08-24) the snapshot passes through
    #: `OpenModelProfile.to_ground_snapshot()`, meaning the trait taken by
    #: Revit WAS BEING DISCARDED BY US on the way to the consumer. Measured
    #: live: the `create_adaptive_component` refusal carried five candidates
    #: with category and family and WITHOUT a placement type — and that
    #: placement type is exactly what makes them unfit.
    #:
    #: Like `section` and `elevation_mm`: the row's CONTENT, not its
    #: identity. Not part of `binding_digest`, and OMITTED rather than nulled
    #: when absent — otherwise the fingerprint of every decompile taken
    #: before this wave would shift.
    placement_type: str | None = None
    #: The row's IDENTIFIER SPACE. NOT part of `to_dict()` and therefore does
    #: not shift the fingerprint of any already-taken decompile: this is a
    #: property of the POOL, not the row's content. Values are the keys of `_ID_SPACES`.
    id_space: str = "element"

    def __post_init__(self) -> None:
        _ID_SPACES[self.id_space](
            self.element_id, "catalog_entry.element_id")
        _string(self.name, "catalog_entry.name")
        for field_name, value in (
            ("unique_id", self.unique_id),
            ("version_guid", self.version_guid),
            ("class_name", self.class_name),
            ("category", self.category),
            ("family_name", self.family_name),
            ("type_name", self.type_name),
            ("placement_type", self.placement_type),
        ):
            _optional_string(value, f"catalog_entry.{field_name}")
        if self.params_json is not None:
            _string(
                self.params_json, "catalog_entry.params_json", nonempty=True)
            try:
                parsed = json.loads(self.params_json)
            except (TypeError, ValueError) as exc:
                raise OpenModelProfileError(
                    "catalog_entry.params_json is invalid JSON") from exc
            canonical = _canonical_object_json(
                parsed, "catalog_entry.params_json")
            if canonical != self.params_json:
                raise OpenModelProfileError(
                    "catalog_entry.params_json must be canonical")
        _optional_vec2(self.p0_mm, "catalog_entry.p0_mm")
        _optional_vec2(self.p1_mm, "catalog_entry.p1_mm")
        if (self.p0_mm is None) != (self.p1_mm is None):
            raise OpenModelProfileError(
                "catalog entry grid endpoints must both be present or absent")
        if self.section is not None and not isinstance(
                self.section, TypeSection):
            raise OpenModelProfileError(
                "catalog_entry.section must be a typed TypeSection")
        if self.elevation_mm is not None and (
                isinstance(self.elevation_mm, bool)
                or not isinstance(self.elevation_mm, (int, float))
                or not math.isfinite(float(self.elevation_mm))):
            raise OpenModelProfileError(
                "catalog_entry.elevation_mm must be a finite number")

    @property
    def identity_exact(self) -> bool:
        return (
            self.unique_id is not None
            and self.version_guid is not None
            and _VERSION_GUID_RE.fullmatch(self.version_guid) is not None
        )

    @property
    def binding_digest(self) -> str:
        payload = {
            "element_id": self.element_id,
            "unique_id": self.unique_id,
            "version_guid": self.version_guid,
            "class_name": self.class_name,
            "category": self.category,
            "family_name": self.family_name,
            "type_name": self.type_name,
            "name": self.name,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @property
    def params(self) -> dict[str, Any] | None:
        return (
            None if self.params_json is None
            else json.loads(self.params_json)
        )

    def to_ground_row(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": self.element_id,
            "name": self.name,
        }
        for key, value in (
            ("unique_id", self.unique_id),
            ("version_guid", self.version_guid),
            ("class_name", self.class_name),
            ("category", self.category),
            ("family_name", self.family_name),
            ("type_name", self.type_name),
        ):
            if value is not None:
                row[key] = value
        if self.params_json is not None:
            row["params"] = self.params
        if self.p0_mm is not None:
            row["p0_mm"] = list(self.p0_mm)
            row["p1_mm"] = list(self.p1_mm or ())
        if self.section is not None:
            row["section"] = self.section.to_dict()
        if self.elevation_mm is not None:
            row["elevation_mm"] = float(self.elevation_mm)
        if self.placement_type is not None:
            row["placement_type"] = self.placement_type
        return row

    def to_dict(self) -> dict[str, Any]:
        row = {
            "element_id": self.element_id,
            "name": self.name,
            "unique_id": self.unique_id,
            "version_guid": self.version_guid,
            "class_name": self.class_name,
            "category": self.category,
            "family_name": self.family_name,
            "type_name": self.type_name,
            "params": self.params,
            "p0_mm": (
                list(self.p0_mm) if self.p0_mm is not None else None),
            "p1_mm": (
                list(self.p1_mm) if self.p1_mm is not None else None),
            "identity_exact": self.identity_exact,
            "binding_digest": self.binding_digest,
        }
        # WHAT IS ABSENT STAYS ABSENT. The other fields are nulled (as before,
        # unchanged), but these two are OMITTED: the profile's `digest` is
        # computed over this same dict, and `"section": null` would shift the
        # fingerprint of EVERY decompile taken before this wave.
        if self.section is not None:
            row["section"] = self.section.to_dict()
        if self.elevation_mm is not None:
            row["elevation_mm"] = float(self.elevation_mm)
        if self.placement_type is not None:
            row["placement_type"] = self.placement_type
        return row

    @classmethod
    def from_ground_row(
        cls,
        value: Any,
        *,
        field_name: str = "catalog_entry",
        id_space: str = "element",
    ) -> "ModelCatalogEntry":
        row = _mapping(value, field_name)
        if id_space not in _ID_SPACES:
            raise OpenModelProfileError(
                f"{field_name}: unknown id_space {id_space!r}")
        return cls(
            id_space=id_space,
            element_id=_ID_SPACES[id_space](
                row.get("id"), f"{field_name}.id"),
            name=_string(row.get("name"), f"{field_name}.name"),
            unique_id=_optional_evidence_string(
                row.get("unique_id"), f"{field_name}.unique_id"),
            version_guid=_optional_evidence_string(
                row.get("version_guid"), f"{field_name}.version_guid"),
            class_name=_optional_evidence_string(
                row.get("class_name"), f"{field_name}.class_name"),
            category=_optional_evidence_string(
                row.get("category"), f"{field_name}.category"),
            family_name=_optional_evidence_string(
                row.get("family_name"), f"{field_name}.family_name"),
            type_name=_optional_evidence_string(
                row.get("type_name"), f"{field_name}.type_name"),
            params_json=_canonical_object_json(
                row.get("params"), f"{field_name}.params"),
            p0_mm=_optional_vec2(row.get("p0_mm"), f"{field_name}.p0_mm"),
            p1_mm=_optional_vec2(row.get("p1_mm"), f"{field_name}.p1_mm"),
            section=(
                None if row.get("section") is None
                else TypeSection.from_dict(
                    row["section"], field_name=f"{field_name}.section")),
            elevation_mm=row.get("elevation_mm"),
            placement_type=_optional_evidence_string(
                row.get("placement_type"), f"{field_name}.placement_type"),
        )

    @classmethod
    def from_dict(
        cls,
        value: Any,
        *,
        field_name: str = "catalog_entry",
        id_space: str = "element",
    ) -> "ModelCatalogEntry":
        row = _mapping(value, field_name)
        entry = cls.from_ground_row(
            {
                **row,
                "id": row.get("element_id", row.get("id")),
            },
            field_name=field_name,
            id_space=id_space,
        )
        if ("identity_exact" in row
                and _strict_bool(
                    row["identity_exact"], f"{field_name}.identity_exact")
                != entry.identity_exact):
            raise OpenModelProfileError(
                f"{field_name}.identity_exact mismatch")
        if ("binding_digest" in row
                and _string(
                    row["binding_digest"], f"{field_name}.binding_digest",
                    nonempty=True) != entry.binding_digest):
            raise OpenModelProfileError(
                f"{field_name}.binding_digest mismatch")
        return entry


@dataclass(frozen=True, slots=True)
class ModelCatalogPool:
    """A deterministically ordered catalog plus a completeness witness."""

    name: str
    entries: tuple[ModelCatalogEntry, ...]
    total_count: int | None
    truncated: bool
    _ids: tuple[int, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _string(self.name, "catalog_pool.name", nonempty=True)
        if (not isinstance(self.entries, tuple)
                or not all(isinstance(item, ModelCatalogEntry)
                           for item in self.entries)):
            raise OpenModelProfileError(
                "catalog_pool.entries must be a typed tuple")
        ids = tuple(item.element_id for item in self.entries)
        if ids != tuple(sorted(set(ids))):
            raise OpenModelProfileError(
                "catalog_pool.entries must be sorted by unique ElementId")
        object.__setattr__(self, "_ids", ids)
        if self.total_count is not None:
            _nonnegative_int(self.total_count, "catalog_pool.total_count")
            if self.total_count < len(self.entries):
                raise OpenModelProfileError(
                    "catalog_pool.total_count is below captured row count")
        _strict_bool(self.truncated, "catalog_pool.truncated")
        if (self.total_count is not None
                and self.total_count > len(self.entries)
                and not self.truncated):
            raise OpenModelProfileError(
                "incomplete catalog pool must declare truncated=true")
        if (self.total_count is not None
                and self.total_count == len(self.entries)
                and self.truncated):
            raise OpenModelProfileError(
                "complete catalog pool cannot declare truncated=true")

    @property
    def complete(self) -> bool:
        return (
            self.total_count is not None
            and self.total_count == len(self.entries)
            and not self.truncated
        )

    @property
    def identity_complete(self) -> bool:
        return all(item.identity_exact for item in self.entries)

    def entry(self, element_id: int) -> ModelCatalogEntry | None:
        # All construction paths enforce sorted unique IDs in __post_init__.
        # Preserve the former equality-only lookup for untyped legacy callers.
        if not isinstance(element_id, int):
            return next((item for item in self.entries
                         if item.element_id == element_id), None)
        position = bisect_left(self._ids, element_id)
        if position < len(self._ids) and self._ids[position] == element_id:
            return self.entries[position]
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "entries": [item.to_dict() for item in self.entries],
            "captured_count": len(self.entries),
            "total_count": self.total_count,
            "truncated": self.truncated,
            "complete": self.complete,
            "identity_complete": self.identity_complete,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ModelCatalogPool":
        row = _mapping(value, "catalog_pool")
        raw_entries = row.get("entries")
        if not isinstance(raw_entries, list):
            raise OpenModelProfileError(
                "catalog_pool.entries must be an array")
        # 🔴 THE IDENTIFIER SPACE IS DECIDED BY THE POOL'S NAME, AND IT MUST
        # BE READ BEFORE THE ROWS (F-077, 2026-08-30). `from_ground_snapshot`
        # knew this and passed `id_space`, but `from_dict` did not: it always
        # parsed rows as `element`. As long as `worksets` was silently
        # discarded, the hole did not show; as soon as a pool beyond the
        # required ones started GETTING THROUGH, the `to_dict` -> `from_dict`
        # round trip started rejecting its own output — for the set of
        # worksets `id` 0 is legitimate, and for an element it is not.
        pool_name = _string(
            row.get("name"), "catalog_pool.name", nonempty=True)
        entries = tuple(sorted(
            (
                ModelCatalogEntry.from_dict(
                    item, field_name=f"catalog_pool.entries[{index}]",
                    id_space=("workset"
                              if pool_name in _NON_ELEMENT_ID_POOLS
                              else "element"))
                for index, item in enumerate(raw_entries)
            ),
            key=lambda item: item.element_id,
        ))
        raw_total = row.get("total_count")
        pool = cls(
            name=pool_name,
            entries=entries,
            total_count=(
                None if raw_total is None
                else _nonnegative_int(
                    raw_total, "catalog_pool.total_count")
            ),
            truncated=_strict_bool(
                row.get("truncated", False), "catalog_pool.truncated"),
        )
        for field_name, actual in (
            ("captured_count", len(pool.entries)),
            ("complete", pool.complete),
            ("identity_complete", pool.identity_complete),
        ):
            if field_name not in row:
                continue
            supplied = (
                _nonnegative_int(row[field_name], f"catalog_pool.{field_name}")
                if field_name == "captured_count"
                else _strict_bool(
                    row[field_name], f"catalog_pool.{field_name}")
            )
            if supplied != actual:
                raise OpenModelProfileError(
                    f"catalog_pool.{field_name} mismatch")
        return pool


@dataclass(frozen=True, slots=True)
class OpenModelProfile:
    """Capabilities and exact selectable identities of one open document."""

    schema_version: str
    document_fingerprint: DocumentFingerprint | None
    revit_version: str
    revit_build: str | None
    required_pools: tuple[str, ...]
    pools: tuple[ModelCatalogPool, ...]
    revision_proof: RevisionProof | None = None
    #: 🔴 POOLS THE SNAPSHOT CARRIED BUT THE PROFILE COULD NOT TAKE (F-077).
    #: Before 2026-08-30 such a pool vanished WITHOUT A SINGLE WORD:
    #: `from_ground_snapshot` traversed only `required`, and everything
    #: beyond it disappeared together with the reverse snapshot — not a
    #: refusal, but SILENCE. Now a pool beyond the required ones is KEPT, and
    #: only the one whose rows could not be parsed lands here: for an
    #: optional pool, a failure has no right to fail the turn, but it must
    #: BE HEARD.
    dropped_pools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != OPEN_MODEL_PROFILE_SCHEMA_VERSION:
            raise OpenModelProfileError(
                f"unsupported open model profile schema_version "
                f"{self.schema_version!r}")
        if (self.document_fingerprint is not None
                and not isinstance(
                    self.document_fingerprint, DocumentFingerprint)):
            raise OpenModelProfileError(
                "document_fingerprint must be typed or null")
        _string(self.revit_version, "open_model.revit_version")
        _optional_string(self.revit_build, "open_model.revit_build")
        required = _strings(
            self.required_pools, "open_model.required_pools")
        if required != tuple(sorted(required)):
            raise OpenModelProfileError(
                "open_model.required_pools must be sorted")
        if (not isinstance(self.pools, tuple)
                or not all(isinstance(item, ModelCatalogPool)
                           for item in self.pools)):
            raise OpenModelProfileError(
                "open_model.pools must be a typed tuple")
        names = tuple(item.name for item in self.pools)
        if names != tuple(sorted(set(names))):
            raise OpenModelProfileError(
                "open_model.pools must be sorted with unique names")
        if (self.revision_proof is not None
                and not isinstance(self.revision_proof, RevisionProof)):
            raise OpenModelProfileError(
                "open_model.revision_proof must be typed or null")
        dropped = _strings(self.dropped_pools, "open_model.dropped_pools")
        if dropped != tuple(sorted(set(dropped))):
            raise OpenModelProfileError(
                "open_model.dropped_pools must be sorted with unique names")

    @property
    def identity_bound(self) -> bool:
        fingerprint = self.document_fingerprint
        return bool(
            fingerprint is not None
            and fingerprint.title
            and (fingerprint.path_name or fingerprint.project_uid)
        )

    @property
    def grounding_complete(self) -> bool:
        by_name = {pool.name: pool for pool in self.pools}
        return all(
            name in by_name and by_name[name].complete
            for name in self.required_pools
        )

    @property
    def identity_complete(self) -> bool:
        by_name = {pool.name: pool for pool in self.pools}
        return all(
            name in by_name and by_name[name].identity_complete
            for name in self.required_pools
        )

    @property
    def authoritative(self) -> bool:
        return (
            self.identity_bound
            and self.grounding_complete
            and self.identity_complete
            and self.revision_proof is not None
        )

    def pool(self, name: str) -> ModelCatalogPool | None:
        return next((pool for pool in self.pools if pool.name == name), None)

    def _canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "document_fingerprint": (
                self.document_fingerprint.to_dict()
                if self.document_fingerprint is not None else None
            ),
            "revit_version": self.revit_version,
            "revit_build": self.revit_build,
            "required_pools": list(self.required_pools),
            "pools": [pool.to_dict() for pool in self.pools],
            "revision_proof": (
                self.revision_proof.to_dict()
                if self.revision_proof is not None else None
            ),
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self._canonical_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._canonical_payload(),
            "identity_bound": self.identity_bound,
            "grounding_complete": self.grounding_complete,
            "identity_complete": self.identity_complete,
            "authoritative": self.authoritative,
            # 🔴 DELIBERATELY NOT IN `_canonical_payload`: the profile's
            # fingerprint is computed EXACTLY from it, and adding the lost
            # pools here would shift the `digest` of ALL already-taken
            # profiles (83 in the corpus), and `from_dict` checks the
            # fingerprint and would reject every one of them. The field is
            # for reporting, not for identity.
            "dropped_pools": list(self.dropped_pools),
            "digest": self.digest,
        }

    def to_ground_snapshot(self) -> dict[str, Any]:
        """Return the existing compiler snapshot dialect, deterministically."""

        result: dict[str, Any] = {}
        for pool in self.pools:
            result[pool.name] = [
                entry.to_ground_row() for entry in pool.entries]
            if pool.total_count is not None:
                result[pool.name + "__total"] = pool.total_count
            if pool.truncated:
                result[pool.name + "__truncated"] = True
        if self.document_fingerprint is not None:
            result["__document_fingerprint"] = (
                self.document_fingerprint.compiler_guard())
        result["__profile_schema_version"] = self.schema_version
        result["__profile_required_pools"] = list(self.required_pools)
        result["__revit_version"] = self.revit_version
        result["__revit_build"] = self.revit_build
        return result

    @classmethod
    def from_ground_snapshot(
        cls,
        value: Any,
        *,
        revision_proof: RevisionProof | None = None,
        required_pools: Sequence[str] | None = None,
    ) -> "OpenModelProfile":
        """Upgrade the current or legacy ground-snapshot wire shape."""

        row = _mapping(value, "ground_snapshot")
        explicit_version = row.get("__profile_schema_version")
        if (explicit_version is not None
                and explicit_version != OPEN_MODEL_PROFILE_SCHEMA_VERSION):
            raise OpenModelProfileError(
                f"unsupported open model profile schema_version "
                f"{explicit_version!r}")
        required = tuple(sorted(_strings(
            (
                required_pools
                if required_pools is not None
                else row.get(
                    "__profile_required_pools",
                    required_grounding_pools())
            ),
            "open_model.required_pools",
        )))
        def _pool_from_row(name: str) -> ModelCatalogPool | None:
            raw_entries = row.get(name)
            if raw_entries is None:
                return None
            if not isinstance(raw_entries, list):
                raise OpenModelProfileError(
                    f"ground_snapshot.{name} must be an array")
            entries = tuple(sorted(
                (
                    ModelCatalogEntry.from_ground_row(
                        item,
                        field_name=(
                            f"ground_snapshot.{name}[{index}]"),
                        id_space=("workset"
                                  if name in _NON_ELEMENT_ID_POOLS
                                  else "element"))
                    for index, item in enumerate(raw_entries)
                ),
                key=lambda item: item.element_id,
            ))
            raw_total = row.get(name + "__total")
            raw_truncated = row.get(name + "__truncated", False)
            return ModelCatalogPool(
                name=name,
                entries=entries,
                total_count=(
                    None if raw_total is None
                    else _nonnegative_int(
                        raw_total, f"ground_snapshot.{name}__total")
                ),
                truncated=_strict_bool(
                    raw_truncated,
                    f"ground_snapshot.{name}__truncated"),
            )

        pools: list[ModelCatalogPool] = []
        for name in required:
            pool = _pool_from_row(name)
            if pool is not None:
                pools.append(pool)
        # 🔴 A POOL BEYOND THE REQUIRED ONES NO LONGER DISAPPEARS SILENTLY (F-077).
        # Before, the traversal went ONLY over `required`, and everything the
        # snapshot carried beyond it vanished without a word — together with
        # the reverse snapshot that goes into grounding. Measured 08-30: a
        # snapshot with `materials` produced a profile without `materials`,
        # with no exception and no mark.
        # Completeness (`grounding_complete`/`identity_complete`/`authoritative`)
        # is computed OVER `required_pools`, so an extra pool does not move
        # it — it merely stops getting lost.
        seen = set(required)
        dropped: list[str] = []
        for key, value in row.items():
            if (key in seen or key.startswith("__")
                    or key.endswith(("__total", "__truncated"))
                    or not isinstance(value, list)):
                continue
            seen.add(key)
            try:
                pool = _pool_from_row(key)
            except OpenModelProfileError:
                # For an OPTIONAL pool, a failure has no right to fail the
                # turn — but it must BE HEARD. A required pool still refuses.
                dropped.append(key)
                continue
            if pool is not None:
                pools.append(pool)
        raw_fingerprint = row.get("__document_fingerprint")
        return cls(
            schema_version=OPEN_MODEL_PROFILE_SCHEMA_VERSION,
            document_fingerprint=(
                None if raw_fingerprint is None
                else DocumentFingerprint.from_dict(raw_fingerprint)
            ),
            revit_version=_string(
                row.get("__revit_version", ""),
                "open_model.revit_version"),
            revit_build=_optional_evidence_string(
                row.get("__revit_build"), "open_model.revit_build"),
            required_pools=required,
            pools=tuple(sorted(pools, key=lambda item: item.name)),
            revision_proof=revision_proof,
            dropped_pools=tuple(sorted(set(dropped))),
        )

    @classmethod
    def from_dict(cls, value: Any) -> "OpenModelProfile":
        row = _mapping(value, "open_model")
        version = row.get(
            "schema_version", OPEN_MODEL_PROFILE_SCHEMA_VERSION)
        if version != OPEN_MODEL_PROFILE_SCHEMA_VERSION:
            raise OpenModelProfileError(
                f"unsupported open model profile schema_version {version!r}")
        raw_pools = row.get("pools", [])
        if not isinstance(raw_pools, list):
            raise OpenModelProfileError("open_model.pools must be an array")
        raw_fingerprint = row.get("document_fingerprint")
        raw_revision = row.get("revision_proof")
        profile = cls(
            schema_version=OPEN_MODEL_PROFILE_SCHEMA_VERSION,
            document_fingerprint=(
                None if raw_fingerprint is None
                else DocumentFingerprint.from_dict(raw_fingerprint)
            ),
            revit_version=_string(
                row.get("revit_version", ""), "open_model.revit_version"),
            revit_build=_optional_evidence_string(
                row.get("revit_build"), "open_model.revit_build"),
            required_pools=tuple(sorted(_strings(
                row.get("required_pools", ()),
                "open_model.required_pools",
            ))),
            pools=tuple(sorted(
                (ModelCatalogPool.from_dict(item) for item in raw_pools),
                key=lambda item: item.name,
            )),
            revision_proof=(
                None if raw_revision is None
                else RevisionProof.from_dict(raw_revision)
            ),
            dropped_pools=tuple(sorted(set(_strings(
                row.get("dropped_pools", ()),
                "open_model.dropped_pools",
            )))),
        )
        for field_name, actual in (
            ("identity_bound", profile.identity_bound),
            ("grounding_complete", profile.grounding_complete),
            ("identity_complete", profile.identity_complete),
            ("authoritative", profile.authoritative),
        ):
            if (field_name in row
                    and _strict_bool(
                        row[field_name], f"open_model.{field_name}") != actual):
                raise OpenModelProfileError(
                    f"open_model.{field_name} mismatch")
        if ("digest" in row
                and _string(
                    row["digest"], "open_model.digest", nonempty=True)
                != profile.digest):
            raise OpenModelProfileError("open_model.digest mismatch")
        return profile


class PreflightIssueCode(str, Enum):
    PROFILE_POOL_MISSING = "profile_pool_missing"
    PROFILE_POOL_INCOMPLETE = "profile_pool_incomplete"
    PINNED_ELEMENT_MISSING = "pinned_element_missing"
    PINNED_IDENTITY_UNPROVEN = "pinned_identity_unproven"
    PINNED_IDENTITY_CHANGED = "pinned_identity_changed"
    DOCUMENT_IDENTITY_CHANGED = "document_identity_changed"


@dataclass(frozen=True, slots=True)
class ModelBinding:
    op_index: int
    op_id: str
    parameter: str
    pool: str
    element_id: int
    binding_digest: str
    unique_id: str | None
    version_guid: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "op_index": self.op_index,
            "op_id": self.op_id,
            "parameter": self.parameter,
            "pool": self.pool,
            "element_id": self.element_id,
            "binding_digest": self.binding_digest,
        }


@dataclass(frozen=True, slots=True)
class ModelPreflightIssue:
    code: PreflightIssueCode
    detail: str
    op_index: int | None = None
    op_id: str | None = None
    parameter: str | None = None
    pool: str | None = None
    element_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code.value,
            "detail": self.detail,
        }
        for name, value in (
            ("op_index", self.op_index),
            ("op_id", self.op_id),
            ("parameter", self.parameter),
            ("pool", self.pool),
            ("element_id", self.element_id),
        ):
            if value is not None:
                result[name] = value
        return result


@dataclass(frozen=True, slots=True)
class OpenModelPreflight:
    profile_digest: str
    bindings: tuple[ModelBinding, ...]
    issues: tuple[ModelPreflightIssue, ...]

    @property
    def ready(self) -> bool:
        return not self.issues

    def exact_identity_proofs(self) -> tuple[ElementIdentityProof, ...]:
        """Return deduplicated transaction guards for a successful preflight."""

        if not self.ready:
            raise OpenModelProfileError(
                "cannot emit identity guards for a refused preflight")
        by_id: dict[int, ElementIdentityProof] = {}
        for binding in self.bindings:
            if binding.unique_id is None or binding.version_guid is None:
                raise OpenModelProfileError(
                    "preflight binding has no exact identity proof")
            try:
                proof = ElementIdentityProof(
                    element_id=binding.element_id,
                    unique_id=binding.unique_id,
                    version_guid=binding.version_guid,
                )
            except ContractSchemaError as exc:
                raise OpenModelProfileError(
                    "preflight binding identity proof is malformed") from exc
            prior = by_id.get(proof.element_id)
            if prior is not None and prior != proof:
                raise OpenModelProfileError(
                    "one ElementId has contradictory identity proofs")
            by_id[proof.element_id] = proof
        return tuple(by_id[element_id] for element_id in sorted(by_id))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": OPEN_MODEL_PREFLIGHT_SCHEMA_VERSION,
            "profile_digest": self.profile_digest,
            "ready": self.ready,
            "binding_count": len(self.bindings),
            "bindings": [item.to_dict() for item in self.bindings],
            "issue_count": len(self.issues),
            "issues": [item.to_dict() for item in self.issues],
        }


def _iter_program_ops(programs: Any) -> Iterable[tuple[int, Mapping[str, Any]]]:
    from kir import macros
    from kir.midend import PlannedProgram

    raw_programs = (
        [programs]
        if isinstance(programs, (Mapping, PlannedProgram))
        else programs
    )
    if (not isinstance(raw_programs, Sequence)
            or isinstance(raw_programs, (str, bytes, bytearray))):
        return ()
    flattened: list[tuple[int, Mapping[str, Any]]] = []
    global_index = 0
    for program in raw_programs:
        if isinstance(program, PlannedProgram):
            # The compiler already expanded, defaulted and validated this exact
            # immutable payload. Re-expanding its source would reopen drift.
            expanded = program.to_ops()
        else:
            if not isinstance(program, Mapping):
                continue
            raw_ops = program.get("ops")
            if not isinstance(raw_ops, list):
                continue
            try:
                expanded = macros.expand(raw_ops)
            except Exception:
                # Compiler validation owns malformed macro diagnostics.
                # Preflight must not replace them with a less useful model-
                # profile error.
                expanded = raw_ops
        for op in expanded:
            if isinstance(op, Mapping):
                flattened.append((global_index, op))
            global_index += 1
    return tuple(flattened)


def open_model_preflight_enabled() -> bool:
    """Opt-in gate for the open-model preflight on the LIVE write path; default OFF.

    This preflight is the only fail-closed check here that can REFUSE a
    write where the write used to go through: ``ready`` requires an empty
    issues list, and an issue arises when the ``element_id`` selector is not
    found in the snapshot's catalogs.  On a TRUNCATED snapshot of a large
    model, a legitimate element can end up outside the catalog — and get a
    refusal instead of a write.  This has only been checked on synthetic
    fixtures and bridge mocks, never on a live Revit.

    Hence — like ``KUKAI_IR_NATIVE_GROUP`` and ``KUKAI_BRIDGE_IDENTITY_ACCEPT``:
    off by default, turned on deliberately.  With the flag off, the path
    degrades to EXACTLY the previous behavior (the raw snapshot as is), not to some new one.
    """

    return env.get("KIR_OPEN_MODEL_PREFLIGHT", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def preflight_programs(
    programs: Any,
    profile: OpenModelProfile,
    *,
    expected_profile: OpenModelProfile | None = None,
    require_exact_identity: bool = False,
) -> OpenModelPreflight:
    """Check every pinned grounding selector before any Revit transaction.

    Name/default selectors remain owned by ``ground.py``.  This fills its one
    intentional gap: an ``element_id`` selector historically skipped the
    snapshot and was only null-checked inside the transaction.  For
    ``same_document`` rebuilds an optional source ``expected_profile`` also
    proves that the id was not reused or semantically changed.
    """

    if not isinstance(profile, OpenModelProfile):
        raise OpenModelProfileError("profile must be OpenModelProfile")
    if (expected_profile is not None
            and not isinstance(expected_profile, OpenModelProfile)):
        raise OpenModelProfileError(
            "expected_profile must be OpenModelProfile or null")
    issues: list[ModelPreflightIssue] = []
    bindings: list[ModelBinding] = []

    if expected_profile is not None:
        if (profile.document_fingerprint is None
                or expected_profile.document_fingerprint is None
                or profile.document_fingerprint
                != expected_profile.document_fingerprint):
            issues.append(ModelPreflightIssue(
                code=PreflightIssueCode.DOCUMENT_IDENTITY_CHANGED,
                detail="target open document differs from source profile",
            ))

    from kir import spec

    for op_index, op in _iter_program_ops(programs):
        op_name = op.get("op")
        op_spec = spec.OPS.get(op_name) if isinstance(op_name, str) else None
        if op_spec is None:
            continue
        op_id = str(op.get("id") or f"op{op_index}")
        # The triples are TAKEN FROM THE CALL: the
        # `create_wall_type.source_type` pool decides `host_kind`, and a
        # static read would search for a floor type among wall types.
        for parameter, pool_template, _required in op_spec.grounded_for(op):
            if (op_spec.name == "create_foundation"
                    and ((parameter == "symbol"
                          and op.get("variety") != "isolated")
                         or (parameter == "type"
                             and op.get("variety") != "slab"))):
                continue
            selector = op.get(parameter)
            if not isinstance(selector, Mapping):
                continue
            grounded = selector.get("__grounded__")
            if isinstance(grounded, Mapping):
                # A post-ground compiler pass covers by=name/family_type too.
                # Intra-program refs and document defaults have no pre-existing
                # ElementId and are guarded by their dedicated emit path.
                if grounded.get("via") == "ref":
                    continue
                raw_id = grounded.get("id")
                if raw_id is None:
                    continue
            elif selector.get("by") == "element_id":
                raw_id = selector.get("value")
            else:
                continue
            try:
                pinned_id = _element_id(
                    raw_id, f"{op_id}.{parameter}.value")
            except OpenModelProfileError:
                # Compiler selector validation owns malformed values.
                continue
            pool_name = (
                pool_template.format(
                    category=op.get("category", "structural"))
                if "{category}" in pool_template else pool_template
            )
            pool = profile.pool(pool_name)
            common = {
                "op_index": op_index,
                "op_id": op_id,
                "parameter": parameter,
                "pool": pool_name,
                "element_id": pinned_id,
            }
            if pool is None:
                issues.append(ModelPreflightIssue(
                    code=PreflightIssueCode.PROFILE_POOL_MISSING,
                    detail=f"open model profile has no {pool_name} pool",
                    **common,
                ))
                continue
            legacy_count_unproven = (
                pool.total_count is None and not pool.truncated)
            if not pool.complete and (
                    require_exact_identity or not legacy_count_unproven):
                issues.append(ModelPreflightIssue(
                    code=PreflightIssueCode.PROFILE_POOL_INCOMPLETE,
                    detail=f"open model profile pool {pool_name} is incomplete",
                    **common,
                ))
                continue
            entry = pool.entry(pinned_id)
            if entry is None:
                issues.append(ModelPreflightIssue(
                    code=PreflightIssueCode.PINNED_ELEMENT_MISSING,
                    detail=(
                        f"ElementId {pinned_id} is absent from {pool_name}"),
                    **common,
                ))
                continue
            if require_exact_identity and not entry.identity_exact:
                issues.append(ModelPreflightIssue(
                    code=PreflightIssueCode.PINNED_IDENTITY_UNPROVEN,
                    detail=(
                        f"ElementId {pinned_id} has no UniqueId/VersionGuid "
                        "identity proof"),
                    **common,
                ))
                continue
            if expected_profile is not None:
                expected_pool = expected_profile.pool(pool_name)
                expected = (
                    expected_pool.entry(pinned_id)
                    if expected_pool is not None else None
                )
                if (expected is None
                        or not expected.identity_exact
                        or expected.binding_digest != entry.binding_digest):
                    issues.append(ModelPreflightIssue(
                        code=PreflightIssueCode.PINNED_IDENTITY_CHANGED,
                        detail=(
                            f"ElementId {pinned_id} identity differs from "
                            "the source profile"),
                        **common,
                    ))
                    continue
            bindings.append(ModelBinding(
                op_index=op_index,
                op_id=op_id,
                parameter=parameter,
                pool=pool_name,
                element_id=pinned_id,
                binding_digest=entry.binding_digest,
                unique_id=entry.unique_id,
                version_guid=entry.version_guid,
            ))

    return OpenModelPreflight(
        profile_digest=profile.digest,
        bindings=tuple(bindings),
        issues=tuple(issues),
    )


async def capture_open_model_profile(
    executor: Any,
    *,
    timeout_ms: int = 30_000,
    revision_proof: RevisionProof | None = None,
) -> OpenModelProfile:
    """Capture one profile through a bridge-shaped async executor.

    A pipeline revision guard may wrap ``executor``; in that case it returns
    the read payload directly.  Plain serving executors commonly return one or
    more ``{"result": ...}`` envelopes, which are unwrapped conservatively.
    """

    if not callable(executor):
        raise OpenModelProfileError("profile executor must be callable")
    if (isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int)
            or timeout_ms <= 0):
        raise OpenModelProfileError(
            "profile timeout_ms must be a positive integer")
    value = await executor(GROUND_SNAPSHOT_CS, timeout_ms=timeout_ms)
    for _ in range(3):
        if not isinstance(value, Mapping):
            break
        if value.get("ok") is False or value.get("error"):
            raise OpenModelProfileError(
                "open model profile bridge read failed")
        nested = value.get("result")
        if not isinstance(nested, Mapping):
            break
        value = nested
    if not isinstance(value, Mapping):
        raise OpenModelProfileError(
            "open model profile bridge payload must be an object")
    return OpenModelProfile.from_ground_snapshot(
        value, revision_proof=revision_proof)


# Read-only ground-snapshot collector (version-safe 2021-2026; C# 7.3).
# The top-level pool dialect is unchanged.  ``__*`` metadata and per-row exact
# identity fields are additive; old compiler/ground consumers ignore them.
_GROUND_SNAPSHOT_CS_TEMPLATE = r"""
Func<Element, long> __Id = (Element __e) => { try { return long.Parse(__e.Id.ToString()); } catch { return -1; } };
Func<double, double> __MM = (double __ft) => UnitUtils.ConvertFromInternalUnits(__ft, UnitTypeId.Millimeters);
// НАЗВАННОЕ УМОЛЧАНИЕ (замер 02.08.2026, Snowdon): сколько экземпляров каждого
// типоразмера УЖЕ РАЗМЕЩЕНО в этом документе. Без этого числа ground не может
// назвать правило «самый употребимый», и единственным исходом на 62 кандидатах
// остаётся отказ — при том, что плечо C# в том же документе взяло 1 тип из 62
// молча. Один проход по экземплярам: типов в каталоге тысячи, но правило
// опирается на ПРАКТИКУ проекта, а её знают только размещённые элементы.
// long.Parse(...ToString()) — тот же версионно-нейтральный приём, что и __Id:
// целочисленное свойство ElementId сменило имя и тип в 2024+, а ToString()
// одинаков на всех шести (страж test_open_model держит это правило подстрокой,
// поэтому старое имя нельзя даже упоминать — и это правильно).
var __instCount = new Dictionary<long, int>();
try
{
    foreach (var __fi in new FilteredElementCollector(doc).OfClass(typeof(FamilyInstance)))
    {
        long __tid;
        try { __tid = long.Parse(__fi.GetTypeId().ToString()); } catch { continue; }
        if (__tid <= 0) continue;
        int __prev;
        __instCount[__tid] = __instCount.TryGetValue(__tid, out __prev) ? __prev + 1 : 1;
    }
}
catch { }
// ─────────────────────────────────────────────────────────────────────────
// СЕЧЕНИЕ ТИПА (волна sections, 09.08.2026). ЗАЧЕМ: замер по реестру
// (`spec.OPS`, 48 операций) — НИ ОДНА операция создания не несёт толщину
// стены, перекрытия или сечение колонны. Они живут в ТИПЕ, а тип разрешается
// против живого документа ровно здесь. До этой волны строка пула несла
// `{id, name}`, и потому `kir/clash/` не мог построить тело НИ ОДНОМУ
// заявленному элементу: на двух реальных зданиях — ноль оболочек.
//
// ВСЕ ЧЛЕНЫ НИЖЕ СКОМПИЛИРОВАНЫ НА ШЕСТИ ВЕРСИЯХ (:52412, 09.08.2026):
//   Level.Elevation                              2021-2026 6/6
//   WallType.Width, WallType.Kind                2021-2026 6/6
//   HostObjAttributes.GetCompoundStructure       2021-2026 6/6
//   CompoundStructure.GetWidth                   2021-2026 6/6
//   CompoundStructure.IsVerticallyHomogeneous()  2021-2026 6/6
//   CompoundStructure.GetWallSweepsInfo(WallSweepType)  2021-2026 6/6
//   CompoundStructure.VariableLayerIndex         2021-2026 6/6
//   CompoundStructure.HasStructuralDeck          2021-2026 6/6
//   CompoundStructure.GetLayers                  2021-2026 6/6  (23.08)
//   CompoundStructureLayer.Width|Function|MaterialId  2021-2026 6/6  (23.08)
//   MaterialFunctionAssignment (ToString)        2021-2026 6/6  (23.08)
//   PipeType.RoutingPreferenceManager            2021-2026 6/6
//   RoutingPreferenceManager.GetNumberOfRules/GetRule   2021-2026 6/6
//   PipeSegment.GetSizes / MEPSize.Nominal|OuterDiameter 2021-2026 6/6
//   BuiltInParameter.STRUCTURAL_SECTION_COMMON_*  2021-2026 6/6
// Версионно-условных чтений здесь поэтому НЕТ: тело снапшота одно на все
// шесть, и отсутствующий на 2021 член сломал бы весь снапшот целиком.
//
// ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. У ЛОТКА сечения на типе не существует ни в одной
// из шести версий: `CableTrayType` несёт только `BendMultiplier`,
// `IsWithFitting`, `ShapeType` (сверено по RevitAPI.xml и компиляцией), а
// `Autodesk.Revit.DB.Electrical.CableTraySizeSettings` не существует вовсе
// (CS0234 на всех шести). Ширина и высота лотка — параметры ЭКЗЕМПЛЯРА, и
// `CableTray.Create(doc, typeId, p0, p1, levelId)` их не принимает. Значит
// молчание тут честное: тела у лотка нет не потому, что снапшот беден, а
// потому, что ни операция, ни тип его не выражают.
Func<Element, BuiltInParameter, double> __ParamMM =
    (Element __pe, BuiltInParameter __bip) =>
{
    try
    {
        var __p = __pe.get_Parameter(__bip);
        if (__p == null || !__p.HasValue
            || __p.StorageType != StorageType.Double) return 0.0;
        return __MM(__p.AsDouble());
    }
    catch { return 0.0; }
};
Func<Element, string, Dictionary<string, object>> __Section =
    (Element __e, string __cat) =>
{
    var __sec = new Dictionary<string, object>();
    var __blk = new List<string>();
    // 1. СТЕНА. Толщина есть, но одного числа МАЛО: у наклонной, ступенчатой
    //    и составной по высоте стены призма по толщине тело НЕ содержит, то
    //    есть допускает пропуск клеша. Поэтому число едет вместе с приговором.
    var __wt = __e as WallType;
    if (__wt != null)
    {
        double __ww = 0.0;
        try { __ww = __MM(__wt.Width); } catch { }
        if (!(__ww > 0.0)) return null;
        __sec["kind"] = "plate";
        __sec["source"] = "WallType.Width";
        __sec["thickness_mm"] = __ww;
        try { if (__wt.Kind != WallKind.Basic)
                  __blk.Add("wall_kind_" + __wt.Kind.ToString()); }
        catch { __blk.Add("wall_kind_unreadable"); }
        try
        {
            var __cs = __wt.GetCompoundStructure();
            if (__cs == null) __blk.Add("compound_structure_absent");
            else
            {
                if (!__cs.IsVerticallyHomogeneous())
                    __blk.Add("vertically_compound");
                if (__cs.GetWallSweepsInfo(WallSweepType.Sweep).Count > 0)
                    __blk.Add("wall_sweeps");
                if (__cs.GetWallSweepsInfo(WallSweepType.Reveal).Count > 0)
                    __blk.Add("wall_reveals");
                if (__cs.VariableLayerIndex >= 0) __blk.Add("variable_layer");
            }
        }
        catch { __blk.Add("compound_structure_unreadable"); }
        // СОСТАВ СЛОЁВ (волна типов, 23.08.2026). ЗАЧЕМ: до неё разбор знал о
        // типе стены ТОЛЬКО общую толщину, и потому тип был невоспроизводим в
        // чужом документе — воспроизводить нечего. Оп, создавший бы тип по
        // одному числу, дал бы верное имя и верный объём при НЕВЕРНОМ пироге,
        // а поймать это нечем: свидетель `create_wall` про тип молчит,
        // `verify.json` слоёв не читает, а оболочка клеша берёт `Width` и
        // оказалась бы ВЕРНОЙ.
        //
        // 🔴 ЧТЕНИЕ СТРОГО ДОБАВОЧНОЕ: НИ ОДНОГО НОВОГО БЛОКЕРА. Блокеры решают
        // `uniform`, а `uniform` решает, строит ли клеш призму. Добавить сюда
        // причину значило бы задним числом сделать не-uniform типы, которые
        // сегодня uniform, — то есть сдвинуть и профиль всего корпуса, и
        // поведение клеша, ради поля, к телу не относящегося. Провал чтения
        // едет СВОИМ полем `layers_unreadable`.
        //
        // `MaterialId == InvalidElementId` — законное состояние слоя, а не
        // сбой: материал просто не назначен. Такой слой едет БЕЗ ключа
        // `material`, и это отличается от «материал есть, имя не прочли».
        try
        {
            var __csL = __wt.GetCompoundStructure();
            if (__csL != null)
            {
                var __lay = new List<object>();
                foreach (var __ly in __csL.GetLayers())
                {
                    var __one = new Dictionary<string, object>();
                    __one["width_mm"] = __MM(__ly.Width);
                    __one["function"] = __ly.Function.ToString();
                    var __mid = __ly.MaterialId;
                    if (__mid != null && __mid != ElementId.InvalidElementId)
                    {
                        var __mat = doc.GetElement(__mid) as Material;
                        if (__mat != null && __mat.Name != null
                            && __mat.Name.Length > 0)
                            __one["material"] = __mat.Name;
                    }
                    __lay.Add(__one);
                }
                if (__lay.Count > 0)
                {
                    __sec["layers"] = __lay.ToArray();
                    __sec["layer_count"] = __lay.Count;
                }
            }
        }
        catch { __sec["layers_unreadable"] = true; }
        if (__blk.Count == 0) __sec["uniform"] = true;
        else { __blk.Sort(); __sec["blockers"] = __blk.ToArray(); }
        return __sec;
    }
    // 2. ПЛИТА (перекрытие / потолок / кровля) — общий предок
    //    `HostObjAttributes`. Стена сюда не доходит: она разобрана выше.
    var __ho = __e as HostObjAttributes;
    if (__ho != null)
    {
        CompoundStructure __cs2 = null;
        try { __cs2 = __ho.GetCompoundStructure(); } catch { }
        if (__cs2 == null) return null;
        double __th = 0.0;
        try { __th = __MM(__cs2.GetWidth()); } catch { }
        if (!(__th > 0.0)) return null;
        __sec["kind"] = "plate";
        __sec["source"] = "HostObjAttributes.GetCompoundStructure().GetWidth";
        __sec["thickness_mm"] = __th;
        try { if (__cs2.VariableLayerIndex >= 0) __blk.Add("variable_layer"); }
        catch { __blk.Add("variable_layer_unreadable"); }
        try { if (__cs2.HasStructuralDeck) __blk.Add("structural_deck"); }
        catch { }
        if (__blk.Count == 0) __sec["uniform"] = true;
        else { __blk.Sort(); __sec["blockers"] = __blk.ToArray(); }
        return __sec;
    }
    // 3. ТРУБА: таблица «номинал -> НАРУЖНЫЙ», напечатанная самим документом.
    //    Ни одного переводного множителя здесь нет и быть не может: у ДУ100
    //    номинал 100, наружный 114.3, и вывести второе из первого нельзя
    //    ничем, кроме сортамента. Когда один номинал приходит от нескольких
    //    сегментов (сталь и медь в одних правилах), берётся БОЛЬШИЙ наружный:
    //    огрубление вверх законно, выбор одного из двух — нет.
    var __pt2 = __e as Autodesk.Revit.DB.Plumbing.PipeType;
    if (__pt2 != null)
    {
        var __nominals = new List<double>();
        var __outers = new Dictionary<double, double>();
        try
        {
            var __rpm = __pt2.RoutingPreferenceManager;
            int __nr = __rpm == null ? 0 : __rpm.GetNumberOfRules(
                RoutingPreferenceRuleGroupType.Segments);
            for (int __i = 0; __i < __nr; __i++)
            {
                var __rule = __rpm.GetRule(
                    RoutingPreferenceRuleGroupType.Segments, __i);
                if (__rule == null) continue;
                var __segEl = doc.GetElement(__rule.MEPPartId)
                    as Autodesk.Revit.DB.Plumbing.PipeSegment;
                if (__segEl == null) continue;
                foreach (MEPSize __z in __segEl.GetSizes())
                {
                    double __nom = __MM(__z.NominalDiameter);
                    double __out = __MM(__z.OuterDiameter);
                    if (!(__nom > 0.0) || !(__out > 0.0)) continue;
                    double __prev;
                    if (!__outers.TryGetValue(__nom, out __prev))
                    { __outers[__nom] = __out; __nominals.Add(__nom); }
                    else if (__prev < __out) __outers[__nom] = __out;
                }
            }
        }
        catch { }
        if (__nominals.Count == 0) return null;
        __nominals.Sort();
        var __pairs = new List<object>();
        bool __trunc = false;
        foreach (double __nom in __nominals)
        {
            if (__pairs.Count >= __SECTION_MAX_SIZES__) { __trunc = true; break; }
            __pairs.Add(new double[] { __nom, __outers[__nom] });
        }
        __sec["kind"] = "nominal_table";
        __sec["source"] =
            "PipeType.RoutingPreferenceManager+PipeSegment.GetSizes";
        __sec["sizes"] = __pairs;
        if (__trunc) __sec["sizes_truncated"] = true;
        return __sec;
    }
    // 4. НЕСУЩИЙ ПРОФИЛЬ у типоразмера семейства. Спрашивается ТОЛЬКО у
    //    несущих категорий: пул `family_symbols` собирается без сужения и
    //    насчитывает тысячи строк, а три чтения на каждую окупаются лишь
    //    там, где ответ бывает.
    if (__cat == "OST_StructuralColumns" || __cat == "OST_Columns"
        || __cat == "OST_StructuralFraming"
        || __cat == "OST_StructuralFoundation")
    {
        var __fsy = __e as FamilySymbol;
        if (__fsy != null)
        {
            double __dia = __ParamMM(
                __fsy, BuiltInParameter.STRUCTURAL_SECTION_COMMON_DIAMETER);
            double __sw = __ParamMM(
                __fsy, BuiltInParameter.STRUCTURAL_SECTION_COMMON_WIDTH);
            double __sh = __ParamMM(
                __fsy, BuiltInParameter.STRUCTURAL_SECTION_COMMON_HEIGHT);
            if (__dia > 0.0)
            {
                __sec["kind"] = "round";
                __sec["source"] = "STRUCTURAL_SECTION_COMMON_DIAMETER";
                __sec["diameter_mm"] = __dia;
                __sec["uniform"] = true;
            }
            else if (__sw > 0.0 && __sh > 0.0)
            {
                __sec["kind"] = "rect";
                __sec["source"] =
                    "STRUCTURAL_SECTION_COMMON_WIDTH+HEIGHT";
                __sec["width_mm"] = __sw;
                __sec["height_mm"] = __sh;
                __sec["uniform"] = true;
            }
            else return null;
            // СОБСТВЕННЫЙ ГАБАРИТ ТИПОРАЗМЕРА ПО Z. Замер 09.08 на Snowdon:
            // 4 колонны из 114 выходили за оболочку ровно на 254.0 мм ВНИЗ, и
            // все четыре — одного типоразмера. База семейства уходит ниже
            // своей отметки, и знать об этом может только сам типоразмер.
            try
            {
                var __bb = __fsy.get_BoundingBox(null);
                if (__bb != null)
                {
                    __sec["local_z_min_mm"] = __MM(__bb.Min.Z);
                    __sec["local_z_max_mm"] = __MM(__bb.Max.Z);
                }
            }
            catch { }
            return __sec;
        }
    }
    return null;
};
var __ParamNames = new string[0];
var __snap = new Dictionary<string, object>();
Action<string, System.Collections.Generic.IEnumerable<Element>, int> __AddPool =
    (string __pool, System.Collections.Generic.IEnumerable<Element> __els, int __limit) =>
{
    var __rows = new List<object>();
    int __total = 0;
    foreach (var __e in __els.OrderBy(__x => __Id(__x)))
    {
        // audit F7: count PAST the cap so a truncated pool is marked, never
        // silently passed off as the whole catalog (ground refuses default/
        // sole-entry on a truncated pool and says so on NOT_FOUND).
        __total++;
        if (__rows.Count >= __limit) continue;
        var __r = new Dictionary<string, object>();
        __r["id"] = __Id(__e);
        try { __r["name"] = __e.Name ?? ""; } catch { __r["name"] = ""; }
        try { __r["unique_id"] = __e.UniqueId ?? ""; } catch { __r["unique_id"] = ""; }
        try { __r["version_guid"] = __e.VersionGuid.ToString("N"); } catch { __r["version_guid"] = ""; }
        try { __r["class_name"] = __e.ToString() ?? ""; } catch { __r["class_name"] = ""; }
        string __catName = "";
        try
        {
            var __category = __e.Category;
            if (__category != null)
            {
                int __categoryId;
                if (Int32.TryParse(__category.Id.ToString(), out __categoryId))
                {
                    __catName = Enum.GetName(
                        typeof(BuiltInCategory), __categoryId)
                        ?? __categoryId.ToString();
                    __r["category"] = __catName;
                }
            }
        }
        catch { }
        // Отметка УРОВНЯ. Без неё программа, объявившая стену на уровне, не
        // имеет ни одной отметки Z, и тела у неё нет по построению — сколько
        // бы толщин ни знал тип. Ключ появляется только у строк пула levels.
        var __lvl = __e as Level;
        if (__lvl != null)
        {
            try { __r["elevation_mm"] = __MM(__lvl.Elevation); } catch { }
        }
        try
        {
            var __secRow = __Section(__e, __catName);
            if (__secRow != null) __r["section"] = __secRow;
        }
        catch { }
        var __fs = __e as FamilySymbol;
        if (__fs != null)
        {
            try { __r["family_name"] = __fs.FamilyName ?? ""; } catch { }
            try { __r["type_name"] = __fs.Name ?? ""; } catch { }
            // 🔴 ТИП РАЗМЕЩЕНИЯ. Он живёт у СЕМЕЙСТВА, а не у типоразмера, и
            // без него пул отдаёт вызывающему кандидатов, которыми тот
            // пользоваться не может ПО ПОСТРОЕНИЮ. Замер живьём 24.08.2026
            // («Проект2», прод-путь revit_ir): create_adaptive_component на
            // {"by":"default"} получил KIR-G102 с 323 кандидатами из
            // family_symbols, и все показанные — импосты витража.
            // Восемь пулов стоят на FamilySymbol, фильтровал ОДИН —
            // beam_types, и фильтровал ВНУТРИ коллектора: признак до питона
            // не доезжал вовсе, поэтому заземлению было нечем отличить
            // годного от негодного, а отказ не мог назвать причину.
            // "unreadable" вместо молчания — намеренно: «не прочитали» и
            // «прочитали, и там вот это» обязаны быть различимы, иначе
            // отсутствие ключа читается как отсутствие свойства.
            try { __r["placement_type"] = __fs.Family.FamilyPlacementType.ToString(); }
            catch { __r["placement_type"] = "unreadable"; }
            // Ноль — ЗНАЧИМОЕ значение, а не отсутствие: правило требует
            // счётчик на КАЖДОЙ строке пула, иначе максимум по неполным
            // данным — утверждение, которого мы доказать не можем, и
            // ground.py осознанно откажется его делать.
            int __used;
            __r["instances"] = __instCount.TryGetValue(__Id(__e), out __used)
                ? __used : 0;
        }
        if (__ParamNames.Length > 0)
        {
            var __params = new Dictionary<string, object>();
            foreach (var __paramName in __ParamNames)
            {
                System.Collections.Generic.IList<Parameter> __matches = null;
                try { __matches = __e.GetParameters(__paramName); } catch { }
                // Duplicate display names are ambiguous too.  Omitting the
                // value makes ground.py refuse; never pick the first.
                if (__matches == null || __matches.Count != 1) continue;
                var __p = __matches[0];
                if (__p == null || !__p.HasValue) continue;
                var __pv = new Dictionary<string, object>();
                __pv["storage_type"] = __p.StorageType.ToString();
                try
                {
                    var __display = __p.AsValueString();
                    if (__display != null) __pv["display"] = __display;
                }
                catch { }
                try
                {
                    if (__p.StorageType == StorageType.String)
                        __pv["value"] = __p.AsString();
                    else if (__p.StorageType == StorageType.Integer)
                        __pv["value"] = __p.AsInteger();
                    else if (__p.StorageType == StorageType.Double)
                        __pv["raw"] = __p.AsDouble();
                    else if (__p.StorageType == StorageType.ElementId)
                        __pv["value"] = __p.AsElementId().ToString();
                }
                catch { continue; }
                __params[__paramName] = __pv;
            }
            __r["params"] = __params;
        }
        __rows.Add(__r);
    }
    __snap[__pool] = __rows;
    __snap[__pool + "__total"] = __total;
    if (__total > __limit) __snap[__pool + "__truncated"] = true;
};
__AddPool("levels", new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Element>(), 1000);
__AddPool("phases", new FilteredElementCollector(doc).OfClass(typeof(Phase)).Cast<Element>(), 1000);
__AddPool("materials", new FilteredElementCollector(doc).OfClass(typeof(Material)).Cast<Element>(), 1000);
__AddPool("wall_types", new FilteredElementCollector(doc).OfClass(typeof(WallType)).Cast<Element>(), 1000);
__AddPool("floor_types", new FilteredElementCollector(doc).OfClass(typeof(FloorType)).Cast<Element>(), 1000);
__AddPool("pipe_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Plumbing.PipeType)).Cast<Element>(), 1000);
__AddPool("piping_system_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Plumbing.PipingSystemType)).Cast<Element>(), 1000);
__AddPool("column_symbols_structural", new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_StructuralColumns).Cast<Element>(), 1000);
__AddPool("column_symbols_architectural", new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_Columns).Cast<Element>(), 1000);
__AddPool("window_symbols", new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_Windows).Cast<Element>(), 1000);
__AddPool("door_symbols", new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_Doors).Cast<Element>(), 1000);
__AddPool("family_symbols", new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).Cast<Element>(), int.MaxValue);
__AddPool("roof_types", new FilteredElementCollector(doc).OfClass(typeof(RoofType)).Cast<Element>(), 1000);
__AddPool("duct_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Mechanical.DuctType)).Cast<Element>(), 1000);
__AddPool("duct_system_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Mechanical.MechanicalSystemType)).Cast<Element>(), 1000);
__AddPool("cable_tray_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Electrical.CableTrayType)).Cast<Element>(), 1000);
// wave/mep-electrical (2026-08-09): пулы короба и двух гибких типов.
// Собираются ПО КЛАССУ, как pipe/duct/cable-tray выше: ConduitType,
// FlexDuctType и FlexPipeType — самостоятельные классы ElementType
// (существование каждого проверено компиляцией на 2021-2026), и фильтр по
// классу возвращает ровно их. Категорийный фильтр здесь был бы хуже:
// OST_Conduit несёт и сами короба, и их типы.
__AddPool("conduit_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Electrical.ConduitType)).Cast<Element>(), 1000);
__AddPool("flex_duct_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Mechanical.FlexDuctType)).Cast<Element>(), 1000);
__AddPool("flex_pipe_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Plumbing.FlexPipeType)).Cast<Element>(), 1000);
// beam_types фильтруется по ТИПУ РАЗМЕЩЕНИЯ, в отличие от остальных пулов
// символов. Замерено 27.07: все 36 семейств каркаса реального здания —
// FamilyPlacementType.OneLevelBased (точечные), а create_beam эмитит
// NewFamilyInstance(Line, …, StructuralType.Beam), который на точечном
// семействе возвращает null. Факт известен здесь, на ground — значит здесь и
// должен приводить к честному KIR-G104 «пусто в модели», а не к рантайм-null
// с сообщением про исчезнувший тип. Для окон/дверей/колонн точечное
// размещение — норма, их пулы не трогаем.
__AddPool("beam_types", new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_StructuralFraming).Cast<FamilySymbol>().Where(__bfs => { try { var __pt = __bfs.Family.FamilyPlacementType; return __pt == FamilyPlacementType.CurveDrivenStructural || __pt == FamilyPlacementType.CurveBased; } catch { return false; } }).Cast<Element>(), 1000);
__AddPool("foundation_symbols", new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_StructuralFoundation).Cast<Element>(), 1000);
// wave/arch (2026-07-29): пулы типов потолка и ограждения. Оба собираются
// ПО КЛАССУ, а не по категории: CeilingType и RailingType — самостоятельные
// классы ElementType (существование обоих проверено компиляцией на 2021-2026),
// и фильтр по классу возвращает ровно их, без примеси системных типов.
// У ограждения это единственный способ вообще узнать список типов:
// ElementTypeGroup.RailingType не существует ни на одной версии (замерено),
// то есть спросить документ «а какой тип по умолчанию» нельзя в принципе.
// wave/wall-foundation (2026-08-09): типы ленточного фундамента. По КЛАССУ,
// как потолок и ограждение: WallFoundationType — самостоятельный класс
// ElementType (компиляция 2021-2026, 6/6), и WallFoundation.Create не примет
// ничего другого. В отличие от ограждения, документный тип по умолчанию у
// него ЕСТЬ: ElementTypeGroup.WallFoundationType компилируется на всех шести.
__AddPool("wall_foundation_types", new FilteredElementCollector(doc).OfClass(typeof(WallFoundationType)).Cast<Element>(), 1000);
// wave/analysis (2026-08-09): случаи загружения и три типа нагрузок.
// ТИПЫ — ПО КЛАССУ, как труба/воздуховод/лоток выше: PointLoadType,
// LineLoadType и AreaLoadType — самостоятельные классы ElementType
// (существование каждого проверено компиляцией на 2021-2026), и фильтр по
// классу возвращает ровно их. Категорийный фильтр здесь был бы хуже:
// OST_PointLoads несёт и сами нагрузки, и их типы.
//
// load_cases — пул ЭКЗЕМПЛЯРОВ (как levels и grids), а не типов: случай
// загружения это элемент проекта, и заземляться по нему обязаны все три
// нагрузки. Природы (LoadNature) здесь НЕТ: их вход — операция создания
// СЛУЧАЯ, которой в этой волне нет, а пул без селектора нарушил бы правило
// «пул существует ради заземления» (см. ops_analysis.py).
__AddPool("load_cases", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Structure.LoadCase)).Cast<Element>(), 1000);
__AddPool("point_load_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Structure.PointLoadType)).Cast<Element>(), 1000);
__AddPool("line_load_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Structure.LineLoadType)).Cast<Element>(), 1000);
__AddPool("area_load_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Structure.AreaLoadType)).Cast<Element>(), 1000);
// wave/framing (2026-08-09): типы ферм. ПО КЛАССУ, как потолок, ограждение и
// ленточный фундамент: TrussType — самостоятельный класс (компиляция 2021-2026,
// 6/6), и Truss.Create принимает ТОЛЬКО его id. Категорийный фильтр был бы
// хуже: OST_Truss держит и сами фермы, и их типы. Отдельного пула балочной
// системе НЕ ЗАВЕДЕНО — её символ балки это обычный beam_types, тот же пул и
// тот же фильтр по типу размещения, что у create_beam.
__AddPool("truss_types", new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_Truss).Cast<Element>(), 1000);
// wave/reinforcement (2026-08-10): три пула армирования по области. ВСЕ ТРИ
// ПО КЛАССУ, как ферма и ленточный фундамент: AreaReinforcementType,
// RebarBarType и RebarHookType — самостоятельные классы ElementType
// (компиляция 2021-2026, 6/6), и AreaReinforcement.Create проверяет КАЖДЫЙ
// аргумент на свой класс отдельно. Категорийный фильтр здесь был бы хуже:
// OST_Rebar держит и стержни, и их типы, а OST_AreaRein — и системы, и типы.
__AddPool("area_reinforcement_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Structure.AreaReinforcementType)).Cast<Element>(), 1000);
__AddPool("rebar_bar_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Structure.RebarBarType)).Cast<Element>(), 1000);
__AddPool("rebar_hook_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Structure.RebarHookType)).Cast<Element>(), 1000);
__AddPool("ceiling_types", new FilteredElementCollector(doc).OfClass(typeof(CeilingType)).Cast<Element>(), 1000);
__AddPool("railing_types", new FilteredElementCollector(doc).OfClass(typeof(Autodesk.Revit.DB.Architecture.RailingType)).Cast<Element>(), 1000);
// wave/site (2026-08-09): типы площадки под здание и толщи рельефа.
//
// ПЛОЩАДКА собирается ПО КЛАССУ, как все остальные: BuildingPadType — тип
// ElementType, существующий на всех шести версиях (замерено компиляцией).
//
// ТОЛЩА — единственный пул этого файла, который НЕ МОЖЕТ назвать свой класс.
// `ToposolidType` появился только в 2024 (на 2021/2022 это CS0246, на 2023 —
// CS0122: тип есть, но internal), а это ТЕЛО ОДНО НА ВСЕ ШЕСТЬ ВЕРСИЙ: оно
// не эмитируется под версию, значит любое упоминание имени не собралось бы
// на половине флота и утащило бы за собой ВЕСЬ снапшот, то есть все
// остальные пулы вместе с ним. Поэтому фильтр идёт по ИМЕНИ ТИПА CLR у
// общего предка HostObjAttributes (BuildingPadType/FloorType/RoofType/
// WallType/CeilingType/ToposolidType — все его наследники; проверено
// присваиванием). На 2021-2023 совпадений нет по построению, и пул честно
// пуст — то есть create_topography(variety=toposolid) там получит KIR-G104
// «пусто в модели», ровно на тех версиях, где эта операция и так отказывает
// по оси версий. Категорией это сделать НЕЛЬЗЯ: BuiltInCategory.OST_Toposolid
// появился в 2023, на ГОД раньше самого класса, то есть имя категории версию
// не различает.
__AddPool("building_pad_types", new FilteredElementCollector(doc).OfClass(typeof(BuildingPadType)).Cast<Element>(), 1000);
// wave/sweep (2026-08-09). ДВА ПУЛА, СОБРАННЫЕ ПО-РАЗНОМУ, И РАЗНИЦА — ЗАМЕР.
// `SlabEdgeType` — настоящий класс ElementType (компиляция 6/6), поэтому пул
// краевых профилей идёт ПО КЛАССУ, как wall_foundation_types.
// А вот класса `WallSweepType`-как-ElementType НЕ СУЩЕСТВУЕТ: `WallSweepType`
// это ПЕРЕЧИСЛЕНИЕ {Sweep, Reveal} (замерено), и тип профиля живёт обычным
// ElementType в OST_Cornices (карнизы) либо OST_Reveals (русты). Поэтому
// единственный возможный сбор — по ДВУМ категориям, одним пулом: разделить их
// на два пула нельзя, потому что `grounded` в реестре статичен, а тип у
// операции один параметр.
__AddPool("wall_sweep_types", new FilteredElementCollector(doc).WherePasses(new ElementMulticategoryFilter(new List<BuiltInCategory> { BuiltInCategory.OST_Cornices, BuiltInCategory.OST_Reveals })).WhereElementIsElementType().Cast<Element>(), 1000);
__AddPool("slab_edge_types", new FilteredElementCollector(doc).OfClass(typeof(SlabEdgeType)).Cast<Element>(), 1000);
// СТРОКОЙ, А НЕ typeof — И ЭТО ЗАПИСЬ О ВЕРСИОННОМ ЗАПРЕТЕ. Не пишите здесь
// typeof(ToposolidType): класса НЕТ в эталонных сборках 2021-2023 (проверено
// по поверхности API всех шести), и снапшот перестанет собираться на трёх
// версиях из шести. Сравнение имени — единственная форма, компилирующаяся
// везде.
//
// СЛЕДСТВИЕ, стоившее живого прогона 13.08.2026: на 2021-2023 этот пул пуст
// ВСЕГДА, в любом документе. Отказ «пусто в модели» там был бы ложью и звал
// бы автора заводить тип, которого на его Ревите не бывает, — поэтому версия
// отвечает РАНЬШЕ заземления (`ops_site.toposolid_version_refusal`, зовётся
// из `compiler` до стадии ground). Знание о запрете жило здесь, в
// исполняемом виде, и не переходило одну границу.
__AddPool("toposolid_types", new FilteredElementCollector(doc).OfClass(typeof(HostObjAttributes)).Cast<Element>().Where(__tse => { try { return __tse.GetType().Name == "ToposolidType"; } catch { return false; } }), 1000);
// wave/detail (2026-08-09): типы заливки. ПО КЛАССУ, как все остальные:
// FilledRegionType — самостоятельный тип ElementType, существующий на всех
// шести версиях (замерено компиляцией). Категорией это делать НЕЛЬЗЯ:
// OST_FilledRegion держит и сами заливки (элементы вида), и их типы, то есть
// категорийный фильтр вернул бы пул, половина которого не является типом и
// отвергается самим `FilledRegion.IsValidFilledRegionTypeId`.
__AddPool("filled_region_types", new FilteredElementCollector(doc).OfClass(typeof(FilledRegionType)).Cast<Element>(), 1000);
// РАБОЧИЕ НАБОРЫ. Кладутся ОТДЕЛЬНО, а не через __AddPool, и это не стиль:
// `Workset` НЕ наследует `Element`, поэтому `Cast<Element>()` к нему неприменим,
// а коллектор у него свой. Замерено по индексу ловушек 13.08.2026 на шести
// версиях; `Parameter.Set(WorksetId)` не существует (CS1503 6/6), набор
// адресуется ЦЕЛЫМ `WorksetId.IntegerValue`.
var __worksets = new List<object>();
// 🔴 ПОЛНОЕ ЧИСЛО БЕРЁТСЯ ДО СРЕЗА, И ВТОРОГО ОБХОДА ДЛЯ ЭТОГО НЕ НУЖНО
// (30.08.2026, находка аудита F-080). `ToWorksets()` отдаёт УЖЕ
// МАТЕРИАЛИЗОВАННЫЙ `IList<Workset>`, поэтому `.Count` стоит O(1) и коллектор
// обходится ровно один раз — как и раньше.
int __worksetsTotal = 0;
try
{
    if (doc.IsWorkshared)
    {
        var __worksetsAll = new FilteredWorksetCollector(doc).ToWorksets();
        __worksetsTotal = __worksetsAll.Count;
        foreach (Workset __w in __worksetsAll.Take(1000))
        {
            var __wr = new Dictionary<string, object>();
            __wr["id"] = __w.Id.IntegerValue;
            try { __wr["name"] = __w.Name ?? ""; } catch { __wr["name"] = ""; }
            try { __wr["kind"] = __w.Kind.ToString(); } catch { __wr["kind"] = ""; }
            __worksets.Add(__wr);
        }
    }
}
catch { }
// НЕ РАЗДЕЛЁННЫЙ ДОКУМЕНТ ДАЁТ ПУСТОЙ ПУЛ, А НЕ ОТСУТСТВУЮЩИЙ КЛЮЧ: пустой
// читается как «наборов нет», отсутствующий — как «мы не спрашивали», и это
// разные утверждения. Различает их `worksets__workshared`.
__snap["worksets"] = __worksets;
__snap["worksets__workshared"] = doc.IsWorkshared;
// 🔴 ПОЛНЫЙ РАЗМЕР — КАК У СОСЕДА. Пул без `__total` вечно неполон: его
// `complete` ложь всегда, и это читалось бы как дефект документа, а не как
// наше умолчание. У `grids` рядом `__total` есть с самого начала; здесь его
// не было, и до 25.08 `worksets` стоял в списке ТРЕБУЕМЫХ (рукописный
// литерал C#), отчего `authoritative` был ложью на любой живой модели.
// 🔴 БЫЛО `__worksets.Count` — ЧИСЛО ЗАХВАЧЕННОГО, ВЫДАННОЕ ЗА ПОЛНОЕ (F-080).
// После `Take(1000)` оно равно 1000 у любого документа, где наборов больше, и
// контракт пула читает это как `total_count == len(entries)`, то есть
// «захвачено ВСЁ»: `complete=true`, `truncated=false`. Документ с 1200
// наборами отчитывался полным ровно на 1000, и признака усечения не было
// вовсе — пул объявлял себя целым, будучи срезанным.
//
// ЗАЗЕМЛЕНИЕ НА КОРПУСЕ, замер 30.08.2026: из 10 разборов, несущих пул
// `worksets`, СЕМЬ стоят ровно на 1000 (`k2v33_join2`, `k3_layers`,
// `mnvnk_k1_layers`, `mnvnk_k3_22aug`, `mnvnk_k3_23aug` и два `mnvnk_atr_pd_b14`).
// Семь разных документов на ОДНОЙ круглой границе — это подпись потолка, а не
// совпадение. Насколько больше их на самом деле, не знает никто: старый код
// этого числа не считал НИКОГДА.
__snap["worksets__total"] = __worksetsTotal;
// Признак усечения — ОТДЕЛЬНОЕ утверждение, а не следствие сравнения на
// стороне читателя: `ModelCatalogPool` требует его явно и отвергает пул, где
// `total_count > len(entries)` без `truncated=true`.
__snap["worksets__truncated"] = __worksetsTotal > __worksets.Count;
var __gridQuery = new FilteredElementCollector(doc).OfClass(typeof(Grid))
    .Cast<Grid>().OrderBy(__x => __Id(__x)).ToList();
var __grids = new List<object>();
foreach (Grid __g in __gridQuery.Take(1000))
{
    var __r = new Dictionary<string, object>();
    __r["id"] = __Id(__g);
    try { __r["name"] = __g.Name ?? ""; } catch { __r["name"] = ""; }
    try { __r["unique_id"] = __g.UniqueId ?? ""; } catch { __r["unique_id"] = ""; }
    try { __r["version_guid"] = __g.VersionGuid.ToString("N"); } catch { __r["version_guid"] = ""; }
    try { __r["class_name"] = __g.ToString() ?? ""; } catch { __r["class_name"] = ""; }
    try
    {
        var __line = __g.Curve as Line;
        if (__line != null)
        {
            var __p0 = __line.GetEndPoint(0); var __p1 = __line.GetEndPoint(1);
            __r["p0_mm"] = new double[] { __MM(__p0.X), __MM(__p0.Y) };
            __r["p1_mm"] = new double[] { __MM(__p1.X), __MM(__p1.Y) };
        }
    }
    catch { }
    __grids.Add(__r);
}
__snap["grids"] = __grids;
__snap["grids__total"] = __gridQuery.Count;
if (__gridQuery.Count > 1000) __snap["grids__truncated"] = true;
var __documentFingerprint = new Dictionary<string, object>();
try { __documentFingerprint["title"] = doc.Title ?? ""; } catch { __documentFingerprint["title"] = ""; }
try { __documentFingerprint["path_name"] = doc.PathName ?? ""; } catch { __documentFingerprint["path_name"] = ""; }
try
{
    __documentFingerprint["project_uid"] = doc.ProjectInformation == null
        ? "" : (doc.ProjectInformation.UniqueId ?? "");
}
catch { __documentFingerprint["project_uid"] = ""; }
__snap["__document_fingerprint"] = __documentFingerprint;
__snap["__profile_schema_version"] = "open-model-profile/1";
__snap["__profile_required_pools"] = new string[] {
__REQUIRED_POOLS__
};
try { __snap["__revit_version"] = doc.Application.VersionNumber ?? ""; }
catch { __snap["__revit_version"] = ""; }
try { __snap["__revit_build"] = doc.Application.VersionBuild ?? ""; }
catch { __snap["__revit_build"] = null; }
return __snap;
"""

#: 🔴 THE LIST OF REQUIRED POOLS IS GENERATED, NOT HAND-WRITTEN.
#: Before 08-25, a hand-written C# literal of 39 names stood here against the
#: 36 that `required_grounding_pools()` DERIVES from the live registry. The
#: extra ones were `materials`, `phases`, `worksets` — pools that no op grounds against.
#:
#: This was not harmless: the list arrives IN THE SNAPSHOT
#: (`__profile_required_pools`), and `from_ground_snapshot` takes IT, not the
#: registry — meaning that on a LIVE model, the C# version was the truth.
#: `worksets`, moreover, has neither a `__total` nor row identity, so the
#: pool is forever incomplete, `authoritative` is forever false, and
#: `a5_contract` refused reassembly into the same document on EVERY live model.
#:
#: In this tree, EVERY hand-written list drifted apart and NOT ONE generated
#: one did — measured 08-15. Here the list became generated.
def _required_pools_cs() -> str:
    return ",\n".join(f'    "{name}"' for name in required_grounding_pools())


def _ground_snapshot_cs() -> str:
    """The snapshot text with Python's values SUBSTITUTED IN.

    🔴 THE SECOND VALUE THAT NEVER MADE IT TO C#, MEASURED 2026-08-25.
    `SECTION_MAX_SIZES = 64` is declared, exported in `__all__` — and read by
    NO ONE: a full grep gave two lines, the declaration and the export. The
    real ceiling stood as a bare `>= 64` literal in the emitted C#. Whoever
    raised the constant would have gotten exactly nothing, and a program with
    a 65th nominal would get "nominal not found" instead of "data truncated."

    The first such value in this same file was the list of required pools
    (Python derived 36 from the registry, C# carried a hand-written 39). One
    pattern, and it is a named one: the value is declared in Python and
    REPEATED as a literal in C#.

    Rendering is factored into a function not for elegance: without it there
    is nothing to check the LINK with — a test for the equality of two
    numbers is green by coincidence as long as there are two of them.
    """
    return (_GROUND_SNAPSHOT_CS_TEMPLATE
            .replace("__REQUIRED_POOLS__", _required_pools_cs())
            .replace("__SECTION_MAX_SIZES__", str(SECTION_MAX_SIZES))
            .strip("\n"))


GROUND_SNAPSHOT_CS = _ground_snapshot_cs()


__all__ = [
    "GROUND_SNAPSHOT_CS",
    "ModelBinding",
    "ModelCatalogEntry",
    "ModelCatalogPool",
    "ModelPreflightIssue",
    "OPEN_MODEL_PREFLIGHT_SCHEMA_VERSION",
    "OPEN_MODEL_PROFILE_SCHEMA_VERSION",
    "OpenModelPreflight",
    "OpenModelProfile",
    "OpenModelProfileError",
    "PreflightIssueCode",
    "SECTION_KINDS",
    "SECTION_MAX_SIZES",
    "TypeSection",
    "capture_open_model_profile",
    "preflight_programs",
    "prune_ground_snapshot",
    "required_grounding_pools",
]
