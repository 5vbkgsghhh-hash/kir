"""A "SOURCE MISSING" BRANCH MUST NAME THE CAUSE, NOT RETURN A BARE ZERO.

WHY THIS FILE APPEARED ON 29.08.2026
------------------------------------
Two independent audits — a full journal of 383 records and a separate pass
of 8 findings — converged on ONE dominant class: "an instrument that
cannot go red." A recount showed that the class is not scattered but
enumerable, and all its cases share one shape:

    if not <source>.exists():
        return []          <- a bare value

The consumer reads such a zero as a FACT ABOUT THE SUBJECT ("no
references," "no decompiles," "the code did not change"), when it is
actually a fact ABOUT THE INSTRUMENT ("there was nothing to look at"). The
price has already been paid three times, each time in a different
currency:

  * `snapshot_pins` was looking for the roots of a past layout ->
    `pinned_snapshots()` returned `{}` ALWAYS, and the snapshot cleaner
    scheduled `delete_inactive` on decompiles pinned by PROD
    (`course/building.py`, `viewer/advice.py`);
  * `scope_audit` traversed `kir/kukai` -> the documented command printed
    "findings: 0" with exit code 0, without reading a single file;
  * `agreements` traverses the `kukai` root, which does not exist here,
    while its actual subject is 31 live functions in `kir/`.

THE LAW IS NOT INVENTED HERE. It is written in the tree verbatim, and
TWICE:

    "the answer does not change, but SILENCE gains a CAUSE that can be
     asked about"                              `install_paths.py`
    "ANY ZERO TAKEN FROM THE CORPUS MUST TRAVEL WITH PROOF THAT THE
     CORPUS WAS REACHABLE"                     `viewer/scene.py`

In practice, 29 branches follow it and 27 places do not. This file fixes
nothing — it forbids ADDING A NEW ONE and forces the fixed ones to be
struck off.

WHAT THIS INSTRUMENT CANNOT DO IS NAMED UP FRONT
-------------------------------------------------
* it only sees the branch `if not <existence predicate>`, where the
  predicate is named syntactically. A check hidden behind someone else's
  function (`if _ready(p)`) is invisible to it, and this is a DELIBERATE
  undercount: a false alarm costs more than a miss;
* "carries a cause" is checked SYNTACTICALLY — a string literal, an
  f-string, a `raise`, or a call with a telling name. A branch that
  returns a value with the cause INSIDE someone else's object will be
  credited by that object's literal, not by its meaning. The boundary is
  named, not hidden;
* tests are not scanned: their "no fixture" branches are about the rig,
  not about what the consumer reads.

THE KEY IS (FILE, FUNCTION), NOT A LINE, and this is not a small thing:
line numbers drift with any edit further up the file, and a journal keyed
on line numbers would go stale on day one — and go stale SILENTLY, the
same way all the others go stale.

🔴 WHO MOVES THE LEDGER LINE (rule set up 30.08.2026, bought by a race)
------------------------------------------------------------------------
**The ledger is amended by THE SAME COMMIT as the place it describes.**
The one who fixes the place moves its own line — and no one else.

The reasoning is not politeness but a measurement: over one shift this
file went red three times with redness that was not its own. One smith
fixed a place, the ledger line was expected from another, and between the
two commits the suite stood red with a "strike it off" message addressed
to no one. Worse, the argument in the line WENT STALE from one commit made
by someone else: `("kir/a5_recovery.py", "find_resumable")` sat in the
debt with the argument "the companion is called ONLY from tests," and
`3976e0b` made that argument false, knowing nothing about the ledger.

Why this WORKS, and is not merely desirable: lines are laid out BY FILE,
files by smiths' holdings, so lines between smiths DO NOT OVERLAP. What is
shared here is exactly one thing — the ledger's STRUCTURE: the categories,
their checks, their ceilings. The structure is held by this file's owner;
the lines are owned by the owners of their own places.

This is also where the division falls in a dispute: "the place is fixed
but the line still stands" is the fixer's defect; "the wrong category" or
"the check does not catch it" is the file owner's defect.
"""
from __future__ import annotations

import ast
import pathlib
import re
import unittest

import kir as _kir_pkg

PACKAGE = pathlib.Path(_kir_pkg.__file__).resolve().parent
TREE = PACKAGE.parent

#: Existence predicates, named syntactically.
_PREDICATES = ("is_dir", "exists", "isdir", "is_file",
               "snapshot_file_exists", "_snapshot_exists")

#: Call names that are counted as NAMING a cause.
_REASON_CALLS = ("refuse", "reason", "absent", "error", "warn", "log")

#: Value names that are counted as NAMING a cause.
_REASON_NAMES = ("missing", "reason", "refus", "absent")

