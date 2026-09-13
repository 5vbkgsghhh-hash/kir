"""THE DOOR NAMES WHAT AN OP CANNOT DO — AS A MACHINE FIELD, WITH A REASON.

The mandate: "a capability contract… a single registry remains the authority."
Since 07.09.2026 the terminal prints a "WHAT THIS OP CANNOT DO" block
(`kir ops <name>`), while the model walks through the door — and before this
instrument, it received a contract from which there was no way to learn that an op
does NOT DRAW in the plan and does NOT RISE back up. Silence reads as "can do
everything": the same class as a clash blind spot with no named reason.

🔴 WHY A FIELD, NOT LINES IN THE CONTRACT TEXT — A MEASUREMENT, NOT TASTE. The
text rides on the SANDBOX's ceiling (`course.LESSON_CAP` = 3300). A census on
07.09.2026 across all 83 ops: the channel headroom for `create_solid_blend` is
EIGHTEEN characters, while the constraints block weighs 321 at the median and 696
at the maximum (even the axis codes alone — 28). Writing it into the text would
take away this op's parameter bounds, and take them away silently. The door has no
ceiling at all: it answers over JSON-RPC.

WHAT THIS INSTRUMENT DOES NOT CHECK: that the axes are STATED CORRECTLY. That is
the subject of `tests/test_the_registry_owns_every_capability.py`, where the
declaration is checked against a LIVE measurement of each axis. What is checked
here is delivery: that what the tree already knows is required to reach the model.
"""
from __future__ import annotations

import asyncio

import pytest

from kir import capability, spec
from kir.mcp import server

#: An op with a MEASURED renderer gap. Chosen not by taste: `create_level` is
#: the first op of every program, and "the level isn't visible in the plan" is
#: otherwise something the model only learns from a blank picture.
ОП_С_ПРОБЕЛОМ = "create_level"

#: A verbatim trace of the reason in the response. The reason is required to name
#: the CARRIER of the gap, not paraphrase it in prose: this line is what lets the
#: author find the renderer.
СЛЕД_ПРИЧИНЫ = "OP_NOT_DRAWN"


def _ответ(op: object) -> dict:
    """The response of the LIVE door, not a call to `_spec` around it.

    The door is `dispatch`: it catches failures and wraps the outcome, and an
    instrument that calls the body directly would be checking the function, not
    the door.
    """
    body, crashed = asyncio.run(server.dispatch("kir_spec", {"op": op}))
    assert not crashed, f"дверь упала на `kir_spec` с op={op!r}"
    return body


def _проверить(body: dict) -> None:
    """The ONE AND ONLY place of assertion — the same one the mutation controls
    drive.

    Otherwise a control would be checking ITS OWN copy of the check, and such a
    copy goes green together with the defect (the shape "a refutation needs a
    control too," 04.09.2026).
    """
    assert body.get("ok") is True, body
    limits = body.get("limits")
    assert isinstance(limits, dict), (
        f"дверь не назвала `limits` вовсе: ключи {sorted(body)}")
    why = limits.get("preview")
    assert why, (
        f"`{ОП_С_ПРОБЕЛОМ}` в плане не рисуется, а ось `preview` в ответе "
        f"двери не названа: {sorted(limits)}")
    assert СЛЕД_ПРИЧИНЫ in why, (
        f"причина названа прозой без носителя: {why!r} — по ней автор не "
        f"найдёт, кто именно молчит")


def test_перепись_не_пуста() -> None:
    """A CONTROL ON THE SUBJECT ITSELF: the renderer gap is required to exist.

    The registry will get rebuilt, the gaps will get closed — and when that
    happens, this file is required to say so out loud, rather than staying green
    on an op that no longer has any constraints.
    """
    assert ОП_С_ПРОБЕЛОМ in spec.OPS, f"{ОП_С_ПРОБЕЛОМ} — не оп реестра"
    пробелы = [n for n in spec.OPS if "preview" in capability.limits(n)]
    assert len(пробелы) > 0, "пробелов рисовальщика нет — прибор проверяет пустоту"
    assert ОП_С_ПРОБЕЛОМ in пробелы, (
        f"{ОП_С_ПРОБЕЛОМ} больше не в пробелах рисовальщика — возьми другой "
        f"оп из {len(пробелы)} и перепиши довод, а не число")


