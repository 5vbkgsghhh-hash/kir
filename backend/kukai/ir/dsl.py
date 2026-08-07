"""KIR как исходный язык: питон считает, IR доказывает.

    from kukai.ir import dsl
    from kukai.ir.dsl import *          # поверхность = реестр, целиком

    envelope(intent="комната 6×4 с дверью")
    lvl = create_level(elev_mm=0, name="Этаж 1")
    pts = [(0, 0), (6000, 0), (6000, 4000), (0, 4000)]
    walls = [create_wall(p0_mm=a, p1_mm=b, level=lvl, height_mm=3000)
             for a, b in zip(pts, pts[1:] + pts[:1])]
    create_door(host=walls[0], offset_mm=3000, symbol="Дверь 900x2100")
    prog = build()                      # ← обычный JSON KIR, больше ничего

`prog` идёт в `compiler.plan_program` БЕЗ послаблений. Питон здесь — только
фронт-энд: он не касается Revit, не знает про транзакции и не умеет выразить
того, чего нет в реестре. Радиус поражения ограничен IR, а не песочницей.

ЧЕМ ЭТОТ МОДУЛЬ ОТЛИЧАЕТСЯ ОТ `sdk.py`
--------------------------------------
`sdk.py` (29.07) уже рождает билдеры из реестра, и НИЧЕГО из этого здесь не
переписано заново там, где факт один: классификация видов параметров и
приведение numpy взяты у него по ссылке (`sdk.SELECTOR_KINDS`, `sdk._plain`,
`sdk.OMIT`), а тест `test_dsl.py` держит обе поверхности за одно имя реестра.

Разница — в четырёх вещах, каждая из которых меняет форму языка, а не удобство:

1. НАКОПЛЕНИЕ НЕЯВНОЕ. Вызов сам кладёт оп в текущую программу и возвращает
   РУЧКУ. В sdk вызов возвращает словарь, который автор обязан отдать в
   `p.add(...)`; скрипт читается как сборка билдера, а не как скрипт.
2. РУЧКА ЗНАЕТ, ССЫЛАЕМА ЛИ ОНА. `sdk.Program.add` возвращает `Ref` на ЛЮБОЙ
   оп — включая девять, у которых `ResultSpec.reference_kind is None`
   (`create_stairs`, `create_group`, `create_pipe_system`, `route_*`, `delete`,
   `set_param`, `change_type`, `set_curtain_panel`, `create_curtain_grid_line`,
   `move_elements`). Такой `Ref` доезжает до компилятора и получает KIR-L003
   через один-два слоя. Здесь ручка непереставляемого опа отказывает НА МЕСТЕ
   и называет причину из самого `ResultSpec`.
3. СЕЛЕКТОРЫ ПРИВОДЯТСЯ ПО СЛОТУ, А НЕ ОДНОЙ ФУНКЦИЕЙ. У `sel`, `target` и
   `target_w` РАЗНЫЕ допустимые формы (`target_w` не знает `by=name` вовсе —
   `authoring_validation._target_w_ok`), поэтому строка в слоте цели —
   невыразимая форма, а не «пусть компилятор разберётся»: приведение это
   сахар, и сахар обязан быть однозначным. Плюс `disambiguate_by`, который из
   питона до сих пор нельзя было написать иначе как словарём руками.
4. ИНТРОСПЕКЦИЯ НЕСЁТ ГРАНИЦЫ. `inspect.signature` показывает вид параметра и
   его пределы из `ParamSpec`, докстрока — постусловие опа и допуски свидетеля.
   Это ответ на «как модель узнаёт о том, чего не видит»: не отдельным ярусом
   документации, а родным для питона способом.

ЗАКОНЫ
------
* НИ ОДНОГО БИЛДЕРА НЕ НАПИСАНО РУКОЙ. Поверхность строится на импорте из
  `spec.OPS` фабрикой по `ParamSpec`. Новый оп в реестре — новая функция в тот
  же момент, без шага сборки и без файла, которому есть чем протухнуть.
* ИМЕНА ТОЧНО КАК В РЕЕСТРЕ. Ни сокращений, ни переименований: второй словарь
  имён — это второй источник правды. Выразительность берётся из питона.
* НИКАКОЙ СВОЕЙ СЕМАНТИКИ. Правда о корректности принадлежит компилятору.
  Модуль проверяет ровно то, без чего не собрать корректный JSON: имя опа
  (сигнатура), известность параметра (сигнатура), форму ручки и однозначность
  сахара. Всё остальное — `plan_program`.
"""

from __future__ import annotations

import inspect
from typing import Any

from kukai.ir import sdk, spec
from kukai.ir.compiler import BUDGET_INTERNAL_BULK, DEFAULTABLE, MAX_BULK_OPS
from kukai.ir.diag import (
    Diagnostic, GROUND_BAD_SELECTOR, KirRefusal, PARSE_DUP_ID,
    PARSE_MISSING_FIELD, PARSE_UNKNOWN_FIELD, PLAN_LIMIT, TYPE_BAD_TYPE,
)

__all__ = [
    "OMIT", "DEFAULT", "Handle", "Program", "DslRefusal",
    "by_name", "by_element_id", "by_default", "by_ref", "family_type",
    "disambiguate",
    "program", "current", "reset", "envelope", "ops", "build", "plan",
    "op_names", "selector_forms", "MAX_BULK_OPS",
]

#: Сентинелы берутся у `sdk`, а не заводятся свои: значение «поле не задано»
#: одно на весь питон-фронт, и скрипт, смешавший два модуля, не должен ловить
#: разные пропуски, которые печатаются одинаково.
OMIT = sdk.OMIT
DEFAULT = sdk.DEFAULT

#: numpy/tuple -> то, что переживает json.dumps. Факт один — берётся по ссылке.
_plain = sdk._plain


