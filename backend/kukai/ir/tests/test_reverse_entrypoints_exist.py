"""Объявленная точка входа обратного хода обязана быть ДОСТИЖИМА.

ЗАМЕР 11.08.2026 (по коду, не по пересказу). `reverse_contract.py` объявляет
`create_group` составным (COMPOSED) и называет эмитирующую точку входа
`component_to_group_program`; валидация в том же файле ТРЕБУЕТ от составного
контракта назвать точку входа — контракт поставил себе условие и выполнил его
ИМЕНЕМ. Измерено:

    component_to_group_program — materialize.py:1315, экспортирована,
        вызывается ТОЛЬКО из тестов (test_materialize.py:1134,1140);
    place_group_ops — component.py:627, её ВХОД, вызывающих НОЛЬ вообще,
        даже в тестах: строить place_op некому;
    сама функция возвращает None, пока выключен native_group_enabled(),
        а tests/test_capability_map_wiring.py ОТДЕЛЬНО утверждает, что этот
        гейт мёртв, и падает, если он доложится подключённым;
    единственный производитель op-dict create_group на обратном ходе —
        native_group_op_to_ir, и зовут её ровно из этой недостижимой
        функции (materialize.py:1375).

То есть обратный ход СЕГОДНЯ не эмитирует create_group никогда.

ПОЧЕМУ ЭТО НАШ КЛАСС. Величина утверждается в одном месте (поле
`entrypoints`) и читается нигде. Стерегущий тест сверял СТРОКУ ИМЕНИ
(`assertEqual(contract.entrypoints, ("component_to_group_program",))`), то
есть подтверждал НАПИСАНИЕ имени, а не существование того, что имя называет.

ЧЕГО ЭТОТ ФАЙЛ НЕ РЕШАЕТ: он не переобъявляет режим. Верен ли для группы
COMPOSED или DECOMPOSED — вопрос о том, что обратный ход ОБЕЩАЕТ; он трогает
таксономию ReverseMode и территорию разбора. Замер приложен, решение за лидом.
Здесь закрыт разрыв между ИМЕНЕМ и ДОСТИЖИМОСТЬЮ, и он от режима не зависит.
"""
from __future__ import annotations

import ast
import os
import pathlib
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_entrypoint_queue.jsonl"))

from kukai.ir.reverse_contract import REVERSE_CONTRACTS  # noqa: E402

_BACKEND = pathlib.Path(__file__).resolve().parents[3]
_INDEX: dict | None = None

_ENTRYPOINTS_NAMED_IN_ADVANCE: dict[str, str] = {
    "component_to_group_program": (
        "склад native_group: функция возвращает None, пока гейт выключен, а "
        "её вход place_group_ops не зовёт НИКТО, даже тесты — питать её "
        "нечем. Потолок пути замерен: 7.52% листьев, сосредоточенных в двух "
        "зданиях из десяти, и библиотеку компонентов не строит никто. Это не "
        "«ещё не подключено», а «нечем питаться»"),
}


def _reference_index() -> dict:
    """Ссылки из ПРОДАКШНА на имя — ЛЮБОГО РОДА, не только вызов.

    ОПЛАЧЕНО ОШИБКОЙ ЭТОГО ЖЕ ФАЙЛА: первая редакция считала достижимостью
    литеральный ast.Call и объявила недостижимыми почти все `_lift_*`,
    которые диспетчеризуются ПО СТРОКЕ ИМЕНИ из таблицы `lift._CANDIDATES`.
    Канон предупреждает ровно об этом: ссылка на функцию КАК НА ЗНАЧЕНИЕ —
    это ребро, потому что здесь диспетчеризуют косвенно. Проба, требовавшая
    литерального вызова, совершила класс, ради которого написана.

    Считается ссылкой: вызов, имя как значение, строковый литерал таблицы.
    НЕ считается: сам файл объявления контракта — иначе контракт подтверждал
    бы себя своим же текстом, что и есть разбираемый дефект.
    """

    global _INDEX
    if _INDEX is not None:
        return _INDEX
    index: dict = {}
    for path in sorted(_BACKEND.rglob("*.py")):
        rel = str(path.relative_to(_BACKEND))
        if "/tests/" in rel or rel.startswith("tests/") or "test_" in path.name:
            continue
        if rel.endswith("reverse_contract.py"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        # `__all__` — ЭТО НЕ ССЫЛКА, А ОБЪЯВЛЕНИЕ. Модуль, экспортирующий имя,
        # им не пользуется; засчитать экспорт за достижимость значит вернуть
        # ровно тот дефект, который этот файл разбирает, — подтверждение
        # НАПИСАНИЯ имени вместо существования того, что имя называет.
        # Замерено на себе: без этого отсева component_to_group_program
        # «достижима» из materialize.py:1389, то есть из собственного __all__.
        exported = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "__all__"
                            for t in node.targets)):
                for el in ast.walk(node.value):
                    if isinstance(el, ast.Constant) and isinstance(el.value, str):
                        exported.add((el.value, el.lineno))
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Call):
                fn = node.func
                name = (fn.id if isinstance(fn, ast.Name)
                        else fn.attr if isinstance(fn, ast.Attribute) else None)
            elif isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if (node.value, node.lineno) in exported:
                    continue
                name = node.value
            if name:
                index.setdefault(name, []).append("%s:%d" % (rel, node.lineno))
    _INDEX = index
    return index