def test_дверь_называет_ось_и_причину() -> None:
    """THE MAIN ASSERTION: the `preview` axis and its reason reached the model."""
    _проверить(_ответ(ОП_С_ПРОБЕЛОМ))


def test_контроль_снятие_причины_у_носителя_краснит(monkeypatch) -> None:
    """A FAIL CONTROL BY MUTATING THE CARRIER, not by substituting the response.

    We remove the name from `capability.PREVIEW_LIMITS` — the very carrier the
    door reads the reason from. The check is REQUIRED to turn red; if it survives
    the removal, it is reading something other than what the door reads, and its
    green means nothing (this is exactly how the first draft of the round-trip
    check fell apart on 07.09).
    """
    урезанный = dict(capability.PREVIEW_LIMITS)
    урезанный.pop(ОП_С_ПРОБЕЛОМ)
    monkeypatch.setattr(capability, "PREVIEW_LIMITS", урезанный)
    with pytest.raises(AssertionError):
        _проверить(_ответ(ОП_С_ПРОБЕЛОМ))


def test_контроль_немая_дверь_краснит(monkeypatch) -> None:
    """THE SECOND MUTATION — IN THE DOOR ITSELF: the field is gone, the carrier is
    intact.

    Two controls, not one, because they close off different ways of lying: the
    first — "the door reads the wrong carrier", the second — "the door stopped
    carrying the field". On its own, each one lets the other shape through.
    """
    monkeypatch.setattr(server, "_capability_fields", lambda _op: {})
    with pytest.raises(AssertionError):
        _проверить(_ответ(ОП_С_ПРОБЕЛОМ))


def test_умеющий_всё_оп_получает_пустой_limits_и_названные_оси() -> None:
    """An empty `limits` reads as "can do all five" ONLY next to `axes`.

    Without a closed list of axes, emptiness is indistinguishable from "we didn't
    look" — the same argument that `capability.limits` itself was set up on.
    """
    полные = [n for n in spec.OPS if not capability.limits(n)]
    assert полные, "опов без ограничений нет — утверждение проверяет пустоту"
    body = _ответ(полные[0])
    assert body["limits"] == {}
    assert body["axes"] == list(capability.AXES)
    assert sorted(body["capabilities"]) == sorted(capability.AXES)


def test_оглавление_и_макрос_осей_не_получают() -> None:
    """`capability` answers about OPS; silence here is more honest than an empty
    dictionary."""
    for аргумент in (None, "stack"):
        body = _ответ(аргумент)
        assert body.get("ok") is True, body
        assert "limits" not in body, (
            f"дверь приписала оси не-опу {аргумент!r}: пустой `limits` там "
            f"читался бы как «ограничений нет»")


def test_каждый_оп_реестра_получает_оси_и_ни_один_не_роняет_дверь() -> None:
    """DENOMINATOR: the census runs across the WHOLE registry, not a single name.

    An op added tomorrow passes through this instrument on the day it is set up:
    no name is ever typed out here.
    """
    беда: list[str] = []
    for имя in sorted(spec.OPS):
        body = _ответ(имя)
        if body.get("ok") is not True:
            беда.append(f"{имя}: дверь отказала — {body.get('err')}")
            continue
        if set(body.get("axes") or ()) != set(capability.AXES):
            беда.append(f"{имя}: оси названы не закрытым списком")
        if set(body.get("limits") or {}) | set(body.get("capabilities") or ()) \
                != set(capability.AXES):
            беда.append(f"{имя}: умеет+не умеет не покрывают пять осей")
    assert беда == [], "\n".join(беда)