#: The companion's name, named IN THE TEXT of the argument: `name()` in
#: backticks. This is how the arguments are written across all three
#: lists, and it is the only handle by which the reverse check (debt ->
#: companion) can tell who is meant.
_COMPANION_IN_TEXT = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)\(\)`")


def _carries_reason(body) -> bool:
    """Whether the branch carries a CAUSE that the consumer can read."""
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, (ast.Raise, ast.JoinedStr)):
                return True
            if (isinstance(node, ast.Constant)
                    and isinstance(node.value, str) and node.value.strip()):
                return True
            if isinstance(node, ast.Call):
                name = (getattr(node.func, "attr", None)
                        or getattr(node.func, "id", None) or "").lower()
                if any(k in name for k in _REASON_CALLS):
                    return True
            if isinstance(node, ast.Name):
                if any(k in node.id.lower() for k in _REASON_NAMES):
                    return True
    return False


def _owner_map(tree: ast.AST) -> dict:
    """id(node) -> the name of the enclosing function. The journal's key
    must survive a shift in line numbers, so it addresses the function, not
    the line number."""
    owner: dict = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(fn):
                owner.setdefault(id(child), fn.name)
    return owner


def scan_source(source: str, label: str) -> tuple[set, int]:
    """(mute places, count of those naming a cause) for ONE source file.

    Factored out and takes TEXT, so the instrument can be set loose on a
    fake: an instrument that can only work on the live tree cannot be
    tested against a deliberate defect, and therefore it cannot be proven
    to catch it.
    """
    tree = ast.parse(source)
    owner = _owner_map(tree)
    mute: set = set()
    named = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        cond = ast.unparse(node.test)
        if not any(k in cond for k in _PREDICATES) or "not " not in cond:
            continue
        if not [s for s in node.body
                if isinstance(s, (ast.Return, ast.Continue, ast.Pass))]:
            continue
        if _carries_reason(node.body):
            named += 1
            continue
        mute.add((label, owner.get(id(node), "<модуль>")))
    return mute, named


def scan_package() -> tuple[set, int]:
    """The live tree: mute places, and the count of those that name a cause."""
    mute: set = set()
    named = 0
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts or "tests" in path.parts:
            continue
        if path.name.startswith("test_"):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:                                  # pragma: no cover
            continue
        found, count = scan_source(source, str(path.relative_to(TREE)))
        mute |= found
        named += count
    return mute, named


#: THE CLOSED LIST OF ALREADY-REGISTERED MUTE PLACES. It has the right only
#: to SHRINK: a line whose place has been fixed must leave from here
#: (guarded by `test_the_ledger_holds_no_ghosts`), otherwise the
#: dispensation would outlive its own cause.
#:
#: The value is what the consumer mistakes this branch's bare value for.
MUTE_SOURCES: dict[tuple[str, str], str] = {
    #: 🔴 EMPTY AS OF 30.08.2026 — AND THIS IS A NUMBER, NOT A VICTORY OVER
    #: THE LIST. Over one shift it went UP and DOWN: 3 -> 5 (E-36 returned
    #: four records here whose companion was called only by tests) -> 0.
    #: Every move was paid for by a commit AT THE PLACE ITSELF, none by
    #: rewriting the ledger.
    #:
    #: Who closed the last lines, and with what:
    #:   kir/instruments/bounds_audit.py::side       648d054 (the absence
    #:                                               branch writes
    #:                                               `side_absences`)
    #:   kir/idempotence.py::_isolation_from_artifacts  2e21c1c
    #:   kir/clash/existing.py::resolve_run          85e911d
    #:   kir/course/corpus.py::group_index           98d8474
    #:   kir/course/corpus.py::curtain_index         8f88809
    #:   kir/a5_recovery.py::find_resumable          3976e0b — did not leave
    #:                                               here into the void, but
    #:                                               into
    #:                                               `ANSWERED_ELSEWHERE`:
    #:                                               the bare `None`
    #:                                               remained, the
    #:                                               companion named the
    #:                                               cause
    #:
    #: The list is LEFT EMPTY, not deleted: `test_no_new_mute_source` and
    #: `test_the_ledger_holds_no_ghosts` read it by name, and an empty debt
    #: is a checkable number, while a deleted one is the absence of a
    #: check.
}


#: 🔴 THE SECOND CLOSED LIST, SET UP ON 29.08.2026, AND SET UP BECAUSE OF A
#: DEFECT IN THIS VERY INSTRUMENT. `_carries_reason` looks ONLY INSIDE THE
#: BRANCH, and a companion function sitting next to it in the module does
#: not exist for it. So a form of fix that the tree's own convention
#: considers correct (`install_root_refusal`,
#: `corpus_unreachable_reason`) was NOT CREDITED by the ratchet, and the
#: closing number "MUTE_SOURCES is empty" was unreachable BY CONSTRUCTION
#: everywhere a bare answer must not be dropped. The instrument was
#: measuring the wrong thing to fix.
#:
#: Here live the places where a bare zero is MANDATORY (the answer must
#: not be dropped: the instrument computes even over an incomplete input),
#: and the cause is asked of a NAMED companion in the same module. The
#: debt is `MUTE_SOURCES`; moving here IS the unit of work. A line never
#: goes back: the ratchet moves in one direction only.
#:
#: The companion must not only EXIST but also SOUND — someone must call
#: it. Without the second condition we would set up a field nobody reads:
#: exactly the defect closed in E-7 (the closure instrument was written on
#: 14.08 and was called by no one).
ANSWERED_ELSEWHERE: dict[tuple[str, str], tuple[str, str]] = {
    ("kir/a5_recovery.py", "find_resumable"):
        ("resumable_absence_reason",
         "улик нет -> «возобновлять нечего»; `None` ронять нельзя — не найдя "
         "журнала, ход обязан начать новый прогон. Но у пустоты ДВА смысла: "
         "прогонов не было либо каталог `a5_runs` СНЕСЁН, и второй дороже — A5 "
         "существует ради улик после сбоя. ЗАКРЫТО 29.08.2026 шестым кузнецом "
         "(коммит 3976e0b): `resumable_absence_reason()` был написан и не "
         "звался никем, теперь стоит на живом пути — `kir/serving.py:8240`. "
         "Запись пролежала в долге с доводом «зовётся только из тестов», "
         "который протух за ОДИН коммит соседа; ловит это теперь "
         "test_a_debt_whose_companion_went_live_must_move"),
    ("kir/instruments/capability_graph.py", "_iter_source_files"):
        ("missing_source_roots",
        "корня нет -> граф строится ПУСТЫМ, и поиск по имени даёт KeyError. "
        "ОСТАВЛЕН НЕМЫМ С ДОВОДОМ 29.08.2026: это ГЕНЕРАТОР, причина живёт у "
        "вызывающего — `missing_source_roots()` называет ненайденные корни, а "
        "`Graph.reachability_unmeasurable()` останавливает читателя ШАПКОЙ "
        "отчёта до числа. Тот же уклад, что у snapshot_pins + scan_reach",),
    ("kir/instruments/relift_offline.py", "_load_envelope"):
        ("absent_side_indexes",
        "конверта нет -> «стадия не запускалась» (журнал: F-301). ОСТАВЛЕН "
        "НЕМЫМ С ДОВОДОМ 29.08.2026: прибор обязан считать и над неполным "
        "разбором, `None` ронять нельзя. Причина спрашивается соседним "
        "`absent_side_indexes()` и печатается ДО чисел отчёта",),
    ("kir/instruments/relift_offline.py", "_load_side_index"):
        ("absent_side_indexes",
        "индекса нет -> то же самое вторым входом. ОСТАВЛЕН НЕМЫМ С ДОВОДОМ "
        "29.08.2026: тот же `absent_side_indexes()` покрывает оба входа — он "
        "спрашивает ФАЙЛЫ, а не место чтения, и потому не зависит от того, "
        "каким из двух они читались",),
    ("kir/instruments/snapshot_janitor.py", "discover_snapshots"):
        ("discover_refusal",
        "корня корпуса нет -> «слепков нет», уборщику нечего делать. "
        "ОСТАВЛЕН НЕМЫМ С ДОВОДОМ 29.08.2026: ответ `[]` ронять нельзя — "
        "уборщик обязан доработать и над отсутствующим корнем. Причина "
        "спрашивается СОСЕДНИМ входом `discover_refusal()` (три исхода: нет "
        "вовсе / не каталог / каталог без слепков) и печатается ДО числа",),
    ("kir/instruments/native_share.py", "_read_census"):
        ("share_of_parse",
        "переписи в L0 нет -> пустой словарь, а не отказ. ОСТАВЛЕН НЕМЫМ С "
        "ДОВОДОМ 02.09.2026: у функции ОДИН вызывающий, и он превращает "
        "пустоту в НАЗВАННЫЙ отказ на месте — `share_of_parse` поднимает "
        "`NativeShareRefusal` («не нашлось переписи категорий … прибор НЕ "
        "СУДИЛ: считать было нечего») ДО всякого числа. Ноль отсюда наружу "
        "не выходит ни одним путём, и доля по пустой переписи не считается "
        "вовсе. Тот же уклад, что у snapshot_janitor.discover_snapshots",),
    ("kir/instruments/revit_refs.py", "find_version"):
        ("searched_places",
         "пакета этой версии в корне NuGet нет -> `continue`, и голый `None` "
         "функции читается как «эталонов Revit для 2023 не бывает», хотя это "
         "факт О ЯЩИКЕ: смотрели в двух-трёх местах и ни в одном не нашли. "
         "`None` ронять нельзя — `discover()` обязан ответить и по неполному "
         "ящику (у него один вход на шесть версий), а `describe()` рисует "
         "строку «✗» по этому же значению. Причину называет НАЗВАННЫЙ спутник "
         "в том же модуле — `searched_places()`: он перечисляет ВСЕ места, "
         "куда прибор ходил, и стоит на живом пути дважды — `require()` "
         "(`revit_refs.py:156`) вкладывает его в текст `ReferencesUnavailable`, "
         "который и печатает пропуск полосы C#-сверки "
         "(`test_connector_compiler_conformance.py:69`), и `main()` "
         "(`revit_refs.py:182`) печатает его же под каждой ненайденной "
         "версией. Внесено 08.09.2026 волной 10 вместе с местом"),
    ("kir/decompile/axes_census.py", "census"):
        ("skipped_snapshots",
        "L0 нет -> перепись отдаёт пустую, а не отказ. ОСТАВЛЕН НЕМЫМ С "
        "ДОВОДОМ 29.08.2026: `None` на один разбор ронять перепись не вправе. "
        "Причину называет спутник `skipped_snapshots()`, и пропуск ЕДЕТ В "
        "ОТЧЁТ обоими выходами — поля `asked`/`skipped` в --json и блок «В "
        "ПЕРЕПИСЬ НЕ ВОШЛИ N из M» текстом; до правки он был виден только в "
        "stderr и только без --json",),
        # 🔴 PATH FIXED ON 02.09.2026: the body moved from `kir/decompile/`
        # -> `kir/model/` in the layers wave (676f92d), and a RE-EXPORT was
        # left at the old path — importing from there works, but the
        # function is no longer DEFINED there. The debt did not change by
        # a single word, only its address changed, and the ratchet caught
        # the move with BOTH HALVES AT ONCE: "the place is no longer mute"
        # at the old path, and "the companion is not defined where it is
        # declared." Exactly what it exists for.
        ("kir/model/snapshot_io.py", "snapshot_raw_size"):
        ("kir/model/snapshot_io.py::snapshot_file_exists",
         "нет .gz -> размер 0, и ноль сравнивается с потолком как настоящий. "
         "ЗАКРЫТО СПУТНИКОМ 29.08.2026, и спутника назвала САМА докстрока "
         "функции: «отличать этот случай надлежит `snapshot_file_exists`, а "
         "не величиной». Правило было записано и НЕ СОБЛЮДЕНО на живом пути: "
         "`serving._building_index_for_turn` спрашивал размер и не спрашивал "
         "существование, отчего отсутствующий разбор проходил бюджет "
         "наблюдений как «дешёвый». Теперь спрашивает, и отказ несёт причину"),
    ("kir/decompile/journal_store.py", "load_log"):
        ("absent_log_may_hide_history",
         "журнала нет -> «ревизий нет», история здания выглядит начатой. "
         "ЗАКРЫТО СПУТНИКОМ 29.08.2026. Сам `None` здесь ВЕРЕН и различён: "
         "порча поднимает JournalError, оба потребителя печатают "
         "`journal_unreadable` против `journal_absent`. Не различались ДВА "
         "СМЫСЛА самого «файла нет»: здание читается впервые либо журнал "
         "потерян. Изнутри файла их не отличить, снаружи видно — "
         "`absent_log_may_hide_history()` ищет разборы ТОГО ЖЕ документа в "
         "корпусе, и подозрение едет полем `history_may_be_lost` в ответе "
         "прогона, не меняя самого ответа"),
    # 🔴 STRUCK OFF ON 31.08.2026: `graph_clash_query._join_index_on_disk`
    # WAS DELETED by the codex wave — the query now goes through the
    # canonical graph, and the index is supplied by
    # `graph_store.build_graph_for_run`. No knowledge was lost: the same
    # `None` and the same distinction live under the line
    # ("kir/decompile/graph_store.py", "joins_on_disk") below, and this was
    # a SECOND entry point to one distinction — now only one entry point
    # remains. The ratchet only allows the list to shrink; this is its
    # legitimate shrinkage, and it caught the ghost by itself, not by eye.
    ("kir/decompile/axes_census.py", "_tree_kinds"):
        ("artifact_absent_note",
         "дерева нет -> «родов в разборе нет». ЗАКРЫТО СПУТНИКОМ 29.08.2026: "
         "строка отчёта про виды узлов L3 просто ИСЧЕЗАЛА, и пропавшая строка "
         "— та же тишина, что пропавшее число. `artifact_absent_note()` "
         "печатается на её месте"),
    ("kir/decompile/axes_census.py", "_verify_summary"):
        ("artifact_absent_note",
         "сводки нет -> «сверка не расходится». ЗАКРЫТО ТЕМ ЖЕ "
         "`artifact_absent_note()`: он спрашивает ИМЯ ФАЙЛА, а не вход. Здесь "
         "причина печаталась и раньше, но своим текстом — два похожих ответа "
         "разъехались бы, и один замолчал бы снова"),
    ("kir/serving.py", "_metadata_from_l0_header"):
        ("kir/serving.py::_metadata_from_passport",
         "потока L0 нет -> «у разбора нет метаданных документа», а не "
         "«разбор не читался». 🔴 СПУТНИК ЗДЕСЬ — ПОЛУПРАВДА, И НАЗВАНА ОНА "
         "ПОЛУПРАВДОЙ. Ответ различают ДВА потребителя, и по-разному: "
         "re-lift откатывается на `_metadata_from_passport()` и при обоих "
         "пустых отказывает именем `no_metadata` — это спутник, он есть и "
         "зовётся; проба чтения возвращает нули ВМЕСТЕ с соседним ключом "
         "`measured: False` — а ключ формат выразить не может, и ослаблять "
         "ради него проверку «спутника кто-то ЗОВЁТ» нельзя: она держит все "
         "восемнадцать записей и стоит против E-7. Вторую половину держит "
         "СТОРОЖ `МетаданныхНетНеЗначитЧтениеПолное::"
         "test_the_probe_carries_the_measured_flag`, чей контроль-FAIL "
         "краснеет на снятом ключе. Без `measured` пара «is_partial_read "
         "False, worksets_closed 0» читается как факт о ЗДАНИИ вместо факта "
         "о ЗАМЕРЕ"),
    ("kir/instruments/capability_graph.py", "parse_env_file"):
        ("missing_env_files",
         "файла окружения нет -> «переменных не объявлено». ЗАКРЫТО СПУТНИКОМ "
         "29.08.2026: `{}` ронять нельзя — инвентарь обязан собраться и без "
         "`.env`. Цена узкая и точная: имена флагов приходят из ТРЁХ "
         "источников, и флаг, который ЧИТАЮТ, найдётся без файлов. Пропадает "
         "ровно тот, что ОБЪЯВЛЕН и НЕ ЧИТАЕТСЯ НИКЕМ — то есть не строка "
         "отчёта, а целый РОД находки, ради которого прибор и написан. "
         "`missing_env_files()` называет оба файла поимённо в шапке отчёта"),
    ("kir/course/building.py", "wall_widths"):
        ("missing_width_runs",
         "слепок пропущен -> замер толщин молча снят с меньшей совокупности. "
         "ЗАКРЫТО СПУТНИКОМ 29.08.2026: `continue` ронять нельзя — замер "
         "обязан собраться по тому, что есть. `missing_width_runs()` называет "
         "недостающие прогоны поимённо, и урок «дом» печатает их ДО чисел "
         "вместе с `sample_too_small_reason()`, который отличает «замеров "
         "нет вовсе» от «замеров меньше четырёх»"),
    ("kir/decompile/graph_store.py", "joins_on_disk"):
        ("kir/decompile/building_graph.py::graph_from_l0",
         "индекса нет -> «соединений нет»; тот же ноль, другой потребитель. "
         "ОТВЕЧЕНО В ДРУГОМ МОДУЛЕ, и связь ДОКАЗАНА сквозным замером "
         "29.08.2026: индекс отсутствует на диске -> build_graph_for_run "
         "передаёт joins=None -> graph_from_l0 кладёт 'joins' в "
         "census.sources_absent -> unmeasured_relations() называет joined_to "
         "и joined_at_end -> pipeline печатает их в квитанции стадии. "
         "«Соединений нет» и «про соединения не спросили» РАЗЛИЧАЮТСЯ уже "
         "сегодня; правка ядра не нужна, нужен сторож этой связи"),
    ("kir/decompile/graph_store.py", "load_graph"):
        ("kir/decompile/building_graph.py::graph_from_l0",
         "файла графа нет -> «граф здания пуст», а не «граф не строился». "
         "ОТВЕЧЕНО ТАМ ЖЕ: `None` здесь значит РОВНО «артефакта нет» (порча, "
         "чужая схема и несходящаяся перепись дают типизированный ОТКАЗ, а не "
         "None — так написано в докстроке и так проверено), а пустоту графа "
         "от неизмеренности отличает census.sources_absent через "
         "graph_from_l0"),
    ("kir/decompile/snapshot_pins.py", "_iter_python_files"):
        ("scan_reach",
        "корня нет -> обход пуст; ЧАСТИЧНО ЗАКРЫТО 29.08 через scan_reach(), "
        "сам генератор остаётся немым намеренно — причина живёт у вызывающего",),
}


