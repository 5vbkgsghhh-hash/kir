"""Молча вставленный default превращает постусловие в требование, которого
вызывающий не выдвигал.

ОТКУДА ПРАВИЛО. 29.07 два фасадных прогона — 4 стены и 16 стен — откатились
целиком с «height mismatch» на КАЖДОЙ стене. Стены были построены верно.
Разбор: `height_mm` несёт registry-default 3000 мм, `_validate_op` кладёт его
в нормализованный оп ДО эмиттера, и эмиттер уже не может отличить «попросили
ровно 3000» от «промолчали, потому что высоту решает `top_level`». Фасадная
стена между двумя уровнями естественно опускает `height_mm` — а компилятор
обещал ровно 3000 и откатывал всё, что мерилось иначе.

ПРАВИЛО, КОТОРОЕ ИЗ ЭТОГО СЛЕДУЕТ. У параметра с молча вставляемым default
есть ровно два законных положения:

  ЭМИТТЕР ЕГО СТАВИТ — тогда постусловие законно: обещание дали мы, мы же его
  и держим. Так у `create_window.sill_mm`: точка вставки СЧИТАЕТСЯ как
  `__hl.Elevation + U(sill)`, и проверка сверяет ту же величину. Замерено, а
  не предположено — `authoring.py:2382` против `authoring.py:2532`;

  РЕШАЕТ REVIT — тогда постусловие на defaulted-значении требует того, чего
  никто не просил. Ровно случай высоты стены с привязанным верхом: Revit
  выводит её из пары уровней, а не из того, что передали в `Wall.Create`.

Различие не в типе параметра и не в его виде — в том, КТО назначает значение
в построенном элементе.

ЗАЧЕМ ЭТОТ ТЕСТ. Он не умеет проверить «ставит ли эмиттер» — это суждение.
Он делает другое: держит список молча вставляемых defaults ЗАКРЫТЫМ. Седьмой
не появится незаметно; чтобы его добавить, придётся прийти сюда и ответить на
вопрос выше словами. Замерено 31.07: шесть из двадцати. Остальные четырнадцать
в нормализованный оп НЕ попадают, и постусловия у них поэтому не срабатывают
на молчании вызывающего — в частности все флипы (`mirrored`, `hand_flipped`,
`facing_flipped`) у `create_door`, `create_window` и `place_family`. Живые
отказы дверей 21.07 пришли от вызывающего, который флипы НАЗВАЛ, — это другой
дефект, и путать их не следует.
"""
import unittest

from kukai.ir import compiler, spec

# Минимально валидный образец для каждого опа, у которого есть параметры с
# default. Не «типичный», а именно минимальный: default вставляется ровно
# тогда, когда вызывающий промолчал.
MINIMAL = {
    "create_column": {"op": "create_column", "id": "C", "xyz": [0, 0, 0],
                      "level": {"by": "name", "value": "L"},
                      "symbol": {"by": "name", "value": "S"}},
    "create_door": {"op": "create_door", "id": "D",
                    "host": {"by": "ref", "value": "W"}, "offset_mm": 1000},
    "create_floor": {"op": "create_floor", "id": "F", "p0_mm": [0, 0],
                     "p1_mm": [1000, 1000], "level": {"by": "name", "value": "L"}},
    "create_type": {"op": "create_type", "id": "T",
                    "base": {"by": "name", "value": "B"}, "name": "N",
                    "width_mm": 300, "depth_mm": 400},
    "create_wall": {"op": "create_wall", "id": "W", "p0_mm": [0, 0],
                    "p1_mm": [6000, 0], "level": {"by": "name", "value": "L"}},
    "create_window": {"op": "create_window", "id": "N",
                      "host": {"by": "ref", "value": "W"}, "offset_mm": 1000},
    "place_family": {"op": "place_family", "id": "P", "xyz": [0, 0, 0],
                     "level": {"by": "name", "value": "L"},
                     "symbol": {"by": "name", "value": "S"}},
    "query_list": {"op": "query_list", "id": "Q", "kind": "wall"},
}

# Замер 31.07. Каждая строка — обещание, которое компилятор даёт за
# вызывающего. Правая колонка отвечает на вопрос «кто назначает значение в
# построенном элементе».
SILENTLY_INJECTED = {
    ("create_wall", "height_mm"),      # Revit, если привязан верх → свидетель
                                       # снят под `top_level` (29.07)
    ("create_window", "sill_mm"),      # эмиттер: точка вставки считается из
                                       # него же → свидетель законен
    ("create_column", "category"),     # выбор перегрузки, не свойство элемента
    ("create_type", "category"),       # то же
    ("query_list", "fields"),          # чтение, элементов не строит
    ("query_list", "limit"),           # чтение
}


def _defaulted_params():
    out = []
    for name, ospec in spec.OPS.items():
        for p in ospec.params:
            if getattr(p, "default", None) is not None:
                out.append((name, p.name))
    return out


def _normalise(op_name):
    sample = MINIMAL[op_name]
    diags = []
    norm = compiler._validate_op(dict(sample), 0, diags)
    return norm, diags


class SilentDefaults(unittest.TestCase):
    def test_every_op_with_defaults_has_a_minimal_sample(self):
        """Иначе список закрыт не полностью, и новый оп проедет мимо."""
        missing = {op for op, _ in _defaulted_params()} - set(MINIMAL)
        self.assertEqual(missing, set(),
                         "у этих опов есть параметры с default, но нет "
                         "минимального образца — правило их не проверяет")

    def test_minimal_samples_actually_validate(self):
        for op_name in sorted({op for op, _ in _defaulted_params()}):
            with self.subTest(op=op_name):
                norm, diags = _normalise(op_name)
                self.assertIsNotNone(norm, f"образец {op_name} не прошёл "
                                           f"валидацию: {[d.code for d in diags]}")

    def test_injected_set_is_closed(self):
        """Список закрыт с ОБЕИХ сторон: новый молчаливый default обязан
        прийти сюда за ответом, а исчезнувший — не остаться в списке."""
        injected = set()
        for op_name, param in _defaulted_params():
            norm, _ = _normalise(op_name)
            if norm is not None and param in norm:
                injected.add((op_name, param))
        self.assertEqual(injected, SILENTLY_INJECTED)

    def test_flips_stay_absent_when_the_caller_is_silent(self):
        """Отдельно закреплено, потому что живые отказы дверей 21.07 читались
        как «default виноват», а он тут ни при чём: молчащий вызывающий флипов
        в нормализованном опе не получает, и постусловие не срабатывает."""
        for op_name in ("create_door", "create_window", "place_family"):
            norm, _ = _normalise(op_name)
            for flip in ("mirrored", "hand_flipped", "facing_flipped"):
                with self.subTest(op=op_name, param=flip):
                    self.assertNotIn(flip, norm)

    def test_explicit_value_survives_normalisation(self):
        """Обратный контроль: названное вызывающим не теряется и не
        подменяется — иначе правило выше проверяло бы пустоту."""
        op = dict(MINIMAL["create_wall"], height_mm=2700.0)
        norm, _ = compiler._validate_op(op, 0, []), None
        self.assertEqual(norm["height_mm"], 2700.0)
        op = dict(MINIMAL["create_door"], mirrored=True)
        norm = compiler._validate_op(op, 0, [])
        self.assertIs(norm["mirrored"], True)


if __name__ == "__main__":
    unittest.main()