class _RegistryDefault:
    """Умолчание реестра в сигнатуре — ПОКАЗАТЬ, но не ВПИСАТЬ.

    Замер 03.08, из-за которого этот класс существует. Поле, вписанное в
    программу со значением умолчания, и поле, ОПУЩЕННОЕ, — это НЕ одно и то же
    для компилятора:

        omitted  -> FieldOrigin.REGISTRY_DEFAULT, plan_digest 2df7a3bc…
        explicit -> FieldOrigin.EXPLICIT,         plan_digest eb267955…

    То есть питон-фронт, materializing умолчания, (а) стирает провенанс —
    механизм, ради которого `midend.FieldOrigin` и написан, — и (б) меняет
    личность доказательства программы, ничего не изменив в здании. Поэтому
    здесь умолчание живёт в сигнатуре как ТЕКСТ (его видно в `help`), а в JSON
    не попадает, пока автор не назовёт его сам.
    """

    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value

    def __repr__(self) -> str:
        return repr(self.value)

    def __bool__(self) -> bool:
        return False

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, _RegistryDefault):
            return other.value == self.value
        return other == self.value          # страж дрейфа сравнивает с реестром

    def __hash__(self) -> int:
        return hash(("_RegistryDefault", repr(self.value)))


class DslRefusal(KirRefusal):
    """Отказ САМОГО языка, в словаре компилятора.

    Наследник `KirRefusal` намеренно: у вызывающего (песочница, скрипт,
    ремонтная петля) одна ветка обработки на все типизированные отказы KIR, и
    отказ фронт-энда не должен требовать второй. `diagnostics` — те же
    `Diagnostic` с `code`/`field_name`/`candidates`, а не текст.
    """


def _refuse(**kw: Any) -> "DslRefusal":
    return DslRefusal([Diagnostic(**kw)])


# ─────────────────────────────────────────────────────────────────── ручки

class Handle:
    """Адрес опа в программе — и, если реестр это разрешает, ссылка на него.

    Возвращается КАЖДЫМ вызовом. Ссылаемость — не свойство удобства, а
    типизированный контракт `ResultSpec`: у группы и у удалённого элемента
    свидетельство идентичности есть, а корректной ссылки вперёд не существует.
    Поэтому ручка непереставляемого опа существует (по ней читают `id`), но
    молча пройти как `{"by": "ref"}` не может.
    """

    __slots__ = ("id", "op", "_spec")

    def __init__(self, id: str, op: str, spec_: spec.OpSpec) -> None:  # noqa: A002
        self.id = id
        self.op = op
        self._spec = spec_

    # ── что о себе знает ────────────────────────────────────────────────
    @property
    def referenceable(self) -> bool:
        return self._spec.result.referenceable

    @property
    def reference_kind(self) -> spec.ReferenceKind | None:
        return self._spec.result.reference_kind

    @property
    def op_spec(self) -> spec.OpSpec:
        return self._spec

    def as_selector(self) -> dict:
        """`{"by": "ref", "value": id}` — или отказ с названной причиной."""
        if not self.referenceable:
            raise _refuse(
                code=TYPE_BAD_TYPE, op_id=self.id, field_name="by=ref",
                expected="оп с ResultSpec.reference_kind",
                got=f"{self.op} -> {self._unreferenceable_reason()}",
                message_ru=(
                    f"на «{self.op}» нельзя сослаться: {self._unreferenceable_reason()}. "
                    "Ссылку внутри программы даёт только оп, чей результат — "
                    "ОДНА идентичность с объявленным reference_kind; адресуй "
                    "такой элемент по element_id после исполнения"))
        return {"by": "ref", "value": self.id}

    def _unreferenceable_reason(self) -> str:
        result = self._spec.result
        card = result.identity_cardinality
        if card is spec.IdentityCardinality.NONE:
            return "результат не несёт идентичности вовсе (query)"
        if card is spec.IdentityCardinality.MANY:
            return (f"результат — МНОЖЕСТВО идентичностей "
                    f"({result.identity_field}), единичной ссылки не бывает")
        return (f"результат несёт идентичность ({result.identity_field}), но "
                "reference_kind не объявлен")

    # ── ЧЕГО РУЧКА НЕ УМЕЕТ — И ГОВОРИТ ОБ ЭТОМ САМА ────────────────────
    #
    # ЗАМЕР 04.08, второй по частоте класс отказа слабой модели (6 из 21):
    #
    #     wall_types = query_types(pool='wall_types')
    #     wall_type_ext = wall_types[0]['id']     ← TypeError: not subscriptable
    #     wall_types = list(query_types(...))     ← TypeError: not iterable
    #
    # Обе строки — самая естественная вещь на свете, и обе получали голый
    # питоновский тип без единого слова о том, КАК НАДО. Оба прогона начались
    # ровно с этого и потеряли по два хода до первой собравшейся программы.
    #
    # ПОЧЕМУ НЕ СДЕЛАТЬ ИХ РАБОЧИМИ. Потому что честной семантики нет: у
    # читающего опа результата НА МОМЕНТ ПИСЬМА ПРОГРАММЫ не существует вовсе
    # (`ResultSpec.identity_cardinality is NONE`, эффект READ) — он появится в
    # Revit при исполнении. `[0]` пришлось бы вернуть «первый попавшийся» тип,
    # то есть молча выбрать за автора; это ровно тот молчаливо-неверный
    # результат, который язык обязан делать невыразимым. Значит остаётся второй
    # путь, и он тоже назван законом: отказ обязан НАЗВАТЬ ПРАВИЛЬНУЮ ФОРМУ
    # ДОСЛОВНО.
    def _no_value(self, attempt: str) -> "DslRefusal":
        card = self._spec.result.identity_cardinality
        if self._spec.effect is spec.EffectKind.READ:
            what = (f"`{self.op}` — ЧИТАЮЩИЙ оп: его ответ появляется при "
                    f"исполнении в Revit, а в скрипте его нет вовсе")
            how = ("СЛЕДУЮЩИЙ ХОД — две честные формы, обе рабочие:\n"
                   "  • НЕ ЧИТАЯ: адресуй по ИМЕНИ (type=\"Наружная 300\") "
                   "либо оставь умолчание документа (type=DEFAULT) — выбор "
                   "будет НАЗВАН, а лестница умолчаний живёт в ground.py;\n"
                   "  • ЧИТАЯ: пошли программу, где этот оп стоит один — "
                   "{id, name} придут в КВИТАНЦИИ этого же хода, и следующая "
                   "программа поставит element_id.")
        elif card is spec.IdentityCardinality.MANY:
            what = (f"`{self.op}` создаёт МНОЖЕСТВО элементов, но в СКРИПТЕ их "
                    f"нет: они появятся при исполнении")
            how = ("СЛЕДУЮЩИЙ ХОД: адресуй их после исполнения по element_id "
                   "из квитанции — единичной ссылки на них не бывает.")
        else:
            what = (f"`{self.op}` возвращает ОДНУ ручку, а не список")
            how = ("СЛЕДУЮЩИЙ ХОД: передай ручку в слот целиком (level=lvl, "
                   "host=wall). Нужен список — собери его САМ, питоном: "
                   "walls = [create_wall(...) for a, b in пары].")
        return _refuse(
            code=TYPE_BAD_TYPE, op_id=self.id, field_name=attempt,
            expected="ручка = АДРЕС операции в программе",
            got=f"{attempt} у Handle({self.op})",
            message_ru=(f"{what}. Ручка — АДРЕС операции в программе, а не её "
                        f"результат, поэтому {attempt} тут невозможен.\n{how}"))

    def __getitem__(self, key: Any) -> Any:
        raise self._no_value(f"индекс [{key!r}]")

    def __iter__(self):
        # `list(handle)`/`for x in handle`/распаковка — все приходят сюда.
        raise self._no_value("перебор (for / list() / распаковка)")

    def __len__(self) -> int:
        raise self._no_value("len()")

    def __bool__(self) -> bool:
        # ЯВНО, И ЭТО НЕ ФОРМАЛЬНОСТЬ. Без `__bool__` истинность считалась бы
        # через `__len__` — то есть отказом. `if wall_types else None` слабая
        # модель написала уже на первом ходу (wB t01), и превращать проверку на
        # пустоту в аварию значит завести НОВУЮ ловушку на месте починенной.
        # Ручка существует всегда: она адрес, а не результат.
        return True

    def __repr__(self) -> str:
        kind = self.reference_kind.value if self.reference_kind else "НЕ ССЫЛКА"
        return f"Handle({self.id!r}, {self.op}, {kind})"

    def __eq__(self, other: Any) -> bool:
        return (isinstance(other, Handle) and other.id == self.id
                and other.op == self.op)

    def __hash__(self) -> int:
        return hash(("Handle", self.op, self.id))