#: 🔴 THE FOURTH LIST, SET UP ON 29.08.2026, AND SET UP BECAUSE OF AN
#: INSTRUMENT ERROR THAT I MYSELF INTRODUCED AN HOUR EARLIER.
#:
#: `test_every_companion_is_called_on_a_live_path` (E-36) rightly removed
#: four records whose companion was called only by tests. But it measured
#: calls ONLY INSIDE `/opt/kir` — and so it declared as debt a place that
#: IS COVERED on a live path, only that path is outside:
#:
#:     /opt/kukai-rebuild1/backend/kukai/api/viewer.py:91
#:         from kir.viewer.scene import corpus_unreachable_reason, list_runs
#:     /opt/kukai-rebuild1/backend/kukai/api/viewer.py:99
#:         reason = corpus_unreachable_reason()
#:         if reason: out["unreachable"] = reason
#:
#: This is `E-32` WITH THE OPPOSITE SIGN: there, the KIR instrument
#: silently DEPENDED on the neighboring tree; here it silently FAILS TO
#: SEE it. One split, two opposite errors of one instrument.
#:
#: Putting this into `ANSWERED_ELSEWHERE` IS NOT ALLOWED: that list means
#: "verified HERE," and the record would be just as false as the four
#: removed today. Keeping it in `MUTE_SOURCES` IS NOT ALLOWED either: the
#: debt would be made up, and made-up gates cost more than missing ones.
#:
#: 🔴 THE COST OF THIS CATEGORY, SAID OUT LOUD: A RECORD HERE IS NOT GUARDED
#: BY A NUMBER. KIR is environment-agnostic and has no right to walk into
#: the host's tree EVEN FOR THE SAKE OF CHECKING, so "the host really does
#: call it" is not verified by anything from here — what is verified is
#: only that the record NAMES the place to go look. The honest answer here
#: is not "verified" but "cannot be verified from here, here is where."
#: That is why the category must remain SMALL, and every new entry in it is
#: the subject of a separate decision, not a transfer of convenience. This
#: is guarded by the ceiling below.
#:
#: 🔴 THE COMMAND BY WHICH THIS ARGUMENT IS RECHECKED (not just its wording).
#: An argument in the list is also a number about a MOVING subject: it goes
#: stale exactly like the headline counter, and once during the shift it
#: went stale from a SINGLE commit by a neighbor. Here the tree cannot
#: check itself, so next to it stands what a human uses to do the check:
#:
#:     grep -n "corpus_unreachable_reason" \
#:       /opt/kukai-rebuild1/backend/kukai/api/viewer.py
#:
#: Empty — the record has become false, and the place returns to
#: `MUTE_SOURCES`.
#:
#: The value is (companion, host "path:line", argument).
ANSWERED_BY_A_HOST: dict[tuple[str, str], tuple[str, str, str]] = {
    ("kir/viewer/scene.py", "list_runs"):
        ("corpus_unreachable_reason",
         "/opt/kukai-rebuild1/backend/kukai/api/viewer.py:99",
         "корня корпуса нет -> «разборов нет»; `corpus_unreachable_reason()` "
         "зовётся на живом пути, но ЕДИНСТВЕННЫЙ живой потребитель — маршрут "
         "КУКАЯ, и причина едет читателю ключом `unreachable` рядом со "
         "списком. Внутри KIR вызовов нет и быть не должно: витрина здесь "
         "библиотека, а хозяин у неё снаружи"),
}

