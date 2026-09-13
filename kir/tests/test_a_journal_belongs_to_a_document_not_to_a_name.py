"""THE JOURNAL BELONGS TO THE DOCUMENT, NOT TO ITS NAME.

🔴 BOUGHT BY THE OWNER'S LIVE REVIT ON 08.09.2026. The owner's word,
verbatim: «I opened a new Revit, I'm having a conversation, and it somehow
remembers about the сарай — that was in a different Revit a week ago.
Where did it get it from?» The backend log for that same turn:

    kir.live.journal: journal: поднято 194 программ со склада для ключа
    (<устройство>, 'Проект1')

`Проект1` is the default name of EVERY new Revit document. The live
journal's key was `(устройство, ИМЯ ДОКУМЕНТА)`, so a NEW EMPTY document
inherited 194 programs of SOMEONE ELSE'S building from a week earlier —
levels «KIR суд 1942», «Сарай», «Кровля сарая» — and on the request "make a
cube," the preview drew 98 elements of the wrong building.

WHY THIS CLASS IS COSTLIER THAN THE REST (and this has already been
recorded by its neighbor, `test_document_identity_is_not_the_device.py`):
every other failure in the tree is LOUD — a code, a cause, a next move. A
wrong-address error is the one and only kind that gives a confident,
correctly-looking answer ABOUT A DIFFERENT BUILDING. The same class had
already cost the tree the `S1_L1` record: A STABLE NAME, A DIFFERENT
REFERENT.

WHAT IS GUARDED HERE — four assertions, each by its own instrument:

  1. TWO DOCUMENTS WITH THE SAME NAME on one устройство do not share a
     journal;
  2. RE-OPENING THE SAME BUILDING (the same identity) the journal DOES
     FIND — otherwise the cure would cost the memory of the real building,
     that is, it would be worse than the disease;
  3. THE OLD STORE RECORD BY NAME (before 08.09.2026, without identity)
     gives a NAMED DIAGNOSIS with a number, not a silent raise;
  4. A MUTATION — reverting the key to by-name — must turn (1) red.

FAIL CONTROL RUN BY HAND: `_ЯДРО_КРАСНЕЕТ_ПРИ_ВОЗВРАТЕ_КЛЮЧА_ПО_ИМЕНИ`
substitutes `serving._turn_document_identity` with its previous behavior
(empty identity) and REQUIRES that the leak reproduce. Without this class
the file would be green both on the code before the fix and after — that
is, it would not be an instrument.
"""
from __future__ import annotations

import os
import pathlib
import tempfile
import unittest
from unittest import mock

from kir import ports
from kir import serving
from kir.live import journal as J
from kir.live import journal_store as S


# ── host doubles: exactly the fields that `serving` asks for ─────────────────
#
# The shape mirrors the REAL provider, not the reader's shape: a double
# that mirrors the reader's shape is green regardless of either side's value.
class _ХодОдногоДокумента:
    """Port `TURN_CONTEXT`: who selected the устройство and which window is declared."""

    def __init__(self, device: str, document: str) -> None:
        self._device = device
        self._document = document

    def get_active_device_id(self) -> str:
        return self._device

    def turn_document_title(self) -> str:
        return self._document


class _РеестрОдногоСокета:
    """Port `WS_REGISTRY`: one устройство, one socket, order is trivial."""

    def __init__(self, device: str, ws_id: str) -> None:
        self._device_websockets = {device: [ws_id]}

    @staticmethod
    def newest_first(items):
        return list(items)

    @staticmethod
    def ws_id_of(ws):
        return ws


class _КонтекстыСессий:
    """Port `SESSION_CONTEXTS`: what the plugin sent about its own window."""

    def __init__(self, contexts: dict) -> None:
        self._session_contexts = contexts


DEVICE = "устр-одноимённость"
DOC = "Проект1"
#: The real carrier of identity is the plugin's `document_key`
#: (`ExecutionContextGuard.ComputeDocumentKey`): sha256 of
#: `project-information:<UniqueId>` and `path:<PathName>`. Here there are
#: two DIFFERENT values precisely because the documents differ while their
#: name is the same.
KEY_САРАЙ = "a1b2c3d4e5f60718" + "0" * 48
KEY_ПУСТОЙ = "f0e1d2c3b4a59687" + "0" * 48


