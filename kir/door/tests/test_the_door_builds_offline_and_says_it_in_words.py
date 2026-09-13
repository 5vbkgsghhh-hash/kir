"""The door, end to end, offline: python in, wall out, receipt in words.

The executor is S's `kir/project_pack.py::OfflineExecutor` — a FAKE that says
so in every answer. That is the point: a receipt that reads the same live and
offline is how «ложно-зелёная квитанция» happened (ДОК-A18, 08.09: the door
answered `started: true` twice and produced nothing).
"""
from __future__ import annotations

from kir.door import registry as R

SOURCE = (
    'program = [\n'
    '    create_level(id="L1", elev_mm=0, name="Этаж 1"),\n'
    '    create_wall(id="W1", p0_mm=[0, 0], p1_mm=[6000, 0], height_mm=3000,\n'
    '                level={"by": "ref", "value": "L1"}),\n'
    ']\n'
)


def _ctx():
    from kir.project_pack import OfflineExecutor

    return R.Ctx(role="expert", executor=OfflineExecutor(),
                 versions=("2023", "2026"))


def test_a_wall_is_built_and_the_receipt_is_words():
    out = R.call("kir_build", {"source": SOURCE}, _ctx())
    assert out["ok"] is True and out["built"] is True
    assert out["ops"] == 2
    assert isinstance(out["words"], str) and out["words"].strip()
    assert out["next"] is None


def test_the_receipt_names_the_addresses_of_what_it_built():
    out = R.call("kir_build", {"source": SOURCE}, _ctx())
    assert set(out["addresses"]) == {"L1", "W1"}
    for uid in out["addresses"].values():
        assert isinstance(uid, str) and len(uid) > 10


def test_the_receipt_refuses_to_pass_a_fake_executor_for_revit():
    out = R.call("kir_build", {"source": SOURCE}, _ctx())
    assert "Настоящего Ревита не было" in out["words"]


def test_the_receipt_says_what_nobody_will_check():
    out = R.call("kir_build", {"source": SOURCE}, _ctx())
    assert isinstance(out["unchecked"], str) and out["unchecked"].strip()


def test_it_compiles_for_both_versions_of_the_document():
    out = R.call("kir_build", {"source": SOURCE}, _ctx())
    assert out["compiled"] == {"2023": True, "2026": True}


def test_preview_writes_nothing_and_says_so():
    out = R.call("kir_build", {"source": SOURCE, "preview": True}, _ctx())
    assert out["built"] is False and out["wrote_nothing"] is True
    assert "не записано" in out["words"]


def test_a_program_the_compiler_refuses_never_reaches_the_executor():
    class Loud:
        def execute(self, link_key, program):  # noqa: D102
            raise AssertionError("исполнителя позвали при красной компиляции")

    ctx = R.Ctx(role="expert", executor=Loud())
    out = R.call("kir_build", {"source": 'program = [create_wall(id="W")]'}, ctx)
    assert out["ok"] is False
    assert out["next"]["do"] in {t.name for t in R.TOOLS}


def test_the_sandbox_refusal_keeps_the_line_of_the_models_own_source():
    ctx = _ctx()
    out = R.call("kir_build", {"source": "program = [нет_такой_функции()]"}, ctx)
    assert out["ok"] is False
    # A traceback the model recognises is worth more than our prose; the
    # sandbox already points at the line in ITS source and the door keeps it.
    assert "line" in out