#: 🔴 THE CEILING OF THE FOURTH LIST. The number was taken by RUNNING this
#: commit (exactly one record), not assigned in advance. It can be raised
#: — but by a SEPARATE commit and with an argument, because every record
#: here is a dispensation that THIS TREE CANNOT VERIFY. A list growing
#: silently would become the place where everything that could not be
#: proven gets dumped.
HOST_ANSWERED_CEILING = 1


#: 🔴 THE THIRD CLOSED LIST, SET UP ON 29.08.2026 BY THE LEAD'S DECISION,
#: SET UP BECAUSE TWO WERE NOT ENOUGH.
#:
#: `MUTE_SOURCES` is DEBT: it gets fixed, it must trend to zero.
#: `ANSWERED_ELSEWHERE` is DONE: a bare value by necessity, the cause is
#: named by a NAMED companion.
#: Here is a DECISION: the bare value IS the answer, there is no companion
#: and there cannot be one.
#:
#: Keeping such places in the debt is wrong: a debt that cannot be paid
#: off is the same thing as a test that is always red — it stops meaning
#: anything. Recording them among the companions would be lying about a
#: companion's existence, and check (a) catches this.
#:
#: 🔴 THE MAIN RISK OF THIS LIST IS NAMED HERE, NOT LEFT IMPLIED: it becomes
#: the place where anything inconvenient gets dumped. Guarding against
#: this: a FLOOR (`SILENCE_FLOOR` below) and a requirement of TWO fields in
#: every argument:
#:   (1) WHAT EXACTLY the bare value means — "None = cache miss," not
#:       "unknown";
#:   (2) WHY a named cause would be NOISE, not a benefit.
#: A record that cannot state (1) is a debt, not a decision.
SILENCE_IS_RIGHT: dict[tuple[str, str], tuple[str, str]] = {
    ("kir/decompile/lift_cache.py", "_read_entry"):
        ("None ЗНАЧИТ РОВНО «в кэше этого нет» — промах, а не неизвестность. "
         "Кэш на то и кэш: отсутствие записи есть его штатный, самый частый "
         "ответ, и вызывающий на него обязан посчитать заново",
         "Причина здесь была бы ШУМОМ ровно потому, что промах — норма: "
         "строка «записи нет» на каждом промахе утопила бы отчёт, а редкий "
         "случай нечитаемой записи она бы не выделила. Отличать порчу "
         "надлежит чтением, а не отсутствием"),
    ("kir/compile_cache.py", "_disk_get"):
        ("None ЗНАЧИТ РОВНО «этого ключа в кэше нет» — промах, штатный и "
         "самый частый ответ кэша. Вызывающий на него обязан посчитать "
         "заново, и он это делает: другого поведения у промаха не бывает",
         "Причина была бы ШУМОМ ровно потому, что промах — норма: строка на "
         "каждом промахе утопила бы отчёт и не выделила бы редкую нечитаемую "
         "запись. Порча здесь уже отделена иначе — она пишет в лог отладки, "
         "а не притворяется отсутствием"),
    ("kir/corpus_catalog.py", "load_catalog"):
        ("Пропуск ЗНАЧИТ «эта запись каталога — не разбор»: не каталог. Рядом "
         "с разборами лежат служебные каталоги корпуса, и разбором ни один "
         "файл не притворяется",
         "Причина была бы ШУМОМ на КАЖДОМ прогоне: каталог уже несёт "
         "`missing` для недостающих СТАДИЙ настоящих разборов, и жалоба на "
         "посторонние файлы утопила бы в ней единственное, ради чего список "
         "заведён"),
    # 🔴 FOUR PLACES OF ONE SHAPE, ADDED ON 08.09.2026 (wave 10). What they
    # share is not convenience but OWNERSHIP: each reads a file that IS
    # WRITTEN BY THIS SAME MODULE and no one else — so the file's absence
    # is a fact ABOUT THE SUBJECT ("nothing was written"), not a fact
    # ABOUT THE INSTRUMENT ("there was nothing to look at"), and it is
    # exactly this difference that separates a decision from a debt
    # throughout the file. This is not checked by a word: each one names
    # the writer function of the same module.
    ("kir/decompile/capture_edit.py", "_has_edits"):
        ("`False` ЗНАЧИТ РОВНО «проигрывать нечего»: файл правок `_EDITS_NAME` "
         "кладёт в каталог ТОЛЬКО `save()` этого же модуля, и до первого "
         "сохранения его не бывает ни у одного разбора корпуса. Пустой файл "
         "правкой тоже не считается — вторая строка ветки как раз про это",
         "Причина была бы ШУМОМ на КАЖДОМ открытии здания: до первого `save` "
         "правок нет ни у одного разбора, и строка «файла правок нет» ехала бы "
         "на каждом `open_capture`, утопив в себе единственный интересный "
         "случай — ИСПОРЧЕННЫЙ файл правок, который этот же модуль уже "
         "называет отказом `edits_file_corrupt` с адресом строки"),
    ("kir/decompile/capture_edit.py", "_apply_saved_edits"):
        ("Возврат без работы ЗНАЧИТ РОВНО «сохранённых правок нет»: тот же "
         "файл `_EDITS_NAME`, тот же единственный писатель `save()` "
         "(`capture_edit.py:1699`). Спрашивают его два места одного подъёма: "
         "наличие — здесь (`:379`), непустоту — `_has_edits` (`:578`)",
         "Причина была бы ШУМОМ по той же причине, что у `_has_edits`, и ХУЖЕ: "
         "об одном и том же отсутствующем файле за один подъём здания "
         "прозвучали бы ДВА голоса. Всё, ради чего функция написана, — назвать "
         "ПОРЧУ: отказы `edits_file_corrupt` и `unsupported_edit_schema` несут "
         "код, адрес `<файл>:<строка>` и повод, и их не должно быть слышно за "
         "жалобой на штатное отсутствие"),
    ("kir/emit_transaction_unit.py", "_read_reservation"):
        ("`None` ЗНАЧИТ РОВНО «резервирования не было»: файл создаёт только "
         "`_create_reservation` этого же модуля и только через `O_EXCL`, то "
         "есть его отсутствие — единственный штатный вход в первую запись. "
         "Всякая эмиссия единицы транзакции начинается с этого `None`",
         "Причина была бы ШУМОМ ровно потому, что отсутствие — НАЧАЛО хода, а "
         "не сбой: она печаталась бы перед каждой первой эмиссией и ничего не "
         "добавляла бы к тому, что уже сказано схемой. Опасный случай здесь "
         "другой — файл ЕСТЬ, но чужой схемы, и он уже назван отказом "
         "`unknown_reservation_schema` строкой ниже"),
    ("kir/mcp/live.py", "_pending_load"):
        ("`{}` ЗНАЧИТ РОВНО «неразрешённых отправок нет»: файл пишет только "
         "`_pending_save` этого же модуля, и до первой неподтверждённой "
         "отправки его не существует. Пустой словарь здесь — не «не смогли "
         "прочитать», а «нечего разрешать», и дверь на этом открыта верно",
         "Причина была бы ШУМОМ на КАЖДОМ вызове живой двери: обычное "
         "состояние — отсутствие висящих отправок, и строка о нём шла бы "
         "потоком. Случай, ради которого функция написана, — файл ЕСТЬ и "
         "ИСПОРЧЕН, и он уже поднимает `PendingStoreError` тремя разными "
         "проверками ниже; жалоба на штатное отсутствие заглушила бы их"),
    ("kir/decompile/journal_store.py", "absent_log_may_hide_history"):
        ("Пропуск ЗНАЧИТ «эта запись каталога — не разбор»: не каталог либо "
         "служебное имя (`_journals`, `_evidence`). Источника здесь никто не "
         "обещал, и его отсутствие ничем не грозит",
         "Причина была бы ШУМОМ: жалоба на каждый служебный каталог рядом с "
         "разборами — это шум на КАЖДОМ прогоне, и в нём потерялось бы "
         "единственное, ради чего функция написана. Я дважды переписывал "
         "форму этой ветки, чтобы её не заметил сканер, и остановился: "
         "подбирать вид вместо поведения — обход прибора, а не починка"),
}

