"""Every name in the script's namespace is either DOCUMENTED or dark
FOR A NAMED REASON.

**The hole this is written for is not in the code — it is between the
code and the model's knowledge.** Measurement 2026-08-12: the script's
namespace carries **98 names** (69 ops from the registry plus 29
others), and **18 of them never once appeared in the rendered
documentation**. Among the dark ones were all the selector
constructors, while the language itself accepts a form SHORTER than
any of them — `level="Этаж 1"` — and the docs never named it AT ALL.
The model wrote twenty-five hand-built selector dictionaries where one
string would have sufficed.

The ops layer, meanwhile, is complete BY CONSTRUCTION and cannot fall
behind: `dsl` generates its functions straight from `spec.OPS`
(`{name: _make_op_fn(ospec) ...}` → `globals()` → `__all__`), so
69 = 69 and a new op appears on its own. **Completeness of the code
promises nothing about completeness of the docs** — these are
different lists with different authorities, and until today no one had
checked the second one.

So the requirement here is not "document everything": some names are
CORRECTLY dark — types the script receives but does not construct; the
program's lifecycle, which the sandbox manages on its own. The
requirement is different and weaker: **darkness must be a DECISION
with a reason, not an oversight.** A new name in the sandbox turns a
test red and forces a choice — describe it to the model, or declare it
dark and say why.

The kind of list is named explicitly, because the meaning of a missing
entry depends on it: :data:`DARK_ON_PURPOSE` is **CLOSED, BUT NOT
COMPLETE**. Its composition is upheld by discipline, not derived from
an authority: "the model does not need to know this name" is a
judgment call, and it cannot be computed automatically. The absence of
a name here means "we haven't decided," not "the model needs the
name."
"""

import re
import unittest

from kir import dsl, sandbox, spec
from kir.course import SANDBOX_NAMES
from kir.skill import build_skill_text, build_walkthrough_programs_text
from kir.tool_doc import build_tool_description

#: A name that is dark ON PURPOSE, with the reason alongside it. A
#: closed but not complete list.
DARK_ON_PURPOSE: dict[str, str] = {
    "Program": "тип программы; скрипт его получает, но никогда не строит",
    "Handle": "тип ручки; возвращается вызовом опа, конструировать нечем",
    "DslRefusal": "исключение языка; ловить его скрипту незачем — отказ уезжает "
                  "в квитанцию сам",
    "build": "песочница забирает программу сама; `build()` — дверь хоста",
    "plan": "планирование ведёт компилятор после песочницы",
    "current": "программа в скрипте ровно одна и подразумевается",
    "reset": "вторая программа за вызов запрещена по построению",
    "OMIT": "часовой «поле не передано»; в питоне это делает само опущение "
            "аргумента",
    "MAX_BULK_OPS": "число уже названо в доке словами («до 300 операций»); "
                    "имя константы модели не нужно",
    "by_name": "вытеснен КОРОТКОЙ формой: `level=\"Этаж 1\"` даёт тот же узел",
    "by_element_id": "вытеснен короткой формой: `level=1100` даёт тот же узел",
    "by_ref": "внутри скрипта ссылка — это РУЧКА, возвращённая вызовом; "
              "писать `by_ref` руками незачем",

    # ── FREE-FORM DICTIONARY (01–02.09.2026): DARK IN THE PERMANENT
    # TEXT, NAMED IN THE LESSON. All eleven share ONE reason, and it is
    # measured, not chosen: the permanent doc costs 29,955 characters
    # against a ceiling of 29,970, the "geometry" lesson — 3,297 against
    # `LESSON_CAP`'s 3,300. Both places are PAID FOR. So the same law
    # applies that separated the spline and the plane on 29.08 (F-293):
    # knowledge of a KIND's EXISTENCE always travels PERMANENTLY —
    # `loft`/`section`/`faces`/`promote` — while the names within a kind
    # live in `course("геометрия")`, which is where one goes for them
    # ALREADY KNOWING the kind exists.
    #
    # 🔴 THIS IS NOT PERMISSION TO STAY SILENT. A name named NEITHER
    # HERE NOR IN THE LESSON must not be added to this list: on 02.09
    # there were three such (`blend`, `revolve`, `promote`), and they
    # were given a place — two in the lesson at a cost of exactly zero
    # characters (squeezed out of neighboring phrases in the same
    # paragraph), the third in the permanent index.
    "move": "преобразования формы названы в `course(\"геометрия\")`",
    "rotate": "то же: урок «геометрия», абзац о свободной форме",
    "mirror": "то же: урок «геометрия», абзац о свободной форме",
    "scale": "то же: урок «геометрия», абзац о свободной форме",
    "array": "то же: урок «геометрия», абзац о свободной форме",
    "blend": "урок «геометрия»: «одной операцией: `blend` — переход»",
    "revolve": "урок «геометрия»: «`revolve` — вращение профиля»",
    "box": "операнд булевой; назван в уроке «геометрия» вместе с `parts`",
    "sphere": "операнд булевой; назван в уроке «геометрия» вместе с `parts`",
    "cylinder": "операнд булевой; назван в уроке «геометрия» вместе с `parts`",
    "by_property": "выбор типа ВЕЛИЧИНОЙ; назван в уроке «геометрия»",
}


