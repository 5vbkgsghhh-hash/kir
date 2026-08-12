"""ЖУРНАЛ ПРОГРАММ — накопленный список программ сессии есть ИСХОДНЫЙ КОД ЗДАНИЯ.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ, А НЕ «конвейер картинок». Картинка — один из читателей
журнала, и притом не главный. Журнал версионируют, диффают, переигрывают, по
нему считают вердикт по всему зданию; лист плана всего лишь один способ его
прочитать. Поэтому первично здесь хранение программ, а рисование живёт этажом
выше (`plan_stream.py`) и может отвалиться целиком, не задев запись.

ЧТО ВЫЯСНИЛ ИНВЕНТАРЬ ПЕРЕД СТРОЙКОЙ (03.08). Долговечной записи авторских
программ в проекте НЕТ, хотя похожих на неё три:

* `data/telemetry/kir_witness.jsonl` (~1226 строк) — корпус ИСХОДОВ, а не
  программ. `witness_feed._skeleton()` заменяет каждый числовой лист на `"#"`
  ПО КОНТРАКТУ («координаты не покидают модель»), в строке остаются имя опа,
  его id и скелет-хэш. Нарисовать по нему план невозможно и не будет возможно:
  редакция геометрии — смысл этого файла, а не его недоделка;
* `ir/acceptance_journal.py` — журнал ПРЕДИКАТОВ приёмки (fsync до записи,
  checksum-цепь). Тела программы не хранит;
* `kukai/design/review.py:record()` — ЕДИНСТВЕННОЕ место, где программы уже
  накапливались целиком. Но: `ContextVar` на ОДИН ход, только в памяти, только
  для программ, которые УЖЕ исполнились и прошли приёмку. Три отличия от
  нужного здесь (ход vs сессия, после записи vs до, исход vs замысел), поэтому
  журнал строится, а не переиспользуется. Обратное тоже верно и записано, чтобы
  через месяц не строить третий: `review.findings()` — готовый второй читатель
  этого журнала, когда его переведут с хода на сессию.

ЧЕСТНОСТЬ ИСТОЧНИКА. Здесь лежит то, что программа ЗАЯВИЛА, и ничего больше.
Заявление ≠ постройка: журнал наполняется ПОСЛЕ планирования и ДО записи, то
есть в нём есть и программы, которые Revit потом отверг. Это не дефект — это
цена того, чтобы поток работал в офлайн-прогонах, где Revit не поднимается
вовсе. Метка `stage="planned"` едет с каждой записью и с каждым кадром, а
`preview.PreviewSource.PROGRAM` независимо штампует лист как
`Assertion.SELF_REPORTED` («ЗАЯВЛЕНО»). Две метки из двух разных модулей, и ни
одна не выводится из другой.

ГРАНИЦЫ. Только stdlib. Ни одного импорта из `kukai.ir`, `kukai.api`,
`kukai.llm` — ни на уровне модуля, ни ленивого. Журнал не умеет ни
компилировать, ни рисовать, ни отправлять.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = (
    "JOURNAL_SCHEMA",
    "ProgramRecord",
    "SessionJournal",
    "SessionKey",
    "append",
    "get",
    "key_for",
    "remember_sections",
    "reset",
    "sessions",
    "stats",
)

JOURNAL_SCHEMA = "kir-journal/1"


def _int_env(name: str, default: int, *, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


#: Потолки. Журнал живёт в памяти живого сервиса, поэтому НЕ БЫВАЕТ
#: «неограниченного»: бесконечный журнал — это утечка с хорошим названием.
#: Переполнение вытесняет САМЫЕ СТАРЫЕ программы и НАЗЫВАЕТ это числом
#: (`programs_evicted`), которое едет на лист. Молча укоротить историю здания
#: значило бы нарисовать не то здание и не сказать об этом.
def _max_programs() -> int:
    return _int_env("KUKAI_KIR_JOURNAL_PROGRAMS", 512, low=8, high=20_000)


def _max_ops() -> int:
    return _int_env("KUKAI_KIR_JOURNAL_OPS", 40_000, low=100, high=2_000_000)


def _max_datums() -> int:
    return _int_env("KUKAI_KIR_JOURNAL_DATUMS", 1_024, low=8, high=100_000)


def _max_sessions() -> int:
    return _int_env("KUKAI_KIR_JOURNAL_SESSIONS", 8, low=1, high=256)


#: Датумы (`create_level`, `create_grid`) хранятся ОТДЕЛЬНО от программ и не
#: вытесняются вместе с ними. Причина не в экономии: без `create_level` этаж
#: теряет ИМЯ, и одна и та же «Отметка 0.000» после вытеснения раскалывается на
#: два разных этажа — `$L1` и «Отметка 0.000». Ключ этажа обязан быть
#: устойчивым дольше, чем живёт программа, которая его объявила.
_DATUM_OPS = ("create_level", "create_grid")

SessionKey = tuple[str, str]


def key_for(device_id: Any, doc_key: Any = "") -> SessionKey:
    """Ключ сессии — ОДНО правило на весь пакет.

    Правило тривиально, и ровно поэтому оно обязано жить в одном месте: писатель
    (`plan_stream.publish`) и читатели (`verdict.judge`) обязаны попадать в одну
    запись, а два независимых `(str(device_id or ""), str(doc_key or ""))`
    разъехались бы на первом же уточнении ключа — и разъехались бы МОЛЧА:
    читатель нашёл бы пустой журнал и честно промолчал.
    """
    return (str(device_id or ""), str(doc_key or ""))


@dataclass(frozen=True, slots=True)
class ProgramRecord:
    """Одна авторская программа, как её принял мидэнд.

    `ops` — то, что вернул `PlannedProgram.to_ops()`: раскрытые макросы,
    проставленные умолчания, проверенные ссылки. Ровно то, что пойдёт вниз, а
    не то, что набрал автор, — иначе лист показывал бы одно, а строилось бы
    другое.
    """

    seq: int
    ts: float
    ops: tuple[Mapping[str, Any], ...]
    plan_digest: str = ""
    author_digest: str = ""
    intent: str = ""
    source: str = ""
    #: Метка стадии. Сегодня всегда `planned`: журнал наполняется до записи.
    #: Поле существует, чтобы «заявлено» и «построено» никогда не оказались
    #: одним значением по умолчанию.
    stage: str = "planned"

    @property
    def op_count(self) -> int:
        return len(self.ops)


@dataclass(slots=True)
class SessionJournal:
    """Программы одной сессии в порядке появления.

    Курсор (`indexed_upto`) принадлежит ЧИТАТЕЛЮ, а не журналу: журнал только
    хранит и вытесняет. Благодаря курсору потерянный кадр не теряет программу —
    читатель догонит с того места, где остановился (см. `plan_stream`).
    """

    key: SessionKey
    records: list[ProgramRecord] = field(default_factory=list)
    datums: list[Mapping[str, Any]] = field(default_factory=list)
    #: Ключи датумов, уже попавшие в `datums`, — датум объявляется один раз, а
    #: приезжать может в каждой программе (`create_level` в шапке чанка).
    _datum_keys: set[str] = field(default_factory=set)
    next_seq: int = 0
    ops_held: int = 0
    programs_evicted: int = 0
    ops_evicted: int = 0
    datums_dropped: int = 0
    last_ts: float = 0.0
    #: Курсор читателя: seq первой ещё не прочитанной программы.
    indexed_upto: int = 0
    #: Индекс читателя: метка этажа -> seq программ, которые его затронули.
    level_index: dict[str, list[int]] = field(default_factory=dict)
    #: Сводка по ЭТАЖАМ: сколько операций этажу предъявлено. Число берётся из
    #: `census.considered` самого `preview` — своего правила «чья это операция»
    #: здесь нет намеренно (см. `plan_stream._slice_for`).
    level_tally: dict[str, int] = field(default_factory=dict)
    #: Сводка по ОПЕРАЦИЯМ на всю сессию. Разложить её ещё и по этажам нечем,
    #: не заведя второй экземпляр правила принадлежности, — поэтому она честно
    #: одна на здание, а не выдуманная поэтажная.
    op_tally: dict[str, int] = field(default_factory=dict)
    #: ГЕОМЕТРИЯ ТИПОВ ЭТОГО ДОКУМЕНТА (волна sections): отметки уровней и
    #: сечения типов, снятые стадией ground у ЖИВОЙ модели и уже очищенные
    #: (`open_model.prune_ground_snapshot`). Журнал их не толкует и ничего о
    #: них не знает — он их ХРАНИТ, потому что он единственное место, где
    #: сессия переживает ход, а тело стены нельзя построить из одной программы.
    #:
    #: `None` и `{}` — РАЗНЫЕ факты: «ground не отвечал» против «ответил, а
    #: сечений у типов нет». Читатель обязан их различать, поэтому и здесь
    #: они разные значения.
    sections: dict[str, Any] | None = None

    # -- запись -----------------------------------------------------------
    def append(self, record: ProgramRecord) -> ProgramRecord:
        self.records.append(record)
        self.ops_held += record.op_count
        self.last_ts = record.ts
        for op in record.ops:
            if op.get("op") in _DATUM_OPS:
                token = f"{op.get('op')}:{op.get('id')}"
                if token in self._datum_keys:
                    continue
                if len(self.datums) >= _max_datums():
                    self.datums_dropped += 1
                    continue
                self._datum_keys.add(token)
                self.datums.append(op)
        self._evict()
        return record

    def _evict(self) -> None:
        """Вытеснение с головы. Вытесненное СЧИТАЕТСЯ, а не забывается."""
        max_programs = _max_programs()
        max_ops = _max_ops()
        while self.records and (
                len(self.records) > max_programs or self.ops_held > max_ops):
            gone = self.records.pop(0)
            self.ops_held -= gone.op_count
            self.programs_evicted += 1
            self.ops_evicted += gone.op_count
            # Индекс чистится вместе с программой: висячий seq заставил бы
            # читателя рисовать пустоту и молчать об этом.
            for seqs in self.level_index.values():
                if seqs and seqs[0] == gone.seq:
                    seqs.pop(0)
                elif gone.seq in seqs:
                    seqs.remove(gone.seq)
            if self.indexed_upto < gone.seq + 1:
                self.indexed_upto = gone.seq + 1

    # -- чтение -----------------------------------------------------------
    def pending(self) -> list[ProgramRecord]:
        """Программы, до которых читатель ещё не дошёл."""
        return [r for r in self.records if r.seq >= self.indexed_upto]

    def by_seqs(self, seqs: Iterable[int]) -> list[ProgramRecord]:
        wanted = set(seqs)
        return [r for r in self.records if r.seq in wanted]

    def stats(self) -> dict[str, Any]:
        return {
            "schema": JOURNAL_SCHEMA,
            "programs": len(self.records),
            "ops": self.ops_held,
            "datums": len(self.datums),
            "datums_dropped": self.datums_dropped,
            "programs_evicted": self.programs_evicted,
            "ops_evicted": self.ops_evicted,
            "levels": len(self.level_index),
            "indexed_upto": self.indexed_upto,
            "next_seq": self.next_seq,
        }

    def summary(self) -> dict[str, Any]:
        """Сводка ЗАЯВЛЕННОГО по этажам и операциям.

        Слово выбрано намеренно. «Что построено» здесь сказать нельзя: журнал
        наполняется до записи, и часть программ Revit ещё отвергнет.
        """
        return {
            "schema": JOURNAL_SCHEMA,
            "stage": "planned",
            "assertion": "self_reported",
            "title_ru": "ЗАЯВЛЕНО программами сессии (не «построено»)",
            "levels": [{"level": name, "declared": self.level_tally[name]}
                       for name in sorted(self.level_tally)],
            "by_op": dict(sorted(self.op_tally.items())),
            "programs": len(self.records),
            "total": sum(self.op_tally.values()),
            "programs_evicted": self.programs_evicted,
        }


_LOCK = threading.Lock()
#: LRU по сессиям: живой сервис держит несколько устройств, но не сотню.
_SESSIONS: "OrderedDict[SessionKey, SessionJournal]" = OrderedDict()


def _normalise_ops(program: Any) -> tuple[Mapping[str, Any], ...]:
    """`PlannedProgram` | {'ops': [...]} | список операций -> кортеж словарей.

    Копия делается ЗДЕСЬ и один раз: журнал обязан пережить вызывающего, а
    вызывающий волен свой словарь потом менять.
    """
    raw: Any
    if hasattr(program, "to_ops"):
        raw = program.to_ops()
    elif isinstance(program, Mapping):
        raw = program.get("ops") or ()
    elif isinstance(program, Sequence) and not isinstance(program, (str, bytes)):
        raw = program
    else:
        return ()
    return tuple(dict(op) for op in raw if isinstance(op, Mapping))


def append(key: SessionKey, program: Any, *, plan_digest: str = "",
           author_digest: str = "", intent: str = "",
           source: str = "") -> ProgramRecord | None:
    """Записать программу в журнал сессии. Никогда не поднимает исключений."""
    ops = _normalise_ops(program)
    if not ops:
        return None
    with _LOCK:
        journal = _SESSIONS.get(key)
        if journal is None:
            journal = SessionJournal(key=key)
            _SESSIONS[key] = journal
            while len(_SESSIONS) > _max_sessions():
                _SESSIONS.popitem(last=False)
        _SESSIONS.move_to_end(key)
        record = ProgramRecord(
            seq=journal.next_seq,
            ts=time.time(),
            ops=ops,
            plan_digest=str(plan_digest or getattr(program, "plan_digest", "") or ""),
            author_digest=str(author_digest or ""),
            intent=str(intent or getattr(program, "intent", "") or "")[:200],
            source=str(source or ""),
        )
        journal.next_seq += 1
        return journal.append(record)


def remember_sections(key: SessionKey, sections: Any) -> None:
    """Запомнить геометрию типов документа этой сессии. Никогда не бросает.

    Отдельным входом, а не полем `append`, намеренно: программа ложится в
    журнал ДО того, как ground сходит к мосту (`serving`: publish на 1362,
    снапшот на 1387), и связать их одним вызовом значило бы либо задержать
    запись исходного кода здания, либо потерять сечения первого хода.
    """
    if sections is not None and not isinstance(sections, dict):
        return
    with _LOCK:
        journal = _SESSIONS.get(key)
        if journal is None:
            journal = SessionJournal(key=key)
            _SESSIONS[key] = journal
            while len(_SESSIONS) > _max_sessions():
                _SESSIONS.popitem(last=False)
        _SESSIONS.move_to_end(key)
        journal.sections = None if sections is None else dict(sections)


def get(key: SessionKey) -> SessionJournal | None:
    with _LOCK:
        return _SESSIONS.get(key)


def sessions() -> tuple[SessionKey, ...]:
    with _LOCK:
        return tuple(_SESSIONS)


def reset(key: SessionKey | None = None) -> None:
    with _LOCK:
        if key is None:
            _SESSIONS.clear()
        else:
            _SESSIONS.pop(key, None)


def stats() -> dict[str, Any]:
    with _LOCK:
        return {
            "schema": JOURNAL_SCHEMA,
            "sessions": len(_SESSIONS),
            "programs": sum(len(j.records) for j in _SESSIONS.values()),
            "ops": sum(j.ops_held for j in _SESSIONS.values()),
            "programs_evicted": sum(
                j.programs_evicted for j in _SESSIONS.values()),
        }