def _references(symbol: str) -> list:
    return list(_reference_index().get(symbol, ()))


class DeclaredEntrypointsMustExist(unittest.TestCase):

    def test_every_declared_entrypoint_is_reachable_or_named_in_advance(self):
        """СВЕРКА ДОСТИЖИМОСТИ, А НЕ СТРОКИ. Контракт, называющий выход,
        которого нет, обещает третье состояние обратного хода — названную
        расписку — не имея её."""
        for op_name, contract in sorted(REVERSE_CONTRACTS.items()):
            for entry in contract.entrypoints:
                with self.subTest(op=op_name, entrypoint=entry):
                    refs = _references(entry)
                    if refs:
                        self.assertNotIn(
                            entry, _ENTRYPOINTS_NAMED_IN_ADVANCE,
                            "%s: точка входа СТАЛА достижимой (%s) — запись "
                            "журнала аванса пережила свою правду"
                            % (entry, refs[:2]))
                        continue
                    self.assertIn(
                        entry, _ENTRYPOINTS_NAMED_IN_ADVANCE,
                        "%s объявляет точку входа %r, на которую в продакшне "
                        "нет НИ ОДНОЙ ссылки: контракт называет выход, "
                        "которого нет" % (op_name, entry))

    def test_the_advance_ledger_carries_a_reason_not_a_label(self):
        for entry, why in sorted(_ENTRYPOINTS_NAMED_IN_ADVANCE.items()):
            with self.subTest(entrypoint=entry):
                self.assertGreater(len(why), 60, entry)

    def test_the_ledger_names_only_declared_entrypoints(self):
        declared = {e for c in REVERSE_CONTRACTS.values() for e in c.entrypoints}
        for entry in sorted(_ENTRYPOINTS_NAMED_IN_ADVANCE):
            with self.subTest(entrypoint=entry):
                self.assertIn(entry, declared)

    def test_the_group_entrypoint_is_still_fed_by_nobody(self):
        """Вход точки входа: `place_group_ops` экспортирована публично и,
        кроме этого экспорта, не упоминается в продакшне НИГДЕ. Пока это так, составной путь группы не
        исполнится даже при включённом гейте."""
        self.assertEqual(_references("place_group_ops"), [])

    def test_the_indirect_dispatch_is_visible_to_this_instrument(self):
        """ЗАЩИТА ОТ ПОВТОРЕНИЯ СОБСТВЕННОЙ ОШИБКИ. `_lift_wall` не вызывают
        литерально — его имя лежит СТРОКОЙ в `lift._CANDIDATES`. Если прибор
        перестанет это видеть, он снова объявит живое мёртвым."""
        self.assertTrue(_references("_lift_wall"),
                        "прибор снова считает только литеральный вызов")


if __name__ == "__main__":
    print("named-in-advance:", sorted(_ENTRYPOINTS_NAMED_IN_ADVANCE))
    for _op, _c in sorted(REVERSE_CONTRACTS.items()):
        for _e in _c.entrypoints:
            print("%-26s %-30s refs=%s"
                  % (_op, _e, (_references(_e) or ["NONE"])[:2]))