#: THE FLOOR OF THE THIRD LIST, by name. The number of lines here is NOT a
#: guard: renaming a place, swapping one record for another, and dumping
#: something inconvenient here do not move it. The list grows only
#: deliberately — a new line HERE, in a separate commit, with an argument.
#: Taken from the audit registry's ratchet, where the same trick closed the
#: same hole: what must be counted is IDENTITIES, not quantity.
SILENCE_FLOOR: frozenset = frozenset({
    ("kir/compile_cache.py", "_disk_get"),
    ("kir/corpus_catalog.py", "load_catalog"),
    ("kir/decompile/lift_cache.py", "_read_entry"),
    ("kir/decompile/journal_store.py", "absent_log_may_hide_history"),
    # Wave 10, 08.09.2026 — four places where a file is read by THE SAME
    # MODULE that writes it (the argument is at each record above). Added
    # by name and in one move: a partial floor would leave the list
    # growing silently.
    ("kir/decompile/capture_edit.py", "_has_edits"),
    ("kir/decompile/capture_edit.py", "_apply_saved_edits"),
    ("kir/emit_transaction_unit.py", "_read_reservation"),
    ("kir/mcp/live.py", "_pending_load"),
})

class NoNewMuteSourceMayBeIntroduced(unittest.TestCase):
    """Ratchet: a new mute branch cannot be added, a fixed one must be struck off."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mute, cls.named = scan_package()

    def test_the_scan_is_not_vacuous(self) -> None:
        """THE DENOMINATOR FIRST. An empty traversal would pass everything
        below vacuously, and "0 mute out of 0" reads as "everything is
        fine"."""
        self.assertGreaterEqual(
            len(self.mute) + self.named, 40,
            "обход нашёл меньше сорока ветвей «источника нет» — это "
            "заявление о ХОДОКЕ, а не о дереве")
        self.assertGreaterEqual(
            self.named, 20,
            "обход не нашёл двадцати ветвей, называющих причину, — а именно "
            "они положительный контроль: закон в дереве уже соблюдается")

    def test_no_new_mute_source(self) -> None:
        unaccounted = sorted(self.mute - set(MUTE_SOURCES)
                             - set(ANSWERED_ELSEWHERE)
                             - set(ANSWERED_BY_A_HOST)
                             - set(SILENCE_IS_RIGHT))
        self.assertEqual(
            unaccounted, [],
            "ветка «источника нет» вернула ГОЛОЕ значение, и это не решено: "
            + ", ".join(f"{f}::{fn}" for f, fn in unaccounted)
            + ". Либо назови причину (образец — install_root_refusal / "
              "corpus_unreachable_reason / snapshot_pins.scan_reach), либо "
              "внеси место в MUTE_SOURCES с тем, за что его ноль примут")

    def test_the_ledger_holds_no_ghosts(self) -> None:
        """A dispensation whose place has been fixed is a dead line, and it
        makes the journal less truthful with every passing day. This is
        exactly the ratchet: the list has the right only to shrink."""
        ghosts = sorted((set(MUTE_SOURCES) | set(ANSWERED_ELSEWHERE)
                         | set(ANSWERED_BY_A_HOST)
                         | set(SILENCE_IS_RIGHT)) - self.mute)
        self.assertEqual(
            ghosts, [],
            "MUTE_SOURCES называет места, которые больше не немы — вычеркни: "
            + ", ".join(f"{f}::{fn}" for f, fn in ghosts))

    def test_every_entry_says_what_the_zero_is_mistaken_for(self) -> None:
        """A cause without a subject is decoration. The line must name
        WHAT the consumer mistakes this bare zero for."""
        both = dict(MUTE_SOURCES)
        both.update({k: v[1] for k, v in ANSWERED_ELSEWHERE.items()})
        # SILENCE_IS_RIGHT is deliberately NOT included here: there, the
        # argument answers not "what the zero is mistaken for" but "what
        # this zero MEANS" — a different shape and a different question,
        # with its own two checks below.
        for key, why in sorted(both.items()):
            with self.subTest(site=key):
                self.assertIn("->", why, f"{key}: строка не называет, за что "
                                         f"принимают ноль этой ветки")
                self.assertGreaterEqual(len(why), 30, f"{key}: причина пуста")


