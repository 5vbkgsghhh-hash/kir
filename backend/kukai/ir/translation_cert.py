"""Translation-validation certificate for the KIR authoring emitter (wave 2).

The emitter (`authoring.py`) already carries, per op, BOTH halves of a
refinement witness — they were just never collected into a checkable
certificate:

1. a **materializing Revit API call** in the ``create`` block
   (``Wall.Create``, ``Pipe.Create``, ``NewFamilyInstance``, ...) guarded by a
   typed ``__Refuse`` on a null / failed return (materialize-or-refuse; no
   silent wrong result), and
2. a **runtime postcondition witness** in the ``post`` block: one
   ``__post.Add("<oid>: ...")`` per invariant the op's ``OpSpec.post`` promises
   (endpoint geometry, level/host topology, parameter values, flip states,
   MEPSystem membership, ...), which ``emit_program`` gates with
   ``if (__post.Count > 0) { RollBack | report }``.

This module turns "a runtime witness exists" into a **statically checkable,
pre-Revit guarantee** that, for every promised postcondition, the witness was
actually emitted (not forgotten), and that the materializer is the specific
API that implements the op (not a stub).  It is the two-part structure of a
refinement proof: **safety** (right API or typed refusal) + **coverage
liveness** (every promised observable is checked).

The check is STATIC — no Revit, no compile — parsing the very
``(decl, create, post, readback)`` tuple the emitter returns, with the same
string/comment-stripping tokenizer the emitter scope contract already uses
(`test_emitter_scope_contract`).  Witnesses are matched by STRUCTURAL C#
markers (``.Location as LocationCurve``, ``WALL_BASE_CONSTRAINT``,
``.Mirrored != ``, ``RBS_PIPE_DIAMETER_PARAM``), never by the Russian message
text (which the tokenizer strips) — so renaming a message cannot fool the
certificate, while deleting the check itself breaks it.

Design, forks and rationale: ``TRANSLATION_VALIDATION_SPEC.md`` at the worktree
root.  Headlines:

* We prove refinement of the op's POSTCONDITIONS (its only observable
  contract, since the semantics live in Revit), not SMT-equivalence of the
  C# AST.
* ``REFINEMENT`` is the machine form of the prose ``OpSpec.post``;
  ``audit_registry_coverage`` enforces a biection so the table cannot silently
  drift from the registry (a new promised clause with no obligation is a hard
  fail).
* ``authoring.py`` is untouched — the certificate OBSERVES emission and never
  steers it.  Since 09.08.2026 it is no longer observation-only at the
  PIPELINE level: ``serving._handle_revit_ir_inner`` certifies the compiled
  write between compilation and the first effect (see
  :func:`certificate_mode`).  ``certificate_enabled()`` is still default OFF,
  so an unset flag leaves that path byte-identical.

Fail-closed: an unproven refinement or a registry/table mismatch raises a typed
:class:`CertificateError` — never a silent "proven".

09.08.2026 — ВАКУУМНЫЙ СВИДЕТЕЛЬ.  Наличие ключа обязательства доказывало, что
строка ``__post.Add`` СУЩЕСТВУЕТ, и молчало о том, ДОСТИЖИМА ли она: мутация
``if (false) __post.Add("never")`` оставляла стену `proven`.  Теперь сертификат
разбирает ОХРАНУ каждого вердикта и отказывает :class:`VacuousWitnessError`,
когда `__post.Add` доказуемо мёртв.  Анализ ЧАСТИЧЕН по построению (достижимость
неразрешима), и его границы перечислены поимённо у :func:`analyze_witness_cs` —
читать ДО того, как сослаться на него как на гарантию.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable

from kukai.ir import spec
from kukai.ir.authoring import _EMITTERS, emit_stairs_program
from kukai.ir.emit_model import BarePost, post_to_string


# ---------------------------------------------------------------------------
# Typed failures (fail-closed)
# ---------------------------------------------------------------------------


class CertificateError(ValueError):
    """Base for every typed translation-certificate failure."""


class UnprovenRefinementError(CertificateError):
    """An emitted op does not discharge every required refinement obligation."""


class CertificateSchemaError(CertificateError):
    """The registry promises a postcondition the obligation table cannot prove,
    or the table references a clause the registry never promises."""


class VacuousWitnessError(UnprovenRefinementError):
    """Свидетель, чей ``__post.Add`` НЕ МОЖЕТ выполниться ни при каком прогоне.

    Проверка, которая не может упасть, хуже отсутствующей: снаружи она
    неотличима от настоящей и разряжает обязательство сертификата.
    """


# ---------------------------------------------------------------------------
# Flag (inertness contract) + ЧТО ДЕЛАЕТ ПРОВАЛЕННЫЙ СЕРТИФИКАТ
# ---------------------------------------------------------------------------
#
# ОДИН ФЛАГ, ТРИ СОСТОЯНИЯ.  «Включён» и «отказывает» — разные решения, и
# слить их в булево значило бы отнять у оператора единственный безопасный
# способ ввести прибор в живой путь: сначала СМОТРЕТЬ, потом ЗАПРЕЩАТЬ.
#
#   не задан / пусто / 0 / off   → OFF     сертификация не запускается вовсе
#   record                       → RECORD  считаем и кладём в квитанцию
#   1 / true / yes / on / refuse → REFUSE  недоказанная программа НЕ ПИШЕТ
#
# ПОЧЕМУ REFUSE — УМОЛЧАНИЕ ВКЛЮЧЁННОГО.  Зелёный ход этой системы стоит на
# четырёх ногах, и одна из них — внутренний свидетель компилятора.  Свидетель,
# чей `__post.Add` доказуемо мёртв, делает эту ногу тождественно истинной:
# программа «прошла постусловия», не проверив ничего.  Разрешить такой записи
# исполниться значит выпустить `ok:true` без независимого подтверждения — то
# самое запрещённое состояние.  Поэтому включённый прибор по умолчанию
# ОТКАЗЫВАЕТ, а `record` — осознанный, названный компромисс наблюдения.
#
# ЧТО ЭТО НЕ ДЕЛАЕТ.  Ни один режим не отказывает там, где ПРИБОР МОЛЧИТ:
# оп без `OpRefinementSpec` (реестр обогнал таблицу) и любая внутренняя
# поломка сертификатора — это отсутствие измерения, а не находка.  Отказать по
# ним значило бы завернуть верно построенную программу из-за нашей
# бухгалтерии — класс дефекта «приёмка сломалась на кириллице», который
# месяцами откатывал исправные помещения.  Такие случаи ЗАПИСЫВАЮТСЯ в
# квитанцию под своим именем и пропускаются (решение живёт в
# ``serving._certify_translation``).

CERT_MODE_OFF = "off"
CERT_MODE_RECORD = "record"
CERT_MODE_REFUSE = "refuse"

#: Значения, включающие сертификацию (любой режим, кроме выключенного).
_CERT_RECORD_VALUES = frozenset({"record", "observe"})
_CERT_REFUSE_VALUES = frozenset({"1", "true", "yes", "on", "refuse"})


def certificate_enabled() -> bool:
    """Запускается ли сертификация вообще; default OFF.

    Флаг читается ЗДЕСЬ буквально (а не через общий хелпер), потому что
    ``tools/capability_map.py`` находит предикат гейта по паре «``def … ->
    bool:`` + имя переменной окружения в его теле», и разрыв этой пары
    вернул бы флагу вердикт «на складе» — ровно ту слепоту, которую этот
    файл сегодня и лечит.
    """

    return os.getenv("KUKAI_IR_TRANSLATION_CERT", "").strip().lower() in (
        _CERT_REFUSE_VALUES | _CERT_RECORD_VALUES)


def certificate_mode() -> str:
    """``off`` | ``record`` | ``refuse`` — ЧТО делает проваленный сертификат.

    Не второй флаг, а вторая половина одного: см. блок выше.  Любая строка
    вне обоих наборов оставляет прибор ВЫКЛЮЧЕННЫМ — и ровно так же её
    читает :func:`certificate_enabled`, поэтому «включён» и «отказывает» не
    могут разъехаться ни на одном значении (закреплено тестом
    ``test_enabled_and_mode_can_never_disagree``).
    """

    raw = os.getenv("KUKAI_IR_TRANSLATION_CERT", "").strip().lower()
    if raw in _CERT_RECORD_VALUES:
        return CERT_MODE_RECORD
    if raw in _CERT_REFUSE_VALUES:
        return CERT_MODE_REFUSE
    return CERT_MODE_OFF


# ---------------------------------------------------------------------------
# C# tokenizer
# ---------------------------------------------------------------------------

def _code(text: str) -> str:
    """Strip C# strings, chars, and both comment forms; leave only code.

    A witness marker is searched in this stripped code, never inside a message
    string, so a renamed message can never fabricate (or hide) a proof.

    This must be a state machine, not two regex substitutions: C# has block
    comments, verbatim strings, escaped quotes, and comment-looking text inside
    literals.  In particular ``/* Wall.Create */`` used to satisfy the
    materializer proof even though it compiles to no call at all (F30).
    """

    out: list[str] = []
    i = 0
    size = len(text)
    line_ends = "\r\n\x85\u2028\u2029"
    while i < size:
        # Line comment (including every C# newline character).
        if text.startswith("//", i):
            i += 2
            while i < size and text[i] not in line_ends:
                i += 1
            out.append(" ")
            continue

        # Block comments are not nestable in C#.  Unterminated means the rest
        # is comment; dropping it is the certificate's fail-closed choice.
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = size if end < 0 else end + 2
            out.append(" ")
            continue

        # Verbatim string prefixes: @"...", $@"...", @$"...".  Generated
        # KIR does not rely on interpolation code for proof markers, so the
        # entire literal is deliberately non-code for certification.
        prefix_len = 0
        if text.startswith('$@"', i) or text.startswith('@$"', i):
            prefix_len = 3
        elif text.startswith('@"', i):
            prefix_len = 2
        if prefix_len:
            i += prefix_len
            while i < size:
                if text[i] == '"':
                    if i + 1 < size and text[i + 1] == '"':
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            out.append('""')
            continue

        # Ordinary/interpolated strings.  Backslash escapes keep the next
        # character inside the literal.  This is sufficient for the C# 7.3
        # dialect emitted here; proof-bearing code is never inside a string.
        quote_len = 0
        if text.startswith('$"', i):
            quote_len = 2
        elif text[i] == '"':
            quote_len = 1
        if quote_len:
            i += quote_len
            while i < size:
                if text[i] == "\\" and i + 1 < size:
                    i += 2
                    continue
                char = text[i]
                i += 1
                if char == '"':
                    break
            out.append('""')
            continue

        # Character literals may contain escaped quote/comment characters.
        if text[i] == "'":
            i += 1
            while i < size:
                if text[i] == "\\" and i + 1 < size:
                    i += 2
                    continue
                char = text[i]
                i += 1
                if char == "'":
                    break
            out.append("''")
            continue

        out.append(text[i])
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# ВАКУУМНЫЙ СВИДЕТЕЛЬ (09.08.2026): проверка, которая не может сработать
# ---------------------------------------------------------------------------
#
# ДЫРА, ЗАКРЫВАЕМАЯ ЗДЕСЬ.  `WitnessCheck` требует НАЛИЧИЯ `__post.Add` в
# вердикте, а сертификат — НАЛИЧИЯ ключа обязательства.  Ни один из двух не
# смотрел на УСЛОВИЕ, под которым этот `__post.Add` стоит.  Мутация аудита:
#
#     if (false) __post.Add("never");
#
# оставляла `certify_op(wall, "2026").proven == True` — «строка, способная
# добавить нарушение, существует» принималось за «проверка способна нарушение
# обнаружить».  Это ровно тот класс, против которого написан весь модуль:
# ЧЕК, КОТОРЫЙ НЕ МОЖЕТ УПАСТЬ, ХУЖЕ ОТСУТСТВУЮЩЕГО.
#
# ───────────────────────────────────────────────────────────────────────────
# ГРАНИЦА ЭТОГО ПРИБОРА, НАЗВАННАЯ ЧЕСТНО — ЧИТАТЬ ДО ТОГО, КАК СОШЛЁШЬСЯ НА
# НЕГО КАК НА ГАРАНТИЮ.
#
# Достижимость в общем случае НЕРАЗРЕШИМА, и здесь она не решается.  Этот
# анализ отвечает РОВНО НА ОДИН вопрос: «могу ли я ДОКАЗАТЬ, что этот
# `__post.Add` мёртв?».  «Нет» здесь НЕ ЕСТЬ доказательство того, что
# свидетель живой.  Прибор умеет только ДОБАВЛЯТЬ отказы, и никогда —
# подтверждать жизнеспособность.  Приняв его за тотальную гарантию, читатель
# повторит дефект, ради которого он написан (закон дома: прибор на ЧАСТЬ
# диапазона опаснее отсутствующего — см. память
# `instrument-covering-part-of-range-2026-08-03`).
#
# ЧТО ДЕТЕКТИРУЕТСЯ (каждый класс проверен мутацией в
# tests/test_witness_vacuity.py):
#
#   1. VACUITY_CONSTANT_FALSE — охрана вычисляется в константу, несовместимую
#      с веткой: `if (false)`, `while (false)`, `if (0 == 1)`, `if (1 > 2)`,
#      `for (...; false; ...)`, `if (false && X)`, `if (!true)`,
#      а также ветка `else` у `if (true)`.
#      Булева алгебра считается по &&/||/!/скобкам; числовые сравнения — по
#      литералам, `Math.Abs(...)` и вычитанию.
#   2. VACUITY_SELF_COMPARISON — охрана сравнивает выражение САМО С СОБОЙ в
#      ложную сторону: `x != x`, `a < a`, `Math.Abs(MM(x) - MM(x)) > 5.0`.
#   3. VACUITY_UNREACHABLE — `__post.Add` стоит ПОСЛЕ безусловного
#      `return`/`throw`/`break`/`continue`/`goto` в том же списке операторов.
#
# ЧТО ДОКАЗУЕМО НЕ ДЕТЕКТИРУЕТСЯ (и это не список задач на завтра, а предел
# статики; каждый пункт назван, чтобы следующий читатель не принял тишину за
# чистоту):
#
#   * ЗНАЧЕНИЯ ПЕРЕМЕННЫХ.  `bool __never = false; if (__never) __post.Add(..)`
#     — константное распространение не делается вовсе.  Тот же вакуум,
#     невидимый этому прибору.
#   * НЕДОСТИЖИМОСТЬ ЧЕРЕЗ ДАННЫЕ.  Охрана вида `if (__count > 1000000)` или
#     `if (__el == null)` там, где `__el` только что проверен на null: условие
#     синтаксически живое, семантически — нет.  Это уже верификация, а не
#     разбор текста.
#   * ПУСТЫЕ ИТЕРАЦИИ.  `foreach (var x in <пустая коллекция>)` — число
#     итераций из текста не выводится; `foreach` даёт НОЛЬ информации об
#     охране, и тело считается достижимым.
#   * ЧАСТИЧНАЯ ВЫХОЛОЩЕННОСТЬ ПО СМЫСЛУ.  Свидетель с двумя `__post.Add`
#     (null-охрана + сверка допуска), у которого ЖИВЫМ оставлен только
#     null-охранник, а сверка ослаблена до `> 1e30`, здесь пройдёт: 1e30 —
#     живое число, а «допуск слишком широк» — вопрос к провенансу допуска
#     (закон 3 в emit_model), не к достижимости.  ПОЭТОМУ правило намеренно
#     строгое: находкой считается КАЖДЫЙ доказуемо мёртвый `__post.Add`, а не
#     только случай «мертвы все» — иначе выхолащивание одной из двух веток
#     проходило бы молча.
#   * ПОБОЧНЫЕ ЭФФЕКТЫ В ОХРАНЕ.  Тождество `x == x` считается тождеством
#     ЗНАЧЕНИЙ по текстовому совпадению операндов.  Вызов, меняющий состояние
#     между двумя чтениями, это опроверг бы; в эмитируемом здесь диалекте
#     охрана состоит из чтений и чистых хелперов (`MM`, `U`, `P`), а операнды
#     с присваиванием/`++`/`--`/`new` из тождества исключены явно.
#   * ВСЕГДА-ИСТИННАЯ охрана (`if (x == x) __post.Add(..)`) — это ДРУГОЙ
#     дефект: такая проверка падает всегда и ГРОМКО, то есть не относится к
#     классу «молча-неверно».  Здесь она не находка (но мёртвую ветку `else`
#     под ней прибор увидит).
#   * НЕСАМОДОСТАТОЧНЫЙ ТЕКСТ.  Шаблон `create_stairs` — тело метода плюс
#     объявления классов, по скобкам НЕ сбалансированное намеренно (рамку
#     даёт `wrap_user_code`).  Такой текст разбирается КУСКАМИ, а факт
#     неполноты едет отдельным полем (`OpCertificate.vacuity_partial`):
#     «прочитано целиком» и «прочитано частями» — разные факты, и второе не
#     должно читаться как доказательство чистоты.
#
# НАПРАВЛЕНИЕ ОТКАЗА.  Прибор — ДЕТЕКТОР, а не доказательство корректности,
# поэтому на неразобранном тексте он молчит, а не обвиняет: иначе он отказал
# бы всему корпусу и его бы отключили, что хуже, чем узкая правда.
#
# ЗАМЕРЕНО 09.08.2026 (корпус test_tolerance_provenance._full_instances, 940
# экземпляров опов = все 37 пишущих опов реестра × 6 версий Revit):
#   * находок вакуума — 0;
#   * обход дошёл до 3748 из 3748 `__post.Add` модельного пути (2618 витнесов)
#     и до 5 из 5 в шаблоне create_stairs, разобранном кусками.
# Вторая строка — не украшение: без неё «ноль находок» и «обход молча прошёл
# мимо» неразличимы.  Оба числа держит ratchet в tests/test_witness_vacuity.py
# (`witness_site_census`), поэтому они не могут протухнуть незамеченными.

#: Именованные классы вакуума (типизированные диагностики, не строки на глаз).
VACUITY_CONSTANT_FALSE = "constant_false_guard"
VACUITY_SELF_COMPARISON = "self_comparison_guard"
VACUITY_UNREACHABLE = "unreachable_verdict"
VACUITY_KINDS = frozenset({
    VACUITY_CONSTANT_FALSE, VACUITY_SELF_COMPARISON, VACUITY_UNREACHABLE,
})

_VERDICT_CALL = "__post.Add"
_TERMINATOR_RE = re.compile(r"^(?:return|throw|break|continue|goto)\b")
_HEADER_RE = re.compile(r"^(if|while|for|foreach|switch|lock|using|fixed)\s*\(")
_NUMBER_RE = re.compile(
    r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?[fFdDmM]?$")
_ASSIGNMENT_RE = re.compile(r"(?<![=!<>+\-*/%&|^])=(?!=)")
_RELOPS = ("==", "!=", "<=", ">=", "<", ">")
_NOT_RELOPS = ("=>", "<<", ">>", "->")
_OPENERS = "([{"
_CLOSERS = ")]}"


@dataclass(frozen=True, slots=True)
class VacuityFinding:
    """Один доказуемо мёртвый ``__post.Add`` — op-bound типизированная находка."""

    op: str
    obligation_key: str | None
    kind: str
    guard: str
    excerpt: str

    def describe(self) -> str:
        where = (f"witness {self.obligation_key!r}"
                 if self.obligation_key is not None else "post block")
        return (
            f"{self.op}: {where} — вакуумный свидетель [{self.kind}]: "
            f"{_VERDICT_CALL} не может выполниться, охрана {self.guard!r} "
            f"(фрагмент: {self.excerpt!r}); проверка, которая не может "
            "упасть, хуже отсутствующей")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


_BRACKET_PAIRS = {")": "(", "]": "[", "}": "{"}


def _balanced_segments(code: str) -> tuple[list[str], bool]:
    """Cut ``code`` into maximal bracket-balanced pieces.

    NOT every emitted fragment is a self-contained statement list:
    ``create_stairs`` owns a whole-program TEMPLATE — a method body followed by
    nested class declarations — deliberately unbalanced at both ends, because
    ``wrap_user_code`` supplies the frame (its own docstring says so).
    Declining that blob wholesale would leave the one string-path op with ZERO
    vacuity coverage and call it "unparseable", which is the silence this
    module exists to prevent.

    So a bracket with no partner HERE ends the current piece and opens the
    next, and the body of an unclosed opener is analysed as its own top-level
    block (with NO inherited guards — the conservative direction: fewer
    findings, never invented ones).  The second return value says whether
    anything had to be cut, so "fully parsed" and "parsed in pieces" stay
    different facts.
    """

    out: list[str] = []
    trimmed = [False]
    _cut(code, out, trimmed)
    return [piece for piece in out if piece.strip()], trimmed[0]


def _cut(code: str, out: list[str], trimmed: list[bool]) -> None:
    stack: list[tuple[str, int]] = []
    start = 0
    for i, ch in enumerate(code):
        if ch in _OPENERS:
            stack.append((ch, i))
        elif ch in _CLOSERS:
            if stack and stack[-1][0] == _BRACKET_PAIRS[ch]:
                stack.pop()
            else:
                out.append(code[start:i])
                start = i + 1
                stack = []
                trimmed[0] = True
    if stack:
        trimmed[0] = True
        at = stack[0][1]
        out.append(code[start:at])
        _cut(code[at + 1:], out, trimmed)
    else:
        out.append(code[start:])


def _matching(text: str, start: int) -> int:
    """Index of the bracket matching the opener at ``start`` (-1 if none)."""

    opener = text[start]
    closer = {"(": ")", "[": "]", "{": "}"}[opener]
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return i
    return -1


def _split_top(expr: str, token: str) -> list[str]:
    """Split ``expr`` on ``token`` occurrences at bracket depth 0."""

    parts: list[str] = []
    depth = last = i = 0
    size = len(expr)
    while i < size:
        ch = expr[i]
        if ch in _OPENERS:
            depth += 1
        elif ch in _CLOSERS:
            depth -= 1
        elif depth == 0 and expr.startswith(token, i):
            parts.append(expr[last:i])
            i += len(token)
            last = i
            continue
        i += 1
    parts.append(expr[last:])
    return parts


def _word_at(text: str, index: int, word: str) -> bool:
    if not text.startswith(word, index):
        return False
    before = text[index - 1] if index else " "
    after = text[index + len(word):index + len(word) + 1] or " "
    return not (before.isalnum() or before == "_") and \
        not (after.isalnum() or after == "_")


def _next_word(text: str, index: int) -> str:
    while index < len(text) and text[index].isspace():
        index += 1
    match = re.match(r"[A-Za-z_]+", text[index:])
    return match.group(0) if match else ""


def _is_pure(text: str) -> bool:
    """Операнд, тождество которого по тексту можно считать тождеством значения.

    Ограничение НАЗВАНО: чтения и чистые хелперы — да; присваивание,
    инкремент и конструирование — нет.
    """

    return bool(text) and not (
        _ASSIGNMENT_RE.search(text) or "++" in text or "--" in text
        or re.search(r"\bnew\b", text))


def _split_relational(expr: str) -> tuple[str, str, str] | None:
    """First depth-0 relational operator, as (lhs, op, rhs)."""

    depth = i = 0
    size = len(expr)
    while i < size:
        ch = expr[i]
        if ch in _OPENERS:
            depth += 1
            i += 1
            continue
        if ch in _CLOSERS:
            depth -= 1
            i += 1
            continue
        if depth == 0:
            if any(expr.startswith(bad, i) for bad in _NOT_RELOPS):
                i += 2
                continue
            for op in _RELOPS:
                if expr.startswith(op, i):
                    return expr[:i], op, expr[i + len(op):]
        i += 1
    return None


def _split_additive(expr: str) -> tuple[str, str, str] | None:
    """Last depth-0 ``+``/``-`` that is a binary operator, as (lhs, op, rhs)."""

    depth = i = 0
    size = len(expr)
    found: tuple[int, str] | None = None
    while i < size:
        ch = expr[i]
        if ch in _OPENERS:
            depth += 1
        elif ch in _CLOSERS:
            depth -= 1
        elif depth == 0 and ch in "+-":
            prev = expr[:i].rstrip()
            nxt = expr[i + 1:i + 2]
            unary = not prev or prev[-1] in "(+-*/%<>=!&|,^~"
            compound = nxt in ("+", "-", "=", ">")
            exponent = bool(re.search(r"[\d.][eE]$", prev))
            if not (unary or compound or exponent):
                found = (i, ch)
        i += 1
    if found is None:
        return None
    at, op = found
    return expr[:at], op, expr[at + 1:]


def _const_num(expr: str) -> tuple[float | None, bool]:
    """Constant value of a numeric C# expression + whether SELF-IDENTITY was used.

    The second flag is what keeps the diagnostic honest: ``Math.Abs(MM(x) -
    MM(x)) > 5.0`` folds to ``0.0 > 5.0``, and calling that "a comparison of
    literals" would hide the actual defect — the witness compares a value to
    ITSELF.  The reason travels with the number.
    """

    expr = expr.strip()
    while expr.startswith("(") and _matching(expr, 0) == len(expr) - 1:
        expr = expr[1:-1].strip()
    if not expr:
        return None, False
    if _NUMBER_RE.match(expr):
        return float(expr.rstrip("fFdDmM")), False
    if expr.startswith("Math.Abs"):
        open_at = expr.find("(")
        if open_at > 0 and _matching(expr, open_at) == len(expr) - 1:
            inner, self_used = _const_num(expr[open_at + 1:-1])
            return (None if inner is None else abs(inner)), self_used
    additive = _split_additive(expr)
    if additive is not None:
        lhs, op, rhs = additive
        left, right = _norm(lhs), _norm(rhs)
        if op == "-" and left and left == right and _is_pure(left):
            return 0.0, True
        a, a_self = _const_num(lhs)
        b, b_self = _const_num(rhs)
        if a is not None and b is not None:
            return (a - b if op == "-" else a + b), (a_self or b_self)
    return None, False


def _const_bool(expr: str) -> tuple[bool | None, str]:
    """Constant value of a boolean C# expression + WHY (for the diagnostic).

    Returns ``(None, "")`` for anything not statically decidable — the honest
    default, since undecided is the overwhelming majority.
    """

    expr = expr.strip()
    while expr.startswith("(") and _matching(expr, 0) == len(expr) - 1:
        expr = expr[1:-1].strip()
    if not expr:
        return None, ""

    ors = _split_top(expr, "||")
    if len(ors) > 1:
        values = [_const_bool(part) for part in ors]
        for value, why in values:
            if value is True:
                return True, why
        if all(value is False for value, _ in values):
            return False, next((w for _, w in values if w), "literal")
        return None, ""

    ands = _split_top(expr, "&&")
    if len(ands) > 1:
        values = [_const_bool(part) for part in ands]
        for value, why in values:
            if value is False:
                return False, why
        if all(value is True for value, _ in values):
            return True, next((w for _, w in values if w), "literal")
        return None, ""

    if expr.startswith("!") and not expr.startswith("!="):
        value, why = _const_bool(expr[1:])
        return (None if value is None else (not value)), why

    if expr == "true":
        return True, "literal"
    if expr == "false":
        return False, "literal"

    relational = _split_relational(expr)
    if relational is not None:
        lhs, op, rhs = relational
        left, right = _norm(lhs), _norm(rhs)
        if left and left == right and _is_pure(left):
            return op in ("==", "<=", ">="), "self"
        a, a_self = _const_num(lhs)
        b, b_self = _const_num(rhs)
        if a is not None and b is not None:
            decided = {
                "==": a == b, "!=": a != b, "<=": a <= b,
                ">=": a >= b, "<": a < b, ">": a > b,
            }[op]
            return decided, ("self" if (a_self or b_self) else "numeric")
    return None, ""


def _guard_label(condition: str, branch: bool, keyword: str) -> str:
    """The guard as the READER will see it — the construct it really came from.

    Rendering a ``while (false)`` as ``if (false)`` would send whoever reads
    the refusal looking for an ``if`` that is not there.
    """

    shown = _norm(condition)
    if keyword == "for":
        return f"for (...; {shown}; ...)"
    if keyword == "while":
        return f"while ({shown})"
    return f"if ({shown})" if branch else f"else of if ({shown})"


def _guard_verdict(
    guards: tuple[tuple[str, bool, str], ...],
) -> tuple[str, str] | None:
    """(kind, guard-text) if some enclosing guard PROVABLY excludes this branch."""

    for condition, branch, keyword in guards:
        value, why = _const_bool(condition)
        if value is None or value == branch:
            continue
        kind = (VACUITY_SELF_COMPARISON if why == "self"
                else VACUITY_CONSTANT_FALSE)
        return kind, _guard_label(condition, branch, keyword)
    return None


def _excerpt(text: str, at: int) -> str:
    return _norm(text[at:at + 48])


def _split_else(rest: str) -> tuple[str, str | None]:
    depth_p = depth_b = i = 0
    size = len(rest)
    while i < size:
        ch = rest[i]
        if ch in "([":
            depth_p += 1
        elif ch in ")]":
            depth_p -= 1
        elif ch == "{":
            depth_b += 1
        elif ch == "}":
            depth_b -= 1
        elif depth_p == 0 and depth_b == 0 and _word_at(rest, i, "else"):
            return rest[:i], rest[i + 4:]
        i += 1
    return rest, None


def _unwrap(part: str) -> str:
    part = part.strip()
    if part.startswith("{"):
        close = _matching(part, 0)
        if close > 0:
            return part[1:close]
    return part


def _statements(block: str) -> list[str]:
    """Split a C# statement list into top-level statements.

    A brace group is opaque and belongs to the statement that opened it;
    ``else``/``catch``/``finally`` continue the statement before them rather
    than starting a new one.
    """

    out: list[str] = []
    depth_p = depth_b = start = i = 0
    size = len(block)
    while i < size:
        ch = block[i]
        if ch in "([":
            depth_p += 1
        elif ch in ")]":
            depth_p -= 1
        elif ch == "{":
            depth_b += 1
        elif ch == "}":
            depth_b -= 1
            if depth_b == 0 and depth_p == 0 and \
                    _next_word(block, i + 1) not in ("else", "catch", "finally"):
                out.append(block[start:i + 1])
                start = i + 1
        elif ch == ";" and depth_b == 0 and depth_p == 0:
            if _next_word(block, i + 1) != "else":
                out.append(block[start:i + 1])
                start = i + 1
        i += 1
    out.append(block[start:])
    return [stmt for stmt in out if stmt.strip()]


@dataclass
class _Scan:
    """Mutable accumulator of one walk.

    ``visited`` exists to GUARD THE GUARD: a walker that silently skips a
    branch would report zero findings and look exactly like a clean corpus.
    Comparing visited sites against the sites present in the text turns that
    indistinguishable pair into a measurement (`witness_site_census`).
    """

    findings: list[tuple[str, str, str]] = field(default_factory=list)
    visited: int = 0


def _scan_block(
    block: str, guards: tuple[tuple[str, bool, str], ...], scan: "_Scan",
) -> None:
    terminated_by: str | None = None
    for statement in _statements(block):
        body = statement.strip()
        if terminated_by is not None:
            for match in re.finditer(re.escape(_VERDICT_CALL), body):
                scan.visited += 1
                scan.findings.append((VACUITY_UNREACHABLE, terminated_by,
                                      _excerpt(body, match.start())))
            continue
        if _TERMINATOR_RE.match(body):
            terminated_by = _norm(body)[:60]
            continue
        header = _HEADER_RE.match(body)
        if header is not None:
            keyword = header.group(1)
            open_at = body.index("(")
            close_at = _matching(body, open_at)
            if close_at < 0:
                _scan_statement(body, guards, scan)
                continue
            condition = body[open_at + 1:close_at]
            rest = body[close_at + 1:]
            if keyword == "if":
                then_part, else_part = _split_else(rest)
                _scan_block(_unwrap(then_part),
                            guards + ((condition, True, "if"),), scan)
                if else_part is not None:
                    _scan_block(_unwrap(else_part),
                                guards + ((condition, False, "if"),), scan)
            elif keyword == "while":
                _scan_block(_unwrap(rest),
                            guards + ((condition, True, "while"),), scan)
            elif keyword == "for":
                clauses = _split_top(condition, ";")
                middle = clauses[1] if len(clauses) == 3 else ""
                inner = ((guards + ((middle, True, "for"),))
                         if middle.strip() else guards)
                _scan_block(_unwrap(rest), inner, scan)
            else:
                # foreach/switch/lock/using/fixed carry NO static guard: the
                # body is treated as reachable (named limit above).
                _scan_block(_unwrap(rest), guards, scan)
            continue
        _scan_statement(body, guards, scan)


def _scan_statement(
    body: str, guards: tuple[tuple[str, bool, str], ...], scan: "_Scan",
) -> None:
    """A statement that is not a recognised header: recurse into its brace
    groups (``try``/``catch``/bare block/``do``) and judge the rest inline."""

    plain: list[str] = []
    i = 0
    size = len(body)
    while i < size:
        if body[i] == "{":
            close = _matching(body, i)
            if close < 0:
                plain.append(body[i:])
                break
            _scan_block(body[i + 1:close], guards, scan)
            i = close + 1
            continue
        plain.append(body[i])
        i += 1
    text = "".join(plain)
    verdict = _guard_verdict(guards)
    for match in re.finditer(re.escape(_VERDICT_CALL), text):
        scan.visited += 1
        if verdict is not None:
            kind, shown = verdict
            scan.findings.append((kind, shown, _excerpt(text, match.start())))


def analyze_witness_cs(code: str) -> tuple[tuple[tuple[str, str, str], ...], bool]:
    """Provably-dead ``__post.Add`` sites in ONE witness fragment.

    Returns ``(findings, partial)``.  ``partial`` says the fragment's brackets
    did not balance on their own, so it was analysed in pieces and the
    coverage is not the whole text — a THIRD state next to "clean" and
    "found something", kept separate so a reader cannot mistake a partial
    read for a proof of cleanliness.

    ``code`` must already be comment/string-stripped by :func:`_code`.
    """

    scan, partial = _walk(code)
    return tuple(scan.findings), partial


def _walk(code: str) -> tuple[_Scan, bool]:
    pieces, partial = _balanced_segments(code)
    scan = _Scan()
    for piece in pieces:
        _scan_block(piece, (), scan)
    return scan, partial


def witness_site_census(code: str) -> tuple[int, int]:
    """(verdict sites the WALK reached, verdict sites the TEXT contains).

    A walker that silently skipped a branch would report zero findings and be
    indistinguishable from a clean corpus.  These two numbers make the
    difference measurable, and the ratchet in
    ``tests/test_witness_vacuity.py`` requires them equal over every emitted
    witness of every registered op.
    """

    scan, _partial = _walk(code)
    return scan.visited, len(re.findall(re.escape(_VERDICT_CALL), code))


def witness_vacuity(
    op_name: str, checks: "list | None", post_code: str,
) -> tuple[tuple[VacuityFinding, ...], tuple[str, ...]]:
    """Vacuity findings for an op's post block + the fragments read only in part.

    Model path: judged per :class:`WitnessCheck`, so the finding is bound to
    the obligation KEY.  String path (``create_stairs``): judged over the whole
    post blob, key ``None``.
    """

    findings: list[VacuityFinding] = []
    partial: list[str] = []
    if checks is None:
        sites, was_partial = analyze_witness_cs(post_code)
        if was_partial:
            partial.append("<post>")
        findings.extend(
            VacuityFinding(op_name, None, kind, guard, excerpt)
            for kind, guard, excerpt in sites)
        return tuple(findings), tuple(partial)
    for check in checks:
        sites, was_partial = analyze_witness_cs(_code(check.render()))
        if was_partial:
            partial.append(check.obligation_key)
        findings.extend(
            VacuityFinding(op_name, check.obligation_key, kind, guard, excerpt)
            for kind, guard, excerpt in sites)
    return tuple(findings), tuple(partial)


# ---------------------------------------------------------------------------
# Certificate data model
# ---------------------------------------------------------------------------

# Obligation kinds — the observable classes an op postcondition can promise.
KIND_MATERIALIZE = "materialize"
KIND_GEOMETRY = "geometry"
KIND_TOPOLOGY = "topology"
KIND_PARAMETER = "parameter"
KIND_SEMANTIC = "semantic"
KIND_IDENTITY = "identity"
_KINDS = frozenset({
    KIND_MATERIALIZE, KIND_GEOMETRY, KIND_TOPOLOGY, KIND_PARAMETER,
    KIND_SEMANTIC, KIND_IDENTITY,
})

# Which emitted block an obligation's witness must live in.
BLOCK_CREATE = "create"
BLOCK_POST = "post"


@dataclass(frozen=True, slots=True)
class Obligation:
    """One proof obligation: a clause and the C# markers that discharge it."""

    clause: str                          # human-readable, aligned to OpSpec.post
    kind: str
    witness_markers: tuple[str, ...]     # ANY present in ``block`` discharges it
    block: str = BLOCK_POST
    param: str | None = None             # gating param for a conditional clause
    conditional: bool = False            # witness required ONLY when param present
    # height mismatch fix (30.07.2026): the mirror image of `conditional` —
    # witness required ONLY when `unless_param` is ABSENT.  create_wall's
    # height witness needs exactly this: WALL_USER_HEIGHT_PARAM stops being
    # authoritative (and the emitter stops witnessing it) the moment
    # top_level IS given, the opposite shape from every existing conditional
    # obligation (which all gate on their OWN param's presence).
    #
    # 10.08: МОЖЕТ СТОЯТЬ ВМЕСТЕ с `conditional`/`param`, и тогда требуются
    # ОБА условия. Повод — наклонная колонна (`create_column` с `top_xy`):
    # эмиттер СОЗНАТЕЛЬНО не свидетельствует у неё поворот, верхнюю привязку
    # и верхнее смещение, потому что ось задаёт верх целиком, а запись этих
    # параметров дралась бы с геометрией (причина записана в `_emit_column`).
    # Обязательства же были безусловными по этой оси, и сертификат объявлял
    # НЕДОКАЗУЕМЫМ то, чего у этого варианта опа не бывает вовсе — при
    # `KUKAI_IR_TRANSLATION_CERT=refuse` живая запись наклонной колонны
    # отказала бы KIR-R001 на ровном месте. Ровно тот же дефект уже чинили
    # 28.07 у `place_family` («у размещения по кривой уровня нет вовсе»), и
    # тогда лечение было тем же: сделать обязательство условным.
    unless_param: str | None = None
    # 03.08: gate on a TRUTHY value, not mere key presence.  Needed for
    # requirements that arrive as a CONTAINER the grounder always writes:
    # `__slope_reqs__` is `{}` on every route without slope_min_pct, so plain
    # key-presence would demand a slope witness from every plain route.
    # Deliberately NOT the global rule for `conditional` — `mirrored=False`
    # IS a request, and the emitter witnesses it.
    param_truthy: bool = False
    # Wave A2: for ops migrated to the witness model the obligation matches a
    # WitnessCheck.obligation_key — a machine KEY, never a C# substring.  When
    # ``key`` is set the markers become optional (unused on the model path);
    # string-path ops keep requiring markers.
    key: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise CertificateSchemaError(f"unknown obligation kind {self.kind!r}")
        if self.block not in (BLOCK_CREATE, BLOCK_POST):
            raise CertificateSchemaError(f"unknown block {self.block!r}")
        if self.conditional and self.param is None:
            raise CertificateSchemaError(
                f"conditional obligation {self.clause!r} needs a gating param")
        if self.param_truthy and not self.conditional:
            raise CertificateSchemaError(
                f"obligation {self.clause!r}: param_truthy only refines a "
                "conditional gate")
        if (self.unless_param is not None
                and self.param is not None and not self.conditional):
            raise CertificateSchemaError(
                f"obligation {self.clause!r}: unless_param may join a "
                "CONDITIONAL gate (both must hold), never a bare param")
        if self.unless_param is not None and self.unless_param == self.param:
            raise CertificateSchemaError(
                f"obligation {self.clause!r}: unless_param equals param — "
                "the two gates would contradict and the witness could never "
                "be required")
        if not self.witness_markers and self.key is None:
            raise CertificateSchemaError(
                f"obligation {self.clause!r} has neither witness markers nor "
                "a model key")


