"""Общий улов ``sketch_extract`` называет ГРАНИЦУ ОХВАТА, а не отсутствие.

Замер, из которого тест родился (12.08.2026, `backend/data/decompile/k2_ar_rd_v7`):
общий улов стадии слал `element_unresolved` — код, чей контракт объявляет «id не
нашёлся В ДОКУМЕНТЕ… мог прийти из чужого разбора». Сверка с L0 ТОГО ЖЕ прогона
дала обратное:

    173 id с element_unresolved  →  найдены в L0 ВСЕ 173 из 173
    контроль-PASS  8 настоящих id из profile_index  →  8 из 8
    контроль-FAIL  5 выдуманных id                  →  0 из 5

то есть прибор различает, а элементы существуют — стадия их просто не читает.
Из 173: **172 × OST_StairsRailing** (категория ЗАПРОШЕННАЯ, у которой 31 элемент
получал честную квитанцию `profile_not_single_closed`) и 1 × OST_Floors. Одна
категория, две квитанции, и вторая говорила неправду о первой.

Цена двусмысленности измерена не рассуждением: ДВА читателя вывели по этому коду
ПРОТИВОПОЛОЖНОЕ, каждый верно относительно своего источника — один читал
контракт («нет в документе»), другой производителя («не читаю»). Разошлись
АВТОРИТЕТ и ПРОИЗВОДИТЕЛЬ, а не два невнимательных человека.

Почему НЕ двинута `PROFILE_INDEX_SCHEMA_VERSION`: несовпадение версии бросает
`SketchPayloadError` (`sketch_extract.py:838`), то есть бамп сделал бы
нечитаемыми все существующие индексы разом. Форма разделения взята у прецедента
`HOST_KIND_UNRESOLVED`: старый код ОСТАЁТСЯ объявленным ради артефактов, снятых
до разделения, и новые разборы его в этом месте не пишут. Старый паспорт от
нового отличается по построению — новый код в старых артефактах не встречается
вовсе.
"""

import unittest

from kukai.ir.decompile.side_contract import (
    SIDE_FAILURE_KINDS,
    SideFailureKind,
    SideFailureReason,
)
from kukai.ir.decompile.sketch_extract import build_sketch_extract_cs


class SketchScopeReceiptTest(unittest.TestCase):

    def _body(self) -> str:
        return build_sketch_extract_cs(["11", "22"])

    def test_catch_all_names_the_scope_boundary(self) -> None:
        """КОНТРОЛЬ-PASS: общий улов пишет `element_not_claimed`."""
        self.assertIn('"element_not_claimed"', self._body())

    def test_catch_all_no_longer_claims_absence_from_the_document(self) -> None:
        """КОНТРОЛЬ-FAIL: возврат старого кода в ОБЩЕМ УЛОВЕ роняет тест.

        Различающее утверждение: `element_unresolved` не должен стоять рядом с
        `__skSeen.Contains` — это и есть площадка общего улова. Проверяем не
        отсутствие строки во всём теле (стадия вправе писать её там, где id
        действительно не нашёлся в документе), а отсутствие ИМЕННО в улове.
        """
        body = self._body()
        marker = "__skSeen.Contains"
        self.assertIn(marker, body, "площадка общего улова исчезла из эмиссии")
        tail = body[body.index(marker):]
        self.assertNotIn(
            '"element_unresolved"', tail,
            "общий улов снова заявляет отсутствие в документе вместо границы охвата")

    def test_the_new_reason_is_classified(self) -> None:
        """Словарь классов полон по построению — новая причина обязана быть в нём."""
        self.assertEqual(
            SIDE_FAILURE_KINDS[SideFailureReason.ELEMENT_NOT_CLAIMED],
            SideFailureKind.CUT)

    def test_the_old_reason_stays_declared_for_pre_split_artefacts(self) -> None:
        """61 сохранённый индекс несёт старый код — он обязан остаться читаемым."""
        self.assertEqual(
            SideFailureReason.ELEMENT_UNRESOLVED.value, "element_unresolved")
        self.assertIn(SideFailureReason.ELEMENT_UNRESOLVED, SIDE_FAILURE_KINDS)


if __name__ == "__main__":
    unittest.main()
