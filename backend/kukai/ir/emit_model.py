"""Witness-object model for emitter post blocks (wave A2, Emission IR light).

Post blocks stop being hand-concatenated strings and become lists of
:class:`WitnessCheck` objects rendered in ONE place (:func:`render_post`).
What this buys, per the master design (Часть 3, A2):

* **Correctness by construction** — a ``WitnessCheck`` REFUSES to exist
  without a ``__post.Add`` verdict in its ``verdict_cs``; the audit-F3 class
  ("the verdict line was deleted but the reader marker survived, cert still
  said proven") becomes UNCONSTRUCTIBLE, so the translation certificate can
  consume obligation KEYS instead of substring markers and the verdict-span
  crutch dies.
* **Central tolerances** — the mm/deg numbers move from emitter literals to
  ``OpSpec.tolerances`` (registry_base); a check references its ``tol_key``.
  Values are the EXACT current numbers (byte-parity; no "improvements").
* **Group member-POSTs** — `_emit_group` can now include member checks with
  namespaced keys (the conditional-absent/substring conflict that deferred
  them disappears with keys).

Deliberately NOT a C# AST (80/20, прибито дизайном): ``decl``/``create``/
``readback`` stay strings; a check's ``reader_cs``/``verdict_cs`` are string
fragments too.  The model's job is STRUCTURE (keys, verdict presence, one
render path), not syntax.

BYTE-GUARANTEE: :func:`render_post` must reproduce the pre-refactor bytes for
every migrated emitter — enforced by ``test_emit_model_byte_parity`` over the
frozen 607-emission corpus.  A check's fragments therefore carry their own
newlines/indentation exactly as the old f-strings did, and ``render_post``
only concatenates: ``"// post <oid>\n{\n"`` + fragments + ``"}"``.

Переходный адаптер (Д4): an emitter returns post as ``str | list[WitnessCheck]``;
``emit_program`` renders both; the cert consumes the model where present
(``witness_source="model"``) and keeps the span rule for strings until the
migration completes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from kukai.ir.emit_utils import cs_line_comment_fragment

_VERDICT_TOKEN = "__post.Add"


class EmitModelError(ValueError):
    """A malformed witness check (fail-closed at construction time)."""


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
    ``tol_key``         — key into ``OpSpec.tolerances`` when the check
                          compares with a tolerance (None for exact/boolean
                          checks).  The emitter substitutes the value at
                          construction; the key preserves provenance.
    ``style``           — the render genre, documentation of shape:
                          ``guard``      condition -> verdict (no else),
                          ``else_block`` reader with null-guard verdict and an
                                         else { ... } body,
                          ``plain``      free-form fragment.
                          Styles do NOT change rendering (fragments carry
                          their own layout — byte parity); they exist so
                          audits/tools can reason about check shape.
    """

    obligation_key: str
    reader_cs: str
    verdict_cs: str
    message: str
    tol_key: str | None = None
    style: Literal["guard", "else_block", "plain"] = "plain"

    def __post_init__(self) -> None:
        if not self.obligation_key or not isinstance(self.obligation_key, str):
            raise EmitModelError("WitnessCheck needs a non-empty obligation_key")
        if not isinstance(self.verdict_cs, str) \
                or _VERDICT_TOKEN not in self.verdict_cs:
            raise EmitModelError(
                f"WitnessCheck {self.obligation_key!r}: verdict_cs must "
                f"contain {_VERDICT_TOKEN} — a witness without a verdict is "
                "unconstructible (audit F3, by construction)")
        if not isinstance(self.reader_cs, str):
            raise EmitModelError(
                f"WitnessCheck {self.obligation_key!r}: reader_cs must be str")
        if self.style not in ("guard", "else_block", "plain"):
            raise EmitModelError(
                f"WitnessCheck {self.obligation_key!r}: unknown style "
                f"{self.style!r}")

    def render(self) -> str:
        """The check's exact C# fragment (fragments own their layout)."""

        return self.reader_cs + self.verdict_cs


def render_post(oid: str, checks: list[WitnessCheck] | tuple[WitnessCheck, ...]) -> str:
    """Render a post block byte-identically to the legacy hand-built string.

    The frame is the universal emitter shape ``// post <oid>\\n{\\n`` ...
    ``}``; every fragment between carries its own indentation and newlines.
    An empty check list is refused: an authoring op with NO postcondition
    would be a silently-unverified element (fail-closed).
    """

    if not checks:
        raise EmitModelError(f"post block for {oid!r} has no witness checks")
    seen: set[str] = set()
    for check in checks:
        if not isinstance(check, WitnessCheck):
            raise EmitModelError(
                f"post block for {oid!r} carries a non-WitnessCheck")
        if check.obligation_key in seen:
            raise EmitModelError(
                f"post block for {oid!r}: duplicate obligation_key "
                f"{check.obligation_key!r}")
        seen.add(check.obligation_key)
    return (
        f"// post {cs_line_comment_fragment(oid)}\n{{\n"
        + "".join(check.render() for check in checks)
        + "}"
    )


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
            if check.obligation_key in seen:
                raise EmitModelError(
                    f"BarePost: duplicate obligation_key "
                    f"{check.obligation_key!r}")
            seen.add(check.obligation_key)


def post_to_string(
    oid: str, post: "str | list[WitnessCheck] | tuple | BarePost",
) -> str:
    """Transitional adapter (Д4): render model posts, pass strings through."""

    if isinstance(post, str):
        return post
    if isinstance(post, BarePost):
        return (f"// post {cs_line_comment_fragment(oid)}\n"
                + "".join(check.render() for check in post.checks))
    return render_post(oid, post)


__all__ = [
    "BarePost",
    "EmitModelError",
    "WitnessCheck",
    "post_to_string",
    "render_post",
]
