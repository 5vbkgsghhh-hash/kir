"""KIR diagnostics — the typed error contract (SPEC_V1 §6, §12.7).

Every stage failure is a Diagnostic, never a raw exception escaping to the
caller and never a raw Roslyn message: C# errors are translated back to the
originating IR op (SACTOR pattern) before a model or a user ever sees them.
Shape follows rustc --error-format=json: code, span (op_index/op_id), message,
optional machine-applicable suggestion.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# Code namespaces (SPEC §6): P parse, G ground/kind, T typecheck, L plan/limits,
# E emit/version, C compile-gate, X execute, W witness.
PARSE_NOT_OBJECT = "KIR-P001"        # program is not a JSON object / ops not a list
PARSE_UNKNOWN_OP = "KIR-P002"        # op name not in registry
PARSE_UNKNOWN_FIELD = "KIR-P003"     # additionalProperties violation (fail-closed)
PARSE_BAD_VERSION = "KIR-P004"       # ir_version missing/unsupported
PARSE_MISSING_FIELD = "KIR-P005"     # required param absent
PARSE_DUP_ID = "KIR-P006"            # duplicate op id inside one program
# «одно из двух» схемой JSON не выражается (oneOf ломает additionalProperties
# fail-closed), поэтому взаимное исключение параметров — отдельный типизированный
# отказ. Первый носитель: place_family, который ставится ЛИБО в точку (xyz),
# ЛИБО по кривой (p0_mm/p1_mm) — у Revit это две разные перегрузки, и угадать
# за автора нельзя.
PARSE_EXCLUSIVE_FIELDS = "KIR-P007"  # mutually exclusive params: both or neither given
GROUND_UNSUPPORTED_KIND = "KIR-G001" # KindEnum escape value / unknown kind -> recipe-path handoff
GROUND_BAD_SELECTOR = "KIR-G002"     # selector shape invalid
GROUND_MODEL_BINDING = "KIR-G107"    # exact open-model dependency proof failed
TYPE_BAD_TYPE = "KIR-T001"           # wrong JSON type for a param
TYPE_BOUNDS = "KIR-T002"             # numeric outside compiler-enforced bounds (§12.9)
TYPE_BAD_ENUM = "KIR-T003"           # value not in closed enum (non-kind enums)
PLAN_LIMIT = "KIR-L001"              # program/op budget exceeded
PLAN_SOLO_OP = "KIR-L002"            # op requires its own program (own transaction scope)
# ФОРМА ПЛАНА ФАЗ (`course.phase()`): границу фаз рисует автор скрипта, и всё,
# что делает такую границу неоднозначной, — типизированный отказ, а не догадка.
# Свободные коды заняты плотно: L003 (порядок ссылок) и L004 (род ссылки) стоят
# литералами в compiler.py/connect.py/route_mep.py, L005 — у несовпадения
# политики bulk. Отсюда L006, и он ЦЕНТРАЛЬНЫЙ, а не литерал: правил формы фазы
# сразу семь, и семь литералов разъехались бы на первой правке.
PLAN_PHASE_SHAPE = "KIR-L006"        # phase(): shape of the phase plan inside one script
PLAN_OP_CONTRACT = "KIR-L007"        # write op lacks a complete canonical lowering contract
EMIT_VERSION = "KIR-E001"            # op unsupported on a requested Revit version
# ОДНА МЫСЛЬ — ОДНА КОНСТАНТА (10.08.2026). Два кода ниже жили РАЗМНОЖЕННЫМИ
# по эмиттерам: `KIR-E007` объявляли ЧЕТЫРЕ модуля (site/sweep/opening/mass),
# `KIR-E008` — ТРИ (opening/struct/stairs_landing), каждый своим именем и
# своим литералом. Мысль при этом была одна на всех, и разъехались бы они
# молча: поправить «где перечень не поддержан» пришлось бы в четырёх местах, а
# забыть — в одном.
#
# ОБЩИЙ ТОЛЬКО КОД, НЕ ТЕКСТ. `message_ru` у каждого места своё и остаётся
# своим: столкновение было НА ПРОВОДЕ (потребитель ветвится по коду), а не в
# прозе, и одна формулировка на четыре разных ремонта была бы новым дефектом
# того же рода.
EMIT_UNSUPPORTED_ENUM = "KIR-E007"   # closed-enum value this op/version does not implement
EMIT_CONTOUR_HOLES = "KIR-E008"      # contour carries holes; this op cannot express them
# КОД T004, А НЕ T003, И ЭТО ИСПРАВЛЕНИЕ СТОЛКНОВЕНИЯ (10.08.2026).
# `TYPE_GEOM_RELATION` двенадцать строк делил провод с `TYPE_BAD_ENUM`: два
# имени, ОДИН код, и два несовместимых ремонта — «значение вне закрытого
# перечня» против «отверстие пересекает контур». Потребитель, ветвящийся по
# `T003`, различить их не мог, и это не гипотеза: серия T001/T002/T003 — это
# типовая проверка (тип, границы, перечень), а отношение контуров приехало
# позже и заняло чужой номер.
#
# СЪЕХАЛА ГЕОМЕТРИЯ, А НЕ ПЕРЕЧЕНЬ, потому что перечень в серии свой по
# построению. Цена: 16 литералов в тестах геометрии (contour, connect, mep,
# site, struct, v11) против 3 у перечня — но дешевле было бы неправильно.
# В проде на `T003` не ветвится НИКТО (`serving` не имеет плеча `KIR-T` вовсе,
# `skill.py` называет T002, но не T003), поэтому перенос ничего не ломает за
# пределами дерева.
TYPE_GEOM_RELATION = "KIR-T004"      # inter-contour geometry (hole vs outline, self-intersection)
# X-stage: runtime outcomes translated to typed codes (SACTOR, SPEC 12.7) —
# a raw Revit message never reaches the model untyped (v1.1, slab-saga fix).
X_SHORT_CURVE = "KIR-X001"           # ShortCurveTolerance / zero-length edge at runtime
X_LOOPS_INTERSECT = "KIR-X002"       # curve loops intersect (T004-caught; runtime backstop)
X_STALE = "KIR-X003"                 # stale_or_failed (model drifted post-ground)
X_POSTCONDITIONS = "KIR-X004"        # in-txn commit-gate rolled back on violations
X_TXN = "KIR-X005"                   # transaction failed to start/commit
X_DUPLICATE_NAME = "KIR-X006"        # name already in use (level/grid rename throw)
X_TIMEOUT = "KIR-X007"               # execution unconfirmed (timeout)
X_RECEIPT = "KIR-X008"               # execution receipt lacks the promised identity
# ─── X009: ОДИН КОД — ОДИН МИР ───────────────────────────────────────────────
#
# `__Refuse` (authoring.py) помечает ОДНИМ транспортным маркером
# `stale_or_failed` ВСЯКИЙ типизированный отказ эмиттера, и `_translate_runtime`
# переводил весь этот поток в X003 — код, чей собственный контракт (строкой
# выше) обещает РОВНО дрейф модели. Так один код стал двумя мирами:
# «элемент исчез между grounding и исполнением» и «Revit отказался это делать».
# Различал их только текст `detail`, а `detail` в корпус свидетелей не писался
# ВООБЩЕ — замер 09.08.2026 по `kir_witness.jsonl`: ни одна из 1306 строк не
# несёт поля с сообщением отказа, поэтому у 38 живых строк X003 причина не
# восстановима ничем. Признак был, и его выбрасывали.
#
# Различающий признак — подпись «после grounding», которую пишут САМИ
# null-guard'ы; она уже вычислялась в `_translate_runtime` и тут же терялась в
# выборе текста. Теперь она выбирает КОД: X003 остаётся дрейфом (как и обещал
# его контракт), а всё остальное получает собственное имя.
#
# ЭТО НЕ РАСШИРЕНИЕ ОТВЕТСТВЕННОСТИ: X009 доказывает откат ровно так же, как
# X003 (обе формы `refuse_stmt` содержат RollBack/throw до коммита), поэтому
# `serving._ROLLBACK_PROVEN_CODES` держит оба, и «откачено» не ослабевает.
X_OP_REFUSED = "KIR-X009"            # typed runtime refusal by an emitter guard
X_UNCLASSIFIED = "KIR-X999"          # typed envelope for the rest; raw kept in detail
# Witness-stage distinction: unlike X004, this state is observed AFTER a
# successful commit in report/per-op mode.  Reusing X004 would claim rollback
# and make a repair retry look safe even though the model already changed.
W_POSTCONDITIONS_COMMITTED = "KIR-W004"

# ─── B: sandBox — исполнение АВТОРСКОГО СКРИПТА (kukai/ir/sandbox.py) ────────
#
# ПОЧЕМУ НОВАЯ БУКВА, А НЕ P/T/L. Стадия предшествует разбору программы: на
# ней программы ЕЩЁ НЕТ, есть питон, который её пишет. Отказ адресован другому
# ремонту — модель чинит СВОЙ скрипт, а не операцию IR, — и указывает на
# строку исходника, а не на op_index. Смешать это с P (разбор JSON) значило бы
# послать ремонт не туда, ровно как смешение двух бюджетов в KIR-L001.
# Занятые буквы на 03.08.2026 (замер грепом по репозиторию): A C D E G L M P S
# T W X. Свободна B, и она читается: sandBox.
# ПЕРЕЗАМЕР 10.08.2026: буква C ОСВОБОДИЛАСЬ — её единственный код `KIR-C001`
# (`COMPILE_FAIL`) не выдавался ни разу за всё время и снят, см. ниже.
SANDBOX_SYNTAX = "KIR-B001"             # исходник не разобран Python
SANDBOX_TIMEOUT = "KIR-B002"            # не завершился: процессорное время/стена
SANDBOX_MEMORY = "KIR-B003"             # превышен предел памяти (RLIMIT_AS)
SANDBOX_FORBIDDEN_IMPORT = "KIR-B004"   # импорт вне белого списка
SANDBOX_FORBIDDEN_BUILTIN = "KIR-B005"  # open/eval/exec/id/... — с причиной
SANDBOX_RUNTIME = "KIR-B006"            # любое другое исключение скрипта
SANDBOX_NO_OPS = "KIR-B007"             # отработал, но программы не выдал
SANDBOX_BAD_RESULT = "KIR-B008"         # выдал не-IR / не JSON-представимое
SANDBOX_OUTPUT_LIMIT = "KIR-B009"       # транспортный потолок (НЕ бюджет автора)
SANDBOX_NONDETERMINISM = "KIR-B010"     # адрес объекта в выходе / разные прогонки
SANDBOX_CRASH = "KIR-B011"              # процесс умер, не сказав ничего
SANDBOX_UNAVAILABLE = "KIR-B012"        # НАШ дефект: изоляция/язык недоступны

# ─── R: Refinement — СЕРТИФИКАТ ПЕРЕВОДА (kukai/ir/translation_cert.py) ──────
#
# ПОЧЕМУ ОТДЕЛЬНАЯ БУКВА. Стадия стоит МЕЖДУ компиляцией и первым эффектом и
# судит не программу автора, а НАШУ эмиссию: доказано ли, что у каждого
# обещанного постусловия есть свидетель и что этот свидетель СПОСОБЕН
# сработать. Смешать её с C (гейт Roslyn отверг C#) значило бы послать ремонт
# в компилятор кода, а не в эмиттер свидетелей; смешать с W (постусловие
# нарушено на исполнении) — соврать, будто что-то исполнялось. Ничего не
# исполнялось: эффекта нет по построению, и отказ здесь ВСЕГДА до записи.
# Занятые буквы на 09.08.2026 (грепом по репозиторию): A B C D E G L M P S T V
# W X. Свободна R, и она читается: Refinement.
# ПЕРЕЗАМЕР 10.08.2026: C свободна (мёртвый `KIR-C001` снят); заняты
# A B D E G L M P S T V W X.
#
# АДРЕС РЕМОНТА У ВСЕХ ТРЁХ — НАШ КОД, НЕ ПРОГРАММА МОДЕЛИ. Автор не может
# написать программу так, чтобы свидетель ожил: свидетеля пишет эмиттер.
# Поэтому у R-отказа нет `handoff`: увести такую запись на свободный C# значит
# выполнить её вообще без свидетеля, то есть усилить ровно тот дефект, из-за
# которого отказали.
CERT_UNPROVEN = "KIR-R001"   # обязательство не разряжено: свидетеля НЕТ
CERT_VACUOUS = "KIR-R002"    # свидетель ЕСТЬ и доказуемо не может сработать
CERT_UNCERTIFIABLE = "KIR-R003"  # ПРИБОР МОЛЧИТ (нет OpRefinementSpec/сбой) —
#                                  запись НЕ отказывается по этому коду


@dataclass
class Diagnostic:
    code: str
    message_ru: str
    op_index: Optional[int] = None
    op_id: Optional[str] = None
    field_name: Optional[str] = None
    expected: Optional[Any] = None
    got: Optional[Any] = None
    candidates: list = field(default_factory=list)
    # rustc-style suggestion: applicability is "machine-applicable" only when the
    # fix is provably safe to auto-apply; otherwise "maybe-incorrect".
    suggested_replacement: Optional[Any] = None
    applicability: Optional[str] = None
    # Opaque correlation token for an unexpected internal failure.  It is the
    # only panic detail exposed on the wire; server logs carry the same token
    # with bounded, non-payload metadata.
    incident_id: Optional[str] = None

    def as_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, [])}


class KirRefusal(Exception):
    """Internal control-flow: carries diagnostics out of a stage. Never leaks —
    compile_program() catches it and returns a refused CompileOutput."""

    def __init__(self, diags: list[Diagnostic]):
        # ТЕКСТ ИСКЛЮЧЕНИЯ НЕСЁТ ПРИЧИНУ, а не её количество.
        #
        # Замер 03.08: отказ САМОГО ЯЗЫКА (`dsl.py` поднимает `DslRefusal` —
        # наследника этого класса — на дубле id, на неадресуемой ручке, на
        # исчерпанном bulk-бюджете) уходит из песочницы через `str(exc)`, и
        # модель получала «DslRefusal: 1 diagnostic(s)»: место есть, причины
        # нет. Пересекать границу процесса умеет только текст, поэтому текст
        # обязан быть содержательным. Коды и сообщения ведущих диагностик
        # стоят здесь ровно затем; полный список остаётся в `.diagnostics` и
        # никуда не девается для тех, кто ловит исключение целиком.
        head = "; ".join(
            f"{d.code}: {d.message_ru}" if getattr(d, "message_ru", "")
            else str(getattr(d, "code", "")) for d in diags[:3])
        if len(diags) > 3:
            head += f" (и ещё {len(diags) - 3})"
        super().__init__(head or f"{len(diags)} diagnostic(s)")
        self.diagnostics = diags


# ═════════════════════════════════════════════════════════════════════════
# СЛОВАРЬ ОТКАЗОВ ЗАКРЫТ: ОДИН КОД — ОДНО ИМЯ
#
# ЗАМЕР 10.08.2026: 89 различных кодов `KIR-*` в пакете, 76 из них имеют
# именованную константу, а ШЕСТЬ кодов несли по нескольку РАЗНЫХ имён. Худший
# случай жил прямо здесь: `KIR-T003` был и `TYPE_BAD_ENUM`, и
# `TYPE_GEOM_RELATION` — в одном файле, в двенадцати строках друг от друга.
# Код на проводе — это обещание потребителю, что ремонт один; два ремонта под
# одним кодом делают ветвление по нему невозможным, и заметить это было
# нечем: центрального реестра кодов нет, а занятость БУКВ отслеживалась
# комментарием с результатом ручного грепа.
#
# ПОЧЕМУ ЛИНТ ЗДЕСЬ ЗАКРЫВАЕТ ТОЛЬКО ЭТОТ ФАЙЛ. Модуля, который импортирует
# все эмиттеры, нет, поэтому на импорте `diag` видно лишь его собственное
# пространство имён — зато именно в нём и произошло худшее столкновение, и
# именно оно теперь невозможно. Межмодульную половину закрывает `test_diag_
# codes` через `code_collisions()` ниже: она читает ИСХОДНИКИ, а не импортирует
# пакет, потому что импорт всего дерева ради линта дороже самого линта.
# ═════════════════════════════════════════════════════════════════════════

#: КОДЫ, У КОТОРЫХ НЕСКОЛЬКО ИМЁН ОСОЗНАННО, — С ПРИЧИНОЙ, А НЕ ПО УМОЛЧАНИЮ.
#: Это НЕ разрешение плодить синонимы: каждая строка — долг с названным
#: ремонтом (одна общая константа вместо нескольких местных), и новый код
#: сюда нельзя дописать, не назвав, почему имена не схлопываются.
CODES_WITH_KNOWN_ALIASES: dict[str, str] = {
    # ПУСТО, И ЭТО ЗАМЕР, А НЕ НЕЗАПОЛНЕННОСТЬ. 10.08 здесь стояли `KIR-E007`
    # (четыре имени) и `KIR-E008` (три); оба схлопнуты в
    # `EMIT_UNSUPPORTED_ENUM` и `EMIT_CONTOUR_HOLES`, и записи сняты ВМЕСТЕ с
    # долгом, а не отдельно от него. Если появится новый код с двумя именами,
    # его покажет `code_collisions()` ниже — молчать этот список не умеет.

}


def _lint_diag_codes() -> None:
    """ОДИН КОД — ОДНО ИМЯ, в пределах этого файла, на импорте."""
    seen: dict[str, str] = {}
    for name, value in globals().items():
        if not (name.isupper() and isinstance(value, str)
                and value.startswith("KIR-")):
            continue
        first = seen.get(value)
        if first is not None and first != name:
            raise AssertionError(
                f"{value}: код носят ДВА имени — {first!r} и {name!r}. "
                f"Код на проводе обещает потребителю ОДИН ремонт; два имени "
                f"под одним кодом делают ветвление по нему невозможным. "
                f"Дайте одному из них свободный номер своей буквы")
        seen[value] = name


_lint_diag_codes()


def code_collisions(root: str | None = None) -> dict[str, list[str]]:
    """Коды, носящие больше одного ИМЕНИ, по всему пакету — чтением исходников.

    Возвращает `{код: [имена]}` только для настоящих столкновений: известные
    долги из `CODES_WITH_KNOWN_ALIASES` исключены (они названы, а не забыты),
    тесты не читаются вовсе (тестовая копия константы — не объявление провода),
    а код, объявленный под ОДНИМ именем в двух модулях, столкновением не
    считается: так живёт `GROUND_EMPTY_POOL` (`ground`/`relate`), и его
    дублирование намеренно — `relate` не тянет `ground`, тот тянет `spec`.
    """
    import io
    import os
    import re

    root = root or os.path.dirname(os.path.abspath(__file__))
    pattern = re.compile(
        r"^([A-Z][A-Z0-9_]*)\s*(?::[^=]+)?=\s*[\"'](KIR-[A-Z]\d+)[\"']",
        re.M)
    names_by_code: dict[str, set[str]] = {}
    for folder, _dirs, files in os.walk(root):
        if os.path.sep + "tests" in folder or "__pycache__" in folder:
            continue
        for fname in files:
            if not fname.endswith(".py"):
                continue
            with io.open(os.path.join(folder, fname), encoding="utf-8") as fh:
                for name, code in pattern.findall(fh.read()):
                    names_by_code.setdefault(code, set()).add(name)
    return {code: sorted(names)
            for code, names in sorted(names_by_code.items())
            if len(names) > 1 and code not in CODES_WITH_KNOWN_ALIASES}
