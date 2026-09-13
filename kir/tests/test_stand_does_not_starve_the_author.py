"""A STAND MUST NOT HAVE THE RIGHT TO CUT THE ANSWER TO THE AUTHOR'S
QUESTION.

🔴 WHY THIS FILE EXISTS (24.08). The stand was handing the model
`json.dumps(kir)[:2500]`. On the RECON turn, the answer to its question
lives in `program_source.stdout` and starts at position 2065 out of 4211 —
meaning the author was getting the first ~435 characters of a
1894-character contract, cut off mid-word. It kept asking
`spec("author_family")` again and again: 10, 11, and 10 again turns across
three runs in a row, zero operations.

The report named this MODEL behavior: "the author did not exit recon".
This was INSTRUMENT behavior. Exactly the shape this same instrument was
catching that same day in acceptance, in the census, and in itself: its own
blindness, recorded against the subject.

The product does NOT cut the receipt at all (`kukai/llm/tools.py` hands the
model the whole answer), so the stand must stay close to the product rather
than being stingier than it: otherwise it is measuring its own stinginess.

🔴 WHOSE SUBJECT THIS IS HERE, AND WHY THIS IS A SEAM ASSERTION AND NOT A
PROOF ABOUT KIR (worked out 04.09.2026). The `loop_meter.py` stand lives in
the HOST's tree, and this is a number, not a matter of taste: the
definitions of `RECEIPT_CHARS` and `_receipt_for_author` in `/opt/kir` are
ZERO (measured by grepping the package), and in
`/opt/kukai-rebuild1/backend/tools/loop_meter.py` there are TWO (lines 304
and 307). Remove any implementation from `/opt/kir` — this file will not so
much as flinch, because it does not touch a single one of them here.

So a green result from this file is NOT evidence about KIR's code, and it
must say so itself. The canon distinguishes two kinds of knowledge of a
foreign tree (`tests/test_the_package_does_not_know_the_host.py`): a
ROUTE — code WALKS a path, and then the path must ask the environment; and
a NARRATIVE — a path is named as evidence, and stays verbatim. Here there
was a ROUTE, hard-coded as a literal, i.e. a machine-local path inside an
environment-agnostic package; the census `tools/host_path_census.py`
counted 22 such files (04.09), and this was one of them.

There is no way to move it into the host's tree — the neighboring project
is not edited from here; so the shape the canon directly permits was
taken, the one already lived in by `test_plural_operand_authority.py`,
`test_record_ratchet.py`, `test_kir_transfer.py`,
`test_clash_in_the_receipt.py`: the host's root is NAMED by the
`KIR_HOST_ROOT` variable, and without it the seam assertions are SKIPPED
WITH A REASON, rather than turning green.

🔴 THE NUMBER BEFORE AND AFTER, TAKEN BY EXECUTION, NOT PROMISED. The
previous edition (`git show HEAD~:` of this file), with `KIR_HOST_ROOT`
pointing at an EMPTY directory, gave `4 passed`: it was not listening to
the variable at all. The current one, on the same root, gives `1 skipped`
— the whole module is skipped, none of the four assertions is executed,
and it is not counted as green.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from kir import env

#: The HOST's root is optional: KIR stands even without it, and then the
#: SEAM assertions (about ITS stand) are skipped with a named reason.
_HOST_ROOT = Path(env.get("KIR_HOST_ROOT", "/opt/kukai-rebuild1/backend"))
TOOLS = _HOST_ROOT / "tools"

if not (TOOLS / "loop_meter.py").is_file():
    pytest.skip(
        f"стенд `loop_meter.py` — прибор ХОЗЯИНА ({TOOLS}); чего он не режет "
        f"автору, отсюда непроверяемо, и молчаливый зелёный здесь читался бы "
        f"как улика о KIR. Назвать корень: KIR_HOST_ROOT",
        allow_module_level=True)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


meter = _load("loop_meter")

#: The shape of the recon turn's live receipt, captured off the door on
#: 24.08.
_ANSWER = "КОНТРАКТ «author_family» — из реестра. " + ("ПОСТУСЛОВИЕ. " * 120)
_RECON = {
    "ok": False, "kir": True, "refused": False, "recon": True,
    "stage": "author_script",
    "diagnostics": [{"code": "KIR-B013", "kind": "Reconnaissance",
                     "message_ru": "разведочный ход" + "…" * 300}],
    "message_ru": "разведочный ход" + "…" * 300,
    "program_source": {
        "language": "python", "author_digest": "d" * 64, "op_count": 0,
        # The ENVIRONMENT signature is needed by the measurement, useless
        # to the author, and it is exactly what was crowding out the
        # answer: the full list of sandbox modules.
        "environment": {"modules": [{"name": f"mod{i}", "version": "1.0"}
                                    for i in range(200)]},
        "isolation": {"namespaces": "user+mount+net", "filesystem": "chroot"},
        "stdout": _ANSWER,
    },
}


def test_the_answer_the_author_asked_for_survives():
    out = meter._receipt_for_author(_RECON)
    assert _ANSWER in out, "ответ на вопрос автора обязан доехать целиком"


def test_the_environment_signature_is_what_gets_dropped():
    """Exactly what the author does not need was thrown out — and this is
    named, not picked to fit a size: the environment signature is needed
    by the MEASUREMENT, not by the author."""
    out = meter._receipt_for_author(_RECON)
    assert "mod199" not in out and "chroot" not in out
    assert "author_digest" in out and "KIR-B013" in out


def test_the_old_blind_slice_would_have_cut_it():
    """🔴 FAIL CONTROL: proof that the defect was real, not imagined."""
    old = json.dumps(_RECON, ensure_ascii=False)[:2500]
    assert _ANSWER not in old


def test_the_cap_is_not_meaner_than_the_product():
    """The product does not cut the receipt at all. The stand's ceiling
    must be an order of magnitude higher than before, otherwise it will
    start measuring its own stinginess again."""
    assert meter.RECEIPT_CHARS >= 8000
