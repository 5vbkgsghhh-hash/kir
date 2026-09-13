"""`question_to_lead` and `ask_user` — the two ways out, and they differ by
WHOM they reach.

🔴 THE EXPERT DOES NOT SPEAK TO THE HUMAN. Owner's word: the lead is a lead
and decides himself. So the expert's only exit is the lead, and the lead's
only exit is the human. A single `ask_user` shared by both would put every
expert's confusion on the human's screen, which is palka (h) of
`HARNESS_VERDICT`: "UI объясняет словами то, что должен делать агент".

This module carries no policy of its own: it shapes the question and names
who will read it. Whether the lead answers from the journal or asks the human
is the LEAD's decision (spec §6.4), and its two exceptions — an ambiguous
brief, and a decision that changes what was explicitly asked — belong to the
lead's turn, not here.
"""
from __future__ import annotations

from kir.door.registry import Ctx, Refusal

__all__ = ["ask_outside"]


def ask_outside(name: str, args: dict, ctx: Ctx) -> dict:
    """🔴 THE BRANCH COMES FIRST, THE FIELD CHECK SECOND. Found by a LIVE model
    on 13.09.2026 (S, cassette `cassettes/B-p01-1.json`): the `question` check
    stood BEFORE the branch, so `assign` and `show_preview` — which have no
    `question` field at all — both answered `question_required`. Their schemas
    say `required: ["section","brief"]` and `additionalProperties: false`, so
    the only road to success led through a field the schema FORBIDS. A model
    reading the schema honestly could never pass.

    The cost was measured, not imagined: the lead called `assign` twice by its
    own schema, was refused twice, and then went to `ask_user` three times —
    it carried a TOOL's obstacle to the HUMAN. That is palka (h), the exact
    thing this door was written against.

    THE LESSON FOR THE GATES, and it is bigger than the line: nine gates and
    87 pins did not see this, because every one of them judged the SHAPE of
    refusals and not one asked whether a tool's happy path is reachable BY ITS
    OWN SCHEMA. `tests/test_every_tool_is_reachable_by_its_own_schema.py` now
    asks exactly that.
    """
    if name == "question_to_lead" or name == "ask_user":
        question = args.get("question")
        if not isinstance(question, str) or not question.strip():
            # `next` points back at this same tool ON PURPOSE, and that is not
            # the dead end S named: the field is IN the schema, so calling
            # again with it filled can succeed. A move that cannot succeed is
            # the defect; a move that needs one more field is not.
            return Refusal("question_required",
                           "поле `question` обязано быть непустым вопросом",
                           next=name).as_dict()
        if name == "question_to_lead":
            return {"ok": True, "asked": "lead", "question": question,
                    "why": args.get("why"), "waiting": True, "next": None}
        return {"ok": True, "asked": "human", "question": question,
                "why": args.get("why"), "options": args.get("options") or [],
                "waiting": True, "next": None}
    if name == "assign":
        return _assign(args, ctx)
    if name == "show_preview":
        return {"ok": True, "shown": args.get("section") or "всё",
                "wrote_nothing": True,
                "words": "Лист показан человеку. В документ не записано ничего.",
                "next": None}
    return Refusal("tool_not_in_role", f"инструмента «{name}» дверь не несёт",
                   next="kir_read").as_dict()


def _assign(args: dict, ctx: Ctx) -> dict:
    """A brief to a section expert. Refuses a section that has nothing to
    build with — measured 13.09 (`spec.ops_by_discipline`): ЭОМ holds **2**
    ops, and СС and ГП are not in `registry_base.DISCIPLINES` at all
    (ОТК-47). Assigning to an empty section is a promise, and the lead has to
    hear that before the human does."""
    from kir.door.read import SECTION_OF_RU, language_text

    section = args.get("section")
    brief = args.get("brief")
    if not isinstance(section, str) or section not in SECTION_OF_RU:
        return Refusal("section_required",
                       "раздел обязан быть одним из: "
                       + ", ".join(SECTION_OF_RU),
                       next="assign").as_dict()
    if not isinstance(brief, str) or not brief.strip():
        return Refusal("brief_required",
                       "бриф обязан быть непустым: эксперт не угадывает задачу",
                       next="assign").as_dict()
    slice_text, sectioned = language_text(section)
    own = _own_count(section)
    if own == 0:
        return Refusal("section_has_no_ops",
                       f"в разделе {section} операций нет — поручать нечего",
                       next="ask_user").as_dict()
    note = None
    if own <= 2:
        note = (f"🔴 в разделе {section} всего {own} операций — этого хватит "
                f"не на всякий бриф")
    return {"ok": True, "assigned": section, "brief": brief,
            "facts": args.get("facts") or [],
            "slice_chars": len(slice_text), "sectioned": sectioned,
            "section_ops": own, "note_ru": note, "next": None}


def _own_count(section: str) -> int:
    from kir import spec
    from kir.door.read import SECTION_OF_RU

    key = SECTION_OF_RU[section]
    return len(dict(spec.ops_by_discipline(writes=True)).get(key, ()))
