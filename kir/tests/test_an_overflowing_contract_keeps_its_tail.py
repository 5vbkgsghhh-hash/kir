"""A contract that does not fit into the channel loses PROSE, not parameter boundaries.

🔴 MEASURED 25.08.2026 ACROSS THE WHOLE REGISTRY. The print channel is
3300 characters; THREE ops overflow it, and one of the three goes down
the wrong branch:

    op                    text  prose   keep  outcome
    create_solid_blend     3541    477     14  TAIL TRUNCATION (threshold 200)
    route_duct_system      3967   2850   1960  prose compression
    route_pipe_system      3904   2786   1959  prose compression

With EMPTY prose, `create_solid_blend`'s text would be 3064 — it FITS.
The sections fit, but the model gets a contract without them.

🔴 REMEASURED 07.09.2026 WITH THE SAME INSTRUMENT (`_переполняющие()` over
the whole registry, 83 ops). Still THREE ops overflow, but the numbers
shifted, and the shift is recorded, not smoothed over:

    op                    text  prose  no_prose  MARGIN  (was text)
    create_solid_blend     3538    477      3061      18     3541
    route_pipe_system      3899   2786      1113    1966     3904
    route_duct_system      3962   2850      1112    1967     3967

The 3–5 character shift comes from edits to the registry's own docstrings
between 25.08 and 07.09; neither the channel nor the op count moved. The
numbers were updated BECAUSE the instrument said something new, not
because the old ones were in the way.

🔴 CHANNEL MARGIN IS A QUANTITY THAT DID NOT EXIST HERE, AND ITS ABSENCE
WOULD HAVE COST A TAIL. The question "will another N characters fit here"
used to be answered by subtracting `LESSON_CAP - text`, and the answer
came out wrong: for `create_solid_blend` that estimate promises a margin
of −238 (that is, "nothing will fit"), while for `route_duct_system` it
gives −662, even though in reality the second one holds 1967 characters
and the first exactly EIGHTEEN. The order is the reverse of the estimate,
because what decides is not the length of the text, but the length
WITHOUT PROSE: only the postcondition's prose gets compressed.

Measured 07.09.2026 (`_запас_канала()`, binary search against the LIVE
cutter):

    create_solid_blend       MARGIN    18   ← binds the whole registry
    create_ceiling           MARGIN   571     (does not overflow the channel)
    create_stairs_landing    MARGIN  1168     (does not overflow the channel)
    route_pipe_system        MARGIN  1966
    route_duct_system        MARGIN  1967
    the other 78              MARGIN  > 1900

The census runs over ALL ops, not just the overflowing ones:
`create_ceiling` does not overflow the channel at all and never once fell
into the old census, and yet its margin is 571 — the second tightest.

WHAT THIS NUMBER WAS PAID FOR. On 07.09.2026 it was proposed to write a
"WHAT THIS OP CANNOT DO" block into the contract (`kir.capability`, five
axes). The block weighs 321 characters at the median and 696 at the
maximum; even a form made of nothing but axis CODES is 28. At a margin of
18 it does not fit in any form, and it would not have fit SILENTLY — see
the note on `continue` below. The axes went to the model through the
door's machine field instead (`kir/mcp/server.py:_capability_fields`),
where there is no ceiling at all.

WHAT EXACTLY IS LOST. The contract's tail is the parameter boundaries:
`height_mm mm 1..500000`, `category enum{…}` with six values, `name
str<=64`. A model that never saw them will miss exactly on them and get a
refusal it could have avoided. The code's own comment says the same:
«ОБРЕЗАННЫЙ КОНТРАКТ — НЕ КОНТРАКТ: допуски и постусловие стоят В КОНЦЕ»
(A TRUNCATED CONTRACT IS NOT A CONTRACT: the tolerances and the
postcondition stand AT THE END).

THE CAUSE IS A THRESHOLD THAT MIXED TWO QUESTIONS TOGETHER. `if keep <
200: fall back to tail truncation` answers, at once, "the sections do not
fit even with empty prose" (a real impossibility) and "not much prose will
be left" (a quality question). The second is cured by cutting the prose
OUT ENTIRELY and naming what was cut, not by losing the sections.

🔴 AND THE `continue` WAS REMOVED THAT MADE THIS INSTRUMENT BLIND EXACTLY
WHERE IT IS NEEDED (07.09.2026). It used to read: `if без_прозы >
LESSON_CAP: continue  # честная невозможность, не предмет теста`. That is,
the op whose sections do not fit even with EMPTY prose — the one op that
DEFINITELY loses its tail — fell out of the census, and the instrument
turned greener the worse things got. Verified by mutation the same day:
adding 386 characters to `create_solid_blend` (text 3924, no_prose 3447)
tips it into tail truncation — and the old instrument did NOT SEE this.
Now such an op turns it red, and the decision (shorten the contract, or
teach the cutter) is made by a human, not by silence.

THIS TEST CHECKS A PROPERTY, NOT A SINGLE CASE: the census runs over the
whole registry, so a fourth such op will turn it red by itself, on the
very day it is introduced.
"""
from __future__ import annotations

