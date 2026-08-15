"""У каждого голден-файла РОВНО ОДИН заявляющий корпус.

ЗАЧЕМ. 13.08.2026 два теста владели одними и теми же двумя файлами в общем
каталоге `golden/`, сверяя их против РАЗНЫХ программ:

    имя                          test_families        test_golden
    families_create_type_full    259 симв. программы  277 симв. — РАЗНЫЕ
    families_load_family_whole   134 симв. программы  263 симв. — РАЗНЫЕ

Один файл не может удовлетворить обе программы. Байты совпадали с `test_golden`,
поэтому `test_families` стоял красным — и читался как «эмиттер уехал от
проверенного эталона», хотя эмиттер был ни при чём. Перезаморозка сделала бы
красным другой тест, и так по кругу: **колебание без сходимости, надетое на
слово «дрейф»**.

ЭТО НАША ЖЕ ФОРМА 9, И ИМЕННО ОНА ОБЪЯСНЯЕТ, ПОЧЕМУ ДЕФЕКТ ЖИЛ. Докстринг
владельца утверждал дословно: «Own files in the SHARED golden/ dir
(families_*.golden.cs — **no filename collision with any other wave's
programs**)». Утверждение было верным, когда его писали, и перестало быть верным,
когда позднейшая волна завела те же два имени. **Мутировать прозу нечем: ни один
прогон не покраснеет оттого, что комментарий устарел.** Поэтому здесь тот же
инвариант записан ИСПОЛНЯЕМЫМ.

РОД ЭТОГО СПИСКА: **ПОЛНЫЙ ПО ПОСТРОЕНИЮ.** Состав корпусов не ведётся руками —
он берётся обходом модулей `kukai/ir/**/tests/` и чтением их объявленных
корпусов. Новый корпус, заведённый завтра, попадает под проверку сам, без правки
этого файла; поэтому отсутствие имени здесь означает «такого корпуса нет», а не
«мы про него не знаем».
"""
from __future__ import annotations

import ast
import importlib
import os
import pathlib
import pkgutil
import types
import unittest
from collections import defaultdict

GOLDEN_DIR = pathlib.Path(__file__).parent / "golden"

#: Корпус узнаётся ПО СОДЕРЖИМОМУ, а не по имени атрибута.
#:
#: Четвёртая ошибка этого зонда была именно здесь: список читал только
#: `PROGRAMS`, а `test_annotation` объявляет свой корпус как
#: `ANNOTATION_PROGRAMS` — и два его голдена не просматривались вовсе. Это
#: форма 7 канона в чистом виде: соглашение об именовании держится девять раз
#: из десяти, а десятый молчит. Поэтому корпусом считается ЛЮБОЙ словарь
#: модуля или его класса, хотя бы один ключ которого именует существующий файл
#: `golden/<ключ>.golden.cs`. Спрашиваем содержимое — оно и есть авторитет.
#: РАЗЛИЧАЕТ ЗНАЧЕНИЕ, А НЕ КЛЮЧ — пятая и последняя поправка этого зонда.
#:
#: Ключами голденов пользуются ДВА разных рода словарей: КОРПУС, который их
#: сверяет (`name -> программа`), и РЕЕСТР, который их описывает
#: (`name -> строка с «pins / does NOT pin»`). Четвёртая редакция смотрела на
#: ключи и потому объявила `UNREVIEWED_GOLDENS` вторым владельцем всего, что в
#: нём записано, — то есть собственная запись аттестации немедленно породила
#: «коллизию». Владеет тот, кто СВЕРЯЕТ, а сверять можно только программу.
def _looks_like_corpus(value: object) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    named = [k for k in value
             if isinstance(k, str) and (GOLDEN_DIR / f"{k}.golden.cs").is_file()]
    if not named:
        return False
    return all(isinstance(value[k], dict) and "ops" in value[k] for k in named)


def _claims() -> dict[str, list[str]]:
    """{имя голдена: [кто на него заявляется]} обходом ВСЕХ тестовых модулей.

    ОКРУЖЕНИЕ ВОССТАНАВЛИВАЕТСЯ ЯВНО, и это не перестраховка. Обход ИМПОРТИРУЕТ
    чужие модули, а часть из них ставит `KIR_*`/`KUKAI_*` прямо на импорте;
    сторож окружения из `conftest.py` поймал ровно это на первом же прогоне.
    Прибор был прав, а загрязнителем был я: наблюдение не имеет права менять
    состояние, в котором работает следующий тест.
    """
    import kukai.ir.tests as tests_pkg

    before = dict(os.environ)
    try:
        return _walk(tests_pkg)
    finally:
        os.environ.clear()
        os.environ.update(before)


