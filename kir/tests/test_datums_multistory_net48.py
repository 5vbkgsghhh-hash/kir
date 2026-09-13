"""The multistory-stair boundary runs through net48 — and it's NOT about
the Revit API.

All members of `MultistoryStairs` exist on all six versions, and the gate
compiled the body 6/6 GREEN. The refusal stands for a different reason:
the entire multistory-stair API is typed as
`System.Collections.Generic.ISet<ElementId>`, and the reference closure of
the DEPLOYED plugin on net48 does not contain `ISet` —

    declared/net48   43 assemblies, 3003 types, ISet EXISTS
    deployed/net48   42 assemblies, 2007 types, ISet MISSING

and the two differ by EXACTLY ONE assembly: `System.dll`. The body would
compile for us and fail for the user with `CS0012`, naming no culprit —
that is, a silently-wrong outcome the cardinal invariant does not allow.

THERE IS NOTHING TO FIX IN THE SOURCE. `CodeCompiler.cs` at HEAD already
keeps `System` in `allowedExactNames`, and its own comment names `ISet<>`
as the first example of what `System.dll` provides. The mismatch is
between HEAD and the DEPLOYED BINARY: the fleet is running an old plugin.
The `deployed` profile is an honestly-named INFERENCE from three live
refusals on 04.08.2026, not a snapshot of a machine.

THE REFUSAL IS BROADER THAN ITS CAUSE, AND THAT IS DELIBERATE: for a
client already updated to 2021-2024 it is UNNECESSARY. But the emitter
does not know which binary the user has, and the tail of un-updated ones
is measured and non-empty. Between "a refusal is unnecessary for someone"
and "a silent CS0012 for someone," the cardinal invariant decides in one
direction.

THERE IS NO ISet-FREE PATH, AND THIS IS A MEASUREMENT AGAINST THE TRAP
INDEX, NOT AN ARGUMENT:

    ConnectLevels(ISet<ElementId>)              all 6 versions
    DisconnectLevels(ISet<ElementId>)           all 6
    GetAllConnectedLevels() -> ISet             all 6
    GetAllStairsIds() -> ISet                   all 6
    GetStairsPlacementLevels(Stairs) -> ISet    all 6

There is no way to connect levels without naming `ISet`: the one and only
connection method takes it as a parameter. So the refusal is not a
stopgap in place of a workaround, but the only honest answer until the
CLIENT is fixed.

THE CONDITION FOR LIFTING IT IS NAMED, SO THE REFUSAL DOES NOT OUTLIVE ITS
CAUSE. The line goes away once the deployed plugin starts referencing
`System.dll`. The judge is not memory and not this file, but the live
closure: the test below ASKS it and goes red if `ISet` has appeared there.
Otherwise the refusal would outlive the fix and would take away a
capability that has already returned.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from kir.compiler import compile_program
from kir.tests.fixtures import GROUND_SNAPSHOT
from kir.tests.test_golden import PROGRAMS

#: Versions on net48 — there the deployed plugin does not link `ISet`.
NET48_VERSIONS = ("2021", "2022", "2023", "2024")
#: Versions on net8 — there it does link it, and the op is legitimate.
NET8_VERSIONS = ("2025", "2026")

_PROGRAM = "datums_multistory_stairs"


def _compile(ver: str):
    prog = {k: v for k, v in PROGRAMS[_PROGRAM].items() if k != "__ver__"}
    return compile_program(prog, revit_version=ver, snapshot=GROUND_SNAPSHOT)


class TheBoundaryStandsWhereItWasMeasured(unittest.TestCase):

    def test_net48_refuses_with_a_typed_diagnostic(self):
        for ver in NET48_VERSIONS:
            with self.subTest(ver=ver):
                out = _compile(ver)
                self.assertFalse(out.ok, f"{ver}: тело собралось — отказ пропал")
                codes = {d.code for d in out.diagnostics}
                self.assertIn("KIR-E003", codes, f"{ver}: коды {codes}")

    def test_the_refusal_carries_the_route_and_not_only_the_ban(self):
        """The error must name the ROUTE, or it only reports a prohibition.

        A model that reads "unavailable" does not know what to do next; a
        model that reads "works on 2025/2026, on 2021-2024 use a separate
        create_stairs program per level" does. BOTH addresses of the route
        are checked, not just the presence of words in general.
        """
        message = _compile("2021").diagnostics[0].message_ru
        for token in ("обновить плагин", "2025", "create_stairs",
                      "System.dll", "ISet"):
            with self.subTest(token=token):
                self.assertIn(token, message, f"в отказе нет «{token}»: {message}")

    def test_net8_still_emits_and_still_names_iset(self):
        """A PASS control: the boundary hasn't eaten the capability where
        it actually exists.

        Without this half, a refusal that spread across all six versions
        would look exactly like the boundary doing its ordinary job.
        """
        for ver in NET8_VERSIONS:
            with self.subTest(ver=ver):
                out = _compile(ver)
                self.assertTrue(out.ok, f"{ver}: оп отказал там, где законен")
                self.assertIn("System.Collections.Generic.ISet", out.csharp,
                              f"{ver}: ISet исчез из эмиссии — тело изменилось, "
                              f"и причина отказа на net48 больше не та")

    def test_the_refusal_dies_with_its_cause(self):
        """The refusal must disappear once the client learns to link
        `ISet`.

        What gets asked is the LIVE closure of the deployed plugin, not a
        constant here: the `NET48_VERSIONS` list is our own decision,
        while the presence of `ISet` in the client is a fact, and it can
        change without us. The day that fact changes must go red here, not
        slip by unnoticed.
        """
        # The test directory has lived INSIDE the package since the split
        # on 27.08, not next to it.
        tests_dir = Path(__file__).resolve().parents[1] / "tests"
        if not tests_dir.is_dir():          # a foreign tree — we don't stay silent, we speak up
            self.skipTest(f"нет каталога {tests_dir}: замыкание не спросить")
        if str(tests_dir) not in sys.path:
            sys.path.insert(0, str(tests_dir))
        try:
            import bridge_reference_closure as brc
        except ImportError as exc:          # no instrument does not mean "no findings"
            self.skipTest(f"замыкание не импортируется ({exc}) — прибор "
                          f"отсутствует, и это не подтверждение отказа")
        deployed = brc.type_index("net48", "deployed")
        self.assertNotIn(
            "System.Collections.Generic.ISet", deployed,
            "развёрнутый плагин теперь связывает ISet на net48 — причина "
            "отказа исчезла. Сними границу в datum_emit.emit_multistory_stairs "
            "и запись 'datums_multistory_stairs' из E003_EXPECTED_BELOW.")
        # a FAIL control for the probe: in the declared profile ISet MUST
        # be present, otherwise the type index has forgotten how to answer
        # and the check above is a vacuum
        self.assertIn(
            "System.Collections.Generic.ISet",
            brc.type_index("net48", "declared"),
            "ISet не найден и в declared — сломан индекс типов, а не клиент")


if __name__ == "__main__":
    unittest.main()