# ────────────────────────────────────────────────────── формы селекторов

#: Виды параметров, которые в JSON выглядят как ОДИН селектор, и виды, которые
#: выглядят как СПИСОК селекторов. Классификация берётся у `sdk` — она там уже
#: есть и уже под стражем (`sdk.unclassified_kinds()`); второй такой список
#: разъехался бы ровно на новом виде параметра, то есть в самый неудачный
#: момент. Здесь эти множества только РАЗДЕЛЯЮТСЯ по допустимым формам.
_SELECTOR_KINDS = frozenset(sdk.SELECTOR_KINDS)
_SELECTOR_LIST_KINDS = frozenset(sdk.SELECTOR_LIST_KINDS)


def selector_forms(op_name: str, param_name: str) -> tuple[str, ...]:
    """Какие формы `by=` принимает ЭТОТ слот ЭТОГО опа.

    Выводится из `ParamSpec.kind` и `ref_kinds`, то есть из реестра, — кроме
    одного: `family_type` живёт только у `place_family.symbol`. Этот факт
    сегодня записан ТРИЖДЫ (здесь, `schema_gen._op_schema`,
    `authoring_validation.validate`), потому что реестр его не носит; ему место
    во флаге `ParamSpec`, и до тех пор строчка ниже — сознательный повтор, а не
    недосмотр.
    """
    ospec = spec.OPS[op_name]
    p = next(p for p in ospec.params if p.name == param_name)
    return _forms(ospec, p)


def _forms(ospec: spec.OpSpec, p: spec.ParamSpec) -> tuple[str, ...]:
    if p.kind == "sel":
        forms = ["name", "element_id", "default"]
        if ospec.name == "place_family" and p.name == "symbol":
            forms.append("family_type")
        if p.ref_kinds:
            forms.append("ref")
        return tuple(forms)
    if p.kind == "target":
        # query_inspect: имя допустимо, но требует `kind` рядом (compiler.py).
        return ("element_id", "name")
    if p.kind in ("target_w", "refs_w", "targets_w"):
        # _target_w_ok: ПРИШПИЛЕННЫЙ id либо ссылка внутри программы. Имени тут
        # нет и быть не может — цель записи разрешается до эмиссии, а не в C#.
        return ("element_id", "ref") if p.ref_kinds else ("element_id",)
    raise AssertionError(f"{ospec.name}.{p.name}: вид {p.kind!r} не селектор")


#: Поля, которыми оп ИМЕНУЕТ то, что создаёт. Нужны отказу, чтобы совет
#: «сошлись по имени» называл КОНКРЕТНОЕ поле, а не жанр.
_NAMING_FIELDS: tuple[str, ...] = ("new_name", "name")


def _by_name_next_move(ospec: spec.OpSpec, p: spec.ParamSpec,
                       handle: "Handle") -> str:
    """СЛЕДУЮЩИЙ ХОД для ручки, попавшей в слот без формы `ref`.

    ЗАМЕР 04.08 (прогон wB, ходы 5 и 11): отказ был КОРРЕКТЕН — он называл
    формы слота, — но совет вёл в яму. Модель читала «слот принимает
    name/element_id/default», а имени в снимке ещё нет: и тип, и уровень
    создаёт ЭТА ЖЕ пачка. Правильный ответ — «сошлись по имени, которое ты сам
    только что дал», и он проверен планом, а не выведен:
        create_type(new_name='Наружная 300') + create_wall(type='Наружная 300')
        -> plan_program принял 3 опа.
    Для `create_stairs` к этому добавляется правило пачки: оп СОЛО (KIR-L002),
    значит уровень приходит из соседнего звена и только по имени.
    """
    produced = handle.op_spec
    named = next((f.name for f in produced.params
                  if f.name in _NAMING_FIELDS), None)
    if ospec.name in spec.SOLO_OPS:
        return (f"СЛЕДУЮЩИЙ ХОД — ФОРМА ПАЧКИ, а не ссылка: `{ospec.name}` "
                f"обязан быть ЕДИНСТВЕННЫМ опом своей программы (KIR-L002, "
                f"StairsEditScope владеет своими транзакциями). Значит здание "
                f"— это ПАЧКА: тело отдельно, лестница отдельно. Уровень "
                f"создаёт программа тела, а лестничная видит его ПО ИМЕНИ: "
                f"{p.name}=\"Этаж 1\". Вердикт бери у ПАЧКИ целиком — "
                f"design_check([тело, лестница]), — иначе он осудит звено "
                f"вместо здания.")
    if named:
        return (f"СЛЕДУЮЩИЙ ХОД: ты создаёшь это опом `{handle.op}` (id "
                f"«{handle.id}») в этой же программе — сошлись на него ПО "
                f"ИМЕНИ, которое сам ему дал в `{named}`: "
                f"{p.name}=\"<{named} этого опа>\". Имя разрешается при "
                f"исполнении, когда оп уже отработал, поэтому порядок опов "
                f"внутри программы это чинит, а ссылка — нет.")
    return (f"СЛЕДУЮЩИЙ ХОД: этот слот адресуется каталогом (name/element_id), "
            f"а не соседним опом. Возьми имя типа из `query_types` либо оставь "
            f"умолчание документа ({p.name}=DEFAULT).")