@dataclass(frozen=True, slots=True)
class OpRefinementSpec:
    """The full refinement contract for one op, parallel to ``spec.OPS``."""

    op: str
    materializer: tuple[str, ...]        # ANY marker proves the create call
    obligations: tuple[Obligation, ...]
    refuse_on_null: bool = True
    # Wave A2: "model" = the emitter returns list[WitnessCheck]; obligations
    # discharge by obligation KEY (correctness by construction — a check
    # cannot exist without its __post.Add verdict).  "string" = legacy post
    # string: marker matching + the verdict-span rule.
    witness_source: str = "string"


@dataclass(frozen=True, slots=True)
class ClauseVerdict:
    clause: str
    kind: str
    required: bool
    discharged: bool
    matched_marker: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class OpCertificate:
    op: str
    version: str
    materialized: bool
    refusal_guarded: bool
    clauses: tuple[ClauseVerdict, ...]
    #: Доказуемо мёртвые `__post.Add` этого опа.  Непустой кортеж ОТМЕНЯЕТ
    #: доказанность целиком — даже если каждое обязательство «разряжено»
    #: ключом: ключ доказывает существование строки, а не её достижимость.
    vacuous: tuple[VacuityFinding, ...] = ()
    #: Ключи витнесов, чей текст НЕ САМОДОСТАТОЧЕН по скобкам и разобран
    #: КУСКАМИ (шаблон create_stairs).  Не находка и не чистота — третье
    #: состояние, названное отдельно, чтобы неполный разбор не читался как
    #: доказательство чистоты.
    vacuity_partial: tuple[str, ...] = ()

    @property
    def proven(self) -> bool:
        return (
            self.materialized
            and self.refusal_guarded
            and not self.vacuous
            and all(v.discharged for v in self.clauses if v.required)
        )

    @property
    def gaps(self) -> tuple[str, ...]:
        holes: list[str] = []
        if not self.materialized:
            holes.append(f"{self.op}: no materializing API call emitted")
        if not self.refusal_guarded:
            holes.append(f"{self.op}: materialization not guarded by __Refuse")
        for verdict in self.clauses:
            if verdict.required and not verdict.discharged:
                holes.append(
                    f"{self.op}: unproven [{verdict.kind}] {verdict.clause} "
                    f"({verdict.reason})")
        holes.extend(finding.describe() for finding in self.vacuous)
        return tuple(holes)


