"""УЖЕ СТОЯЩЕЕ В ДОКУМЕНТЕ — второй источник тел для пачки.

ЧТО ЭТО ЧИНИТ. `clash_bundle` сравнивает пачку сессии САМУ С СОБОЙ. Его
собственная квитанция говорит это прямым текстом: «НЕ ВИДИТ ВООБЩЕ: только
объявленное сессией. Стоящее в документе в поиск не входит никогда (ground даёт
уровни и ТИПЫ, ни одного экземпляра) — столкновение с чужой стеной не „не
найдено“, а НЕВИДИМО.» Ноль находок отвечал «мои новые элементы не бьются между
собой», и читался как «здание в порядке».

ОТКУДА БЕРУТСЯ ТЕЛА СТОЯЩЕГО. Из разбора L0, который лежит на диске: элемент
несёт `bbox_min_mm`/`bbox_max_mm` — НАСТОЯЩИЙ габарит Revit, снятый чтением, а
не объявленный программой. `hulls.build_hull` этот путь уже знает и помечает
грейдом `coarse`; его собственный комментарий про `_z_span` прямо говорит «у
разбора L0 его нет — там Z приходит из настоящего габарита». Мы не заводим
второго построителя оболочек: тот же `build_hull`, тот же снапшот, тот же
детектор.

АДРЕС ИСТОЧНИКА — УЖЕ СУЩЕСТВУЮЩЕЕ СОГЛАШЕНИЕ, А НЕ НОВОЕ. Волна сводной
модели (14.08) ввела `<модель>::<исходный id>` и `detect.cross_model_pair_filter`
поверх него. Стоящее здание — просто ещё один источник в том же адресном
пространстве, поэтому здесь нет ни одной новой формы адреса.

════════════════════════════════════════════════════════════════════════════
ТРИ РЕШЕНИЯ, И КАЖДОЕ ДОКАЗАНО, А НЕ ВЫБРАНО
════════════════════════════════════════════════════════════════════════════

**1. ОБЛАСТЬ = ГАБАРИТ ОБЪЕДИНЕНИЯ НОВЫХ ТЕЛ, ЗАПАС 0 мм.**

Это не вкус и не порог. Мы ищем ровно два отношения — `overlap` (signed_distance
< 0) и `contact` (== 0); оба ТРЕБУЮТ, чтобы габариты двух оболочек пересекались:
оболочка содержится в своём габарите, поэтому у пары с непересекающимися
габаритами расстояние строго положительно. Значит элемент, чей габарит не
пересекает габарит объединения новых тел, не может быть с ними ни в `overlap`,
ни в `contact` — и отбросить его можно БЕЗ ПОТЕРИ НАХОДОК.

Запас 0 мм означает: мы не ищем «рядом». Третье отношение, `separated`, против
стоящего НЕ публикуется вовсе — иначе в находки уехало бы всё здание, и число
находок перестало бы что-либо значить. Это названо в квитанции.

**2. «НЕ БЬЁТСЯ» ОТЛИЧАЕТСЯ ОТ «НЕ СМОТРЕЛИ» ПОЛЕМ, А НЕ ИНТОНАЦИЕЙ.**

Пустой отчёт обязан нести, ПРОТИВ ЧЕГО сравнивали: источник, число тел
стоящего, область, число сравнённых пар. Без источника ноль находок остаётся
тем же зелёным без акта различения, только шире — а это ровно тот дефект,
который волна закрывает. Поэтому `Existing.absent()` — не пустое множество, а
НАЗВАННОЕ отсутствие с причиной, и квитанция печатает его другими словами.

**3. КАСАНИЕ И ПРОНИКАНИЕ НЕ СМЕШИВАЮТСЯ.** Они уже разведены
(`detect.HULL_RELATIONS`), и замер это оправдывает: касание — до трети всех пар
(7 804 против 19 523 перекрытий на одном здании). Складывать их значит
систематически переоценивать число конфликтов, поэтому здесь они считаются
порознь и порознь печатаются.

ЧЕГО ЭТОТ МОДУЛЬ НЕ ДЕЛАЕТ. Он не ходит к мосту и не читает живой документ:
источник — разбор, уже лежащий на диске, то есть состояние на момент чтения.
Расхождение разбора с живым документом — факт о свежести источника, и он
называется отпечатком разбора в провенансе, а не прячется.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Mapping, Sequence

#: Разделитель адреса источника. То же соглашение, что у сводной модели
#: (`detect.cross_model_pair_filter`), и намеренно то же: два адресных
#: пространства для одного вопроса — наш именной дефект.
SOURCE_SEPARATOR = "::"

#: Префикс источника «уже стоящее в документе». Короткий и НЕ пустой: элемент
#: без префикса считается принадлежащим пачке, и пустая строка сделала бы эти
#: два случая неотличимыми.
EXISTING_SOURCE = "документ"

#: Запас области, мм. НОЛЬ, и это доказано в шапке модуля: `overlap` и
#: `contact` требуют пересечения габаритов, поэтому расширение области не
#: добавило бы ни одной находки, а только работы.
REGION_MARGIN_MM = 0.0


def existing_source_id(element_id: Any) -> str:
    """Адрес стоящего элемента в общем пространстве источников."""
    return f"{EXISTING_SOURCE}{SOURCE_SEPARATOR}{element_id}"


def is_existing(source_id: str) -> bool:
    """Принадлежит ли адрес стоящему зданию.

    Решает ПРЕФИКС, а не наличие разделителя: адрес другой модели
    (`ФАС_R23::7240696`) — тоже не пачка, но и не наше стоящее здание, и
    смешивать их нельзя.
    """
    return source_id.split(SOURCE_SEPARATOR, 1)[0] == EXISTING_SOURCE


@dataclass(frozen=True)
class Region:
    """Область сравнения — габарит, в котором находка ВООБЩЕ возможна.

    Пустая область (`lo is None`) — законный случай: пачка не построила ни
    одного тела. Тогда сравнивать не с чем не потому, что здания нет, а потому
    что нет НАШЕЙ стороны пары, и это разные факты.
    """

    lo: tuple[float, float, float] | None
    hi: tuple[float, float, float] | None
    margin_mm: float = REGION_MARGIN_MM

    @property
    def empty(self) -> bool:
        return self.lo is None or self.hi is None

    @classmethod
    def around(cls, records: Iterable[Any],
               *, margin_mm: float = REGION_MARGIN_MM) -> "Region":
        """Габарит объединения оболочек. Ни одной находки не теряет — см. шапку."""
        lo: list[float] | None = None
        hi: list[float] | None = None
        for rec in records:
            try:
                blo, bhi = rec.bounds()
            except Exception:  # noqa: BLE001 — запись без границ просто не расширяет
                continue
            if lo is None:
                lo, hi = list(blo), list(bhi)
                continue
            for axis in range(3):
                if blo[axis] < lo[axis]:
                    lo[axis] = blo[axis]
                if bhi[axis] > hi[axis]:  # type: ignore[index]
                    hi[axis] = bhi[axis]  # type: ignore[index]
        if lo is None or hi is None:
            return cls(None, None, margin_mm)
        m = float(margin_mm)
        return cls(
            (lo[0] - m, lo[1] - m, lo[2] - m),
            (hi[0] + m, hi[1] + m, hi[2] + m),
            m,
        )

    def admits(self, bbox_lo: Sequence[float], bbox_hi: Sequence[float]) -> bool:
        """Может ли элемент с таким габаритом вообще коснуться области."""
        if self.empty:
            return False
        for axis in range(3):
            if bbox_hi[axis] < self.lo[axis]:  # type: ignore[index]
                return False
            if bbox_lo[axis] > self.hi[axis]:  # type: ignore[index]
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        if self.empty:
            return {"empty": True, "margin_mm": self.margin_mm,
                    "why": "пачка не построила ни одного тела"}
        return {"empty": False, "margin_mm": self.margin_mm,
                "lo_mm": [round(v, 3) for v in self.lo],   # type: ignore[union-attr]
                "hi_mm": [round(v, 3) for v in self.hi]}   # type: ignore[union-attr]


@dataclass(frozen=True)
class Existing:
    """Тела уже стоящего — ИЛИ названная причина, почему их нет.

    Два состояния, и они РАЗНЫЕ факты. `present=False` значит «источника нет,
    сравнивать было не с чем»; `present=True` при `elements == ()` значит
    «источник есть, в области пусто» — то есть настоящий ответ о здании.
    Слить их в пустой список означало бы вернуть тот самый зелёный без
    различения, ради которого волна и делалась.
    """

    present: bool
    elements: tuple[dict, ...] = ()
    source: str = ""
    doc_name: str = ""
    region: Region = Region(None, None)
    scanned: int = 0
    admitted: int = 0
    without_bbox: int = 0
    reason: str = ""
    freshness: "Freshness | None" = None

    @classmethod
    def absent(cls, reason: str) -> "Existing":
        """Источника нет. Причина ОБЯЗАТЕЛЬНА — молчащее отсутствие неотличимо
        от честного нуля, и именно это мы чиним."""
        if not reason:
            raise ValueError("отсутствие стоящего обязано называть причину")
        return cls(present=False, reason=reason)

    def to_dict(self) -> dict[str, Any]:
        if not self.present:
            return {"present": False, "reason": self.reason}
        return {
            "present": True,
            "source": self.source,
            "doc_name": self.doc_name,
            "region": self.region.to_dict(),
            "scanned": self.scanned,
            "admitted": self.admitted,
            "bodies": len(self.elements),
            "without_bbox": self.without_bbox,
            # СВЕЖЕСТЬ ЕДЕТ ВСЕГДА, а не только когда плоха: поле, которое
            # появляется лишь при беде, читается как «раз его нет — всё
            # хорошо», а здесь ХОРОШО НЕ БЫВАЕТ (см. `Freshness`).
            "freshness": (None if self.freshness is None
                          else self.freshness.to_dict()),
        }


@dataclass(frozen=True)
class Freshness:
    """НАСКОЛЬКО источник соответствует ТОМУ ЖЕ документу — и доказано ли это.

    🔴 СЕГОДНЯ НЕ ДОКАЗЫВАЕТСЯ НИКАК, И ЭТО ЗАМЕР, А НЕ ОСТОРОЖНОСТЬ.
    Личность живого документа — `contracts.DocumentFingerprint`: тройка
    `(title, path_name, project_uid)`. Разбор не несёт из неё НИ ОДНОГО поля,
    кроме имени: `passport.json` держит `doc_name`, `change_stamp`,
    `revit_version`, шапка `L0.jsonl` — те же плюс `units`. `project_uid` и
    `path_name` в артефактах разбора отсутствуют вовсе.

    Общий ключ ровно один — ИМЯ, и оно сравнивается с ИМЕНЕМ честно: `doc_name`
    разбора это буквально `Document.Title` (`decompile/extract.py:1014`), то же
    самое поле, что лежит в `DocumentFingerprint.title`. Значит совпадение имён
    — сравнение подобного с подобным, а не догадка; но два документа с одним
    заголовком неразличимы, и «тот же файл» из этого НЕ СЛЕДУЕТ.

    Поэтому находка, снятая с такого источника, помечается `proven=False`, а
    квитанция это печатает. Молча сравнивать с прошлым нельзя — это тот же
    класс, что «устаревший каталог даёт `KIR-G101`, а не тихую постройку».

    🔴 ЗАКРЫТО 15.08.2026 — ЧАСТИЧНО, И ГРАНИЦА ЗДЕСЬ ВАЖНЕЕ ФАКТА.
    Паспорт теперь несёт `document_identity` (`decompile/passport.py`), а
    живой отпечаток берёт то же поле Revit (`open_model.py:1908`). Но
    `ProjectInformation.UniqueId` — РОДОСЛОВНАЯ, не авторитет: Save As несёт
    то же значение. Отсюда асимметрия, на которой всё стоит:

        совпало   -> сильнее имени, но «тот же файл» НЕ следует
        разошлось -> ДРУГОЙ документ, доказано; такой разбор отбрасывается
        нет в паспорте -> разбор снят до этой волны (4 из 71 несут личность)

    `proven=True` наступает только на авторитетном источнике (облачный или
    серверный GUID), и список этих источников спрашивается у
    `decompile/identity.py`, а не переписывается здесь.
    """

    proven: bool
    matched_by: str
    age_days: float | None = None
    why: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"proven": self.proven, "matched_by": self.matched_by,
                "age_days": (None if self.age_days is None
                             else round(self.age_days, 1)),
                "why": self.why}


#: Корень корпуса разборов. ТА ЖЕ переменная, что читают `serving`,
#: `course.corpus` и `gate_runner` — второй адрес того же корпуса означал бы
#: два места, обязанных совпасть.
DECOMPILE_ROOT_ENV = "KUKAI_DECOMPILE_DATA"
DECOMPILE_ROOT_DEFAULT = "backend/data/decompile"


def decompile_root() -> pathlib.Path:
    import os

    return pathlib.Path(
        os.environ.get(DECOMPILE_ROOT_ENV, DECOMPILE_ROOT_DEFAULT))


#: Источник личности, который Autodesk контрактует как АВТОРИТЕТ логической
#: модели. `project_information_unique_id` сюда НЕ входит намеренно: это
#: `Element.UniqueId`, уникальный лишь ВНУТРИ документа, и Save As несёт то же
#: значение. Список ведётся в `decompile/identity.py`; здесь он спрашивается, а
#: не переписывается — две таблицы, обязанные совпасть, и есть именной дефект
#: этого дерева.
def _authoritative_sources() -> frozenset:
    from kukai.ir.decompile.identity import (
        AUTHORITATIVE_DOCUMENT_IDENTITY_SOURCES)
    return AUTHORITATIVE_DOCUMENT_IDENTITY_SOURCES


def resolve_run(doc_title: str, *, root: Any = None, project_uid: str = ""
                ) -> tuple[pathlib.Path | None, str, Freshness | None]:
    """Заголовок живого документа -> самый свежий его разбор.

    Возвращает `(путь, причина_отказа, свежесть)`. Путь и причина
    взаимоисключающи: отказ ОБЯЗАН называть себя словами, иначе отсутствие
    источника неотличимо от «сравнили и чисто» — дефект, ради которого вся
    волна.

    Свежесть считается по времени последней записи каталога, а не по
    `change_stamp`: штамп — имя прогона, оно не упорядочено во времени.
    """
    import os
    import time

    if not doc_title:
        return None, ("личность документа неизвестна: ground не дал "
                      "`__document_fingerprint`, и с ЧЕМ сравнивать — "
                      "не выведено"), None
    base = pathlib.Path(str(root)) if root is not None else decompile_root()
    if not base.exists():
        return None, f"корпуса разборов нет: {base}", None

    best: tuple[int, float, pathlib.Path, Mapping[str, Any]] | None = None
    seen = 0
    refuted = 0
    for run in sorted(base.iterdir()):
        if not run.is_dir():
            continue
        passport = run / "passport.json"
        if not passport.exists() or not (run / "L0.jsonl").exists():
            continue
        seen += 1
        # 🔴 ДОРОГОЕ ЧТЕНИЕ — ТОЛЬКО ПО КАНДИДАТАМ, ОТОБРАННЫМ ДЁШЕВО.
        # Замерено 16.08.2026 на живом корпусе (52 разбора): полный разбор
        # паспортов стоил 17.2 с НА КАЖДЫЙ вызов, из них 13.2 с — `json.loads`
        # 918 МБ, чтобы прочитать ОДНО строковое поле. Цена росла с размером
        # ЗДАНИЯ (крупнейший паспорт 206 МБ, из них `tree` — 276 МБ в JSON),
        # хотя ответ фиксированного размера. Для клеша это была секунда на
        # ходе, для живого хода KIR — приговор способности.
        #
        # Шапка L0 (первая строка JSONL) несёт то же `doc_name`: сверено на
        # ВСЕХ 52 разборах корпуса — 52 совпали, 0 разошлись. Проход по
        # шапкам стоит 0.7 с против 17.2 с.
        #
        # Ошибаться дешёвый отбор может ТОЛЬКО в сторону лишней работы:
        # имя не прочиталось — разбор идёт в паспорт, как раньше. Пропустить
        # настоящего кандидата он не может, потому что «не знаю» и «не он» —
        # разные исходы, и первый не отбраковывает.
        cheap = _doc_name_from_l0_head(run / "L0.jsonl")
        if cheap is not None and cheap != doc_title:
            continue
        try:
            row = json.loads(passport.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if row.get("doc_name") != doc_title:
            continue
        # 🔴 ОПРОВЕРЖЕНИЕ СИЛЬНЕЕ ПОДТВЕРЖДЕНИЯ, И ЭТО НЕ ОСТОРОЖНОСТЬ.
        # Совпадение `project_uid` НЕ доказывает «тот же файл» (Save As несёт
        # то же значение), а РАСХОЖДЕНИЕ доказывает «другой файл» — обе стороны
        # читают одно поле Revit: разбор через `L0Document.identity`
        # (`extract.py:1074`), живой отпечаток через `open_model.py:1908`.
        # Поэтому разошедшийся разбор отбрасывается ЗДЕСЬ, а не помечается
        # ниже: он заведомо про другой документ, и «свежайший» среди чужих —
        # худший из возможных ответов.
        row_uid = _passport_uid(row)
        if project_uid and row_uid and row_uid != project_uid:
            refuted += 1
            continue
        try:
            stamp = os.path.getmtime(run)
        except OSError:
            stamp = 0.0
        # 🔴 СВИДЕТЕЛЬСТВО ВПЕРЁД СВЕЖЕСТИ, И ЭТО ПОЙМАНО КОНТРОЛЕМ, А НЕ
        # ПРИДУМАНО. Первая редакция брала просто самый свежий, и разбор БЕЗ
        # личности выигрывал у разбора с СОВПАВШЕЙ родословной по случайности
        # времени записи: сильнейшее свидетельство проигрывало штампу файловой
        # системы. Порядок теперь явный — авторитет, затем родословная, затем
        # «личности нет», и только внутри одного разряда решает свежесть.
        rank = _evidence_rank(row, project_uid)
        if best is None or (rank, stamp) > (best[0], best[1]):
            best = (rank, stamp, run, row)

    if best is None:
        tail = (f"; {refuted} отброшено по РАСХОЖДЕНИЮ личности — это другие "
                f"документы с тем же заголовком" if refuted else "")
        return None, (f"разбора документа «{doc_title}» в корпусе нет "
                      f"(просмотрено {seen}){tail} — сравнивать со стоящим "
                      f"НЕ С ЧЕМ"), None
    age_days = max(0.0, (time.time() - best[1]) / 86400.0)
    return best[2], "", _freshness_of(best[3], project_uid, age_days)


def _doc_name_from_l0_head(l0: pathlib.Path) -> str | None:
    """Имя документа из ШАПКИ L0 — или `None`, что значит «не знаю».

    🔴 ТРИ ИСХОДА, А НЕ ДВА, И ТРЕТИЙ ЗДЕСЬ ГЛАВНЫЙ. Строка — имя. Пустая
    строка — разбор имени не несёт (тоже знание: он не кандидат ни для кого).
    `None` — прочитать не удалось, и тогда решать по шапке НЕЛЬЗЯ: вызывающий
    обязан пойти в паспорт. Слить `None` с пустой строкой значит МОЛЧА
    отбросить существующий разбор и ответить «сравнивать не с чем».

    Читается ровно первая строка: у `L0.jsonl` она и есть шапка, а весь
    остальной файл (до 1.4 МБ на этаж) не трогается вовсе.
    """
    try:
        with l0.open(encoding="utf-8") as handle:
            head = json.loads(handle.readline())
    except (OSError, ValueError):
        return None
    if not isinstance(head, Mapping):
        return None
    document = head.get("document")
    if not isinstance(document, Mapping):
        return None
    name = document.get("doc_name")
    return name if isinstance(name, str) else None


def _evidence_rank(row: Mapping[str, Any], project_uid: str) -> int:
    """Сила свидетельства о личности: 2 авторитет · 1 родословная · 0 нечем.

    Ранг — НЕ качество разбора и не его свежесть. Это ответ на один вопрос:
    насколько твёрдо мы знаем, что этот разбор про ТОТ ЖЕ документ.
    """
    if not project_uid:
        return 0
    fact = row.get("document_identity")
    if not isinstance(fact, Mapping):
        return 0
    if _passport_uid(row) != project_uid:
        return 0
    source = fact.get("source")
    return 2 if source in _authoritative_sources() else 1


def _passport_uid(row: Mapping[str, Any]) -> str:
    """Значение личности из паспорта; пусто — разбор снят до этой волны."""
    fact = row.get("document_identity")
    if not isinstance(fact, Mapping):
        return ""
    value = fact.get("value")
    return value if isinstance(value, str) else ""


def _freshness_of(row: Mapping[str, Any], project_uid: str,
                  age_days: float) -> Freshness:
    """ЧЕТЫРЕ исхода, а не два, и каждый назван своим полем.

    Разница между ними решает, что делать с находкой, поэтому сливать их
    нельзя: «личность доказана» и «совпало только имя» ведут к разным
    действиям, а «разбор снят до этой волны» — факт О НАС, не о здании.
    """
    fact = row.get("document_identity")
    source = (fact.get("source") if isinstance(fact, Mapping) else None) or ""
    row_uid = _passport_uid(row)

    if not row_uid:
        return Freshness(
            proven=False, matched_by="doc_title", age_days=age_days,
            why=("совпало ИМЯ документа; разбор снят ДО того, как паспорт "
                 "научился нести личность, и доказать «тот же файл» нечем"))
    if not project_uid:
        return Freshness(
            proven=False, matched_by="doc_title", age_days=age_days,
            why=("совпало ИМЯ; разбор личность НЕСЁТ, но живая сторона её не "
                 "дала — сравнивать не с чем, и это факт о НАШЕМ чтении"))
    if source in _authoritative_sources():
        return Freshness(
            proven=True, matched_by=source, age_days=age_days,
            why=("личность документа совпала по источнику, который Autodesk "
                 "контрактует как авторитет логической модели"))
    return Freshness(
        proven=False, matched_by=source or "project_uid", age_days=age_days,
        why=("совпали ИМЯ и РОДОСЛОВНАЯ (`ProjectInformation.UniqueId`); это "
             "сильнее имени, но не доказательство: Save As несёт то же "
             "значение, поэтому «тот же файл» отсюда не следует"))


def _bbox_of(element: Mapping[str, Any]
             ) -> tuple[list[float], list[float]] | None:
    lo = element.get("bbox_min_mm")
    hi = element.get("bbox_max_mm")
    if (not isinstance(lo, list) or not isinstance(hi, list)
            or len(lo) != 3 or len(hi) != 3):
        return None
    try:
        lo_f = [float(v) for v in lo]
        hi_f = [float(v) for v in hi]
    except (TypeError, ValueError):
        return None
    if any(a != a for a in lo_f + hi_f):        # NaN
        return None
    if any(hi_f[i] < lo_f[i] for i in range(3)):
        return None
    return lo_f, hi_f


def iter_l0_elements(path: pathlib.Path) -> Iterator[dict]:
    """Элементы разбора L0. Строка без `record == "element"` пропускается.

    Читает построчно и не держит документ в памяти: у башни 115 889 элементов,
    и «прочитать всё, потом отфильтровать» стоило бы гигабайта ради области,
    в которую попадут единицы.
    """
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, Mapping) or row.get("record") != "element":
                continue
            element = row.get("element")
            if isinstance(element, Mapping):
                yield dict(element)


def load(run_dir: Any, region: Region, *, doc_name: str = "",
         freshness: "Freshness | None" = None) -> Existing:
    """Разбор + область -> тела стоящего в общем адресном пространстве.

    Отказы НАЗЫВАЮТСЯ, а не возвращаются пустотой: путь не задан, каталога
    нет, `L0.jsonl` нет, область пуста — четыре разных факта, и читатель
    квитанции обязан их различать.
    """
    if run_dir is None:
        return Existing.absent("источник стоящего не задан")
    root = pathlib.Path(str(run_dir))
    if not root.exists():
        return Existing.absent(f"каталога разбора нет: {root}")
    l0 = root / "L0.jsonl"
    if not l0.exists():
        return Existing.absent(f"в разборе нет L0.jsonl: {root.name}")
    if region.empty:
        return Existing.absent(
            "область пуста: пачка не построила ни одного тела, "
            "и сравнивать было НЕ ЧЕМУ с нашей стороны")

    elements: list[dict] = []
    scanned = 0
    without_bbox = 0
    for element in iter_l0_elements(l0):
        scanned += 1
        box = _bbox_of(element)
        if box is None:
            without_bbox += 1
            continue
        if not region.admits(box[0], box[1]):
            continue
        raw_id = element.get("element_id")
        if raw_id is None:
            without_bbox += 1
            continue
        # Адрес переписывается В ОБЩЕЕ ПРОСТРАНСТВО, всё остальное — как в
        # разборе: тела строит тот же `build_hull`, и подменять ему вход
        # значило бы завести второй построитель.
        element["element_id"] = existing_source_id(raw_id)
        elements.append(element)
    return Existing(
        present=True,
        elements=tuple(elements),
        source=root.name,
        doc_name=doc_name or root.name,
        region=region,
        scanned=scanned,
        admitted=len(elements),
        without_bbox=without_bbox,
        freshness=freshness,
    )


#: ФИЛЬТР ПАР ЖИВЁТ НЕ ЗДЕСЬ, И ЭТО НАМЕРЕННО.
#: `detect.bundle_vs_document_pair_filter` — единственный, и область названа в
#: каноне областей (`detect.SCOPES`), потому что детектор отказывает
#: неизвестному фильтру: «область поиска обязана называться в каноне». Вторая
#: копия предиката здесь была бы ровно нашим именным дефектом — две функции,
#: обязанные совпадать, и ничто их не заставляет.


def pairs_compared(new_bodies: int, existing_bodies: int) -> int:
    """Сколько пар отдано фильтру — ТОЧНО, а не оценкой.

    Считается формулой, потому что обе численности известны по построению:
    все пары внутри пачки плюс все пары пачка×стоящее. `None` здесь запрещён —
    прочитанный как ноль, он превратил бы «не считалось» в «нисколько».
    """
    n = max(0, int(new_bodies))
    m = max(0, int(existing_bodies))
    return n * (n - 1) // 2 + n * m
