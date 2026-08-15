"""Отказ гейта называет ТУ причину, которая отказала.

ЗАЧЕМ. 13.08.2026 гейт `revit_ir_enabled` получил третье условие — явный
признак режима КИР на ходе (решение оператора: КИР — отдельный режим, а не
инструмент обычного чата). Текст отказа остался прежним, один на все причины,
и указывал на СПИСОК УСТРОЙСТВ:

    отказало   третье условие, `kir_mode_active()`
    названо    второе, `KUKAI_ADMIN_DEVICES`

Найдено ВОРОТАМИ при разборе 110 красных слитой линии: они первым делом пошли
проверять `admin_devices()`, потому что сообщение указывает туда, и потратили
на невиновный модуль отдельный заход. **Всякий, кто прочтёт это сообщение,
добавит id устройства, и ничего не изменится.**

Это наш именованный класс в канале диагностики: величина, назвавшая причину, —
не та, что решила. И это же обратная сторона закона «ошибка несёт своё
лекарство»: ошибка, называющая НЕВЫПОЛНИМЫЙ ход, хуже той, что не называет
никакого.

ЧТО ЗДЕСЬ ПИНИТСЯ. Не формулировки, а РАЗЛИЧИМОСТЬ: три причины обязаны дать
три РАЗНЫХ текста, и каждый обязан указывать на свою. Тест переживёт любую
редактуру слов, пока различение сохраняется.
"""

from __future__ import annotations

import os
import unittest

from kukai.ir import serving
from kukai.ir.serving import admin_gate_message_ru

ADMIN = "test-device-id-0000000000000000"