import unittest

from kir import spec as _spec
from kir.course import LESSON_CAP, _contract_within_channel, _spec_parts


def _переполняющие() -> list[tuple[str, object, str]]:
    ряды = []
    for имя, ospec in sorted(_spec.OPS.items()):
        голова, тело = _spec_parts(ospec)
        текст = голова + тело
        if len(текст) > LESSON_CAP:
            ряды.append((имя, ospec, текст))
    return ряды


#: The binary search's ceiling — and it IS REACHABLE, so saturation is NAMED.
#:
#: Set equal to the sandbox's entire channel (`LESSON_CAP` + reserve =
#: 4000): a larger addition makes no sense — it would not fit the pipe
#: even with an empty contract. An op that hits the ceiling is printed as
#: "≥4000", not as a number: a silent "4000" would read as a measurement,
#: even though it is the INSTRUMENT's boundary, not a property of the op.
#: This does not touch the tightness — the census's subject is its lower end.
_ПОТОЛОК_ПОИСКА = LESSON_CAP + 700


def _запас_канала(ospec: object, текст: str) -> int:
    """How many CHARACTERS an op can still hold, WITHOUT LOSING the contract's tail.

    This is asked of the LIVE cutter's BEHAVIOR, not computed by arithmetic
    over its docstring: `_contract_within_channel` chooses one of three
    branches by the length WITHOUT PROSE, and any formula here would be a
    second opinion about the same fact — it would drift apart at the first
    edit of the threshold.

    The addition is placed as a TAIL, because that is exactly how text
    accretes onto a contract (a constraints block, a new schedule), and
    because the tail is what gets lost first.
    """
    низ, верх = 0, _ПОТОЛОК_ПОИСКА
    while низ < верх:
        середина = (низ + верх + 1) // 2
        добавка = "\n" + "X" * (середина - 2) + "\n" if середина >= 2 else ""
        выдано = _contract_within_channel(ospec, текст + добавка, lambda _k: "")
        доехало = (len(выдано) <= LESSON_CAP
                   and (not добавка or добавка[-40:] in выдано))
        низ, верх = (середина, верх) if доехало else (низ, середина - 1)
    return низ