def _программа(n: int = 1) -> dict:
    return {"ops": [{"op": "create_level", "id": f"l{n}",
                     "name": f"Э{n}", "elev_mm": 3300 * n}]}


class _НаСвоёмХосте(unittest.TestCase):
    """A shared host double and shared cleanup — including the store and raise markers."""

    def setUp(self) -> None:
        for порт in (ports.TURN_CONTEXT, ports.WS_REGISTRY,
                     ports.SESSION_CONTEXTS):
            self.addCleanup(ports.unregister, порт)
        J.reset()
        J._RESTORE_TRIED.clear()
        self.addCleanup(J._RESTORE_TRIED.clear)
        self.addCleanup(J.reset)

    def _ключ_хода(self, *, document: str = DOC,
                   document_key: str = "",
                   document_path: str = "",
                   has_document: bool = True):
        """The live journal's key exactly as the REAL turn computes it."""
        ws_id = "ws-1"
        контекст = {
            "document_name": document,
            "has_document": has_document,
            "revit_version": "2026",
        }
        if document_path:
            контекст["document_path"] = document_path
        if document_key:
            контекст["execution_context"] = {"document_key": document_key}
        ports.register(ports.TURN_CONTEXT,
                       lambda: _ХодОдногоДокумента(DEVICE, document))
        ports.register(ports.WS_REGISTRY,
                       lambda: _РеестрОдногоСокета(DEVICE, ws_id))
        ports.register(ports.SESSION_CONTEXTS,
                       lambda: _КонтекстыСессий({ws_id: контекст}))
        return serving._turn_journal_key()


class ДваОдноимённыхДокументаНеДелятЖурнал(_НаСвоёмХосте):
    """(1) THE MAIN ASSERTION: `Проект1` and `Проект1` are not one document."""

    def test_the_programs_of_one_project1_are_invisible_to_another(self) -> None:
        сарай = self._ключ_хода(document_key=KEY_САРАЙ)
        J.append(сарай, _программа(1), source="test")
        J.append(сарай, _программа(2), source="test")

        пустой = self._ключ_хода(document_key=KEY_ПУСТОЙ)
        self.assertNotEqual(
            сарай, пустой,
            "два РАЗНЫХ документа с именем «Проект1» получили ОДИН ключ — "
            "новый пустой документ унаследует чужое здание")

        сессия = J.get(пустой)
        держит = 0 if сессия is None else len(сессия.records)
        self.assertEqual(
            держит, 0,
            f"новый документ «{DOC}» видит {держит} программ ДРУГОГО "
            "документа с тем же именем — это и есть утечка памяти между "
            "документами (живьём: 194 программы, 98 чужих элементов)")

        свой = J.get(сарай)
        self.assertIsNotNone(свой, "журнал СВОЕГО документа потерян")
        self.assertEqual(len(свой.records), 2)

    def test_the_key_still_shows_the_human_name_first(self) -> None:
        """The name remains READABLE: the key travels into the log and into the receipt.

        Without this, the cure would buy a second disease: a person would
        stop recognizing their own document in the line «поднято N программ
        для ключа …».
        """
        ключ = self._ключ_хода(document_key=KEY_САРАЙ)
        self.assertEqual(J.document_name_of(ключ[1]), DOC)
        self.assertTrue(J.document_identity_of(ключ[1]).startswith("dk:"))
        self.assertTrue(ключ[1].startswith(DOC),
                        f"ключ «{ключ[1]}» не начинается с имени документа")

    def test_a_path_identifies_a_saved_document_when_the_plugin_is_old(self) -> None:
        """The old plugin does not send `document_key` — but it does have a path."""
        a = self._ключ_хода(document_path=r"C:\\стройка\\Сарай.rvt")
        b = self._ключ_хода(document_path=r"C:\\стройка\\Куб.rvt")
        self.assertNotEqual(a, b, "путь не различил два документа")
        self.assertTrue(J.document_identity_of(a[1]).startswith("path:"))

    def test_a_turn_without_any_identity_keeps_the_old_key(self) -> None:
        """A NAMED LIMIT: no identity — the old by-name key.

        This is not a relaxation but honesty: the chat path without Revit
        and a standalone KIR existed even before the fix, and a turn has no
        right to fail because of the showroom. The same-name collision is
        then NOT cured — and the journal says so out loud with the
        `FOREIGN_JOURNAL_REFUSAL` refusal, not with silence.
        """
        ключ = self._ключ_хода()
        self.assertEqual(ключ, (DEVICE, DOC))
        self.assertEqual(J.document_identity_of(ключ[1]), "")