class TheRefusalNamesTheConditionThatFailed(unittest.TestCase):

    def setUp(self) -> None:
        self._env = {k: os.environ.get(k)
                     for k in ("KUKAI_KIR_TOOL", "KUKAI_ADMIN_DEVICES")}
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        os.environ["KUKAI_ADMIN_DEVICES"] = ADMIN

    def tearDown(self) -> None:
        # Восстанавливаем НАБЛЮДЁННОЕ, а не запомненную константу.
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            from kukai.llm.turn_context import publish_kir_mode
            publish_kir_mode(False)
        except Exception:  # noqa: BLE001
            pass

    def _mode(self, on: bool) -> None:
        from kukai.llm.turn_context import publish_kir_mode
        publish_kir_mode(on)

    def test_no_flag_names_the_flag(self) -> None:
        os.environ["KUKAI_KIR_TOOL"] = "off"
        msg = admin_gate_message_ru("revit_ir")
        self.assertIn("KUKAI_KIR_TOOL", msg)
        self.assertNotIn("KUKAI_ADMIN_DEVICES", msg,
                         "отказ по флагу отправляет настраивать устройства")

    def test_no_mode_names_the_mode_and_never_the_device_list(self) -> None:
        """ГЛАВНОЕ УТВЕРЖДЕНИЕ, ради которого тест написан.

        Флаг есть, устройства заданы — отказать может только режим. Сообщение
        обязано сказать про режим и НЕ ОБЯЗАНО отправлять читателя в список
        устройств: именно этот ложный маршрут стоил ВОРОТАМ отдельного захода.
        """
        self._mode(False)
        msg = admin_gate_message_ru("revit_ir")
        self.assertIn("РЕЖИМ", msg)
        self.assertNotIn("KUKAI_ADMIN_DEVICES", msg,
                         "отказ по режиму снова отправляет в список устройств")

    def test_empty_device_list_names_the_list(self) -> None:
        self._mode(True)
        os.environ["KUKAI_ADMIN_DEVICES"] = ""
        msg = admin_gate_message_ru("revit_ir")
        self.assertIn("KUKAI_ADMIN_DEVICES", msg)
        self.assertIn("пуст", msg)

    def test_the_three_texts_are_pairwise_DIFFERENT(self) -> None:
        """Различимость, а не формулировки: пинится то, что три причины дают
        три РАЗНЫХ ответа. Редактура слов тест не ломает."""
        texts = []
        os.environ["KUKAI_KIR_TOOL"] = "off"
        texts.append(admin_gate_message_ru("revit_ir"))
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        self._mode(False)
        texts.append(admin_gate_message_ru("revit_ir"))
        self._mode(True)
        os.environ["KUKAI_ADMIN_DEVICES"] = ""
        texts.append(admin_gate_message_ru("revit_ir"))
        self.assertEqual(len(set(texts)), 3,
                         f"причин три, различных текстов {len(set(texts))}")

    def test_the_order_here_matches_the_gate(self) -> None:
        """Порядок проверок в сообщении и в гейте — один.

        Разойдись они, сообщение снова начнёт называть не то условие: гейт
        отказал бы по первому, а текст доложил бы про второе. Пинится
        ИСТОЧНИКОМ, а не памятью.
        """
        import ast
        import inspect
        import textwrap

        def body_text(fn) -> str:
            """ТЕЛО функции без докстринга.

            Первая редакция этого теста индексировала сырой `getsource` — и
            попала в ДОКСТРИНГ, где `kir_mode_active` упомянут раньше `_FLAG`.
            Сопоставление по виду вместо сопоставления по предмету, в тесте,
            написанном против ровно этого класса.
            """
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
            fn_node = tree.body[0]
            stmts = fn_node.body
            if (stmts and isinstance(stmts[0], ast.Expr)
                    and isinstance(stmts[0].value, ast.Constant)
                    and isinstance(stmts[0].value.value, str)):
                stmts = stmts[1:]
            return "\n".join(ast.unparse(s) for s in stmts)

        gate = body_text(serving.revit_ir_enabled)
        msg = body_text(serving.admin_gate_message_ru)
        for token in ("_FLAG", "kir_mode_active", "admin_device"):
            self.assertIn(token, gate, f"{token} исчез из ТЕЛА гейта")
        # В сообщении флаг — ПАРАМЕТР `flag`, а не константа: гейтов два, и
        # какой из них отказал, знает только вызывающий.
        self.assertLess(msg.index("os.environ.get(flag"),
                        msg.index("kir_mode_active"),
                        "в сообщении режим проверяется раньше флага")
        self.assertLess(msg.index("kir_mode_active"),
                        msg.index("admin_devices"),
                        "в сообщении устройства проверяются раньше режима")


