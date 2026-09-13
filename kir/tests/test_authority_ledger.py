"""THE AUTHORITY LEDGER: every level field has a declared kind, and a
NEW field will not slip through silently.

WHY, BY MEASUREMENT ON 18-19.08.2026 ON A LIVE BENCHMARK. Two hands built
the same office tower from the same brief in a live Revit 2023 — one on
KIR, the other in freehand C#. All three major failures of the KIR hand
turned out to be VERTICAL under otherwise clean planar geometry, and both
of the load-bearing ones are about fields whose authority the registry
was silent on:

    540 out of 540 beams at z=0 while "Floor 5" was written.
    `create_beam.level` had `required=True`, yet Revit derives the
    reference level from the curve's elevation and ignores the sent
    selector. This was measured on 27.07 and recorded IN PROSE in the
    operation's `post` and in the emitter's comment. A human reads
    prose; an instrument reads a field; the field stayed undeclared, and
    the model reasonably concluded the beam stood where it had written
    it.

    420 columns at 2500 mm instead of 3600-4500.
    `create_column.top_level` is optional, and omitting it LIFTS the
    conditional obligation "top constraint == resolved top_level": the
    witness stayed silent, acceptance accepted it, and three audits
    missed it.

WHY A LEDGER, AND NOT JUST "EVERYTHING IS DECLARED." Requiring "every
level field has a non-empty declaration" would be a lie: for most of
them the authority genuinely is the author's, and an empty declaration
is the correct answer. But then a NEW field, with any authority at all,
slips through silently, because "undeclared" and "declared as authored"
look identical. The ledger closes exactly this gap: what is compared is
the SET of (op, field) pairs, and adding or removing a level field must
go through a line written by a human. The same form as
`UNREVIEWED_GOLDENS` in `test_golden.py`, and for the same reason: the
list has no default.

WHAT THIS TEST DOES NOT DO. It does not check whether a declaration is
CORRECT — that a beam's `authority` really is `DERIVED_BY_REVIT` is
established by reading the chain up to the Revit API call, not by this
test. It holds only the ledger's completeness.
"""
import unittest

from kir import spec
from kir.registry_base import ReferenceKind

#: THE KIND OF AUTHORITY FOR EVERY LEVEL FIELD. A closed list, no
#: default.
#:   "authored"  — the sent value decides, omitting it transfers nothing;
#:   "derived"   — Revit computes it itself, the sent value decides
#:                 nothing;
#:   "transfers" — omitting it SILENTLY transfers authority to another
#:                 mechanism.
#: The reasoning behind each line is in the comment next to the
#: `ParamSpec` itself.
LEVEL_FIELD_AUTHORITY: dict[tuple[str, str], str] = {
    ("create_beam", "level"): "derived",
    ("create_column", "top_level"): "transfers",
    ("create_wall", "top_level"): "transfers",
    ("place_family", "top_level"): "transfers",
    ("create_beam_system", "level"): "authored",
    ("create_building_pad", "level"): "authored",
    ("create_cable_tray", "level"): "authored",
    ("create_ceiling", "level"): "authored",
    ("create_column", "level"): "authored",
    ("create_conduit", "level"): "authored",
    ("create_duct", "level"): "authored",
    ("create_duct_placeholder", "level"): "authored",
    ("create_extrusion_roof", "level"): "authored",
    ("create_flex_duct", "level"): "authored",
    ("create_flex_pipe", "level"): "authored",
    ("create_floor", "level"): "authored",
    ("create_floor_by_contour", "level"): "authored",
    # 24.08.2026. The op arrived on 23.08 and sat outside the ledger for
    # a day — the exact silence this file catches. The answer is read
    # from its own postcondition: «its GenLevel is EXACTLY the resolved
    # level (identity)», i.e. `ViewPlan.Create(doc, typeId, levelId)`
    # takes the sent level and the witness reads back EXACTLY that one.
    # The sent value DECIDES.
    ("create_floor_plan", "level"): "authored",
    ("create_foundation", "level"): "authored",
    ("create_multi_segment_grid", "level"): "authored",
    ("create_pipe", "level"): "authored",
    ("create_pipe_placeholder", "level"): "authored",
    ("create_pipe_system", "level"): "authored",
    ("create_railing", "level"): "authored",
    ("create_roof", "level"): "authored",
    ("create_room", "level"): "authored",
    ("create_room_separator", "level"): "authored",
    ("create_space", "level"): "authored",
    ("create_topography", "level"): "authored",
    # Truss: `SketchPlane.Create(doc, __lv.Id)` — the level id travels
    # DIRECTLY into building the sketch plane (`struct_emit.py`), i.e.
    # the level decides where the truss ends up. The witness, however,
    # checks only the EXISTENCE of the reference level, not equality, out
    # of the caution paid for by the beam lesson. This is a weakened
    # witness, not a lie about authority — hence "authored".
    ("create_truss", "level"): "authored",
    ("create_wall", "level"): "authored",
    ("place_family", "level"): "authored",
    ("route_duct_system", "level"): "authored",
    ("route_pipe_system", "level"): "authored",
}


