"""Closed outcome algebra for one KIR program execution.

``ok`` is a compatibility bit, not a sufficient state model.  In particular,
a bulk/per-op program may commit and still violate a postcondition.  Collapsing
that state to either success or failure loses one of two material facts:

* the model was mutated, so a blind retry is unsafe;
* the produced state was not proven, so it must not be accepted as success.

The three axes below deliberately stay independent.  ``acceptance`` refers to
the separate post-execution acceptance pass (for example L2 census), not to
the emitter's own in-transaction witness.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


OUTCOME_SCHEMA_VERSION = "kir-program-outcome/1"


class ExecutionState(str, Enum):
    """What is known about execution and model mutation."""

    NOT_STARTED = "not_started"
    READ_COMPLETED = "read_completed"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    UNCONFIRMED = "unconfirmed"


class WitnessState(str, Enum):
    """Verdict of KIR's execution readback/postcondition witness."""

    NOT_RUN = "not_run"
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    INCOMPLETE = "incomplete"


class AcceptanceState(str, Enum):
    """Verdict of an independent post-execution acceptance pass."""

    NOT_APPLICABLE = "not_applicable"
    NOT_RUN = "not_run"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class RetrySafety(str, Enum):
    """Whether the same mutating program may safely be attempted again."""

    SAFE = "safe"
    VERIFY_FIRST = "verify_first"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True, slots=True)
class ProgramOutcome:
    """One internally consistent point in the KIR outcome state space."""

    execution: ExecutionState
    witness: WitnessState
    acceptance: AcceptanceState

    def __post_init__(self) -> None:
        if not isinstance(self.execution, ExecutionState):
            raise TypeError("outcome.execution must be typed")
        if not isinstance(self.witness, WitnessState):
            raise TypeError("outcome.witness must be typed")
        if not isinstance(self.acceptance, AcceptanceState):
            raise TypeError("outcome.acceptance must be typed")

        terminal_witness = self.witness in (
            WitnessState.SATISFIED,
            WitnessState.VIOLATED,
        )
        if terminal_witness and self.execution not in (
            ExecutionState.READ_COMPLETED,
            ExecutionState.COMMITTED,
            ExecutionState.ROLLED_BACK,
        ):
            raise ValueError(
                "a terminal witness requires a completed execution outcome")
        if (self.execution is ExecutionState.NOT_STARTED
                and self.witness is not WitnessState.NOT_RUN):
            raise ValueError("a non-started program cannot carry a witness")
        if (self.execution is ExecutionState.UNCONFIRMED
                and self.witness not in (
                    WitnessState.NOT_RUN, WitnessState.INCOMPLETE)):
            raise ValueError("unconfirmed execution cannot carry a verdict")
        if self.execution is ExecutionState.READ_COMPLETED:
            if self.acceptance is not AcceptanceState.NOT_APPLICABLE:
                raise ValueError(
                    "read-only execution has no mutation acceptance pass")
        elif self.acceptance is AcceptanceState.NOT_APPLICABLE:
            raise ValueError(
                "not_applicable acceptance is reserved for read-only execution")
        if self.acceptance in (
            AcceptanceState.ACCEPTED,
            AcceptanceState.REJECTED,
        ) and self.execution is not ExecutionState.COMMITTED:
            raise ValueError(
                "independent acceptance requires a confirmed commit")
        if (self.acceptance is AcceptanceState.ACCEPTED
                and self.witness is not WitnessState.SATISFIED):
            raise ValueError(
                "acceptance cannot overrule an unsatisfied witness")

    @property
    def retry_safety(self) -> RetrySafety:
        if self.execution is ExecutionState.COMMITTED:
            return RetrySafety.FORBIDDEN
        if self.execution is ExecutionState.UNCONFIRMED:
            return RetrySafety.VERIFY_FIRST
        return RetrySafety.SAFE

    @property
    def committed(self) -> bool:
        return self.execution is ExecutionState.COMMITTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": OUTCOME_SCHEMA_VERSION,
            "execution": self.execution.value,
            "witness": self.witness.value,
            "acceptance": self.acceptance.value,
            "retry": self.retry_safety.value,
        }


def query_accepted() -> ProgramOutcome:
    return ProgramOutcome(
        ExecutionState.READ_COMPLETED,
        WitnessState.SATISFIED,
        AcceptanceState.NOT_APPLICABLE,
    )


def program_not_started() -> ProgramOutcome:
    return ProgramOutcome(
        ExecutionState.NOT_STARTED,
        WitnessState.NOT_RUN,
        AcceptanceState.NOT_RUN,
    )


def write_committed(*, witness: WitnessState) -> ProgramOutcome:
    if witness not in (
        WitnessState.SATISFIED,
        WitnessState.VIOLATED,
        WitnessState.INCOMPLETE,
    ):
        raise ValueError("committed write needs a completed witness state")
    return ProgramOutcome(
        ExecutionState.COMMITTED,
        witness,
        AcceptanceState.NOT_RUN,
    )


def write_rolled_back(*, witness: WitnessState) -> ProgramOutcome:
    if witness not in (WitnessState.VIOLATED, WitnessState.INCOMPLETE):
        raise ValueError("rolled-back write needs violated/incomplete witness")
    return ProgramOutcome(
        ExecutionState.ROLLED_BACK,
        witness,
        AcceptanceState.NOT_RUN,
    )


def execution_unconfirmed() -> ProgramOutcome:
    return ProgramOutcome(
        ExecutionState.UNCONFIRMED,
        WitnessState.INCOMPLETE,
        AcceptanceState.NOT_RUN,
    )


def independently_assessed(
    outcome: ProgramOutcome,
    acceptance: AcceptanceState,
) -> ProgramOutcome:
    """Attach an independent verdict without rewriting execution/witness.

    Only a confirmed write can reach this transition.  ``ProgramOutcome``'s
    constructor remains the final authority (in particular, it refuses an
    accepted result over a violated/incomplete witness).
    """

    if not isinstance(outcome, ProgramOutcome):
        raise TypeError("acceptance transition requires ProgramOutcome")
    if outcome.execution is not ExecutionState.COMMITTED:
        raise ValueError("only a confirmed commit can be independently assessed")
    if outcome.acceptance is not AcceptanceState.NOT_RUN:
        raise ValueError("independent acceptance was already attached")
    if acceptance not in (
        AcceptanceState.ACCEPTED,
        AcceptanceState.REJECTED,
        AcceptanceState.INCONCLUSIVE,
    ):
        raise ValueError("acceptance transition requires a terminal verdict")
    return ProgramOutcome(outcome.execution, outcome.witness, acceptance)


__all__ = [
    "OUTCOME_SCHEMA_VERSION",
    "AcceptanceState",
    "ExecutionState",
    "ProgramOutcome",
    "RetrySafety",
    "WitnessState",
    "execution_unconfirmed",
    "independently_assessed",
    "program_not_started",
    "query_accepted",
    "write_committed",
    "write_rolled_back",
]
