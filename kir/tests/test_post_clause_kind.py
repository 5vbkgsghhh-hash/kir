"""THE `post` CLAUSE KIND IS AN INSTRUMENT, WITHOUT WHICH THE LABEL REMAINS
DECORATION.

WHY THIS FILE EXISTS. The 21.08.2026 census declared: 218 of 365 `post`
clauses do not name an axis. The number checked out on recount, but the
conclusion did not follow from it: the clause's axis has THREE carriers,
and prose is the only one that nobody reads.

    1. `OpSpec.post` — prose. `translation_cert.audit_registry_coverage`
       STRIPS OUT axis words (`filler`), i.e. does not read the bracket at
       all;
    2. `translation_cert.Obligation.kind` — the machine kind; it is read by
       `serving._unwitnessed_axes`;
    3. the witness's message text — from it `serving._axes_from_violations`
       sorts out the violation that ACTUALLY HAPPENED, and everything
       unmarked goes into semantics.

Adding the word to the prose and stopping there would mean getting a green
by construction. So the label is COPIED onto carrier #2, and this file
holds what the copy is worthless without:

    L1  a guard on import refuses a NEW clause with no kind (mutation);
    L2  two labels on one clause — a refusal (mutation);
    L3  ANTI-DECORATION: a kind named by an op's clauses must be among the
        kinds of its obligations — there is no such thing as a label with
        no matching obligation;
    L4  the `CLAUSES_WITHOUT_KIND` journal does not rot: dead and overdue
        lines fail the test;
    L5  the baseline does not rot and only decreases;
    L6  the sixteen ops that make up the REAL building are fully parsed;
    L7  the dictionary of kinds does not diverge from
        `translation_cert._KINDS`;
    L8  🔴 THE LIVE AXIS ROUTE: a violation of a geometry/topology-kind
        obligation must land on ITS OWN axis at
        `serving._axes_from_violations`. Today it does not always land
        there, and three exceptions are named by name — this is a finding,
        not an allowance: `create_wall.arc` and `place_family.rotation`
        account for 13 185 operations of the real building out of 19 041.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_kind_queue.jsonl"))

from kir import spec                                       # noqa: E402
from kir import translation_cert as tc                     # noqa: E402
from kir.serving import _axes_from_violations              # noqa: E402

#: The ops that make up the real building, and how many times each of them
#: occurs in it. Parse of MNVNK_ATR_PD_B14_K6_AR_R2022 (33 944 elements,
#: 19 041 lifted operations), `lift_cache`, measurement 22.08.2026. The sum
#: is 19 041, meaning there is NOT a single other writing op in this
#: building.
BUILDING_OPS = {
    "create_wall": 7845, "place_family": 5340, "create_tag": 1285,
    "create_door": 1230, "create_room_separator": 1086, "create_text": 809,
    "create_dimension": 667, "create_room": 467, "create_railing": 86,
    "create_beam": 76, "create_floor": 58, "create_grid": 31,
    "create_level": 30, "create_roof": 28, "create_column": 2,
    "create_ceiling": 1,
}

#: 🔴 LIVE CARRIER DISCREPANCIES, measurement 22.08.2026 — frozen by name,
#: so that a fourth one does not creep in silently. Each line: (op,
#: obligation key, kind, what is wrong). All three are the witness's
#: message, and NOT the obligation: `_axes_from_violations` looks for the
#: EXACT substring `(geometry)` in the message, and
#: `(geometry, tolerance 0.1deg)` does not match it.
#:
#: THE PRICE, IN NUMBERS. The violation ends up on the semantic axis, while
#: the geometric one stays GREEN: an arc wall with the wrong center and a
#: family rotated the wrong way both report `geometry_ok: True`. Fixed with
#: ONE word in `authoring.py` (a bracket made exactly from the axis name)
#: or by relaxing the reader in `serving._axes_from_violations`; both files
#: are foreign to this wave.
#: 🔴 EMPTY SINCE 22.08.2026 — ALL THREE WERE FIXED ON THE DAY OF THE
#: FINDING, and this guard itself showed which ones, once the fix removed
#: them.
#:
#: There were three: `create_wall/arc`, `create_column/rotation`,
#: `place_family/rotation` — 13 187 operations out of 19 041 in the MNVNK
#: parse, 69 % of the real building. Two routes were fixed at the READER
#: (`serving._axis_marked` now accepts `(axis, refinement)`, not just
#: `(axis)`), the third at the WRITER: the arc's messages had no marking
#: at all.
#:
#: An empty set here does NOT mean "defects of this kind do not occur":
#: the test checks WHAT WAS FOUND against this set in both directions, so
#: a fourth route would fail it just as it would have failed with three
#: entries.
AXIS_ROUTING_DEFECTS: set[tuple[str, str, str]] = set()


def _kinds_of(op_name: str) -> set[str]:
    ref = tc._ensure_table().get(op_name)
    return {o.kind for o in ref.obligations} if ref else set()


class GuardRefusesSilence(unittest.TestCase):
    """L1/L2 — the registry guard really does refuse (via mutation)."""

    def _relint(self, op_name: str, post: str):
        import dataclasses
        original = spec.OPS[op_name]
        spec.OPS[op_name] = dataclasses.replace(original, post=post)
        try:
            spec._lint_post_clause_kinds()
        finally:
            spec.OPS[op_name] = original

    def test_l1_a_new_clause_without_a_kind_is_refused(self) -> None:
        post = spec.OPS["create_wall"].post + "; свежее обещание без рода"
        with self.assertRaises(AssertionError) as got:
            self._relint("create_wall", post)
        self.assertIn("без названного рода", str(got.exception))

    def test_l1_the_control_passes_when_the_kind_is_named(self) -> None:
        """Control: the guard does NOT fail the same clause WITH a kind.

        Without this pair, L1 is green by construction — it could fail for
        a reason that has nothing to do with the kind.
        """
        post = spec.OPS["create_wall"].post + "; свежее обещание (geometry)"
        self._relint("create_wall", post)          # does not throw

    def test_l2_two_kinds_in_one_clause_are_refused(self) -> None:
        post = spec.OPS["create_wall"].post + "; и форма и связь (geometry) (topology)"
        with self.assertRaises(AssertionError) as got:
            self._relint("create_wall", post)
        self.assertIn("СРАЗУ", str(got.exception))


class LabelIsBackedByAnObligation(unittest.TestCase):
    """L3 — there is no such thing as a label with no matching obligation."""

    def test_l3_every_named_kind_has_an_obligation_of_that_kind(self) -> None:
        for name, op in sorted(spec.OPS.items()):
            named = {k for k in
                     (spec.post_clause_kind(c) for c in spec.post_clauses(op))
                     if k}
            if not named:
                continue
            declared = _kinds_of(name)
            if not declared:
                # An op outside the obligations table (the query family). It
                # must have no label at all — otherwise it would promise a
                # witness that the op does not have by construction.
                self.assertEqual(
                    named, set(),
                    f"{name}: клаузы называют роды {sorted(named)}, а "
                    f"обязательств у опа нет ни одного")
                continue
            self.assertLessEqual(
                named, declared,
                f"{name}: клаузы называют роды {sorted(named - declared)}, "
                f"которых нет ни у одного обязательства "
                f"({sorted(declared)}) — метка без свидетеля")


class LedgerDoesNotRot(unittest.TestCase):
    """L4 — the journal of named decisions is re-checked, not just read."""

    def test_l4_every_entry_still_matches_a_real_clause(self) -> None:
        for key in spec.CLAUSES_WITHOUT_KIND:
            op_name, _sep, needle = key.partition("::")
            self.assertIn(op_name, spec.OPS, f"{key}: опа нет в реестре")
            clauses = [c.lower() for c in spec.post_clauses(spec.OPS[op_name])]
            self.assertTrue(
                any(needle in c for c in clauses),
                f"{key}: подстроки нет ни в одной клаузе — строка МЁРТВАЯ, "
                f"а `named_absences`-подобные записи такого рода этот дом "
                f"уже покупал")

    def test_l4_no_entry_survives_its_own_clause_getting_a_kind(self) -> None:
        for key in spec.CLAUSES_WITHOUT_KIND:
            op_name, _sep, needle = key.partition("::")
            for clause in spec.post_clauses(spec.OPS[op_name]):
                if needle not in clause.lower():
                    continue
                self.assertIsNone(
                    spec.post_clause_kind(clause),
                    f"{key}: клауза УЖЕ называет род — строка журнала "
                    f"просрочена и обязана быть удалена")

    def test_l4_form_is_enforced_on_import(self) -> None:
        from kir.record_ratchet import ALL_LEDGERS
        self.assertIn("spec.CLAUSES_WITHOUT_KIND", ALL_LEDGERS)


class BaselineOnlyShrinks(unittest.TestCase):
    """L5 — ratchet: the number of unparsed clauses does not grow."""

    def test_l5_no_op_exceeds_its_baseline(self) -> None:
        unlabelled = spec.clauses_without_kind()
        for name, clauses in sorted(unlabelled.items()):
            ceiling = spec.CLAUSES_WITHOUT_KIND_BASELINE.get(name, 0)
            self.assertLessEqual(
                len(clauses), ceiling,
                f"{name}: клауз без рода {len(clauses)} > базовой линии "
                f"{ceiling}")

    def test_l5_baseline_names_only_real_ops(self) -> None:
        for name in spec.CLAUSES_WITHOUT_KIND_BASELINE:
            self.assertIn(
                name, spec.OPS,
                f"{name}: базовая линия называет оп, которого нет в реестре")

    def test_l5_baseline_carries_no_zero_rows(self) -> None:
        """A zero-count line is an op that has been parsed but stayed on the
        debt list.

        Such a line never goes red and therefore never shrinks: it turns
        the ratchet into an archive.
        """
        zero = [n for n, v in spec.CLAUSES_WITHOUT_KIND_BASELINE.items()
                if v <= 0]
        self.assertEqual(zero, [], f"нулевые строки базовой линии: {zero}")


class TheRealBuildingIsCovered(unittest.TestCase):
    """L6 — all 19 041 operations of the real building are fully parsed."""

    def test_l6_building_ops_have_no_untriaged_clause(self) -> None:
        unlabelled = spec.clauses_without_kind()
        left = {n: unlabelled[n] for n in BUILDING_OPS if n in unlabelled}
        self.assertEqual(
            left, {},
            f"опы настоящего здания с неразобранными клаузами: {left}")

    def test_l6_building_ops_are_registry_ops(self) -> None:
        missing = sorted(set(BUILDING_OPS) - set(spec.OPS))
        self.assertEqual(missing, [], f"нет в реестре: {missing}")


class KindVocabularyIsShared(unittest.TestCase):
    """L7 — the two carriers of the kind dictionary do not diverge."""

    def test_l7_spec_kinds_equal_certificate_kinds(self) -> None:
        self.assertEqual(
            set(spec.POST_CLAUSE_KINDS), set(tc._KINDS),
            "словарь родов у реестра и у сертификата разошёлся — метка в "
            "прозе перестала бы значить то же, что род обязательства")


class AxisRoutingIsHonest(unittest.TestCase):
    """L8 🔴 — a violation of an obligation lands on ITS OWN axis, not a neighboring one."""

    @staticmethod
    def _messages_by_key() -> dict[tuple[str, str], set[str]]:
        from kir import ground as ground_mod
        from kir.authoring import _EMITTERS
        from kir.compiler import _parse_and_check
        from kir.emit_model import BarePost
        from kir.tests.fixtures import GROUND_SNAPSHOT
        from kir.tests.test_emitter_scope_contract import (
            PROGRAMS, VERSIONS,
        )
        out: dict[tuple[str, str], set[str]] = {}
        for prog in PROGRAMS.values():
            lo = prog.get("__min_ver__", "2021")
            hi = prog.get("__max_ver__", VERSIONS[-1])
            clean = {k: v for k, v in prog.items()
                     if k not in ("__min_ver__", "__max_ver__")}
            grounded = ground_mod.ground(_parse_and_check(clean),
                                         GROUND_SNAPSHOT)
            for ver in [v for v in VERSIONS if lo <= v <= hi]:
                for op in grounded:
                    if op["op"] not in _EMITTERS:
                        continue
                    _d, _c, post, _r = _EMITTERS[op["op"]](op, ver, "kir:cert")
                    if isinstance(post, BarePost):
                        post = list(post.checks)
                    if not isinstance(post, (list, tuple)):
                        continue
                    for check in post:
                        out.setdefault((op["op"], check.obligation_key),
                                       set()).add(check.message)
        return out

    def test_l8_a_geometry_violation_reddens_the_geometry_axis(self) -> None:
        messages = self._messages_by_key()
        found: set[tuple[str, str, str]] = set()
        for name, ref in sorted(tc._ensure_table().items()):
            for ob in ref.obligations:
                if ob.kind not in ("geometry", "topology") or ob.key is None:
                    continue
                for message in sorted(messages.get((name, ob.key), ())):
                    axes = _axes_from_violations([f"id: {message}"])
                    if not axes[f"{ob.kind}_ok"]:
                        continue
                    found.add((name, ob.key, ob.kind))
        self.assertEqual(
            found, AXIS_ROUTING_DEFECTS,
            "маршрут оси разошёлся с замером 22.08.2026. Новая строка — "
            "свежий дефект: нарушение уезжает не на свою ось, и та остаётся "
            "зелёной. Исчезнувшая строка — починка: удали её из "
            "AXIS_ROUTING_DEFECTS вместе с правкой")

    def test_l8_the_control_is_not_vacuous(self) -> None:
        """Control: a correctly labeled message reddens ITS OWN axis.

        Without it, L8 is green by construction — the sets could coincide
        simply because the reader never goes red.
        """
        axes = _axes_from_violations(["id: endpoints mismatch (geometry)"])
        self.assertFalse(axes["geometry_ok"])
        self.assertTrue(axes["semantic_ok"])
        self.assertTrue(axes["topology_ok"])


if __name__ == "__main__":                                   # pragma: no cover
    unittest.main()
