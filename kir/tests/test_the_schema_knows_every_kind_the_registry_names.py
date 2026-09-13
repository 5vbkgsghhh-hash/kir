"""Every parameter kind the registry names must have a schema branch.

🔴 THE CLASS THIS CLOSES, MEASURED TWICE (13.09.2026 and before it).
`kir/schema_gen.py` dispatches on `ParamSpec.kind` and ends in
`raise AssertionError(f"unknown param kind {p.kind}")`. Adding a kind to
`spec.PARAM_KINDS` without a branch here does NOT fail the registry import and
does NOT fail the compiler: it fails when the DOOR is built. In the product that
assertion is swallowed — the `revit_ir` injection sits inside a bare `except`
(`client.py:239`) — so the tool disappears from the palette in silence, with an
open gate and no error anyone can see.

It has happened twice by the same mechanism: `wall_layers` once, and
`identity` on 13.09.2026 (the wave that gave `set_param`/`change_type`/
`delete`/`move_elements` an `expected_identity`). Both times the registry was
right, the compiler was right, and the door was mute.

So this file does not pin the kinds that exist today — that list would rot and
would have to be edited by the very change it is meant to catch. It pins the
PROPERTY: whatever kinds the registry names, the schema generator knows them
all. The next new kind fails HERE, loudly, instead of in a palette.
"""
import pytest

from kir import spec
from kir.schema_gen import _op_schema


def registry_kinds() -> set[str]:
    return {param.kind for op in spec.OPS.values() for param in op.params}


def test_every_kind_in_use_is_declared_in_the_registry():
    """A kind used by an op but missing from `PARAM_KINDS` is the same hole
    one level earlier."""
    undeclared = sorted(registry_kinds() - set(spec.PARAM_KINDS))
    assert not undeclared, undeclared


@pytest.mark.parametrize("op_name", sorted(spec.OPS))
def test_the_schema_generator_knows_every_op(op_name):
    """Built per op, so a failure names WHICH op the door would have lost."""
    schema = _op_schema(spec.OPS[op_name])
    assert schema["type"] == "object"
    properties = schema.get("properties") or {}
    for param in spec.OPS[op_name].params:
        assert param.name in properties, (op_name, param.name, param.kind)


# `test_the_door_itself_builds` lives in `kir/mcp/tests/test_the_door_builds_for_every_kind.py`:
# it imports the door, and the language's tests may not (`test_the_language_never_mentions_the_door`).


def test_a_kind_with_no_branch_still_fails_loudly():
    """The lock itself is alive: an invented kind must raise, not pass."""
    from dataclasses import replace

    op = spec.OPS["create_level"]
    broken = replace(op, params=tuple(replace(p, kind="кто-то-выдумал")
                                      for p in op.params[:1]) + op.params[1:])
    with pytest.raises(AssertionError, match="unknown param kind"):
        _op_schema(broken)


#: EVERY reader of `spec.PARAM_KINDS` that decides something PER KIND, each with
#: the way its own table is read. The pin below walks this list, so a reader that
#: does not know a new kind fails HERE — with its own name — instead of in a
#: palette, a release gate or a course census three commits later.
#:
#: 🔴 THIS LIST EXISTS BECAUSE THE FIRST VERSION OF THIS FILE MISSED THREE OF
#: THEM (13.09.2026). It pinned `schema_gen` and the expressibility census, said
#: "the class is closed", and the release gate for 0.8.3 then went red on
#: `course/shape.py::CARRIERS` — a THIRD reader — while `macros._TRANSFORM_BY_KIND`
#: and the plural/scalar witnesses were quietly broken too. A pin that names the
#: readers it happens to know is not closing a class; it is closing the cases its
#: author remembered. So the list is here, in ONE place, and adding a reader
#: means adding a line to it.
def _registry_readers() -> dict[str, set[str]]:
    from kir.course import expressiveness, shape
    from kir.tests import test_unpinned_plural_witnesses as witnesses
    import kir.macros as macros

    from kir import sdk

    return {
        "kir/course/shape.py::CARRIERS": set(shape._kind_to_carrier()),
        "kir/course/expressiveness.py::CENSUS": set(expressiveness.CENSUS),
        "kir/macros.py::_TRANSFORM_BY_KIND": set(macros._TRANSFORM_BY_KIND),
        # 🔴 ПЯТЫЙ ЧИТАТЕЛЬ, И МОЙ СТОРОЖ СВЕЖЕСТИ ЕГО НЕ ВИДЕЛ (13.09.2026).
        # `kir/sdk.py` раскладывает КАЖДЫЙ вид по трём множествам
        # (`SELECTOR_KINDS | SELECTOR_LIST_KINDS | PLAIN_KINDS`) и сам держит на
        # это тест (`unclassified_kinds()`). Почему список не поймал его сам:
        # `test_the_reader_list_itself_is_not_stale` ищет файлы, НАЗЫВАЮЩИЕ
        # `PARAM_KINDS`, а в `sdk.py` этого имени нет ни разу — он перечисляет
        # виды строками. Измерено: `grep -c PARAM_KINDS kir/sdk.py` = 0.
        # То есть сторож свежести стерёг ОДИН способ быть читателем, а их два.
        "kir/sdk.py::SELECTOR|SELECTOR_LIST|PLAIN":
            set(sdk.SELECTOR_KINDS) | set(sdk.SELECTOR_LIST_KINDS) | set(sdk.PLAIN_KINDS),
        "kir/tests/test_unpinned_plural_witnesses.py::PLURAL|SCALAR":
            set(witnesses.PLURAL_KINDS) | set(witnesses.SCALAR_KINDS),
    }