def _selector_error(ospec: spec.OpSpec, p: spec.ParamSpec, value: Any,
                    reason: str, next_move: str = "") -> DslRefusal:
    forms = _forms(ospec, p)
    hints = {
        "name": 'строка -> {"by":"name"}',
        "element_id": 'целое -> {"by":"element_id"}',
        "default": 'DEFAULT/by_default() -> {"by":"default"}',
        "ref": "ручка соседнего опа -> {\"by\":\"ref\"}",
        "family_type": "family_type(category, family_name, type_name)",
    }
    message = (f"{ospec.name}.{p.name}: {reason}. Слот принимает "
               f"{list(forms)}; словарь-селектор всегда можно написать "
               f"явно ({', '.join(hints[f] for f in forms)})")
    if next_move:
        message += "\n" + next_move
    return _refuse(
        code=GROUND_BAD_SELECTOR, field_name=p.name,
        expected=list(forms), got=repr(value), candidates=[hints[f] for f in forms],
        message_ru=message)


def _coerce_selector(ospec: spec.OpSpec, p: spec.ParamSpec, value: Any) -> Any:
    """Питон-значение -> селектор. САХАР, а не второй словарь.

    Явная форма (готовый dict) проходит НЕТРОНУТОЙ — её судит компилятор.
    Сахар отказывает только там, где формы просто не существует: приведение,
    которое не может быть однозначным, лучше не делать вовсе.
    """
    forms = _forms(ospec, p)
    if isinstance(value, dict):
        return _plain(value)                     # автор сказал явно — не трогаем
    if isinstance(value, Handle):
        if "ref" not in forms:
            raise _selector_error(
                ospec, p, value,
                "ссылка внутри программы этому слоту не разрешена "
                "типизированным контрактом параметра (ref_kinds пуст)",
                _by_name_next_move(ospec, p, value))
        return value.as_selector()               # сам откажет, если не ссылаем
    if isinstance(value, sdk.Ref):               # взаимность с sdk-скриптами
        if "ref" not in forms:
            raise _selector_error(ospec, p, value, "ref этому слоту не разрешён")
        return {"by": "ref", "value": value.id}
    if value is DEFAULT:
        if "default" not in forms:
            raise _selector_error(ospec, p, value,
                                  "у этого слота нет формы by=default")
        return {"by": "default"}
    if isinstance(value, bool):
        raise _selector_error(ospec, p, value, "bool — не адрес элемента")
    if isinstance(value, int):
        if "element_id" not in forms:            # сегодня недостижимо; не молчим
            raise _selector_error(ospec, p, value, "у слота нет формы element_id")
        return {"by": "element_id", "value": int(value)}
    if isinstance(value, str):
        if "name" not in forms:
            raise _selector_error(
                ospec, p, value,
                "у этого слота НЕТ формы by=name — цель записи адресуется "
                "element_id или ссылкой на соседний оп")
        return {"by": "name", "value": value}
    raise _selector_error(ospec, p, value, "не селектор")


# ── явные формы (сахар необязателен; disambiguate_by живёт только здесь) ──

def disambiguate(param: str, value: Any) -> dict:
    """`disambiguate_by` — сужение по параметру.

    Проверяется ДАЖЕ когда кандидат остался один (`ground.py`): иначе «дай
    Ø100» молча получил бы Ø200, и снаружи это неотличимо от успеха.
    """
    return {"param": param, "value": _plain(value)}


def by_name(value: str, *, kind: str | None = None,
            disambiguate_by: dict | None = None) -> dict:
    """`{"by": "name"}`. `kind` нужен там, где язык требует назвать вид
    элемента вместе с именем (`query_inspect.target`)."""
    out: dict[str, Any] = {"by": "name", "value": value}
    if kind is not None:
        out["kind"] = kind
    if disambiguate_by is not None:
        out["disambiguate_by"] = dict(disambiguate_by)
    return out


def by_element_id(value: int) -> dict:
    """`{"by": "element_id"}` — пришпилено; существование проверит гард в C#."""
    return {"by": "element_id", "value": int(value)}


def by_default(*, disambiguate_by: dict | None = None) -> dict:
    """`{"by": "default"}` — лестница `ground.py`: умолчание документа,
    единственный в пуле, НАЗВАННОЕ умолчание most_used, иначе отказ."""
    out: dict[str, Any] = {"by": "default"}
    if disambiguate_by is not None:
        out["disambiguate_by"] = dict(disambiguate_by)
    return out


def by_ref(target: Any) -> dict:
    """`{"by": "ref"}` из ручки, `sdk.Ref` или id-строки."""
    if isinstance(target, Handle):
        return target.as_selector()
    if isinstance(target, sdk.Ref):
        return {"by": "ref", "value": target.id}
    if isinstance(target, str):
        return {"by": "ref", "value": target}
    raise _refuse(code=TYPE_BAD_TYPE, field_name="by=ref", got=repr(target),
                  expected="Handle | sdk.Ref | str",
                  message_ru="ссылка строится из ручки опа или его id")


def family_type(category: str, family_name: str, type_name: str) -> dict:
    """Каталожный селектор: категория + семейство + тип, ровно одно совпадение."""
    return {"by": "family_type", "category": category,
            "family_name": family_name, "type_name": type_name}


# ───────────────────────────────────────── интроспекция: типы и границы