class ПереполненныйКонтрактДоезжаетРазделами(unittest.TestCase):

    def test_перепись_не_пуста(self) -> None:
        """A CONTROL ON THE TEST ITSELF: a census over zero ops is green by construction.

        Canon form 4 — a zero from an unreachable corpus is not a zero. If
        the registry is rebuilt and there are no more overflowing ops, this
        test MUST say so OUT LOUD, rather than quietly pass on nothing at all.
        """
        self.assertGreater(len(_переполняющие()), 0,
                           "переполняющих опов нет — тест проверяет пустоту")

    def test_хвост_контракта_доезжает_у_каждого(self) -> None:
        """The parameter boundaries stand AT THE END and MUST arrive — FOR EVERY OP.

        🔴 NO EXCEPTIONS, AND THIS IS THE 07.09.2026 FIX. Previously, an op
        whose sections do not fit even with empty prose was skipped as an
        "honest impossibility" — that is, the census dropped exactly the
        one op that DEFINITELY lost its tail. Impossibility here is not an
        excuse, it is a finding: it means the contract has outgrown the
        channel, and that is for a human to decide.
        """
        потеряли = []
        for имя, ospec, текст in _переполняющие():
            без_прозы = len(текст) - len(getattr(ospec, "post", "") or "")
            выдано = _contract_within_channel(ospec, текст, lambda _k: "")
            хвост = текст[-120:]
            if хвост not in выдано:
                потеряли.append(
                    f"{имя}: текст {len(текст)}, без прозы {без_прозы} "
                    f"(канал {LESSON_CAP}, запас "
                    f"{_запас_канала(ospec, текст)}) — хвост НЕ ДОЕХАЛ")
        self.assertEqual(потеряли, [], msg=(
            "\n🔴 КОНТРАКТ ПОТЕРЯЛ ХВОСТ.\n"
            "В хвосте стоят границы параметров и допуски свидетеля —\n"
            "ровно то, по чему модель промахнётся, не увидев их.\n"
            "Если «без прозы» больше канала, разделы не помещаются и с\n"
            "ПУСТОЙ прозой: укоротить контракт либо научить резчик —\n"
            "молчания третьим исходом больше нет.\n"
            + "\n".join(потеряли)))

    def test_выданное_влезает_в_канал(self) -> None:
        """A repair has no right to cure itself by overrunning the channel."""
        велики = [(имя, len(_contract_within_channel(ospec, текст, lambda _k: "")))
                  for имя, ospec, текст in _переполняющие()]
        превысили = [(и, n) for и, n in велики if n > LESSON_CAP]
        self.assertEqual(превысили, [], msg=(
            f"\n🔴 ВЫДАННОЕ БОЛЬШЕ КАНАЛА {LESSON_CAP}: {превысили}"))

    def test_вырезанное_названо(self) -> None:
        """Prose silently shortened is indistinguishable from prose that never existed."""
        for имя, ospec, текст in _переполняющие():
            с_ним = _contract_within_channel(ospec, текст, lambda _k: "")
            self.assertTrue(
                "ПРОЗА ПОСТУСЛОВИЯ" in с_ним or "ОБРЕЗАНО" in с_ним,
                msg=f"{имя}: текст урезан и об этом не сказано")

    def test_запас_канала_назван_числом_а_не_прикидкой(self) -> None:
        """THE MARGIN IS PRINTED, because decisions are made from it.

        Whoever wants to add a line to a contract (a constraints block, a
        schedule, one more section) asks exactly this number — and before
        07.09.2026 there was nobody to ask it of, so they asked the
        subtraction `LESSON_CAP - text`, which gives the REVERSE order.

        There are two assertions, and both are about a property, not
        about today's number: the census read the WHOLE registry (the
        denominator), and not a single op stands at zero — an op with zero
        margin loses its tail from any addition at all, including one line
        added to the registry's docstring.
        """
        ряды = []
        for имя, ospec in sorted(_spec.OPS.items()):
            голова, тело = _spec_parts(ospec)
            текст = голова + тело
            ряды.append((_запас_канала(ospec, текст), имя, len(текст),
                         len(текст) > LESSON_CAP))
        ряды.sort()

        print(f"\nЗАПАС КАНАЛА (канал {LESSON_CAP}, опов {len(ряды)}) — "
              f"сколько знаков контракт ещё вмещает, не теряя хвост:")
        for запас, имя, длина, переполняет in ряды[:6]:
            метка = "  ← ПЕРЕПОЛНЯЕТ КАНАЛ" if переполняет else ""
            число = (f"≥{_ПОТОЛОК_ПОИСКА}" if запас >= _ПОТОЛОК_ПОИСКА
                     else f"{запас}")
            print(f"  {имя:24} текст {длина:5}  ЗАПАС {число:>6}{метка}")
        переполняющие = [(з, и, д) for з, и, д, п in ряды if п]
        print(f"  переполняющих {len(переполняющие)}, "
              f"теснейший запас {ряды[0][0]} у {ряды[0][1]}")

        self.assertEqual(len(ряды), len(_spec.OPS), msg=(
            "перепись прочла не весь реестр — число ниже ничего не значит"))
        нулевые = [(и, д) for з, и, д, _п in ряды if з <= 0]
        self.assertEqual(нулевые, [], msg=(
            f"\n🔴 ЗАПАС КАНАЛА ИСЧЕРПАН у {нулевые}: контракт теряет хвост\n"
            f"от ЛЮБОЙ добавки, включая строку докстроки реестра.\n"
            f"Канал {LESSON_CAP} = {LESSON_CAP + 700} песочницы минус 700 "
            f"резерва автору; поднять его значит отнять у модели её же "
            f"печать."))


    def test_контроль_прибор_краснеет_на_ушедшем_в_обрезку_хвоста(self) -> None:
        """A MUTATION FAIL CONTROL: the assertion above MUST BE ABLE to turn red.

        The removed `continue` is proved not by argument, but by
        exhibiting an op that falls into the new census and loses its
        tail. The mutation is exactly the one proposed on 07.09: add a
        constraints block to the contract, larger than the op's margin.

        🔴 THE ADDITION IS MEASURED, NOT REMEMBERED (13.09.2026). It used to
        be the literal 386 — the margin `create_solid_blend` had on 07.09,
        which was 18. On 13.09 the region help stopped repeating the whole
        shape catalogue in the SECOND region slot of the same contract
        (`kir/dsl.py::_docstring`; the op is the only one in the registry with
        two), the contract fell from 3143 to 2100 characters without prose,
        and the margin grew past 386 — so yesterday's number stopped being a
        mutation at all, and this control went green for the wrong reason.
        The message below had foreseen exactly that: «возьми добавку крупнее
        запаса, а не число прошлого дня». It is now taken that way.

        Without this control, the main test's green would mean either "the
        tail arrives" or "no such op exists today," and the second would
        read as the first — the form "a refutation needs a control"
        (04.09.2026).
        """
        ospec = _spec.OPS["create_solid_blend"]
        голова, тело = _spec_parts(ospec)
        текст = голова + тело
        запас = _запас_канала(ospec, текст)
        self.assertGreaterEqual(запас, 0, msg=(
            f"запас {запас} отрицателен — контракт уже не помещается, и "
            "мутировать нечего: это предмет главного теста, не контроля"))

        # 🔴 THE TAIL NEEDS A DISTINCT MARK, NOT A RUN OF ONE LETTER. With the
        # addition built of «X» alone, the check «последних 120 знаков нет в
        # выдаче» matched the X's that SURVIVED inside the channel — a false
        # find that read as "the tail arrived". Measured 13.09.2026, right
        # after the margin grew. The mutation therefore ends with a phrase that
        # can be found nowhere else.
        маркер = "‹ХВОСТ-КОНТРОЛЯ-13.09›"
        добавка = запас + 1
        раздутый = текст + "X" * добавка + маркер
        без_прозы = len(раздутый) - len(getattr(ospec, "post", "") or "")
        self.assertGreater(без_прозы, LESSON_CAP, msg=(
            "мутация не завела опа в «невозможность» — она проверяет не то"))
        выдано = _contract_within_channel(ospec, раздутый, lambda _k: "")
        self.assertNotIn(маркер, выдано, msg=(
            "раздутый контракт хвост НЕ ПОТЕРЯЛ — значит главный тест зелен "
            "по построению, и снятие `continue` ничего не изменило"))
        self.assertIn("ОБРЕЗАНО", выдано, msg=(
            "ветка обрезки хвоста не сработала — контроль мерит другое"))


if __name__ == "__main__":
    unittest.main()
