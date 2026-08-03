"""Foundational identity and live-write safety contract for KIR A5.

Version identities and the copy/token guard live below planning, evidence, and
orchestration so request hashing never imports the executable workflow.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


Vec3 = tuple[float, float, float]

# Δ pinned by the master design (mm).  200 m along +X keeps every translated
# coordinate inside Revit's ±16 km workable extent (audit F12 / _COORD_LIMIT_MM).
DELTA_MM: Vec3 = (200_000.0, 0.0, 0.0)
_ORIGIN: Vec3 = (0.0, 0.0, 0.0)

# Bump when deterministic rebuild-plan construction changes.  A persisted
# program id is a restart boundary, so changing its meaning without a version
# change would be equivalent to replaying the wrong transaction.
REBUILD_PLAN_VERSION = "a5-rebuild-plan/1"

# ── typed refusals / outcomes ────────────────────────────────────────────────


class IdempotenceError(RuntimeError):
    """A typed A5 failure.  The orchestrator never raises a bare exception."""

    def __init__(self, code: str, message: str, detail: str = "") -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail:
            d["detail"] = self.detail[:400]
        return d


# ── Д3 safety context (fail-closed doc.Title / gate guard) ───────────────────


@dataclass(frozen=True, slots=True)
class SafetyContext:
    """Everything the live path needs to prove it may write to THIS document.

    ``doc_title`` is the live ``doc.Title`` reported by the bridge.  The path
    always needs TWO independent proofs; only the first one has two forms:

    * that the document is DISPOSABLE — either an explicit A5 copy-name suffix,
      or ``operator_declared_copy`` (the naming convention is a heuristic, and
      it refused a file the operator does keep as a scratch copy; the flag is
      the deliberate override, added 2026-07-27 at the operator's decision);
    * that the RUN is authorised — an exact ``confirm_token``, a server-side
      secret.

    The declaration alone is never enough, and a token alone still cannot
    override a working-file title: a spoken "it is a copy" must not be able to
    put a thousand elements into the wrong document, which is the whole reason
    this guard exists. Ordinary words which merely contain ``copy``/``test``
    are never evidence that a document is disposable.

    ``gate_ok`` mirrors ``serving.revit_decompile_enabled()`` (flag + admin
    device); the caller resolves it and passes the boolean so this module has no
    serving import cycle and stays unit-testable.
    """

    doc_title: Optional[str] = None
    gate_ok: bool = False
    copy_markers: tuple[str, ...] = (
        "копия a5", "copy a5", "_a5_copy", "[a5-copy]",
    )
    confirm_token: Optional[str] = None
    expected_token: Optional[str] = None
    #: Explicit operator statement that THIS document is a disposable copy.
    #: Defaults to False so every existing caller and refusal is unchanged.
    operator_declared_copy: bool = False

    def title_confirms_copy(self) -> bool:
        title = " ".join((self.doc_title or "").strip().lower().split())
        if not title:
            return False
        for marker in self.copy_markers:
            marker = marker.lower()
            if title == marker:
                return True
            if not title.endswith(marker):
                continue
            # Delimiter-shaped conventions are deliberately attachable
            # (``Project_A5_COPY`` / ``Project[A5-COPY]``).  Human-readable
            # phrases need a non-word boundary, so ``Photocopy A5`` is not a
            # disposable-copy proof merely because it ends in ``copy a5``.
            if marker.startswith(("_", "[")):
                return True
            start = len(title) - len(marker)
            if start > 0 and not title[start - 1].isalnum():
                return True
        return False

    def operator_confirms_run(self) -> bool:
        return (
            bool(self.expected_token)
            and self.confirm_token == self.expected_token
        )

    def copy_proof(self) -> str:
        """Which proof admits this document, for the run record: ``title``,
        ``operator_declaration``, or ``""`` when neither holds."""

        if self.title_confirms_copy():
            return "title"
        if self.operator_declared_copy and self.operator_confirms_run():
            return "operator_declaration"
        return ""

    def refusal(self) -> Optional[IdempotenceError]:
        """Return the (fail-closed) refusal, or None if the live path is safe."""

        if not self.gate_ok:
            return IdempotenceError(
                "gate",
                "A5 недоступен: нужен KUKAI_KIR_DECOMPILE=stage2 и admin-устройство")
        if not self.doc_title:
            return IdempotenceError(
                "unconfirmed_title",
                "doc.Title не подтверждён — отказ (пиши только в копию модели)")
        if not self.copy_proof():
            return IdempotenceError(
                "not_a_copy",
                "doc.Title не распознан как копия — отказ; допустимо либо имя "
                "с суффиксом копии, либо явное operator_declared_copy ВМЕСТЕ с "
                "точным confirm_token",
                f"title={self.doc_title!r}")
        if not self.expected_token:
            return IdempotenceError(
                "confirmation_unavailable",
                "live A5 запрещён: KUKAI_A5_CONFIRM_TOKEN не настроен")
        if not self.operator_confirms_run():
            return IdempotenceError(
                "confirmation_required",
                "live A5 требует точный операторский confirm_token")
        return None
