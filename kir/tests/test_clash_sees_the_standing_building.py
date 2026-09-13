"""THE BATCH IS COMPARED AGAINST WHAT IS ALREADY STANDING — and can say that it was not compared.

WHAT THIS FILE GUARDS. Before the "standing" wave, `clash_bundle` compared
the batch AGAINST ITSELF, and its own receipt called this out: "a clash with
someone else's wall is not 'not found', it is INVISIBLE". Zero findings read
as "the building is fine" — green with no act of distinguishing, our form
18, on the product path.

Three FACTS must stay distinguishable here, and merging them was exactly
the defect:

    no source                -> present=False + a REASON in words
    source present, empty    -> present=True, bodies=0   ("looked, clean")
    source present, found    -> a finding with addresses on BOTH sides

Merging any two means bringing the defect back, so each is checked
separately, and the reverse control requires that substituting emptiness
for the standing building must not give a silent green.
"""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from kir.clash import detect as D
from kir.clash import existing as E
from kir import clash_bundle as CB

#: The bounding box of the "existing wall" — numbers of a real decompiled
#: element from `sob62_r23_v5`, taken by measurement, not invented.
WALL_LO = [9600.0, 105160.0, 2350.0]
WALL_HI = [9800.0, 109160.4, 5800.0]


def _l0_line(element: dict) -> str:
    return json.dumps({"record": "element", "collector": element["category"],
                       "element": element}, ensure_ascii=False)


def _wall(element_id: str, lo, hi) -> dict:
    return {"element_id": element_id, "category": "OST_Walls",
            "category_ru": "Стены", "geom_kind": "curve",
            "bbox_min_mm": list(lo), "bbox_max_mm": list(hi),
            "level_id": "9835106", "type_name": "ВН_Газобетон D600_200мм"}


def _run_dir(elements: list[dict]) -> pathlib.Path:
    """A decompile on disk. A real file, not a stub: the loader reads it
    line by line, and substituting its source would mean testing something
    other than the loader."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="kir-standing-"))
    with (root / "L0.jsonl").open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({"document": {"doc_name": "тест"}}) + "\n")
        for element in elements:
            handle.write(_l0_line(element) + "\n")
    return root


def _pack(dx: float = 0.0) -> list[dict]:
    """A new body with a bounding box exactly like the wall's, shifted by `dx`.

    `create_directshape` is chosen deliberately: its body is a mesh in mm,
    i.e. numbers from the program itself, and it does NOT REQUIRE a type
    snapshot. A pipe would need an outer diameter from its type, and the
    control would then be measuring the fixture's presence, not the
    comparison against the standing building.
    """
    x0, y0, z0 = WALL_LO[0] + dx, WALL_LO[1], WALL_LO[2]
    x1, y1, z1 = WALL_HI[0] + dx, WALL_HI[1], WALL_HI[2]
    verts = [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
             [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]]
    return [{"ir_version": "1.0", "ops": [{
        "op": "create_directshape", "id": "w1", "category": "generic_model",
        "name": "новая стена",
        "mesh": {"vertices_mm": verts, "faces": [[0, 1, 2]]}}]}]


def _report(pack, existing_run=None):
    """A report with the flag raised — and the environment is RESTORED afterward.

    This tree's environment guard caught the first edition: the flag stayed
    raised, and the next test would have seen someone else's state, its
    failure looking like its own. We restore via `try/finally` instead of
    writing ourselves into the guard's exceptions.
    """
    import os

    had = "KUKAI_IR_CLASH" in os.environ
    before = os.environ.get("KUKAI_IR_CLASH")
    os.environ["KUKAI_IR_CLASH"] = "1"
    try:
        CB._CACHE.clear()
        return CB.bundle_clash_report(pack, existing_run=existing_run)
    finally:
        if had:
            os.environ["KUKAI_IR_CLASH"] = before  # type: ignore[assignment]
        else:
            os.environ.pop("KUKAI_IR_CLASH", None)


class ТриИсходаРазличимы(unittest.TestCase):
    """The wave's main property: "did not look" ≠ "looked, clean" ≠ "found"."""

    def test_новое_тело_в_существующей_стене_даёт_находку(self):
        run = _run_dir([_wall("7240696", WALL_LO, WALL_HI)])
        block = _report(_pack(0.0), existing_run=run)

        self.assertTrue(block["compared_against"]["present"])
        self.assertGreaterEqual(len(block["findings"]), 1)
        # THE ADDRESS OF BOTH SIDES. A finding that names only our side does not
        # let the author fix it: they do not know WHAT they hit.
        text = json.dumps(block, ensure_ascii=False)
        self.assertIn("w1", text)
        self.assertIn(E.existing_source_id("7240696"), text)
        self.assertEqual(block["scope_id"], "bundle_vs_document")

    def test_то_же_тело_в_пустом_месте_находки_не_даёт(self):
        run = _run_dir([_wall("7240696", WALL_LO, WALL_HI)])
        block = _report(_pack(300000.0), existing_run=run)

        self.assertEqual(block["findings"], [])
        # AND THIS IS NOT THE SAME AS "DID NOT LOOK": the source was read, the
        # area is empty. The difference lives in the fields, not in tone.
        against = block["compared_against"]
        self.assertTrue(against["present"])
        self.assertEqual(against["bodies"], 0)
        self.assertGreaterEqual(against["scanned"], 1)

    def test_без_источника_отсутствие_НАЗЫВАЕТСЯ(self):
        block = _report(_pack(0.0), existing_run=None)

        against = block["compared_against"]
        self.assertFalse(against["present"])
        self.assertTrue(against["reason"])
        self.assertIn("НЕ ВИДИТ СТОЯЩЕЕ", block["message_ru"])


