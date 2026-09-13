"""Test-only attribution of the reviewed section identity-capture migration.

This is not an emitter compatibility mode. It reverses exact shared readback
fragments in memory, leaving declarations/create/post untouched, and restores
the registry on exit. A changed/missing fragment is an assertion failure.
Annotation's separately reviewed older type-stage delta has its own reversal.
No native execution, fixture writes, or historical source reconstruction.
"""
from contextlib import contextmanager
import os
import unittest
from unittest.mock import patch

from kir import authoring
from kir.emit_core import (
    _indent, _safe, element_identity_readback_cs,
    type_assignment_declarations, type_assignment_readback_cs,
    type_assignment_witness,
)
from kir.emit_model import render_staged_post


CAPTURE_EMITTERS = (
    "create_wall", "create_floor", "create_floor_by_contour", "create_room",
    "create_wall_type",
)


def reverse_capture_readback(readback, *, op_id, revit_version):
    identifier = _safe(op_id)
    fragment = element_identity_readback_cs(
        "__el_" + identifier, revit_version=revit_version)
    guarded = f'    try {{ __rb["id"] = __el_{identifier}.Id.ToString(); }} catch {{ }}\n'
    legacy = f'    __rb["id"] = __el_{identifier}.Id.ToString();\n'
    assert readback.count(fragment) == 1, "capture fragment missing or duplicated"
    assert readback.count(guarded) == 1, "guarded id fragment missing or duplicated"
    return readback.replace(fragment, "", 1).replace(guarded, legacy, 1)


@contextmanager
def without_section_capture():
    originals = {name: authoring._EMITTERS[name] for name in CAPTURE_EMITTERS}

    def wrap(name, actual):
        def emitter(op, version, stamp, isolation="atomic"):
            decl, create, post, readback = actual(op, version, stamp, isolation)
            if name == "create_wall_type" and op.get("host_kind", "wall") not in ("wall", "floor"):
                return decl, create, post, readback
            restored = reverse_capture_readback(
                readback, op_id=op["id"], revit_version=version)
            return decl, create, post, restored
        return emitter

    try:
        authoring._EMITTERS.update({name: wrap(name, actual) for name, actual in originals.items()})
        yield
    finally:
        authoring._EMITTERS.update(originals)


def annotation_stage_fragments():
    """Only the W1 wall in the two reviewed annotation golden programs."""
    operation, final = render_staged_post(
        "W1", [type_assignment_witness("__el_W1", "__wt_W1", "W1")])
    assert final == ""
    return {
        "declarations": type_assignment_declarations("W1") + "\n",
        "operation_gate": _indent(
            authoring.operation_check_gate("W1", operation, "atomic"), "        ") + "\n",
        "assignment_and_final_type_readback": type_assignment_readback_cs("__el_W1", "W1"),
    }


def reverse_annotation_stage(source):
    for label, fragment in annotation_stage_fragments().items():
        assert source.count(fragment) == 1, f"annotation {label} missing or duplicated"
        source = source.replace(fragment, "", 1)
    return source


def collect_golden_emissions():
    """Use the actual owners' version/snapshot policies, not corpus defaults.

    Only the expected text-equality comparison is collected. Every other owner
    assertion remains active; this helper does not replace the golden tests.
    """
    from kir.tests import test_annotation, test_golden
    emissions = {}

    class Collector:
        def assertEqual(self, left, right, msg=None):
            if isinstance(left, str) and isinstance(right, str) and msg and ": emit drifted" in msg:
                name = msg.split(": emit drifted", 1)[0]
                assert name not in emissions, "duplicate golden owner"
                emissions[name] = right
                return
            return super().assertEqual(left, right, msg)

    with patch.dict(os.environ, {"KIR_UPDATE_GOLDEN": "0"}):
        for owner in (test_golden.Golden, test_annotation.Golden):
            test_class = type("CaptureGolden", (Collector, owner), {})
            result = unittest.TestResult()
            test_class("test_golden").run(result)
            assert not result.errors and not result.failures, (result.errors, result.failures)
    return emissions