class TheCompanionMustExistAndBeCalled(unittest.TestCase):
    """🔴 THE COMPANION MUST NOT ONLY EXIST, BUT ALSO SOUND.

    `ANSWERED_ELSEWHERE` permits a bare zero where the answer must not be
    dropped — at the cost of a named companion. A dispensation without a
    check is worth zero: a dictionary line can outlive both the
    companion's rename and its death.

    The second condition (someone CALLS it) matters more than the first.
    A field nobody reads is E-7 all over again: the closure instrument was
    written on 14.08, existed, and was called by NO ONE, while the list
    looked closed.

    🔴 AND THAT TURNED OUT NOT TO BE ENOUGH (E-36, 29.08.2026). "Someone
    calls it" was computed over the WHOLE package, TESTS INCLUDED — and
    through this hole slipped FOUR records out of twenty:
    `index_absent_reason` (two entry points), `corpus_unreachable_reason`
    and `resumable_absence_reason` were called by NO live path, only by
    tests. A companion called only by its own test proves exactly one
    thing — that it RUNS; its cause never reaches the consumer, and that
    is E-7, word for word.

    The worst of the four cases shows exactly why the condition is shaped
    this way: the sole caller of `index_absent_reason` (`test_course.py:97`)
    sits INSIDE the branch `if abs(got - m.value) > 0.051`. That is, the
    cause is only asked for once the numbers have already diverged, while
    on the live path a bare `{}` silently goes into the lesson — and the
    course's numbers are read by the MODEL, taking them for measurements of
    real buildings.

    🔴 WHAT THIS CHECK CANNOT DO IS NAMED UP FRONT, like everything else in
    this file: it tells TEST from NOT-A-TEST by the file's PATH, not by
    parsing which branch of product code the call sits in. A companion
    called from the product inside a dead branch is invisible to it. The
    boundary is named, not hidden: a false alarm costs more than a miss,
    and this undercount is caught by the next measurement, not by silence.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.calls: set = set()
        #: Names called OUTSIDE tests. The same selection as
        #: `scan_package` uses: two places of truth about "what counts as
        #: a test here" would drift apart.
        cls.live_calls: set = set()
        cls.defined: dict = {}
        for path in sorted(PACKAGE.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, OSError):
                continue
            rel = str(path.relative_to(PACKAGE.parent))
            is_test = ("tests" in path.parts or path.name.startswith("test_"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    cls.defined.setdefault(node.name, set()).add(rel)
                elif isinstance(node, ast.Call):
                    fn = node.func
                    name = (fn.id if isinstance(fn, ast.Name)
                            else fn.attr if isinstance(fn, ast.Attribute)
                            else None)
                    if name:
                        cls.calls.add(name)
                        if not is_test:
                            cls.live_calls.add(name)

    def test_the_scan_is_not_vacuous(self) -> None:
        """THE DENOMINATOR FIRST: an empty traversal would credit any companion at all."""
        self.assertGreaterEqual(len(self.defined), 500)
        self.assertGreaterEqual(len(self.calls), 500)
        # The NEW set has ITS OWN denominator. An empty `live_calls` would
        # make the live-path check go red ALWAYS, and that is not a guard
        # but noise; a denominator taken from one set says nothing about
        # another.
        self.assertGreaterEqual(
            len(self.live_calls), 500,
            "обход не нашёл и пятисот вызовов ВНЕ тестов — это заявление о "
            "ходоке, а не о дереве")
        self.assertLess(
            len(self.live_calls), len(self.calls),
            "вызовов вне тестов оказалось не меньше, чем всего: отбор "
            "«что здесь тест» не сработал ни на одном файле")

    def test_every_companion_exists_where_it_is_declared(self) -> None:
        """A companion lives either in the same module, or in a NAMED
        foreign one.

        The second case is not a relaxation but precision: `graph_store`
        returns `None`, and `GraphCensus.sources_absent` in
        `building_graph` is what answers for it. Writing "the companion is
        nearby" there would be lying about the PLACE of the answer, and
        the place is what the reader will go check.
        """
        for (module, _fn), (companion, _why) in sorted(
                ANSWERED_ELSEWHERE.items()):
            with self.subTest(companion=companion):
                home, _, name = companion.rpartition("::")
                where = self.defined.get(name, set())
                self.assertIn(
                    home or module, where,
                    f"спутник {name}() не определён в {home or module}: "
                    f"разрешение ссылается на имя, которого там нет")

    def test_every_companion_is_called_by_someone(self) -> None:
        for (module, _fn), (companion, _why) in sorted(
                ANSWERED_ELSEWHERE.items()):
            with self.subTest(companion=companion):
                self.assertIn(
                    companion.rpartition("::")[2], self.calls,
                    f"спутник {companion}() НЕ ЗОВЁТСЯ НИКЕМ — причина, "
                    f"которую никто не спрашивает, молчит так же, как её "
                    f"отсутствие (E-7)")

    def test_every_companion_is_called_on_a_live_path(self) -> None:
        """🔴 "IS CALLED" MEANS CALLED BY MORE THAN JUST ITS OWN TEST (E-36).

        The check above credited a call from ANYWHERE, tests included, and
        four records slipped through it. A companion called only by its
        own test proves that it RUNS — and says nothing about whether the
        cause reaches the consumer. A dispensation for a bare zero is
        bought by a cause that is DELIVERED, not one that merely exists.
        """
        for (module, _fn), (companion, _why) in sorted(
                ANSWERED_ELSEWHERE.items()):
            with self.subTest(companion=companion):
                self.assertIn(
                    companion.rpartition("::")[2], self.live_calls,
                    f"спутник {companion}() зовётся ТОЛЬКО ИЗ ТЕСТОВ — на "
                    f"живом пути {module} по-прежнему отдаёт голое значение "
                    f"молча. Либо позови спутника оттуда, где голый ноль "
                    f"РОЖДАЕТСЯ, либо верни место в MUTE_SOURCES: долг, "
                    f"названный честно, лучше закрытия, которого нет")

    def test_the_extractor_of_companion_names_works(self) -> None:
        """THE DENOMINATOR OF THE REVERSE CHECK. It looks for the
        companion's name IN THE TEXT of the argument; a broken expression
        would find NOTHING and would always be green — exactly the unfit
        control this whole file is written against."""
        self.assertEqual(
            _COMPANION_IN_TEXT.findall(
                "нет -> ноль; `foo_reason()` рядом, но `bar()` не в счёт"),
            ["foo_reason", "bar"],
            "выражение перестало находить имена — обратная проверка ослепла")

    def test_a_debt_whose_companion_went_live_must_move(self) -> None:
        """🔴 THE RATCHET MUST MOVE IN BOTH DIRECTIONS (29.08.2026).

        `test_every_companion_is_called_on_a_live_path` catches ONE
        direction — "declared closed but not actually closed." The reverse
        — "CLOSED, BUT STILL LISTED AS DEBT" — caught nothing, and the debt
        could only be honest going up: it does not go down by itself, it is
        moved by hand, and hands forget. Bought by an actual case:
        `("kir/a5_recovery.py", "find_resumable")` sat in the debt with the
        argument "the companion is called ONLY from tests," which became
        false from a SINGLE commit by a neighbor (`3976e0b` wired
        `resumable_absence_reason()` into `kir/serving.py:8240`).

        An argument in the list is also a NUMBER ABOUT A MOVING SUBJECT,
        and it goes stale the same way the headline counters do. Wherever
        an argument can be made to check itself, it must check itself.

        The companion is looked up by the name given IN THE ARGUMENT ITSELF
        (`` `name()` ``), and is credited only if it is defined IN THE SAME
        module as the mute place. What the check CANNOT DO is named: an
        argument that does not name a companion by name is invisible to it
        — but such an argument does not claim a companion exists either.
        """
        for (module, fn), why in sorted(MUTE_SOURCES.items()):
            for name in _COMPANION_IN_TEXT.findall(why):
                if module not in self.defined.get(name, set()):
                    continue
                with self.subTest(site=f"{module}::{fn}", companion=name):
                    self.assertNotIn(
                        name, self.live_calls,
                        f"{module}::{fn} числится ДОЛГОМ, а спутник {name}() "
                        f"уже стоит на живом пути — перенеси запись в "
                        f"ANSWERED_ELSEWHERE с доводом, называющим ЗОВУЩЕГО и "
                        f"коммит. Долг, не идущий вниз, врёт так же, как долг, "
                        f"не идущий вверх")

    def test_the_two_lists_do_not_overlap(self) -> None:
        """A place is either debt or resolved by a companion. It cannot be
        both: two records about the same place would drift apart, and
        whichever is read first would win."""
        both = sorted(set(MUTE_SOURCES) & set(ANSWERED_ELSEWHERE))
        self.assertEqual(both, [], f"место в обоих списках сразу: {both}")

    def test_the_companion_is_named_in_its_own_reason(self) -> None:
        """A reader of the dictionary must see the companion's name IN THE
        TEXT, not only in a neighboring column: the text travels into
        reports and is quoted on its own."""
        for key, (companion, why) in sorted(ANSWERED_ELSEWHERE.items()):
            with self.subTest(site=key):
                self.assertIn(companion.rpartition("::")[2], why,
                              f"{key}: довод не называет спутника поимённо")


class AnswerThatLivesOutsideThisTree(unittest.TestCase):
    """🔴 THE FOURTH LIST: THE COMPANION IS CALLED, BUT THE HOST IS OUTSIDE KIR.

    What is checked here is exactly what THIS TREE CAN check, and NO MORE.
    Checkable: the companion exists in KIR where it is declared; the
    record NAMES the host's place by path and line; the list has not grown
    unchecked.

    🔴 NOT CHECKED, AND NEVER WILL BE: whether the host really calls it.
    KIR is environment-agnostic and has no right to walk into the host's
    tree even for the sake of checking — opening that file would mean
    setting up exactly the dependency that `E-32` and the whole split stand
    against. This is an UNDERCOUNT, and it is named, not hidden: the record
    here rests on a WORD, backed by an address, and the cost of that word
    is the reason the category must remain small.
    """

    def test_the_list_stays_small(self) -> None:
        """A ceiling taken by running, not assigned in advance."""
        self.assertLessEqual(
            len(ANSWERED_BY_A_HOST), HOST_ANSWERED_CEILING,
            "четвёртый список вырос молча. Каждая запись здесь — разрешение, "
            "которое это дерево проверить НЕ МОЖЕТ; расти он вправе только "
            "отдельным коммитом, поднимающим потолок вместе с доводом")

    def test_every_companion_exists_in_this_tree(self) -> None:
        """The companion must be OURS: outside, it is called by our name."""
        defined: dict = {}
        for path in sorted(PACKAGE.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, OSError):
                continue
            rel = str(path.relative_to(PACKAGE.parent))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defined.setdefault(node.name, set()).add(rel)
        self.assertGreaterEqual(len(defined), 500, "обход пуст — знаменатель")
        for (module, _fn), (companion, _where, _why) in sorted(
                ANSWERED_BY_A_HOST.items()):
            with self.subTest(companion=companion):
                self.assertIn(
                    module, defined.get(companion, set()),
                    f"спутник {companion}() не определён в {module}: наружу "
                    f"нечего звать")

    def test_every_entry_names_where_to_look(self) -> None:
        """The address is the only thing that substitutes for a check here.
        A record without a path and a line is indistinguishable from "we
        think someone calls it over there"."""
        for key, (companion, where, why) in sorted(ANSWERED_BY_A_HOST.items()):
            with self.subTest(site=key):
                head, _, line = where.rpartition(":")
                self.assertTrue(head.startswith("/"),
                                f"{key}: путь хозяина не абсолютный: {where}")
                self.assertFalse(
                    head.startswith(str(TREE) + "/"),
                    f"{key}: назван путь ВНУТРИ этого дерева ({where}) — тогда "
                    f"место проверяемо здесь, и запись обязана жить в "
                    f"ANSWERED_ELSEWHERE, а не тут")
                self.assertTrue(line.isdigit(),
                                f"{key}: строка хозяина не названа: {where}")
                self.assertIn("->", why, f"{key}: не сказано, за что "
                                         f"принимают голое значение")
                self.assertIn(companion, why,
                              f"{key}: довод не называет спутника поимённо")