class _Ann:
    """Аннотация-текст. `inspect` печатает не-типы через `repr`, поэтому вид
    параметра и его границы видны прямо в сигнатуре, а не только в докстроке."""

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:
        return self.text

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, _Ann) and other.text == self.text

    def __hash__(self) -> int:
        return hash(("_Ann", self.text))


def _bounds(p: spec.ParamSpec) -> str:
    if p.min_val is None and p.max_val is None:
        return ""
    lo = "" if p.min_val is None else f"{p.min_val:g}"
    hi = "" if p.max_val is None else f"{p.max_val:g}"
    return f" {lo}..{hi}"


def _annotation(ospec: spec.OpSpec, p: spec.ParamSpec) -> _Ann:
    if p.kind in _SELECTOR_KINDS or p.kind in _SELECTOR_LIST_KINDS:
        forms = "|".join(_forms(ospec, p))
        refs = ("(" + ",".join(k.value for k in p.ref_kinds) + ")"
                if p.ref_kinds else "")
        listed = "[]" if p.kind in _SELECTOR_LIST_KINDS else ""
        return _Ann(f"{p.kind}{listed}: {forms}{refs}")
    if p.kind == "enum":
        return _Ann("enum{" + "|".join(map(str, p.choices)) + "}")
    if p.kind in ("mm", "num", "int", "deg"):
        return _Ann(f"{p.kind}{_bounds(p)}")
    if p.kind in ("str", "str_long"):
        cap = p.max_val if p.max_val is not None else 64
        return _Ann(f"{p.kind}<={cap}")
    return _Ann(p.kind)


def _return_annotation(ospec: spec.OpSpec) -> _Ann:
    if ospec.result.referenceable:
        return _Ann(f"Handle[ссылка «{ospec.result.reference_kind.value}»]")
    return _Ann("Handle[НЕ ссылка: by=ref этим опом не производится]")


