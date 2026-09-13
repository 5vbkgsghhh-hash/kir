"""`kir_read` — the building, and the SDK, through one door.

🔴 WHY THE REFERENCE IS PULLED AND NOT PUSHED, IN S's NUMBERS (13.09.2026).
A section slice on task P01: YES on the first attempt, **940 characters** of
prompt, **0 refusals**. The whole registry plus help: YES on the second,
**2 781 characters**. And **without help at all: zero on both tasks** — the
model tries to invent the reference itself and never reaches a program.

So all three are false: pushing the course (16 781 characters in every
prompt, the block the model looped on for 174 291 ms), pushing all 83 names,
and withholding help. What works is a SLICE plus help ON REQUEST.

🔴 CHARACTERS, NOT BYTES, IN THIS FILE'S CEILINGS. `language` and `help`
return TEXT a model reads; the gates count characters (G3: <=900 with a
section, <=1 500 without). The SURFACE is counted in bytes elsewhere. Mixing
the two is how a pin came to hold 13 204 characters under the name
`SURFACE_MAX_BYTES`.
"""
from __future__ import annotations

from kir.door.registry import Ctx, Refusal

__all__ = ["kir_read", "language_text", "help_text", "SECTION_OF_RU"]

#: Gate G3. With a section: 900 (measured max — АР 804 characters, own plus
#: "общее"). Without: 1 500 (measured — all 83 names one per line, 1 400).
#: TWO ceilings and not one, and that is the whole strength of the gate: a
#: single ceiling of 1 500 would pass the full registry to a sectioned expert
#: and the gate would be decoration.
LANGUAGE_MAX_CHARS_SECTIONED = 900
LANGUAGE_MAX_CHARS_WHOLE = 1_500

#: The owner's letters against the registry's English keys. The translation
#: itself lives in `kir/spec.py::DISCIPLINE_RU` and is NOT copied here — this
#: maps the other way, from what an agent types to what the registry knows.
SECTION_OF_RU = {
    "АР": "architectural",
    "КР": "structural",
    "ОВ": "mechanical",
    "ВК": "plumbing",
    "ЭОМ": "electrical",
}


def kir_read(args: dict, ctx: Ctx) -> dict:
    what = args.get("what")
    if not isinstance(what, str) or not what:
        return Refusal("what_required",
                       "поле `what` обязано быть одним из: building, level_plan, "
                       "elements, element, language, help",
                       next="kir_read").as_dict()

    if what == "language":
        section = args.get("section") or ctx.section
        text, sectioned = language_text(section)
        cap = (LANGUAGE_MAX_CHARS_SECTIONED if sectioned
               else LANGUAGE_MAX_CHARS_WHOLE)
        return {"ok": True, "what": "language", "section": section,
                "chars": len(text), "text": text,
                "next": {"do": "kir_read"},
                # The ceiling travels WITH the answer: an agent that sees the
                # number stops guessing whether it got everything.
                "ceiling_chars": cap}

    if what == "help":
        op = args.get("op")
        if not isinstance(op, str) or not op:
            return Refusal("unknown_op",
                           "для what=help назови операцию полем `op`; "
                           "имена — what=language",
                           next="kir_read").as_dict()
        text = help_text(op)
        if text is None:
            return Refusal("unknown_op",
                           f"операции «{op}» в реестре нет; имена — what=language",
                           next="kir_read").as_dict()
        return {"ok": True, "what": "help", "op": op,
                "chars": len(text), "text": text, "next": None}

    if what == "level_plan":
        # 🔴 THE ONE FIELD WHOSE CARRIER DOES NOT EXIST YET. Measured 13.09:
        # six `query` ops in the registry and not one of them reads a level
        # whole. ДОК-M11 names it open and assigns it to N. The door refuses
        # BY NAME and hands over a move that exists, instead of returning an
        # empty plan that would read as "the level is empty".
        return Refusal(
            "no_level_plan_op",
            "чтения уровня пачкой в реестре ещё нет (оп `query_level_plan` "
            "не сдан). Уровень можно собрать счётчиками: what=elements по "
            "категориям",
            next="kir_read").as_dict()

    if what == "building":
        if ctx.snapshot is None:
            return Refusal("no_snapshot",
                           "снимка документа нет: среда не сообщила, что открыто",
                           next="question_to_lead" if ctx.role == "expert" else "ask_user",
                           ).as_dict()
        return {"ok": True, "what": "building",
                "text": _building_words(ctx.snapshot), "next": None}

    if what in ("elements", "element"):
        # The carriers are the six `query` ops; wiring them to a live document
        # is the panel's half (step 4 of the plan), not the registry's.
        return Refusal(
            "no_snapshot" if ctx.snapshot is None else "unknown_kind",
            "чтение элементов идёт через опы `query_*` и требует открытого "
            "документа; офлайн этой двери отвечать нечем",
            next="kir_read").as_dict()

    return Refusal("what_required", f"значения «{what}» у `what` нет",
                   next="kir_read").as_dict()


