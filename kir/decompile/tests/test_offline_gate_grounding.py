"""The dry gate must compile the SAME THING that will go into the model.

A REFUTING MEASUREMENT OF 10.08.2026, a real building, not a hypothesis.
``tools/compile_gate_offline.py`` on ``snowdon_plumb_v3`` — that very
Autodesk sample which, live on 30.07, assembled 318 programs out of
318 — gave **0 out of 156** program-versions: all 26 programs refused
with ``KIR-G104 piping_system_types: empty in the model`` on every one
of the six versions. That is, the project's strongest offline instrument
NEVER ONCE compiled a single engineering building and reported this as a
program failure.

The refusal was not reporting on the program but on the gate's own
blindness, and the blindness was twofold:

1. **The lift was not fed all the side indexes.** ``emit_all`` passed
   ``sketch``/``family_placement``/``curve``/``curtain`` and said
   nothing about ``mep_system``, ``annotation``, and ``tag`` — while
   both the live pipeline and ``tools/relift_offline.py`` pass all
   seven. Measurement on ``snowdon_plumb_v3``: without the systems
   index, 6 343 ops and NOT ONE with ``system_type``; with it, 6 369
   ops, of which 3 055 ``create_pipe`` and 181 ``create_duct`` carry a
   system type by name. The instrument was measuring the compiler on a
   degraded representation — exactly the reason the tag index in
   ``relift_offline`` carries its own separate comment.

2. **The grounding snapshot was rebuilt FROM SCRATCH out of L0 instead
   of the captured catalogue.** ``snapshot_from_l0`` reconstructs pools
   from the distribution of ``type_id``/``type_name`` across elements,
   but a system type is NOT AN L0 ELEMENT — such a pool cannot be
   assembled from L0 in principle. Next to every decompile sits
   ``open_model.profile.json``, captured by the same run, and it is
   already read by the SHARED function
   ``serving.source_catalogue_snapshot``, set up on 28.07 (``0bdb0cef``)
   for exactly this class of defect: "the refusal was reporting not on
   the program but on the caller's blindness," measured then as 43
   compilable ops out of 543 against 543. This is the third private
   copy of the same knowledge, and it planted the defect a third time.
   The catalogue exists for 69 of the 76 decompiles on this machine.

The fixture here is SYNTHETIC on purpose: the real corpus of decompiles
lives outside any checkout (a machine-local 4.1 GB), and the test must
fail in a clean clone. It reproduces exactly the shape on which the
measurement was made: two pipes, TWO system types in the catalogue (one,
and the default would have been inferred, and the defect would not have
shown), and a side index naming the system type by name.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from kir.instruments.compile_gate_offline import emit_all, gate_snapshot



_LEVEL_ID = "355"
_PIPE_TYPE_ID = 604023
#: There are TWO of them deliberately: with a single option, `ground`
#: would have inferred the system type itself, and both halves of the
#: defect would have stayed invisible.
_SYSTEM_TYPES = ((712045, "Hydronic Supply"), (712047, "Sanitary"))


def _pipe(element_id: str, y: float) -> dict:
    return {
        "record": "element",
        "element": {
            "element_id": element_id,
            "category": "OST_PipeCurves",
            "category_ru": "Трубы",
            "type_id": str(_PIPE_TYPE_ID),
            "type_name": "По умолчанию",
            "level_id": _LEVEL_ID,
            "level_name": "Уровень 1",
            "geom_kind": "curve",
            "p0_mm": [0.0, y, 2700.0],
            "p1_mm": [5000.0, y, 2700.0],
            "rotation_deg": None,
            "bbox_min_mm": [0.0, y - 50.0, 2650.0],
            "bbox_max_mm": [5000.0, y + 50.0, 2750.0],
            "host_id": None,
            "params": {"RBS_PIPE_DIAMETER_PARAM": 100},
        },
    }


def _pool(name: str, entries: tuple[tuple[int, str], ...]) -> dict:
    return {
        "name": name,
        "captured_count": len(entries),
        "complete": True,
        "entries": [
            {"element_id": element_id, "name": name_, "category": None,
             "class_name": None, "family_name": None, "type_name": None,
             "identity_exact": True, "p0_mm": None, "p1_mm": None,
             "params": None}
            for element_id, name_ in entries
        ],
    }


def _write_fixture(directory: pathlib.Path) -> None:
    header = {
        "record": "header",
        "schema_version": "1.0",
        "document": {
            "change_stamp": "offline-gate-fixture",
            "doc_name": "Инженерная фикстура",
            "grids": [],
            "levels": [{"elevation_mm": 0.0, "id": _LEVEL_ID,
                        "name": "Уровень 1"}],
            "project_info": {"address": None, "building_type_hint": None,
                             "name": "Фикстура"},
            "revit_version": "2026",
            "rooms": [],
            "units": "mm",
        },
    }
    rows = [header, _pipe("21201143", 0.0), _pipe("21201854", 3000.0),
            {"record": "footer", "category_count": 1, "element_count": 2,
             "link_count": 0, "stream_complete": True}]
    (directory / "L0.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8")

    # The source model's catalogue — the very one the live run captures.
    (directory / "open_model.profile.json").write_text(json.dumps({
        "schema_version": "kir-open-model-profile/1",
        "revit_version": "2026",
        "pools": [
            _pool("levels", ((int(_LEVEL_ID), "Уровень 1"),)),
            _pool("pipe_types", ((_PIPE_TYPE_ID, "По умолчанию"),)),
            _pool("piping_system_types", _SYSTEM_TYPES),
        ],
    }, ensure_ascii=False), encoding="utf-8")

    # The system type's side index: without it the pipe lifts without
    # `system_type`, and grounding honestly refuses with KIR-G102.
    (directory / "mep_system.index.json").write_text(json.dumps({
        "schema_version": "kir-decompile-mep-system-index/1",
        "system_index": {
            "21201143": {"element_id": "21201143",
                         "system_type_id": str(_SYSTEM_TYPES[1][0]),
                         "system_type_name": _SYSTEM_TYPES[1][1]},
            "21201854": {"element_id": "21201854",
                         "system_type_id": str(_SYSTEM_TYPES[0][0]),
                         "system_type_name": _SYSTEM_TYPES[0][1]},
        },
        "failures": [],
    }, ensure_ascii=False), encoding="utf-8")


class OfflineGateGrounding(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.directory = pathlib.Path(self._tmp.name)
        _write_fixture(self.directory)
        self.addCleanup(self._tmp.cleanup)

    def test_snapshot_is_the_captured_catalogue_not_a_reconstruction(self):
        """A pool of system types CANNOT be assembled from L0: they are
        not model elements.

        While the gate rebuilt the snapshot itself, `piping_system_types`
        was absent from it entirely, and every engineering program
        refused with KIR-G104 "empty in the model" — the instrument was
        reporting on its own blindness.
        """
        snapshot, source = gate_snapshot(self.directory)
        self.assertEqual(source, "open_model.profile.json")
        self.assertIn("piping_system_types", snapshot)
        self.assertEqual(
            sorted(row["name"] for row in snapshot["piping_system_types"]),
            sorted(name for _, name in _SYSTEM_TYPES))
        # Levels must remain: grounding the level is mandatory.
        self.assertTrue(snapshot.get("levels"))

    def test_lift_gets_every_side_index_the_live_pipeline_gets(self):
        """The gate must feed the lift the same set of indexes as the
        live path.

        Otherwise it measures the compiler on a degraded representation:
        the pipe lifts without a system type, and the refusal looks like
        a defect of the language.
        """
        _, stats = emit_all(self.directory, chunk=250)
        self.assertEqual(stats["ops"], 2, stats)
        self.assertEqual(stats["named_system_type_ops"], 2, stats)

    def test_a_piping_building_compiles_on_all_six_versions(self):
        """The end-to-end assertion the gate exists for."""
        emitted, stats = emit_all(self.directory, chunk=250)
        self.assertEqual(stats["refused"], {}, stats)
        self.assertEqual(len(emitted), 6 * stats["programs"], stats)
        self.assertTrue(stats["compiler_ready"], stats)
        self.assertEqual(stats["snapshot_source"], "open_model.profile.json")

    def test_a_run_without_the_catalogue_says_so_instead_of_pretending(self):
        """A decompile without a catalogue is not a reason to fake a
        pool.

        `демо-v3`, the only building on which the gate ever gave a clean
        run, has no catalogue at all. Rebuilding from L0 remains a
        fallback path, but it must be NAMED: a silent substitution would
        make the gate's number incomparable across buildings.
        """
        (self.directory / "open_model.profile.json").unlink()
        snapshot, source = gate_snapshot(self.directory)
        self.assertEqual(source, "L0 (каталога нет)")
        self.assertNotIn("piping_system_types", snapshot)
        _, stats = emit_all(self.directory, chunk=250)
        self.assertEqual(stats["snapshot_source"], "L0 (каталога нет)")


class ОтсутствующийИндексНазываетПричину(unittest.TestCase):
    """🔴 F-301: "the stage did not run" and "the index was deleted"
    both used to arrive as the same None.

    `_load_side_index` must return `None` — the instrument counts over
    an incomplete decompile too, and must not crash on it. But the
    docstring promises "the stage DID NOT RUN," while `None` means
    exactly "the file is absent." The answer stays the same, the silence
    has gained a reason: `absent_side_indexes()`.

    A pair of controls: it can name it, and it can stay silent.
    """

    def test_a_missing_directory_and_a_missing_file_differ(self) -> None:
        from kir.instruments import relift_offline as R
        with tempfile.TemporaryDirectory() as tmp:
            gone = pathlib.Path(tmp) / "нет-такого"
            empty = pathlib.Path(tmp) / "пустой"
            empty.mkdir()
            no_dir = R.absent_side_indexes(gone, R._SIDE_INDEX_NAMES)
            no_file = R.absent_side_indexes(empty, R._SIDE_INDEX_NAMES)
            self.assertEqual(list(no_dir), [""],
                             "каталога нет -> ОДНА причина на всех, "
                             "перечислять файлы негде")
            self.assertIn(str(gone), no_dir[""])
            self.assertEqual(len(no_file), len(R._SIDE_INDEX_NAMES),
                             "каталог есть -> каждый недостающий индекс назван "
                             "поимённо")
            self.assertNotEqual(set(no_dir), set(no_file),
                                "«искать было негде» и «искали, не нашли» — "
                                "РАЗНЫЕ факты")

    def test_a_present_index_is_not_reported_absent(self) -> None:
        """A positive control: an instrument that always complains is
        not guarding anything."""
        from kir.instruments import relift_offline as R
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "tag.index.json").write_text("{}", encoding="utf-8")
            absent = R.absent_side_indexes(d, R._SIDE_INDEX_NAMES)
            self.assertNotIn("tag.index.json", absent)
            self.assertEqual(len(absent), len(R._SIDE_INDEX_NAMES) - 1)


if __name__ == "__main__":
    unittest.main()