class ОбратныйКонтроль(unittest.TestCase):
    """Substituting emptiness for the standing building has no right to give a
    silent green.

    This is exactly the side the wave was made for: an empty report must
    carry WHAT it was compared against, otherwise it stays green with no
    distinguishing — just a wider one.
    """

    def test_пустой_разбор_отличим_от_отсутствующего(self):
        empty = _run_dir([])
        block = _report(_pack(0.0), existing_run=empty)
        against = block["compared_against"]
        # The source EXISTS and was read — there is simply nothing in it.
        self.assertTrue(against["present"])
        self.assertEqual(against["bodies"], 0)

        missing = _report(_pack(0.0), existing_run=None)["compared_against"]
        self.assertFalse(missing["present"])
        # The two answers must DIFFER. Equality here would mean the defect
        # came back under a new name.
        self.assertNotEqual(against["present"], missing["present"])

    def test_каталога_нет_это_названный_отказ_а_не_пустота(self):
        block = _report(_pack(0.0), existing_run="/нет/такого/каталога")
        against = block["compared_against"]
        self.assertFalse(against["present"])
        self.assertIn("каталога разбора нет", against["reason"])

    def test_разбор_без_L0_называет_именно_это(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="kir-no-l0-"))
        block = _report(_pack(0.0), existing_run=root)
        self.assertIn("нет L0.jsonl", block["compared_against"]["reason"])


class ЧислоПарТочноеИНеNone(unittest.TestCase):
    """`None`, read as zero, already produced "zero next to 58 280 findings".

    A filter by SOURCE does not reduce along the `(label, mvp_side)` classes,
    so `detect` honestly returns `eligible_pairs=None` for it, with a reason.
    The pair count is computed by a formula from two known counts — and must
    always be a number.
    """

    def test_число_пар_считается_формулой_и_совпадает(self):
        run = _run_dir([_wall(f"{7240696 + i}",
                              [WALL_LO[0], WALL_LO[1] + i, WALL_LO[2]],
                              [WALL_HI[0], WALL_HI[1] + i, WALL_HI[2]])
                        for i in range(3)])
        block = _report(_pack(0.0), existing_run=run)
        self.assertIsNotNone(block["pairs_compared"])
        self.assertEqual(
            block["pairs_compared"],
            E.pairs_compared(block["bodies_bundle"], block["bodies_existing"]))

    def test_формула_это_пары_внутри_плюс_перекрёстные(self):
        # 2 of ours + 3 standing: C(2,2)=1 internal plus 2*3=6 cross pairs.
        self.assertEqual(E.pairs_compared(2, 3), 7)
        self.assertEqual(E.pairs_compared(0, 5), 0)
        self.assertEqual(E.pairs_compared(1, 0), 0)