def _documentation() -> str:
    """What the model RECEIVES, not the sources that generate it.

    The difference is not cosmetic: a grep over `tool_doc.py`/
    `skill.py` declared **31** names dark, including **ten ops**
    (`create_roof`, `create_duct`, `move_elements`…). A false alarm,
    entirely: ops enter the text FROM THE REGISTRY at render time, they
    are not literals in the source. The authority is the rendered
    document.
    """
    return "\n".join((build_tool_description(),
                      build_skill_text(),
                      build_walkthrough_programs_text()))


class EverySandboxNameIsDocumentedOrDeclaredDark(unittest.TestCase):

    def _names(self) -> set[str]:
        # 🔴 THE GUARD'S SCOPE WAS NARROWER THAN ITS OWN PROMISE (fix
        # 15.08). The header says "every name in the script's
        # namespace," but the scope was `dsl.__all__ | SANDBOX_NAMES` —
        # that is, without the names the sandbox injects ITSELF.
        # `model` had lived unchecked since the catalog first appeared.
        # Now the third term is taken from the authority
        # (`sandbox.HOST_NAMES`), which is checked against the actual
        # injection and fails on any discrepancy.
        return set(dsl.__all__) | set(SANDBOX_NAMES) | set(sandbox.HOST_NAMES)

    def test_the_op_layer_cannot_fall_behind(self):
        """69 = 69, and this is by construction, not by luck."""
        ops = set(spec.OPS)
        self.assertEqual(
            ops - set(dsl.__all__), set(),
            "оп реестра не экспортирован песочницей — порождение функций из "
            "`spec.OPS` сломано")

    def test_a_reason_that_names_the_lesson_is_checked_against_it(self):
        """🔴 A REASON NOBODY CHECKS IS A WORD, NOT A REASON.

        Bought by a control on 02.09.2026. Eleven names of the
        free-form dictionary are declared dark with the argument
        "named in `course("геометрия")`." Control-FAIL: remove two
        names from the lesson, and
        `test_no_name_is_dark_without_a_reason` STAYED GREEN, because
        it reads the PERMANENT text, and no one reads the lesson. That
        is, the argument rested on my word, and it could have been
        rewritten without going red anywhere — the named form of this
        tree's disease: an instrument that can be defeated by
        rewriting guards nothing.

        Here the argument becomes a NUMBER: say "in the lesson" — the
        name must be in the lesson. Reasons that have nothing to check
        them against ("handle type", "host door") remain a matter of
        discipline, and the file's header is honest about that.
        """
        from kir.skill import build_shape_vocabulary_text
        урок = build_shape_vocabulary_text()
        обещали = {n for n, причина in DARK_ON_PURPOSE.items()
                   if "геометрия" in причина}
        self.assertGreaterEqual(
            len(обещали), 11,
            "проверять стало нечего — либо доводы переписаны, либо сломан "
            "разбор причин; пустая проверка прошла бы вакуумно")
        промахи = sorted(n for n in обещали
                         if not re.search(rf"\b{re.escape(n)}\b", урок))
        self.assertEqual(
            промахи, [],
            "довод обещает урок «геометрия», а имени там нет:\n  "
            + "\n  ".join(промахи)
            + "\nЛибо верни имя в урок, либо назови ДРУГУЮ причину — но не "
              "оставляй довод, который сам себя не держит.")

    def test_no_name_is_dark_without_a_reason(self):
        text = _documentation()
        # Control-PASS and control-FAIL belong to the instrument, not
        # the subject: a documented name must be found, an invented one
        # must not.
        self.assertRegex(text, r"\bcreate_wall\b",
                         "прибор не видит заведомо документированного имени — "
                         "сломан рендер, а не документация")
        self.assertNotRegex(text, r"\b__имени_которого_нет__\b")

        dark = {n for n in self._names()
                if not re.search(rf"\b{re.escape(n)}\b", text)}
        undeclared = sorted(dark - set(DARK_ON_PURPOSE))
        self.assertEqual(
            undeclared, [],
            "имя есть в пространстве скрипта, но модель о нём не знает и "
            "никто не решал, что так и надо:\n  " + "\n  ".join(undeclared)
            + "\nОпиши его в `tool_doc`/`skill` ЛИБО внеси в DARK_ON_PURPOSE "
              "с причиной.")

    def test_the_dark_list_has_not_outlived_its_names(self):
        """A record about a name that no longer exists is a lie, going
        stale in silence."""
        stale = sorted(set(DARK_ON_PURPOSE) - self._names())
        self.assertEqual(
            stale, [],
            "DARK_ON_PURPOSE называет имена, которых в песочнице нет: "
            f"{stale}")

    def test_every_reason_says_something(self):
        for name, reason in sorted(DARK_ON_PURPOSE.items()):
            with self.subTest(name=name):
                self.assertGreater(
                    len(reason.strip()), 20,
                    f"{name}: причина слишком коротка, чтобы быть решением")

    def test_the_short_selector_form_is_taught(self):
        """The shortest form must be NAMED, not implied.

        It was exactly the hole: the language accepted `level="Этаж 1"`
        from the very start, while the docs showed only the dictionary
        form.
        """
        text = _documentation()
        self.assertIn(
            'level="Этаж 1"', text,
            "короткая форма селектора не названа модели — она снова будет "
            "писать словарь руками")


class TheHintsHaveOneOwner(unittest.TestCase):
    """The language's refusal and the model's docs read ONE dictionary,
    not two copies."""

    def test_the_doc_is_built_from_the_refusal_hints(self):
        from kir import tool_doc
        rendered = " ".join(tool_doc._selector_forms_in_python())
        for form in ("name", "element_id", "default", "ref"):
            with self.subTest(form=form):
                self.assertIn(dsl._SELECTOR_HINTS[form], rendered,
                              "дока переписала подсказку своими словами вместо "
                              "того, чтобы взять её у языка")

    def test_a_new_form_would_reach_the_doc_by_itself(self):
        original = dict(dsl._SELECTOR_HINTS)
        dsl._SELECTOR_HINTS["name"] = "ПРОБНАЯ ФОРМА"
        try:
            from kir import tool_doc
            rendered = " ".join(tool_doc._selector_forms_in_python())
            self.assertIn(
                "ПРОБНАЯ ФОРМА", rendered,
                "правка авторитета не доехала до доки — связь только на вид")
        finally:
            dsl._SELECTOR_HINTS.clear()
            dsl._SELECTOR_HINTS.update(original)


if __name__ == "__main__":
    unittest.main()
