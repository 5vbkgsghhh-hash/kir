"""§18.1 — закон переписи: бухгалтерия документа обязана сходиться.

    |элементов в документе| = поднято_в_опы
                            + атомов (каждый с типизированной причиной)
                            + не_читалось (каждая строка с типизированной
                              причиной)

До этой волны знаменатель любого процента покрытия был ВЫБОРКОЙ: extract
читает закрытую таблицу из 47 категорий, и всё, чего в таблице нет, не давало
ни элемента, ни строки статуса, ни отказа (находка M3 аудита 2026-07-28). Нет
топографии, площадки, паркинга, озеленения, масс, арматуры, изоляции — а
«покрытие 93%» считалось от того, что увидели, и молчало о том, чего не
смотрели вовсе.

Перепись (``L0Document.census``) — один дешёвый полномодельный проход
``FilteredElementCollector(doc).WhereElementIsNotElementType()``, ключуемый
BuiltInCategory (§18.5: локализованное имя — только справочная колонка). Этот
модуль сводит её с тем, что реально извлеклось, и раскладывает разницу по
типизированным причинам.

Направление расхождения не симметрично, и это главное решение модуля:

* НЕДОБОР (перепись > извлечено) — это НЕ ошибка, это и есть ``не_читалось``;
  каждая такая строка получает типизированную причину;
* ПЕРЕБОР (извлечено > переписи) — утверждение «прочитано элементов больше,
  чем их есть в документе». Опровержимо и всегда дефект: типизированная
  ошибка прогона, а не предупреждение (§18.1).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .schema import CategoryState, L0Document


# Ключ переписи для элемента без категории. Не «прочее» и не пустая строка:
# отсутствие категории — это факт о документе (виды, листы, служебные
# элементы), и он обязан быть счётным, а не растворяться.
NO_CATEGORY_KEY = "no_category"

# Обращение к ``Element.Category`` БРОСИЛО. До 12.08.2026 такой элемент падал
# в ``no_category`` вместе с настоящими бескатегорийными: `catch { }` в
# переписи (`extract.py`) превращал отказ ПРИБОРА в ИЗМЕРЕНИЕ — форма 3
# канона. Цена измерена: на башне `k2_ar_rd_v7` ключ `no_category` несёт
# 53 896 элементов = 17.35% документа, и сколько из них какого рода, из
# артефактов узнать было НЕЛЬЗЯ: ключ один.
#
# Ключи разделены, и это разные предметы с разными лекарствами:
#   no_category          — факт о МОДЕЛИ: у элемента нет категории у Ревита.
#                          Таблицей извлечения не лечится вовсе, потому что
#                          таблица ключуется КАТЕГОРИЕЙ (граница архитектуры).
#   category_read_failed — факт о НАШЕМ чтении: спросить не удалось.
#
# Старые артефакты нового ключа не несут — 77 сохранённых прогонов сняты до
# разделения, и их `no_category` остаётся суммой обоих родов. Различимость
# по построению, без версии схемы: ключа, которого нет, не спутать.
CATEGORY_READ_FAILED_KEY = "category_read_failed"

# Сколько строк «не читалось» печатается поимённо; остальное сворачивается в
# остаток с сохранением ОБОИХ чисел (сколько категорий и сколько элементов) —
# усечённый хвост, о размере которого не сказано, был бы тем же умолчанием,
# ради запрета которого закон и заведён.
TOP_N = 8


class UnscannedReason(str, Enum):
    """Закрытый словарь причин, по которым элемент не был прочитан."""

    # Категории нет в таблице извлечения вообще: элемент невидим для чтения.
    CATEGORY_OUTSIDE_TABLE = "category_outside_table"
    # Категория в таблице, но её страница/зонд отказали (CategoryState.PARTIAL).
    PAGE_REFUSED = "page_refused"
    # Категория в таблице, статус complete, а элементов пришло меньше, чем
    # насчитала перепись. Причина известна не всегда (закрытые рабочие наборы,
    # подкласс, который не берёт коллектор, фильтр DirectShape), поэтому она
    # названа своим именем — «прочитано меньше», — а не подставлена догадкой
    # из словаря §18.1. Догадка тут была бы тем же дефектом, что и бюджет,
    # срезающий элементы молча.
    CATEGORY_SHORT_READ = "category_short_read"


class CensusBalanceError(str, Enum):
    """Типизированные ошибки тождества (§18.1: ошибка прогона, не warning)."""

    EXTRACTED_EXCEEDS_CENSUS = "extracted_exceeds_census"
    CENSUS_TOTAL_MISMATCH = "census_total_mismatch"


@dataclass(frozen=True, slots=True)
class UnscannedRow:
    """Одна строка «не читалось» с типизированной причиной."""

    category: str
    census_count: int
    extracted_count: int
    unscanned: int
    reason: UnscannedReason
    category_ru: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "category_ru": self.category_ru,
            "census_count": self.census_count,
            "extracted_count": self.extracted_count,
            "unscanned": self.unscanned,
            "reason": self.reason.value,
        }


@dataclass(frozen=True, slots=True)
class CensusBalance:
    """Сведённая бухгалтерия одного прогона.

    ``present=False`` означает, что перепись НЕ ПРОВОДИЛАСЬ (замороженный L0,
    снятый до этой волны, либо мост, который её не вернул). Это честная
    деградация: числа отсутствуют, а не подменяются нулями, и любой процент
    обязан печататься с оговоркой «знаменателя документа нет».
    """

    present: bool
    census_total: int
    extracted: int
    unscanned: int
    categories_in_model: int
    categories_scanned: int
    rows: tuple[UnscannedRow, ...] = ()
    errors: tuple[dict[str, Any], ...] = ()

    @property
    def balanced(self) -> bool:
        return not self.errors

    def document_pct(self, lifted: int) -> float | None:
        """Процент от ВСЕГО документа (знаменатель — перепись), либо None."""
        if not self.present or self.census_total <= 0:
            return None
        return round(100.0 * lifted / self.census_total, 2)

    def extracted_pct(self, lifted: int) -> float | None:
        """Процент от ПРОЧИТАННОГО — историческая база, оставлена явно."""
        if self.extracted <= 0:
            return None
        return round(100.0 * lifted / self.extracted, 2)

    def top_rows(self, top_n: int = TOP_N) -> tuple[UnscannedRow, ...]:
        return self.rows[:top_n]

    def by_category_dict(self, top_n: int = TOP_N) -> dict[str, Any]:
        top = self.top_rows(top_n)
        rest = self.rows[top_n:]
        return {
            "top": [row.to_dict() for row in top],
            "other_categories": len(rest),
            "other_elements": sum(row.unscanned for row in rest),
        }

    def to_dict(self, top_n: int = TOP_N) -> dict[str, Any]:
        return {
            "census_present": self.present,
            "census_total": self.census_total,
            "extracted": self.extracted,
            "unscanned_elements": self.unscanned,
            "categories_in_model": self.categories_in_model,
            "categories_scanned": self.categories_scanned,
            "unscanned_by_category": self.by_category_dict(top_n),
            "census_balanced": self.balanced,
            "census_balance_errors": [dict(error) for error in self.errors],
        }

    def summary_ru(self, top_n: int = 3) -> str:
        """Человекочитаемая строка §18.1 — печатается ПЕРЕД процентами."""
        if not self.present:
            return ("переписи нет в этом L0 (снят до §18.1) — знаменателя "
                    "документа не существует, проценты ниже считаны от "
                    "ПРОЧИТАННОГО")
        head = (f"категорий в модели {self.categories_in_model}, "
                f"читается {self.categories_scanned}; "
                f"не читалось {self.unscanned} элементов "
                f"из {self.census_total}")
        top = [row for row in self.top_rows(top_n) if row.unscanned]
        if not top:
            return head
        listed = ", ".join(
            f"{row.category} {row.unscanned}" for row in top)
        rest = self.rows[top_n:]
        tail = sum(row.unscanned for row in rest)
        if tail:
            listed += f", прочие {len(rest)} категорий {tail}"
        return f"{head} (топ: {listed})"


def _extract_table() -> frozenset[str]:
    # Импорт внутри функции: extract.py — самый тяжёлый модуль пакета, а этот
    # используется и офлайн-инструментами, которым мост не нужен.
    from .extract import EXTRACT_CATEGORIES

    return frozenset(EXTRACT_CATEGORIES)


def _table_of_this_document(document: L0Document) -> frozenset[str]:
    """Таблица чтения ТОГО поколения, которым снят этот документ.

    Берётся из самого потока: ``category_status`` пишется ровно по одной
    строке на категорию таблицы, поэтому список статусов И ЕСТЬ таблица
    прогона — без обращения к ``extract.py`` и без догадок о поколении.

    ЗАЧЕМ, а не «сегодняшняя таблица». Причина «не читалось» обязана
    описывать ТОТ прогон. 29.07 таблица выросла 54 -> 73; со сегодняшней
    таблицей все 19 новых категорий старого слепка получали бы
    ``category_short_read`` — «извлечение читало и недочитало», — то есть
    слепку приписывался бы отказ, которого он не совершал, и вместо роста
    таблицы в отчёте виднелась бы деградация чтения. Правильный ответ ровно
    один: этих категорий в таблице ТОГДА не было.

    Пустой список статусов — не «таблица пуста»: так выглядит документ,
    собранный в обход потока (фикстуры, materialize без статусов). Тогда
    сведений о таблице у нас нет вовсе, и остаётся сегодняшняя — но это
    ЯВНЫЙ откат, а не тихая подстановка.
    """
    visited = frozenset(status.category for status in document.category_status)
    return visited or _extract_table()


def reconcile_census(
    document: L0Document,
    *,
    table: frozenset[str] | None = None,
) -> CensusBalance:
    """Свести перепись документа с тем, что реально извлеклось.

    ``table`` — множество категорий, которые извлечение умело читать В МОМЕНТ
    СЪЁМКИ этого документа. По умолчанию берётся из самого потока (см.
    :func:`_table_of_this_document`), а не из сегодняшнего
    ``EXTRACT_CATEGORIES``: правило обязано мерить слепок его собственной
    таблицей, иначе рост таблицы задним числом переписывает причины отказов в
    уже снятых слепках. Явный аргумент по-прежнему главнее — он существует
    ради тестов и чужой сборки с другой таблицей.
    """

    known = _table_of_this_document(document) if table is None else table
    extracted_by_category: dict[str, int] = {}
    for element in document.elements:
        extracted_by_category[element.category] = (
            extracted_by_category.get(element.category, 0) + 1)
    extracted_total = len(document.elements)

    if not document.census:
        # Честная деградация: без переписи нет ни знаменателя, ни строк
        # «не читалось». Ноль здесь означал бы «не читалось ничего», то есть
        # ровно ту тихую 100%-ю ложь, которую §18.1 запрещает.
        return CensusBalance(
            present=False,
            census_total=0,
            extracted=extracted_total,
            unscanned=0,
            categories_in_model=0,
            categories_scanned=0,
        )

    status_by_category: dict[str, CategoryState] = {
        status.category: status.state for status in document.category_status}

    census_by_key = {entry.key: entry for entry in document.census}
    census_total = sum(entry.count for entry in document.census)

    rows: list[UnscannedRow] = []
    errors: list[dict[str, Any]] = []
    for key, entry in census_by_key.items():
        seen = extracted_by_category.get(key, 0)
        if seen > entry.count:
            errors.append({
                "code": CensusBalanceError.EXTRACTED_EXCEEDS_CENSUS.value,
                "category": key,
                "census_count": entry.count,
                "extracted_count": seen,
                "detail": (
                    f"извлечено {seen} элементов категории {key}, "
                    f"а перепись документа насчитала {entry.count}"),
            })
            continue
        missing = entry.count - seen
        if not missing:
            continue
        if key not in known:
            reason = UnscannedReason.CATEGORY_OUTSIDE_TABLE
        elif status_by_category.get(key) is CategoryState.PARTIAL:
            reason = UnscannedReason.PAGE_REFUSED
        else:
            reason = UnscannedReason.CATEGORY_SHORT_READ
        rows.append(UnscannedRow(
            category=key,
            census_count=entry.count,
            extracted_count=seen,
            unscanned=missing,
            reason=reason,
            category_ru=entry.name,
        ))

    # Категория, которую извлечение вернуло, а перепись не знает вовсе, — тот
    # же перебор: элементов такой категории в документе, по переписи, ноль.
    for category, seen in extracted_by_category.items():
        if category not in census_by_key and seen:
            errors.append({
                "code": CensusBalanceError.EXTRACTED_EXCEEDS_CENSUS.value,
                "category": category,
                "census_count": 0,
                "extracted_count": seen,
                "detail": (
                    f"извлечено {seen} элементов категории {category}, "
                    "которой нет в переписи документа"),
            })

    unscanned = sum(row.unscanned for row in rows)
    if not errors and census_total != extracted_total + unscanned:
        # Единственный оставшийся путь сюда — арифметическая рассогласованность
        # самой сводки; она обязана быть громкой, а не подогнанной.
        errors.append({
            "code": CensusBalanceError.CENSUS_TOTAL_MISMATCH.value,
            "category": "",
            "census_count": census_total,
            "extracted_count": extracted_total,
            "detail": (
                f"перепись {census_total} != извлечено {extracted_total} + "
                f"не читалось {unscanned}"),
        })

    rows.sort(key=lambda row: (-row.unscanned, row.category))
    return CensusBalance(
        present=True,
        census_total=census_total,
        extracted=extracted_total,
        unscanned=unscanned,
        categories_in_model=len(census_by_key),
        categories_scanned=len(set(census_by_key) & known),
        rows=tuple(rows),
        errors=tuple(errors),
    )


def census_from_mapping(counts: Mapping[str, int]) -> tuple[dict[str, Any], ...]:
    """Собрать полезную нагрузку переписи из счётчика (для фикстур/тестов)."""
    return tuple(
        {"key": key, "name": "", "count": int(count)}
        for key, count in sorted(counts.items()))


__all__ = [
    "NO_CATEGORY_KEY",
    "TOP_N",
    "CensusBalance",
    "CensusBalanceError",
    "UnscannedReason",
    "UnscannedRow",
    "census_from_mapping",
    "reconcile_census",
]
