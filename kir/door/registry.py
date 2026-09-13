"""THE REGISTRY — the only place a tool exists.

A tool is ONE record. Hosts and roles are projections of it, never second
copies. The defect this closes was measured, not imagined: four sets for one
language (MCP 7 · panel 3 · CLI 9 · window 28, audit H §1), and eight
subjects that diverged between two of them (§1.2).

🔴 THE ORDER IS A TUPLE. A listing whose order depends on a dict's history
misses every client's prompt cache silently. The same argument is recorded
in `kir/mcp/surface.py`'s header, and this tree has already paid for it with
the obfuscator.

🔴 A ROLE IS A PROJECTION TOO, NOT A FILTER APPLIED LATER. `roles` sits on
the record because "the lead must not see the language" is a fact about the
tool, not a decision of whoever renders it. Filtering after the fact is how
`revit_ir_bulk` came to be announced to models while never being injected
(ОТК-42).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable

__all__ = ["FACTS_SCHEMA", "HOSTS", "LEAD_ANSWER_SCHEMA", "ROLES", "TOOLS",
           "Ctx", "Refusal", "Tool", "budget", "call", "exhausted",
           "first_touch_bytes", "lead_answer", "names", "notice", "projection",
           "rule_of_seniority", "schema_digest", "surface_bytes", "tool"]

#: The two roles, and there is no third. The lead talks to the human and
#: hands out sections; the expert builds and never speaks to the human.
ROLES = ("lead", "expert")

#: Hosts a projection is asked for. `panel` is the product's function-call
#: shape, `cli` the shell's.
HOSTS = ("mcp", "panel", "cli")

#: The ceiling on one role's surface, in UTF-8 BYTES (gate G2 for the
#: expert, G4/G2 arithmetic for the lead). Held by
#: `tests/test_the_expert_surface_is_bounded.py`.
EXPERT_SURFACE_MAX_BYTES = 5_500
LEAD_SURFACE_MAX_BYTES = 4_730

#: THE EXPERT'S BUDGET, AND EVERY NUMBER IS FROM THE M5 MEASUREMENT (ДОК-M14,
#: `.work/prod-20260913/rq7-prep/deepseek_sdk/REPORT.md`). The winning cell —
#: section slice plus help on P01 — built on the FIRST attempt with 940
#: characters of prompt, 2 help calls, 13 792 tokens and 76.44 s. The
#: pathological cell — all 83 names plus help on the shed — burned 13 help
#: calls, 151 311 tokens and 382.58 s and built NOTHING. Each ceiling below is
#: roughly twice the winner and cuts the funnel.
EXPERT_PROMPT_MAX_CHARS = 1_000      # winner 940
EXPERT_HELP_CALLS_MAX = 4            # winner 2; funnel 13 and 9
EXPERT_BUILD_ATTEMPTS_MAX = 3        # winner 1; arm A spent 3 and never built
EXPERT_TOKENS_MAX = 20_000           # winner 13 792; funnel 151 311 (11x)
#: 120 s also makes FIVE sections fit one human turn sequentially: the panel's
#: turn budget in production is `KUKAI_TURN_BUDGET_S=600`.
EXPERT_SECONDS_MAX = 120             # winner 76.44; funnel 382.58

#: Gate G4: no role may exceed four tools. Four is not a taste — it is the
#: count at which a weak model still picks the right one; S measured a lead
#: with four handing out exactly one brief on a 591-character prompt.
MAX_TOOLS_PER_ROLE = 4


@dataclass(frozen=True)
class Refusal:
    """A refusal that NAMES the next move, and the next move is a tool.

    🔴 `next` IS NOT PROSE. Measured 13.09: of three refusals that reached
    a model that day, **3 of 3** named a move the agent could not make —
    `revit_ir` that was absent from the palette, and the environment
    variable `KUKAI_KIR_TOOL=stage2`. A refusal whose next move is a
    variable is a dead end wearing an explanation.
    """

    code: str
    message_ru: str
    next: str  # a tool name from TOOLS — checked by gate G8

    def as_dict(self) -> dict:
        return {"ok": False, "wrote_nothing": True,
                "err": {"code": self.code, "message_ru": self.message_ru},
                "next": {"do": self.next}}


@dataclass
class Ctx:
    """What the door knows and the agent therefore does not have to say.

    Every field here is a question the agent used to be asked and could not
    answer: which document, which Revit version, which section, who executes.
    The audit's §1.3 lists them as "hidden state"; hidden state stops being
    a defect exactly when the door owns it instead of the prompt.
    """

    role: str = "expert"
    section: str | None = None
    document: str | None = None
    versions: tuple[str, ...] = ("2023", "2026")
    executor: Any = None          # port: .execute(link_key, program) -> dict
    link_key: str = "offline"
    #: Identity of the turn, for a DERIVED operation_id (never random).
    turn_id: str = ""
    tool_call_id: str = ""
    #: The document as the environment read it — half of the pair the store
    #: searches by (`kir/mcp/live.py::_blocking_records`).
    document_fingerprint: str | None = None
    attempt: int = 1
    snapshot: Any = None          # what `kir_read(what="building")` reads


@dataclass(frozen=True)
class Tool:
    """One record. `description`/`schema` may depend on the ROLE and on
    nothing else — not on the host, because a host must not change a byte of
    what the model sees (that is the whole point of a projection)."""

    name: str
    roles: frozenset[str]
    title_ru: str
    _description: Callable[[str], str]
    _schema: Callable[[str], dict]
    refusals: tuple[str, ...]
    reads: bool
    writes: bool

    def description(self, role: str) -> str:
        return self._description(role)

    def schema(self, role: str) -> dict:
        return self._schema(role)


# ─────────────────────────────────────────────────────────────────────────────
# Schemas. Small on purpose: gate G1 caps `kir_build` at 700 B, and the
# reason is not economy. The agent writes python; a JSON envelope on the
# wire would be a second language it has never seen.
# ─────────────────────────────────────────────────────────────────────────────

def _build_schema(role: str) -> dict:
    return {
        "type": "object", "additionalProperties": False,
        "required": ["source"],
        "properties": {
            "source": {"type": "string", "minLength": 1, "maxLength": 200000,
                       "description": "Питон против `kir.dsl`."},
            "focus": {"type": "string", "maxLength": 128,
                      "description": "Уровень или зона. Молчание — активный вид."},
            "preview": {"type": "boolean", "default": False,
                        "description": "true — показать лист человеку, не писать."},
        },
    }


#: What `kir_read` can be asked, BY ROLE. The lead has no `language`/`help`:
#: he does not write programs, and an answer he cannot use is a temptation
#: to try (that is how a model spends a turn probing what is already shut).
_READ_WHAT = {
    "expert": ("building", "level_plan", "elements", "element", "language", "help"),
    "lead": ("building", "level_plan", "elements", "element"),
}


def _read_schema(role: str) -> dict:
    props: dict[str, Any] = {
        "what": {"enum": list(_READ_WHAT[role])},
        "level": {"type": "string", "maxLength": 128},
        "kind": {"type": "string", "maxLength": 64,
                 "description": "Категория. Неизвестная — отказ со списком."},
        "uid": {"type": "string", "maxLength": 128},
        "limit": {"type": "integer", "minimum": 1, "maximum": 2000},
    }
    if role == "expert":
        props["op"] = {"type": "string", "maxLength": 64,
                       "description": "Имя операции — для what=help."}
        props["section"] = {"type": "string", "maxLength": 8,
                            "description": "Раздел — для what=language."}
    return {"type": "object", "additionalProperties": False,
            "required": ["what"], "properties": props}


def _question_schema(role: str) -> dict:
    return {
        "type": "object", "additionalProperties": False,
        "required": ["question"],
        "properties": {
            "question": {"type": "string", "maxLength": 2000},
            "why": {"type": "string", "maxLength": 500,
                    "description": "Чем ход заблокирован — из `next` прошлой квитанции."},
        },
    }


def _ask_schema(role: str) -> dict:
    s = _question_schema(role)
    s["properties"]["options"] = {"type": "array", "maxItems": 6,
                                  "items": {"type": "string", "maxLength": 200}}
    return s


#: The fact sheet's schema. S's carrier, not a second form:
#: `.work/prod-20260913/rq7-prep/facts/document_facts.py`.
FACTS_SCHEMA = "kir-rq7-document-facts/2"

#: The lead's answer to `question_to_lead`. Three load-bearing fields, each
#: bought by a measurement — see `lead_answer`.
LEAD_ANSWER_SCHEMA = "kir-door-lead-answer/1"


def _assign_schema(role: str) -> dict:
    """🔴 `facts` IS AN OBJECT, NOT A LIST OF STRINGS, AND THE FORM IS
    `identifiers`. Measured by S 13.09: offline a type/symbol/system slot
    grounds ONLY as `{"by": "element_id"}` — a name or a default needs a model
    snapshot and answers `KIR-G103`. Of 35 such slots in the registry, 21 do
    not take even an in-program reference. A sheet of names therefore makes an
    expert refuse before Revit, and the measurement would show a missing
    identifier rather than a language. P01 with identifiers: built on the
    FIRST attempt, 0 refusals; with names, the second attempt through
    `KIR-G103`.

    `links` carries NEIGHBOURS BY ADDRESS, never their program text: a
    neighbour may be rewritten after the brief goes out, and the text would go
    stale silently while the address does not (`kir/project_pack.py::pack_ref`).
    """
    return {
        "type": "object", "additionalProperties": False,
        "required": ["section", "brief"],
        "properties": {
            "section": {"enum": ["АР", "КР", "ОВ", "ВК", "ЭОМ"]},
            "brief": {"type": "string", "maxLength": 4000},
            "facts": {"type": "object",
                      "description": ("Лист фактов формы `identifiers`: "
                                      "уровни и каталоги с element_id. "
                                      "Имена без id эксперту не заземлить.")},
            "links": {"type": "array", "maxItems": 64,
                      "description": "Адреса выходов соседних разделов.",
                      "items": {"type": "object",
                                "additionalProperties": False,
                                "required": ["by", "link", "output"],
                                "properties": {
                                    "by": {"const": "pack"},
                                    "link": {"type": "string", "maxLength": 64},
                                    "output": {"type": "string", "maxLength": 64}}}},
        },
    }


def _preview_schema(role: str) -> dict:
    return {"type": "object", "additionalProperties": False,
            "properties": {"section": {"enum": ["АР", "КР", "ОВ", "ВК", "ЭОМ", "всё"]}}}


# ─────────────────────────────────────────────────────────────────────────────
# Prose. Russian, because it is a PRODUCT string the model reads. No op
# names and no example programs: S measured on 13.09 that a section slice
# plus help-on-request beats the full registry (YES on attempt 1, 940
# characters, against YES on attempt 2, 2 781), and the owner's word forbids
# examples outright.
# ─────────────────────────────────────────────────────────────────────────────

_BUILD_DESC = (
    "Построить в открытом документе то, что соберёт твой питон.\n"
    "Пиши обычный питон против `kir.dsl`: операции — функции, циклы и "
    "переменные работают как всегда. Наружу уезжает последнее выражение "
    "либо переменная `program`.\n"
    "Имена операций своего раздела — `kir_read({\"what\":\"language\"})`; что "
    "принимает одна — `kir_read({\"what\":\"help\",\"op\":\"…\"})`. То же внутри "
    "скрипта: `spec(\"…\")`, ответ придёт в этой же квитанции.\n"
    "Скрипт идёт в песочницу отдельным процессом: сети нет, диск закрыт, "
    "импорты по белому списку.\n"
    "Дальше дверь делает всё сама — проверяет замысел, компилирует под "
    "версию этого документа, пишет, перечитывает построенное по адресам. "
    "Отдельных шагов у тебя нет.\n"
    "Возвращает словами: что построено, по каким адресам, что осталось "
    "непроверенным, и если не всё — причину и следующий ход. Повтор того же "
    "исходника не строит дважды."
)

_READ_DESC_EXPERT = (
    "Спросить среду о здании — или о SDK.\n"
    "building — что за документ: уровни, счётчики, единицы;\n"
    "level_plan — уровень целиком одним ответом;\n"
    "elements / element — пачка по категории либо один по uid;\n"
    "language — имена операций ТВОЕГО раздела;\n"
    "help — что принимает одна операция."
)

_READ_DESC_LEAD = (
    "Спросить среду о здании.\n"
    "building — что за документ: уровни, счётчики, единицы;\n"
    "level_plan — уровень целиком одним ответом;\n"
    "elements / element — пачка по категории либо один по uid."
)

_QUESTION_DESC = (
    "Спросить ЛИДА. Человеку ты не пишешь: всё, чего не решить самому — "
    "двусмысленный бриф, нужда в чужом разделе, преграда среды — идёт лиду. "
    "Точную строку он даёт в `next` отказа."
)

_ASK_DESC = (
    "Задать вопрос ЧЕЛОВЕКУ и ждать ответа. Сюда уходит то, что решить "
    "нельзя: недостающее решение по проекту и преграда, которую снимает "
    "только человек. Точную строку дверь даёт в `next` отказа."
)

_ASSIGN_DESC = (
    "Поручить раздел эксперту. Он получит твой бриф, лист фактов и имена "
    "операций своего раздела; человеку он не пишет — вернётся к тебе.\n"
    "Поручай параллельно: разделы идут одновременно.\n"
    "`facts` — идентификаторы, которые эксперту не нужно искать самому."
)

_PREVIEW_DESC = (
    "Показать человеку лист того, что будет построено: имена, счёт, "
    "перепись. В документ ничего не пишет. Одобряет человек кнопкой — "
    "ответ придёт тебе."
)


def _const(text: str) -> Callable[[str], str]:
    return lambda role: text


TOOLS: tuple[Tool, ...] = (
    Tool(name="kir_build", roles=frozenset({"expert"}), title_ru="построить",
         _description=_const(_BUILD_DESC), _schema=_build_schema,
         refusals=("source_required", "weak_sandbox", "author_failed",
                   "compile_failed", "no_executor", "execute_failed"),
         reads=True, writes=True),
    Tool(name="kir_read", roles=frozenset({"expert", "lead"}), title_ru="прочитать",
         _description=lambda role: (_READ_DESC_EXPERT if role == "expert"
                                    else _READ_DESC_LEAD),
         _schema=_read_schema,
         refusals=("what_required", "unknown_op", "no_level_plan_op",
                   "unknown_kind", "no_snapshot"),
         reads=True, writes=False),
    Tool(name="question_to_lead", roles=frozenset({"expert"}), title_ru="спросить лида",
         _description=_const(_QUESTION_DESC), _schema=_question_schema,
         refusals=("question_required",), reads=False, writes=False),
    Tool(name="assign", roles=frozenset({"lead"}), title_ru="поручить раздел",
         _description=_const(_ASSIGN_DESC), _schema=_assign_schema,
         refusals=("section_required", "brief_required", "section_has_no_ops"),
         reads=False, writes=False),
    Tool(name="show_preview", roles=frozenset({"lead"}), title_ru="показать лист",
         _description=_const(_PREVIEW_DESC), _schema=_preview_schema,
         refusals=("nothing_to_show",), reads=True, writes=False),
    Tool(name="ask_user", roles=frozenset({"lead"}), title_ru="спросить человека",
         _description=_const(_ASK_DESC), _schema=_ask_schema,
         refusals=("question_required",), reads=False, writes=False),
)


def tool(name: str) -> Tool:
    for t in TOOLS:
        if t.name == name:
            return t
    raise KeyError(name)


def names(role: str) -> tuple[str, ...]:
    """Names a role sees, in registry order."""
    _check_role(role)
    return tuple(t.name for t in TOOLS if role in t.roles)


def projection(host: str, role: str) -> list[dict]:
    """ONE record rendered for a host. The host chooses the WRAPPER, never
    the content: `mcp` and `cli` carry `input_schema`, `panel` carries the
    product's `{"type":"function","function":{…}}`. Gate G5 compares the
    digests across hosts and they must be equal."""
    if host not in HOSTS:
        raise ValueError(f"unknown host {host!r}; known: {HOSTS}")
    _check_role(role)
    out: list[dict] = []
    for t in TOOLS:
        if role not in t.roles:
            continue
        body = {"name": t.name, "description": t.description(role),
                "input_schema": t.schema(role)}
        if host == "panel":
            out.append({"type": "function",
                        "function": {"name": t.name,
                                     "description": body["description"],
                                     "parameters": body["input_schema"]}})
        else:
            out.append(body)
    return out


def schema_digest(host: str, role: str) -> dict[str, str]:
    """name -> sha256 of the canonical schema. The wrapper is deliberately
    NOT hashed: what must match across hosts is the schema the model reads,
    not the envelope the host needs."""
    digests = {}
    for t in TOOLS:
        if role not in t.roles:
            continue
        blob = json.dumps(t.schema(role), ensure_ascii=False, sort_keys=True)
        digests[t.name] = hashlib.sha256(blob.encode()).hexdigest()
    return digests


def surface_bytes(role: str) -> int:
    """The role's whole surface in UTF-8 BYTES — descriptions plus schemas.

    🔴 BYTES, and the unit is the point. The older pin counted characters
    under the name `SURFACE_MAX_BYTES`; with Russian prose that is a factor
    of two, so the number was wrong by its own name.
    """
    total = 0
    for t in TOOLS:
        if role not in t.roles:
            continue
        total += len(t.description(role).encode())
        total += len(json.dumps(t.schema(role), ensure_ascii=False).encode())
    return total


#: The door's whole announcement, per role, in UTF-8 bytes (gate G7). It
#: replaces `instructions()` — 48 088 B measured 13.09, of which the language
#: course was the bulk and the block a model looped on for 174 291 ms.
NOTICE_MAX_BYTES = 2_000

_NOTICE_LEAD = (
    "Ты ведёшь проект. Языка здесь нет и он тебе не нужен: разделы строят "
    "эксперты, ты раздаёшь поручения и отвечаешь человеку.\n"
    "Разделы: АР — архитектура, КР — конструкции, ОВ — вентиляция, "
    "ВК — водоснабжение, ЭОМ — электрика (мало операций, хватит не на всякий "
    "бриф). Слаботочки и генплана сегодня нет вовсе — скажи это человеком, "
    "если он их просит.\n"
    "Старшинство при споре: КР важнее АР всегда; дальше самотёк, вентиляция, "
    "напорные, электрика. Решаешь ты; причину пиши в поручение. Человека "
    "спрашивай, только если бриф читается двумя способами или решение меняет "
    "явно просимое."
)

_NOTICE_EXPERT = (
    "Ты эксперт своего раздела. Строит `kir_build`: пиши питон, дверь сама "
    "проверит, скомпилирует и запишет.\n"
    "Имена операций своего раздела — `kir_read` с what=language; что "
    "принимает одна — what=help. Не угадывай форму операции: спроси.\n"
    "Человеку ты не пишешь. Не понял бриф или нужен чужой раздел — "
    "`question_to_lead`."
)


def notice(role: str) -> str:
    """What the door says about itself, and nothing about the language.

    🔴 NOT A COURSE, AND THE DIFFERENCE IS MEASURED. S, 13.09: a section
    slice pulled on request gave YES on the first attempt at 940 characters
    of prompt; the whole registry pushed gave YES on the second at 2 781.
    Pushing the course gave a model that looped on the notice itself. So the
    notice says two things only — which room, and where the reference is.
    """
    _check_role(role)
    return _NOTICE_LEAD if role == "lead" else _NOTICE_EXPERT


def first_touch_bytes(role: str) -> int:
    """Everything a role receives before it says one word, in BYTES."""
    return surface_bytes(role) + len(notice(role).encode())


def budget() -> dict:
    """The four numbers an expert is given, and it is TOLD them.

    🔴 AN EXPERT THAT DOES NOT KNOW ITS REMAINDER SPENDS IT ON RECONNAISSANCE.
    That is exactly what the pathological cell did: 13 help calls on a task
    that never built. So the budget is not a silent cap — it travels with the
    brief and its remainder travels with every answer of the lead.
    """
    return {"prompt_chars": EXPERT_PROMPT_MAX_CHARS,
            "help_calls": EXPERT_HELP_CALLS_MAX,
            "build_attempts": EXPERT_BUILD_ATTEMPTS_MAX,
            "tokens": EXPERT_TOKENS_MAX,
            "seconds": EXPERT_SECONDS_MAX}


#: What to say to the LEAD when a budget runs out. Never silence: silence is
#: the turn of 18:11Z — 174 291 ms, 0 tool calls, stopped by the owner's hand.
_EXHAUSTED_RU = {
    "help_calls": ("справки исчерпаны: форму слота назови в брифе. "
                   "Спрашивал: {detail}"),
    "build_attempts": ("попытки исчерпаны. Последний отказ: {detail}"),
    "tokens": ("бюджет токенов исчерпан. Сделано: {detail}"),
    "seconds": ("время исчерпано. Сделано: {detail}"),
}


def exhausted(kind: str, detail: str = "—") -> dict:
    """A spent budget is a QUESTION TO THE LEAD, not a stop and not a human.

    Returns the same shape `question_to_lead` returns, so the caller has one
    reader for both: an expert that asked and an expert that ran out look the
    same to the lead, and that is correct — both need a decision.
    """
    if kind not in _EXHAUSTED_RU:
        raise ValueError(f"unknown budget {kind!r}; known: {sorted(_EXHAUSTED_RU)}")
    return {"ok": True, "asked": "lead", "budget_exhausted": kind,
            "question": _EXHAUSTED_RU[kind].format(detail=detail),
            "waiting": True, "next": None}


def lead_answer(*, answers: str, facts_added: dict | None = None,
                brief_amended: str | None = None,
                decision: dict | None = None,
                budget_left: dict | None = None) -> dict:
    """The lead's answer, in one shape — `kir-door-lead-answer/1`.

    THE THREE LOAD-BEARING FIELDS, each from a measurement:

      * `facts_added` — what an expert lacks is most often an IDENTIFIER, not
        a meaning (`KIR-G103`, 21 of 35 slots take nothing but an id). An
        answer in prose leaves it exactly where it was.
      * `decision` — the seniority ruling, and it is THE SAME STRING that goes
        into the journal (`seniority.decide(...)["line_ru"]`). Two strings
        would drift and the expert would be told a reason the journal does not
        hold.
      * `budget_left` — see `budget()`.
    """
    if not isinstance(answers, str) or not answers.strip():
        raise ValueError("lead answer must say something")
    return {"schema": LEAD_ANSWER_SCHEMA,
            "answers": answers,
            "facts_added": facts_added or {},
            "brief_amended": brief_amended,
            "decision": decision,
            "budget_left": budget_left or budget()}


def rule_of_seniority(conflict: dict, sections: tuple[str, str]) -> dict:
    """The door's single entrance to seniority — merge, clash and norms all
    come here, so the table cannot be copied into three callers."""
    from kir.door.seniority import decide

    return decide(conflict, sections)


def call(name: str, args: dict, ctx: Ctx) -> dict:
    """Dispatch. A name the role does not have is a refusal that NAMES what
    the role does have — never a silent nothing, and never an exception into
    the turn."""
    _check_role(ctx.role)
    allowed = names(ctx.role)
    if name not in allowed:
        return Refusal(
            "tool_not_in_role",
            f"инструмента «{name}» у роли «{ctx.role}» нет; есть: "
            + ", ".join(f"`{n}`" for n in allowed),
            next=allowed[0]).as_dict()
    if name == "kir_build":
        from kir.door.build import kir_build
        return kir_build(args, ctx)
    if name == "kir_read":
        from kir.door.read import kir_read
        return kir_read(args, ctx)
    from kir.door.outside import ask_outside
    return ask_outside(name, args, ctx)


def _check_role(role: str) -> None:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; known: {ROLES}")