class ПереоткрытоеЗданиеНаходитСвойЖурнал(_НаСвоёмХосте):
    """(2) THE CURE HAS NO RIGHT TO COST THE MEMORY OF THE REAL BUILDING."""

    def test_the_same_document_reopened_keeps_its_journal(self) -> None:
        сначала = self._ключ_хода(document_key=KEY_САРАЙ)
        J.append(сначала, _программа(1), source="test")

        # "Reopened" — a new socket, a new turn, THE SAME document: the
        # plugin's `document_key` is computed from
        # `ProjectInformation.UniqueId` and the path, and reopening does not
        # change it (unlike `document_instance_key`, which lives for a
        # single session).
        снова = self._ключ_хода(document_key=KEY_САРАЙ)
        self.assertEqual(сначала, снова,
                         "переоткрытое ТО ЖЕ здание получило другой ключ — "
                         "его журнал потерян")
        сессия = J.get(снова)
        self.assertIsNotNone(сессия)
        self.assertEqual(len(сессия.records), 1)


class _СоСтарымСкладом(_НаСвоёмХосте):
    """A base with its OWN store on disk. Deliberately carries no tests.

    The classes that need a store became four, and inheriting for the
    fixture's sake from a class WITH TESTS reruns someone else's assertions
    as many times as it has descendants — and the report's numbers stop
    meaning anything.
    """

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = pathlib.Path(self._tmp.name) / "kir_programs.jsonl"
        патч = mock.patch.dict(os.environ, {S.PATH_ENV: str(self.store)})
        патч.start()
        self.addCleanup(патч.stop)

    def _положить_старые(self, сколько: int) -> None:
        """Write the store EXACTLY AS THE PRE-08.09.2026 VERSION WROTE IT.

        Through the store's real door, not by hand-writing JSON: a
        hand-written line would test my own parsing, not format
        compatibility.
        """
        старый_ключ = (DEVICE, DOC)
        for i in range(сколько):
            S.record_program(старый_ключ, J.ProgramRecord(
                seq=i, ts=0.0,
                ops=({"op": "create_level", "id": f"стар{i}",
                      "name": "Сарай", "elev_mm": 0},)))