class SilenceDecidedIsNotSilenceForgotten(unittest.TestCase):
    """🔴 THE THIRD LIST MUST BE A DECISION, NOT A DUMPING GROUND.

    A place where the bare value IS the answer never needs fixing — but
    exactly for that reason it is convenient to dump inconvenient things
    here: a record here closes the question forever and demands nothing in
    return.

    Guarding against this: three things — a FLOOR by name (the line count
    is not a guard — it does not change from renaming a place or swapping
    one record for another), TWO mandatory fields in the argument, and
    pairwise non-overlap of the lists.
    """

    def test_the_three_lists_do_not_overlap_pairwise(self) -> None:
        m, a, r = set(MUTE_SOURCES), set(ANSWERED_ELSEWHERE), set(SILENCE_IS_RIGHT)
        h = set(ANSWERED_BY_A_HOST)
        for left, right, names in ((m, a, "долг/спутник"),
                                   (m, r, "долг/молчание"),
                                   (a, r, "спутник/молчание"),
                                   (m, h, "долг/хозяин"),
                                   (a, h, "спутник/хозяин"),
                                   (r, h, "молчание/хозяин")):
            with self.subTest(pair=names):
                self.assertEqual(sorted(left & right), [],
                                 f"{names}: место в двух списках сразу — "
                                 f"две записи об одном месте разъедутся, и "
                                 f"победит та, что прочтут первой")

    def test_every_entry_says_what_the_bare_value_means(self) -> None:
        """Field (1). A record that cannot say WHAT the bare value means is
        a debt, not a decision."""
        for key, (means, _why) in sorted(SILENCE_IS_RIGHT.items()):
            with self.subTest(site=key):
                self.assertGreaterEqual(
                    len(means), 60,
                    f"{key}: не сказано, ЧТО ИМЕННО значит голое значение")
                self.assertRegex(
                    means, r"ЗНАЧИТ|значит",
                    f"{key}: довод обязан НАЗВАТЬ смысл, а не описать место")

    def test_every_entry_says_why_a_reason_would_be_noise(self) -> None:
        """Field (2). Without it, a record reads as "did not want to fix it"."""
        for key, (_means, why) in sorted(SILENCE_IS_RIGHT.items()):
            with self.subTest(site=key):
                self.assertGreaterEqual(len(why), 60, f"{key}: довод пуст")
                self.assertIn(
                    "ШУМ", why,
                    f"{key}: не сказано, ПОЧЕМУ названная причина была бы "
                    f"шумом, а не пользой")

    def test_the_floor_holds_by_name_not_by_count(self) -> None:
        """🔴 THE FLOOR BY NAME. A line count is not a guard: renaming a
        place and swapping one record for another do not change it —
        exactly the hole closed today in the audit registry's ratchet."""
        added = sorted(set(SILENCE_IS_RIGHT) - SILENCE_FLOOR)
        self.assertEqual(
            added, [],
            "в список «молчание верно» внесено место, которого нет в полу: "
            + ", ".join(f"{f}::{fn}" for f, fn in added)
            + ". Список растёт только осознанно — строкой в SILENCE_FLOOR, "
              "отдельным коммитом, с доводом")
        gone = sorted(SILENCE_FLOOR - set(SILENCE_IS_RIGHT))
        self.assertEqual(
            gone, [],
            "из списка «молчание верно» пропало место, стоящее в полу: "
            + ", ".join(f"{f}::{fn}" for f, fn in gone)
            + ". Решение отменяют явно, а не потерей строки")