@pytest.mark.parametrize("reader", sorted(_registry_readers()))
def test_every_reader_of_the_registry_knows_every_kind(reader):
    """Parametrized so a failure names WHICH reader went blind, not just that one did."""
    known = _registry_readers()[reader]
    missing = sorted(set(spec.PARAM_KINDS) - known)
    assert not missing, (
        f"{reader} не знает виды реестра: {missing}. Разнесите их ПО СМЫСЛУ — "
        "не в первую попавшуюся ветку: молчаливое умолчание здесь и есть та "
        "слепота, ради которой таблица заведена")
    stray = sorted(known - set(spec.PARAM_KINDS))
    assert not stray, f"{reader} называет виды, которых в реестре нет: {stray}"


#: Files that NAME the registry but decide nothing per kind — each with the
#: reason, because "it only mentions it" is a claim and claims rot.
_MENTIONS_ONLY = {
    "kir/spec.py": "дом реестра",
    "kir/schema_gen.py": "ветвление по виду, а не таблица — покрыто пином по каждому опу",
    "kir/instruments/canon_state.py": "печатает ЧИСЛО видов, решений по виду не принимает",
    "kir/ops_solid.py": "упоминание в комментарии",
    "kir/surface_query.py": "упоминание в комментарии",
    "kir/agreements.py": "сводит чужие переписи, своей таблицы по виду не держит",
    # ── Найдены 13.09.2026, когда сторож свежести стал ловить и второй способ
    # быть читателем (перечисление видов строками без имени `PARAM_KINDS`).
    "kir/ops_authoring.py": ("ОБЪЯВЛЯЕТ виды в ParamSpec, решений по виду не "
                             "принимает: это сторона реестра, а не читателя"),
    "kir/authoring_validation.py": ("ветвление по виду, а не таблица — как "
                                    "schema_gen; полнота покрыта пином по каждому "
                                    "опу и отказом на неизвестном виде"),
    # ── Вписаны S 13.09.2026 по заявке N 3 (в тот же заход, где `targets_w`
    # снят из обоих файлов: вида нет в `PARAM_KINDS` и ни один оп его не носит).
    # Ни один из двух НЕ ДЕРЖИТ ПЕРЕПИСИ по видам, поэтому место им здесь, а не
    # среди читателей: внесение их в `_registry_readers` потребовало бы знать
    # ВСЕ 41 вид, а это было бы ложью о том, что они делают.
    "kir/dsl.py": ("ветвление по виду, а не таблица: селекторные виды берутся у "
                   "`sdk` (единственный носитель классификации), форма составного "
                   "слота ВЫВОДИТСЯ из схемы, а неизвестный вид получает честное "
                   "голое имя рода. Полноту стережёт перепись по всему реестру "
                   "(test_a_composite_slot_prints_its_form)"),
    "kir/project_pack.py": ("_WRITE_KINDS/_SELECTOR_KINDS — ПОДМНОЖЕСТВА по "
                            "смыслу (цель записи против каталожного селектора), "
                            "а не перепись: неперечисленный вид просто не "
                            "селектор, и это верно по построению"),
    "kir/decompile/program_source.py": ("MM_KINDS/DEG_KINDS/MM_KINDS_REFUSED — "
                                        "ПОДМНОЖЕСТВА по смыслу, а не перепись: "
                                        "неперечисленный вид остаётся нетронутым. "
                                        "Полноту стережёт своя ревизия "
                                        "(test_program_source: «пересмотреть, а не "
                                        "поправить число»)"),
}


