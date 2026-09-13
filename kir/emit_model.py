"""Witness-object model for emitter post blocks (wave A2, Emission IR light).

Post blocks stop being hand-concatenated strings and become lists of
:class:`WitnessCheck` objects rendered in ONE place (:func:`render_post`).
What this buys, per the master design (Part 3, A2):

* **Correctness by construction** — a ``WitnessCheck`` REFUSES to exist
  without a ``__post.Add`` verdict in its ``verdict_cs``; the audit-F3 class
  ("the verdict line was deleted but the reader marker survived, cert still
  said proven") becomes UNCONSTRUCTIBLE, so the translation certificate can
  consume obligation KEYS instead of substring markers and the verdict-span
  crutch dies.
* **Central tolerances** — the mm/deg numbers move from emitter literals to
  ``OpSpec.tolerances`` (registry_base); a check carries the registry-minted
  :class:`Tolerance` (03.08: the key is NO LONGER A STRING — see the
  TOLERANCE PROVENANCE LAW below, the "reference into the void" defect
  became unconstructible).
  Values are the EXACT current numbers (byte-parity; no "improvements").
* **Group member-POSTs** — `_emit_group` can now include member checks with
  namespaced keys (the conditional-absent/substring conflict that deferred
  them disappears with keys).

Deliberately NOT a C# AST (80/20, pinned by design): ``decl``/``create``/
``readback`` stay strings; a check's ``reader_cs``/``verdict_cs`` are string
fragments too.  The model's job is STRUCTURE (keys, verdict presence, one
render path), not syntax.

BYTE-GUARANTEE: :func:`render_post` must reproduce the pre-refactor bytes for
every migrated emitter — enforced by ``test_emit_model_byte_parity`` over the
frozen 607-emission corpus.  A check's fragments therefore carry their own
newlines/indentation exactly as the old f-strings did, and ``render_post``
only concatenates: ``"// post <oid>\n{\n"`` + fragments + ``"}"``.

~~Transitional adapter (D4): an emitter returns post as ``str | list[WitnessCheck]``;
``emit_program`` renders both; the cert consumes the model where present
(``witness_source="model"``) and keeps the span rule for strings until the
migration completes.~~

🔴 **THE MOVE IS COMPLETE, THE ADAPTER WAS RETIRED ON 27.08.2026.** The line
above is left struck through, not erased: it was true for its period and
explains why the tree has blocks that get assembled into a variable and ship
into ``verdict_cs`` (this is NOT "handwritten", it is the same object path).
Today ``post_to_string`` accepts only ``list[WitnessCheck]`` and ``BarePost``,
and a string is a loud :class:`EmitModelError`.

WHAT IS MEASURED, NOT ASSUMED (27.08.2026, python3.12, tree `/opt/kir`):

* asked of the PRODUCER, not of the text: ``_EMITTERS`` and
  ``_SOLO_PROGRAMS`` were wrapped, the corpus was run — **73 of 77 writing
  ops are grounded, and not one returned a string** (65 lists, 3
  ``BarePost``, the rest accounted for separately);
* a probe on ``post_to_string`` itself over 931 tests: **9452 lists + 164
  BarePost, ZERO STRINGS**;
* ~38 handwritten ``__post.Add`` calls in the tree belong to FIVE SOLO OPS
  (``create_stairs``, ``…_landing``, ``…_run``, ``author_family``,
  ``transfer_family``), which bypass ``_EMITTERS`` altogether and build the
  WHOLE program with their own ``__post`` frame. The object model does not
  apply to them BY CONTRACT, not by an unfinished job;
* the solo class is closed by a DIFFERENT mechanism, and this is verified by
  a run: ``translation_cert.certify_op`` has an explicit ``_SOLO_PROGRAMS``
  branch; on a grounded staircase — 6 clauses, all ``discharged``,
  ``vacuous 0``. A guard over the whole corpus exists too and walks the
  solos: ``test_witness_vacuity.TheWholeCorpusIsClean``.

🔴 THE COUNT OF "HANDWRITTEN" BY TEXT POSITION IS FALSE, AND THIS IS OUR NAMED
FORM. Counting ``__post.Add`` outside ``WitnessCheck(...)`` parentheses gives
90 and measures THE WRONG THING: ``boolean_emit`` assembles the verdict into
a ``body`` variable and hands it into ``verdict_cs`` — six "outside" cases
under a fully completed move. Position in the text is not a measure of the
model's completeness; the producer must be asked by running it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from kir.emit_utils import cs_line_comment_fragment

_VERDICT_TOKEN = "__post.Add"


class EmitModelError(ValueError):
    """A malformed witness check (fail-closed at construction time)."""


def _verdict_code(text: str) -> str:
    """``_VERDICT_TOKEN``, if it is present in the verdict AS CODE; otherwise an
    empty string.

    🔴 WHY, BY MEASUREMENT (04.09.2026). The constructor searched for
    ``__post.Add`` as a SUBSTRING across the whole text, and so THIS used to
    get built:

        WitnessCheck(..., verdict_cs='    // __post.Add("no verdict");')

    The witness "existed", the obligation key was present, and
    ``translation_cert.certify_op`` discharged the clause BY KEY, relying
    verbatim on "A WitnessCheck cannot exist without its ``__post.Add``
    (unconstructible), so key-presence IS verdict-presence." That claim was
    FALSE, and it was also the sole ground on which the certificate had given
    up parsing the text.

    VACUITY ANALYSIS DID NOT CLOSE THIS HOLE, AND THAT IS MEASURED, NOT
    DERIVED: ``witness_vacuity`` over such a witness returns ``()`` findings,
    because ``analyze_witness_cs`` answers the question "can I PROVE that
    THIS ``__post.Add`` is dead," and the stripped code contains NOT A SINGLE
    site: ``witness_site_census`` = (0, 0). The instrument was correct — about
    a different subject: it guards the verdict against impossible tampering,
    not against the verdict's absence.

    🔴 THERE IS ONE CARRIER OF THE LAW, AND IT IS NOT THIS FUNCTION. There is
    exactly one stripper in the tree — ``translation_cert._code`` (a state
    machine: both kinds of comments, verbatim strings, escaped quotes; its
    docstring names the same defect class — ``/* Wall.Create */`` once
    satisfied the materializer's proof). Setting up a second one here would
    mean repeating this house's own named defect, so the import is local
    (exactly as in :func:`tolerance`: the registry does not know about
    emission, and emission does not know about the certificate at module
    level).

    A FAILED IMPORT DOES NOT SOFTEN THE LAW. If the certificate is
    unavailable at that moment (a partially initialized module during
    import), the check does NOT fall back to the old "substring across the
    whole text" — it refuses loudly: a silent relaxation here would be
    exactly that same hole.

    🔴 A PREFIX IS ASKED FOR, NOT THE WHOLE TEXT, AND THIS IS NOT ECONOMY FOR
    ECONOMY'S SAKE. Only what stands BEFORE the token can hide it: an open
    comment or an open literal. So "is this occurrence code" is decided by
    the prefix up to and including the token itself, and the tail (for a real
    verdict this is the long message to the reader) need not be parsed. A
    comment or literal cut off at the prefix is read by `_code` to the end as
    unclosed, meaning the truncation can only err TOWARD refusal —
    fail-closed, like the whole law.

    THE MEASUREMENT THAT BOUGHT THIS (04.09.2026). The parse itself: 150 real
    verdicts of the corpus, 20 runs — full parse 0.613 s against 0.168 s with
    the prefix (**27%**). Full emission, 200 walls, best of five: the tree
    BEFORE the law 0.184 s, with the full parse 0.313 s (**+70%**), with the
    prefix 0.219 s (**+19%**). The law is NOT weakened by this: the decisions
    agree occurrence for occurrence — 11,850 corpus verdicts (758 distinct),
    14 adversarial forms (an unclosed block comment, an unclosed literal, a
    verbatim string with `""`, a comment BEFORE the real verdict), and 2,400
    random mutations of real verdicts: 0 discrepancies.

    THERE CAN BE SEVERAL OCCURRENCES, AND THE FIRST CAN BE FALSE: `// there
    used to be a __post.Add under the old name` on the line above the real
    verdict is lawful code, and the loop is obligated to reach the second
    one. This is held by
    `test_a_comment_NEXT_TO_a_real_verdict_does_not_refuse`.
    """

    from kir.translation_cert import _code  # local: see the docstring

    end = len(_VERDICT_TOKEN)
    found = text.find(_VERDICT_TOKEN)
    while found >= 0:
        if _VERDICT_TOKEN in _code(text[:found + end]):
            return _VERDICT_TOKEN
        found = text.find(_VERDICT_TOKEN, found + 1)
    return ""


# ---------------------------------------------------------------------------
# TOLERANCE PROVENANCE LAW (03.08.2026)
# ---------------------------------------------------------------------------
# This house's precedent: `WitnessCheck` CANNOT be built without a
# `__post.Add` in the verdict, and a whole defect class (F3 — "the reader
# marker survived, the verdict was deleted, the certificate lies") died BY
# CONSTRUCTION. Here the same technique is applied to the tolerance number.
#
# The sample defect (`create_type`, found 27.07): the check declared
# `tol_key="param_mm"`, while the C# compared against a HARDCODED `0.5`. A
# reference into the void that no test saw: `tol_key` was just a string, and
# nobody ever asked whether it resolved to anything. Editing the tolerance in
# the registry changed nothing, and an audit of "where tolerances live" got
# the wrong answer.
#
# Three laws, each machine-enforced:
#
#   LAW 1 (MINTING). A tolerance enters emission ONLY as a :class:`Tolerance`
#   object, minted by :func:`tolerance` from
#   ``spec.OPS[op].tolerances[key]``. A key that nobody in the registry
#   answers for does not exist: minting refuses on the spot. A bare string
#   `tol_key="…"` can no longer be passed — the witness has no field by that
#   name.
#
#   LAW 2 (READ, NOT DECLARED). A witness that declares a tolerance is
#   obligated to contain, in its own C#, exactly the string that this object
#   ITSELF rendered. A number typed nearby by hand, which the object did not
#   produce, does not satisfy this ⇒ the check does not build. The decorative
#   `tol_key` (the create_type defect) becomes unconstructible.
#
#   LAW 3 (PROMISE ↔ REGISTRY ↔ EMISSION). Every `±<number>` in
#   ``OpSpec.post`` is obligated to be a value in ``OpSpec.tolerances``, and
#   every registry entry is obligated to reach the emitted C# (a mutation
#   oracle: touch the number — the bytes are obligated to move). This is a
#   property of the WHOLE table, so it lives not in the constructor but in
#   ``tests/test_tolerance_provenance.py``.
#
# THE REMAINDER, NAMED HONESTLY: law 2 is a necessary condition, not a
# sufficient one. The rendered string is searched for as a substring, and
# "5.0" could coincide with a coordinate in the same fragment. The mutation
# oracle of law 3 provides the sufficient check; together they close the
# class.


def _compact_cs_number(value: float) -> str:
    """The shortest C# literal for a number: ``1e-06`` -> ``1e-6``,
    ``5.0`` -> ``5.0``.

    Needed for exactly one reason: so that substitution from the registry
    does NOT SHIFT BYTES where the source has historically been typed
    compactly (``> 1e-6`` in set_param).
    """

    return re.sub(r"e([+-])0+(\d)", r"e\1\2", repr(float(value)))


@dataclass(frozen=True, slots=True)
class Tolerance:
    """The tolerance number, MINTED by the registry (law 1).

    Carries its own provenance (``op``/``key``) and remembers EVERY string it
    has rendered itself as — law 2 stands on this memory.

    Renders (all get recorded):
      * ``f"{tol}"``            -> ``5.0``     (the usual form)
      * ``f"{tol:g}"``          -> ``5``       (where the source is typed as
                                                 an integer)
      * ``tol.cs``              -> ``1e-6``    (compact exponent form)
      * ``tol.deg_rad_divisor`` -> ``1800.0``  (for ``Math.PI / 1800.0``)

    ``tol.value`` — the RAW number for DERIVED calculations (the floor of a
    segment's trim is computed from the endpoint tolerance), and it does NOT
    COUNT as a render: if a witness comparison is typed via ``.value``, law 2
    will not build such a check. This is deliberate: a derived number is not
    the same thing as the comparison itself.
    """

    op: str
    key: str
    value: float
    # Takes part in neither equality nor the hash: this is a memory of
    # renders, not part of the tolerance's identity.
    _rendered: set = field(
        default_factory=set, repr=False, compare=False, hash=False)

    def _record(self, text: str) -> str:
        self._rendered.add(text)
        return text

    @property
    def rendered(self) -> frozenset:
        """The strings this tolerance has rendered itself as (for law 2)."""

        return frozenset(self._rendered)

    def __str__(self) -> str:
        return self._record(str(self.value))

    def __format__(self, format_spec: str) -> str:
        return self._record(format(self.value, format_spec))

    @property
    def cs(self) -> str:
        """A compact C# literal (``1e-6``), see :func:`_compact_cs_number`."""

        return self._record(_compact_cs_number(self.value))

    @property
    def deg_rad_divisor(self) -> str:
        """The divisor D for the expression ``Math.PI / D`` == this
        tolerance IN DEGREES.

        A rotation tolerance has historically been emitted as an EXPRESSION
        (``Math.PI / 1800.0``), not a number of radians: that is how C#
        computes it accurately and that is how it is typed in the golden
        files. The divisor is computed in ``Decimal``, because
        ``180.0 / 0.1`` in binary floating point gives 1799.9999999999998 —
        and the bytes would have shifted for the sake of prettiness.
        """

        divisor = Decimal("180") / Decimal(repr(float(self.value)))
        if divisor == divisor.to_integral_value():
            return self._record(f"{int(divisor)}.0")
        return self._record(format(divisor.normalize(), "f"))


def tolerance(op_name: str, key: str) -> Tolerance:
    """Mint the tolerance ``key`` of op ``op_name`` from the registry
    (law 1).

    A key absent from ``OpSpec.tolerances`` is a refusal HERE AND NOW, not a
    silent reference into the void that survives into production (the
    create_type defect).
    """

    from kir import spec  # local import: the registry does not know about emission

    op_spec = spec.OPS.get(op_name)
    if op_spec is None:
        raise EmitModelError(
            f"tolerance({op_name!r}, {key!r}): такого опа нет в реестре")
    tolerances = getattr(op_spec, "tolerances", None) or {}
    if key not in tolerances:
        raise EmitModelError(
            f"tolerance({op_name!r}, {key!r}): допуска с таким ключом в "
            f"реестре нет (есть: {sorted(tolerances)}) — число обязано жить в "
            "реестре, а не в эмитируемой C#")
    return Tolerance(op_name, key, float(tolerances[key]))


class ToleranceSet:
    """The tolerances of one op: ``tol["endpoint_mm"]`` mints and CACHES.

    The cache is needed in substance: the same one object both renders the
    number into C# and gets declared in the witness — law 2 checks EXACTLY
    its own memory of renders.
    """

    __slots__ = ("_op", "_minted")

    def __init__(self, op_name: str) -> None:
        self._op = op_name
        self._minted: dict[str, Tolerance] = {}

    def __getitem__(self, key: str) -> Tolerance:
        got = self._minted.get(key)
        if got is None:
            got = self._minted[key] = tolerance(self._op, key)
        return got


def tolerances(op_name: str) -> ToleranceSet:
    """The set of an op's tolerances (a replacement for
    ``spec.OPS[op].tolerances`` in emitters)."""

    return ToleranceSet(op_name)


@dataclass(frozen=True, slots=True)
class WitnessCheck:
    """One in-transaction postcondition witness.

    ``obligation_key``  — machine key the translation certificate matches
                          against ``Obligation.key`` (never a C# substring).
    ``reader_cs``       — the C# that READS the fact (may be empty when the
                          verdict's condition reads inline).
    ``verdict_cs``      — the C# that renders the verdict; MUST contain
                          ``__post.Add`` (unconstructible otherwise — this is
                          the by-construction kill of audit-F3).
    ``message``         — the human message inside the verdict (for audits;
                          the cert never matches on it).
    ``tol``             — the registry-minted :class:`Tolerance` this check
                          compares against (None for exact/boolean checks).
                          NOT A STRING: the key cannot be declared, it can
                          only be presented together with the number minted
                          by the registry (laws 1 and 2 above). ``tol_key``
                          remains as a DERIVED property — readers (the
                          certificate, audits) still need the machine key.
    ``style``           — the render genre, documentation of shape:
                          ``guard``      condition -> verdict (no else),
                          ``else_block`` reader with null-guard verdict and an
                                         else { ... } body,
                          ``plain``      free-form fragment.
                          Styles do NOT change rendering (fragments carry
                          their own layout — byte parity); they exist so
                          audits/tools can reason about check shape.
    ``stage``           — ``final`` preserves the legacy end-of-program check;
                          ``operation`` must run before the operation completes
                          and before a later operation can deliberately change
                          its result. The scheduler owns the refusal/subcommit
                          boundary; rendering alone does not execute a check.
    """

    obligation_key: str
    reader_cs: str
    verdict_cs: str
    message: str
    # compare=False IS DELIBERATE: equality of witnesses IS equality of the
    # EMITTED C#. The mutation oracle stands on this (touch a number in the
    # registry — if the bytes did not move, the tolerance is decorative);
    # include the tolerance object in the comparison, and the oracle would
    # start passing vacuously.
    tol: "Tolerance | None" = field(default=None, compare=False)
    style: Literal["guard", "else_block", "plain"] = "plain"
    stage: Literal["final", "operation"] = "final"

    @property
    def tol_key(self) -> str | None:
        """The tolerance's machine key — DERIVED from the minted object."""

        return None if self.tol is None else self.tol.key

    def __post_init__(self) -> None:
        if not self.obligation_key or not isinstance(self.obligation_key, str):
            raise EmitModelError("WitnessCheck needs a non-empty obligation_key")
        if not isinstance(self.verdict_cs, str) \
                or _VERDICT_TOKEN not in _verdict_code(self.verdict_cs):
            raise EmitModelError(
                f"WitnessCheck {self.obligation_key!r}: verdict_cs must "
                f"contain {_VERDICT_TOKEN} В КОДЕ — a witness without a "
                "verdict is unconstructible (audit F3, by construction). "
                "Токен в КОММЕНТАРИИ или внутри строкового литерала "
                "вердиктом не является: он не компилируется ни во что и "
                "нарушения не добавит")
        if not isinstance(self.reader_cs, str):
            raise EmitModelError(
                f"WitnessCheck {self.obligation_key!r}: reader_cs must be str")
        if self.style not in ("guard", "else_block", "plain"):
            raise EmitModelError(
                f"WitnessCheck {self.obligation_key!r}: unknown style "
                f"{self.style!r}")
        if self.stage not in ("final", "operation"):
            raise EmitModelError(
                f"WitnessCheck {self.obligation_key!r}: unknown stage {self.stage!r}")
        if self.tol is None:
            return
        # LAW 1: the tolerance is presented as an object from the registry,
        # not a string.
        if not isinstance(self.tol, Tolerance):
            raise EmitModelError(
                f"WitnessCheck {self.obligation_key!r}: tol={self.tol!r} — "
                "допуск обязан быть объектом Tolerance из реестра "
                "(emit_model.tolerance(op, key)); голой строкой/числом "
                "провенанс не объявляется")
        # LAW 2: a declared tolerance is obligated to be READ — the
        # witness's C# contains exactly the string the minted object
        # rendered itself.
        body = self.reader_cs + self.verdict_cs
        if not any(form in body for form in self.tol.rendered):
            raise EmitModelError(
                f"WitnessCheck {self.obligation_key!r}: объявлен допуск "
                f"{self.tol.op}.{self.tol.key}={self.tol.value}, но в C# "
                "проверки нет ни одной строки, которую этот допуск породил "
                f"(отрендерено: {sorted(self.tol.rendered)}) — это дефект "
                "create_type: заявленный провенанс при захардкоженном числе, "
                "неконструируемый по построению")

    def render(self) -> str:
        """Exact fragment for inspection/rendering; this does not schedule its stage."""

        return self.reader_cs + self.verdict_cs


def _validate_checks(oid: str, checks) -> tuple[WitnessCheck, ...]:
    if not isinstance(checks, (list, tuple)):
        raise EmitModelError(f"post block for {oid!r} requires a list or tuple of WitnessCheck")
    if not checks:
        raise EmitModelError(f"post block for {oid!r} has no witness checks")
    seen: set[str] = set()
    captured = tuple(checks)
    for check in captured:
        if not isinstance(check, WitnessCheck):
            raise EmitModelError(f"post block for {oid!r} carries a non-WitnessCheck")
        if check.stage not in ("final", "operation"):
            raise EmitModelError(f"WitnessCheck {check.obligation_key!r}: unknown stage {check.stage!r}")
        if check.obligation_key in seen:
            raise EmitModelError(f"post block for {oid!r}: duplicate obligation_key {check.obligation_key!r}")
        seen.add(check.obligation_key)
    return captured


def _render_stage(oid: str, checks, *, stage: str, bare: bool) -> str:
    if not checks:
        return ""
    label = "post" if stage == "final" else "operation"
    header = f"// {label} {cs_line_comment_fragment(oid)}\n"
    fragments = "".join(check.render() for check in checks)
    return header + (fragments if bare else "{\n" + fragments + "}")


def _require_final_stage(oid: str, checks) -> None:
    if any(check.stage != "final" for check in checks):
        raise EmitModelError(
            f"post block for {oid!r} contains operation-stage checks; "
            "use render_staged_post and schedule each returned stage explicitly")


def render_post(oid: str, checks: list[WitnessCheck] | tuple[WitnessCheck, ...]) -> str:
    """Render a post block byte-identically to the legacy hand-built string.

    The frame is the universal emitter shape ``// post <oid>\\n{\\n`` ...
    ``}``; every fragment between carries its own indentation and newlines.
    An empty check list is refused: an authoring op with NO postcondition
    would be a silently-unverified element (fail-closed). Operation-stage checks
    require render_staged_post; the legacy API never silently delays them.
    """

    checked = _validate_checks(oid, checks)
    _require_final_stage(oid, checked)
    return _render_stage(oid, checked, stage="final", bare=False)


@dataclass(frozen=True, slots=True)
class BarePost:
    """A frameless post block (the NETWORK genre).

    pipe_system/route_* historically emit ``// post <oid>\n`` + checks with
    NO surrounding ``{ }`` frame (their per-segment blocks carry their own
    braces).  Same validation as :func:`render_post`, frameless render.
    """

    checks: tuple[WitnessCheck, ...]

    def __post_init__(self) -> None:
        if not self.checks:
            raise EmitModelError("BarePost has no witness checks")
        seen: set[str] = set()
        for check in self.checks:
            if not isinstance(check, WitnessCheck):
                raise EmitModelError("BarePost carries a non-WitnessCheck")
            if check.stage not in ("final", "operation"):
                raise EmitModelError(f"BarePost carries unknown witness stage {check.stage!r}")
            if check.obligation_key in seen:
                raise EmitModelError(
                    f"BarePost: duplicate obligation_key "
                    f"{check.obligation_key!r}")
            seen.add(check.obligation_key)


def post_to_string(
    oid: str, post: "list[WitnessCheck] | tuple | BarePost",
) -> str:
    """Render a post block. THE D4 TRANSITIONAL ADAPTER WAS RETIRED ON
    27.08.2026.

    🔴 A STRING IS NO LONGER LET THROUGH, AND THIS IS A GUARANTEE, NOT
    HOUSEKEEPING. While the string passed straight through, an emitter could
    return a handwritten block — and the defect class killed by construction
    ("the verdict was deleted, the reader marker survived, the certificate
    says proven") would rise from the dead silently, bypassing the
    :class:`WitnessCheck` constructor. Now an emitter that returns a string
    REFUSES LOUDLY, and the class is closed not only for what has been
    written, but for what will be written.

    THE MEASUREMENT THAT AUTHORIZED THIS (27.08.2026, python3.12, `/opt/kir`):
    a probe on the function itself over a corpus of 28 files, 931 tests,
    **9452 lists + 164 BarePost, ZERO STRINGS**. The branch was dead, removing
    it broke nothing and did not shift a single byte of emission — held by
    `test_emit_model_byte_parity` and the goldens.

    A REFUSAL, NOT A FALL-THROUGH FAILURE: without this branch a string would
    fall through into :func:`render_post` and get taken apart there character
    by character, producing "post block carries a non-WitnessCheck" — a truth
    about the symptom, not the cause.
    """

    if isinstance(post, str):
        raise EmitModelError(
            f"post block for {oid!r} пришёл СТРОКОЙ. Переходный адаптер Д4 "
            "выведен из обращения 27.08.2026: пост возвращается только "
            "list[WitnessCheck] либо BarePost. Рукописная строка обходит "
            "конструктор WitnessCheck, то есть гарантию «свидетеля без "
            "вердикта не существует», ради которой объектная модель и заведена")
    bare = isinstance(post, BarePost)
    checked = _validate_checks(oid, post.checks if bare else post)
    _require_final_stage(oid, checked)
    return _render_stage(oid, checked, stage="final", bare=bare)


def render_staged_post(
    oid: str, post: list[WitnessCheck] | tuple[WitnessCheck, ...] | BarePost,
) -> tuple[str, str]:
    """Return (operation_cs, final_cs), never a combined executable block.

    Keys are unique across BOTH stages. Ordering within each stage is retained;
    fragments are not rewritten. A sole operation-stage check legitimately has
    no final block, but an ordinary empty collection remains an error. Existing
    final-only inputs produce exactly the legacy post_to_string bytes.

    The caller must schedule operation_cs within that operation's transaction,
    apply its refusal policy before completion, then schedule final_cs at the
    final-witness boundary. Readers can inspect both strings, but neither this
    function nor WitnessCheck.render establishes that scheduling happened.
    """
    bare = isinstance(post, BarePost)
    checked = _validate_checks(oid, post.checks if bare else post)
    operation = tuple(check for check in checked if check.stage == "operation")
    final = tuple(check for check in checked if check.stage == "final")
    return (_render_stage(oid, operation, stage="operation", bare=bare),
            _render_stage(oid, final, stage="final", bare=bare))


__all__ = [
    "BarePost",
    "EmitModelError",
    "Tolerance",
    "ToleranceSet",
    "WitnessCheck",
    "post_to_string",
    "render_post",
    "render_staged_post",
    "tolerance",
    "tolerances",
]
