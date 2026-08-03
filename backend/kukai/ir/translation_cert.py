"""Translation-validation certificate for the KIR authoring emitter (wave 2).

The emitter (`authoring.py`) already carries, per op, BOTH halves of a
refinement witness — they were just never collected into a checkable
certificate:

1. a **materializing Revit API call** in the ``create`` block
   (``Wall.Create``, ``Pipe.Create``, ``NewFamilyInstance``, ...) guarded by a
   typed ``__Refuse`` on a null / failed return (materialize-or-refuse; no
   silent wrong result), and
2. a **runtime postcondition witness** in the ``post`` block: one
   ``__post.Add("<oid>: ...")`` per invariant the op's ``OpSpec.post`` promises
   (endpoint geometry, level/host topology, parameter values, flip states,
   MEPSystem membership, ...), which ``emit_program`` gates with
   ``if (__post.Count > 0) { RollBack | report }``.

This module turns "a runtime witness exists" into a **statically checkable,
pre-Revit guarantee** that, for every promised postcondition, the witness was
actually emitted (not forgotten), and that the materializer is the specific
API that implements the op (not a stub).  It is the two-part structure of a
refinement proof: **safety** (right API or typed refusal) + **coverage
liveness** (every promised observable is checked).

The check is STATIC — no Revit, no compile — parsing the very
``(decl, create, post, readback)`` tuple the emitter returns, with the same
string/comment-stripping tokenizer the emitter scope contract already uses
(`test_emitter_scope_contract`).  Witnesses are matched by STRUCTURAL C#
markers (``.Location as LocationCurve``, ``WALL_BASE_CONSTRAINT``,
``.Mirrored != ``, ``RBS_PIPE_DIAMETER_PARAM``), never by the Russian message
text (which the tokenizer strips) — so renaming a message cannot fool the
certificate, while deleting the check itself breaks it.

Design, forks and rationale: ``TRANSLATION_VALIDATION_SPEC.md`` at the worktree
root.  Headlines:

* We prove refinement of the op's POSTCONDITIONS (its only observable
  contract, since the semantics live in Revit), not SMT-equivalence of the
  C# AST.
* ``REFINEMENT`` is the machine form of the prose ``OpSpec.post``;
  ``audit_registry_coverage`` enforces a biection so the table cannot silently
  drift from the registry (a new promised clause with no obligation is a hard
  fail).
* Pure OBSERVATION (Р-3): ``authoring.py`` is untouched; nothing imports this
  in a hot path; ``certificate_enabled()`` is default OFF.

Fail-closed: an unproven refinement or a registry/table mismatch raises a typed
:class:`CertificateError` — never a silent "proven".
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable

from kukai.ir import spec
from kukai.ir.authoring import _EMITTERS, emit_stairs_program
from kukai.ir.emit_model import BarePost, post_to_string


# ---------------------------------------------------------------------------
# Typed failures (fail-closed)
# ---------------------------------------------------------------------------


class CertificateError(ValueError):
    """Base for every typed translation-certificate failure."""


class UnprovenRefinementError(CertificateError):
    """An emitted op does not discharge every required refinement obligation."""


class CertificateSchemaError(CertificateError):
    """The registry promises a postcondition the obligation table cannot prove,
    or the table references a clause the registry never promises."""


# ---------------------------------------------------------------------------
# Flag (inertness contract)
# ---------------------------------------------------------------------------


def certificate_enabled() -> bool:
    """Opt-in gate for future compiler/serving wiring; default OFF."""

    return os.getenv("KUKAI_IR_TRANSLATION_CERT", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


# ---------------------------------------------------------------------------
# C# tokenizer
# ---------------------------------------------------------------------------

def _code(text: str) -> str:
    """Strip C# strings, chars, and both comment forms; leave only code.

    A witness marker is searched in this stripped code, never inside a message
    string, so a renamed message can never fabricate (or hide) a proof.

    This must be a state machine, not two regex substitutions: C# has block
    comments, verbatim strings, escaped quotes, and comment-looking text inside
    literals.  In particular ``/* Wall.Create */`` used to satisfy the
    materializer proof even though it compiles to no call at all (F30).
    """

    out: list[str] = []
    i = 0
    size = len(text)
    line_ends = "\r\n\x85\u2028\u2029"
    while i < size:
        # Line comment (including every C# newline character).
        if text.startswith("//", i):
            i += 2
            while i < size and text[i] not in line_ends:
                i += 1
            out.append(" ")
            continue

        # Block comments are not nestable in C#.  Unterminated means the rest
        # is comment; dropping it is the certificate's fail-closed choice.
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = size if end < 0 else end + 2
            out.append(" ")
            continue

        # Verbatim string prefixes: @"...", $@"...", @$"...".  Generated
        # KIR does not rely on interpolation code for proof markers, so the
        # entire literal is deliberately non-code for certification.
        prefix_len = 0
        if text.startswith('$@"', i) or text.startswith('@$"', i):
            prefix_len = 3
        elif text.startswith('@"', i):
            prefix_len = 2
        if prefix_len:
            i += prefix_len
            while i < size:
                if text[i] == '"':
                    if i + 1 < size and text[i + 1] == '"':
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append('""')
            continue

        # Ordinary/interpolated strings.  Backslash escapes keep the next
        # character inside the literal.  This is sufficient for the C# 7.3
        # dialect emitted here; proof-bearing code is never inside a string.
        quote_len = 0
        if text.startswith('$"', i):
            quote_len = 2
        elif text[i] == '"':
            quote_len = 1
        if quote_len:
            i += quote_len
            while i < size:
                if text[i] == "\\" and i + 1 < size:
                    i += 2
                    continue
                char = text[i]
                i += 1
                if char == '"':
                    break
            out.append('""')
            continue

        # Character literals may contain escaped quote/comment characters.
        if text[i] == "'":
            i += 1
            while i < size:
                if text[i] == "\\" and i + 1 < size:
                    i += 2
                    continue
                char = text[i]
                i += 1
                if char == "'":
                    break
            out.append("''")
            continue

        out.append(text[i])
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Certificate data model
# ---------------------------------------------------------------------------

# Obligation kinds — the observable classes an op postcondition can promise.
KIND_MATERIALIZE = "materialize"
KIND_GEOMETRY = "geometry"
KIND_TOPOLOGY = "topology"
KIND_PARAMETER = "parameter"
KIND_SEMANTIC = "semantic"
KIND_IDENTITY = "identity"
_KINDS = frozenset({
    KIND_MATERIALIZE, KIND_GEOMETRY, KIND_TOPOLOGY, KIND_PARAMETER,
    KIND_SEMANTIC, KIND_IDENTITY,
})

# Which emitted block an obligation's witness must live in.
BLOCK_CREATE = "create"
BLOCK_POST = "post"


@dataclass(frozen=True, slots=True)
class Obligation:
    """One proof obligation: a clause and the C# markers that discharge it."""

    clause: str                          # human-readable, aligned to OpSpec.post
    kind: str
    witness_markers: tuple[str, ...]     # ANY present in ``block`` discharges it
    block: str = BLOCK_POST
    param: str | None = None             # gating param for a conditional clause
    conditional: bool = False            # witness required ONLY when param present
    # height mismatch fix (30.07.2026): the mirror image of `conditional` —
    # witness required ONLY when `unless_param` is ABSENT.  create_wall's
    # height witness needs exactly this: WALL_USER_HEIGHT_PARAM stops being
    # authoritative (and the emitter stops witnessing it) the moment
    # top_level IS given, the opposite shape from every existing conditional
    # obligation (which all gate on their OWN param's presence).  Mutually
    # exclusive with `conditional`/`param` — one obligation gates one way.
    unless_param: str | None = None
    # Wave A2: for ops migrated to the witness model the obligation matches a
    # WitnessCheck.obligation_key — a machine KEY, never a C# substring.  When
    # ``key`` is set the markers become optional (unused on the model path);
    # string-path ops keep requiring markers.
    key: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise CertificateSchemaError(f"unknown obligation kind {self.kind!r}")
        if self.block not in (BLOCK_CREATE, BLOCK_POST):
            raise CertificateSchemaError(f"unknown block {self.block!r}")
        if self.conditional and self.param is None:
            raise CertificateSchemaError(
                f"conditional obligation {self.clause!r} needs a gating param")
        if self.unless_param is not None and (self.conditional or self.param is not None):
            raise CertificateSchemaError(
                f"obligation {self.clause!r}: unless_param is mutually "
                "exclusive with conditional/param — an obligation gates one "
                "way")
        if not self.witness_markers and self.key is None:
            raise CertificateSchemaError(
                f"obligation {self.clause!r} has neither witness markers nor "
                "a model key")