def _docstring(ospec: spec.OpSpec) -> str:
    result = ospec.result
    if result.referenceable:
        result_line = (f"одна идентичность ({result.identity_field}); НА НЕЁ "
                       f"МОЖНО СОСЛАТЬСЯ как «{result.reference_kind.value}»")
    elif result.identity_cardinality is spec.IdentityCardinality.NONE:
        result_line = "идентичности нет (чтение)"
    elif result.identity_cardinality is spec.IdentityCardinality.MANY:
        result_line = (f"МНОЖЕСТВО идентичностей ({result.identity_field}); "
                       "ссылки внутри программы не даёт")
    else:
        result_line = (f"одна идентичность ({result.identity_field}), но "
                       "reference_kind не объявлен — ссылки не даёт")

    lines = [
        f"`{ospec.name}` — {ospec.family}, эффект {ospec.effect.value}"
        f"{', ПИШЕТ В МОДЕЛЬ' if ospec.writes_model else ''}.",
        "",
        f"Результат: {result_line}.",
        "",
        "ПОСТУСЛОВИЕ (контракт опа; проверяется свидетелем в транзакции):",
        f"    {ospec.post}",
        "",
        "Параметры — из реестра (kukai/ir/ops_*.py), не из этого файла:",
    ]
    grounded = {name: pool for name, pool, _req in ospec.grounded}
    width = max((len(p.name) for p in ospec.params), default=0)
    for p in ospec.params:
        bits = [str(_annotation(ospec, p))]
        bits.append("ОБЯЗАТЕЛЬНЫЙ" if p.required else "необязательный")
        if p.default is not None:
            bits.append(f"умолчание {p.default!r}")
        if p.name in grounded:
            bits.append(f"заземляется по пулу «{grounded[p.name]}»")
        lines.append(f"    {p.name:<{width}}  {'; '.join(bits)}")
    if not ospec.params:
        lines.append("    (нет)")
    if ospec.tolerances:
        lines += ["", "Допуски свидетеля (реестр — единственный их источник):"]
        lines += [f"    {k} = {v:g}" for k, v in sorted(ospec.tolerances.items())]
    lines += [
        "",
        "Вызов кладёт оп в текущую программу и возвращает ручку; `id` можно",
        "задать явно, иначе он выдаётся детерминированно.",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────── фабрика: поверхность из реестра

def _call_form(ospec: spec.OpSpec) -> str:
    """ВСЕ слоты опа одной справкой — то, чего стоил замер 04.08.

    Считано по 27 отказам двух прогонов слабой модели: 13 из них (самый частый
    класс, вдвое больше следующего) — голый питоновский `TypeError` от
    `Signature.bind`, «missing a required argument: 'variety'». Он верен и
    бесполезен: он называет ОДИН слот из шести и молчит о том, что `variety` —
    enum из двух значений. Модель узнавала сигнатуру ПО ОДНОМУ БИТУ ЗА ХОД:
    прогон wB, ходы 4-15 — одиннадцать подряд, missing → unexpected → missing.
    Поэтому отказ печатает форму ЦЕЛИКОМ: один ход вместо одиннадцати.
    """
    required = [p for p in ospec.params if p.required]
    optional = [p for p in ospec.params if not p.required]
    head = ", ".join([p.name for p in required]
                     + (["*"] if optional else [])
                     + [f"{p.name}=…" for p in optional] + ["id=…"])
    rows = [f"    {ospec.name}({head})"]
    width = max((len(p.name) for p in ospec.params), default=0)
    if required:
        rows.append("  ОБЯЗАТЕЛЬНЫЕ:")
        rows += [f"    {p.name:<{width}}  {_annotation(ospec, p)}"
                 for p in required]
    if optional:
        rows.append("  НЕОБЯЗАТЕЛЬНЫЕ (без них оп законен):")
        for p in optional:
            row = f"    {p.name:<{width}}  {_annotation(ospec, p)}"
            if p.default is not None:
                row += f"; умолчание {p.default!r} (ВПИШЕТ РЕЕСТР, не ты)"
            rows.append(row)
    return "\n".join(rows)


#: ОТВЕТ НА ОСТАТОК КЛАССА, ЗАМЕРЕННЫЙ НА ПОЧИНЕННОЙ ПОВЕРХНОСТИ.
#:
#: Отказ печатает форму ОДНОГО опа — того, на котором скрипт сорвался. Дальше
#: он сорвётся на следующем незнакомом, и в прогоне 04.08 после починки это
#: видно прямо: ход 2 — `create_opening.variety`, ход 3 — `create_railing.variety`.
#: Один оп за ход вместо одного слота за ход — лучше, но не даром.
#:
#: Докстрока каждой функции языка собрана из реестра (`_docstring`) и доступна
#: ПРЯМО В СКРИПТЕ: `print(create_railing.__doc__)`. Ни в описании инструмента,
#: ни в курсе этого не сказано НИГДЕ — способность была тёмной. Проверено
#: исполнением в песочнице: печатается полный список слотов с видами,
#: границами и постусловием, в квитанцию ТОГО ЖЕ хода.
_DOC_HINT = ("ФОРМУ ЛЮБОГО ОПА МОЖНО ПРОЧЕСТЬ ДО ВЫЗОВА, не тратя ход: "
             "print(<имя_опа>.__doc__) — слоты, виды, границы и постусловие "
             "придут в квитанцию этого же хода. Незнакомые опы дешевле "
             "распечатать разом, чем узнавать по одному отказу за ход.")


def _bind_refusal(ospec: spec.OpSpec, exc: TypeError,
                  args: tuple, kwargs: dict) -> DslRefusal:
    """Голый `TypeError` от `Signature.bind` -> типизированный отказ KIR.

    ЗАКОН (лид, 04.08): отказ обязан называть СЛЕДУЮЩИЙ ХОД, а не только
    диагноз. Эталон — KIR-L001 в `Program._append`: бюджет, виновник, что
    делать. Здесь то же: чего не хватило, что лишнее, и ВСЯ форма вызова —
    чтобы следующий ход закрывал все слоты сразу, а не один.
    """
    known = {p.name for p in ospec.params} | {"id"}
    required = [p.name for p in ospec.params if p.required]
    unexpected = [k for k in kwargs if k not in known]
    filled = set(required[:len(args)]) | set(kwargs)
    missing = [n for n in required if n not in filled]
    form = _call_form(ospec)
    given = ", ".join(sorted(kwargs)) or "(ни одного именованного)"
    if len(args) > len(required):
        given += f"; позиционных {len(args)} при {len(required)} обязательных"

    if unexpected:
        return _refuse(
            code=PARSE_UNKNOWN_FIELD, field_name=unexpected[0],
            expected=sorted(known), got=unexpected,
            candidates=sorted(known),
            message_ru=(
                f"`{ospec.name}`: слота {', '.join(repr(u) for u in unexpected)}"
                f" у этого опа НЕТ. Поверхность языка — это реестр целиком, "
                f"и лишнее поле не отбрасывается молча: оно значит, что ты "
                f"держишь в голове другой оп.\n{form}\n"
                f"СЛЕДУЮЩИЙ ХОД: убери лишнее либо возьми имя из списка выше "
                f"(размеры почти везде идут с суффиксом `_mm`), и СРАЗУ сверь "
                f"остальные слоты — они все перечислены здесь.\n{_DOC_HINT}"))
    if missing:
        return _refuse(
            code=PARSE_MISSING_FIELD, field_name=missing[0],
            expected=required, got=given, candidates=missing,
            message_ru=(
                f"`{ospec.name}`: не задан ОБЯЗАТЕЛЬНЫЙ слот "
                f"{', '.join('`' + m + '`' for m in missing)}. "
                f"Умолчания у него нет намеренно — угаданный за автора выбор "
                f"неотличим снаружи от названного.\n{form}\n"
                f"Ты передал: {given}.\n"
                f"СЛЕДУЮЩИЙ ХОД: допиши недостающее и СРАЗУ сверь остальные "
                f"слоты по списку выше — второй такой отказ стоит ещё хода."
                f"\n{_DOC_HINT}"))
    return _refuse(
        code=TYPE_BAD_TYPE, field_name="(вызов)", expected=required, got=given,
        message_ru=(f"`{ospec.name}`: вызов не сходится с формой опа "
                    f"({exc}).\n{form}\n"
                    f"Ты передал: {given}.\n"
                    f"СЛЕДУЮЩИЙ ХОД: передавай слоты ПО ИМЕНИ — необязательные "
                    f"иначе позиционно не принимаются вовсе."))


def _make_op_fn(ospec: spec.OpSpec):
    P = inspect.Parameter
    # Реестр перемежает обязательные и необязательные, питон — не умеет:
    # параметр без умолчания не может стоять после параметра с умолчанием.
    # Поэтому в сигнатуре обязательные идут первыми (как в sdk.py), а В JSON
    # поля пишутся В ПОРЯДКЕ РЕЕСТРА — программу читают глазами.
    params = [P(p.name, P.POSITIONAL_OR_KEYWORD,
                annotation=_annotation(ospec, p))
              for p in ospec.params if p.required]
    params += [P(p.name, P.KEYWORD_ONLY,
                 default=(OMIT if p.default is None
                          else _RegistryDefault(p.default)),
                 annotation=_annotation(ospec, p))
               for p in ospec.params if not p.required]
    # `id` — не параметр реестра, а АДРЕС опа: по нему на оп ссылаются соседи.
    params.append(P("id", P.KEYWORD_ONLY, default=OMIT,
                    annotation=_Ann("str<=64 (иначе выдаётся сам)")))
    sig = inspect.Signature(params, return_annotation=_return_annotation(ospec))

    def op_fn(*args: Any, **kwargs: Any) -> Handle:
        try:
            bound = sig.bind(*args, **kwargs)
        except TypeError as exc:
            # Голый `TypeError` отсюда уходил модели как есть — см. `_bind_refusal`.
            raise _bind_refusal(ospec, exc, args, kwargs) from None
        bound.apply_defaults()
        oid = bound.arguments.pop("id")
        payload: dict[str, Any] = {}
        for p in ospec.params:                 # ПОРЯДОК РЕЕСТРА
            value = bound.arguments[p.name]
            if value is OMIT or value is None or isinstance(
                    value, _RegistryDefault):
                continue
            payload[p.name] = _coerce(ospec, p, value)
        return current()._append(ospec, payload, oid)

    op_fn.__name__ = ospec.name
    op_fn.__qualname__ = ospec.name
    op_fn.__module__ = __name__
    op_fn.__signature__ = sig
    op_fn.__doc__ = _docstring(ospec)
    op_fn.op_spec = ospec
    return op_fn


def _coerce(ospec: spec.OpSpec, p: spec.ParamSpec, value: Any) -> Any:
    if p.kind in _SELECTOR_KINDS:
        return _coerce_selector(ospec, p, value)
    if p.kind in _SELECTOR_LIST_KINDS:
        if not isinstance(value, (list, tuple)):
            raise _selector_error(ospec, p, value, "ожидается СПИСОК адресов")
        return [_coerce_selector(ospec, p, item) for item in value]
    return _plain(value)


#: Поверхность языка. Ровно столько функций, сколько опов в реестре, всегда.
OP_FUNCTIONS: dict[str, Any] = {name: _make_op_fn(ospec)
                                for name, ospec in sorted(spec.OPS.items())}
globals().update(OP_FUNCTIONS)
__all__ += sorted(OP_FUNCTIONS)


def op_names(*, writes: bool | None = None) -> list[str]:
    """Имена опов реестра; `writes=True` — только пишущие в модель."""
    return sorted(n for n, o in spec.OPS.items()
                  if writes is None or o.writes_model is writes)


# ───────────────────────────────────────────────────────────── программа

class Program:
    """Одна программа KIR: конверт, опы, ручки.

    Накопление НЕЯВНОЕ: опы попадают сюда из вызовов, а не из `add(...)`.
    Программа — не всё здание: предел v1 — ВНУТРЕННИЙ bulk-бюджет
    (`MAX_BULK_OPS`), и превышение — типизированный отказ, а не молчаливая
    обрезка.
    """

    def __init__(self, *, intent: str | None = None,
                 allow_destructive: bool | None = None,
                 defaults: dict | None = None) -> None:
        self.intent = intent
        self.allow_destructive = allow_destructive
        self.defaults = dict(defaults) if defaults else None
        self.ops: list[dict] = []
        self._seq: dict[str, int] = {}
        self._ids: set[str] = set()
        self._previous: "Program | None" = None

    # ── накопление ──────────────────────────────────────────────────────
    def _next_id(self, op_name: str) -> str:
        # Та же схема, что у `sdk._OpSink._next_id`: программа, собранная двумя
        # питон-фронтами, обязана получать ОДНИ и те же адреса, иначе «то же
        # самое» перестаёт быть проверяемым сравнением.
        n = self._seq.get(op_name, 0) + 1
        self._seq[op_name] = n
        stem = op_name[7:] if op_name.startswith("create_") else op_name
        return f"{stem}{n}"

    def _census(self, top: int = 6) -> str:
        """Что успело собраться, по родам. Строка для ОТКАЗА, не для отчёта."""
        tally: dict[str, int] = {}
        for op in self.ops:
            name = op.get("op", "?")
            tally[name] = tally.get(name, 0) + 1
        ordered = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
        shown = ", ".join(f"{name} {count}" for name, count in ordered[:top])
        if len(ordered) > top:
            shown += f", и ещё {len(ordered) - top} родов"
        return shown

    def _append(self, ospec: spec.OpSpec, payload: dict, oid: Any) -> Handle:
        if len(self.ops) >= MAX_BULK_OPS:
            # Д-7, ЗАМЕР 03.08. Отказ приходил БЕЗ ЕДИНСТВЕННОГО числа, ради
            # которого его читают: сколько успело собраться и из чего. Печать
            # итогов, которую курс велит ставить в конец скрипта, при ЭТОМ
            # отказе не выполняется ВООБЩЕ — скрипт снят на операции №301, — и
            # `stdout` квитанции приходит пустым. Значит перепись обязана ехать
            # В САМОМ ОТКАЗЕ: иначе модель узнаёт, что упёрлась, но не узнаёт,
            # где именно резать, и следующий ход начинает с нуля вслепую.
            raise _refuse(
                code=PLAN_LIMIT, field_name="ops", expected=f"<={MAX_BULK_OPS}",
                got=len(self.ops) + 1,
                message_ru=(
                    f"исчерпан ВНУТРЕННИЙ bulk-бюджет ({BUDGET_INTERNAL_BULK}) "
                    f"— {MAX_BULK_OPS} опов на программу. Это ЧЕСТНАЯ граница "
                    "v1, а не предел эмиттера: чанкование прямого хода ещё не "
                    "написано (на обратном оно есть — "
                    "decompile/materialize.py). Пока — режь на несколько "
                    "программ САМ, в питоне, и это следующая работа.\n"
                    f"СОБРАНО ДО ОТКАЗА: {len(self.ops)} операций — "
                    f"{self._census()}. Наружу не выйдет НИ ОДНА: отказ "
                    f"песочницы обнуляет ход целиком, и печать в конце скрипта "
                    f"тоже не выполнилась. Режь по этим числам"))
        if oid is OMIT or oid is None:
            oid = self._next_id(ospec.name)
        elif not isinstance(oid, str) or not (1 <= len(oid) <= 64):
            raise _refuse(code=TYPE_BAD_TYPE, field_name="id", got=repr(oid),
                          expected="строка 1..64 символа",
                          message_ru="id опа — строка 1..64 символа")
        if oid in self._ids:
            raise _refuse(
                code=PARSE_DUP_ID, op_id=oid, field_name="id", got=oid,
                candidates=sorted(self._ids),
                message_ru=(f"id «{oid}» в этой программе уже занят: ручка — "
                            "адрес, и одинаковые адреса молча перевязали бы "
                            "ссылки на чужой оп"))
        self._ids.add(oid)
        # `op` и `id` впереди: программу читают глазами чаще, чем парсером.
        self.ops.append({"op": ospec.name, "id": oid, **payload})
        return Handle(oid, ospec.name, ospec)

    # ── конверт ─────────────────────────────────────────────────────────
    def envelope(self, *, intent: Any = OMIT, allow_destructive: Any = OMIT,
                 defaults: Any = OMIT) -> "Program":
        """Поля конверта — те же, что у JSON, других нет (`ir_version` ставит
        сам реестр)."""
        if intent is not OMIT:
            self.intent = intent
        if allow_destructive is not OMIT:
            self.allow_destructive = allow_destructive
        if defaults is not OMIT:
            self.defaults = dict(defaults) if defaults else None
        return self

    def _defaults_json(self) -> dict:
        """Селекторы на всю программу. Приводятся тем же сахаром, но по
        каталогу `_defaults_schema` — конверт не привязан к одному опу."""
        out = {}
        for key, value in (self.defaults or {}).items():
            if isinstance(value, dict) or value is None:
                out[key] = _plain(value)
            elif isinstance(value, Handle):
                out[key] = value.as_selector()
            elif isinstance(value, sdk.Ref):
                out[key] = {"by": "ref", "value": value.id}
            elif value is DEFAULT:
                out[key] = {"by": "default"}
            elif isinstance(value, bool):
                raise _refuse(code=GROUND_BAD_SELECTOR, field_name="defaults",
                              got=repr(value), candidates=list(DEFAULTABLE),
                              message_ru="bool — не адрес элемента")
            elif isinstance(value, int):
                out[key] = {"by": "element_id", "value": int(value)}
            elif isinstance(value, str):
                out[key] = {"by": "name", "value": value}
            else:
                raise _refuse(code=GROUND_BAD_SELECTOR, field_name="defaults",
                              got=repr(value), candidates=list(DEFAULTABLE),
                              message_ru=f"defaults.{key} — не селектор")
        return out

    # ── выход ───────────────────────────────────────────────────────────
    def build(self) -> dict:
        """РОВНО тот JSON, который принимает компилятор. Не обёртка, не свой
        порядок, не свои поля."""
        out: dict[str, Any] = {"ir_version": spec.IR_VERSION}
        if self.intent is not None:
            out["intent"] = self.intent
        if self.allow_destructive is not None:
            out["allow_destructive"] = bool(self.allow_destructive)
        if self.defaults:
            out["defaults"] = self._defaults_json()
        out["ops"] = [dict(op) for op in self.ops]
        return out

    def plan(self, *, bulk: bool = True):
        """`compiler.plan_program` — ЕДИНСТВЕННЫЙ семантический вход вниз.

        `bulk=True` по умолчанию, и это следствие того, ЧТО здесь авторская
        единица. Авторский бюджет (20) меряет программу, НАПИСАННУЮ моделью;
        программу, которую написал питон, он не меряет — как не меряет чанк
        материализатора. Авторская вещь тут — скрипт, и её размер бюджетом
        опов не выражается вовсе. Кто хочет мерить выход DSL авторским
        бюджетом, зовёт `plan(bulk=False)` и получает тот же отказ, что чат.
        """
        from kukai.ir.compiler import plan_program
        return plan_program(self.build(), bulk=bulk)

    # ── контекст ────────────────────────────────────────────────────────
    def __enter__(self) -> "Program":
        return self

    def __exit__(self, *exc: Any) -> bool:
        global _CURRENT
        if _CURRENT is self and self._previous is not None:
            _CURRENT = self._previous
        return False

    def __len__(self) -> int:
        return len(self.ops)

    def __iter__(self):
        return iter(self.ops)

    def __repr__(self) -> str:
        return f"Program({len(self.ops)} опов, intent={self.intent!r})"


#: Текущая программа модуля. Живёт в модуле, а не в объекте, ровно затем, чтобы
#: скрипт читался как скрипт.
#:
#: ЧЕГО ЭТО СТОИТ, СКАЗАНО ПРЯМО: модульное состояние НЕ потокобезопасно и не
#: изолирует два скрипта, крутящихся в одном интерпретаторе, — они допишут друг
#: другу опы. Замок здесь ничего бы не починил (переплетение вызовов остаётся
#: переплетением) и только выдал бы ложное спокойствие. Изоляция скриптов —
#: свойство ПЕСОЧНИЦЫ (свежий интерпретатор на скрипт); внутри одного процесса
#: её дают `reset()` и `with program(...)`, и на неё есть тест.
_CURRENT = Program()


def current() -> Program:
    """Программа, в которую сейчас копятся вызовы."""
    return _CURRENT


def reset(**envelope_kw: Any) -> Program:
    """Начать новую пустую программу. Возвращает её."""
    global _CURRENT
    _CURRENT = Program(**envelope_kw)
    return _CURRENT


def program(*, intent: str | None = None,
            allow_destructive: bool | None = None,
            defaults: dict | None = None) -> Program:
    """Явная программа. Делается текущей СРАЗУ, поэтому работает и так:

        with program(intent="этаж"):
            create_wall(...)

    и так:

        p = program(intent="этаж")
        create_wall(...)
        prog = p.build()

    В форме `with` прежняя программа возвращается на место по выходу.
    """
    global _CURRENT
    fresh = Program(intent=intent, allow_destructive=allow_destructive,
                    defaults=defaults)
    fresh._previous = _CURRENT
    _CURRENT = fresh
    return fresh


def envelope(*, intent: Any = OMIT, allow_destructive: Any = OMIT,
             defaults: Any = OMIT) -> Program:
    """Конверт текущей программы."""
    return current().envelope(intent=intent,
                              allow_destructive=allow_destructive,
                              defaults=defaults)


def ops() -> list[dict]:
    """Опы текущей программы, как они уйдут в JSON."""
    return [dict(op) for op in current().ops]


def build() -> dict:
    """JSON текущей программы."""
    return current().build()


def plan(*, bulk: bool = True):
    """`plan_program` над текущей программой."""
    return current().plan(bulk=bulk)


def take_ops() -> dict | None:
    """ДВЕРЬ ПЕСОЧНИЦЫ, а не автора. Забрать накопленное и обнулить.

    `sandbox.py` опрашивает язык этим именем ПЕРВЫМ (`_DRAIN_CANDIDATES`) и
    умеет конверт: словарь с ключом `ops` разбирается на `intent`/`defaults`/
    `allow_destructive` плюс сами опы. Поэтому здесь отдаётся `build()`
    целиком — иначе конверт, выставленный скриптом, потерялся бы молча.

    ПУСТО — значит `None`, а НЕ пустой конверт. Договор песочницы допускает и
    второй путь: скрипт кладёт готовый список в переменную `ops`. Если бы drain
    возвращал истинное значение при нуле накопленного, он забрал бы этот путь
    себе и переменная скрипта не сработала бы никогда.

    Обнуление здесь — не уборка, а изоляция: два скрипта в одном интерпретаторе
    не должны видеть опы друг друга (см. комментарий у `_CURRENT`).

    В `__all__` НЕ входит намеренно: песочница зовёт его через модуль, а автору
    скрипта сливать собственную программу незачем — забирает её она.
    """
    prog = current()
    if not prog.ops:
        return None
    out = prog.build()
    reset()
    return out
