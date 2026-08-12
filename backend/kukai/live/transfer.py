"""ВОЗВРАТ — «перенести в Revit» как ТИПИЗИРОВАННОЕ решение, а не как кнопка.

До этой волны поток был односторонним: кадры уходили человеку и не
возвращались (`serving.py` признавал это дословно). Здесь появляется ребро
обратно, и оно намеренно узкое: панель умеет сказать ровно одно — «построй то,
что я вижу» и, возможно, «вот эта его часть».

──────────────────────────────────────────────────────────────────────────────
ЗАКОН ПЕРВЫЙ: смотрим и строим ОДНУ программу, а не две
──────────────────────────────────────────────────────────────────────────────
Панель не присылает программу. Панель присылает ПОДПИСЬ показанного, а тело
берётся из витрины (`showroom.py`) по этой подписи. Подмена не проверяется —
она НЕПРОИЗНОСИМА: у программы, которой сервер не показывал, нет подписи в
витрине, и назвать её панели нечем. Проверяется другое, и это второй рубеж:
`Shown.verify()` пересчитывает подпись из хранимых байтов перед выдачей, то
есть порча самой витрины даёт типизированный отказ, а не тихую подмену.

ПОЧЕМУ НЕ `content_digest` ЛИСТА. Он подписывает картинку. Замер 04.08: стена
по умолчанию, та же стена с `height_mm=4200` и та же с `type_name="Кирпич 380"`
дают ОДИН дайджест листа — ни высота, ни тип на плане не рисуются. Билетом на
перенос он бы означал ровно то, ради запрета чего строился типизированный
компилятор: у здания две подписи. Подпись переноса берёт программу целиком.

──────────────────────────────────────────────────────────────────────────────
ЗАКОН ВТОРОЙ: выделенный кусок замкнут по зависимостям
──────────────────────────────────────────────────────────────────────────────
Дверь без стены-носителя — не «неполная программа», а НЕВАЛИДНАЯ: `compiler`
отказывает кодом KIR-L003 («ref не указывает на более ранний оп»). Поэтому
подмножество доращивается до замыкания по графу прямого хода.

ГРАФ НЕ ИЗОБРЕТАЕТСЯ ЗДЕСЬ. Он уже есть и живёт в реестре: параметр рода
`sel`/`target_w`/`refs_w` со значением `{"by": "ref", ...}` есть ребро, и ровно
это правило `compiler.py:591-638` применяет, строя DAG. `refs_of()` ниже
читает `spec.OPS[...].params`, а не список имён полей: список имён («host»,
«level», «wall») разъехался бы с реестром на первой же новой операции, и
разъехался бы МОЛЧА.

ВЫБРАНО ДОРАЩИВАНИЕ, А НЕ ОТКАЗ. Обоснование, по пунктам:

  1. добавляемое не угадывается, а ВЫВОДИТСЯ: замыкание детерминировано и
     единственно. Отказать значило бы вернуть человеку задачу, которую
     компилятор уже решил, — и ради чего тогда типы;
  2. доращивание не может внести НЕВИДАННОГО: замыкание берёт операции только
     из той же показанной программы. Всё добавленное было на том же листе, в
     той же переписи, под той же подписью. Расширяется подсветка, а не мир;
  3. цена ошибки несимметрична. Отказ стоит круга через самый дорогой ресурс
     (внимание человека), доращивание — одной названной строки;
  4. и всё же молчать нельзя, поэтому доращивание НЕ ИСПОЛНЯЕТСЯ СРАЗУ.
     Выросшая пачка получает СВОЮ подпись и кладётся в витрину, а решение
     возвращается со статусом `needs_confirm` и поимённым списком добавленного
     («стена W1 — её требует дверь D3, поле host»). Исполнение возможно только
     по второму запросу, несущему НОВУЮ подпись. То есть «молча построить
     неполное» невозможно по построению, и «молча построить лишнее» — тоже:
     ни одна пачка не исполняется, пока её собственная подпись не приехала с
     панели.

──────────────────────────────────────────────────────────────────────────────
ЧЕГО ЭТОТ МОДУЛЬ НЕ ДЕЛАЕТ
──────────────────────────────────────────────────────────────────────────────
Не компилирует, не заземляет, не пишет в Revit и не открывает транзакций.
Он выдаёт РАЗРЕШЕНИЕ: пачку операций и подпись, под которой она разрешена.
Исполняет `kukai/api/chat_ws.py` через ту же публичную дверь `revit_ir`, что и
чат, — второй двери в Revit здесь не заводится намеренно.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from kukai.live import showroom as _showroom

logger = logging.getLogger(__name__)

__all__ = (
    "DECISION_SCHEMA",
    "REQUEST_SCHEMA",
    "Added",
    "Decision",
    "Refusal",
    "Status",
    "authorize",
    "closure",
    "enabled",
    "redeem",
    "refs_of",
)

REQUEST_SCHEMA = "kir-transfer-request/1"
DECISION_SCHEMA = "kir-transfer-decision/1"

_FLAG = "KUKAI_KIR_TRANSFER"

#: Роды параметров, которые МОГУТ нести ссылку. Не список полей — список
#: РОДОВ; сами поля объявляет реестр операции. Совпадает с `compiler.py:613`.
_REF_KINDS = ("sel", "target_w")
_REF_LIST_KIND = "refs_w"


def enabled() -> bool:
    """Выключатель возврата отдельно от выключателя показа: сломать кнопку и
    сломать экран — разные решения, и путать их не надо."""
    return os.environ.get(_FLAG, "1") != "0"


class Status(str, Enum):
    #: Подпись найдена, замыкание ничего не добавило — исполнять можно.
    READY = "ready"
    #: Замыкание доросло выделение. Названо что; ждём подтверждения НОВОЙ
    #: подписи. Без второго запроса ничего не исполняется.
    NEEDS_CONFIRM = "needs_confirm"
    REFUSED = "refused"


class Refusal(str, Enum):
    """ЗАКРЫТЫЙ список причин. Отказ обязан НАЗЫВАТЬ, а не извиняться."""

    #: Возврат выключен флагом.
    DISABLED = "disabled"
    #: Подписи нет в витрине: сервер такого не показывал (или показывал так
    #: давно, что кадр вытеснен). НЕ «программа плохая» — «я этого не показывал».
    NOT_SHOWN = "not_shown"
    #: Витрина хранит байты, чья подпись им не соответствует. Внутренняя порча;
    #: единственный случай, когда мы можем назвать РАСХОЖДЕНИЕ поимённо.
    STORE_CORRUPT = "store_corrupt"
    #: Просили перенести выделение, а выделено ничего.
    SELECTION_EMPTY = "selection_empty"
    #: Выделены идентификаторы, которых в показанном нет. Пользователь смотрит
    #: на один кадр, а подпись прислал от другого — назвать это обязаны.
    SELECTION_UNKNOWN = "selection_unknown"
    #: В показанном есть операция, которой нет в реестре: её рёбра неизвестны,
    #: а значит замыкание недоказуемо. Догадываться здесь нельзя.
    UNKNOWN_OP = "unknown_op"
    #: После замыкания исполнять нечего.
    NOTHING_TO_BUILD = "nothing_to_build"
    #: Подпись НАРИСОВАННОГО панелью не совпала с подписью ПОКАЗАННОГО
    #: сервером. Со сцены-склейки это два РАЗНЫХ вычисления, и расхождение
    #: означает здание, которого инженер не видел. Победитель здесь НЕ
    #: выбирается: взять серверную версию значит построить непоказанное,
    #: взять панельную — довериться тому, чего мы не считали.
    SHOWN_MISMATCH = "shown_mismatch"
    #: Панель смотрит на ХВОСТ журнала, а не на здание. Отправить хвост как
    #: здание нельзя, даже если подписи сошлись: сошлись бы на хвосте.
    PARTIAL_SCENE = "partial_scene"
    #: Сервер этой сессии не показывал сцены вовсе — подписывать нечего.
    #: Отдельно от `SHOWN_MISMATCH` намеренно: «не совпало» и «не показывали»
    #: лечатся разным, и первое ещё требует объяснения, а второе нет.
    NOTHING_SHOWN = "nothing_shown"


_REFUSAL_RU: dict[Refusal, str] = {
    Refusal.DISABLED: "перенос выключен на этом сервере (KUKAI_KIR_TRANSFER=0)",
    Refusal.NOT_SHOWN: (
        "такой программы сервер не показывал: подписи нет в витрине. "
        "Переносится только увиденное — программу, которой не было на экране, "
        "назвать нечем"),
    Refusal.STORE_CORRUPT: (
        "витрина хранит не то, что подписывала: содержимое кадра изменилось "
        "после показа — переносить нечего, пока расхождение не объяснено"),
    Refusal.SELECTION_EMPTY: "выделение пусто: переносить нечего",
    Refusal.SELECTION_UNKNOWN: (
        "выделены элементы, которых в показанной программе нет — вероятно, "
        "карточка и выделение с разных кадров"),
    Refusal.UNKNOWN_OP: (
        "в показанной программе есть операция, отсутствующая в реестре: её "
        "зависимости неизвестны, и замыкание выделения недоказуемо"),
    Refusal.NOTHING_TO_BUILD: "после замыкания исполнять нечего",
    Refusal.SHOWN_MISMATCH: (
        "то, что нарисовала панель, и то, что показал сервер, — разные вещи. "
        "Переносить нельзя НИ ОДНУ из версий: серверная не была на экране, "
        "панельную мы не считали. Перезагрузите сцену целиком"),
    Refusal.PARTIAL_SCENE: (
        "на экране ХВОСТ журнала, а не здание: часть программ в эту сцену не "
        "попала. Отправить хвост как здание нельзя — запросите сцену целиком"),
    Refusal.NOTHING_SHOWN: (
        "сервер не показывал этой сессии ни одной сцены: подписывать нечего"),
}


@dataclass(frozen=True, slots=True)
class Added:
    """Одна операция, ДОБАВЛЕННАЯ замыканием, и кем она затребована."""

    op_id: str
    op: str
    needed_by: str
    via: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.op_id, "op": self.op,
                "needed_by": self.needed_by, "via": self.via,
                "ru": (f"{self.op} «{self.op_id}» — его требует «{self.needed_by}» "
                       f"(поле {self.via})")}


@dataclass(frozen=True, slots=True)
class Decision:
    """Типизированное решение. Одно на запрос, целиком сериализуемо."""

    status: Status
    #: Подпись, которую прислала панель (что человек видел).
    requested_digest: str = ""
    #: Подпись того, что РАЗРЕШЕНО исполнить. При `READY` равна предыдущей —
    #: это и есть «что видел, то и построится», выраженное равенством.
    transfer_digest: str = ""
    level: str = ""
    refusal: Refusal | None = None
    refusal_ru: str = ""
    #: Что именно разошлось. Заполняется там, где расхождение ИЗВЕСТНО.
    diverged: tuple[str, ...] = ()
    added: tuple[Added, ...] = ()
    programs: int = 0
    ops: int = 0
    selected: int = 0
    #: Перепись ровно того, что разрешено к переносу, — не того, что на листе.
    census: Mapping[str, Any] = field(default_factory=dict)
    census_lines: tuple[Mapping[str, Any], ...] = ()
    #: Кадр этого этажа с тех пор обновился. НЕ отказ: переносится именно то,
    #: что на карточке. Но промолчать об этом значило бы дать человеку думать,
    #: что он смотрит на свежее.
    stale: bool = False
    current_digest: str = ""
    #: Сколько программ пачки не влезает в авторский бюджет чат-двери. Считаем
    #: ЗДЕСЬ, до всякого Revit: узнать это на устройстве стоит круглого рейса.
    over_budget: tuple[str, ...] = ()
    #: Что скажет о пачке САМ компилятор, спрошенный офлайн (`plan_program`).
    #: Не второе мнение и не копия правил — тот же судья, только заранее.
    preflight: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status is not Status.REFUSED

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DECISION_SCHEMA,
            "status": self.status.value,
            "requested_digest": self.requested_digest,
            "transfer_digest": self.transfer_digest,
            "level": self.level,
            "refusal": self.refusal.value if self.refusal else None,
            "refusal_ru": self.refusal_ru,
            "diverged": list(self.diverged),
            "added": [a.to_dict() for a in self.added],
            "programs": self.programs,
            "ops": self.ops,
            "selected": self.selected,
            "census": dict(self.census),
            "census_lines": [dict(line) for line in self.census_lines],
            "stale": self.stale,
            "current_digest": self.current_digest,
            "over_budget": list(self.over_budget),
            "preflight": list(self.preflight),
        }


def _refuse(reason: Refusal, *, requested: str = "", level: str = "",
            diverged: Sequence[str] = (), extra_ru: str = "",
            current_digest: str = "") -> Decision:
    text = _REFUSAL_RU[reason]
    if extra_ru:
        text = f"{text}; {extra_ru}"
    return Decision(status=Status.REFUSED, refusal=reason, refusal_ru=text,
                    requested_digest=requested, level=level,
                    diverged=tuple(diverged), current_digest=current_digest)


# ── граф прямого хода ───────────────────────────────────────────────────────

def refs_of(op: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """(поле, id, на который ссылается) — по РЕЕСТРУ, а не по списку имён.

    Возвращает пустой кортеж для операции без ссылок. Поднимает `KeyError`,
    если операции нет в реестре: у неё неизвестны рёбра, и молча считать её
    независимой значило бы разрешить неполную программу.
    """
    from kukai.ir import spec as _spec

    ospec = _spec.OPS[str(op.get("op", ""))]
    out: list[tuple[str, str]] = []
    for param in ospec.params:
        value = op.get(param.name)
        if param.kind in _REF_KINDS and isinstance(value, Mapping):
            if value.get("by") == "ref" and isinstance(value.get("value"), str):
                out.append((param.name, value["value"]))
        elif param.kind == _REF_LIST_KIND and isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                if not isinstance(item, Mapping):
                    continue
                if (item.get("by") == "ref"
                        and isinstance(item.get("value"), str)):
                    out.append((f"{param.name}[{index}]", item["value"]))
                    continue
                # Вторая ступень селектора (`{"by": "face", "of": ...}`,
                # `kukai/ir/faceref.py`): ссылка лежит на уровень глубже.
                # Пропустить её здесь — значит замкнуть выделение БЕЗ
                # производящего опа и выдать наружу программу с висячим ref;
                # замыкание, теряющее ребро, хуже отсутствующего, потому что
                # выглядит выполненным.
                inner = item.get("of")
                if (item.get("by") == "face" and isinstance(inner, Mapping)
                        and inner.get("by") == "ref"
                        and isinstance(inner.get("value"), str)):
                    out.append((f"{param.name}[{index}].of", inner["value"]))
    return tuple(out)


def closure(ops: Sequence[Mapping[str, Any]],
            selected: Sequence[str]) -> tuple[list[dict[str, Any]], list[Added]]:
    """Замкнуть выделение по графу прямого хода ВНУТРИ одной программы.

    Порядок исходной программы сохраняется: `compiler` требует, чтобы ref
    указывал на БОЛЕЕ РАННИЙ оп, и перестановка сделала бы замкнутое
    подмножество снова невалидным.

    Замыкание внутрипрограммное намеренно. Между программами пачки ссылок по
    `ref` не бывает по построению — `compiler` резолвит `ref` только внутри
    одной программы, а соседняя программа обращается к уровню ПО ИМЕНИ
    (`base_level="Этаж 1"`). Тянуть закрытие через пачку значило бы изобрести
    ребро, которого в языке нет.
    """
    by_id: dict[str, Mapping[str, Any]] = {}
    for op in ops:
        oid = op.get("id")
        if isinstance(oid, str) and oid:
            by_id.setdefault(oid, op)

    wanted = {oid for oid in selected if oid in by_id}
    added: dict[str, Added] = {}
    stack = list(wanted)
    while stack:
        oid = stack.pop()
        op = by_id.get(oid)
        if op is None:
            continue
        for field_name, target in refs_of(op):
            if target in wanted or target not in by_id:
                # Ссылка наружу программы (по имени/по id элемента) сюда не
                # попадает: `refs_of` отдаёт только `by=ref`, а неразрешимый
                # `ref` — забота компилятора, а не выделения.
                continue
            wanted.add(target)
            added[target] = Added(
                op_id=target, op=str(by_id[target].get("op", "?")),
                needed_by=oid, via=field_name)
            stack.append(target)

    kept = [dict(op) for op in ops
            if isinstance(op.get("id"), str) and op["id"] in wanted]
    order = {op.get("id"): i for i, op in enumerate(ops)}
    grown = sorted(added.values(), key=lambda a: order.get(a.op_id, 0))
    return kept, grown


# ── разрешение ──────────────────────────────────────────────────────────────

def authorize(key: tuple[str, str], *, digest: str,
              selection: Sequence[str] | None = None) -> Decision:
    """Единственный вход возврата. Никогда не бросает: отказ — это значение.

    `selection is None` — перенести кадр целиком. `selection == []` — человек
    нажал «перенести выделенное», ничего не выделив; это отдельный отказ, а не
    молчаливый перенос всего.
    """
    try:
        return _authorize(key, digest=digest, selection=selection)
    except Exception:  # noqa: BLE001 — панель не имеет права уронить сервер
        logger.exception("kir transfer authorize failed")
        return _refuse(Refusal.NOT_SHOWN, requested=str(digest or ""),
                       extra_ru="внутренняя ошибка разбора запроса")


def _authorize(key: tuple[str, str], *, digest: str,
               selection: Sequence[str] | None) -> Decision:
    if not enabled():
        return _refuse(Refusal.DISABLED, requested=str(digest or ""))

    digest = str(digest or "").strip().lower()
    shown = _showroom.recall(key, digest)
    if shown is None:
        current = _showroom.levels(key)
        return _refuse(
            Refusal.NOT_SHOWN, requested=digest,
            diverged=sorted(f"{lvl}={d[:16]}" for lvl, d in current.items()),
            extra_ru=(f"сервер помнит кадров: {len(current)}"
                      if current else "витрина этой сессии пуста"))
    if not shown.verify():
        stored = _showroom.program_digest(
            shown.programs_json, shown.context_json, shown.level)
        return _refuse(
            Refusal.STORE_CORRUPT, requested=digest, level=shown.level,
            diverged=(f"подписано {digest[:16]}", f"хранится {stored[:16]}"),
            extra_ru="содержимое кадра изменилось после показа")

    programs = shown.programs()
    context = shown.context()

    # ЗАМЫКАНИЕ. Пустое выделение и отсутствие выделения — РАЗНЫЕ вещи.
    added: list[Added] = []
    selected_ids: set[str] = set()
    if selection is None:
        pack = programs
    else:
        selected_ids = {str(s) for s in selection if str(s)}
        if not selected_ids:
            return _refuse(Refusal.SELECTION_EMPTY, requested=digest,
                           level=shown.level)
        known = {str(op.get("id")) for program in programs for op in program
                 if isinstance(op.get("id"), str)}
        unknown = sorted(selected_ids - known)
        if unknown:
            return _refuse(
                Refusal.SELECTION_UNKNOWN, requested=digest, level=shown.level,
                diverged=tuple(unknown[:24]),
                extra_ru=f"не найдено в показанном: {len(unknown)}")
        pack = []
        try:
            for program in programs:
                kept, grown = closure(program, sorted(selected_ids))
                if kept:
                    pack.append(kept)
                    added.extend(grown)
        except KeyError as exc:
            return _refuse(Refusal.UNKNOWN_OP, requested=digest,
                           level=shown.level, diverged=(str(exc.args[0]),))
        if not pack:
            return _refuse(Refusal.NOTHING_TO_BUILD, requested=digest,
                           level=shown.level)

    blobs = tuple(_showroom.canonical_program(p) for p in pack)
    transfer_digest = _showroom.program_digest(
        blobs, shown.context_json, shown.level)

    # ВЫРОСШАЯ ПАЧКА КЛАДЁТСЯ В ВИТРИНУ ПОД СВОЕЙ ПОДПИСЬЮ. Иначе подтверждение
    # пришлось бы принимать «на слово», и адресация содержимым перестала бы
    # быть полной: исполняется ровно то, что витрина умеет выдать по подписи.
    census, lines = _census_of(context, pack, shown.level)
    if transfer_digest != digest:
        _showroom.show(key, level=shown.level, programs=pack,
                       context=context, census=census, seq=shown.seq,
                       ts=shown.ts, intent=shown.intent)

    latest = _showroom.levels(key).get(shown.level, "")
    over = _over_budget(pack)
    ops_total = sum(len(p) for p in pack)
    status = Status.READY if not added else Status.NEEDS_CONFIRM
    return Decision(
        preflight=_preflight(pack),
        status=status,
        requested_digest=digest,
        transfer_digest=transfer_digest,
        level=shown.level,
        added=tuple(added),
        programs=len(pack),
        ops=ops_total,
        selected=len(selected_ids),
        census=census,
        census_lines=tuple(lines),
        stale=bool(latest and latest not in (digest, transfer_digest)),
        current_digest=latest,
        over_budget=over,
    )


def redeem(key: tuple[str, str], digest: str) -> list[list[dict[str, Any]]] | None:
    """Выдать исполнителю ПАЧКУ по подписи. Единственный способ получить тело.

    Исполнитель НЕ ПОЛУЧАЕТ операции от панели — ни при каком повороте: он
    называет подпись, витрина отдаёт байты. Поэтому «исполнить не то, что
    показали» — не проверяемое условие, а невыразимое.
    """
    shown = _showroom.recall(key, str(digest or "").strip().lower())
    if shown is None or not shown.verify():
        return None
    return shown.programs()


def _over_budget(pack: Sequence[Sequence[Mapping[str, Any]]]) -> tuple[str, ...]:
    """Какие программы не пролезут в авторский бюджет ЧАТ-двери (20).

    Считается офлайн намеренно. Узнать «программа слишком длинная» на живом
    устройстве стоит круглого рейса через самый дорогой ресурс; здесь это
    стоит одного сравнения.
    """
    try:
        from kukai.ir.compiler import MAX_OPS_PER_PROGRAM as _cap
    except Exception:  # noqa: BLE001
        return ()
    return tuple(
        f"программа #{i + 1}: {len(program)} опов > {_cap}"
        for i, program in enumerate(pack) if len(program) > _cap)


def _preflight(pack: Sequence[Sequence[Mapping[str, Any]]]) -> tuple[str, ...]:
    """Спросить САМ компилятор о пачке — офлайн, до устройства.

    ПОЧЕМУ НЕ СВОИ ПРОВЕРКИ. Второй экземпляр правила «куда может смотреть
    ref», «какой оп обязан быть одиноким», «какое поле обязательно» разъехался
    бы с первым за месяц и разъехался бы молча. Здесь вызывается ровно тот
    судья, который будет судить на устройстве, — `plan_program`. Разница
    только в том, что ответ приходит бесплатно и сразу, а не через круглый
    рейс к самому дорогому ресурсу.

    ЭТО НЕ ОТКАЗ, А ПРЕДУПРЕЖДЕНИЕ. Судьёй остаётся дверь `revit_ir`: она
    видит ещё и живую модель, и её вердикт может отличаться от планового в обе
    стороны. Превратить предсказание в запрет значило бы завести второй
    авторитет — тот самый дефект, который уже стоил этому проекту `ok:true`
    поверх нарушенного постусловия.
    """
    try:
        from kukai.ir.compiler import plan_program
        from kukai.ir.spec import IR_VERSION
    except Exception:  # noqa: BLE001
        return ()
    out: list[str] = []
    for index, program in enumerate(pack):
        try:
            plan_program({"ir_version": IR_VERSION, "intent": "перенос",
                          "ops": [dict(op) for op in program]}, bulk=True)
        except Exception as exc:  # noqa: BLE001 — текст отказа и есть ответ
            out.append(f"программа #{index + 1}: {exc}"[:400])
    return tuple(out)


def _census_of(context: Sequence[Mapping[str, Any]],
               pack: Sequence[Sequence[Mapping[str, Any]]],
               level: str) -> tuple[dict[str, Any], list[Mapping[str, Any]]]:
    """Перепись РОВНО ПЕРЕНОСИМОГО, а не листа.

    Это не украшение решения. Человек выделил кусок; сколько из него вообще
    рисуется, а сколько не показано и почему — единственный способ увидеть,
    что переносится не то, что он думает, ДО того как это окажется в Revit.
    """
    try:
        from kukai.ir.preview import build_program_preview, census_lines
        ops = [dict(op) for op in context]
        for program in pack:
            ops.extend(dict(op) for op in program)
        building = build_program_preview(ops, levels=[level] if level else None)
        try:
            plan = building.plan(level)
            census = plan.census
        except KeyError:
            census = building.census
        return census.to_dict(), list(census_lines(census))
    except Exception:  # noqa: BLE001 — без переписи решение остаётся честным,
        # но обязано СКАЗАТЬ, что переписи нет, а не подсунуть пустую как факт
        logger.debug("transfer census failed", exc_info=True)
        return ({"unavailable": True,
                 "ru": "перепись посчитать не удалось — считайте, что "
                       "показанного покрытия НЕТ"}, [])


# ═══════════════════════════════════════════════════════════════════════════
# КНОПКА ВЬЮЕРА: перенос ПОКАЗАННОЙ СЦЕНЫ, а не показанного кадра
# ═══════════════════════════════════════════════════════════════════════════
#
# ГРАНИЦА ПРОДУКТА, А НЕ ОПТИМИЗАЦИЯ. Кнопка «отправить в Revit» — единственное
# место, где виртуальное становится настоящим, и она подписывает ТО, ЧТО
# ЧЕЛОВЕК ВИДЕЛ. Пока сцена приезжала целиком, «показанное» и «переносимое»
# совпадали по построению. Со склейкой из базы и хвостов это два РАЗНЫХ
# вычисления — серверное и панельное, — и любое их расхождение есть здание,
# которого инженер не видел, построенное с его согласия.
#
# ТРИ ПРАВИЛА, И НИ ОДНО НЕ ВЫВОДИТСЯ ИЗ ДРУГИХ:
#
#   1. подпись считается ОТ НАРИСОВАННОГО. Панель складывает её из своих
#      склеенных буферов — из тех же чисел, что кормят рисовальщик, — а не
#      повторяет то, что прислал сервер. Иначе подписывалось бы намерение;
#   2. расхождение — ОТКАЗ, а не выбор победителя. Обе версии запрещены:
#      серверная не была на экране, панельную мы не считали;
#   3. `partial` доезжает до кнопки. Инженер, смотрящий на хвост, не должен
#      иметь возможности отправить его как здание — даже если подписи сошлись,
#      сошлись бы они на хвосте.
#
# ЧЕГО ЗДЕСЬ НЕТ. Выделения куска (`selection`) на этом пути пока нет: сцена
# переносится целиком. Замыкание по зависимостям поэтому не нужно — в пачке
# уже всё, на что она ссылается. Появится выделение — вернётся и `closure`,
# который для кадров уже написан выше.

SCENE_DECISION_SCHEMA = "kir-transfer-scene/1"


def authorize_scene(key: tuple[str, str], *, shown_digest: str,
                    partial: bool = False) -> Decision:
    """Разрешить перенос ПОКАЗАННОЙ СЦЕНЫ. Никогда не поднимает исключений."""
    try:
        return _authorize_scene(key, shown_digest=shown_digest,
                                partial=partial)
    except Exception:  # noqa: BLE001 — кнопка не имеет права ронять сессию
        logger.exception("kir transfer authorize_scene failed")
        return _refuse(Refusal.NOT_SHOWN, requested=shown_digest,
                       extra_ru="решение не собралось — переносить нечего")


def _authorize_scene(key: tuple[str, str], *, shown_digest: str,
                     partial: bool) -> Decision:
    from kukai.live import journal as _journal
    from kukai.live import showroom as _showroom

    if not enabled():
        return _refuse(Refusal.DISABLED, requested=shown_digest)

    # ХВОСТ ПРОВЕРЯЕТСЯ ПЕРВЫМ. Он делает бессмысленным всё остальное: подпись
    # хвоста сойдётся сама с собой и ничего этим не докажет.
    if partial:
        return _refuse(Refusal.PARTIAL_SCENE, requested=shown_digest)

    current = _showroom.scene_digest(key)
    if not current:
        return _refuse(Refusal.NOTHING_SHOWN, requested=shown_digest)
    if not shown_digest or shown_digest != current:
        # РАСХОЖДЕНИЕ НАЗЫВАЕТСЯ ОБЕИМИ ПОДПИСЯМИ. Отказ, не говорящий, что с
        # чем не сошлось, неотличим от поломки.
        return _refuse(
            Refusal.SHOWN_MISMATCH, requested=shown_digest,
            current_digest=current,
            diverged=(f"панель: {shown_digest or '(пусто)'}",
                      f"сервер: {current}"))

    session = _journal.get(key)
    if session is None or not session.records:
        return _refuse(Refusal.NOTHING_TO_BUILD, requested=shown_digest)

    pack = [[dict(op) for op in record.ops] for record in session.records]
    if not any(pack):
        return _refuse(Refusal.NOTHING_TO_BUILD, requested=shown_digest)

    context = [dict(op) for op in session.datums]
    census, lines = _census_of(context, pack, "")
    return Decision(
        status=Status.READY,
        requested_digest=shown_digest,
        # РАВЕНСТВО ПОДПИСЕЙ И ЕСТЬ «что видел, то и построится». Разные
        # значения здесь означали бы, что мы переносим не показанное.
        transfer_digest=shown_digest,
        current_digest=current,
        programs=len(pack),
        ops=sum(len(program) for program in pack),
        census=census,
        census_lines=tuple(lines),
        over_budget=_over_budget(pack),
        preflight=_preflight(pack),
    )