class СтараяЗаписьСкладаНазываетсяАНеПоднимается(_СоСтарымСкладом):
    """(3) STORE COMPATIBILITY: a diagnosis with a number, not 194 programs."""

    def test_a_by_name_record_is_named_not_lifted(self) -> None:
        self._положить_старые(194)
        ключ = self._ключ_хода(document_key=KEY_ПУСТОЙ)

        итог = J.restore(ключ)
        self.assertEqual(
            итог.get("refused"), J.FOREIGN_JOURNAL_REFUSAL,
            f"подъём не назвал одноимённый чужой журнал: {итог}")
        self.assertEqual(итог.get("restored"), 0,
                         "чужие программы ПОДНЯТЫ — это дефект целиком")
        self.assertEqual(итог.get("programs_by_name"), 194,
                         "диагноз без числа не даёт человеку решения")
        self.assertEqual(итог.get("document_name"), DOC)
        self.assertTrue(итог.get("next_step_ru"),
                        "диагноз без следующего хода — половина отказа")

    def test_the_diagnosis_reaches_the_receipt_not_only_the_log(self) -> None:
        """The receipt, not a debug log: "programs 0" is otherwise indistinguishable."""
        self._положить_старые(3)
        ключ = self._ключ_хода(document_key=KEY_ПУСТОЙ)
        J.append(ключ, _программа(1), source="test")

        диагноз = serving._journal_restore_diagnosis()
        self.assertIsNotNone(
            диагноз, "квитанция не узнала, что одноимённый журнал не поднят")
        self.assertEqual(диагноз.get("refused"), J.FOREIGN_JOURNAL_REFUSAL)
        self.assertEqual(диагноз.get("programs_by_name"), 3)

        # THROUGH THE SINGLE OUTCOME FUNNEL, not around it: what is proven
        # is that the field reaches the RECEIPT, not merely exists as a
        # function.
        квитанция = serving._with_outcome(
            {"ok": True, "held_in_kir": True},
            serving.program_not_started())
        self.assertEqual(
            (квитанция.get("journal_restore") or {}).get("refused"),
            J.FOREIGN_JOURNAL_REFUSAL,
            f"поле `journal_restore` не доехало до квитанции: {квитанция}")

    def test_its_own_record_with_identity_is_lifted_as_before(self) -> None:
        """THE RAISE IS NOT BROKEN: one's own record with identity is raised."""
        ключ = self._ключ_хода(document_key=KEY_САРАЙ)
        for i in range(2):
            S.record_program(ключ, J.ProgramRecord(
                seq=i, ts=0.0,
                ops=({"op": "create_level", "id": f"свой{i}",
                      "name": "Э", "elev_mm": 0},)))
        J.reset()
        итог = J.restore(ключ)
        self.assertEqual(итог.get("restored"), 2,
                         f"свой журнал не поднялся: {итог}")


class УспешныйПодъёмНеМолчитОСоседеПоИмени(_СоСтарымСкладом):
    """"Not done" item #1 of wave 9: raising ONE'S OWN journal stayed silent
    about a by-name pile.

    The diagnosis was only computed when there are NO records of one's own
    in the store (`if not raw`). So a person whose document had already
    moved to identity would see "raised 7" and not know that 194 programs
    from their previous session lay right next to it and were NOT raised —
    that is, "the building is incomplete" was indistinguishable from "the
    building was always like this." This is the same indistinguishable zero
    for whose prohibition the whole fix was written.
    """

    def test_a_successful_restore_still_counts_the_by_name_pile(self) -> None:
        self._положить_старые(194)
        ключ = self._ключ_хода(document_key=KEY_САРАЙ)
        for i in range(7):
            S.record_program(ключ, J.ProgramRecord(
                seq=i, ts=0.0,
                ops=({"op": "create_level", "id": f"свой{i}",
                      "name": "Э", "elev_mm": 0},)))
        J.reset()

        итог = J.restore(ключ)
        self.assertEqual(7, итог.get("restored"), f"свой журнал: {итог}")
        self.assertEqual(
            194, итог.get("programs_by_name"),
            "успешный подъём смолчал о 194 программах ПО ИМЕНИ рядом")
        self.assertEqual(DOC, итог.get("document_name"))
        self.assertTrue(итог.get("next_step_ru"),
                        "число без причины не даёт человеку решения")

    def test_no_neighbour_is_an_answer_too_not_a_missing_field(self) -> None:
        """CONTROL: zero here is the FACT "there is nothing nearby," not a
        missing field.

        Without this, "did not look" and "looked and found nothing" would
        be indistinguishable — the named class of this tree.
        """
        ключ = self._ключ_хода(document_key=KEY_САРАЙ)
        S.record_program(ключ, J.ProgramRecord(
            seq=0, ts=0.0, ops=({"op": "create_level", "id": "s",
                                 "name": "Э", "elev_mm": 0},)))
        J.reset()
        итог = J.restore(ключ)
        self.assertEqual(1, итог.get("restored"))
        self.assertIn("programs_by_name", итог)
        self.assertEqual(0, итог.get("programs_by_name"))

    def test_the_receipt_carries_the_neighbour_after_a_success(self) -> None:
        """Through the SINGLE outcome funnel, not around it."""
        self._положить_старые(194)
        ключ = self._ключ_хода(document_key=KEY_САРАЙ)
        S.record_program(ключ, J.ProgramRecord(
            seq=0, ts=0.0, ops=({"op": "create_level", "id": "s",
                                 "name": "Э", "elev_mm": 0},)))
        J.reset()
        J._RESTORE_TRIED.clear()
        J.append(ключ, _программа(9), source="test")

        диагноз = serving._journal_restore_diagnosis()
        self.assertIsNotNone(диагноз, "квитанция не узнала о куче по имени")
        self.assertEqual(194, диагноз.get("programs_by_name"))
        self.assertIsNone(диагноз.get("refused"),
                          "свой журнал поднялся — отказа тут быть не должно")

        квитанция = serving._with_outcome(
            {"ok": True, "held_in_kir": True},
            serving.program_not_started())
        self.assertEqual(
            194, (квитанция.get("journal_restore") or {}).get(
                "programs_by_name"),
            f"поле не доехало до квитанции: {квитанция}")

    def test_the_diagnosis_becomes_one_russian_line_for_a_human(self) -> None:
        """A field nobody unpacks is the instrument's own journal."""
        from kir.preview import journal_note_ru

        self._положить_старые(194)
        ключ = self._ключ_хода(document_key=KEY_ПУСТОЙ)
        J.append(ключ, _программа(1), source="test")

        строка = journal_note_ru(serving._journal_restore_diagnosis())
        self.assertIn("194", строка)
        self.assertIn("НЕ подняты", строка)
        for слово in ("refused", "programs_by_name", "journal_of_another"):
            self.assertNotIn(слово, строка, f"{слово!r} в строке человека")

    def test_the_refusal_name_has_exactly_one_meaning_on_both_sides(self) -> None:
        """`preview` lives without `live`, so the refusal's name is
        repeated there.

        The repetition is deliberate (the drawer importing the live
        journal would break the boundary and the clean install), and so it
        is guarded by equality, not by hope.
        """
        from kir.preview import FOREIGN_JOURNAL_REFUSAL_RU_KEY

        self.assertEqual(J.FOREIGN_JOURNAL_REFUSAL,
                         FOREIGN_JOURNAL_REFUSAL_RU_KEY)


