"""Deterministic bridge adapter for tests that are not about L2 failure.

Production never imports this module.  It lets older serving-contract tests
keep concentrating on their own axis while still exercising the real
pre/post acceptance calls and strict parser.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Mapping

from kukai.ir.acceptance import derive_expectation, symbol_rows_from_snapshot
from kukai.ir.acceptance_live import observation_from_census
from kukai.ir.acceptance_mutation import (
    MutationKind,
    MutationObservation,
    MutationObservationRow,
    derive_mutation_expectation,
)
from kukai.ir.acceptance_probe import ACCEPTANCE_OBSERVATION_SCHEMA_VERSION
from kukai.ir.compiler import plan_program
from kukai.ir.contracts import DocumentFingerprint


_RUN_ID_IN_CS = re.compile(r'\{"run_id", "([0-9a-f]{32})"\}')
_REVIT_VERSION_IN_CS = re.compile(r'\{"revit_version", "(20\d\d)"\}')


class PassingAcceptanceBridge:
    """Return a mechanically matching census around a mocked write."""

    def __init__(self, program: Any, *, bulk: bool = False) -> None:
        try:
            self.plan = plan_program(program, bulk=bulk)
        except Exception:  # the handler owns typed compiler refusals
            self.plan = None
        self.snapshot: Mapping[str, Any] | None = None
        self.before: dict[tuple[str, str], int] | None = None

    @staticmethod
    def _unwrap_snapshot(result: Any) -> Mapping[str, Any] | None:
        if not isinstance(result, Mapping):
            return None
        candidate = result.get("result", result)
        return candidate if isinstance(candidate, Mapping) else None

    def _expectation(self):
        assert self.snapshot is not None
        assert self.plan is not None
        levels = self.snapshot.get("levels")
        by_id = {}
        if isinstance(levels, list):
            by_id = {
                str(row["id"]): row["name"]
                for row in levels
                if (isinstance(row, Mapping)
                    and row.get("id") is not None
                    and isinstance(row.get("name"), str))
            }
        # Обязано совпадать с acceptance_runtime.prepare_acceptance байт в
        # байт: ожидание участвует в подписи, и лишний/недостающий справочник
        # тут же ломает строгий разбор переписи.
        return derive_expectation(
            self.plan,
            level_names_by_id=by_id,
            family_symbols=symbol_rows_from_snapshot(self.snapshot),
        )

    def _mutation_expectation(self):
        assert self.plan is not None
        return derive_mutation_expectation(self.plan)

    @staticmethod
    def _baseline(expectation) -> dict[tuple[str, str], int]:
        census: dict[tuple[str, str], int] = {}
        for row in expectation.rows:
            if row.count <= 0:
                continue
            key = (row.categories[0], row.level or "")
            census.setdefault(key, 10)
        return census

    @staticmethod
    def _matching_after(expectation, before):
        after = dict(before)
        for row in expectation.rows:
            if row.count <= 0:
                continue
            key = (row.categories[0], row.level or "")
            after[key] = after.get(key, 0) + row.count
        return after

    @staticmethod
    def _mutation_observation(expectation, document, run_id, phase):
        rows = []
        for claim in expectation.claims:
            exists = not (
                phase == "after" and claim.kind is MutationKind.DELETE)
            unique_id = f"kir-test-uid-{claim.target_id}" if exists else None
            version_guid = (
                hashlib.sha256(str(claim.target_id).encode("ascii")).hexdigest()[:32]
                if exists else None
            )
            location_kind = "not_requested" if exists else "missing"
            point = curve0 = curve1 = None
            type_id = None
            desired_type_exists = None
            desired_type_unique_id = None
            desired_type_version_guid = None
            parameter_matches = parameter_read_only = None
            parameter_storage = parameter_string = None
            parameter_integer = parameter_double = None
            if exists and claim.kind is MutationKind.MOVE:
                location_kind = "point"
                base = (float(claim.target_id % 1000), 2000.0, 3000.0)
                point = base
                if phase == "after":
                    point = tuple(base[index] + claim.delta_mm[index]
                                  for index in range(3))
            elif exists and claim.kind is MutationKind.CHANGE_TYPE:
                type_id = str(claim.type_id if phase == "after" else 1)
                desired_type_exists = True
                desired_type_unique_id = (
                    f"kir-test-uid-{claim.type_id}")
                desired_type_version_guid = hashlib.sha256(
                    str(claim.type_id).encode("ascii")).hexdigest()[:32]
            elif exists and claim.kind is MutationKind.SET_PARAMETER:
                parameter_matches = 1
                parameter_read_only = False
                parameter_storage = {
                    "str": "String", "int": "Integer",
                    "mm": "Double", "double": "Double",
                }[claim.value_kind]
                if claim.value_kind == "str":
                    parameter_string = claim.expected_string
                elif claim.value_kind == "int":
                    parameter_integer = int(claim.expected_number)
                elif claim.value_kind == "mm":
                    parameter_double = float(claim.expected_number) / 304.8
                else:
                    parameter_double = float(claim.expected_number)
            rows.append(MutationObservationRow(
                claim_key=claim.key,
                target_id=str(claim.target_id),
                exists=exists,
                unique_id=unique_id,
                version_guid=version_guid,
                desired_type_exists=desired_type_exists,
                desired_type_unique_id=desired_type_unique_id,
                desired_type_version_guid=desired_type_version_guid,
                type_id=type_id,
                location_kind=location_kind,
                point_mm=point,
                curve0_mm=curve0,
                curve1_mm=curve1,
                parameter_matches=parameter_matches,
                parameter_read_only=parameter_read_only,
                parameter_storage=parameter_storage,
                parameter_string=parameter_string,
                parameter_integer=parameter_integer,
                parameter_double=parameter_double,
            ))
        return MutationObservation(
            run_id=run_id,
            phase=phase,
            expectation_digest=expectation.digest,
            document_digest=document.digest,
            rows=tuple(rows),
        )

    def dispatch(
        self,
        execute: Callable[[str, str], Any],
        code: str,
        op: str,
    ) -> Any:
        if op == "ground_snapshot":
            result = execute(code, op)
            self.snapshot = self._unwrap_snapshot(result)
            return result
        if op not in {"acceptance_before", "acceptance_after"}:
            return execute(code, op)
        if self.snapshot is None:
            raise AssertionError("acceptance read preceded the ground snapshot")
        match = _RUN_ID_IN_CS.search(code)
        if match is None:
            raise AssertionError("generated acceptance C# has no bound run id")
        expectation = self._expectation()
        mutation_expectation = self._mutation_expectation()
        document = DocumentFingerprint.from_dict(
            self.snapshot["__document_fingerprint"])
        phase = "before" if op == "acceptance_before" else "after"
        observation = None
        if expectation.checkable:
            if self.before is None:
                self.before = self._baseline(expectation)
            census = (
                self.before if op == "acceptance_before"
                else self._matching_after(expectation, self.before)
            )
            observation = observation_from_census(
                expectation,
                document,
                census,
                run_id=match.group(1),
                phase=phase,
            )
        version_match = _REVIT_VERSION_IN_CS.search(code)
        if version_match is None:
            raise AssertionError("generated acceptance C# has no Revit version")
        mutation = (
            self._mutation_observation(
                mutation_expectation, document, match.group(1), phase)
            if mutation_expectation.checkable else None
        )
        return {"result": {
            "schema_version": ACCEPTANCE_OBSERVATION_SCHEMA_VERSION,
            "run_id": match.group(1),
            "phase": phase,
            "plan_digest": self.plan.plan_digest,
            "document_digest": document.digest,
            "revit_version": version_match.group(1),
            "scope_census": (
                observation.to_dict() if observation is not None else None),
            "mutations": mutation.to_dict() if mutation is not None else None,
        }}


__all__ = ["PassingAcceptanceBridge"]