def test_the_reader_list_itself_is_not_stale():
    """A reader that exists but is not listed is exactly the hole this file had.

    Scanned over the LIVE package only. An earlier version of this test walked
    the whole tree and found two hundred files — copies under `.work`, installed
    venvs, published snapshots — which is not vigilance, it is noise that would
    be silenced by whoever met it next, and a silenced guard guards nothing.
    """
    import pathlib
    import re

    package = pathlib.Path(spec.__file__).resolve().parent
    root = package.parent
    listed = {name.split("::")[0] for name in _registry_readers()} | set(_MENTIONS_ONLY)
    candidates = set()
    for path in package.rglob("*.py"):
        posix = path.relative_to(root).as_posix()
        if posix.startswith("kir/tests/") and "unpinned_plural" not in posix:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        # ДВА СПОСОБА БЫТЬ ЧИТАТЕЛЕМ, И ВТОРОЙ СТОИЛ МНЕ ПЯТОГО ЧИТАТЕЛЯ
        # (13.09.2026). Первый — назвать `PARAM_KINDS`. Второй — не называть его
        # вовсе, а ПЕРЕЧИСЛИТЬ виды строками, как делает `kir/sdk.py`. Порог
        # взят по замеру, а не на глаз: по всему живому пакету выше 20 видов
        # держат ровно девять файлов — пять читателей из таблицы, `sdk.py`,
        # `authoring_validation.py`, `ops_authoring.py` и
        # `decompile/program_source.py`; ниже 20 идёт длинный хвост `ops_*`,
        # которые виды ОБЪЯВЛЯЮТ в ParamSpec, а решений по ним не принимают.
        if re.search(r"\bPARAM_KINDS\b", text):
            candidates.add(posix)
        elif sum(1 for kind in spec.PARAM_KINDS
                 if re.search(r'["\']%s["\']' % re.escape(kind), text)) >= 20:
            candidates.add(posix)
    unlisted = sorted(candidates - listed)
    assert not unlisted, (
        "эти файлы сверяются с реестром видов, но не перечислены ни среди "
        f"читателей, ни среди упоминающих: {unlisted} — впишите их в "
        "`_registry_readers` (если решают ПО ВИДУ) или в `_MENTIONS_ONLY` "
        "с причиной")
    stale = sorted(set(_MENTIONS_ONLY) - candidates)
    assert not stale, (
        f"эти файлы больше не упоминают реестр: {stale} — список освобождённых "
        "обязан протухать вместе с деревом, иначе он оправдывает то, чего нет")


def test_the_expressibility_census_knows_every_kind_too():
    """The SAME class, one door further out (measured 13.09.2026).

    `kir/course/expressiveness.py::CENSUS` is keyed by parameter kind and calls
    itself "complete by construction". A kind added to the registry without a
    row there does not make the census wrong quietly — it turns the census tests
    red — but it is the same hole as the schema branch: one registry, several
    readers, and each reader has to be taught separately. Pinning both here
    means a new kind meets ONE failure with both addresses in it.
    """
    from kir.course.expressiveness import CENSUS

    missing = sorted(set(spec.PARAM_KINDS) - set(CENSUS))
    assert not missing, (
        "виды есть в реестре, но не в переписи выразимости "
        f"(kir/course/expressiveness.py::CENSUS): {missing}")
    invented = sorted(set(CENSUS) - set(spec.PARAM_KINDS))
    assert not invented, ("перепись называет виды, которых в реестре нет: "
                          f"{invented}")


def test_the_two_readers_are_named_together():
    """If this fails, read it as: the registry grew and N readers must learn it.

    The readers known today are the schema generator and the census; the pin
    above checks each. This one exists so the LIST of readers is itself visible
    in one place instead of being rediscovered by whoever breaks the door next.
    """
    readers = set(_registry_readers()) | {"kir/schema_gen.py::_op_schema",
                                          "kir/sdk.py::PLAIN_KINDS"}
    assert len(readers) >= 6, sorted(readers)