class СверкаТождестваСМостом(_НаСвоёмХосте):
    """"Not done" item #5 of wave 9: the socket's `dk:` was not checked
    against the bridge's identity.

    Verbatim: «After grounding, the turn has `project_uid` in hand — the
    document's exact identity. There is nothing to check it against the
    `dk:` from the socket's context with, and the mismatch today STAYS
    SILENT». It stays silent exactly where the error does not look like an
    error: the journal and preview are kept for the WINDOW's document,
    while the program writes into the document the BRIDGE read.
    """

    ПУТЬ = r"C:\стройка\Сарай.rvt"

    def _мост(self, *, title="Проект1", path_name="", uid="uid-1"):
        from kir.contracts import DocumentFingerprint

        return DocumentFingerprint(title=title, path_name=path_name,
                                   project_uid=uid)

    def test_a_different_path_is_named_not_swallowed(self) -> None:
        self._ключ_хода(document_key=KEY_САРАЙ, document_path=self.ПУТЬ)
        итог = serving._document_identity_crosscheck(
            self._мост(path_name=r"C:\стройка\ДРУГОЙ.rvt", uid="uid-2"))
        self.assertIsNotNone(итог, "сверка промолчала при обеих сторонах")
        self.assertFalse(итог["agree"])
        self.assertEqual("document_path", итог["checked"])
        self.assertEqual(serving.DOCUMENT_IDENTITY_MISMATCH, итог["refused"])
        self.assertIn("РАЗНЫЕ", итог["message_ru"])

    def test_the_same_document_agrees_across_separators_and_case(self) -> None:
        """A separator and case do NOT make the document a different one — same as for the plugin."""
        self._ключ_хода(document_key=KEY_САРАЙ, document_path=self.ПУТЬ)
        итог = serving._document_identity_crosscheck(
            self._мост(path_name="c:/СТРОЙКА/Сарай.rvt"))
        self.assertTrue(итог["agree"], итог)
        self.assertIsNone(итог.get("refused"))

    def test_nothing_to_compare_is_not_agreement(self) -> None:
        """A silent "yes" here would be the same defect as a silent "no"."""
        self._ключ_хода(document_key=KEY_САРАЙ)
        self.assertIsNone(serving._document_identity_crosscheck(
            self._мост(title="", path_name="")))

    def test_the_mismatch_reaches_the_receipt_body_in_russian(self) -> None:
        """Not into the log: the held receipt is the only thing a person reads."""
        self._ключ_хода(document_key=KEY_САРАЙ, document_path=self.ПУТЬ)
        программа = {"ir_version": "1.0", "ops": [
            {"op": "create_level", "id": "L1", "name": "Уровень 1",
             "elev_mm": 0}]}
        квитанция = serving._held_receipt(
            программа, ops=1,
            document_fingerprint=self._мост(
                path_name=r"C:\стройка\ДРУГОЙ.rvt", uid="uid-2"))
        self.assertEqual(serving.DOCUMENT_IDENTITY_MISMATCH,
                         квитанция["document_identity"]["refused"])
        self.assertIn("РАЗНЫЕ документы", квитанция["message_ru"])
        # As the LAST line, not the first: a person reads the subject of
        # the request first, in this receipt too.
        строки = квитанция["message_ru"].splitlines()
        self.assertIn("ВНИМАНИЕ", строки[-1])
        self.assertNotIn("ВНИМАНИЕ", строки[0])