class ОбластьНичегоНеТеряет(unittest.TestCase):
    """A margin of 0 mm is not a threshold, it is a proven boundary.

    `overlap` requires signed_distance < 0, `contact` requires == 0; both
    require the bounding boxes to intersect. So an element outside the area
    cannot produce a finding, and dropping it is safe. The control checks
    BOTH directions: a neighboring element inside the area gets in, a
    distant one does not.
    """

    def test_элемент_вне_области_не_мог_бы_дать_находку(self):
        near = _wall("111", WALL_LO, WALL_HI)
        far = _wall("222", [WALL_LO[0] + 50000, WALL_LO[1], WALL_LO[2]],
                    [WALL_HI[0] + 50000, WALL_HI[1], WALL_HI[2]])
        run = _run_dir([near, far])
        block = _report(_pack(0.0), existing_run=run)
        # Exactly one is in the area: the distant one is dropped BEFORE the hull is built.
        self.assertEqual(block["compared_against"]["bodies"], 1)
        self.assertEqual(block["compared_against"]["scanned"], 2)

    def test_пустая_область_это_факт_о_НАШЕЙ_стороне(self):
        region = E.Region.around([])
        self.assertTrue(region.empty)
        loaded = E.load(_run_dir([_wall("1", WALL_LO, WALL_HI)]), region)
        self.assertFalse(loaded.present)
        self.assertIn("пачка не построила ни одного тела", loaded.reason)


class КасаниеИПрониканиеНеСмешаны(unittest.TestCase):
    """Contact accounts for up to a third of all pairs (7 804 versus 19 523 on
    one building). Adding them together means systematically overstating
    the number of conflicts."""

    def test_отношения_остаются_разными_ключами(self):
        self.assertIn("contact", D.HULL_RELATIONS)
        self.assertIn("overlap", D.HULL_RELATIONS)
        self.assertNotEqual("contact", "overlap")


class СтароеПоведениеЦело(unittest.TestCase):
    """The wave has no right to change the answer where no source was given."""

    def test_без_источника_область_прежняя(self):
        block = _report(_pack(0.0), existing_run=None)
        self.assertEqual(block["scope_id"], "all_physical_diagnostic")

    def test_пара_стоящее_на_стоящее_в_область_не_входит(self):
        a = type("R", (), {"source_id": E.existing_source_id("1")})()
        b = type("R", (), {"source_id": E.existing_source_id("2")})()
        mine = type("R", (), {"source_id": "w1"})()
        self.assertFalse(D.bundle_vs_document_pair_filter(a, b))
        self.assertTrue(D.bundle_vs_document_pair_filter(a, mine))
        self.assertTrue(D.bundle_vs_document_pair_filter(mine, mine))

    def test_область_названа_в_каноне(self):
        # The detector refuses an unknown filter, and that is its law: a report
        # that cannot name its coverage claims more than it searched.
        self.assertIn("bundle_vs_document", D.SCOPES)
        self.assertEqual(
            D.scope_id_of(D.bundle_vs_document_pair_filter),
            "bundle_vs_document")


class ИсточникВходитВКлючКэша(unittest.TestCase):
    """The same batch against a DIFFERENT building — a different answer."""

    def test_другой_источник_даёт_другой_ключ(self):
        pack = _pack(0.0)
        self.assertNotEqual(
            CB._cache_key(pack, None, None, "/a"),
            CB._cache_key(pack, None, None, "/b"))
        self.assertNotEqual(
            CB._cache_key(pack, None, None, None),
            CB._cache_key(pack, None, None, "/a"))


if __name__ == "__main__":
    unittest.main()


# ═════════════════════════════════════════════════════════════════════════
# WAVE B2 — THE DOOR IS OPEN: THE SOURCE RESOLVES ITSELF
#
# `existing_run` stopped being a parameter that nobody passes.
# A capability with no door is indistinguishable from a missing one — that is how `sdk.py` sat
# unused for 493 lines and five weeks. The door is here: `serving` names the turn's document
# (identity is known exactly where ground handed back a fingerprint), and resolving
# the source is done by `clash_bundle` itself.
# ═════════════════════════════════════════════════════════════════════════


