"""СУДЬЯ ЗДАНИЯ — пачка сессии уезжает вердикту и возвращается В КВИТАНЦИЮ.

ЧТО ЗДЕСЬ ЧИНИТСЯ (замер 04.08). Пачка в проде уже собиралась и собиралась
правильно: журнал копит программы сессии, `plan_stream._slice_for` отдаёт их
НЕ склеенными, `transfer.redeem()` возвращает `list[list[dict]]`, чат-дверь
гоняет её по одной. Но уезжала она ВИТРИНЕ и ИСПОЛНИТЕЛЮ — человеку и Revit'у.
К СУДЬЕ она не приходила НИКОГДА: у `design_check.check_bundle` был ровно один
прод-вызывающий — `course.design_check` внутри песочницы, то есть только тогда,
когда модель сама догадалась собрать пачку руками и спросить.

ПОЧЕМУ ЭТО НЕ МЕЛОЧЬ. Единица здания — ПАЧКА, и это не удобство: `create_stairs`
по закону Revit обязан быть единственным опом своей программы (KIR-L002),
поэтому тело двухэтажного здания лестницы содержать НЕ МОЖЕТ, а без лестницы
HAB010 блокирует каждый занятый этаж выше земли. Каждое звено по отдельности
непригодно ПО ПОСТРОЕНИЮ. Судить звено и молчать о пачке значит всегда говорить
модели неправду об одном и том же.

ГДЕ ЭТОТ МОДУЛЬ ЖИВЁТ В КАРТЕ ПАКЕТА. Это путь ОБРАТНО, как `transfer`: он
читает журнал и знает вердикт (то есть компилятор), поэтому его не имеет права
импортировать ни один модуль пути «туда» (`journal`, `plan_stream`, `showroom`)
— иначе односторонность потока, доказанная `test_live_plan_stream.py`, стала бы
ложной через него. Единственный импортёр — `kukai/ir/serving.py`, чат-дверь.

ЧЕГО ЭТОТ МОДУЛЬ НЕ ДЕЛАЕТ:

* НЕ судит на админской двери (`handle_revit_ir_bulk`). Там автор — материализатор
  пересборки (замер 30.07, Snowdon Towers: 6 335 опов, 26 программ чанками по
  250), а не модель, и читателя у квитанции нет вовсе;
* НЕ решает, что такое «обязательное правило». Свой список правил стал бы вторым
  судьёй одного вопроса; здесь только пересказывается то, что сказал чекер;
* НЕ бросает исключений. Вердикт о здании — обратная связь, а не постусловие:
  сломанный судья не имеет права стоить хода, в котором Revit уже пишет.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from kukai.live import journal as _journal

logger = logging.getLogger(__name__)

__all__ = (
    "BUILDING_SCHEMA",
    "enabled",
    "judge",
    "programs_seen",
)

BUILDING_SCHEMA = "kir-building-verdict/1"

_FLAG = "KUKAI_KIR_BUILDING_VERDICT"


def enabled() -> bool:
    """Выключатель. Выключенный = поведение до этой волны (вердикта нет)."""
    return os.environ.get(_FLAG, "1") != "0"


def _int_env(name: str, default: int, *, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


#: ПОТОЛКИ, И ОНИ НЕ КРУГЛЫЕ. Замер 04.08 на прод-боксе, честная пачка (тело +
#: лестница, помещения замыкаются, правила высказываются): 22 операции — 13 мс,
#: 190 — 94 мс, 400 — 197 мс, 820 — 340 мс, 1660 — 681 мс. Линейно, ~0.4 мс на
#: операцию. Потолок выбран так, чтобы худший случай стоил ~0.5 с при живой
#: записи в Revit в десятки секунд. Перебор НАЗЫВАЕТСЯ числом, а не молча
#: роняет вердикт: «здание слишком велико» и «здание не проверялось» — разные
#: утверждения, и второе модель прочитала бы как «всё хорошо».
def _max_ops() -> int:
    return _int_env("KUKAI_KIR_BUILDING_VERDICT_OPS", 1_200, low=20, high=40_000)


def _max_programs() -> int:
    return _int_env("KUKAI_KIR_BUILDING_VERDICT_PROGRAMS", 64, low=2, high=512)


#: Потолок текста квитанции. Канал здесь — не `stdout` песочницы (4000), а тело
#: результата инструмента, но платит за него тот же контекст модели.
_TEXT_CAP = 2_600


def programs_seen(key: _journal.SessionKey) -> int:
    """Сколько программ журнал НАЗНАЧИЛ этой сессии за всё время.

    Считается по `next_seq`, а не по длине списка: вытеснение укорачивает
    список, и «выросло ли за этот ход» по длине читалось бы как «не выросло»
    ровно на переполненном журнале — то есть на самом большом здании.
    """
    entry = _journal.get(key)
    return entry.next_seq if entry is not None else 0


def judge(key: _journal.SessionKey) -> dict[str, Any] | None:
    """Судить ВСЁ, что сессия объявила, как одно здание. Никогда не бросает.

    `None` означает «сказать нечего» (журнала нет, выключено, судья недоступен
    как модуль) — и это единственный случай, когда квитанция молчит. Всё
    остальное, включая отказ двери вердикта и перебор потолка, возвращается
    текстом: молчание читается как «всё в порядке».
    """
    try:
        if not enabled():
            return None
        entry = _journal.get(key)
        if entry is None or not entry.records:
            return None
        pack = [{"ops": [dict(op) for op in record.ops]}
                for record in entry.records]
        head: dict[str, Any] = {
            "schema": BUILDING_SCHEMA,
            "programs": len(pack),
            "ops": sum(record.op_count for record in entry.records),
            "programs_evicted": entry.programs_evicted,
        }
        over = _over_cap(head)
        if over is not None:
            return {**head, "verdict": "", "message_ru": over}
        try:
            from kukai.ir import design_check as _verdict
        except Exception as exc:  # noqa: BLE001 — модуль судьи не поднялся
            logger.debug("building verdict import failed", exc_info=True)
            return {**head, "verdict": "",
                    "message_ru": f"{_preamble(head)}\nВЕРДИКТ О ЗДАНИИ "
                                  f"НЕДОСТУПЕН: {type(exc).__name__}: {exc}"}
        try:
            report = _verdict.check_bundle(
                pack, building_id="здание этой сессии (пачка программ)")
        except _verdict.VerdictInputError as exc:
            # НАЗВАННЫЙ отказ двери — это сигнал, а не сбой: KIR-V002 говорит,
            # что ссылка перешла границу программы, KIR-V003 — что звено
            # непостроимо. И то и другое чинит АВТОР, и узнать об этом он
            # обязан здесь, а не на устройстве.
            return {**head, "verdict": "",
                    "message_ru": f"{_preamble(head)}\n{exc.render()}"}
        except _verdict.DesignCheckUnavailable as exc:
            return {**head, "verdict": "",
                    "message_ru": f"{_preamble(head)}\n"
                                  f"ВЕРДИКТ О ЗДАНИИ НЕДОСТУПЕН: {exc}"}
        return {**head, **_describe(report, head, _verdict)}
    except Exception:  # noqa: BLE001 — АБСОЛЮТНЫЙ fail-open, см. шапку
        logger.debug("building verdict failed (fail-open)", exc_info=True)
        return None


def _preamble(head: dict[str, Any]) -> str:
    """ЗНАМЕНАТЕЛЬ ПЕРЕД УТВЕРЖДЕНИЕМ. Вердикт, прочитанный раньше того, о чём
    он, — это оценка неизвестно чего; первой строкой всегда стоит, ЧТО судили."""
    whole = ("то, что журнал ещё помнит" if head["programs_evicted"]
             else "всё, что эта сессия объявила")
    line = (f"ЗДАНИЕ ЦЕЛИКОМ (не эта одна программа): пачка из "
            f"{head['programs']} программ, {head['ops']} операций — {whole}, "
            f"судится как ОДНО здание")
    if head["programs_evicted"]:
        line += (f"\nВНИМАНИЕ: {head['programs_evicted']} самых ранних программ "
                 f"вытеснено из журнала — судится ХВОСТ здания, а не всё")
    return line


def _over_cap(head: dict[str, Any]) -> str | None:
    if head["programs"] <= _max_programs() and head["ops"] <= _max_ops():
        return None
    return (f"{_preamble(head)}\nВЕРДИКТ О ЗДАНИИ НЕ СЧИТАЛСЯ: пачка больше "
            f"потолка хода ({_max_programs()} программ / {_max_ops()} "
            f"операций). Это НЕ «нарушений нет» — это «не смотрели». Спроси "
            f"вердикт сам по интересующей части: "
            f"`design_check([программа1, программа2, …])` в скрипте.")


def _describe(report: Any, head: dict[str, Any], module: Any) -> dict[str, Any]:
    """Вердикт -> поля квитанции. Числа машинные, текст человеческий."""
    coverage = report.report.coverage
    suspended = list(report.rules_suspended)
    blocking = sorted({v.rule_id for v in report.report.blocking})
    verdict = report.verdict
    text = "\n".join(
        [_preamble(head), module.render_verdict_brief(report, limit=1_600)]
        + _waiver_block(report, module))
    if len(text) > _TEXT_CAP:
        text = (text[:_TEXT_CAP].rsplit("\n", 1)[0]
                + f"\n… обрезано на {_TEXT_CAP} символах")
    return {
        "verdict": (verdict.value if verdict is not None else ""),
        "rules_evaluated": report.rules_applied,
        "rules_total": report.rules_total,
        "rules_suspended": suspended,
        "blocking": blocking,
        "message_ru": text,
    }


def _waiver_block(report: Any, module: Any) -> list[str]:
    """PASS ПО СНЯТИЮ ОБЯЗАН ЧИТАТЬСЯ ИНАЧЕ, ЧЕМ PASS ПО УДОВЛЕТВОРЕНИЮ.

    ЗАМЕР, ради которого этот блок существует. Одно здание, отличается ТОЛЬКО
    имя помещения у лестницы: «Лестничная клетка» -> PASS, 13 правил из 20,
    HAB001 (второй выход) и HAB010 (связь этажей) ОЦЕНЕНЫ; «Кладовая» -> PASS,
    11 из 20, те же два правила СНЯТЫ профилем и не высказывались вовсе. Обе
    строки при наивном чтении: «PASS, блокирующих 0».

    Сам чекер этой разницы не ловит и не обязан: снятое профилем правило уходит
    `continue` ДО учёта в `mandatory_not_evaluated` (`engine.run_checker`), и
    список обязательных-неоценённых в ОБОИХ случаях выше — ПУСТ. Краткий
    вердикт называет снятые правила, но причину отсылает «см. полный вердикт»,
    а полного модель не получает никогда: канал узкий.

    Поэтому здесь печатается ровно то, чего не хватает, — ПРИЧИНА снятия рядом
    с именами снятых правил. Причина берётся у профиля, а не сочиняется: это та
    самая строка, которая и есть починка следующего хода («связность строится
    только через помещение с функцией ЛЕСТНИЦА»).

    ДВА РОДА СНЯТИЯ РАЗВЕДЕНЫ, И РАЗВЕДЕНЫ СТРУКТУРНО, А НЕ ПО ТЕКСТУ ПРИЧИНЫ.
    `DESIGN_STAGE.suspended` — снятия САМОЙ СТАДИИ: они стоят при любом здании
    (площадь проёма не выражена типом, признака «несущая» у стены нет, оракул
    квартиры измеренно неточен). Их причины не меняются никогда и стоят ~1100
    символов; печатать их КАЖДЫЙ пишущий ход значит платить контекстом за
    новость, которой нет, — а предупреждение, которое стоит всегда, модель
    перестаёт читать через два хода. Остальные снятия `design_stage_profile`
    добавляет ЗАМЕРОМ ЭТОГО СВИДЕТЕЛЯ, и вот они — новость и адрес починки.
    Вычитание множеств здесь не эвристика: обе стороны берутся у самого
    вердикта, и второго правила «что тут постоянное» не заводится.
    """
    profile = report.profile
    if profile is None or not report.rules_suspended:
        return []
    try:
        stage = set(module.DESIGN_STAGE.suspended)
    except Exception:  # noqa: BLE001 — стадия не обязана быть той же
        stage = set()
    constant = [r for r in report.rules_suspended if r in stage]
    specific = [r for r in report.rules_suspended if r not in stage]
    lines = [f"СНЯТО, А НЕ ПРОЙДЕНО — правила, которые не высказывались вовсе "
             f"({len(report.rules_suspended)} из {report.rules_total}):"]
    grouped: dict[str, list[str]] = {}
    for rule_id in specific:
        try:
            reason = str(profile.suspension_reason(rule_id) or "")
        except Exception:  # noqa: BLE001 — профиль не обязан знать каждый код
            reason = ""
        grouped.setdefault(reason, []).append(rule_id)
    for reason, rule_ids in grouped.items():
        lines.append(f"  ЭТИМ ЗДАНИЕМ {'/'.join(sorted(rule_ids))}: "
                     + (reason[:360] if reason else "причина не названа профилем"))
    if constant:
        lines.append(f"  СТАДИЕЙ (стоят при любом замысле, чинить нечем): "
                     f"{', '.join(sorted(constant))}")
    word = report.verdict.value if report.verdict is not None else ""
    if word == "pass":
        lines.append(
            f"ПРИГОДЕН здесь значит РОВНО «среди {report.rules_applied} "
            f"высказавшихся правил нарушений нет». Про остальные "
            f"{report.rules_total - report.rules_applied} не сказано НИЧЕГО — "
            f"снятое правило это не пройденное правило.")
    return lines