@dataclass(frozen=True, slots=True)
class OpRefinementSpec:
    """The full refinement contract for one op, parallel to ``spec.OPS``."""

    op: str
    materializer: tuple[str, ...]        # ANY marker proves the create call
    obligations: tuple[Obligation, ...]
    refuse_on_null: bool = True
    # Wave A2: "model" = the emitter returns list[WitnessCheck]; obligations
    # discharge by obligation KEY (correctness by construction — a check
    # cannot exist without its __post.Add verdict).  "string" = legacy post
    # string: marker matching + the verdict-span rule.
    witness_source: str = "string"


@dataclass(frozen=True, slots=True)
class ClauseVerdict:
    clause: str
    kind: str
    required: bool
    discharged: bool
    matched_marker: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class OpCertificate:
    op: str
    version: str
    materialized: bool
    refusal_guarded: bool
    clauses: tuple[ClauseVerdict, ...]

    @property
    def proven(self) -> bool:
        return (
            self.materialized
            and self.refusal_guarded
            and all(v.discharged for v in self.clauses if v.required)
        )

    @property
    def gaps(self) -> tuple[str, ...]:
        holes: list[str] = []
        if not self.materialized:
            holes.append(f"{self.op}: no materializing API call emitted")
        if not self.refusal_guarded:
            holes.append(f"{self.op}: materialization not guarded by __Refuse")
        for verdict in self.clauses:
            if verdict.required and not verdict.discharged:
                holes.append(
                    f"{self.op}: unproven [{verdict.kind}] {verdict.clause} "
                    f"({verdict.reason})")
        return tuple(holes)


@dataclass(frozen=True, slots=True)
class ProgramCertificate:
    version: str
    ops: tuple[OpCertificate, ...]

    @property
    def proven(self) -> bool:
        return all(cert.proven for cert in self.ops)

    @property
    def gaps(self) -> tuple[str, ...]:
        return tuple(gap for cert in self.ops for gap in cert.gaps)


# ---------------------------------------------------------------------------
# The obligation table — machine form of every write op's OpSpec.post
# ---------------------------------------------------------------------------

# Shared witness marker groups (structural C#, NOT message text).
_ENDPOINTS = (".Location as LocationCurve",)           # _endpoint_check
_LEVEL_BIP = (
    "WALL_BASE_CONSTRAINT", "RBS_START_LEVEL_PARAM", "ROOF_BASE_LEVEL_PARAM",
    "FAMILY_BASE_LEVEL_PARAM", "FAMILY_LEVEL_PARAM", "SCHEDULE_LEVEL_PARAM",
    "LEVEL_PARAM", ".LevelId",                          # _level_check_expr / chain / room
)
_LOCATION_POINT = (".Location as LocationPoint",)
_BBOX = ("get_BoundingBox",)
_REFUSE = ("__Refuse",)