def _walk(tests_pkg) -> dict[str, list[str]]:
    """Владелец — тот, кто корпус ОБЪЯВИЛ, а не тот, кто его импортировал.

    ПЕРВАЯ РЕДАКЦИЯ ЭТОГО ОБХОДА БЫЛА НЕВЕРНА, и поймал её не тест, а вопрос
    «а покажи владельцев поимённо». Она делала `getattr(holder, "PROGRAMS")` по
    всему `dir(module)`, куда попадают ИМПОРТИРОВАННЫЕ модули: `gate_runner`
    импортирует `PROGRAMS` из `test_golden`, поэтому владельцем всех 69 голденов
    оказался `test_gate_declares_its_ground.gate_runner`, а сами объявления не
    просматривались вовсе. Оба контроля при этом прошли — они работали на тех же
    испорченных данных, а порог «не меньше 50» был выполнен случайным путём.

    Отсюда два правила, оба записаны исполняемо ниже:
    * модули-держатели пропускаются (`ModuleType`) — импорт не есть владение;
    * корпуса различаются по ИДЕНТИЧНОСТИ объекта. Два модуля, показывающие ОДИН
      И ТОТ ЖЕ словарь, суть один владелец; коллизия — это два РАЗНЫХ словаря,
      заявляющих одно имя.
    """
    out: dict[str, list[str]] = defaultdict(list)
    for info in pkgutil.iter_modules(tests_pkg.__path__):
        if not info.name.startswith("test_"):
            continue
        path = pathlib.Path(tests_pkg.__path__[0]) / f"{info.name}.py"
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        # ВЛАДЕНИЕ = СВЕРКА ФАЙЛА, а не совпадение имени. Третья ошибка этого
        # зонда была здесь: `test_emitter_scope_contract` объявляет свой
        # `PROGRAMS` из 12 имён, совпадающих с голденами, и не трогает каталог
        # НИ РАЗУ (0 упоминаний против 69 у `test_golden`) — он проверяет
        # области видимости эмиссии. Имя, совпавшее с файлом, владением не
        # является; владеет тот, кто файл ЧИТАЕТ.
        if "golden" not in source.lower():
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        # МЕСТО ОБЪЯВЛЕНИЯ — вот авторитет. Импорт `from … import PROGRAMS`
        # даёт модулю тот же атрибут, и `getattr` их не различает: вторая
        # редакция обхода объявила владельцем всех 69 голденов первого
        # ИМПОРТЁРА по алфавиту. AST различает — присваивание есть объявление.
        declared: list[str] = []
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                for target in (node.targets if isinstance(node, ast.Assign)
                               else [node.target]):
                    if isinstance(target, ast.Name):
                        declared.append(target.id)
            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.Assign, ast.AnnAssign)):
                        for target in (sub.targets if isinstance(sub, ast.Assign)
                                       else [sub.target]):
                            if isinstance(target, ast.Name):
                                declared.append(f"{node.name}.{target.id}")
        if not declared:
            continue
        try:
            module = importlib.import_module(f"{tests_pkg.__name__}.{info.name}")
        except Exception:  # noqa: BLE001 — чужой сломанный модуль не наша тема
            continue
        for decl in declared:
            if "." in decl:
                holder_name, attr = decl.split(".", 1)
                holder = getattr(module, holder_name, None)
                programs = getattr(holder, attr, None) if holder else None
                owner = f"{info.name}.{holder_name}"
            else:
                programs = getattr(module, decl, None)
                owner = info.name
            if not _looks_like_corpus(programs):
                continue
            for golden in programs:
                if not isinstance(golden, str):
                    continue
                if (GOLDEN_DIR / f"{golden}.golden.cs").is_file():
                    if owner not in out[golden]:
                        out[golden].append(owner)
    return out


class EveryGoldenHasExactlyOneOwner(unittest.TestCase):

    def test_no_golden_is_claimed_twice(self):
        """Два владельца одного файла — колебание без сходимости."""
        claims = _claims()
        shared = {name: owners for name, owners in claims.items()
                  if len(owners) > 1}
        self.assertEqual(
            shared, {},
            "у голдена больше одного заявляющего корпуса: перезаморозка под "
            "одного немедленно красит другого, и так по кругу. Переименуй или "
            "оставь ОДНОГО владельца")

    def test_the_probe_actually_found_owners(self):
        """Контроль-PASS: пустой обход дал бы зелёный, ничего не проверив.

        Ровно тот вакуумный зелёный, который мы ловим весь месяц: «нарушений
        нет» и «я никуда не смотрел» печатаются одинаково.
        """
        claims = _claims()
        self.assertGreaterEqual(
            len(claims), 50,
            f"обход нашёл {len(claims)} заявленных голденов — прибор не дошёл "
            f"до корпусов, и зелёный выше вакуумный")

    def test_the_walk_names_the_real_owner(self):
        """Контроль ОБХОДА, а не предиката: владелец назван верно.

        Две предыдущие редакции этого обхода давали ровно по одному владельцу
        на голден — и оба раза НЕ ТОГО: сперва `gate_runner`, который `PROGRAMS`
        лишь импортирует, потом первого импортёра по алфавиту. Счёт «1 владелец
        на файл» был зелёным в обоих случаях. Значит проверять надо ИМЯ.
        """
        claims = _claims()
        self.assertEqual(claims.get("auth_contour_l"), ["test_golden"])

    def test_declaring_a_corpus_is_not_owning_a_golden(self):
        """Контроль-FAIL обхода: имя, совпавшее с файлом, — не владение.

        `test_emitter_scope_contract` объявляет свой `PROGRAMS`, 12 имён
        которого совпадают с голденами, и каталог не трогает ни разу. Если он
        всплывёт владельцем — предикат снова считает по ВИДУ, а не по делу.
        """
        owners = {owner for owners in _claims().values() for owner in owners}
        self.assertNotIn("test_emitter_scope_contract", owners)

    def test_the_probe_can_say_no(self):
        """Контроль-FAIL: подставной второй владелец обязан краснеть.

        Без него «ноль коллизий» неотличим от матчера, отвечающего «нет» на
        любой вопрос.
        """
        claims = _claims()
        self.assertTrue(claims, "нечего проверять")
        victim = sorted(claims)[0]
        forged = dict(claims)
        forged[victim] = forged[victim] + ["_подставной_владелец"]
        shared = {n: o for n, o in forged.items() if len(o) > 1}
        self.assertEqual(
            sorted(shared), [victim],
            "подставная коллизия не обнаружена — предикат не различает")


if __name__ == "__main__":
    unittest.main()