def _corpus(runs: dict) -> pathlib.Path:
    """A corpus of decompiles on disk: a directory with `passport.json` and `L0.jsonl`."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="kir-corpus-"))
    for name, (doc_name, elements) in runs.items():
        run = root / name
        run.mkdir()
        (run / "passport.json").write_text(
            json.dumps({"doc_name": doc_name, "change_stamp": name},
                       ensure_ascii=False), encoding="utf-8")
        with (run / "L0.jsonl").open("w", encoding="utf-8") as handle:
            handle.write(json.dumps({"document": {"doc_name": doc_name}}) + "\n")
            for element in elements:
                handle.write(_l0_line(element) + "\n")
    return root


def _report_for_document(pack, title, corpus):
    """A report the way the live path receives it: the document is named, the path is not."""
    import os

    keys = ("KUKAI_IR_CLASH", E.DECOMPILE_ROOT_ENV)
    before = {k: os.environ.get(k) for k in keys}
    os.environ["KUKAI_IR_CLASH"] = "1"
    os.environ[E.DECOMPILE_ROOT_ENV] = str(corpus)
    try:
        CB._CACHE.clear()
        CB.remember_turn_document(title)
        return CB.bundle_clash_report(pack)      # existing_run is NOT passed
    finally:
        CB.remember_turn_document("")
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class ДверьОткрытаБезПараметра(unittest.TestCase):
    """The live path gets the comparison against the standing building without passing anything."""

    def test_источник_находится_по_заголовку_документа(self):
        corpus = _corpus({"run_a": ("Дом.rvt", [_wall("1", WALL_LO, WALL_HI)])})
        block = _report_for_document(_pack(0.0), "Дом.rvt", corpus)

        against = block["compared_against"]
        self.assertTrue(against["present"])
        self.assertEqual(against["source"], "run_a")
        self.assertGreaterEqual(len(block["findings"]), 1)

    def test_берётся_САМЫЙ_СВЕЖИЙ_разбор_документа(self):
        import os
        import time

        # 🔴 THE NAME AND THE TIME ARE DELIBERATELY PULLED APART, AND THIS IS NOT PEDANTRY.
        # The first edition named the runs "old"/"new": in Cyrillic
        # "new" < "old" alphabetically, so the first ALPHABETICALLY was also the freshest.
        # The mutation "take the first instead of the freshest" then did NOT turn red —
        # the control stood on a degenerate sample and pinned nothing. Here `aaa_*` comes
        # first alphabetically and LAST by time, so the two rules
        # are distinguishable.
        corpus = _corpus({
            "aaa_позавчерашний": ("Дом.rvt", [_wall("1", WALL_LO, WALL_HI)]),
            "zzz_сегодняшний": ("Дом.rvt", [_wall("2", WALL_LO, WALL_HI)]),
        })
        old = time.time() - 86400 * 30
        os.utime(corpus / "aaa_позавчерашний", (old, old))
        block = _report_for_document(_pack(0.0), "Дом.rvt", corpus)
        self.assertEqual(block["compared_against"]["source"],
                         "zzz_сегодняшний")

    def test_чужой_документ_корпуса_НЕ_берётся(self):
        """A name match is the only key, and it must DISTINGUISH."""
        corpus = _corpus({"чужой": ("Другой.rvt", [_wall("1", WALL_LO, WALL_HI)])})
        block = _report_for_document(_pack(0.0), "Дом.rvt", corpus)

        against = block["compared_against"]
        self.assertFalse(against["present"])
        self.assertIn("Дом.rvt", against["reason"])
        self.assertEqual(block["findings"], [])


class ТриИсходаДвериНедостижимыТихо(unittest.TestCase):
    """Every door refusal is NAMED. A silent fallback to comparing within the
    batch would open a door onto a wall: zero findings, and the reader would
    conclude it is clean."""

    def test_документ_не_назван(self):
        corpus = _corpus({"run_a": ("Дом.rvt", [_wall("1", WALL_LO, WALL_HI)])})
        block = _report_for_document(_pack(0.0), "", corpus)
        against = block["compared_against"]
        self.assertFalse(against["present"])
        self.assertIn("личность документа неизвестна", against["reason"])

    def test_корпуса_нет(self):
        block = _report_for_document(
            _pack(0.0), "Дом.rvt", pathlib.Path("/нет/корпуса"))
        self.assertIn("корпуса разборов нет",
                      block["compared_against"]["reason"])

    def test_каждый_отказ_попадает_в_текст_квитанции(self):
        corpus = _corpus({"чужой": ("Другой.rvt", [])})
        block = _report_for_document(_pack(0.0), "Дом.rvt", corpus)
        self.assertIn("НЕ ВИДИТ СТОЯЩЕЕ", block["message_ru"])


class СвежестьНеМолчит(unittest.TestCase):
    """A week-old decompile against today's document is a comparison against a
    PAST building. This cannot be done silently."""

    def test_находка_помечена_недоказанным_источником(self):
        corpus = _corpus({"run_a": ("Дом.rvt", [_wall("1", WALL_LO, WALL_HI)])})
        block = _report_for_document(_pack(0.0), "Дом.rvt", corpus)

        fresh = block["compared_against"]["freshness"]
        self.assertIsNotNone(fresh)
        self.assertFalse(fresh["proven"])
        self.assertEqual(fresh["matched_by"], "doc_title")
        self.assertIsNotNone(fresh["age_days"])
        self.assertIn("НЕ ДОКАЗАН", block["message_ru"])

    def test_причина_недоказуемости_названа_поимённо(self):
        """The reason must be NAMED and must DISTINGUISH cases.

        🔴 WHAT IS PINNED IS THE SUBJECT, NOT THE WORDING (fix of
        15.08.2026). The previous edition searched for the substring
        `project_uid` — and turned red when the passport LEARNED to carry
        identity and the phrase became more precise. A spelling test
        declares an improvement a breakage; what must be checked is that
        two DIFFERENT reasons for failing to prove give DIFFERENT answers.
        """
        old = _corpus({"r": ("Дом.rvt", [_wall("1", WALL_LO, WALL_HI)])})
        _run, _why, fresh = E.resolve_run("Дом.rvt", root=old)
        self.assertFalse(fresh.proven)
        self.assertTrue(fresh.why.strip(), "причина обязана быть названа")
        # the decompile was taken before the identity wave — and this is stated as a fact ABOUT US
        self.assertIn("паспорт", fresh.why)

        # A DIFFERENT reason for failing to prove: the decompile CARRIES identity, while the live
        # side is silent. This is a fact about OUR reading, not about the decompile's age, and the
        # phrase must be different — otherwise the field distinguishes nothing.
        import json as _json
        import pathlib as _pathlib
        import tempfile as _tempfile
        fresh_root = _pathlib.Path(_tempfile.mkdtemp())
        run_dir = fresh_root / "r"
        run_dir.mkdir()
        (run_dir / "L0.jsonl").write_text("{}", encoding="utf-8")
        (run_dir / "passport.json").write_text(_json.dumps({
            "doc_name": "Дом.rvt",
            "document_identity": {
                "source": "project_information_unique_id",
                "value": "UID-1"},
        }), encoding="utf-8")

        _r2, _w2, fresh2 = E.resolve_run("Дом.rvt", root=fresh_root)
        self.assertNotEqual(fresh.why, fresh2.why)

        # and a third: both sides named the same thing — stronger than a name, but
        # STILL not proof, because Save As carries the same value
        _r3, _w3, fresh3 = E.resolve_run(
            "Дом.rvt", root=fresh_root, project_uid="UID-1")
        self.assertFalse(fresh3.proven)
        self.assertEqual(fresh3.matched_by, "project_information_unique_id")
        self.assertNotIn(fresh3.why, (fresh.why, fresh2.why))

        # A MISMATCH is the only one-sidedly SOLID answer: a different file
        run4, why4, fresh4 = E.resolve_run(
            "Дом.rvt", root=fresh_root, project_uid="UID-ДРУГОЙ")
        self.assertIsNone(run4)
        self.assertIn("РАСХОЖДЕНИЮ", why4)

    def test_свидетельство_личности_обгоняет_свежесть(self):
        """THE STRONGEST EVIDENCE BEATS THE TIMESTAMP.

        🔴 This test was paid for by a mutation, not designed. The first
        edition simply took the freshest decompile, and a decompile WITHOUT
        identity beat a decompile with MATCHING lineage purely by the
        accident of write time. The behavior was fixed, but no guard was
        put in place — the mutation "rank is always 0" passed green on 24
        tests. What is pinned here is precisely the SELECTION ORDER.
        """
        import json as _json
        import os as _os
        import pathlib as _pathlib
        import tempfile as _tempfile
        import time as _time

        root = _pathlib.Path(_tempfile.mkdtemp())

        def _put(name, identity, age_days):
            d = root / name
            d.mkdir()
            (d / "L0.jsonl").write_text("{}", encoding="utf-8")
            row = {"doc_name": "Дом.rvt"}
            if identity:
                row["document_identity"] = identity
            (d / "passport.json").write_text(
                _json.dumps(row), encoding="utf-8")
            t = _time.time() - age_days * 86400
            _os.utime(d, (t, t))

        # the freshest one — WITHOUT identity; the kin is five days older
        _put("a_свежий_без_личности", None, 0)
        _put("b_родня_старее",
             {"source": "project_information_unique_id", "value": "UID-1"}, 5)

        run, why, fresh = E.resolve_run(
            "Дом.rvt", root=root, project_uid="UID-1")
        self.assertEqual(why, "")
        self.assertEqual(run.name, "b_родня_старее",
                         "родословная обязана обогнать более свежий разбор "
                         "без личности: иначе свидетельство проигрывает mtime")
        self.assertEqual(fresh.matched_by, "project_information_unique_id")

    def test_явный_путь_перевешивает_разрешение(self):
        """The admin door and the tests must be able to name the source themselves."""
        run = _run_dir([_wall("1", WALL_LO, WALL_HI)])
        block = _report(_pack(0.0), existing_run=run)
        self.assertTrue(block["compared_against"]["present"])
        # Resolution never ran — there is no freshness, and that is honest: the
        # source was named from outside, and we know nothing about its freshness.
        self.assertIsNone(block["compared_against"]["freshness"])


class ДешёвыйОтборНеТеряетРазбор(unittest.TestCase):
    """A PREFILTER ON THE L0 HEADER — a guard on the cost fix of 16.08.2026.

    🔴 WHY THIS CLASS. The resolver parsed ALL of the corpus's passports to
    take one string field: measured on a live corpus — 17.2 s per call, of
    which 13.2 s was `json.loads` over 918 MB, and the cost grew with the
    size of the BUILDING (the largest passport, 206 MB). Selecting
    candidates by the L0 header cut this to 2.05 s.

    A cost fix is more dangerous than a behavior fix: it is green exactly
    up to the input where the cheap source falls silent. So what is pinned
    is not the speedup but the BOUNDARY — "I don't know" must lead to the
    passport, not to rejection.
    """

    def _run_with(self, head_text: str, passport_name: str = "Дом.rvt"):
        root = pathlib.Path(tempfile.mkdtemp(prefix="kir-cheap-"))
        run = root / "r"
        run.mkdir()
        (run / "L0.jsonl").write_text(head_text, encoding="utf-8")
        (run / "passport.json").write_text(
            json.dumps({"doc_name": passport_name}, ensure_ascii=False),
            encoding="utf-8")
        return root

    def test_шапки_нет_разбор_всё_равно_находится(self):
        """An empty/broken header is "I don't know", and the passport must be read."""
        for head in ("{}", "", "не json вовсе", '{"document": 5}'):
            with self.subTest(head=head):
                root = self._run_with(head)
                run, why, _fresh = E.resolve_run("Дом.rvt", root=root)
                self.assertIsNotNone(
                    run, "разбор потерян на шапке %r: %s" % (head, why))

    def test_имя_в_шапке_расходится_с_паспортом_решает_паспорт(self):
        """The authority is the passport. The header only NARROWS, and has no right
        to decide.

        The mismatch does not reproduce today (52 of 52 matched), but it is
        possible tomorrow, and silently losing the decompile then would be
        the worst outcome.
        """
        root = self._run_with(
            json.dumps({"document": {"doc_name": "Дом.rvt"}}) + "\n",
            passport_name="Дом.rvt")
        run, _why, _fresh = E.resolve_run("Дом.rvt", root=root)
        self.assertIsNotNone(run)

    def test_чужое_имя_в_шапке_отсекается_без_чтения_паспорта(self):
        """And what it is all for: a foreign decompile is not worth parsing the passport AT ALL."""
        root = self._run_with(
            json.dumps({"document": {"doc_name": "Другой.rvt"}}) + "\n")
        (root / "r" / "passport.json").write_text(
            "ЭТО НЕ JSON — прочитан не будет", encoding="utf-8")
        run, why, _fresh = E.resolve_run("Другой.rvt", root=root)
        # The passport is broken: if it were read, the candidate would fall over with a ValueError
        # and the answer would be the same. So the OPPOSITE direction is checked —
        # its own header gets rejected by the header BEFORE the broken passport is read.
        self.assertIsNone(run)
        self.assertIn("Другой.rvt", why)

    def test_шапка_читается_без_чтения_всего_L0(self):
        """Only the FIRST line is read: the rest of the file is not touched at all."""
        root = self._run_with(
            json.dumps({"document": {"doc_name": "Дом.rvt"}}) + "\n"
            + "СТРОКА-КОТОРУЮ-НЕЛЬЗЯ-РАЗОБРАТЬ\n" * 100)
        self.assertEqual(E._doc_name_from_l0_head(root / "r" / "L0.jsonl"),
                         "Дом.rvt")
        run, _why, _fresh = E.resolve_run("Дом.rvt", root=root)
        self.assertIsNotNone(run)