def _refinement_specs() -> dict[str, OpRefinementSpec]:
    ob = Obligation
    specs = [
        OpRefinementSpec(
            op="create_wall",
            materializer=("Wall.Create",),
            witness_source="model",
            obligations=(
                ob("wall exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("base constraint == resolved level (topology)",
                   KIND_TOPOLOGY, ("WALL_BASE_CONSTRAINT",),
                   key="base_constraint"),
                # Замер 29.07.2026 (два фасадных прогона: 4 стены + 5 полов,
                # затем 16 стен — «height mismatch» на КАЖДОЙ). height_mm
                # несёт registry-default (3000мм), и validate() подставляет
                # его в norm ДО эмиттера для ЛЮБОЙ опущенной стены — отличить
                # «явно попросили 3000» от «промолчали, потому что решает
                # top_level» эмиттер больше не может. WALL_USER_HEIGHT_PARAM
                # к тому же перестаёт быть источником истины, как только
                # верх стены привязан к уровню (Revit сам выводит высоту из
                # пары уровней). Обязательство required ТОЛЬКО когда
                # top_level ОТСУТСТВУЕТ — обратное направление обычного
                # conditional (см. Obligation.unless_param).
                ob("height param == height_mm when top_level is not given "
                   "(parameter)",
                   KIND_PARAMETER, ("WALL_USER_HEIGHT_PARAM",),
                   unless_param="top_level", key="height"),
                ob("arc curve == arc dict when supplied (geometry)",
                   KIND_GEOMETRY, (".Curve is Arc", "__arc"),
                   param="arc", conditional=True, key="arc"),
                ob("base offset param == base_offset_mm when given (geometry)",
                   KIND_GEOMETRY, ("WALL_BASE_OFFSET",),
                   param="base_offset_mm", conditional=True, key="base_offset"),
                # Замер 28.07 (docs/2026-07-28-location-line-measurement.md):
                # правило привязки НЕ двигает ни ось, ни тело — ни при
                # создании, ни потом; оно решает, какая плоскость переживёт
                # смену толщины. Значит ось у него семантическая, и читается
                # оно тем единственным, что у него есть, — ординалом
                # параметра. Геометрию стены закрывает свидетель концов.
                ob("location line rule == location_line when given (semantic)",
                   KIND_SEMANTIC, ("WALL_KEY_REF_PARAM",),
                   param="location_line", conditional=True,
                   key="location_line"),
                ob("top constraint == resolved top_level when given (topology)",
                   KIND_TOPOLOGY, ("WALL_HEIGHT_TYPE",),
                   param="top_level", conditional=True, key="top_constraint"),
                # Wall-fidelity (live A5 evidence 2026-07-21): explicit top
                # offset is a DEFINING DOF of the attach and must be witnessed.
                ob("top offset param == top_offset_mm when given (geometry)",
                   KIND_GEOMETRY, ("WALL_TOP_OFFSET",),
                   param="top_offset_mm", conditional=True, key="top_offset"),
            ),
        ),
        OpRefinementSpec(
            op="create_pipe",
            materializer=("Plumbing.Pipe.Create",),
            witness_source="model",
            obligations=(
                ob("pipe exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 3D (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
                ob("diameter param == diameter_mm when given (parameter)",
                   KIND_PARAMETER, ("RBS_PIPE_DIAMETER_PARAM",),
                   param="diameter_mm", conditional=True, key="diameter"),
            ),
        ),
        OpRefinementSpec(
            op="create_grid",
            materializer=("Grid.Create",),
            witness_source="model",
            obligations=(
                ob("grid exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("curve endpoints == p0/p1 (geometry)",
                   KIND_GEOMETRY, (".Curve",), key="endpoints"),
                ob("Name == name when given (identity)",
                   KIND_IDENTITY, (".Name != ",),
                   param="name", conditional=True, key="name"),
            ),
        ),
        OpRefinementSpec(
            op="create_level",
            materializer=("Level.Create",),
            witness_source="model",
            obligations=(
                ob("level exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("Elevation == elev_mm (geometry)",
                   KIND_GEOMETRY, (".Elevation",), key="elevation"),
                ob("Name == name when given (identity)",
                   KIND_IDENTITY, (".Name != ",),
                   param="name", conditional=True, key="name"),
            ),
        ),
        OpRefinementSpec(
            op="set_param",
            materializer=(".Set(",),
            witness_source="model",
            obligations=(
                ob("param resolved+writable or typed refusal (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("parameter holds requested value post-commit (parameter)",
                   KIND_PARAMETER, (".AsString(", ".AsDouble(", ".AsInteger("), key="value_held"),
            ),
        ),
        OpRefinementSpec(
            op="delete",
            materializer=("doc.Delete",),
            witness_source="model",
            obligations=(
                ob("target resolved or typed refusal (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("element no longer resolvable post-commit (semantic)",
                   KIND_SEMANTIC, ("doc.GetElement",), key="gone"),
            ),
        ),
        # CLASH-починка (28.07): move_elements / change_type.
        OpRefinementSpec(
            op="move_elements",
            materializer=("ElementTransformUtils.MoveElements",),
            witness_source="model",
            obligations=(
                ob("targets resolved, none pinned/stale, or typed refusal "
                   "(materialize)", KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("every target's Location shifted by delta_mm exactly "
                   "(geometry)", KIND_GEOMETRY,
                   _LOCATION_POINT + _ENDPOINTS, key="location"),
                ob("total CONNECTED connector count over targets unchanged "
                   "(topology)", KIND_TOPOLOGY, (".ConnectorManager",),
                   key="connectors"),
                ob("LocationCurve target slope (end1.Z-end0.Z) unchanged "
                   "(semantic)", KIND_SEMANTIC, (".GetEndPoint(",),
                   key="slope"),
            ),
        ),
        OpRefinementSpec(
            op="change_type",
            materializer=(".ChangeTypeId(",),
            witness_source="model",
            obligations=(
                ob("target/type resolved or typed refusal (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("GetTypeId() == requested type after Regenerate "
                   "(semantic)", KIND_SEMANTIC, (".GetTypeId()",),
                   key="type_held"),
            ),
        ),
        OpRefinementSpec(
            op="create_floor",
            materializer=("Floor.Create", "NewFloor"),
            witness_source="model",
            obligations=(
                ob("floor exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("level binding == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP, key="level_binding"),
                ob("bbox XY extents == outline extents (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
                ob("structural flag == requested (semantic)",
                   KIND_SEMANTIC, ("FLOOR_PARAM_IS_STRUCTURAL",),
                   key="structural"),
                # P1 DOF-completeness: смещение пола от уровня.
                ob("height offset param == height_offset_mm when given "
                   "(geometry)",
                   KIND_GEOMETRY, ("FLOOR_HEIGHTABOVELEVEL_PARAM",),
                   param="height_offset_mm", conditional=True,
                   key="height_offset"),
            ),
        ),
        # wave/arch (2026-07-29).
        OpRefinementSpec(
            op="create_ceiling",
            # Один-единственный материализатор: Ceiling.Create. У перекрытия
            # их два (Floor.Create / NewFloor — развилка версий), у потолка
            # второго не существует, и это ЗАМЕР, а не упрощение таблицы:
            # doc.Create.NewCeiling не компилируется ни на одной из шести
            # версий. Поэтому же сертификат потолка снимается только с 2022+
            # (__min_ver__ у arch_ceiling): на 2021 эмиссии нет вовсе — там
            # типизированный отказ KIR-E003, а не другая эмиссия.
            materializer=("Ceiling.Create",),
            witness_source="model",
            obligations=(
                ob("ceiling exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("level binding == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP, key="level_binding"),
                ob("bbox XY extents == outline extents (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
                ob("height offset param == height_offset_mm when given "
                   "(geometry)",
                   KIND_GEOMETRY, ("CEILING_HEIGHTABOVELEVEL_PARAM",),
                   param="height_offset_mm", conditional=True,
                   key="height_offset"),
            ),
        ),
        OpRefinementSpec(
            op="create_railing",
            # Обе перегрузки называются Railing.Create — одного маркера
            # хватает на обе ветви.
            materializer=("Railing.Create",),
            witness_source="model",
            obligations=(
                ob("railing exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # ОДНО обязательство на две ветви, как "footprint" у
                # create_foundation: у свободного ограждения якорь — уровень,
                # у лестничного — хозяин. Любой из двух маркеров доказывает
                # ту привязку, которая на этой ветви вообще существует.
                ob("path variety: base level == resolved level OR hosted "
                   "variety: railing belongs to the requested host "
                   "(topology)",
                   KIND_TOPOLOGY,
                   ("STAIRS_RAILING_BASE_LEVEL_PARAM", "HasHost"),
                   key="anchor"),
                # Габарит проверяем только там, где мы САМИ задали геометрию.
                # У лестничного ограждения путь выбирает Revit по маршу, и
                # требовать от него наш bbox значило бы проверять выдуманное.
                ob("path variety: bbox XY extents == path extents (geometry)",
                   KIND_GEOMETRY, _BBOX, param="path", conditional=True,
                   key="bbox"),
            ),
        ),
        OpRefinementSpec(
            op="create_directshape",
            materializer=("DirectShape.CreateElement",),
            witness_source="model",
            obligations=(
                ob("direct shape exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # Габарит ПО ТРЁМ ОСЯМ: у меша Z — такая же координата входа,
                # как X и Y, поэтому общий XY-свидетель перекрытий здесь не
                # годится (свидетель обязан подписывать ту ось, которую
                # действительно читал).
                ob("bbox extents == mesh vertex extents in XYZ (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
                # Число граней вычитывается С ПОСТРОЕННОГО элемента через
                # Mesh.NumTriangles, а не пересчитывается из нашего же входа —
                # иначе обязательство подтверждало бы вызов, а не результат.
                ob("built mesh triangle count == triangles count (geometry)",
                   KIND_GEOMETRY, ("NumTriangles",), key="triangles"),
            ),
        ),
        OpRefinementSpec(
            op="create_roof",
            materializer=("NewFootPrintRoof",),
            witness_source="model",
            obligations=(
                ob("roof exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("base level == resolved level (topology)",
                   KIND_TOPOLOGY, ("ROOF_BASE_LEVEL_PARAM",), key="base_level"),
                ob("bbox XY extents == outline extents (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
            ),
        ),
        OpRefinementSpec(
            op="create_column",
            materializer=("NewFamilyInstance",),
            witness_source="model",
            obligations=(
                ob("column exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationPoint == xy (geometry)",
                   KIND_GEOMETRY, _LOCATION_POINT, key="location"),
                ob("level binding == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP, key="level_binding"),
                ob("StructuralType == requested (semantic)",
                   KIND_SEMANTIC, (".StructuralType",), key="structural_type"),
                ob("rotation == rotation_deg when given (geometry)",
                   KIND_GEOMETRY, (".Rotation",),
                   param="rotation_deg", conditional=True, key="rotation"),
                # P1 DOF-completeness (fidelity audit 2026-07-21): столбовая
                # вертикаль — определяющие DOF attach'а колонны.
                ob("base offset param == base_offset_mm when given (geometry)",
                   KIND_GEOMETRY, ("FAMILY_BASE_LEVEL_OFFSET_PARAM",),
                   param="base_offset_mm", conditional=True, key="base_offset"),
                ob("top constraint == resolved top_level when given (topology)",
                   KIND_TOPOLOGY, ("FAMILY_TOP_LEVEL_PARAM",),
                   param="top_level", conditional=True, key="top_constraint"),
                ob("top offset param == top_offset_mm when given (geometry)",
                   KIND_GEOMETRY, ("FAMILY_TOP_LEVEL_OFFSET_PARAM",),
                   param="top_offset_mm", conditional=True, key="top_offset"),
            ),
        ),
        OpRefinementSpec(
            op="create_window",
            materializer=("NewFamilyInstance",),
            witness_source="model",
            obligations=_hosted_obligations("window"),
        ),
        OpRefinementSpec(
            op="create_door",
            materializer=("NewFamilyInstance",),
            witness_source="model",
            obligations=_hosted_obligations("door"),
        ),
        OpRefinementSpec(
            op="create_room",
            materializer=("NewRoom",),
            witness_source="model",
            obligations=(
                ob("room exists and nonzero area (materialize / semantic)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LevelId == resolved level (topology)",
                   KIND_TOPOLOGY, (".LevelId",), key="level_binding"),
                ob("LocationPoint == xy (geometry)",
                   KIND_GEOMETRY, _LOCATION_POINT, key="location"),
                ob("nonzero enclosed area (semantic)",
                   KIND_SEMANTIC, (".Area",), key="area"),
                ob("Name == name when given (identity)",
                   KIND_IDENTITY, (".Name != ",),
                   param="name", conditional=True, key="name"),
            ),
        ),
        OpRefinementSpec(
            op="place_family",
            materializer=("NewFamilyInstance",),
            witness_source="model",
            obligations=(
                ob("instance exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # У опа два варианта размещения, и сертификат обязан
                # называть ТОТ, который доказан. Пока обязательство было
                # одно, кривой вариант разряжал его по ключу `location` — и
                # сертификат писал «LocationPoint == xyz» про экземпляр, у
                # которого LocationPoint не существует. Доказанное неверное
                # утверждение хуже недоказанного: оно выглядит проверкой.
                ob("LocationPoint == xyz (geometry)",
                   KIND_GEOMETRY, _LOCATION_POINT,
                   param="xyz", conditional=True, key="location"),
                ob("LocationCurve endpoints == p0_mm/p1_mm (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS,
                   param="p0_mm", conditional=True, key="location"),
                # Уровень — принадлежность ТОЧЕЧНОГО варианта. У размещения по
                # кривой на хосте уровня нет вовсе: Revit берёт его у хоста, и
                # безусловное обязательство здесь неразрядимо в принципе —
                # сертификат объявлял бы недоказуемым то, чего в опе нет.
                # Ровно та же поправка, что уже сделана выше для `location`.
                ob("level binding == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP,
                   param="level", conditional=True, key="level_binding"),
                # Хост эмиттер читает обратно (`__el_.Host`), а сертификат про
                # эту проверку не знал: свидетель без обязательства — это
                # проверка, которую можно молча удалить, не уронив ни один
                # сертификат. Та же дыра, что закрыли по диаметру 27.07.
                ob("host == resolved host (topology)",
                   KIND_TOPOLOGY, (".Host",),
                   param="host", conditional=True, key="host"),
                ob("rotation == rotation_deg when given (geometry)",
                   KIND_GEOMETRY, (".Rotation",),
                   param="rotation_deg", conditional=True, key="rotation"),
                ob("mirrored state == requested when given (semantic)",
                   KIND_SEMANTIC, (".Mirrored != ",),
                   param="mirrored", conditional=True, key="mirrored"),
                ob("hand flip state == requested when given (semantic)",
                   KIND_SEMANTIC, (".HandFlipped != ",),
                   param="hand_flipped", conditional=True, key="hand_flipped"),
                ob("facing flip state == requested when given (semantic)",
                   KIND_SEMANTIC, (".FacingFlipped != ",),
                   param="facing_flipped", conditional=True, key="facing_flipped"),
            ),
        ),
        OpRefinementSpec(
            op="create_pipe_system",
            materializer=("Plumbing.Pipe.Create",),
            witness_source="model",
            obligations=_network_obligations("RBS_PIPE_DIAMETER_PARAM"),
        ),
        OpRefinementSpec(
            op="route_pipe_system",
            materializer=("Plumbing.Pipe.Create",),
            witness_source="model",
            obligations=_network_obligations("RBS_PIPE_DIAMETER_PARAM"),
        ),
        OpRefinementSpec(
            op="route_duct_system",
            materializer=("Mechanical.Duct.Create",),
            witness_source="model",
            obligations=_network_obligations("RBS_CURVE_DIAMETER_PARAM"),
        ),
        OpRefinementSpec(
            op="create_floor_by_contour",
            materializer=("Floor.Create", "NewFloor"),
            witness_source="model",
            obligations=(
                ob("floor exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("level binding == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP, key="level_binding"),
                ob("bbox == lowered-edges extents (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
                ob("height offset param == height_offset_mm when given "
                   "(geometry)",
                   KIND_GEOMETRY, ("FLOOR_HEIGHTABOVELEVEL_PARAM",),
                   param="height_offset_mm", conditional=True,
                   key="height_offset"),
            ),
        ),
        OpRefinementSpec(
            op="create_duct",
            materializer=("Mechanical.Duct.Create",),
            witness_source="model",
            obligations=(
                ob("duct exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 3D (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
                ob("diameter param == diameter_mm when given (parameter)",
                   KIND_PARAMETER, ("RBS_CURVE_DIAMETER_PARAM",),
                   param="diameter_mm", conditional=True, key="diameter"),
            ),
        ),
        OpRefinementSpec(
            op="create_cable_tray",
            materializer=("Electrical.CableTray.Create",),
            witness_source="model",
            obligations=(
                ob("cable tray exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 3D (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
            ),
        ),
        OpRefinementSpec(
            op="create_type",
            materializer=(".Duplicate(",),
            witness_source="model",
            obligations=(
                ob("new FamilySymbol exists (materialize or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("width param holds width_mm post-commit (parameter)",
                   KIND_PARAMETER, ("__pw_",), key="width"),
                ob("depth param holds depth_mm when given (parameter)",
                   KIND_PARAMETER, ("__pd_",),
                   param="depth_mm", conditional=True, key="depth"),
                ob("material holds when given (parameter)",
                   KIND_PARAMETER, ("STRUCTURAL_MATERIAL_PARAM",),
                   param="material", conditional=True, key="material"),
            ),
        ),
        OpRefinementSpec(
            op="load_family",
            materializer=("LoadFamily", "LoadFamilySymbol"),
            witness_source="model",
            obligations=(
                ob("File.Exists checked / typed refusal (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("symbol active post-load (semantic)",
                   KIND_SEMANTIC, (".IsActive",), key="active"),
            ),
        ),
        OpRefinementSpec(
            op="create_dimension",
            materializer=("NewDimension",),
            witness_source="model",
            # 28.07 (live E5 measurement, FAS_R23 Revit 2023 — see wave
            # report): no gated GEOMETRY obligation for this op — the
            # measured VALUE depends on which faces resolve (Exterior/
            # Interior, emitter docstring) and Dimension.Curve is
            # documented ALWAYS UNBOUND (Revit API Developer Guide,
            # "Dimensions and Constraints"), so the compiler has no
            # independent "expected" geometry to compare against for an
            # arbitrary live model. Honest obligations: existence +
            # References topology + view binding; the numeric value still
            # reaches the caller un-gated (readback ``value_mm``). The
            # retired "line_at reproduced (geometry)" obligation asserted
            # Dimension.Origin's offset along a FIXED View.UpDirection,
            # which stopped being meaningful once the dimension line's own
            # direction became face-normal-derived (not always
            # UpDirection-perpendicular) — see _emit_dimension docstring.
            obligations=(
                ob("dimension exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("belongs to in_view (topology)",
                   KIND_TOPOLOGY, (".OwnerViewId", ".View"), key="in_view"),
                ob("References match requested refs (topology)",
                   KIND_TOPOLOGY, (".References",), key="references"),
            ),
        ),
        OpRefinementSpec(
            op="create_tag",
            materializer=("IndependentTag.Create",),
            witness_source="model",
            obligations=(
                ob("tag exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("belongs to in_view (topology)",
                   KIND_TOPOLOGY, (".OwnerViewId", ".View"), key="in_view"),
                ob("TaggedLocalElementId == target (semantic)",
                   KIND_SEMANTIC,
                   ("TaggedLocalElementId", "GetTaggedLocalElementIds"),
                   key="target_bound"),
                ob("tag head at `at` reproduced in view-space (geometry)",
                   KIND_GEOMETRY, ("TagHeadPosition",), key="head_at"),
            ),
        ),
        OpRefinementSpec(
            op="create_text",
            materializer=("TextNote.Create",),
            witness_source="model",
            obligations=(
                ob("text note exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("belongs to in_view (topology)",
                   KIND_TOPOLOGY, (".OwnerViewId", ".View"), key="in_view"),
                ob("content matches (semantic)",
                   KIND_SEMANTIC, (".Text",), key="content"),
                ob("at reproduced in view-space (geometry)",
                   KIND_GEOMETRY, (".Coord",), key="at"),
                ob("width_mm honored when given (geometry)",
                   KIND_GEOMETRY, (".Width",),
                   param="width_mm", conditional=True, key="width"),
                ob("leader target visible when given (semantic)",
                   KIND_SEMANTIC, ("__leaderTargetVisible", "__leaderOk"),
                   param="leader_to", conditional=True, key="leader"),
            ),
        ),
        OpRefinementSpec(
            op="create_beam",
            materializer=("NewFamilyInstance",),
            witness_source="model",
            obligations=(
                ob("beam exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 3D (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                # Было «reference level == resolved level». Замерено 27.07:
                # Revit ВЫВОДИТ опорный уровень балки из отметки кривой
                # (передан L_01 @ 0, кривая на Z=3000 -> привязка к
                # L_01ДОО1_+2.500). Обязательство требовало того, чего API не
                # обещает, и откатывало правильную балку. Инвариант, который
                # действительно есть: опорный уровень существует; какой именно
                # — читается в свидетель.
                ob("опорный уровень существует; какой — читается в свидетель (topology)",
                   KIND_TOPOLOGY, ("INSTANCE_REFERENCE_LEVEL_PARAM",),
                   key="reference_level"),
                ob("StructuralType == Beam (semantic)",
                   KIND_SEMANTIC, ("StructuralType.Beam",), key="structural_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_foundation",
            # variety=isolated -> NewFamilyInstance; variety=slab -> Floor.Create
            # / NewFloor.  ANY of the three proves the op materialized on its
            # branch (only one path is emitted per op instance).
            materializer=("NewFamilyInstance", "Floor.Create", "NewFloor"),
            witness_source="model",
            obligations=(
                ob("footing/slab exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # isolated -> LocationPoint==xy; slab -> bbox extents.  ANY of
                # the two proves the geometry clause on the emitted branch.
                ob("isolated LocationPoint == xy OR slab bbox extents "
                   "== outline extents (geometry)",
                   KIND_GEOMETRY, _LOCATION_POINT + _BBOX, key="footprint"),
                ob("base level == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP + _BBOX, key="level_binding"),
                ob("StructuralType==Footing (isolated) OR structural "
                   "flag forced (slab) (semantic)",
                   KIND_SEMANTIC,
                   ("StructuralType.Footing", "FLOOR_PARAM_IS_STRUCTURAL",
                    "get_BoundingBox"), key="structural_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_stairs",
            materializer=("CreateStraightRun",),
            obligations=(
                ob("stairs exist (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("base/top level == resolved levels (topology)",
                   KIND_TOPOLOGY,
                   ("STAIRS_BASE_LEVEL_PARAM", "STAIRS_TOP_LEVEL_PARAM")),
                ob(">=1 run materialized (semantic)",
                   KIND_SEMANTIC, ("GetStairsRuns",)),
                ob("width_mm held when supplied (geometry)",
                   KIND_GEOMETRY, ("ActualRunWidth",),
                   param="width_mm", conditional=True),
            ),
        ),
        OpRefinementSpec(
            # feat/native-groups: NewGroup builds the definition (guarded by
            # __Refuse on null); .Groups witnesses the placed instance count;
            # .Name witnesses the requested GroupType name.  Witnesses are
            # structural C# (NewGroup / .Groups / .Name), never message text.
            op="create_group",
            materializer=("NewGroup",),
            witness_source="model",
            obligations=(
                ob("group definition materialized (GroupType) or typed refusal",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("one placed group instance per placement offset "
                   "(PlaceGroup) (semantic)",
                   KIND_SEMANTIC, (".Groups",), key="instances"),
                ob("GroupType Name matches name when given (semantic)",
                   KIND_SEMANTIC, (".Name",),
                   param="name", conditional=True, key="name"),
            ),
        ),
        OpRefinementSpec(
            # Витражная ячейка. Материализатор — ЕДИНСТВЕННЫЙ вызов, которым
            # Revit меняет тип ячейки; «панель создана» здесь не бывает:
            # панель существует ровно потому, что существует ячейка.
            #
            # Свидетель типа читает ячейку ЗАНОВО ПО АДРЕСУ после
            # Regenerate: ChangePanelType возвращает элемент, и сверка с ним
            # доказывала бы лишь то, что вызов состоялся, — ровно тот класс
            # «свидетеля вызова», который этот реестр запрещает.
            # Линия разрезки — ЕДИНСТВЕННЫЙ конструктор: AddGridLine.
            # Свидетель читает СОЗДАННУЮ линию заново по её id после
            # Regenerate: членство в списке линий этой сетки (topology),
            # IsUGridLine (semantic) и расстояние от запрошенной точки до
            # FullCurve (geometry). Возврат вызова свидетельством не
            # считается — он доказывает лишь то, что вызов состоялся.
            op="create_curtain_grid_line",
            materializer=("AddGridLine",),
            witness_source="model",
            obligations=(
                ob("grid line created or typed refusal (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("created line is a member of the host grid's U/V line "
                   "ids (topology)",
                   KIND_TOPOLOGY, ("__gMem",), key="grid_membership"),
                ob("IsUGridLine == requested direction (semantic)",
                   KIND_SEMANTIC, (".IsUGridLine",), key="direction"),
                ob("requested position lies on FullCurve within tolerance "
                   "(geometry)",
                   KIND_GEOMETRY, ("__gDist",), key="position_mm"),
            ),
        ),
        OpRefinementSpec(
            op="set_curtain_panel",
            materializer=("ChangePanelType",),
            witness_source="model",
            obligations=(
                ob("cell (u,v) resolved or typed refusal (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("effective panel type in cell (u,v) == panel_type, "
                   "re-read by address (semantic)",
                   KIND_SEMANTIC, ("__ccEffType",), key="panel_type"),
                ob("cell host == host (topology)",
                   KIND_TOPOLOGY, (".Host",), key="cell_host"),
            ),
        ),
    ]
    return {spec_.op: spec_ for spec_ in specs}


def _hosted_obligations(noun: str) -> tuple[Obligation, ...]:
    ob = Obligation
    return (
        ob(f"{noun} exists (materialized or typed refusal)",
           KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
        ob("Host.Id == host wall id (topology)",
           KIND_TOPOLOGY, (".Host",), key="host"),
        ob("LocationPoint == offset placement at level+sill (geometry)",
           KIND_GEOMETRY, _LOCATION_POINT, key="location"),
        # audit F5: swing/mirror state — same conditional markers as
        # place_family; every emitted check carries its own __post.Add in the
        # marker span (verdict-span rule).
        ob("mirrored state == requested when given (semantic)",
           KIND_SEMANTIC, (".Mirrored != ",),
           param="mirrored", conditional=True, key="mirrored"),
        ob("hand flip state == requested when given (semantic)",
           KIND_SEMANTIC, (".HandFlipped != ",),
           param="hand_flipped", conditional=True, key="hand_flipped"),
        ob("facing flip state == requested when given (semantic)",
           KIND_SEMANTIC, (".FacingFlipped != ",),
           param="facing_flipped", conditional=True, key="facing_flipped"),
    )


def _network_obligations(diameter_bip: str) -> tuple[Obligation, ...]:
    ob = Obligation
    return (
        ob("segments materialized or typed refusal (materialize)",
           KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
        ob("each segment LocationCurve == node coords (geometry)",
           KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
        # Was "all segments in one MEPSystem (semantic)" until 2026-07-27.
        # Revit DERIVES system membership from the connector graph at commit
        # (measured — connect.py §A), so no in-transaction check can discharge
        # it; the emitter used to force membership with NewPipingSystem and
        # that call is what made the four graph ops unbuildable. The clause
        # the emitter really can prove before commit is connectivity — the
        # CONNECT signal the spec itself names — and it is proven by a BFS
        # over the live connector graph (`Connector.AllRefs`). System identity
        # is now READ BACK after commit and reported, never asserted here.
        ob("connector-graph BFS reaches every segment (topology)",
           KIND_TOPOLOGY, (".AllRefs",), key="connectivity"),
        # Диаметр сегмента: эмиттер эту проверку СТАВИТ
        # (`_network_geometry_post`: «segment N diameter (semantic)»), а
        # сертификат о ней не знал — аргумент `diameter_bip` принимался и
        # не использовался ни разу. Значит удаление проверки из эмиттера
        # оставляло сертификат «доказанным»: ровно та дыра, ради закрытия
        # которой сертификат и заведён.
        #
        # Маркером служит сам BuiltInParameter — он же и различает домены
        # (у трубы RBS_PIPE_DIAMETER_PARAM, у воздуховода
        # RBS_CURVE_DIAMETER_PARAM), поэтому подмена одного другим тоже
        # перестаёт быть незаметной.
        ob("each declared segment diameter is read back (semantic)",
           KIND_SEMANTIC, (f"BuiltInParameter.{diameter_bip}",),
           key="diameter"),
    )


# Some obligation constructors are referenced before their def at class-body
# eval time; Python resolves them at call time, so define the table lazily.
REFINEMENT: dict[str, OpRefinementSpec] = {}


def _ensure_table() -> dict[str, OpRefinementSpec]:
    global REFINEMENT
    if not REFINEMENT:
        REFINEMENT = _refinement_specs()
    return REFINEMENT


# ---------------------------------------------------------------------------
# Certification
# ---------------------------------------------------------------------------


def _op_present(op: dict, param: str) -> bool:
    """Whether a gating param is genuinely present on this op instance.

    Presence is by key AND (for booleans) any value: place_family always
    carries mirrored/hand/facing keys only when the IR set them, and the
    emitter keys its witness on ``has_<flag> = "<flag>" in op`` — so key
    presence is the correct, emitter-aligned test.
    """

    return param in op and op[param] is not None


def _not_required_because(obligation: Obligation) -> str:
    """Human-readable reason a NOT-required obligation's gate resolved that
    way — either the ordinary ``conditional``/``param`` shape (required only
    when ``param`` IS present) or the inverse ``unless_param`` shape
    (required only when ``unless_param`` is ABSENT)."""

    if obligation.unless_param is not None:
        return f"for present param {obligation.unless_param!r}"
    return f"for absent param {obligation.param!r}"


def certify_op(
    op: dict, version: str, *, stamp: str = "kir:cert",
) -> OpCertificate:
    """Statically certify one grounded op's emission refines its OpSpec.post."""

    table = _ensure_table()
    op_name = op["op"]
    if op_name not in table:
        raise CertificateSchemaError(
            f"{op_name}: no OpRefinementSpec (registry op not certifiable)")
    ref = table[op_name]

    model_checks: "list | None" = None
    if op_name == "create_stairs":
        # Sole-op program with its own template (not in _EMITTERS).  Parse the
        # whole emitted program as one blob for materializer + post witnesses;
        # its postconditions are the same __post.Add pattern.
        program = emit_stairs_program(op, version)
        create_code = post_code = _code(program)
    else:
        decl, create, post, _readback = _EMITTERS[op_name](op, version, stamp)
        create_code = _code(create)
        if isinstance(post, BarePost):
            post = list(post.checks)
        if isinstance(post, (list, tuple)):
            # Wave A2 model post: the emitter handed over WitnessCheck objects.
            if ref.witness_source != "model":
                raise CertificateSchemaError(
                    f"{op_name}: emitter returns a model post but the "
                    "refinement spec still declares witness_source='string' "
                    "— update REFINEMENT in the same migration step")
            model_checks = list(post)
            post_code = _code(post_to_string(op["id"], post))
        else:
            if ref.witness_source == "model":
                raise CertificateSchemaError(
                    f"{op_name}: refinement spec declares witness_source="
                    "'model' but the emitter returned a string post")
            post_code = _code(post)

    materialized = any(m in create_code for m in ref.materializer)
    refusal_guarded = (
        not ref.refuse_on_null
        or any(m in create_code for m in _REFUSE)
    )

    model_keys = (
        {check.obligation_key for check in model_checks}
        if model_checks is not None else None)

    verdicts: list[ClauseVerdict] = []
    for obligation in ref.obligations:
        if obligation.kind == KIND_MATERIALIZE:
            # Materialize obligations are proven by the create-side refuse
            # guard; recorded as a clause so the ledger is complete.
            verdicts.append(ClauseVerdict(
                clause=obligation.clause,
                kind=obligation.kind,
                required=True,
                discharged=refusal_guarded and materialized,
                matched_marker=(ref.materializer[0] if materialized else None),
                reason=("materializer + __Refuse present"
                        if (materialized and refusal_guarded)
                        else "missing materializer or __Refuse"),
            ))
            continue

        required = True
        if obligation.conditional:
            required = _op_present(op, obligation.param)
        elif obligation.unless_param is not None:
            required = not _op_present(op, obligation.unless_param)

        if model_keys is not None and obligation.block == BLOCK_POST:
            # Model path (A2): discharge by KEY.  A WitnessCheck cannot exist
            # without its __post.Add (unconstructible), so key-presence IS
            # verdict-presence — no span heuristics.
            if obligation.key is None:
                raise CertificateSchemaError(
                    f"{op_name}: obligation {obligation.clause!r} has no "
                    "model key but the op is model-certified")
            present = obligation.key in model_keys
            if required:
                verdicts.append(ClauseVerdict(
                    clause=obligation.clause, kind=obligation.kind,
                    required=True, discharged=present,
                    matched_marker=obligation.key if present else None,
                    reason=(f"witness check {obligation.key!r} present"
                            if present else
                            f"no witness check with key {obligation.key!r}")))
            else:
                verdicts.append(ClauseVerdict(
                    clause=obligation.clause, kind=obligation.kind,
                    required=False, discharged=not present,
                    matched_marker=obligation.key if present else None,
                    reason=("absent param -> witness correctly absent"
                            if not present else
                            f"spurious witness {obligation.key!r} "
                            f"{_not_required_because(obligation)}")))
            continue

        block_code = create_code if obligation.block == BLOCK_CREATE else post_code
        matched = next(
            (m for m in obligation.witness_markers if m in block_code), None)
        if not required:
            # Conditional clause whose param is absent: the witness must ALSO
            # be absent (no spurious check for a param that was not requested).
            discharged = matched is None
            reason = ("absent param -> witness correctly absent"
                      if discharged
                      else f"spurious witness {matched!r} "
                           f"{_not_required_because(obligation)}")
            verdicts.append(ClauseVerdict(
                clause=obligation.clause, kind=obligation.kind,
                required=False, discharged=discharged,
                matched_marker=matched, reason=reason))
            continue
        verdicts.append(ClauseVerdict(
            clause=obligation.clause,
            kind=obligation.kind,
            required=True,
            discharged=matched is not None,
            matched_marker=matched,
            reason=(f"witness {matched!r} present" if matched
                    else f"no witness among {obligation.witness_markers}"),
        ))

    # Wave A2: the verdict-span rule is GONE.  Every _EMITTERS op is
    # model-certified (a WitnessCheck cannot exist without its __post.Add —
    # the F3 class is unconstructible), and create_stairs, the sole string
    # blob, was always span-exempt.  Obligations discharge by KEY.

    return OpCertificate(
        op=op_name,
        version=version,
        materialized=materialized,
        refusal_guarded=refusal_guarded,
        clauses=tuple(verdicts),
    )


def certify_program(
    grounded_ops: list[dict], version: str, *, intent: str = "",
) -> ProgramCertificate:
    """Certify every op of a grounded program (per-op; the program wrapper is
    constant, so the certificate composes from per-op certificates)."""

    return ProgramCertificate(
        version=version,
        ops=tuple(certify_op(op, version) for op in grounded_ops),
    )


def assert_refined(certificate: OpCertificate | ProgramCertificate) -> None:
    """Fail-closed: raise with every gap unless the certificate is proven."""

    if certificate.proven:
        return
    raise UnprovenRefinementError(
        "translation certificate not proven:\n  "
        + "\n  ".join(certificate.gaps))


# ---------------------------------------------------------------------------
# Registry-coverage audit (table <-> spec.OPS biection)
# ---------------------------------------------------------------------------

# Ops handled outside the _EMITTERS table but still certifiable.
_EXTRA_CERTIFIABLE = frozenset({"create_stairs"})

# Some OpSpec.post clauses describe PLAN-stage / policy / emit-ordering /
# resolution behavior, NOT a post-commit runtime witness — so they cannot (and
# must not) be forced to map onto a __post.Add obligation.  Exemptions are
# EXPLICIT and carry a rationale: a clause is skipped by audit_registry_coverage
# only if it contains its op's exemption marker.  This keeps the biection honest
# (a genuinely-witnessable clause with no obligation still hard-fails) while not
# fabricating a fake witness for a non-runtime promise.  Format: op -> tuple of
# (distinguishing-substring, why-not-a-runtime-postcondition).
_NON_WITNESSABLE_CLAUSES: dict[str, tuple[tuple[str, str], ...]] = {
    "delete": (
        ("allow_destructive",
         "plan/envelope policy gate (SPEC 12.2), enforced before emission"),
    ),
    "create_room": (
        ("placed after",
         "emitter EMIT-ORDER rule (doc.Regenerate before rooms), not a "
         "post-commit witness"),
    ),
    "create_stairs": (
        ("sole op",
         "PLAN constraint (KIR-L002); emit_program raises before emission"),
    ),
    "load_family": (
        ("already loaded",
         "idempotent-resolution semantics proven by the create-side collector "
         "search, not a post-commit witness"),
        ("another family",
         "resolution correctness (family+type match) enforced in the create "
         "block's collector filter, not a post-commit witness"),
    ),
    "create_dimension": (
        ("receipt-only",
         "the measured value depends on which geometric reference resolves "
         "per element (Exterior/Interior face choice) — no independent "
         "expected distance exists to gate on for an arbitrary live model; "
         "reported via readback value_mm only, never asserted (28.07, live "
         "E5 measurement, FAS_R23 Revit 2023)"),
    ),
}


def _clause_tokens(text: str) -> frozenset[str]:
    """Normalize a prose postcondition into comparable lowercase word tokens."""

    return frozenset(re.findall(r"[a-zа-я_]+", text.lower()))


def audit_registry_coverage() -> tuple[str, ...]:
    """Return every table<->registry mismatch (empty tuple == fully covered).

    Three fail-closed invariants:
      1. Every write op (family in WRITE_FAMILIES) has an OpRefinementSpec.
      2. Every REFINEMENT op is a real registry op (no dangling entry).
      3. Every ';'-separated clause of each op's OpSpec.post is witnessed by at
         least one obligation whose clause shares a distinguishing token —
         so a newly promised clause with no obligation is a hard mismatch.
    """

    table = _ensure_table()
    problems: list[str] = []

    write_ops = {
        name for name, op_spec in spec.OPS.items()
        if op_spec.family in spec.WRITE_FAMILIES
    }
    covered = set(table)

    for name in sorted(write_ops - covered):
        problems.append(f"{name}: write op has no OpRefinementSpec")
    for name in sorted(covered - write_ops - _EXTRA_CERTIFIABLE):
        problems.append(
            f"{name}: OpRefinementSpec references a non-write / unknown op")

    # Clause-level biection: each prose clause must map to an obligation.
    # Distinguishing tokens: content words minus ubiquitous filler.
    filler = _clause_tokens(
        "exists when given the a is at in of and or == !=  mm tol day "
        "post commit re read semantic geometry topology witness parameter "
        "chain bip resolved requested value type flag")
    for name, ref in sorted(table.items()):
        if name not in spec.OPS:
            continue
        op_spec = spec.OPS[name]
        obligation_tokens = frozenset().union(
            *(_clause_tokens(o.clause) for o in ref.obligations))
        exemptions = _NON_WITNESSABLE_CLAUSES.get(name, ())
        for raw_clause in op_spec.post.split(";"):
            clause = raw_clause.strip()
            if not clause:
                continue
            low = clause.lower()
            if any(marker in low for marker, _why in exemptions):
                continue
            key_tokens = _clause_tokens(clause) - filler
            if not key_tokens:
                continue
            if not (key_tokens & obligation_tokens):
                problems.append(
                    f"{name}: promised clause not witnessed by any "
                    f"obligation: {clause!r}")

    return tuple(problems)


__all__ = [
    "BLOCK_CREATE",
    "BLOCK_POST",
    "CertificateError",
    "CertificateSchemaError",
    "ClauseVerdict",
    "KIND_GEOMETRY",
    "KIND_IDENTITY",
    "KIND_MATERIALIZE",
    "KIND_PARAMETER",
    "KIND_SEMANTIC",
    "KIND_TOPOLOGY",
    "Obligation",
    "OpCertificate",
    "OpRefinementSpec",
    "ProgramCertificate",
    "REFINEMENT",
    "UnprovenRefinementError",
    "assert_refined",
    "audit_registry_coverage",
    "certificate_enabled",
    "certify_op",
    "certify_program",
]