def _level_fields() -> dict[tuple[str, str], object]:
    out = {}
    for op_name, op in spec.OPS.items():
        for param in op.params:
            if ReferenceKind.LEVEL in (param.ref_kinds or ()):
                out[(op_name, param.name)] = param
    return out


class LevelAuthorityIsDeclared(unittest.TestCase):

    def test_ledger_covers_exactly_the_registry(self):
        """Not a single level field outside the ledger, not a single
        row without a field."""
        found = set(_level_fields())
        declared = set(LEVEL_FIELD_AUTHORITY)
        undeclared = sorted(found - declared)
        self.assertFalse(undeclared, (
            f"уровневые поля вне ведомости: {undeclared}. Новое поле обязано "
            "СКАЗАТЬ, кто решает его значение — 'authored', 'derived' или "
            "'transfers'; молчание здесь и стоило 540 балок на z=0."))
        stale = sorted(declared - found)
        self.assertFalse(stale, (
            f"строки ведомости без поля в реестре: {stale} — ведомость должна "
            "умереть вместе с полем, иначе она рассказывает про прошлое."))

    def test_declaration_matches_the_param(self):
        """The ledger's row and the field itself say the same thing."""
        for key, verdict in sorted(LEVEL_FIELD_AUTHORITY.items()):
            param = _level_fields()[key]
            with self.subTest(field=f"{key[0]}.{key[1]}", verdict=verdict):
                if verdict == "derived":
                    self.assertEqual(param.authority, "DERIVED_BY_REVIT")
                    self.assertFalse(param.omission_transfers)
                elif verdict == "transfers":
                    self.assertEqual(param.authority, "AUTHORED")
                    self.assertTrue(param.omission_transfers, (
                        "род 'transfers' обязан НАЗВАТЬ, что берёт власть — "
                        "иначе репетиция печатает его наравне с украшением"))
                    self.assertFalse(param.required, (
                        "передача власти при пропуске возможна только у "
                        "НЕобязательного поля: обязательное пропустить нельзя"))
                else:
                    self.assertEqual(param.authority, "AUTHORED")
                    self.assertFalse(param.omission_transfers)

    def test_a_transfer_names_a_mechanism_not_a_feeling(self):
        """A "transfers" declaration is a claim about the MECHANISM, not
        about "an important field"."""
        for (op_name, field), verdict in sorted(LEVEL_FIELD_AUTHORITY.items()):
            if verdict != "transfers":
                continue
            text = _level_fields()[(op_name, field)].omission_transfers
            with self.subTest(field=f"{op_name}.{field}"):
                self.assertGreaterEqual(len(text), 40, (
                    "слишком коротко, чтобы назвать механизм: читателю нужно "
                    "знать, ЧТО решит вместо программы"))
                self.assertTrue(
                    any(w in text for w in ("умолчани", "число", "ЧИСЛОМ",
                                            "автонумерац", "семейства", "типа")),
                    f"не назван механизм-получатель власти: {text!r}")


if __name__ == "__main__":
    unittest.main()