class TheMessageAsksTheGateThatActuallyRefused(unittest.TestCase):
    """ГЕЙТОВ ДВА, И СООБЩЕНИЕ ОДНО НА ОБА.

    `revit_ir` стоит за `revit_ir_enabled` (флаг `KUKAI_KIR_TOOL` + режим +
    устройство). `revit_decompile` / `revit_rebuild` / `revit_idempotence` —
    за `revit_decompile_enabled` (флаг `KUKAI_KIR_DECOMPILE`, режима НЕТ).

    Первая редакция починки вшила в общее сообщение условия ПЕРВОГО гейта, и
    отказ декомпиляции стал называть чужой флаг и условие, которого у неё нет.
    **Починка совершила тот самый дефект, который чинила, этажом выше.**
    Поймано ВОРОТАМИ, не автором.

    ВТОРАЯ РЕДАКЦИЯ ЭТОГО ЖЕ ФАЙЛА СОВЕРШИЛА ЕГО ТРЕТИЙ РАЗ, и вот как.
    `test_the_decompile_message_names_its_own_flag` УТВЕРЖДАЛ ветку «флаг не
    выставлен», НЕ УПРАВЛЯЯ флагом: значение приходило из окружения. В
    одиночку файл зелёный (флага нет), в паре с любым тестом под `tests/`
    красный — `tests/conftest.py` тянет прод-`.env`, где
    `KUKAI_KIR_DECOMPILE=stage2` (замерено 13.08 зондом на каждый тест:
    флаг уже `stage2` ПЕРЕД первым тестом прогона, то есть выставлен на
    импорте, а не соседом). Тест проходил ПО ПОСТРОЕНИЮ ОКРУЖЕНИЯ, а не по
    свойству кода — величина, решающая исход, задавалась не там, где
    утверждалась.

    Поэтому флаг здесь ставится ЯВНО, в обе стороны, и обе стороны
    проверяются: выключен ⇒ сообщение называет СВОЙ флаг; включён ⇒ не
    называет его вовсе, потому что отказала не он. Пара «выкл/вкл» и есть
    акт различения: без неё зелёный не отличим от зелёного-по-умолчанию.
    """

    def setUp(self) -> None:
        self._env = {k: os.environ.get(k)
                     for k in (serving._DECOMPILE_FLAG, "KUKAI_ADMIN_DEVICES")}
        # Устройства пиним, чтобы ветка «флаг в порядке» была одной и той же
        # независимо от того, что оставил в окружении прод-`.env`.
        os.environ["KUKAI_ADMIN_DEVICES"] = ADMIN

    def tearDown(self) -> None:
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _flag(self, on: bool) -> None:
        if on:
            os.environ[serving._DECOMPILE_FLAG] = "stage2"
        else:
            os.environ.pop(serving._DECOMPILE_FLAG, None)

    def _msg(self) -> str:
        return serving.admin_gate_message_ru(
            "revit_decompile", flag=serving._DECOMPILE_FLAG, needs_mode=False)

    def test_the_decompile_message_names_its_own_flag(self) -> None:
        self._flag(False)
        msg = self._msg()
        self.assertIn("KUKAI_KIR_DECOMPILE", msg)
        self.assertNotIn("KUKAI_KIR_TOOL", msg, "назван чужой флаг")

    def test_with_the_flag_on_the_message_stops_naming_it(self) -> None:
        """КОНТРОЛЬ В ДРУГУЮ СТОРОНУ: назван тот, кто ОТКАЗАЛ.

        Без этого теста первый зелен и при сообщении, называющем свой флаг
        ВСЕГДА, — то есть при возврате к ровно тому дефекту, ради которого
        функция и переписывалась.
        """
        self._flag(True)
        msg = self._msg()
        self.assertNotIn("KUKAI_KIR_DECOMPILE", msg,
                         "назван флаг, который не отказывал")

    def test_the_decompile_message_never_speaks_of_a_mode(self) -> None:
        """У этого гейта режима НЕТ — упоминать его значит слать читателя
        включать то, чего не существует."""
        self._flag(True)
        self.assertNotIn("РЕЖИМ", self._msg())

    def test_every_call_site_names_the_gate_it_stands_behind(self) -> None:
        """СПИСОК ПЛОЩАДОК ПОЛОН ПО ПОСТРОЕНИЮ: обход AST по `serving.py`.

        Площадка, добавленная завтра, попадёт под проверку сама. Правило:
        инструменты декомпиляции обязаны назвать свой флаг явно; площадки
        `revit_ir` вправе опираться на умолчание, описывающее ИХ гейт.
        """
        import ast
        import pathlib
        src = pathlib.Path(serving.__file__).read_text(encoding="utf-8")
        decompile = {"revit_decompile", "revit_rebuild", "revit_idempotence"}
        seen = set()
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else getattr(fn, "id", ""))
            if name != "admin_gate_message_ru" or not node.args:
                continue
            arg = node.args[0]
            if not isinstance(arg, ast.Constant):
                continue
            inst = str(arg.value).split(" ")[0]
            kw = {k.arg for k in node.keywords}
            seen.add(inst)
            if inst in decompile:
                self.assertIn("flag", kw, f"{inst} не назвал свой флаг")
                self.assertIn("needs_mode", kw,
                              f"{inst} не снял условие режима")
        self.assertEqual(seen & decompile, decompile,
                         f"обход не нашёл все площадки декомпиляции: {seen}")


if __name__ == "__main__":
    unittest.main()