class _ЯДРО_КРАСНЕЕТ_ПРИ_ВОЗВРАТЕ_КЛЮЧА_ПО_ИМЕНИ(_НаСвоёмХосте):
    """(4) MUTATION: restore the old rule — and the leak must return.

    Without this class the file would have been green even before the
    fix: it proves that the green in (1) is bought PRECISELY by the
    document's identity, and not by the two calls to the double happening
    to give different values.
    """

    def test_a_key_by_name_alone_leaks_the_other_document(self) -> None:
        with mock.patch.object(serving, "_turn_document_identity",
                               return_value=""):
            сарай = self._ключ_хода(document_key=KEY_САРАЙ)
            J.append(сарай, _программа(1), source="test")
            пустой = self._ключ_хода(document_key=KEY_ПУСТОЙ)

            self.assertEqual(
                сарай, пустой,
                "мутация не воспроизвела прежнее правило — прибор не может "
                "покраснеть и потому ничего не охраняет")
            сессия = J.get(пустой)
            self.assertIsNotNone(сессия)
            self.assertEqual(
                len(сессия.records), 1,
                "прежний ключ по имени НЕ дал утечки — значит зелёный цвет "
                "остальных классов куплен не тождеством документа")


class _ДИАГНОЗ_КРАСНЕЕТ_ПРИ_СЧЁТЕ_ТОЛЬКО_НА_ПУСТОМ(_СоСтарымСкладом):
    """MUTATION #2: restore the old condition — and the by-name neighbor goes mute again.

    The previous version counted the by-name pile only via `if not raw`.
    Here the same thing is reproduced by substituting
    `document_identity_of` with an empty value when one's own journal is
    NOT EMPTY: the count must vanish, otherwise the green of
    `УспешныйПодъёмНеМолчитОСоседеПоИмени` is not bought by this fix.
    """

    def test_without_the_identity_the_neighbour_cannot_be_counted(self) -> None:
        self._положить_старые(194)
        ключ = self._ключ_хода(document_key=KEY_САРАЙ)
        S.record_program(ключ, J.ProgramRecord(
            seq=0, ts=0.0, ops=({"op": "create_level", "id": "s",
                                 "name": "Э", "elev_mm": 0},)))
        J.reset()
        with mock.patch.object(J, "document_identity_of", return_value=""):
            итог = J.restore(ключ)
        self.assertEqual(1, итог.get("restored"))
        self.assertEqual(
            0, итог.get("programs_by_name"),
            "счёт соседа выжил без тождества — значит он считается не там, "
            "где объявлен, и прибор ничего не охраняет")


if __name__ == "__main__":
    unittest.main()