@dataclass(frozen=True, slots=True)
class ProgramCertificate:
    version: str
    ops: tuple[OpCertificate, ...]

    @property
    def proven(self) -> bool:
        return all(cert.proven for cert in self.ops)

    @property
    def gaps(self) -> tuple[str, ...]:
        return tuple(gap for cert in self.ops for gap in cert.gaps)

    @property
    def vacuous(self) -> tuple[VacuityFinding, ...]:
        return tuple(f for cert in self.ops for f in cert.vacuous)


# ---------------------------------------------------------------------------
# The obligation table — machine form of every write op's OpSpec.post
# ---------------------------------------------------------------------------

# Shared witness marker groups (structural C#, NOT message text).
_ENDPOINTS = (".Location as LocationCurve",)           # _endpoint_check
_LEVEL_BIP = (
    "WALL_BASE_CONSTRAINT", "RBS_START_LEVEL_PARAM", "ROOF_BASE_LEVEL_PARAM",
    "FAMILY_BASE_LEVEL_PARAM", "FAMILY_LEVEL_PARAM", "SCHEDULE_LEVEL_PARAM",
    "LEVEL_PARAM", ".LevelId",                          # _level_check_expr / chain / room
)
_LOCATION_POINT = (".Location as LocationPoint",)
_BBOX = ("get_BoundingBox",)
_REFUSE = ("__Refuse",)


