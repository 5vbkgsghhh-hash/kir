"""Питон-поверхность языка обязана быть ЯЗЫКОМ, а не его пересказом.

SDK опасен ровно одним: он выглядит как язык, но им не является. Стоит написать
билдер рукой — и он живёт до первой правки реестра, после чего врёт молча:
обещает поле, которого больше нет, или молчит о появившемся, а программа
собирается и отказывается уже у пользователя. Поэтому здесь проверяется не
«удобно ли», а два свойства:

* билдеры РОЖДЕНЫ из `spec.OPS` — каждый оп реестра имеет функцию, её сигнатура
  совпадает с `ParamSpec` по именам и обязательности, и новый оп получает
  и билдер, и этот тест автоматически;
* SDK не завёл своей семантики — он не умеет выразить того, чего нет в реестре,
  ничего не проверяет сам и не прячет отказ.

Плюс два демо-примера: они обязаны компилироваться офлайн, иначе «фантастика»
в отчёте — это картинка, а не факт.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import pathlib

import pytest

from kukai.ir import macros, sdk, spec
from kukai.ir.compiler import DEFAULTABLE, MAX_OPS_PER_PROGRAM
from kukai.ir.diag import Diagnostic
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT

BACKEND = pathlib.Path(__file__).resolve().parents[3]
EXAMPLES = BACKEND / "tools" / "design" / "examples"

WRITE_OPS = sorted(n for n, o in spec.OPS.items() if o.writes_model)
ALL_OPS = sorted(spec.OPS)


# ── билдеры рождены из реестра ───────────────────────────────────────────────

@pytest.mark.parametrize("name", ALL_OPS)
def test_every_op_of_the_registry_has_a_builder(name):
    """Параметризация по реестру, а не по списку: новый оп приносит свой тест
    сам, и «забыли добавить в SDK» перестаёт быть возможным состоянием."""
    fn = getattr(sdk, name, None)
    assert callable(fn), f"нет билдера для {name}"
    assert fn.op_spec is spec.OPS[name], "билдер держит ЧУЖУЮ спецификацию"


@pytest.mark.parametrize("name", WRITE_OPS)
def test_every_write_op_builds_its_own_op_dict(name):
    """Для каждого пишущего опа билдер зовётся с обязательными полями и отдаёт
    словарь ровно этого опа."""
    ospec = spec.OPS[name]
    args = {p.name: _sample(p) for p in ospec.params if p.required}
    out = getattr(sdk, name)(**args)
    assert out["op"] == name
    assert set(out) - {"op", "id"} <= {p.name for p in ospec.params}
    for p in ospec.params:
        if p.required:
            assert p.name in out, f"{name}: обязательное {p.name} потерялось"


@pytest.mark.parametrize("name", ALL_OPS)
def test_the_signature_never_drifts_from_the_paramspec(name):
    """Дрейф-страж. Имена и обязательность — из `ParamSpec`, и только оттуда:
    расхождение здесь означает, что питон обещает не тот язык."""
    ospec = spec.OPS[name]
    sig = inspect.signature(getattr(sdk, name))
    got = [p for p in sig.parameters if p != "id"]
    # Реестр перемежает обязательные и необязательные (`create_floor`:
    # outline, holes, level, ...), а питон не разрешает параметру без
    # умолчания стоять после параметра с умолчанием. Поэтому сравнивается не
    # общий порядок, а порядок ВНУТРИ каждой группы: переименование,
    # появление и пропажа поля ловятся так же, а невыразимого порядка от
    # питона не требуется.
    want = ([p.name for p in ospec.params if p.required]
            + [p.name for p in ospec.params if not p.required])
    assert got == want, f"{name}: набор/порядок полей"
    assert "id" in sig.parameters, f"{name}: у опа обязан быть адрес"

    required = {p.name for p in ospec.params if p.required}
    for pname, param in sig.parameters.items():
        if pname == "id":
            continue
        has_default = param.default is not inspect.Parameter.empty
        assert has_default is (pname not in required), \
            f"{name}.{pname}: обязательность разошлась с реестром"


@pytest.mark.parametrize("name", ALL_OPS)
def test_registry_defaults_are_the_python_defaults(name):
    """«Умолчания из ParamSpec» — буквально: значение берётся из реестра на
    импорте, поэтому разъехаться ему негде."""
    sig = inspect.signature(getattr(sdk, name))
    for p in spec.OPS[name].params:
        if p.required or p.default is None:
            continue
        assert sig.parameters[p.name].default == p.default, p.name


def test_there_are_exactly_as_many_builders_as_ops():
    assert set(sdk.builders()) == set(spec.OPS)
    assert sdk.op_names(writes=True) == WRITE_OPS


#: Правдоподобное значение по виду параметра — тесту нужна ФОРМА, а не
#: осмысленное здание; смысл проверяет компилятор в тестах ниже.
_SAMPLES: dict = {
    "pt_xy": [0.0, 0.0], "pt_xyz": [0.0, 0.0, 0.0], "pt_view2d": [0.0, 0.0],
    "pts": [[0.0, 0.0], [1000.0, 0.0]],
    "pts_list": [[[0.0, 0.0], [1000.0, 0.0]]],
    # `path` (wave/arch) — ОТКРЫТАЯ ломаная: две точки законны, площадь не
    # требуется. Тем и отличается от "pts" выше.
    "path": [[0.0, 0.0], [3000.0, 0.0]],
    # `path3` (wave/mep-electrical) — та же открытая ломаная, но с Z: гибкая
    # подводка идёт с этажа к потолку, и двумерного образца ей мало.
    "path3": [[0.0, 0.0, 3000.0], [3000.0, 0.0, 2700.0]],
    "mm": 1000.0, "num": 1000.0, "deg": 0.0, "int": 1, "bool": True,
    "str": "имя", "str_long": "текст",
    "sel": "Этаж 1", "target": 42, "target_w": 42,
    # `sel_list` (wave/datums) — множественное число рода `sel`. Образец из
    # ДВУХ РАЗНЫХ имён намеренно: одно имя не отличило бы список от
    # одиночного селектора, а два ОДИНАКОВЫХ упёрлись бы в закон «повтор в
    # множестве — отказ» (authoring_validation) и тест ловил бы не то.
    "sel_list": ["Этаж 1", "Этаж 2"],
    "refs_w": [42, 43], "targets_w": [42, 43], "value": "значение",
    "vec3_mm": [100.0, 0.0, 0.0],
    "arc": {"curve_type": "Arc", "center_mm": [0, 0, 0], "radius_mm": 5000.0,
            "x_axis": [1, 0, 0], "y_axis": [0, 1, 0]},
    # `spiral` (09.08) — винтовой марш create_stairs. Образец обязан быть
    # ЗАКОННЫМ целиком: радиус больше полуширины любого допустимого марша
    # (width_mm <= 5000 => radius > 2500), угол в (0, 360].
    "spiral": {"center_mm": [0.0, 0.0], "radius_mm": 3000.0,
               "start_angle_deg": 0.0, "included_angle_deg": 180.0,
               "clockwise": False},
    "kind_enum": "wall", "filters": {}, "fields": ["id"],
    "enum": None,                      # берётся из choices самого параметра
    "region": {"outer": {"shape": "poly",
                         "points_mm": [[0, 0], [1000, 0], [1000, 1000]]}},
    "member_ops": [{"op": "create_level", "id": "m1", "elev_mm": 0}],
    "placements": [[0, 0, 0]],
    "graph_nodes": [{"id": "n1", "xyz_mm": [0, 0, 0]}],
    "graph_segments": [{"from": "n1", "to": "n2"}],
    "slopes": [{"edge": 0, "angle_deg": 30}],
    # `mesh` (wave/shape) — тетраэдр: наименьший меш, проходящий ВСЕ законы
    # формы (связный, без вырожденных граней, без висячих вершин). Образец
    # обязан быть законным целиком: тест берёт его как форму значения, но
    # соседние тесты гоняют им компилятор.
    "mesh": {"vertices_mm": [[0.0, 0.0, 0.0], [3000.0, 0.0, 0.0],
                             [1500.0, 2600.0, 0.0], [1500.0, 900.0, 2400.0]],
             "triangles": [[0, 1, 2], [0, 1, 3], [1, 2, 3], [0, 2, 3]]},
    # `pts_xyz` (wave/site) — облако точек рельефа. Образец обязан быть
    # законным ЦЕЛИКОМ, как и меш выше: соседние тесты гоняют им компилятор.
    # Поэтому здесь четыре точки, ни одна пара которых не совпадает в плане
    # (у рельефа в одной точке плана ровно одна земля) и которые не лежат на
    # одной прямой (поверхность нулевой площади — типизированный отказ).
    "pts_xyz": [[0.0, 0.0, 0.0], [10000.0, 0.0, 500.0],
                [10000.0, 8000.0, 900.0], [0.0, 8000.0, 200.0]],
}


#: Роды, у которых образец — ЧИСЛО и потому обязан уложиться в границы ЭТОГО
#: параметра, а не только иметь верный тип.
_NUMERIC_KINDS = ("mm", "num", "int", "deg")


def _sample(p: spec.ParamSpec):
    """Образец значения ЭТОГО параметра — законный целиком, а не по роду.

    Найдено волной solid 09.08: образец рода `num` — 1000.0, а `sweep_deg`
    живёт в 1..360, и корпус получал программу, которую компилятор законно
    отказывал (KIR-T002). Прибор при этом сообщал не «у оператора узкие
    границы», а «оп не строит JSON, который принимает планировщик», то есть
    указывал ремонт НЕ ТУДА. Отсечка по границам самого параметра лечит это
    для всякого будущего опа, а не для одного.
    """
    if p.kind == "enum":
        return (p.choices or ("x",))[0]
    value = _SAMPLES[p.kind]
    if p.kind in _NUMERIC_KINDS and None not in (p.min_val, p.max_val):
        clamped = min(max(float(value), float(p.min_val)), float(p.max_val))
        return int(clamped) if p.kind == "int" else clamped
    return value


def test_every_param_kind_of_the_registry_is_classified_by_the_sdk():
    """Найдено этим тестом 28.07: параллельная волна принесла `move_elements` с
    видами `targets_w`/`vec3_mm`, и `targets` — список селекторов — молча
    поехал бы мимо приведения. Неизвестный вид не ломает ничего (проходит как
    есть), и именно поэтому его нельзя оставлять незамеченным."""
    assert sdk.unclassified_kinds() == []


def test_every_param_kind_of_the_registry_has_a_sample():
    """Иначе новый вид параметра тихо получал бы строку "x" и проходил бы
    проверку формы, ничего не проверив: тест, который нельзя не заметить при
    расширении языка, лучше теста, который сам себя обманывает."""
    kinds = {p.kind for o in spec.OPS.values() for p in o.params}
    assert not sorted(kinds - set(_SAMPLES)), "новый вид параметра без образца"


# ── никакой новой семантики ──────────────────────────────────────────────────

def test_the_sdk_cannot_name_an_op_the_registry_does_not_have():
    assert not hasattr(sdk, "create_teleporter")
    with pytest.raises(AttributeError):
        sdk.create_teleporter()  # noqa: B018


def test_an_unknown_field_is_refused_by_the_signature():
    """Отказ приходит из реестра (через сигнатуру), а не из проверки, которую
    SDK завёл бы себе сам."""
    with pytest.raises(TypeError):
        sdk.create_wall([0, 0], [1000, 0], "Этаж 1", nonexistent_field=1)


def test_a_missing_required_field_is_refused_by_the_signature():
    with pytest.raises(TypeError):
        sdk.create_wall([0, 0], [1000, 0])


def test_the_sdk_validates_nothing_that_the_compiler_validates():
    """Заведомо неверная программа обязана дойти ДО компилятора и получить его
    диагностику. SDK, который отказал бы раньше и по-своему, — второй диалект."""
    p = sdk.program()
    p.add(sdk.create_wall([0, 0], [1000, 0], "Этаж 1", height_mm=-5))
    out = p.compile(version="2023", snapshot=GROUND_SNAPSHOT)
    assert out.ok is False
    assert out.diagnostics and isinstance(out.diagnostics[0], Diagnostic)
    assert out.diagnostics[0].code.startswith("KIR-")


def test_diagnostics_come_back_as_objects_not_text():
    """Скрипт, который чинит сам себя, читает `code` и `candidates`, а не
    парсит сообщение."""
    p = sdk.program()
    p.add(sdk.create_wall([0, 0], [1000, 0], "нет такого уровня"))
    out = p.compile(version="2023", snapshot=GROUND_SNAPSHOT)
    assert out.ok is False
    d = out.diagnostics[0]
    assert hasattr(d, "code") and hasattr(d, "candidates")


# ── эргономика без семантики ─────────────────────────────────────────────────

def test_selectors_accept_what_python_has_at_hand():
    assert sdk.sel("Этаж 1") == {"by": "name", "value": "Этаж 1"}
    assert sdk.sel(1679) == {"by": "element_id", "value": 1679}
    assert sdk.sel(sdk.Ref("L1")) == {"by": "ref", "value": "L1"}
    assert sdk.sel(sdk.DEFAULT) == {"by": "default"}
    assert sdk.sel({"by": "name", "value": "x"}) == {"by": "name", "value": "x"}
    assert sdk.sel("Стена", kind="wall")["kind"] == "wall"
    with pytest.raises(TypeError):
        sdk.sel(True)


def test_a_ref_from_add_wires_ops_together():
    """Дверь адресует свою стену ссылкой на соседний оп — это и есть польза от
    того, что `add` возвращает `Ref`, а не заставляет держать id в голове."""
    p = sdk.program()
    wall = p.add(sdk.create_wall([0, 0], [6000, 0], "Этаж 1", type="Кирпич 250"))
    door = p.add(sdk.create_door(host=wall, offset_mm=3000,
                                 symbol="Дверь 900x2100"))
    assert isinstance(wall, sdk.Ref) and isinstance(door, sdk.Ref)
    assert p.ops[1]["host"] == {"by": "ref", "value": wall.id}
    assert p.compile(version="2023", snapshot=GROUND_SNAPSHOT).ok


def test_numpy_values_survive_into_json():
    """Без этого разъём не работает вовсе: вся затея в том, чтобы координаты
    считались numpy, а `np.float64` не сериализуется."""
    np = pytest.importorskip("numpy")
    p = sdk.program()
    p.add(sdk.create_column(xy=np.array([1234.5, 6789.0]), level="Этаж 1"))
    text = p.to_json()
    assert "1234.5" in text
    assert json.loads(text)["ops"][0]["xy"] == [1234.5, 6789.0]


def test_auto_ids_are_deterministic_and_unique():
    p = sdk.program()
    for _ in range(3):
        p.add(sdk.create_wall([0, 0], [1000, 0], "Этаж 1"))
    ids = [o["id"] for o in p.ops]
    assert ids == ["wall1", "wall2", "wall3"]
    assert len(set(ids)) == 3


def test_an_explicit_id_is_never_overwritten():
    p = sdk.program()
    p.add(sdk.create_wall([0, 0], [1000, 0], "Этаж 1", id="мой"))
    assert p.ops[0]["id"] == "мой"


def test_omitted_optional_fields_do_not_appear():
    out = sdk.create_wall([0, 0], [1000, 0], "Этаж 1", type=sdk.OMIT)
    assert "type" not in out
    assert "arc" not in out


def test_by_macro_omits_a_field_the_macro_owns():
    """Шов двух верных правил: реестр требует `level`, `macros.py` запрещает его
    внутри `stack.floor`. Питон обязан дать сказать «это назначит макрос»."""
    out = sdk.create_column(xy=[0, 0], level=sdk.BY_MACRO)
    assert "level" not in out


# ── программа ────────────────────────────────────────────────────────────────

def test_to_dict_is_exactly_the_compilers_json():
    p = sdk.program(intent="проба", defaults={"level": "Этаж 1"})
    p.add(sdk.create_wall([0, 0], [6000, 0], "Этаж 1", type="Кирпич 250"))
    d = p.to_dict()
    assert d["ir_version"] == spec.IR_VERSION
    assert set(d) <= {"ir_version", "intent", "allow_destructive", "ops", "defaults"}
    assert d["defaults"] == {"level": {"by": "name", "value": "Этаж 1"}}
    assert p.compile(version="2023", snapshot=GROUND_SNAPSHOT).ok


def test_envelope_defaults_only_carry_what_the_compiler_accepts():
    """SDK не расширяет конверт: список умолчаний принадлежит компилятору."""
    p = sdk.program(defaults={"nonsense": "x"})
    p.add(sdk.create_wall([0, 0], [1000, 0], "Этаж 1"))
    out = p.compile(version="2023", snapshot=GROUND_SNAPSHOT)
    assert out.ok is False
    assert any(d.field_name == "defaults" for d in out.diagnostics)
    assert set(DEFAULTABLE) == {"level", "symbol", "type", "top_level"}


def test_stats_tell_written_expanded_and_elements_apart():
    """Три числа, а не одно: в одном растворяется то, ради чего язык и нужен."""
    p = sdk.program()
    with p.stack(levels=10, h_mm=3000) as floor:
        floor.add(sdk.create_column(xy=[0, 0], level=sdk.BY_MACRO,
                                    symbol="К 300x300"))
    st = p.stats()
    assert st["ops_written"] == 1
    assert st["ops_expanded"] == 20        # 10 уровней + 10 колонн
    assert st["elements"] == 10            # уровень — не элемент модели


def test_a_program_is_one_program_not_a_whole_building():
    """Пачка программ — свойство языка, а не недоделка SDK: 20 авторских опов
    до экспансии, и SDK этого не прячет."""
    p = sdk.program()
    for _ in range(MAX_OPS_PER_PROGRAM + 1):
        p.add(sdk.create_wall([0, 0], [1000, 0], "Этаж 1"))
    out = p.compile(version="2023", snapshot=GROUND_SNAPSHOT)
    assert out.ok is False
    assert any(d.code == "KIR-L001" for d in out.diagnostics)


def test_compile_all_covers_every_shipped_version():
    p = sdk.program()
    p.add(sdk.create_wall([0, 0], [6000, 0], "Этаж 1", type="Кирпич 250"))
    got = p.compile_all(snapshot=GROUND_SNAPSHOT)
    assert set(got) == set(spec.REVIT_VERSIONS)
    assert all(out.ok for out in got.values())


def test_grid_array_reaches_the_macro_layer():
    p = sdk.program()
    p.grid_array(nx=4, ny=3, dx_mm=6000, dy_mm=4500, prefix_y="А")
    assert p.stats()["ops_expanded"] == 7
    assert p.compile(version="2023", snapshot=GROUND_SNAPSHOT).ok


def test_the_macro_field_names_do_not_drift():
    """Макросы живут не в `spec.OPS`, поэтому их поля здесь названы руками — и
    ровно поэтому нужен страж: полный набор полей обязан пройти экспансию, а
    не получить KIR-M001 «неизвестное поле макроса»."""
    p = sdk.program()
    with p.stack(levels=2, h_mm=3000, base_elev_mm=0, name_prefix="Э",
                 transform=sdk.transform(scale_xy_top=[0.9, 0.9],
                                         twist_deg_total=10,
                                         offset_mm_top=[100, 0],
                                         pivot_mm=[0, 0])) as floor:
        floor.add(sdk.create_column(xy=[0, 0], level=sdk.BY_MACRO))
    p.grid_array(nx=2, ny=2, dx_mm=6000, dy_mm=6000, origin_mm=[0, 0],
                 margin_mm=1000, prefix_x="", prefix_y="А")
    expanded = macros.expand(list(p.ops))          # не должен бросить KirRefusal
    assert len(expanded) == 8


def test_the_stack_floor_is_a_separate_sink():
    """В этаж нельзя случайно доложить оп программы и наоборот."""
    p = sdk.program()
    with p.stack(levels=2, h_mm=3000) as floor:
        floor.add(sdk.create_column(xy=[0, 0], level=sdk.BY_MACRO))
    p.add(sdk.create_level(elev_mm=9000, name="Тех"))
    assert len(p.ops) == 2
    assert p.ops[0]["op"] == "stack" and len(p.ops[0]["floor"]) == 1


# ── демо-примеры компилируются офлайн ────────────────────────────────────────

def _load(name: str):
    spec_ = importlib.util.spec_from_file_location(name, EXAMPLES / f"{name}.py")
    mod = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("name", ["tower_numpy", "contour_shapely"])
def test_the_examples_compile_offline_on_every_version(name):
    """«Фантастика» в отчёте обязана быть фактом: пример строит программы и все
    они принимаются компилятором на всех шести версиях, без сети и без Revit."""
    pytest.importorskip("numpy")
    if name == "contour_shapely":
        pytest.importorskip("shapely")
    mod = _load(name)
    programs = mod.build(mod.slab_outline()[0]) if name == "contour_shapely" \
        else mod.build()
    assert programs
    for p in programs:
        for version, out in p.compile_all(snapshot=GROUND_SNAPSHOT).items():
            assert out.ok, (name, version,
                            [d.code for d in out.diagnostics][:3])


@pytest.mark.parametrize("name", ["tower_numpy", "contour_shapely"])
def test_the_examples_stay_within_a_hundred_lines(name):
    text = (EXAMPLES / f"{name}.py").read_text("utf-8")
    assert len(text.splitlines()) <= 100


def test_the_tower_says_more_with_less():
    """Смысл разъёма — в отношении: написанных опов должно быть НАМНОГО меньше,
    чем элементов. Если отношение схлопнется, пример перестанет быть примером."""
    mod = _load("tower_numpy")
    st = [p.stats() for p in mod.build()]
    written = sum(x["ops_written"] for x in st)
    elements = sum(x["elements"] for x in st)
    assert elements >= 50 * written, (written, elements)


def test_a_built_program_is_byte_identical_to_the_hand_written_json():
    """Сильнейшая форма «никакой новой семантики»: SDK выдаёт РОВНО тот JSON,
    который написали бы руками, — не свою обёртку, не свой порядок, не свои
    поля."""
    p = sdk.program(intent="стена")
    p.add(sdk.create_wall([0, 0], [6000, 0], "Этаж 1", type="Кирпич 250",
                          id="w1"))
    assert p.to_dict() == {
        "ir_version": "1.0",
        "intent": "стена",
        "ops": [{"op": "create_wall", "id": "w1",
                 "p0_mm": [0, 0], "p1_mm": [6000, 0],
                 "level": {"by": "name", "value": "Этаж 1"},
                 "height_mm": 3000.0,
                 "type": {"by": "name", "value": "Кирпич 250"}}],
    }


def test_the_registry_default_is_emitted_and_means_the_same_thing():
    """`height_mm` приходит в JSON из реестра, а не выдуман SDK, — и программа
    с ним компилируется в тот же C#, что и программа без него."""
    explicit = sdk.program()
    explicit.add(sdk.create_wall([0, 0], [6000, 0], "Этаж 1", type="Кирпич 250"))
    omitted = sdk.program()
    omitted.add(sdk.create_wall([0, 0], [6000, 0], "Этаж 1", type="Кирпич 250",
                                height_mm=sdk.OMIT))
    assert explicit.ops[0]["height_mm"] == spec.OPS["create_wall"].params[3].default
    assert "height_mm" not in omitted.ops[0]
    a = explicit.compile(version="2023", snapshot=GROUND_SNAPSHOT)
    b = omitted.compile(version="2023", snapshot=GROUND_SNAPSHOT)
    assert a.ok and b.ok and a.csharp == b.csharp


def test_a_list_of_selectors_is_coerced_element_by_element():
    """`move_elements.targets` — список адресов; питон обязан принимать в нём то
    же, что и в одиночном селекторе."""
    out = sdk.move_elements(targets=[42, sdk.Ref("w1")], delta_mm=[100, 0, 0])
    assert out["targets"] == [{"by": "element_id", "value": 42},
                              {"by": "ref", "value": "w1"}]