class TheInstrumentItselfCanFail(unittest.TestCase):
    """FAIL CONTROL. An instrument that does not go red does not hold the ratchet."""

    def test_a_bare_return_IS_a_finding(self) -> None:
        mute, named = scan_source(
            "def load(p):\n"
            "    if not p.exists():\n"
            "        return []\n"
            "    return read(p)\n", "проба.py")
        self.assertEqual(mute, {("проба.py", "load")})
        self.assertEqual(named, 0)

    def test_a_named_cause_is_NOT_a_finding(self) -> None:
        mute, named = scan_source(
            "def load(p):\n"
            "    if not p.exists():\n"
            "        return [], f'корпуса нет: {p}'\n"
            "    return read(p), ''\n", "проба.py")
        self.assertEqual(mute, set())
        self.assertEqual(named, 1)

    def test_a_raise_is_NOT_a_finding(self) -> None:
        mute, _ = scan_source(
            "def load(p):\n"
            "    if not p.is_dir():\n"
            "        raise Missing(p)\n"
            "    return 1\n", "проба.py")
        self.assertEqual(mute, set())

    def test_a_continue_inside_a_loop_IS_a_finding(self) -> None:
        """`continue` loses an element just as silently as `return` loses the whole answer."""
        mute, _ = scan_source(
            "def walk(paths):\n"
            "    for p in paths:\n"
            "        if not p.is_file():\n"
            "            continue\n"
            "        yield p\n", "проба.py")
        self.assertEqual(mute, {("проба.py", "walk")})

    def test_the_key_survives_a_line_shift(self) -> None:
        """The key is (file, function). A shift in line numbers has no
        right to change it, otherwise the journal would go stale from any
        edit further up the file."""
        body = ("def load(p):\n"
                "    if not p.exists():\n"
                "        return None\n")
        first, _ = scan_source(body, "проба.py")
        shifted, _ = scan_source("# сдвиг\n# ещё\n" + body, "проба.py")
        self.assertEqual(first, shifted)


if __name__ == "__main__":
    unittest.main()