def _refinement_specs() -> dict[str, OpRefinementSpec]:
    ob = Obligation
    specs = [
        OpRefinementSpec(
            op="create_wall",
            materializer=("Wall.Create",),
            witness_source="model",
            obligations=(
                ob("wall exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("base constraint == resolved level (topology)",
                   KIND_TOPOLOGY, ("WALL_BASE_CONSTRAINT",),
                   key="base_constraint"),
                # Замер 29.07.2026 (два фасадных прогона: 4 стены + 5 полов,
                # затем 16 стен — «height mismatch» на КАЖДОЙ). height_mm
                # несёт registry-default (3000мм), и validate() подставляет
                # его в norm ДО эмиттера для ЛЮБОЙ опущенной стены — отличить
                # «явно попросили 3000» от «промолчали, потому что решает
                # top_level» эмиттер больше не может. WALL_USER_HEIGHT_PARAM
                # к тому же перестаёт быть источником истины, как только
                # верх стены привязан к уровню (Revit сам выводит высоту из
                # пары уровней). Обязательство required ТОЛЬКО когда
                # top_level ОТСУТСТВУЕТ — обратное направление обычного
                # conditional (см. Obligation.unless_param).
                ob("height param == height_mm when top_level is not given "
                   "(parameter)",
                   KIND_PARAMETER, ("WALL_USER_HEIGHT_PARAM",),
                   unless_param="top_level", key="height"),
                ob("arc curve == arc dict when supplied (geometry)",
                   KIND_GEOMETRY, (".Curve is Arc", "__arc"),
                   param="arc", conditional=True, key="arc"),
                ob("base offset param == base_offset_mm when given (geometry)",
                   KIND_GEOMETRY, ("WALL_BASE_OFFSET",),
                   param="base_offset_mm", conditional=True, key="base_offset"),
                # Замер 28.07 (docs/2026-07-28-location-line-measurement.md):
                # правило привязки НЕ двигает ни ось, ни тело — ни при
                # создании, ни потом; оно решает, какая плоскость переживёт
                # смену толщины. Значит ось у него семантическая, и читается
                # оно тем единственным, что у него есть, — ординалом
                # параметра. Геометрию стены закрывает свидетель концов.
                ob("location line rule == location_line when given (semantic)",
                   KIND_SEMANTIC, ("WALL_KEY_REF_PARAM",),
                   param="location_line", conditional=True,
                   key="location_line"),
                ob("top constraint == resolved top_level when given (topology)",
                   KIND_TOPOLOGY, ("WALL_HEIGHT_TYPE",),
                   param="top_level", conditional=True, key="top_constraint"),
                # Wall-fidelity (live A5 evidence 2026-07-21): explicit top
                # offset is a DEFINING DOF of the attach and must be witnessed.
                ob("top offset param == top_offset_mm when given (geometry)",
                   KIND_GEOMETRY, ("WALL_TOP_OFFSET",),
                   param="top_offset_mm", conditional=True, key="top_offset"),
            ),
        ),
        OpRefinementSpec(
            op="create_pipe",
            materializer=("Plumbing.Pipe.Create",),
            witness_source="model",
            obligations=(
                ob("pipe exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 3D (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
                ob("diameter param == diameter_mm when given (parameter)",
                   KIND_PARAMETER, ("RBS_PIPE_DIAMETER_PARAM",),
                   param="diameter_mm", conditional=True, key="diameter"),
            ),
        ),
        OpRefinementSpec(
            op="create_grid",
            materializer=("Grid.Create",),
            witness_source="model",
            obligations=(
                ob("grid exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("curve endpoints == p0/p1 (geometry)",
                   KIND_GEOMETRY, (".Curve",), key="endpoints"),
                ob("Name == name when given (identity)",
                   KIND_IDENTITY, (".Name != ",),
                   param="name", conditional=True, key="name"),
            ),
        ),
        OpRefinementSpec(
            op="create_level",
            materializer=("Level.Create",),
            witness_source="model",
            obligations=(
                ob("level exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("Elevation == elev_mm (geometry)",
                   KIND_GEOMETRY, (".Elevation",), key="elevation"),
                ob("Name == name when given (identity)",
                   KIND_IDENTITY, (".Name != ",),
                   param="name", conditional=True, key="name"),
            ),
        ),
        OpRefinementSpec(
            op="set_param",
            materializer=(".Set(",),
            witness_source="model",
            obligations=(
                ob("param resolved+writable or typed refusal (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("parameter holds requested value post-commit (parameter)",
                   KIND_PARAMETER, (".AsString(", ".AsDouble(", ".AsInteger("), key="value_held"),
            ),
        ),
        OpRefinementSpec(
            op="delete",
            materializer=("doc.Delete",),
            witness_source="model",
            obligations=(
                ob("target resolved or typed refusal (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("element no longer resolvable post-commit (semantic)",
                   KIND_SEMANTIC, ("doc.GetElement",), key="gone"),
            ),
        ),
        # CLASH-починка (28.07): move_elements / change_type.
        OpRefinementSpec(
            op="move_elements",
            materializer=("ElementTransformUtils.MoveElements",),
            witness_source="model",
            obligations=(
                ob("targets resolved, none pinned/stale, or typed refusal "
                   "(materialize)", KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("every target's Location shifted by delta_mm exactly "
                   "(geometry)", KIND_GEOMETRY,
                   _LOCATION_POINT + _ENDPOINTS, key="location"),
                ob("total CONNECTED connector count over targets unchanged "
                   "(topology)", KIND_TOPOLOGY, (".ConnectorManager",),
                   key="connectors"),
                ob("LocationCurve target slope (end1.Z-end0.Z) unchanged "
                   "(semantic)", KIND_SEMANTIC, (".GetEndPoint(",),
                   key="slope"),
            ),
        ),
        OpRefinementSpec(
            op="change_type",
            materializer=(".ChangeTypeId(",),
            witness_source="model",
            obligations=(
                ob("target/type resolved or typed refusal (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("GetTypeId() == requested type after Regenerate "
                   "(semantic)", KIND_SEMANTIC, (".GetTypeId()",),
                   key="type_held"),
            ),
        ),
        OpRefinementSpec(
            op="create_floor",
            materializer=("Floor.Create", "NewFloor"),
            witness_source="model",
            obligations=(
                ob("floor exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("level binding == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP, key="level_binding"),
                ob("bbox XY extents == outline extents (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
                ob("structural flag == requested (semantic)",
                   KIND_SEMANTIC, ("FLOOR_PARAM_IS_STRUCTURAL",),
                   key="structural"),
                # P1 DOF-completeness: смещение пола от уровня.
                ob("height offset param == height_offset_mm when given "
                   "(geometry)",
                   KIND_GEOMETRY, ("FLOOR_HEIGHTABOVELEVEL_PARAM",),
                   param="height_offset_mm", conditional=True,
                   key="height_offset"),
            ),
        ),
        # wave/arch (2026-07-29).
        OpRefinementSpec(
            op="create_ceiling",
            # Один-единственный материализатор: Ceiling.Create. У перекрытия
            # их два (Floor.Create / NewFloor — развилка версий), у потолка
            # второго не существует, и это ЗАМЕР, а не упрощение таблицы:
            # doc.Create.NewCeiling не компилируется ни на одной из шести
            # версий. Поэтому же сертификат потолка снимается только с 2022+
            # (__min_ver__ у arch_ceiling): на 2021 эмиссии нет вовсе — там
            # типизированный отказ KIR-E003, а не другая эмиссия.
            materializer=("Ceiling.Create",),
            witness_source="model",
            obligations=(
                ob("ceiling exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("level binding == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP, key="level_binding"),
                # Один свидетель на ОБА входа формы (09.08): прямой `outline`
                # и эскиз `contour` расходятся только в ЧИСЛЕ, с которым
                # сверяется габарит (вершины против lowered-edges с
                # кардинальными экстремумами дуг), а читается в обоих случаях
                # get_BoundingBox созданного потолка. Второе обязательство
                # здесь означало бы, что одна из веток может остаться без
                # свидетеля и сертификат этого не заметит.
                ob("bbox XY extents == outline or contour extents (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
                ob("height offset param == height_offset_mm when given "
                   "(geometry)",
                   KIND_GEOMETRY, ("CEILING_HEIGHTABOVELEVEL_PARAM",),
                   param="height_offset_mm", conditional=True,
                   key="height_offset"),
            ),
        ),
        OpRefinementSpec(
            op="create_railing",
            # Обе перегрузки называются Railing.Create — одного маркера
            # хватает на обе ветви.
            materializer=("Railing.Create",),
            witness_source="model",
            obligations=(
                ob("railing exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # ОДНО обязательство на две ветви, как "footprint" у
                # create_foundation: у свободного ограждения якорь — уровень,
                # у лестничного — хозяин. Любой из двух маркеров доказывает
                # ту привязку, которая на этой ветви вообще существует.
                ob("path variety: base level == resolved level OR hosted "
                   "variety: railing belongs to the requested host "
                   "(topology)",
                   KIND_TOPOLOGY,
                   ("STAIRS_RAILING_BASE_LEVEL_PARAM", "HasHost"),
                   key="anchor"),
                # Габарит проверяем только там, где мы САМИ задали геометрию.
                # У лестничного ограждения путь выбирает Revit по маршу, и
                # требовать от него наш bbox значило бы проверять выдуманное.
                ob("path variety: bbox XY extents == path extents (geometry)",
                   KIND_GEOMETRY, _BBOX, param="path", conditional=True,
                   key="bbox"),
            ),
        ),
        # wave/site (2026-08-09).
        OpRefinementSpec(
            op="create_topography",
            # ДВА материализатора, потому что разновидностей две и это два
            # РАЗНЫХ вызова API, а не развилка версий одного: поверхность и
            # толща — элементы разных категорий.
            materializer=("TopographySurface.Create", "Toposolid.Create"),
            witness_source="model",
            obligations=(
                ob("topography exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # ОДНО обязательство на две ветви, как "anchor" у
                # create_railing: поверхность отдаёт точки через GetPoints(),
                # толща — через вершины редактора формы (GetPoints() у неё не
                # существует, замерено). Любой из двух маркеров доказывает то
                # чтение, которое на этой ветви вообще возможно.
                ob("described terrain points read back from the built "
                   "element (geometry)",
                   KIND_GEOMETRY, ("GetPoints", "SlabShapeVertices"),
                   key="terrain_points"),
                ob("bbox XY extents == points XY extents (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
                # Условное: уровень существует ТОЛЬКО у толщи (у поверхности
                # его нет в API вовсе), и ground не кладёт его в
                # variety=surface — значит гейт по присутствию поля точен.
                ob("level binding == resolved level when variety=toposolid "
                   "(topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP, param="level", conditional=True,
                   key="level_binding"),
            ),
        ),
        OpRefinementSpec(
            op="create_building_pad",
            materializer=("BuildingPad.Create",),
            witness_source="model",
            obligations=(
                ob("building pad exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("level binding == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP, key="level_binding"),
                # Читатель здесь НЕ get_BoundingBox: габарит тела площадки
                # включает её толщину и вырез в рельефе. Читается сама
                # граница, то есть ровно переданный эскиз.
                ob("GetBoundary() re-read bbox == contour lowered-edges bbox "
                   "(geometry)",
                   KIND_GEOMETRY, ("GetBoundary",), key="bbox"),
                ob("AssociatedTopographySurfaceId holds a real element id "
                   "(topology)",
                   KIND_TOPOLOGY, ("AssociatedTopographySurfaceId",),
                   key="hosting_topography"),
            ),
        ),
        # wave/sweep (2026-08-09). ДВА СЕРТИФИКАТА РАЗНОЙ СИЛЫ, и разница
        # объявлена здесь, а не сглажена: у краевого профиля есть
        # обязательство рода GEOMETRY, у стенного его НЕТ ВОВСЕ — потому что
        # положение стенного профиля задаёт ТИП, а не вызов (ремарка Autodesk
        # во всех шести RevitAPI.xml, процитирована дословно в `post` и
        # освобождена от сверки явной строкой в _NON_WITNESSABLE_CLAUSES).
        # Придумать ему геометрическое обязательство значило бы предъявить
        # свидетеля, который не может провалиться, — а это, по закону этого
        # файла, хуже отсутствующего.
        OpRefinementSpec(
            op="create_wall_sweep",
            materializer=("WallSweep.Create",),
            witness_source="model",
            obligations=(
                ob("wall sweep exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # ПРЕДПОЛЁТ, КОТОРОГО ТРЕБУЕТ САМ API: «wall may not host a
                # wall sweep or reveal» стоит среди условий ArgumentException
                # у Create. Обязательство блока СОЗДАНИЯ, а не поста: оно
                # обязано сработать ДО эффекта, иначе отказ приедет
                # исключением Revit и будет записан как `internal`.
                ob("a wall that may not host a sweep is a typed refusal from "
                   "WallAllowsWallSweep before the call",
                   KIND_MATERIALIZE, ("WallAllowsWallSweep",),
                   block=BLOCK_CREATE),
                ob("GetHostIds() re-read contains the requested wall "
                   "(topology)",
                   KIND_TOPOLOGY, ("GetHostIds",), key="sweep_host"),
                ob("GetTypeId() re-read == resolved wall sweep type "
                   "(topology)",
                   KIND_TOPOLOGY, ("GetTypeId",), key="sweep_type"),
                ob("GetWallSweepInfo().IsVertical == requested orientation "
                   "(semantic)",
                   KIND_SEMANTIC, ("GetWallSweepInfo",),
                   key="sweep_orientation"),
            ),
        ),
        OpRefinementSpec(
            op="create_slab_edge",
            materializer=("NewSlabEdge",),
            witness_source="model",
            obligations=(
                ob("slab edge exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # МОЩНОСТЬ — ОБЯЗАТЕЛЬСТВО БЛОКА СОЗДАНИЯ, и это единственное
                # место, где она может быть исполнена: ссылки на рёбра
                # выбираются ДО вызова, и «первая подходящая» после него уже
                # неотличима от правильной.
                ob("the named side resolves to exactly one face and that "
                   "face to exactly one edge loop, and any other cardinality "
                   "is a typed refusal naming the count",
                   KIND_MATERIALIZE, ("EdgeLoops",), block=BLOCK_CREATE),
                ob("every perimeter edge handed to the call is bound in the "
                   "built sweep: get_ReferenceCurve is non-null for each "
                   "(geometry)",
                   KIND_GEOMETRY, ("get_ReferenceCurve",),
                   key="slab_edge_binding"),
                ob("GetTypeId() re-read == resolved slab edge type "
                   "(topology)",
                   KIND_TOPOLOGY, ("GetTypeId",), key="sweep_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_site_subregion",
            materializer=("SiteSubRegion.Create",),
            witness_source="model",
            obligations=(
                ob("site subregion exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("the created surface reports IsSiteSubRegion (semantic)",
                   KIND_SEMANTIC, ("IsSiteSubRegion",), key="is_subregion"),
                ob("GetBoundary() re-read bbox == contour lowered-edges bbox "
                   "(geometry)",
                   KIND_GEOMETRY, ("GetBoundary",), key="bbox"),
                ob("HostId holds a real element id, and equals host when "
                   "given (topology)",
                   KIND_TOPOLOGY, ("HostId",), key="host_binding"),
            ),
        ),
        OpRefinementSpec(
            op="create_directshape",
            materializer=("DirectShape.CreateElement",),
            witness_source="model",
            obligations=(
                ob("direct shape exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # Габарит ПО ТРЁМ ОСЯМ: у меша Z — такая же координата входа,
                # как X и Y, поэтому общий XY-свидетель перекрытий здесь не
                # годится (свидетель обязан подписывать ту ось, которую
                # действительно читал).
                ob("bbox extents == mesh vertex extents in XYZ (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
                # Число граней вычитывается С ПОСТРОЕННОГО элемента через
                # Mesh.NumTriangles, а не пересчитывается из нашего же входа —
                # иначе обязательство подтверждало бы вызов, а не результат.
                ob("built mesh triangle count == triangles count (geometry)",
                   KIND_GEOMETRY, ("NumTriangles",), key="triangles"),
                # ПОВЕРХНОСТЬ, А НЕ ЕЁ ЧИСЛО. Число граней не видит пересборку
                # Salvage, которая сохранила количество и сдвинула вершину:
                # такой элемент проходит молча и снаружи неотличим от успеха.
                # Обязательство разряжается свидетелем, который строит канон
                # поверхности (`mesh_surface_payload`) из ПОСТРОЕННОГО меша и
                # сравнивает с прообразом, пред-регистрированным до эффекта.
                ob("built mesh surface multiset == authored surface multiset "
                   "on the canon grid (geometry)",
                   KIND_GEOMETRY, ("__KirCanonPayload",), key="surface"),
            ),
        ),
        # wave/solid (2026-08-09): параметрическое тело. Оба опа несут
        # ОДИН И ТОТ ЖЕ набор обязательств, и это не копипаста: свидетели у
        # них РАЗНЫЕ по формуле (призма против тела вращения), а обязательство
        # — про то, ЧТО доказано, а не про то, как. Ключи совпадают именно
        # потому, что доказывается одно и то же.
        OpRefinementSpec(
            op="create_solid_extrusion",
            materializer=("GeometryCreationUtilities.CreateExtrusionGeometry",),
            witness_source="model",
            obligations=(
                ob("solid direct shape exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # СКОЛЬКО ТЕЛ. Одно — это и есть заявленная форма; два
                # означают, что Revit разрезал её, ноль — что не построил, и
                # оба случая снаружи выглядят как успех.
                ob("built geometry holds exactly one solid (geometry)",
                   KIND_GEOMETRY, ("__nsol_",), key="solid_count"),
                # СЕРДЦЕ ВОЛНЫ. Объём вычитывается с ПОСТРОЕННОГО тела и
                # сверяется с числом, которого во входе не было ни в каком
                # виде: площадь профиля × высота, обе замкнутой формой на
                # компиляции. Это не пересчёт нашего же ввода.
                ob("solid volume == profile area * extrusion height, both "
                   "closed-form at compile time (geometry)",
                   KIND_GEOMETRY, ("Volume",), key="volume"),
                # ВТОРАЯ, НЕЗАВИСИМАЯ ОСЬ. Площадь торцов не смешивает
                # площадь с высотой, поэтому ловит то, чего объём не ловит
                # (профиль другой формы той же площади при другой высоте).
                # Читаются ТОЛЬКО плоские грани — к кривым поверхностям, о
                # занижении площади которых предупреждает RevitAPI.xml, этот
                # свидетель не прикасается.
                ob("planar cap area == twice the profile area (geometry)",
                   KIND_GEOMETRY, ("PlanarFace",), key="cap_area"),
                ob("bbox extents == profile bbox by base_z..base_z+height in "
                   "XYZ (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
            ),
        ),
        OpRefinementSpec(
            op="create_solid_revolve",
            materializer=("GeometryCreationUtilities.CreateRevolvedGeometry",),
            witness_source="model",
            obligations=(
                ob("revolved direct shape exists (materialized or typed "
                   "refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("built geometry holds exactly one solid (geometry)",
                   KIND_GEOMETRY, ("__nsol_",), key="solid_count"),
                # θ·∬x dA — вывод в докстринге emit_solid_revolve (Фубини в
                # цилиндрических координатах; первая теорема Паппа есть его
                # частный случай при θ=2π).
                ob("solid volume == sweep radians * profile first moment about "
                   "the axis, closed-form at compile time (geometry)",
                   KIND_GEOMETRY, ("Volume",), key="volume"),
                # БЕЗУСЛОВНОЕ, И ЭТО НЕ НЕДОСМОТР. Первая редакция гейтила
                # свидетеля торцов на неполный оборот — «у 360° торцов нет,
                # проверять нечего». Ровно наоборот: у полного оборота
                # ожидаемая площадь торцов равна НУЛЮ, и это содержательная
                # проверка того, что оборот ЗАМКНУЛСЯ. Собери Revit вместо
                # кольца клин — на месте нуля окажется удвоенная площадь
                # профиля, и условный свидетель оставил бы самую вероятную
                # поломку 360° без единого читателя.
                ob("planar cap area == twice the profile area for a sector "
                   "and zero for a full turn (geometry)",
                   KIND_GEOMETRY, ("PlanarFace",), key="cap_area"),
                ob("bbox extents == the swept annular sector of the profile in "
                   "XYZ (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
            ),
        ),
        # wave/mass (2026-08-10): стена по наклонной грани концептуальной
        # массы. ДВА ОБЯЗАТЕЛЬСТВА БЛОКА СОЗДАНИЯ, и оба обязаны сработать ДО
        # эффекта: Revit привёз к этой фабрике СВОИ предполётные валидаторы, и
        # спросить их после вызова уже нечего — отказ приедет исключением и
        # ляжет в квитанцию как `internal`, то есть «у нас что-то сломалось»
        # вместо «Revit не берёт такой тип / такую грань».
        OpRefinementSpec(
            op="create_face_wall",
            materializer=("FaceWall.Create",),
            witness_source="model",
            obligations=(
                ob("face wall exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("a wall type Revit refuses for a face wall is a typed "
                   "refusal from IsWallTypeValidForFaceWall before the call",
                   KIND_MATERIALIZE, ("IsWallTypeValidForFaceWall",),
                   block=BLOCK_CREATE),
                ob("a face Revit refuses as a face-wall parent is a typed "
                   "refusal from IsValidFaceReferenceForFaceWall before the "
                   "call",
                   KIND_MATERIALIZE, ("IsValidFaceReferenceForFaceWall",),
                   block=BLOCK_CREATE),
                ob("GetTypeId() re-read == resolved wall type (topology)",
                   KIND_TOPOLOGY, ("GetTypeId",), key="face_wall_type"),
                # ГЛАВНОЕ ГЕОМЕТРИЧЕСКОЕ ОБЯЗАТЕЛЬСТВО ВОЛНЫ. Читается
                # ПОСТРОЕННАЯ стена: среди её наружных граней обязана быть
                # ровно одна, сонаправленная названной грани массы. Ноль
                # означает, что Revit прицепил стену не туда, — и снаружи это
                # неотличимо от успеха.
                ob("the built wall has EXACTLY ONE exterior side face "
                   "codirectional with the named mass face (geometry)",
                   KIND_GEOMETRY, ("GetSideFaces",), key="face_wall_normal"),
                ob("a point of that face lies inside the host's model-space "
                   "bounding box grown by the wall's own WallType.Width plus "
                   "VertexTolerance (geometry)",
                   KIND_GEOMETRY, ("get_BoundingBox",),
                   key="face_wall_within_host"),
                # ЧИТАЕТ ТЕЛО, А НЕ ПАРАМЕТР: маркер `PlanarFace` — это и
                # есть та разница, ради которой §18.3 существует. Прежняя
                # редакция стояла на `HOST_AREA_COMPUTED` и подписывала
                # геометрию, не читая её.
                ob("the PlanarFace.Area of that same built face is strictly "
                   "positive (geometry)",
                   KIND_GEOMETRY, ("PlanarFace",),
                   key="face_wall_area_positive"),
            ),
        ),
        # wave/room (2026-08-03): разделитель помещений.
        OpRefinementSpec(
            op="create_room_separator",
            materializer=("NewRoomBoundaryLines",),
            witness_source="model",
            obligations=(
                ob("room separator segments exist (materialized or typed "
                   "refusal)", KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # СКОЛЬКО. Ломаная из n точек обязана дать n-1 кривую: одна
                # линия вместо четырёх — это не «почти построили», это другая
                # граница, и снаружи она выглядит успехом.
                #
                # KIND_IDENTITY, А НЕ KIND_MATERIALIZE, И ЭТО НЕ ВКУС:
                # materialize-обязательства сертификат гасит СТОРОНОЙ СОЗДАНИЯ
                # (наличие материализатора + __Refuse) и на свидетеля не
                # смотрит вовсе — то есть под этим родом вырезание живого
                # свидетеля оставляло бы PROVEN. Поймал мутационный оракул L6
                # (test_tolerance_provenance), а не рассуждение.
                ob("созданных сегментов ровно на один меньше, чем точек path "
                   "(identity)",
                   KIND_IDENTITY, (".Count !=",), key="segment_count"),
                # ЧТО ИМЕННО. Сердце операции: обычная модельная линия на том
                # же месте не ограничивает ничего и снаружи неотличима от
                # разделителя — ровно та подмена, из-за которой волна потолков
                # отказалась строить перекрытие вместо потолка.
                ob("каждый созданный сегмент лежит в категории "
                   "OST_RoomSeparationLines, а не в обычных модельных линиях "
                   "(topology)",
                   KIND_TOPOLOGY, ("OST_RoomSeparationLines",),
                   key="category"),
                # ГДЕ. Element.LevelId — то же первое звено, которым уровень
                # читает сторона извлечения: один вопрос, один судья.
                ob("level binding == resolved level у каждого сегмента "
                   "(topology)", KIND_TOPOLOGY, (".LevelId",),
                   key="level_binding"),
                ob("концы каждого сегмента == соседняя пара точек path "
                   "(geometry)", KIND_GEOMETRY, (".GetEndPoint(",),
                   key="endpoints"),
            ),
        ),
        # wave/space (2026-08-10): пространство ОВК.
        #
        # КЛАУЗУЛЫ ЗДЕСЬ — ДОСЛОВНЫЕ КОПИИ `OpSpec.post`, и это не стиль:
        # `audit_registry_coverage` сверяет прозу по ОБЩИМ СЛОВАМ, то есть
        # перефразировка может пройти аудит на чужих словах (замеренный
        # промах — уклон route_*, где «segment» встречался и у диаметра).
        # Дословная копия убирает этот класс ошибки целиком.
        OpRefinementSpec(
            op="create_space",
            materializer=("doc.Create.NewSpace",),
            witness_source="model",
            obligations=(
                ob("space exists and is placed (materialized or typed "
                   "refusal)", KIND_MATERIALIZE, _REFUSE,
                   block=BLOCK_CREATE),
                # ГДЕ — уровень. Тот же `.LevelId`, которым уровень читает и
                # сторона извлечения.
                ob("LevelId == resolved level (topology)",
                   KIND_TOPOLOGY, (".LevelId",), key="level_binding"),
                # ГДЕ — точка. `Location` СЧИТАЕТ REVIT, поэтому подпись
                # «(geometry)» законна под §18.3: читатель не сводится к
                # `get_Parameter(...)`, который мы же и записали.
                ob("LocationPoint == xy (±5mm) (geometry)",
                   KIND_GEOMETRY, _LOCATION_POINT, key="location"),
                # ЗАМКНУТО ЛИ — ВЕЛИЧИНА. Площадь, а не объём: `Space.Volume`
                # зависит от настройки расчёта объёмов в документе, и
                # обязательство на нём проверяло бы галочку проекта, а не
                # построенное.
                ob("Area > 0 — пространство замкнуто, а не создано впустую "
                   "(geometry)", KIND_GEOMETRY, (".Area",), key="area"),
                # ЗАМКНУТО ЛИ — ОТНОШЕНИЕ, И ЭТО ОТДЕЛЬНОЕ ОБЯЗАТЕЛЬСТВО, А
                # НЕ ДУБЛЬ ПРЕДЫДУЩЕГО. Площадь отвечает «сколько», петли
                # границы — «чем ограничено». Топологическую ось разряжает
                # ТОЛЬКО вторая: подписать «(topology)» под чтением площади
                # значило бы сертифицировать ось, которой читатель не
                # касался, — ровно тот дефект, ради которого написан
                # test_witness_axis_honesty.
                ob("GetBoundarySegments даёт хотя бы одну непустую петлю "
                   "границы (topology)",
                   KIND_TOPOLOGY, ("GetBoundarySegments",), key="boundary"),
            ),
        ),
        # wave/opening (2026-08-03): проём как ОТДЕЛЬНЫЙ элемент.
        OpRefinementSpec(
            op="create_opening",
            # Один материализатор на обе ветви: перегрузки NewOpening
            # различаются аргументами, а не именем.
            materializer=("doc.Create.NewOpening",),
            witness_source="model",
            obligations=(
                ob("opening exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # ПРИНАДЛЕЖНОСТЬ — общее обязательство обеих ветвей: и у
                # прямоугольного проёма в стене, и у профильного в
                # перекрытии носитель читается одним и тем же
                # `Opening.Host`. Ключ поэтому один, безусловный.
                ob("opening belongs to the host element the program asked "
                   "for (Opening.Host, topology)",
                   KIND_TOPOLOGY, (".Host",), key="host"),
                # ГАБАРИТ — ключи РАЗНЫЕ, потому что читаются разные члены
                # API и ветви взаимоисключающие. Общий ключ здесь был бы
                # дефектом: необязательное обязательство разряжается ровно
                # ОТСУТСТВИЕМ своего свидетеля (certify_op), и один ключ на
                # две условные ветви объявил бы витнес соседней ветви
                # «лишним».
                ob("wall_rect variety: IsRectBoundary and the BoundaryRect "
                   "corners hold the requested Z band and width along the "
                   "wall, the absolute shift staying unpinned (geometry)",
                   KIND_GEOMETRY, ("BoundaryRect",),
                   param="p0_mm", conditional=True, key="rect_extent"),
                ob("host_face variety with outline: the BoundaryCurves "
                   "extents == outline extents for a vertical cut and "
                   "contain them for a perpendicular one (geometry)",
                   KIND_GEOMETRY, ("BoundaryCurves",),
                   param="outline", conditional=True, key="bbox"),
                # ВТОРОЙ ВХОД ФОРМЫ — СВОЙ КЛЮЧ, по тому же доводу, что у
                # двух родов абзацем выше: `outline` и `contour` взаимно
                # исключительны, а условное обязательство разряжается ровно
                # ОТСУТСТВИЕМ своего свидетеля. Общий ключ объявил бы витнес
                # соседнего входа «лишним» на каждой программе.
                #
                # Обещание тут СЛАБЕЕ, и намеренно: у эскиза габарит
                # сверяется ПОЛОСОЙ (вершины снизу, точный габарит с дугами
                # сверху), потому что экстремум дуги достаётся только
                # конечной выборкой по `Curve.Evaluate`, а её плотности API
                # не обещает. Разбор — в шапке `opening_emit.py`.
                ob("host_face variety with contour: the BoundaryCurves "
                   "extents cover the contour vertex extents and, for a "
                   "vertical cut, stay inside its arc-aware extents "
                   "(geometry)",
                   KIND_GEOMETRY, ("BoundaryCurves",),
                   param="contour", conditional=True, key="bbox_contour"),
            ),
        ),
        OpRefinementSpec(
            op="create_roof",
            materializer=("NewFootPrintRoof",),
            witness_source="model",
            obligations=(
                ob("roof exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("base level == resolved level (topology)",
                   KIND_TOPOLOGY, ("ROOF_BASE_LEVEL_PARAM",), key="base_level"),
                ob("bbox XY extents == outline extents (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
            ),
        ),
        OpRefinementSpec(
            op="create_column",
            materializer=("NewFamilyInstance",),
            witness_source="model",
            obligations=(
                ob("column exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationPoint == xy (geometry)",
                   KIND_GEOMETRY, _LOCATION_POINT, key="location"),
                ob("level binding == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP, key="level_binding"),
                ob("StructuralType == requested (semantic)",
                   KIND_SEMANTIC, (".StructuralType",), key="structural_type"),
                # Поворот, верхняя привязка и верхнее смещение сняты у
                # НАКЛОННОЙ колонны (`top_xy`): у неё верх задаёт ОСЬ, эмиттер
                # сознательно не пишет верхние параметры (запись дралась бы с
                # геометрией) и не свидетельствует поворот (ориентацию несёт
                # ось). Требовать их назад значило бы объявить недоказуемым
                # то, чего у этого варианта опа не бывает. `base_offset`
                # остаётся: нижний конец оси считается ИЗ него, обещание наше.
                ob("rotation == rotation_deg when given (geometry)",
                   KIND_GEOMETRY, (".Rotation",),
                   param="rotation_deg", conditional=True,
                   unless_param="top_xy", key="rotation"),
                # P1 DOF-completeness (fidelity audit 2026-07-21): столбовая
                # вертикаль — определяющие DOF attach'а колонны.
                ob("base offset param == base_offset_mm when given (geometry)",
                   KIND_GEOMETRY, ("FAMILY_BASE_LEVEL_OFFSET_PARAM",),
                   param="base_offset_mm", conditional=True, key="base_offset"),
                ob("top constraint == resolved top_level when given (topology)",
                   KIND_TOPOLOGY, ("FAMILY_TOP_LEVEL_PARAM",),
                   param="top_level", conditional=True,
                   unless_param="top_xy", key="top_constraint"),
                ob("top offset param == top_offset_mm when given (geometry)",
                   KIND_GEOMETRY, ("FAMILY_TOP_LEVEL_OFFSET_PARAM",),
                   param="top_offset_mm", conditional=True,
                   unless_param="top_xy", key="top_offset"),
            ),
        ),
        OpRefinementSpec(
            op="create_window",
            materializer=("NewFamilyInstance",),
            witness_source="model",
            obligations=_hosted_obligations("window"),
        ),
        OpRefinementSpec(
            op="create_door",
            materializer=("NewFamilyInstance",),
            witness_source="model",
            obligations=_hosted_obligations("door"),
        ),
        OpRefinementSpec(
            op="create_room",
            materializer=("NewRoom",),
            witness_source="model",
            obligations=(
                ob("room exists and nonzero area (materialize / semantic)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LevelId == resolved level (topology)",
                   KIND_TOPOLOGY, (".LevelId",), key="level_binding"),
                ob("LocationPoint == xy (geometry)",
                   KIND_GEOMETRY, _LOCATION_POINT, key="location"),
                ob("nonzero enclosed area (semantic)",
                   KIND_SEMANTIC, (".Area",), key="area"),
                ob("Name == name when given (identity)",
                   KIND_IDENTITY, (".Name != ",),
                   param="name", conditional=True, key="name"),
                # ROOM_NUMBER is an independent semantic field.  The emitter
                # rereads the built-in parameter after Set; Room.Name is a
                # display composite and cannot discharge this obligation.
                ob("Number == number when given (semantic)",
                   KIND_SEMANTIC, ("ROOM_NUMBER", ".AsString()"),
                   param="number", conditional=True, key="number"),
            ),
        ),
        OpRefinementSpec(
            op="place_family",
            materializer=("NewFamilyInstance",),
            witness_source="model",
            obligations=(
                ob("instance exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # У опа два варианта размещения, и сертификат обязан
                # называть ТОТ, который доказан. Пока обязательство было
                # одно, кривой вариант разряжал его по ключу `location` — и
                # сертификат писал «LocationPoint == xyz» про экземпляр, у
                # которого LocationPoint не существует. Доказанное неверное
                # утверждение хуже недоказанного: оно выглядит проверкой.
                ob("LocationPoint == xyz (geometry)",
                   KIND_GEOMETRY, _LOCATION_POINT,
                   param="xyz", conditional=True, key="location"),
                ob("LocationCurve endpoints == p0_mm/p1_mm (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS,
                   param="p0_mm", conditional=True, key="location"),
                # Уровень — принадлежность ТОЧЕЧНОГО варианта. У размещения по
                # кривой на хосте уровня нет вовсе: Revit берёт его у хоста, и
                # безусловное обязательство здесь неразрядимо в принципе —
                # сертификат объявлял бы недоказуемым то, чего в опе нет.
                # Ровно та же поправка, что уже сделана выше для `location`.
                ob("level binding == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP,
                   param="level", conditional=True, key="level_binding"),
                # Хост эмиттер читает обратно (`__el_.Host`), а сертификат про
                # эту проверку не знал: свидетель без обязательства — это
                # проверка, которую можно молча удалить, не уронив ни один
                # сертификат. Та же дыра, что закрыли по диаметру 27.07.
                ob("host == resolved host (topology)",
                   KIND_TOPOLOGY, (".Host",),
                   param="host", conditional=True, key="host"),
                # ── РОДЫ РАЗМЕЩЕНИЯ (11.08.2026) ───────────────────────
                # Все УСЛОВНЫ, как и соседи: обязательство разряжается
                # ОТСУТСТВИЕМ своего свидетеля, когда операнд не назван
                # (`certify_op`), поэтому ключ у каждого свой — общий
                # объявил бы свидетеля соседней ветки «лишним».
                ob("reference direction == ref_dir when given, read back "
                   "from HandOrientation up to sense (geometry)",
                   KIND_GEOMETRY, ("HandOrientation",),
                   param="ref_dir", conditional=True,
                   key="reference_direction"),
                ob("FAMILY_TOP_LEVEL_PARAM == top_level when given "
                   "(topology)",
                   KIND_TOPOLOGY, ("FAMILY_TOP_LEVEL_PARAM",),
                   param="top_level", conditional=True,
                   key="top_level_binding"),
                # ОДНА клаузула `post` — ДВА обязательства, и это не
                # разнобой: смещения независимы (автор вправе назвать только
                # одно), а условность разряжается ПОКЛЮЧЕВО. Аудит покрытия
                # режет `post` по точке с запятой и ищет пересечение слов —
                # обе строки честно указывают на ту же клаузулу.
                ob("base/top offsets == the requested millimetres when given "
                   "(semantic)",
                   KIND_SEMANTIC, ("FAMILY_BASE_LEVEL_OFFSET_PARAM",),
                   param="base_offset_mm", conditional=True,
                   key="base_offset"),
                ob("base/top offsets == the requested millimetres when given "
                   "(semantic)",
                   KIND_SEMANTIC, ("FAMILY_TOP_LEVEL_OFFSET_PARAM",),
                   param="top_offset_mm", conditional=True,
                   key="top_offset"),
                ob("rotation == rotation_deg when given (geometry)",
                   KIND_GEOMETRY, (".Rotation",),
                   param="rotation_deg", conditional=True, key="rotation"),
                ob("mirrored state == requested when given (semantic)",
                   KIND_SEMANTIC, (".Mirrored != ",),
                   param="mirrored", conditional=True, key="mirrored"),
                ob("hand flip state == requested when given (semantic)",
                   KIND_SEMANTIC, (".HandFlipped != ",),
                   param="hand_flipped", conditional=True, key="hand_flipped"),
                ob("facing flip state == requested when given (semantic)",
                   KIND_SEMANTIC, (".FacingFlipped != ",),
                   param="facing_flipped", conditional=True, key="facing_flipped"),
            ),
        ),
        OpRefinementSpec(
            op="create_pipe_system",
            materializer=("Plumbing.Pipe.Create",),
            witness_source="model",
            obligations=_network_obligations("RBS_PIPE_DIAMETER_PARAM"),
        ),
        OpRefinementSpec(
            op="route_pipe_system",
            materializer=("Plumbing.Pipe.Create",),
            witness_source="model",
            obligations=_network_obligations(
                "RBS_PIPE_DIAMETER_PARAM", with_slope=True, with_level=True),
        ),
        OpRefinementSpec(
            op="route_duct_system",
            materializer=("Mechanical.Duct.Create",),
            witness_source="model",
            obligations=_network_obligations(
                "RBS_CURVE_DIAMETER_PARAM", with_slope=True, with_level=True),
        ),
        OpRefinementSpec(
            op="create_floor_by_contour",
            materializer=("Floor.Create", "NewFloor"),
            witness_source="model",
            obligations=(
                ob("floor exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("level binding == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP, key="level_binding"),
                ob("bbox == lowered-edges extents (geometry)",
                   KIND_GEOMETRY, _BBOX, key="bbox"),
                ob("height offset param == height_offset_mm when given "
                   "(geometry)",
                   KIND_GEOMETRY, ("FLOOR_HEIGHTABOVELEVEL_PARAM",),
                   param="height_offset_mm", conditional=True,
                   key="height_offset"),
            ),
        ),
        OpRefinementSpec(
            op="create_duct",
            materializer=("Mechanical.Duct.Create",),
            witness_source="model",
            obligations=(
                ob("duct exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 3D (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
                ob("diameter param == diameter_mm when given (parameter)",
                   KIND_PARAMETER, ("RBS_CURVE_DIAMETER_PARAM",),
                   param="diameter_mm", conditional=True, key="diameter"),
            ),
        ),
        OpRefinementSpec(
            op="create_cable_tray",
            materializer=("Electrical.CableTray.Create",),
            witness_source="model",
            obligations=(
                ob("cable tray exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 3D (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
                ob("width param == width_mm when given (parameter)",
                   KIND_PARAMETER, ("RBS_CABLETRAY_WIDTH_PARAM",),
                   param="width_mm", conditional=True, key="width"),
                ob("height param == height_mm when given (parameter)",
                   KIND_PARAMETER, ("RBS_CABLETRAY_HEIGHT_PARAM",),
                   param="height_mm", conditional=True, key="height"),
            ),
        ),
        # wave/mep-electrical (2026-08-09). Пять операций, три жанра
        # свидетеля — и ни у одной обязательство не сводится к «сеттер
        # отработал»: у короба и заготовок ось читается у Revit
        # (`LocationCurve`), у гибких — весь путь (`Points`), тип у всех
        # берётся `GetTypeId()` с построенного элемента.
        OpRefinementSpec(
            op="create_conduit",
            materializer=("Electrical.Conduit.Create",),
            witness_source="model",
            obligations=(
                ob("conduit exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 3D (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
                ob("conduit_type of the built element == resolved "
                   "conduit_type (semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="conduit_type"),
            ),
        ),
        # wave/analysis (2026-08-09). Три нагрузки и путь эвакуации.
        # Обязательства перечислены в том же порядке, в каком их эмитирует
        # analysis_emit.py, и каждое читает СВОЙСТВО ПОСТРОЕННОГО ЭЛЕМЕНТА:
        # у нагрузок — `Point`/`StartPoint`/`GetLoops`, `OrientTo`,
        # `ForceVector*`, `LoadCaseId`, `GetTypeId`; у маршрута —
        # `PathStart`/`PathEnd`, `GetCurves`, `OwnerViewId`.
        #
        # `OrientTo` стоит здесь ОТДЕЛЬНЫМ обязательством, а не примечанием к
        # силе: `ForceVector` документирован как «oriented according to
        # OrientTo setting», то есть без пришпиленной системы отсчёта три
        # числа вектора не значат ничего определённого, и свидетель силы
        # опирается на этот факт.
        OpRefinementSpec(
            op="create_point_load",
            materializer=("Structure.PointLoad.Create",),
            witness_source="model",
            obligations=(
                ob("point load exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("Point of the built element == xyz (geometry)",
                   KIND_GEOMETRY, (".Point",), key="position"),
                ob("OrientTo of the built element == Project (semantic)",
                   KIND_SEMANTIC, (".OrientTo",), key="orientation"),
                ob("ForceVector of the built element == newtons requested "
                   "(semantic)",
                   KIND_SEMANTIC, (".ForceVector",), key="force_vector"),
                ob("MomentVector of the built element == newton-metres "
                   "requested (semantic)",
                   KIND_SEMANTIC, (".MomentVector",), key="moment_vector"),
                ob("load case of the built element == resolved load_case "
                   "(semantic)",
                   KIND_SEMANTIC, (".LoadCaseId",), key="load_case"),
                ob("load_type of the built element == resolved load_type "
                   "(semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="load_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_line_load",
            materializer=("Structure.LineLoad.Create",),
            witness_source="model",
            obligations=(
                ob("line load exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("StartPoint and EndPoint of the built element == p0_mm and "
                   "p1_mm (geometry)",
                   KIND_GEOMETRY, (".StartPoint",), key="endpoints"),
                ob("OrientTo of the built element == Project (semantic)",
                   KIND_SEMANTIC, (".OrientTo",), key="orientation"),
                ob("ForceVector1 of the built element == newtons per metre "
                   "requested (semantic)",
                   KIND_SEMANTIC, (".ForceVector1",), key="force_vector"),
                ob("IsUniform of the built element (semantic)",
                   KIND_SEMANTIC, (".IsUniform",), key="uniform"),
                ob("load case of the built element == resolved load_case "
                   "(semantic)",
                   KIND_SEMANTIC, (".LoadCaseId",), key="load_case"),
                ob("load_type of the built element == resolved load_type "
                   "(semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="load_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_area_load",
            materializer=("Structure.AreaLoad.Create",),
            witness_source="model",
            obligations=(
                ob("area load exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("GetLoops of the built element returns one loop whose "
                   "vertices are the outline at elev_mm, same count (geometry)",
                   KIND_GEOMETRY, ("GetLoops",), key="loop_vertices"),
                ob("OrientTo of the built element == Project (semantic)",
                   KIND_SEMANTIC, (".OrientTo",), key="orientation"),
                ob("ForceVector1 of the built element == newtons per square "
                   "metre requested (semantic)",
                   KIND_SEMANTIC, (".ForceVector1",), key="force_vector"),
                ob("load case of the built element == resolved load_case "
                   "(semantic)",
                   KIND_SEMANTIC, (".LoadCaseId",), key="load_case"),
                ob("load_type of the built element == resolved load_type "
                   "(semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="load_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_path_of_travel",
            materializer=("Analysis.PathOfTravel.Create",),
            witness_source="model",
            obligations=(
                ob("path of travel exists and its calculation status is "
                   "Success (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("PathStart and PathEnd of the built element == p0_mm and "
                   "p1_mm in plan, Z excluded (geometry)",
                   KIND_GEOMETRY, (".PathStart",), key="endpoints"),
                ob("the route read back is non-empty and no shorter than the "
                   "straight line between the requested points (geometry)",
                   KIND_GEOMETRY, ("GetCurves",), key="route"),
                ob("OwnerViewId of the built element == in_view (topology)",
                   KIND_TOPOLOGY, (".OwnerViewId",), key="owner_view"),
            ),
        ),
        OpRefinementSpec(
            op="create_pipe_placeholder",
            materializer=("Plumbing.Pipe.CreatePlaceholder",),
            witness_source="model",
            obligations=(
                ob("placeholder pipe exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 3D (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
                ob("IsPlaceholder of the built element (semantic)",
                   KIND_SEMANTIC, ("IsPlaceholder",), key="is_placeholder"),
                ob("pipe_type of the built element == resolved pipe_type "
                   "(semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="pipe_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_duct_placeholder",
            materializer=("Mechanical.Duct.CreatePlaceholder",),
            witness_source="model",
            obligations=(
                ob("placeholder duct exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 3D (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
                ob("IsPlaceholder of the built element (semantic)",
                   KIND_SEMANTIC, ("IsPlaceholder",), key="is_placeholder"),
                ob("duct_type of the built element == resolved duct_type "
                   "(semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="duct_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_flex_duct",
            materializer=("Mechanical.FlexDuct.Create",),
            witness_source="model",
            obligations=(
                ob("flex duct exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("Points read back == path, same count and same order "
                   "(geometry)",
                   KIND_GEOMETRY, (".Points",), key="path_points"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
                ob("flex_duct_type of the built element == resolved "
                   "flex_duct_type (semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="flex_duct_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_flex_pipe",
            materializer=("Plumbing.FlexPipe.Create",),
            witness_source="model",
            obligations=(
                ob("flex pipe exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("Points read back == path, same count and same order "
                   "(geometry)",
                   KIND_GEOMETRY, (".Points",), key="path_points"),
                ob("reference level == resolved level (topology)",
                   KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",),
                   key="reference_level"),
                ob("flex_pipe_type of the built element == resolved "
                   "flex_pipe_type (semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="flex_pipe_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_type",
            materializer=(".Duplicate(",),
            witness_source="model",
            obligations=(
                ob("new FamilySymbol exists (materialize or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("width param holds width_mm post-commit (parameter)",
                   KIND_PARAMETER, ("__pw_",), key="width"),
                ob("depth param holds depth_mm when given (parameter)",
                   KIND_PARAMETER, ("__pd_",),
                   param="depth_mm", conditional=True, key="depth"),
                ob("material holds when given (parameter)",
                   KIND_PARAMETER, ("STRUCTURAL_MATERIAL_PARAM",),
                   param="material", conditional=True, key="material"),
            ),
        ),
        OpRefinementSpec(
            op="load_family",
            materializer=("LoadFamily", "LoadFamilySymbol"),
            witness_source="model",
            obligations=(
                ob("File.Exists checked / typed refusal (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("symbol active post-load (semantic)",
                   KIND_SEMANTIC, (".IsActive",), key="active"),
            ),
        ),
        OpRefinementSpec(
            op="create_dimension",
            materializer=("NewDimension",),
            witness_source="model",
            # 28.07 said this op could carry no gated GEOMETRY obligation:
            # the measured VALUE depended on which face happened to resolve
            # first, and Dimension.Curve is documented ALWAYS UNBOUND (Revit
            # API Developer Guide, "Dimensions and Constraints"), so no
            # independent expectation existed. 09.08 REVERSES that half: the
            # resolver now knows which PLANE each reference names, so the
            # distance between those planes IS the independent expectation,
            # and the witness compares Revit's own Value/Segments against it.
            # The claim signed is deliberately narrow — the number matches
            # the geometry the dimension is bound to, NOT the operator's
            # intent (exterior vs interior face is unknowable here).
            # The retired "line_at reproduced (geometry)" obligation asserted
            # Dimension.Origin's offset along a FIXED View.UpDirection,
            # which stopped being meaningful once the dimension line's own
            # direction became face-normal-derived (not always
            # UpDirection-perpendicular) — see _emit_dimension docstring.
            obligations=(
                ob("dimension exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("belongs to in_view (topology)",
                   KIND_TOPOLOGY, (".OwnerViewId", ".View"), key="in_view"),
                ob("References match requested refs (topology)",
                   KIND_TOPOLOGY, (".References",), key="references"),
                ob("measured value equals the distance between the "
                   "referenced geometry (geometry)",
                   KIND_GEOMETRY, (".Value", ".Segments"), key="value"),
            ),
        ),
        OpRefinementSpec(
            op="create_angular_dimension",
            materializer=("AngularDimension.Create",),
            witness_source="model",
            # 09.08. The arc is DERIVED from the two references (vertex =
            # intersection of their planes, radius and ray choice from `at`),
            # so the sweep angle is known at creation time and the reported
            # Value has an independent expectation — gated in radians against
            # Application.AngleTolerance, read at runtime. What the offline
            # gate cannot settle is whether Revit reports the sweep of the arc
            # we passed or its supplement; the witness makes that LOUD on the
            # first live run instead of returning a plausible angle.
            obligations=(
                ob("angular dimension exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("belongs to in_view (topology)",
                   KIND_TOPOLOGY, (".OwnerViewId", ".View"), key="in_view"),
                ob("References match requested refs (topology)",
                   KIND_TOPOLOGY, (".References",), key="references"),
                ob("measured angle equals the sweep of the arc built from "
                   "those references (geometry)",
                   KIND_GEOMETRY, (".Value",), key="value"),
            ),
        ),
        OpRefinementSpec(
            op="create_tag",
            materializer=("IndependentTag.Create",),
            witness_source="model",
            obligations=(
                ob("tag exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("belongs to in_view (topology)",
                   KIND_TOPOLOGY, (".OwnerViewId", ".View"), key="in_view"),
                ob("TaggedLocalElementId == target (semantic)",
                   KIND_SEMANTIC,
                   ("TaggedLocalElementId", "GetTaggedLocalElementIds"),
                   key="target_bound"),
                ob("tag head at `at` reproduced in view-space (geometry)",
                   KIND_GEOMETRY, ("TagHeadPosition",), key="head_at"),
            ),
        ),
        # wave/detail (09.08). Свидетель СИЛЬНЕЕ, чем у остальной аннотации, и
        # это свойство самого элемента: у заливки есть ЧТО перечитать —
        # `GetBoundaries()` отдаёт кривые ПОСТРОЕННОЙ границы, а не эхо
        # аргумента. Поэтому геометрическое обязательство здесь не габаритное:
        # каждое авторское ребро обязано найтись ровно один раз по своим
        # концам И середине, а число петель и рёбер обязано совпасть.
        OpRefinementSpec(
            op="create_filled_region",
            materializer=("FilledRegion.Create",),
            witness_source="model",
            obligations=(
                ob("filled region exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("belongs to in_view (topology)",
                   KIND_TOPOLOGY, (".OwnerViewId", ".View"), key="in_view"),
                ob("GetTypeId == the resolved filled region type (semantic)",
                   KIND_SEMANTIC, (".GetTypeId",), key="region_type"),
                ob("GetBoundaries reproduces the authored loops in view space "
                   "— loop count, curve count and every edge matched by its "
                   "endpoints and mid-point (geometry)",
                   KIND_GEOMETRY, ("GetBoundaries",), key="boundary"),
            ),
        ),
        OpRefinementSpec(
            op="create_text",
            materializer=("TextNote.Create",),
            witness_source="model",
            obligations=(
                ob("text note exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("belongs to in_view (topology)",
                   KIND_TOPOLOGY, (".OwnerViewId", ".View"), key="in_view"),
                ob("content matches (semantic)",
                   KIND_SEMANTIC, (".Text",), key="content"),
                ob("at reproduced in view-space (geometry)",
                   KIND_GEOMETRY, (".Coord",), key="at"),
                ob("width_mm honored when given (geometry)",
                   KIND_GEOMETRY, (".Width",),
                   param="width_mm", conditional=True, key="width"),
                ob("leader target visible when given (semantic)",
                   KIND_SEMANTIC, ("__leaderTargetVisible", "__leaderOk"),
                   param="leader_to", conditional=True, key="leader"),
            ),
        ),
        OpRefinementSpec(
            op="create_beam",
            materializer=("NewFamilyInstance",),
            witness_source="model",
            obligations=(
                ob("beam exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 3D (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                # Было «reference level == resolved level». Замерено 27.07:
                # Revit ВЫВОДИТ опорный уровень балки из отметки кривой
                # (передан L_01 @ 0, кривая на Z=3000 -> привязка к
                # L_01ДОО1_+2.500). Обязательство требовало того, чего API не
                # обещает, и откатывало правильную балку. Инвариант, который
                # действительно есть: опорный уровень существует; какой именно
                # — читается в свидетель.
                ob("опорный уровень существует; какой — читается в свидетель (topology)",
                   KIND_TOPOLOGY, ("INSTANCE_REFERENCE_LEVEL_PARAM",),
                   key="reference_level"),
                ob("StructuralType == Beam (semantic)",
                   KIND_SEMANTIC, ("StructuralType.Beam",), key="structural_type"),
            ),
        ),
        OpRefinementSpec(
            op="create_foundation",
            # variety=isolated -> NewFamilyInstance; variety=slab -> Floor.Create
            # / NewFloor.  ANY of the three proves the op materialized on its
            # branch (only one path is emitted per op instance).
            materializer=("NewFamilyInstance", "Floor.Create", "NewFloor"),
            witness_source="model",
            obligations=(
                ob("footing/slab exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # isolated -> LocationPoint==xy; slab -> bbox extents.  ANY of
                # the two proves the geometry clause on the emitted branch.
                ob("isolated LocationPoint == xy OR slab bbox extents "
                   "== outline extents (geometry)",
                   KIND_GEOMETRY, _LOCATION_POINT + _BBOX, key="footprint"),
                ob("base level == resolved level (topology)",
                   KIND_TOPOLOGY, _LEVEL_BIP + _BBOX, key="level_binding"),
                ob("StructuralType==Footing (isolated) OR structural "
                   "flag forced (slab) (semantic)",
                   KIND_SEMANTIC,
                   ("StructuralType.Footing", "FLOOR_PARAM_IS_STRUCTURAL",
                    "get_BoundingBox"), key="structural_type"),
            ),
        ),
        # wave/wall-foundation (2026-08-09): ленточный фундамент. Оси версий
        # нет — WallFoundation.Create одинаков на всех шести (замер 09.08).
        OpRefinementSpec(
            op="create_wall_foundation",
            materializer=("WallFoundation.Create",),
            witness_source="model",
            obligations=(
                ob("wall foundation exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # ТОПОЛОГИЯ БЕЗ ДОПУСКА. Единственное настоящее обязательство
                # этой операции: элемент перечитывается из документа и сам
                # называет свою стену. Никакого числа здесь нет и быть не
                # может — это равенство id, а не измерение.
                ob("WallId == host wall id (topology, exact equality)",
                   KIND_TOPOLOGY, (".WallId",), key="host_wall"),
                ob("GetTypeId == requested wall foundation type (semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="element_type"),
            ),
        ),
        # wave/framing (2026-08-09): балочная система. Оси версий нет — все
        # четыре перегрузки BeamSystem.Create одинаковы на шести (замер 09.08).
        OpRefinementSpec(
            op="create_beam_system",
            materializer=("BeamSystem.Create",),
            witness_source="model",
            obligations=(
                ob("beam system exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # Габарит по ВЕРШИНАМ с обеих сторон: C# видит у прочитанного
                # профиля только концы кривых. Что остаётся вне — названо в
                # `post` и разобрано в шапке эмиттера.
                ob("re-read Profile vertex bbox == lowered-edge vertex bbox "
                   "(geometry)", KIND_GEOMETRY, (".Profile",),
                   key="profile_bbox"),
                ob("GetBeamIds is non-empty — Revit actually laid framing "
                   "(semantic)", KIND_SEMANTIC, ("GetBeamIds",),
                   key="beams_laid"),
                ob("BeamSystem.Level == resolved level (topology)",
                   KIND_TOPOLOGY, (".Level",), key="level_binding"),
                ob("BeamType == resolved symbol (semantic)",
                   KIND_SEMANTIC, (".BeamType",), key="beam_type"),
            ),
        ),
        # wave/reinforcement (2026-08-10): армирование по области. Оси версий
        # нет — обе перегрузки AreaReinforcement.Create одинаковы на всех
        # шести (замер 10.08 на :52412). Ни одного допуска: все обязательства
        # этой операции — равенства id и счётчик.
        OpRefinementSpec(
            op="create_area_reinforcement",
            materializer=("AreaReinforcement.Create",),
            witness_source="model",
            obligations=(
                ob("area reinforcement exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # ТОПОЛОГИЯ БЕЗ ДОПУСКА: элемент перечитывается из документа и
                # сам называет свой носитель. Числа здесь нет и быть не может.
                ob("GetHostId == requested host id (topology, exact equality)",
                   KIND_TOPOLOGY, ("GetHostId",), key="host"),
                ob("GetTypeId == requested area reinforcement type (semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="element_type"),
                # УСЛОВНОЕ обязательство: Autodesk документирует пустой массив
                # как ПРАВИЛЬНЫЙ ответ при выключенной HostStructuralRebar,
                # поэтому безусловное «непусто» отвергало бы исправную работу.
                ob("GetRebarInSystemIds is non-empty under "
                   "HostStructuralRebar (semantic)",
                   KIND_SEMANTIC,
                   ("GetRebarInSystemIds", "HostStructuralRebar"),
                   key="bars_laid"),
                ob("the bars' own GetTypeId == requested bar type (semantic)",
                   KIND_SEMANTIC, ("RebarInSystem", "GetTypeId"),
                   key="bar_type"),
            ),
        ),
        # wave/framing (2026-08-09): ферма. Одна подпись на шесть версий.
        OpRefinementSpec(
            op="create_truss",
            materializer=("Truss.Create",),
            witness_source="model",
            obligations=(
                ob("truss exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("LocationCurve endpoints == p0/p1 in plan (geometry)",
                   KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
                ob("both endpoint elevations == the level's own plane "
                   "(geometry)", KIND_GEOMETRY, _ENDPOINTS,
                   key="base_elevation"),
                ob("GetTypeId == requested truss type (semantic)",
                   KIND_SEMANTIC, ("GetTypeId",), key="element_type"),
                ob("Members is non-empty — Revit derived chords and webs "
                   "(semantic)", KIND_SEMANTIC, (".Members",),
                   key="members_derived"),
                # СУЩЕСТВОВАНИЕ, А НЕ РАВЕНСТВО — тот же урок, что у
                # create_beam (замер 27.07: требование равенства откатывало
                # верно построенные балки).
                ob("reference level link is REAL (topology)",
                   KIND_TOPOLOGY, ("TRUSS_ELEMENT_REFERENCE_LEVEL_PARAM",),
                   key="reference_level"),
            ),
        ),
        OpRefinementSpec(
            op="create_stairs",
            # ДВЕ формы марша — ДВА материализатора, и ЛЮБОГО из них хватает
            # (materializer: «ANY marker proves the create call»). Форма
            # выбирается параметром `spiral`, и ровно один из двух вызовов
            # существует в эмиссии одной программы.
            materializer=("CreateStraightRun", "CreateSpiralRun"),
            obligations=(
                ob("stairs exist (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("base/top level == resolved levels (topology)",
                   KIND_TOPOLOGY,
                   ("STAIRS_BASE_LEVEL_PARAM", "STAIRS_TOP_LEVEL_PARAM")),
                ob(">=1 run materialized (semantic)",
                   KIND_SEMANTIC, ("GetStairsRuns",)),
                ob("width_mm held when supplied (geometry)",
                   KIND_GEOMETRY, ("ActualRunWidth",),
                   param="width_mm", conditional=True),
                # Свидетель ЧИТАЕТ РЕЗУЛЬТАТ: путь созданного марша
                # перечитывается `GetStairsPath` и обязан содержать дугу. Он
                # НЕ проверяет центр/радиус/размах — см. клаузулу post и её
                # объяснение в emit_stairs_program; тому отношению не хватает
                # ЗАМЕРА, а не проверки.
                ob("spiral run path contains an Arc (geometry)",
                   KIND_GEOMETRY, ("GetStairsPath",),
                   param="spiral", conditional=True, key="spiral_path"),
            ),
        ),
        OpRefinementSpec(
            # ВОЛНА ЛЕСТНИЦ (10.08.2026). Второй оп со СВОИМ шаблоном целой
            # программы; текст разбирается КУСКАМИ той же дорогой, что и
            # марш (`vacuity_partial`), потому что по скобкам он намеренно
            # не сбалансирован — рамку даёт `wrap_user_code`.
            op="create_stairs_landing",
            materializer=("CreateSketchedLanding",),
            obligations=(
                ob("landing exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("GetStairs() == the requested stairs (topology)",
                   KIND_TOPOLOGY, (".GetStairs()",), key="owner_stairs"),
                ob("the landing appears in GetStairsLandings (topology)",
                   KIND_TOPOLOGY, ("GetStairsLandings",), key="in_landing_set"),
                ob("IsAutomaticLanding is false — the sketched factory was "
                   "asked for (semantic)",
                   KIND_SEMANTIC, ("IsAutomaticLanding",), key="sketched"),
                # Свидетель читает РЕЗУЛЬТАТ: границу ПОСТРОЕННОЙ площадки,
                # ребро за ребром, против авторского контура, вывезенного в
                # C# отдельными массивами.
                ob("GetFootprintBoundary reproduces the authored contour in "
                   "plan — curve count and every edge matched once by "
                   "endpoints and mid-point (geometry)",
                   KIND_GEOMETRY, ("GetFootprintBoundary",), key="boundary"),
                ob("fresh post-scope BaseElevation equals the normalized "
                   "integer riser multiple within the derived geometry "
                   "tolerance (geometry)",
                   KIND_GEOMETRY, ("BaseElevation",), key="elevation"),
            ),
        ),
        OpRefinementSpec(
            # ВОЛНА ЛЕСТНИЦ, ВТОРОЙ МАРШ (15.08.2026). Третий оп со СВОИМ
            # шаблоном целой программы; текст разбирается КУСКАМИ той же
            # дорогой, что марш и площадка (`vacuity_partial`), потому что по
            # скобкам он намеренно не сбалансирован — рамку даёт
            # `wrap_user_code`.
            op="create_stairs_run",
            materializer=("CreateStraightRun",),
            obligations=(
                ob("run exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("GetStairs() == the requested stairs (topology)",
                   KIND_TOPOLOGY, (".GetStairs()",), key="owner_stairs"),
                ob("the run appears in Stairs.GetStairsRuns (topology)",
                   KIND_TOPOLOGY, ("GetStairsRuns",), key="in_run_set"),
                # Свидетель читает РЕЗУЛЬТАТ: путь ПОСТРОЕННОГО марша против
                # авторской оси, по обоим направлениям обхода.
                ob("GetStairsPath reproduces the authored axis endpoints in "
                   "plan within the derived tolerance (geometry)",
                   KIND_GEOMETRY, ("GetStairsPath",), key="path"),
                ob("fresh post-scope BaseElevation equals the stairs base "
                   "plus the normalized integer riser multiple within the "
                   "derived geometry tolerance (geometry)",
                   KIND_GEOMETRY, ("BaseElevation",), key="elevation"),
            ),
        ),
        OpRefinementSpec(
            # feat/native-groups: NewGroup builds the definition (guarded by
            # __Refuse on null); .Groups witnesses the placed instance count;
            # .Name witnesses the requested GroupType name.  Witnesses are
            # structural C# (NewGroup / .Groups / .Name), never message text.
            op="create_group",
            materializer=("NewGroup",),
            witness_source="model",
            obligations=(
                ob("group definition materialized (GroupType) or typed refusal",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("one placed group instance per placement offset "
                   "(PlaceGroup) (semantic)",
                   KIND_SEMANTIC, (".Groups",), key="instances"),
                ob("GroupType Name matches name when given (semantic)",
                   KIND_SEMANTIC, (".Name",),
                   param="name", conditional=True, key="name"),
            ),
        ),
        OpRefinementSpec(
            # Витражная ячейка. Материализатор — ЕДИНСТВЕННЫЙ вызов, которым
            # Revit меняет тип ячейки; «панель создана» здесь не бывает:
            # панель существует ровно потому, что существует ячейка.
            #
            # Свидетель типа читает ячейку ЗАНОВО ПО АДРЕСУ после
            # Regenerate: ChangePanelType возвращает элемент, и сверка с ним
            # доказывала бы лишь то, что вызов состоялся, — ровно тот класс
            # «свидетеля вызова», который этот реестр запрещает.
            # Линия разрезки — ЕДИНСТВЕННЫЙ конструктор: AddGridLine.
            # Свидетель читает СОЗДАННУЮ линию заново по её id после
            # Regenerate: членство в списке линий этой сетки (topology),
            # IsUGridLine (semantic) и расстояние от запрошенной точки до
            # FullCurve (geometry). Возврат вызова свидетельством не
            # считается — он доказывает лишь то, что вызов состоялся.
            op="create_curtain_grid_line",
            materializer=("AddGridLine",),
            witness_source="model",
            obligations=(
                ob("grid line created or typed refusal (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("created line is a member of the host grid's U/V line "
                   "ids (topology)",
                   KIND_TOPOLOGY, ("__gMem",), key="grid_membership"),
                ob("IsUGridLine == requested direction (semantic)",
                   KIND_SEMANTIC, (".IsUGridLine",), key="direction"),
                ob("requested position lies on FullCurve within tolerance "
                   "(geometry)",
                   KIND_GEOMETRY, ("__gDist",), key="position_mm"),
            ),
        ),
        OpRefinementSpec(
            op="set_curtain_panel",
            materializer=("ChangePanelType",),
            witness_source="model",
            obligations=(
                ob("cell (u,v) resolved or typed refusal (materialize)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                ob("effective panel type in cell (u,v) == panel_type, "
                   "re-read by address (semantic)",
                   KIND_SEMANTIC, ("__ccEffType",), key="panel_type"),
                ob("cell host == host (topology)",
                   KIND_TOPOLOGY, (".Host",), key="cell_host"),
            ),
        ),
        # ── волна датумов (09.08.2026) ───────────────────────────────────
        OpRefinementSpec(
            op="create_multi_segment_grid",
            materializer=("MultiSegmentGrid.Create",),
            witness_source="model",
            obligations=(
                ob("chain exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # ДВА РАЗНЫХ ОБЯЗАТЕЛЬСТВА, А НЕ ОДНО. Число осей и их
                # координаты падают по-разному: цепь может собраться из
                # правильного числа звеньев не там, где просили, и наоборот —
                # совпасть частью концов при потерянном звене. Одно
                # обязательство на оба факта пропустило бы ровно ту половину,
                # которая сломалась.
                ob("one Grid per path segment: GetGridIds count == segments "
                   "(geometry)",
                   KIND_GEOMETRY, ("GetGridIds",), key="segment_count"),
                ob("every authored segment matched by a created Grid's own "
                   "Curve endpoints, each Grid used once (geometry)",
                   KIND_GEOMETRY, ("GetEndPoint",), key="endpoints"),
            ),
        ),
        OpRefinementSpec(
            op="create_extrusion_roof",
            materializer=("NewExtrusionRoof",),
            witness_source="model",
            obligations=(
                ob("extrusion roof exists (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # Перечитывание ИЗ ДОКУМЕНТА, а не доверие статическому типу
                # возврата: `NewExtrusionRoof` объявлен как ExtrusionRoof, и
                # обязательство, стоящее на этом, доказывало бы сигнатуру
                # C#, а не постройку.
                ob("re-read from the document casts to ExtrusionRoof "
                   "(semantic)",
                   KIND_SEMANTIC, ("as ExtrusionRoof",), key="element_class"),
                ob("ROOF_BASE_LEVEL_PARAM == resolved level (topology)",
                   KIND_TOPOLOGY, ("ROOF_BASE_LEVEL_PARAM",),
                   key="base_level"),
                # Габарит меряется ПО НОРМАЛИ рабочей плоскости, а не по
                # осям мира: нормаль горизонтальна, но произвольна, и
                # осевой bbox смешал бы ход выдавливания с размахом профиля.
                ob("solid extent along the work plane normal spans "
                   "[start_mm, end_mm] from the plane (geometry)",
                   KIND_GEOMETRY, ("DotProduct",), key="extrusion_extent"),
            ),
        ),
        OpRefinementSpec(
            op="create_multistory_stairs",
            materializer=("MultistoryStairs.Create",),
            witness_source="model",
            obligations=(
                ob("multistory stairs exist (materialized or typed refusal)",
                   KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
                # ОДНО обязательство на весь оп, и это не бедность: у опа
                # РОВНО ОДИН наблюдаемый результат — множество уровней, — и
                # оно проверяется ТОЧНЫМ равенством, без допуска. Дробить его
                # на «создалось» и «подключилось» значило бы завести
                # обязательство, которое не может упасть отдельно.
                ob("GetAllConnectedLevels re-read equals the resolved levels "
                   "set exactly (topology)",
                   KIND_TOPOLOGY, ("GetAllConnectedLevels",),
                   key="connected_levels"),
            ),
        ),
    ]
    return {spec_.op: spec_ for spec_ in specs}


def _hosted_obligations(noun: str) -> tuple[Obligation, ...]:
    ob = Obligation
    return (
        ob(f"{noun} exists (materialized or typed refusal)",
           KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
        ob("Host.Id == host wall id (topology)",
           KIND_TOPOLOGY, (".Host",), key="host"),
        ob("LocationPoint == offset placement at level+sill (geometry)",
           KIND_GEOMETRY, _LOCATION_POINT, key="location"),
        # audit F5: swing/mirror state — same conditional markers as
        # place_family; every emitted check carries its own __post.Add in the
        # marker span (verdict-span rule).
        ob("mirrored state == requested when given (semantic)",
           KIND_SEMANTIC, (".Mirrored != ",),
           param="mirrored", conditional=True, key="mirrored"),
        ob("hand flip state == requested when given (semantic)",
           KIND_SEMANTIC, (".HandFlipped != ",),
           param="hand_flipped", conditional=True, key="hand_flipped"),
        ob("facing flip state == requested when given (semantic)",
           KIND_SEMANTIC, (".FacingFlipped != ",),
           param="facing_flipped", conditional=True, key="facing_flipped"),
    )


def _network_obligations(diameter_bip: str,
                         with_slope: bool = False,
                         with_level: bool = False) -> tuple[Obligation, ...]:
    ob = Obligation
    # ДЫРА, ЗАКРЫТАЯ 09.08.  `level` у сетевых опов ОБЯЗАТЕЛЕН и уезжает
    # четвёртым аргументом прямо в `Pipe.Create`/`Duct.Create` — то есть это
    # авторская степень свободы, которую держим МЫ.  При этом
    # `acceptance._LEVEL_FROM_PARAM` уже числил все три сетевых опа среди
    # тех, у кого «уровень результата равен разрешённому селектору», и строил
    # на этом послекоммитную перепись: судья опирался на утверждение, которое
    # ни один свидетель не читал.  Одиночные `create_pipe`/`create_duct`
    # читают ТОТ ЖЕ `RBS_START_LEVEL_PARAM` с 21.07 — 3434 и 215 живых
    # построек, ноль обвинений и ноль нарушений «level binding» (все 35 в
    # корпусе принадлежат опам, где уровень Revit ВЫВОДИТ: create_beam 29,
    # create_floor 5).
    level = (
        ob("each segment's reference level == the resolved level (topology)",
           KIND_TOPOLOGY, ("RBS_START_LEVEL_PARAM",), key="reference_level"),
    ) if with_level else ()
    slope = (
        # ДРЕЙФ, ЗАКРЫТЫЙ 03.08.  `route_*.post` обещает KIR-X004 («сегмент с
        # slope_min_pct держит уклон или программа откатывается»), эмиттер
        # ставит НАСТОЯЩЕГО свидетеля (route_mep.emit_slope_witness_cs), а
        # обязательства в таблице не было вовсе: удаление свидетеля
        # оставляло сертификат ДОКАЗАННЫМ.  audit_registry_coverage() это
        # пропускал, потому что сверяет прозу по ОБЩИМ СЛОВАМ — слово
        # «segment» есть и у диаметра, и у связности.  Ловится только
        # мутацией (вырезать свидетеля -> `proven` обязан упасть), и именно
        # так это теперь и проверяется — tests/test_tolerance_provenance.py.
        ob("a segment carrying slope_min_pct holds it or the program rolls "
           "back (geometry, KIR-X004)",
           KIND_GEOMETRY, ("__slc",), param="__slope_reqs__",
           conditional=True, param_truthy=True, key="slope"),
    ) if with_slope else ()
    return (
        ob("segments materialized or typed refusal (materialize)",
           KIND_MATERIALIZE, _REFUSE, block=BLOCK_CREATE),
        ob("each segment LocationCurve == node coords (geometry)",
           KIND_GEOMETRY, _ENDPOINTS, key="endpoints"),
        # Was "all segments in one MEPSystem (semantic)" until 2026-07-27.
        # Revit DERIVES system membership from the connector graph at commit
        # (measured — connect.py §A), so no in-transaction check can discharge
        # it; the emitter used to force membership with NewPipingSystem and
        # that call is what made the four graph ops unbuildable. The clause
        # the emitter really can prove before commit is connectivity — the
        # CONNECT signal the spec itself names — and it is proven by a BFS
        # over the live connector graph (`Connector.AllRefs`). System identity
        # is now READ BACK after commit and reported, never asserted here.
        ob("connector-graph BFS reaches every segment (topology)",
           KIND_TOPOLOGY, (".AllRefs",), key="connectivity"),
        # Диаметр сегмента: эмиттер эту проверку СТАВИТ
        # (`_network_geometry_post`: «segment N diameter (semantic)»), а
        # сертификат о ней не знал — аргумент `diameter_bip` принимался и
        # не использовался ни разу. Значит удаление проверки из эмиттера
        # оставляло сертификат «доказанным»: ровно та дыра, ради закрытия
        # которой сертификат и заведён.
        #
        # Маркером служит сам BuiltInParameter — он же и различает домены
        # (у трубы RBS_PIPE_DIAMETER_PARAM, у воздуховода
        # RBS_CURVE_DIAMETER_PARAM), поэтому подмена одного другим тоже
        # перестаёт быть незаметной.
        ob("each declared segment diameter is read back (semantic)",
           KIND_SEMANTIC, (f"BuiltInParameter.{diameter_bip}",),
           key="diameter"),
    ) + level + slope


# Some obligation constructors are referenced before their def at class-body
# eval time; Python resolves them at call time, so define the table lazily.
REFINEMENT: dict[str, OpRefinementSpec] = {}


def _ensure_table() -> dict[str, OpRefinementSpec]:
    global REFINEMENT
    if not REFINEMENT:
        REFINEMENT = _refinement_specs()
    return REFINEMENT


# ---------------------------------------------------------------------------
# Certification
# ---------------------------------------------------------------------------


def _op_present(op: dict, param: str, truthy: bool = False) -> bool:
    """Whether a gating param is genuinely present on this op instance.

    Presence is by key AND (for booleans) any value: place_family always
    carries mirrored/hand/facing keys only when the IR set them, and the
    emitter keys its witness on ``has_<flag> = "<flag>" in op`` — so key
    presence is the correct, emitter-aligned test.
    """

    if param not in op or op[param] is None:
        return False
    # `truthy` distinguishes «ключ есть» от «запрошено» для контейнеров —
    # см. Obligation.param_truthy.
    return bool(op[param]) if truthy else True


def _not_required_because(obligation: Obligation) -> str:
    """Human-readable reason a NOT-required obligation's gate resolved that
    way — either the ordinary ``conditional``/``param`` shape (required only
    when ``param`` IS present) or the inverse ``unless_param`` shape
    (required only when ``unless_param`` is ABSENT)."""

    if obligation.unless_param is not None:
        return f"for present param {obligation.unless_param!r}"
    return f"for absent param {obligation.param!r}"


def certify_op(
    op: dict, version: str, *, stamp: str = "kir:cert",
) -> OpCertificate:
    """Statically certify one grounded op's emission refines its OpSpec.post."""

    table = _ensure_table()
    op_name = op["op"]
    if op_name not in table:
        raise CertificateSchemaError(
            f"{op_name}: no OpRefinementSpec (registry op not certifiable)")
    ref = table[op_name]

    model_checks: "list | None" = None
    if op_name in spec.SOLO_OPS:
        # Sole-op program with its own template (not in _EMITTERS).  Parse the
        # whole emitted program as one blob for materializer + post witnesses;
        # its postconditions are the same __post.Add pattern.  Шаблон берётся
        # из ТАБЛИЦЫ, а не по имени: с 10.08.2026 таких опов два, и `if
        # op_name == "create_stairs"` тихо отправил бы площадку в общую ветку
        # `_EMITTERS`, где её нет вовсе.
        from kukai.ir.authoring import _SOLO_PROGRAMS
        program = _SOLO_PROGRAMS[op_name](op, version)
        create_code = post_code = _code(program)
    else:
        decl, create, post, _readback = _EMITTERS[op_name](op, version, stamp)
        create_code = _code(create)
        if isinstance(post, BarePost):
            post = list(post.checks)
        if isinstance(post, (list, tuple)):
            # Wave A2 model post: the emitter handed over WitnessCheck objects.
            if ref.witness_source != "model":
                raise CertificateSchemaError(
                    f"{op_name}: emitter returns a model post but the "
                    "refinement spec still declares witness_source='string' "
                    "— update REFINEMENT in the same migration step")
            model_checks = list(post)
            post_code = _code(post_to_string(op["id"], post))
        else:
            if ref.witness_source == "model":
                raise CertificateSchemaError(
                    f"{op_name}: refinement spec declares witness_source="
                    "'model' but the emitter returned a string post")
            post_code = _code(post)

    materialized = any(m in create_code for m in ref.materializer)
    refusal_guarded = (
        not ref.refuse_on_null
        or any(m in create_code for m in _REFUSE)
    )

    model_keys = (
        {check.obligation_key for check in model_checks}
        if model_checks is not None else None)

    # ВАКУУМ (09.08): ключ доказывает, что СТРОКА `__post.Add` существует, а не
    # что она достижима.  Мутация `if (false) __post.Add("never")` оставляла
    # сертификат доказанным — см. большой комментарий у analyze_witness_cs,
    # включая честный список того, чего этот анализ НЕ видит.
    vacuous, partial = witness_vacuity(op_name, model_checks, post_code)
    dead_keys = {f.obligation_key for f in vacuous
                 if f.obligation_key is not None}

    verdicts: list[ClauseVerdict] = []
    for obligation in ref.obligations:
        if obligation.kind == KIND_MATERIALIZE:
            # Materialize obligations are proven by the create-side refuse
            # guard; recorded as a clause so the ledger is complete.
            verdicts.append(ClauseVerdict(
                clause=obligation.clause,
                kind=obligation.kind,
                required=True,
                discharged=refusal_guarded and materialized,
                matched_marker=(ref.materializer[0] if materialized else None),
                reason=("materializer + __Refuse present"
                        if (materialized and refusal_guarded)
                        else "missing materializer or __Refuse"),
            ))
            continue

        required = True
        if obligation.conditional:
            required = _op_present(
                op, obligation.param, obligation.param_truthy)
        # Не `elif`: два затвора могут стоять на одном обязательстве, и тогда
        # свидетель требуется, только когда выполнены ОБА (см. `unless_param`).
        if obligation.unless_param is not None:
            required = required and not _op_present(
                op, obligation.unless_param)

        if model_keys is not None and obligation.block == BLOCK_POST:
            # Model path (A2): discharge by KEY.  A WitnessCheck cannot exist
            # without its __post.Add (unconstructible), so key-presence IS
            # verdict-presence — no span heuristics.
            if obligation.key is None:
                raise CertificateSchemaError(
                    f"{op_name}: obligation {obligation.clause!r} has no "
                    "model key but the op is model-certified")
            present = obligation.key in model_keys
            dead = obligation.key in dead_keys
            if required:
                if present and dead:
                    reason = (f"witness check {obligation.key!r} present but "
                              "VACUOUS — its __post.Add cannot execute")
                elif present:
                    reason = f"witness check {obligation.key!r} present"
                else:
                    reason = f"no witness check with key {obligation.key!r}"
                verdicts.append(ClauseVerdict(
                    clause=obligation.clause, kind=obligation.kind,
                    required=True, discharged=present and not dead,
                    matched_marker=obligation.key if present else None,
                    reason=reason))
            else:
                verdicts.append(ClauseVerdict(
                    clause=obligation.clause, kind=obligation.kind,
                    required=False, discharged=not present,
                    matched_marker=obligation.key if present else None,
                    reason=("absent param -> witness correctly absent"
                            if not present else
                            f"spurious witness {obligation.key!r} "
                            f"{_not_required_because(obligation)}")))
            continue

        block_code = create_code if obligation.block == BLOCK_CREATE else post_code
        matched = next(
            (m for m in obligation.witness_markers if m in block_code), None)
        if not required:
            # Conditional clause whose param is absent: the witness must ALSO
            # be absent (no spurious check for a param that was not requested).
            discharged = matched is None
            reason = ("absent param -> witness correctly absent"
                      if discharged
                      else f"spurious witness {matched!r} "
                           f"{_not_required_because(obligation)}")
            verdicts.append(ClauseVerdict(
                clause=obligation.clause, kind=obligation.kind,
                required=False, discharged=discharged,
                matched_marker=matched, reason=reason))
            continue
        verdicts.append(ClauseVerdict(
            clause=obligation.clause,
            kind=obligation.kind,
            required=True,
            discharged=matched is not None,
            matched_marker=matched,
            reason=(f"witness {matched!r} present" if matched
                    else f"no witness among {obligation.witness_markers}"),
        ))

    # Wave A2: the verdict-span rule is GONE.  Every _EMITTERS op is
    # model-certified (a WitnessCheck cannot exist without its __post.Add —
    # the F3 class is unconstructible), and create_stairs, the sole string
    # blob, was always span-exempt.  Obligations discharge by KEY.

    return OpCertificate(
        op=op_name,
        version=version,
        materialized=materialized,
        refusal_guarded=refusal_guarded,
        clauses=tuple(verdicts),
        vacuous=vacuous,
        vacuity_partial=partial,
    )


def certify_program(
    grounded_ops: list[dict], version: str, *, intent: str = "",
) -> ProgramCertificate:
    """Certify every op of a grounded program (per-op; the program wrapper is
    constant, so the certificate composes from per-op certificates)."""

    return ProgramCertificate(
        version=version,
        ops=tuple(certify_op(op, version) for op in grounded_ops),
    )


def assert_refined(certificate: OpCertificate | ProgramCertificate) -> None:
    """Fail-closed: raise with every gap unless the certificate is proven.

    A vacuous witness raises the MORE SPECIFIC :class:`VacuousWitnessError`
    (a subclass, so existing catch sites keep working): "the check is missing"
    and "the check exists and cannot fire" are different defects and must not
    arrive under one name.
    """

    if certificate.proven:
        return
    error = (VacuousWitnessError if certificate.vacuous
             else UnprovenRefinementError)
    raise error(
        "translation certificate not proven:\n  "
        + "\n  ".join(certificate.gaps))


# ---------------------------------------------------------------------------
# Registry-coverage audit (table <-> spec.OPS biection)
# ---------------------------------------------------------------------------

# Ops handled outside the _EMITTERS table but still certifiable — the ops that
# own their transaction scope and therefore carry a WHOLE-PROGRAM template
# (`authoring._SOLO_PROGRAMS`).  Кортеж строится ИЗ РЕЕСТРА, а не переписывается
# литералом: второй такой оп (площадка, 10.08.2026) показал, что переписанное
# имя — это второе мнение об одном факте, и разъезжается оно молча.
_EXTRA_CERTIFIABLE = frozenset(spec.SOLO_OPS)

# Some OpSpec.post clauses describe PLAN-stage / policy / emit-ordering /
# resolution behavior, NOT a post-commit runtime witness — so they cannot (and
# must not) be forced to map onto a __post.Add obligation.  Exemptions are
# EXPLICIT and carry a rationale: a clause is skipped by audit_registry_coverage
# only if it contains its op's exemption marker.  This keeps the biection honest
# (a genuinely-witnessable clause with no obligation still hard-fails) while not
# fabricating a fake witness for a non-runtime promise.  Format: op -> tuple of
# (distinguishing-substring, why-not-a-runtime-postcondition).
_NON_WITNESSABLE_CLAUSES: dict[str, tuple[tuple[str, str], ...]] = {
    "delete": (
        ("allow_destructive",
         "plan/envelope policy gate (SPEC 12.2), enforced before emission"),
    ),
    "create_room": (
        ("placed after",
         "emitter EMIT-ORDER rule (doc.Regenerate before rooms), not a "
         "post-commit witness"),
    ),
    "create_stairs": (
        ("sole op",
         "PLAN constraint (KIR-L002); emit_program raises before emission"),
    ),
    # ВОЛНА ЛЕСТНИЦ (10.08.2026). ТРИ освобождения, и каждое названо ровно
    # затем, чтобы не-свидетельствуемое обещание не растворилось в соседней
    # клаузуле по случайному общему слову.
    # ВТОРОЙ МАРШ (15.08.2026). ДВА освобождения, обе — не-свидетельствуемые
    # обещания, названные поимённо, чтобы не растворились в соседней клаузуле
    # по случайному общему слову.
    "create_stairs_run": (
        ("sole op",
         "PLAN constraint (KIR-L002); emit_program raises before emission"),
        # НАЗВАННОЕ ОТСУТСТВИЕ ОСИ — тот же довод, что у площадки: Z пути
        # марша назначает Revit от базы лестницы. Подписать ось, которую не
        # задавали, — ровно дефект, ради запрета которого заведён
        # test_witness_axis_honesty.
        ("z is not compared",
         "Revit derives the run path Z from the stairs base itself, so that Z "
         "is Revit's number and not the op's; witnessing it would sign an "
         "axis nobody authored"),
        # ПРЕДУСЛОВИЕ, А НЕ ПОСТУСЛОВИЕ: кратность подступенку проверяется ДО
        # эффекта и отказывает, поэтому обязательства свидетеля у неё нет.
        ("base_elevation_mm must already be an integer multiple",
         "checked BEFORE any effect and refused with the adjacent multiples "
         "named; a precondition has no post-effect witness to discharge"),
    ),
    "create_stairs_landing": (
        ("sole op",
         "PLAN constraint (KIR-L002); emit_program raises before emission"),
        # НАЗВАННОЕ ОТСУТСТВИЕ ОСИ. Клаузула говорит, чего свидетель НЕ
        # подписывает: Z прочитанной границы ставит сам Revit («projected on
        # the stairs base level»), а не мы. Подписать ось, которую не
        # задавали, — ровно тот дефект, ради запрета которого заведён
        # test_witness_axis_honesty.
        ("the z of those curves is not compared",
         "Revit itself projects the boundary onto the stairs base level, so "
         "that Z is Revit's number and not the op's; witnessing it would sign "
         "an axis nobody authored"),
        # ПРЕДУСЛОВИЕ, А НЕ ПОСТУСЛОВИЕ. Точная нижняя граница отметки
        # (половина высоты подступенка) известна только по живой лестнице,
        # поэтому проверяется ДО вызова и является типизированным ОТКАЗОМ.
        # Обязательства у неё нет и быть не может: после отказа коммита не
        # происходит вовсе, свидетельствовать нечего.
        ("typed refusal naming the measured number",
         "a PRE-condition read off the live stairs (ActualRiserHeight) and "
         "refused before the create call — after a refusal nothing commits, "
         "so there is no post-commit state to witness"),
    ),
    # wave/sweep (2026-08-09). ЕДИНСТВЕННОЕ ОСВОБОЖДЕНИЕ ЭТОЙ ВОЛНЫ, и оно
    # заведено ИМЕННО ЗАТЕМ, чтобы названная более слабая гарантия не
    # проскочила сверку на случайном общем слове. Клаузула цитирует Autodesk
    # дословно («The values set in the WallSweepInfo are ignored») и говорит,
    # чего операция НЕ утверждает; обязательства у неё нет и быть не может —
    # положение профиля задаёт тип, а не вызов, и поля для него у операции
    # нет вовсе. Это НЕ дыра в сверке: сверка осталась строгой, а
    # неутверждаемое названо вслух вместо того, чтобы молча раствориться в
    # соседней клаузуле.
    "create_wall_sweep": (
        ("named weaker guarantee",
         "a documented API fact (RevitAPI.xml, all six versions: the wall "
         "sweep's profile and position come from the type, and the "
         "WallSweepInfo values are ignored), so the op exposes no distance "
         "or offset field and there is nothing to witness — stating the "
         "limit is the honest alternative to inventing a witness"),
    ),
    # wave/mass (2026-08-10). ЕДИНСТВЕННОЕ ОСВОБОЖДЕНИЕ ЭТОЙ ВОЛНЫ, и оно
    # заведено ровно затем, чтобы НАЗВАННОЕ ОТСУТСТВИЕ свидетеля не
    # проскочило сверку на случайном общем слове. Клаузула говорит, чего
    # операция НЕ утверждает: равенства площади построенной стены площади
    # названной грани. Обязательства у неё нет и быть не может — накрывает ли
    # Revit грань целиком, не сказано ни в одной из шести RevitAPI.xml, а
    # утверждать это на догадке значило бы завести проверку, отвергающую
    # исправную работу. Сырая пара едет в квитанцию, и первый живой прогон
    # ИЗМЕРИТ величину вместо того, чтобы её оценивать.
    "create_face_wall": (
        ("named absence",
         "whether Revit spans the whole named face is documented nowhere in "
         "any of the six RevitAPI.xml, so no witness can be honest here; the "
         "receipt carries the raw pair and the first live run measures the "
         "remainder instead of a reasoned tolerance standing in for it"),
    ),
    "load_family": (
        ("already loaded",
         "idempotent-resolution semantics proven by the create-side collector "
         "search, not a post-commit witness"),
        ("another family",
         "resolution correctness (family+type match) enforced in the create "
         "block's collector filter, not a post-commit witness"),
    ),
    # Клаузула, которая ЧЕСТНО НАЗЫВАЕТ ОТСУТСТВИЕ свидетеля, а не обещает
    # его. Обязательства у неё нет и не должно быть: свес подошвы за стену и
    # отметка её низа НЕ ЗАМЕРЕНЫ (во всех сохранённых разборах на диске ноль
    # экземпляров WallFoundation, grep 09.08), а допуск, выведенный
    # рассуждением, — именно тот класс дефекта, который этот компилятор ловит
    # (create_door.sill_mm min_val=0; docspace._SHEET_LIMIT_MM). Снимает
    # исключение ОДИН живой прогон с замером, а не переформулировка.
    "create_wall_foundation": (
        ("not witnessed on purpose",
         "the footing's projection beyond its wall and its underside "
         "elevation have never been measured — no honest expected value "
         "exists to gate on, and an invented tolerance would be the defect "
         "class this compiler exists to kill (09.08)"),
    ),
    # Клаузула «выведено Revit — намеренно не в воротах» (09.08). Она НАЗЫВАЕТ
    # границу, а не обещает проверку, и обязательства у неё быть не должно ни
    # у одного из двух опов:
    #   * фитинги — их СОЗДАЁТ САМ ЭТОТ ОП (`connect.emit_fittings_cs` ->
    #     NewElbowFitting/NewTeeFitting/NewTransitionFitting в каждом узле
    #     степени >= 2), но ЧИСЛА их он не называет: `classify_junction` может
    #     свести стык к голому `Connector.ConnectTo` и не породить элемента, а
    #     какое семейство подставится в вызов, решают routing preferences. Ни
    #     то, ни другое НЕ ЗАМЕРЕНО, поэтому счётный свидетель гейтил бы
    #     незамеренную величину. До 10.08.2026 тут стояло «их число выбирает
    #     Revit из графа коннекторов (2652 + 152 при НУЛЕ авторских)» —
    #     причинность неверна (фитинги наши), а числа суть перепись
    #     snowdon_plumb_v3: PF=2652, DF=152, PA=126, и «152 арматуры» — это
    #     счёт фитингов воздуховодов, арматуры там 126, а её не создаёт ни
    #     один эмиттер пакета;
    #   * членство в MEPSystem — сливается на Commit(), а не на
    #     doc.Regenerate() (замер, connect.py §A), поэтому ЛЮБАЯ
    #     внутритранзакционная проверка «все участки в одной системе»
    #     неудовлетворима ПО ПОСТРОЕНИЮ. Написать её было бы не осторожностью,
    #     а проверкой, которая всегда падает, — ровно так же нечестно, как та,
    #     что не может упасть никогда. Факт читается ПОСЛЕ коммита
    #     (`connect.emit_system_readback_cs` -> mep_system_ids/one_system) и
    #     сообщается, а не утверждается.
    # Снимет исключение только архитектурное изменение (свидетель, живущий
    # после Commit), а не переформулировка прозы.
    "route_pipe_system": (
        ("deliberately not gated",
         "the op emits the fittings itself (NewElbowFitting/NewTeeFitting/"
         "NewTransitionFitting per node of degree>=2) but declares no fitting "
         "COUNT, and neither the ConnectTo-instead-of-fitting case nor the "
         "routing-preference family choice has been measured, and "
         "MEPSystem membership merges at Commit() — an in-transaction "
         "membership check is unsatisfiable by construction, so the fact is "
         "read back after commit and reported, never asserted (09.08)"),
    ),
    "route_duct_system": (
        ("deliberately not gated",
         "the op emits the fittings itself (NewElbowFitting/NewTeeFitting/"
         "NewTransitionFitting per node of degree>=2) but declares no fitting "
         "COUNT, and neither the ConnectTo-instead-of-fitting case nor the "
         "routing-preference family choice has been measured, and "
         "MEPSystem membership merges at Commit() — an in-transaction "
         "membership check is unsatisfiable by construction, so the fact is "
         "read back after commit and reported, never asserted (09.08)"),
    ),
    # Ещё две клаузулы, которые НАЗЫВАЮТ ОТСУТСТВИЕ свидетеля вместо того,
    # чтобы промолчать. Обе — про величины, которые вычисляет REVIT, а не
    # автор. Приехали волной каркаса; слияние 09.08 взяло ОБЪЕДИНЕНИЕ — обе
    # волны дописывали в конец одного словаря исключений, и любая «победившая»
    # сторона стёрла бы два честно названных отсутствия.
    "create_beam_system": (
        ("deliberately not gated",
         "beam count and spacing come from LayoutRule, which no argument of "
         "BeamSystem.Create sets and no author named — demanding a number "
         "nobody asked for is exactly how the height_mm default rolled back "
         "correctly built facade walls (31.07). Direction and Elevation are "
         "Revit-normalised values with no measured comparison rule, so they "
         "ride the receipt instead: a reader sees them, a witness does not "
         "demand them"),
    ),
    "create_truss": (
        ("belongs to the truss family",
         "chord shape, panel count and web layout are the family's, not the "
         "op's — the op names a base line and a type, and gating geometry it "
         "never authored would reject every correctly built truss whose "
         "family differs from our guess"),
        ("rides the receipt rather than a demand",
         "which reference level Revit picks is its inference from the sketch "
         "plane, not our argument — the exact create_beam lesson measured "
         "27.07, where forcing that equality rolled correct framing back"),
    ),
    # wave/reinforcement (10.08). ДВЕ клаузулы, которые НАЗЫВАЮТ ОТСУТСТВИЕ
    # свидетеля вместо того, чтобы промолчать, и обе — замер, а не осторожность.
    "create_area_reinforcement": (
        ("ride the receipt rather than a demand",
         "Revit normalises the major direction and projects it into the "
         "host's plane, so comparing it back needs an angular tolerance "
         "nobody in this house has measured; bar count is chosen by the "
         "reinforcement type's layout, which no argument of Create sets — "
         "demanding a number nobody asked for is exactly how the height_mm "
         "default rolled back correctly built facade walls (31.07). Both "
         "values, and the HostStructuralRebar setting that explains a zero, "
         "are read back and reported, never asserted"),
        ("not witnessed on purpose",
         "the boundary is computed by Revit from the host — the program "
         "authors no dimension at all — and 38 stored decompiles with a "
         "census contain zero OST_AreaRein/OST_PathRein/OST_Rebar/"
         "OST_FabricAreas elements (10.08), so no honest expected value "
         "exists to gate on and an invented tolerance would be the defect "
         "class this compiler exists to kill"),
    ),
    # `create_dimension`'s "receipt-only" exemption was DELETED by the
    # annotation wave (09.08), not lost in this merge: the resolver now knows
    # which PLANE each reference names, so an independent expected distance
    # exists and the op carries a real gated GEOMETRY obligation instead of an
    # exemption. `create_wall_foundation` above keeps its exemption because
    # nothing about it has been measured yet — the two are unrelated.
}


def _clause_tokens(text: str) -> frozenset[str]:
    """Normalize a prose postcondition into comparable lowercase word tokens."""

    return frozenset(re.findall(r"[a-zа-я_]+", text.lower()))


def audit_registry_coverage() -> tuple[str, ...]:
    """Return every table<->registry mismatch (empty tuple == fully covered).

    Three fail-closed invariants:
      1. Every write op (family in WRITE_FAMILIES) has an OpRefinementSpec.
      2. Every REFINEMENT op is a real registry op (no dangling entry).
      3. Every ';'-separated clause of each op's OpSpec.post is witnessed by at
         least one obligation whose clause shares a distinguishing token —
         so a newly promised clause with no obligation is a hard mismatch.

    ГРАНИЦА ЭТОГО АУДИТА, НАЗВАННАЯ ЧЕСТНО (03.08).  Инвариант 3 сверяет
    прозу по ОБЩИМ СЛОВАМ, то есть это сопоставление подстрок в другой
    одежде.  Пропущенный им случай измерен: клаузула уклона route_* (KIR-X004)
    жила БЕЗ своего обязательства и проходила аудит, потому что слово
    «segment» встречается и у диаметра, и у связности.  Сильная форма — не
    слова, а МУТАЦИЯ: вырезать эмитируемого свидетеля и потребовать, чтобы
    `proven` упал (tests/test_tolerance_provenance.py, закон L6).  Этот
    аудит остаётся дешёвой первой линией, а не доказательством.
    """

    table = _ensure_table()
    problems: list[str] = []

    write_ops = {
        name for name, op_spec in spec.OPS.items()
        if op_spec.family in spec.WRITE_FAMILIES
    }
    covered = set(table)

    for name in sorted(write_ops - covered):
        problems.append(f"{name}: write op has no OpRefinementSpec")
    for name in sorted(covered - write_ops - _EXTRA_CERTIFIABLE):
        problems.append(
            f"{name}: OpRefinementSpec references a non-write / unknown op")

    # Clause-level biection: each prose clause must map to an obligation.
    # Distinguishing tokens: content words minus ubiquitous filler.
    filler = _clause_tokens(
        "exists when given the a is at in of and or == !=  mm tol day "
        "post commit re read semantic geometry topology witness parameter "
        "chain bip resolved requested value type flag")
    for name, ref in sorted(table.items()):
        if name not in spec.OPS:
            continue
        op_spec = spec.OPS[name]
        obligation_tokens = frozenset().union(
            *(_clause_tokens(o.clause) for o in ref.obligations))
        exemptions = _NON_WITNESSABLE_CLAUSES.get(name, ())
        for raw_clause in op_spec.post.split(";"):
            clause = raw_clause.strip()
            if not clause:
                continue
            low = clause.lower()
            if any(marker in low for marker, _why in exemptions):
                continue
            key_tokens = _clause_tokens(clause) - filler
            if not key_tokens:
                continue
            if not (key_tokens & obligation_tokens):
                problems.append(
                    f"{name}: promised clause not witnessed by any "
                    f"obligation: {clause!r}")

    return tuple(problems)


__all__ = [
    "BLOCK_CREATE",
    "BLOCK_POST",
    "CERT_MODE_OFF",
    "CERT_MODE_RECORD",
    "CERT_MODE_REFUSE",
    "CertificateError",
    "CertificateSchemaError",
    "ClauseVerdict",
    "KIND_GEOMETRY",
    "KIND_IDENTITY",
    "KIND_MATERIALIZE",
    "KIND_PARAMETER",
    "KIND_SEMANTIC",
    "KIND_TOPOLOGY",
    "Obligation",
    "OpCertificate",
    "OpRefinementSpec",
    "ProgramCertificate",
    "REFINEMENT",
    "UnprovenRefinementError",
    "VACUITY_CONSTANT_FALSE",
    "VACUITY_KINDS",
    "VACUITY_SELF_COMPARISON",
    "VACUITY_UNREACHABLE",
    "VacuityFinding",
    "VacuousWitnessError",
    "analyze_witness_cs",
    "assert_refined",
    "audit_registry_coverage",
    "certificate_enabled",
    "certificate_mode",
    "certify_op",
    "certify_program",
    "witness_site_census",
    "witness_vacuity",
]