def language_text(section: str | None) -> tuple[str, bool]:
    """Names, one per line. Returns (text, is_sectioned).

    The slice is (own section + "общее"), and it comes from
    `spec.ops_by_discipline` — never from a literal here. A literal list would
    be a second carrier of truth about the language and would drift on the
    first new op, silently; the same argument is recorded in
    `kir/mcp/surface.py::_versions_enum`.
    """
    from kir import spec

    groups = dict(spec.ops_by_discipline(writes=True))
    key = SECTION_OF_RU.get((section or "").strip().upper()) if section else None
    if key and key in groups:
        own = sorted(groups[key])
        shared = sorted(groups.get("shared", []))
        lines = [spec.DISCIPLINE_RU[key]] + own
        if shared:
            lines += [spec.DISCIPLINE_RU["shared"]] + shared
        return "\n".join(lines), True
    # No section: plain names, no group headings. Headings would add ~100
    # characters and push the measured 1 400 against the 1 500 ceiling for
    # nothing an agent can use.
    return "\n".join(sorted(spec.OPS)), False


def help_text(op: str) -> str | None:
    """One op's contract — the SDK builder's docstring, not a second copy.

    Measured 13.09: `create_wall` 1 662 characters, the average across 83 ops
    799. That is the whole reason this is a door and not a prompt block: the
    same reference pushed for all 83 would be 66 356 characters.
    """
    from kir import sdk

    builder = sdk.builders().get(op)
    if builder is None:
        return None
    return (builder.__doc__ or "").strip() or None


def _building_words(snapshot: object) -> str:
    """The document in words and numbers. Reads whatever the host handed over
    and NAMES what it could not read — an unnamed gap reads as "empty", and
    "пустой" was already wrong once: «Проект1» was called empty and held
    3 892 instances (ДОК-A5)."""
    get = (snapshot.get if isinstance(snapshot, dict)
           else lambda k, d=None: getattr(snapshot, k, d))
    parts: list[str] = []
    title = get("document_name") or get("title")
    if title:
        parts.append(f"Документ «{title}»")
    version = get("revit_version") or get("version")
    if version:
        parts.append(f"Revit {version}")
    levels = get("levels")
    if isinstance(levels, (list, tuple)):
        parts.append(f"уровней {len(levels)}")
    elif isinstance(levels, int):
        parts.append(f"уровней {levels}")
    else:
        parts.append("уровни среда не сообщила")
    counts = get("categories") or get("counts")
    if isinstance(counts, dict) and counts:
        top = sorted(counts.items(), key=lambda kv: -_as_int(kv[1]))[:6]
        parts.append("по категориям: "
                     + ", ".join(f"{k} {_as_int(v)}" for k, v in top))
    else:
        parts.append("переписи по категориям нет — счётчики не сверены")
    units = get("units")
    if units:
        parts.append(f"единицы {units}")
    return ". ".join(parts) + "."


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return 0
