# -*- coding: utf-8 -*-
"""THE "FINAL RESULT" INSTRUMENT: one residential complex passes all eight
steps of the mandate.

The mandate `.work/stabilize-SujqrS/OFFLINE_KIR_MARATHON_RU.md`, "The Final
Result and the Boundary of Honesty": "One elaborate, saved residential
complex goes through create/open, a geometric change, refinement,
analysis/repair, group editing, closing the application, and
continuation."

🔴 WHAT IS CHECKED HERE, AND WHAT IS NOT. Each step is a separate check of
the RESULT by number: the head, history, bodies, volumes (by a closed-form
formula, not the product), sets of outputs, findings, the state of the
assignment, the process exit code. The mere presence of a line in the
report does NOT COUNT as an instrument. Live acceptance, Revit, and the
full product are NOT closed by these numbers: each step's `not_run` line
says so out loud, and the test reads it.

🔴 RED STEPS ARE PINNED, NOT ROUTED AROUND. Wherever the public path does
not hold, the test PINS the refusal along with its address: it must
disappear by a fix from the owner of that holding, not by rewriting the
instrument.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("OCP.BRepPrimAPI", reason="сцена ЖК строится настоящим OCCT")

from kir.project import _canonical, output_id  # noqa: E402
from kir.project_store import ProjectStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHILD_ENV = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1",
                 PYTHONNOUSERSITE="1")


def _walkthrough():
    """A scene from `examples/` — ONLY on call, not at module load.

    🔴 THERE USED TO BE A HARD EXIT HERE (fix on 07.09.2026). `from examples
    import X` at module level executes AT COLLECTION time: wherever
    `examples/` is absent — and it is absent for anyone who installed the
    wheel (`[tool.setuptools.packages.find] include = ["kir*"]`) — this
    crashed SUITE COLLECTION, not a single test.

    🔴 AND SPECIFICALLY `from examples import ...`, NOT
    `importlib.import_module(name)`. The latter would have moved the name
    into a STRING, where a walk over the boundary cannot see it: the debt
    would not have become soft, it would have DISAPPEARED FROM THE LEDGER,
    and the gate would have gone green without untangling anything. The
    tree has already paid exactly this price — the neighboring environment
    gate (`test_the_environment_has_one_door`) was set off by 24 references
    through a helper, where the name was a call ARGUMENT. The exit stays
    visible, is named in the registry with a reason, and fails AT THE
    CALLER, rather than taking collection down with it.
    """
    from examples import final_result_walkthrough

    return final_result_walkthrough


def _capture_walk():
    """A second scene of the same file, by the same argument — see
    :func:`_walkthrough`."""
    from examples import final_result_capture_walkthrough

    return final_result_capture_walkthrough


#: The order of the steps is from the mandate verbatim, not from the
#: instrument's convenience.
MANDATE_STEPS = ("1. создание", "2. открытие", "3. геометрическое изменение",
                 "4. террасы", "5. refinement", "6. анализ", "7. анализ/repair",
                 "8. командное редактирование",
                 "9. закрытие приложения и продолжение",
                 "10. третье изменение после reopen",
                 "11. repair после третьего изменения")


@pytest.fixture(scope="module")
def walk(tmp_path_factory):
    """ONE run per module: the eight steps proceed over a SINGLE project
    file."""
    root = tmp_path_factory.mktemp("final-result")
    rows = _walkthrough().run(root)
    return rows, Path(root)


@pytest.fixture(scope="module")
def rows(walk):
    return {row["step"]: row for row in walk[0]}


def _store(walk):
    return ProjectStore.open(walk[1] / "workspace" / f"{_walkthrough().STORE_NAME}.sqlite")


def _instance(revision, key):
    return next(item for item in revision.instances if item.key == key)


# ── shared: the mandate's steps and the boundary of honesty ────────────────────────────────
def test_every_mandate_step_is_walked_in_its_own_order(walk):
    assert tuple(row["step"] for row in walk[0]) == MANDATE_STEPS


def test_no_step_claims_revit_a_live_model_or_a_real_llm(walk):
    """🔴 A GREEN STEP DOES NOT CLOSE LIVE ACCEPTANCE, and this is NOT a
    promise, it is a field."""
    for row in walk[0]:
        assert row["not_run"]["native_execution"] == "not_run", row["step"]
        assert row["not_run"]["live_model_observed"] is False, row["step"]
        assert row["not_run"]["revit_started"] is False, row["step"]
        assert row["not_run"]["real_llm_calls"] == 0, row["step"]
        assert row["not_run"]["whole_project_acceptance"] == "not_established", row["step"]


# ── 1–2. creation and opening ───────────────────────────────────────────────
def test_the_saved_complex_is_five_revisions_five_instances_and_one_body(rows):
    numbers = rows["1. создание"]["numbers"]
    assert rows["1. создание"]["holds"], rows["1. создание"]["red"]
    assert numbers["history"] == 5
    assert numbers["instances"] == 5
    assert numbers["outputs"] == 25
    assert numbers["bodies"] == 1


def test_another_process_opens_the_same_numbers(rows):
    assert rows["2. открытие"]["holds"], rows["2. открытие"]["red"]
    assert rows["2. открытие"]["numbers"] == rows["1. создание"]["numbers"]


# ── 3. a geometric change ────────────────────────────────────────────
def test_the_authoring_path_puts_three_more_real_bodies_into_the_saved_project(rows):
    row = rows["3. геометрическое изменение"]
    assert row["holds"], row["red"]
    assert row["numbers"]["bodies_before"] == 1
    # podium + shell + stylobate + ramp + a curved A-B transition
    assert row["numbers"]["bodies_after"] == 5
    assert row["numbers"]["shell_twist_deg"] == 15.0
    assert row["numbers"]["shell_shift_mm"] == [1000.0, 700.0]


def test_the_authored_volumes_match_a_closed_formula_not_the_product(rows):
    """🔴 A NUMBER THAT WAS NOT IN THE INPUT. Simpson's prismatoid formula
    for the loft's ruled side wall, and a box minus a cylinder for the
    boolean: this file computes both quantities, not KIR. The match is
    evidence that the body was actually BUILT."""
    import math

    walkthrough = _walkthrough()
    numbers = rows["3. геометрическое изменение"]["numbers"]

    def shoelace(points):
        total = 0.0
        for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1]):
            total += x0 * y1 - x1 * y0
        return abs(total) / 2.0

    def prismatoid(low, top, height):
        # The vertices are interpolated LINEARLY, so the cross-section area
        # is quadratic in height, and Simpson's rule here is EXACT, not an
        # approximation.
        middle = [[(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0] for a, b in zip(low, top)]
        return height / 6.0 * (shoelace(low) + 4 * shoelace(middle) + shoelace(top))

    low = [list(point) for point in walkthrough.TOWER_C_FOOTPRINT]
    top = walkthrough.twisted(walkthrough.TOWER_C_FOOTPRINT,
                              angle_deg=walkthrough.TOWER_C_TWIST_DEG,
                              taper=walkthrough.TOWER_C_TAPER,
                              shift=walkthrough.TOWER_C_SHIFT_MM)
    # 🔴 THE ROTATION SHOWS UP IN THE NUMBER: the upper profile is not
    # parallel to the lower one, and the volume DIFFERS from a straight
    # taper of the same compression.
    assert top != [[low[0][0], low[0][1]]] * 4
    assert numbers["shell_volume_mm3"] == pytest.approx(
        prismatoid(low, top, walkthrough.TOWER_C_HEIGHT_MM), rel=1e-6)
    plinth = (14000 * 9000 * walkthrough.TOWER_C_PLINTH_HEIGHT_MM
              - math.pi * walkthrough.TOWER_C_ATRIUM_RADIUS_MM ** 2
              * walkthrough.TOWER_C_PLINTH_HEIGHT_MM)
    assert numbers["plinth_volume_mm3"] == pytest.approx(plinth, rel=1e-4)
    # The cut is not just a marker: the stylobate has one more face than
    # the box.
    assert numbers["plinth_face_count"] == 7 and numbers["shell_face_count"] == 6
    bridge_low = [list(point) for point in walkthrough.BRIDGE_FOOTPRINT]
    bridge_top = walkthrough.twisted(walkthrough.BRIDGE_FOOTPRINT,
                                     angle_deg=walkthrough.BRIDGE_TWIST_DEG,
                                     taper=walkthrough.BRIDGE_TAPER,
                                     shift=walkthrough.BRIDGE_SHIFT_MM)
    assert numbers["bridge_volume_mm3"] == pytest.approx(
        prismatoid(bridge_low, bridge_top, walkthrough.BRIDGE_HEIGHT_MM), rel=1e-6)


# ── 4. refinement ──────────────────────────────────────────────────────────
def test_the_source_change_partitions_every_output_and_asks_before_touching_a_wall(rows):
    row = rows["5. refinement"]
    assert row["holds"], row["red"]
    numbers = row["numbers"]
    # 🔴 23, NOT 21. The section's program is 21 instance outputs PLUS two
    # declared types (wall and floor), adopted by the parentage record
    # (`adopt_foreign_members`). The sum of the three sets covers it
    # entirely: no op disappears silently. The same number is held by the
    # neighboring instrument `test_a_source_change_names_all_three_sets`.
    assert numbers["recomputed"] + numbers["preserved"] + numbers["needs_decision"] == 23
    assert numbers["recomputed"] == 3
    assert numbers["needs_decision"] == 3
    assert numbers["questions_asked"] == 3


def test_the_answer_closes_every_question_and_names_what_it_conceded(rows):
    numbers = rows["5. refinement"]["numbers"]
    assert numbers["questions_left"] == 0
    assert numbers["answers_given"] == 1
    # The concession in the decision is a NUMBER: the author asked for an
    # atrium up to 9500, got 8885.
    assert numbers["conceded_mm"] == [615.0]
    assert numbers["head_moved_on_answer"] is True
    assert numbers["head_moved_on_second_change"] is True


# ── 4. terraces ─────────────────────────────────────────────────────────────
def test_the_section_carries_two_slab_widths_and_the_change_proves_the_terrace(rows):
    """🔴 THE SETBACK IS TWO NUMBERS, NOT A PLAN VIEW.

    The first: the slab outlines by level. The second: the very same
    facade fix changes the area of the stepped-back level by a DIFFERENT
    amount — exactly `(width − setback) · |dy|`. This file computes both
    quantities, not the product.
    """
    numbers = rows["4. террасы"]["numbers"]
    assert numbers["floors"] == 3
    assert numbers["slab_widths_mm"] == [12200.0, 14000]
    assert numbers["levels_per_width"] == {"14000": 2, "12200.0": 1}
    assert numbers["terrace_steps"] == 1
    assert numbers["setback_mm"] == 1800.0
    assert numbers["atrium_holes"] == 3
    assert numbers["deviation_matches_closed_formula"] is True
    assert numbers["deviation_mm2"] == [9760000.0, 11200000.0, 11200000.0]
    assert numbers["expected_mm2"] == numbers["deviation_mm2"]
    # The facade fix drags along the corners: 3 floors + 3 facades + 6
    # adjoining ends.
    assert numbers["recomputed"] == 12
    assert numbers["needs_decision"] == 0


def test_the_generator_makes_two_terrace_tiers_without_moving_the_old_number(rows):
    """🔴 PROVENANCE: THIS WAS RED R3, CLOSED ON 07.09.2026 ADDITIVELY.

    Measurement before: exactly ONE setback, always on the top storey
    (`current_width = width - (setback if number == storeys else 0)`), so
    Q01's "terraces," plural, had nothing to show.

    The fix is ADDITIVE: optional `terrace_storeys` (default 1) and
    `terrace_setback_step_mm` (default 0). The defaults reproduce the
    previous number exactly, and this is what is CHECKED here. A section
    with two tiers lives at its own address and gives THREE outlines:
    14000, 12800, 12200 — a setback of 1800 at the top and 1200 a tier
    below, a step of 600.
    """
    numbers = rows["4. террасы"]["numbers"]
    assert rows["4. террасы"]["red"] is None, rows["4. террасы"]["red"]
    assert numbers["default_section_untouched"] is True
    assert numbers["terrace_steps"] == 1
    assert numbers["terraced_instance"] == "tower-d"
    assert numbers["terraced_storeys"] == 2 and numbers["terraced_step_mm"] == 600
    assert numbers["terraced_widths_mm"] == [14000, 12800, 12200]
    assert numbers["terraced_distinct"] == 3


# ── 5. analysis ──────────────────────────────────────────────────────────────
def test_the_analysis_reads_every_declared_body_and_names_its_pairs(rows):
    row = rows["6. анализ"]
    assert row["holds"], row["red"]
    numbers = row["numbers"]
    assert numbers["bodies_declared"] == numbers["bodies_with_geometry"] == 5
    pairs = {tuple(item[:3]) for item in numbers["pairs"]}
    assert pairs == {
        ("contained", "possible", "tower-c/plinth x tower-c/shell"),
        ("intersect", "possible", "parking-ramp/ramp x podium/atrium-volume"),
        ("intersect", "possible", "podium/atrium-volume x tower-c/plinth"),
        ("intersect", "possible", "podium/atrium-volume x tower-c/shell"),
    }
    depth = {tuple(item[:3]): item[3] for item in numbers["pairs"]}
    assert depth[("intersect", "possible",
                  "parking-ramp/ramp x podium/atrium-volume")] == pytest.approx(1500.0, abs=1e-3)


# ── 6. analysis/repair ───────────────────────────────────────────────────────
def test_the_repair_of_an_author_parameter_removes_exactly_its_own_pair(rows):
    numbers = rows["7. анализ/repair"]["numbers"]
    assert numbers["findings_before"] == 4
    assert numbers["findings_after_ramp"] == 3
    assert numbers["ramp_depth_mm"] == pytest.approx(1500.0, abs=1e-3)
    # Lift = depth 1500 + the default gap of 50. Both quantities are
    # declared.
    assert numbers["ramp_lift_mm"] == pytest.approx(1550.0, abs=1e-3)
    assert numbers["head_moved"] is True


def test_a_body_that_came_through_authoring_is_repaired_by_moving_the_body(rows):
    """🔴 PROVENANCE: THIS WAS RED R1 OF THE END-TO-END INSTRUMENT, CLOSED
    ON 07.09.2026.

    Measurement before (this same file, the previous revision): in the
    author's program (`geometry_authoring.author_project` /
    `attach_recipe_bodies`), all bodies of one instance share ONE set of
    parameters — shape is set by the registry's operations, not by a box
    keyed on the output name. The only strategy at the time, `raise_clear`,
    fixes precisely the box and refused: `raise_clear needs a box parameter
    named 'shell' on instance 'tower-c'`. So the pair found at step 5,
    `tower-c/plinth × tower-c/shell`, could not be fixed AT ALL, and the
    loop "finish, then MODIFY a complex project" never closed on rich
    geometry.

    The law after the fix: the second strategy,
    `kir.project_fix.RAISE_CLEAR_BODY`, moves the BODY ITSELF by
    translating the frame and does not touch the author's parameters — so
    the NEIGHBOR's bundle on the same instance stays the same (otherwise
    `validate_geometry_bindings` would have declared it foreign).
    """
    numbers = rows["7. анализ/repair"]["numbers"]
    assert rows["7. анализ/repair"]["red"] is None, rows["7. анализ/repair"]["red"]
    assert numbers["authored_relation"] == "contained"
    # Nesting for the shell's full height: 25200 of extent + 50 of gap.
    assert numbers["authored_lift_mm"] == pytest.approx(25250.0, abs=1e-3)
    # Both fixed pairs are gone: 4 -> 3 (ramp) -> 1 (stylobate and its
    # touch).
    assert numbers["findings_after_authored"] == 1
    # 🔴 THE NEIGHBOR'S FIGURE IS ITSELF THE PROOF THAT ONE BODY WAS MOVED.
    assert numbers["sibling_bundle_unchanged"] is True
    assert numbers["untouched_instances_identical"] == 3


def test_the_default_strategy_still_refuses_that_shape_and_names_the_other(rows):
    """A NEGATIVE CONTROL: there is NO silent switch to the second
    strategy.

    The contract "shape set by a recipe → the lift refuses BY NAME, rather
    than being forced through" is held by
    `kir/tests/test_a_fix_survives_a_restart.py::
    test_the_strategy_refuses_a_shape_it_cannot_raise`. A silent switch
    would turn a named refusal into a success; so the refusal remains, but
    it must name a way out — otherwise a human runs into a wall with no
    door.
    """
    numbers = rows["7. анализ/repair"]["numbers"]
    assert numbers["default_strategy_refused"] is True
    assert numbers["refusal_names_raise_clear_body"] is True


# ── 7. group editing ────────────────────────────────────────────
def test_the_team_edit_produces_a_proposal_that_waits_for_a_person(rows):
    row = rows["8. командное редактирование"]
    assert row["holds"], row["red"]
    numbers = row["numbers"]
    assert numbers["sealed_before_handoff"] is True
    assert numbers["state"] == "submitted"
    assert numbers["spare_state"] == "assigned"
    assert numbers["calls"] == 1
    assert numbers["tower_b_height_before"] == 18000
    # The responder is named FROM THE RESPONSE, not from a flag: there is
    # no real LLM in the tree.
    assert numbers["provider_id"] == "tape/deterministic"
    assert row["not_run"]["real_llm_calls"] == 0


# ── 8. closing the application and continuation ───────────────────────────────────
def test_the_application_closes_by_signal_and_another_process_continues(rows):
    import signal

    row = rows["9. закрытие приложения и продолжение"]
    assert row["holds"], row["red"]
    numbers = row["numbers"]
    assert numbers["exit_code"] == -signal.SIGTERM
    assert numbers["ports_differ"] is True
    assert numbers["head_survived"] is True
    assert numbers["head_after_reopen"] == numbers["durable_head"]
    assert numbers["submitted_before"] == numbers["submitted_after_reopen"] == 1
    assert numbers["accepted_tasks"] == 1
    assert numbers["head_moved_on_accept"] is True
    # CONTINUATION IS MEASURED BY A VALUE IN THE PROJECT, not by a response
    # code.
    assert numbers["tower_b_height_after"] == 21600


def test_the_reopened_application_still_sees_the_human_decision(rows):
    assert rows["9. закрытие приложения и продолжение"]["numbers"][
        "answered_decisions_after_reopen"] == 1


# ── negative controls ─────────────────────────────────────────────────
def test_a_rejection_does_not_move_the_head(rows):
    numbers = rows["9. закрытие приложения и продолжение"]["numbers"]
    assert numbers["reject_status"] == 200
    assert numbers["reject_state"] == "revoked"
    assert numbers["reject_moved_head"] is False


def test_a_decision_taken_on_a_stale_head_is_refused_by_name(rows):
    numbers = rows["9. закрытие приложения и продолжение"]["numbers"]
    assert numbers["stale_accept_status"] == 409
    assert numbers["stale_accept_refusal"] == "head_moved_since_read"


def test_a_wrong_before_value_is_refused_and_moves_nothing(walk):
    """A wrong expected head value — a refusal by name, not a silent
    write."""
    from kir.project_store import ProjectStoreError, StoreConflict

    path = walk[1] / "workspace" / f"{_walkthrough().STORE_NAME}.sqlite"
    store = ProjectStore.open(path, readonly=False)
    head = store.head()
    candidate = head.revise(expected_revision=head.revision_id,
                            intent=head.intent + " (контроль)")
    with pytest.raises((StoreConflict, ProjectStoreError)):
        store.commit(candidate, expected_revision="0" * 64)
    assert ProjectStore.open(path).head().revision_id == head.revision_id, \
        "отказанная запись всё-таки сдвинула голову"


def test_an_answer_outside_the_declared_choices_is_refused(walk):
    from kir.project_refinement import RefinementError, answer_question

    store = ProjectStore.open(walk[1] / "workspace" / f"{_walkthrough().STORE_NAME}.sqlite",
                              readonly=False)
    with pytest.raises(RefinementError) as caught:
        answer_question(store, "0" * 16, "лишь бы что")
    assert caught.value.code == "unknown_question"


def test_the_untouched_podium_is_byte_identical_from_its_first_revision(walk):
    """The preservation of what was untouched — by the BYTES of the
    neighboring instance, not by a word."""
    store = _store(walk)
    history = store.history()
    first = next(revision for revision in history
                 if any(item.key == "podium" for item in revision.instances))
    head = store.head()
    assert _canonical(_instance(first, "podium").to_dict()) == \
        _canonical(_instance(head, "podium").to_dict())
    # A CONTROL FOR THE COMPARISON'S ABILITY: tower B DID change across the
    # same revisions.
    assert _canonical(_instance(first, "tower-b").to_dict()) != \
        _canonical(_instance(head, "tower-b").to_dict())


def test_a_brand_new_process_reads_the_same_head_history_and_decision(walk):
    """Continuation is proven by a process that has neither the objects nor
    the memory."""
    path = walk[1] / "workspace" / f"{_walkthrough().STORE_NAME}.sqlite"
    code = ("import json,sys; sys.path.insert(0, %r);"
            "from kir.project_store import ProjectStore;"
            "from kir.project_refinement import answered_decisions, open_questions;"
            "from kir.project import _thaw;"
            "s=ProjectStore.open(%r);h=s.head();"
            "b=next(i for i in h.instances if i.key=='tower-b');"
            "print(json.dumps({'head':h.revision_id,'history':len(s.history()),"
            "'decisions':len(answered_decisions(s)),'open':len(open_questions(s)),"
            "'tower_b_height':_thaw(b.outputs[0].operation)['height_mm']}))"
            ) % (str(ROOT), str(path))
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=CHILD_ENV,
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    seen = json.loads(done.stdout.strip().splitlines()[-1])
    numbers = {row["step"]: row["numbers"] for row in walk[0]}
    # 🔴 CHECKING AGAINST STEP 9'S HEAD IS NO LONGER POSSIBLE: after the
    # application closed, the project lived through YET ANOTHER, third,
    # source change (step 10). The new process must see the LATEST saved
    # state, not the one we left on.
    store = ProjectStore.open(path)
    assert seen["head"] == store.head().revision_id
    assert seen["history"] == len(store.history())
    # After step 10, the history was also advanced by a second repair loop
    # (step 11).
    assert seen["history"] > numbers["10. третье изменение после reopen"]["history"]
    assert seen["decisions"] == 1
    assert seen["open"] == 0
    assert seen["tower_b_height"] == 21600


# ── 10–11. the project's life AFTER closing the application ──────────────────────────
def test_a_third_source_change_moves_the_second_facade_after_reopen(rows):
    """A THIRD fix — a SECOND facade, on a project that has lived through
    someone else's moves.

    🔴 PROVENANCE: the facade side used not to be named at all — the fix
    moved y=0 and only that. Now the side is a word from a closed list, the
    default is the old one, so the first two fixes did not shift.
    """
    row = rows["10. третье изменение после reopen"]
    assert row["holds"], row["red"]
    numbers = row["numbers"]
    assert numbers["change_kind"] == "facade_curve"
    assert numbers["facade_side"] == "max_y"
    assert numbers["second_facade_y_mm"] == 9600.0
    assert numbers["walls_on_the_second_facade"] == 3
    assert numbers["free_ends"] == 0
    assert numbers["recomputed"] == 12
    assert numbers["recomputed"] + numbers["preserved"] == 23
    assert numbers["needs_decision"] == 0 and numbers["open_questions"] == 0
    assert numbers["head_moved"] is True
    assert numbers["decisions_before"] == numbers["decisions_after"] == 1
    assert numbers["untouched_instances_identical"] == 3


def test_the_facade_side_is_a_word_from_a_closed_list(rows):
    assert "min_y/max_y" in rows["10. третье изменение после reopen"]["not_run"][
        "facade_sides"]


def test_the_second_repair_round_closes_when_the_lift_is_named(rows):
    """🔴 PROVENANCE: THERE WERE TWO REDS BACK TO BACK HERE, BOTH CLOSED ON
    07.09.2026.

    R4: moving the CURVED body changed its BRep, and the lift refused with
    `authored_body_needs_recipe_rebind` — the loop on the loft never even
    began. Now `rebind_body_frame` does not go into the kernel: only the
    manifest's `frame` field changes, the BRep stays byte-for-byte the
    same, and the proposal BUILDS.

    R5: the automatic depth was not enough. The lift is computed from the
    overlap of THIS pair (50 mm), while a third body stands above the
    target — the stylobate, raised at step 7 — and the gate
    `fix_creates_new_conflict` correctly rejected worsening the neighbor.
    The way out is declared by the module itself: name the lift directly
    (`lift_mm`). Here it is not eyeballed but computed from the report's
    extents — the scene's ceiling plus the gap minus the target's bottom,
    28900 mm — and the loop closes: findings go 1 → 0.
    """
    numbers = rows["11. repair после третьего изменения"]["numbers"]
    assert rows["11. repair после третьего изменения"]["red"] is None
    assert numbers["pair"] == "podium/atrium-volume x tower-c/shell"
    assert numbers["target"] == "tower-c/shell"
    # The automatic lift is NAMED and its REFUSAL is NAMED — there is no
    # silent substitution.
    assert numbers["automatic_lift_mm"] == pytest.approx(50.0, abs=1e-3)
    assert numbers["automatic_lift_refused"] is True
    assert "fix_creates_new_conflict" in numbers["refusal_of_the_automatic_lift"]
    # The explicit lift comes from the report's extents, not from thin air.
    assert numbers["lift_mm"] == pytest.approx(28900.0, abs=1e-3)
    # THE LOOP CLOSED.
    assert numbers["findings_before"] == 1 and numbers["findings_after"] == 0
    assert numbers["head_moved"] is True
    assert numbers["untouched_instances_identical"] == 4


# ── R2 CLOSED: an unprovable gap refuses by name and names the action ───
def test_an_undeclared_wall_type_refuses_by_name_and_its_action_closes_the_question(tmp_path):
    """🔴 PROVENANCE: THIS WAS RED R2 OF THE END-TO-END INSTRUMENT, CLOSED
    ON 07.09.2026.

    Measurement before (this same file, the previous revision): on the
    saved residential complex, RIGHT AFTER detailing, `_wall_half_width`
    returned `None`, `_shrunk_atrium` trimmed the atrium EXACTLY to the
    axis, `_still_open` counted a touch as an intersection — 3 asked, 3
    ANSWERED, 3 stayed open forever, and `apply_source_change` went on
    refusing with `decision_required`. The reason for the question, at the
    same time, named someone else's business: "the contour still touches
    this axis."

    The law after the fix (`kir/project_refinement.py:_GAP_CODE`): half the
    width is DECLARED by the wall type, it cannot be invented on the
    author's behalf, so the answer that needs it REFUSES BY NAME with
    `wall_type_required_for_gap`, names the address and the action — and
    writes nothing. The pin here is positive: refuse → declare the type →
    0 open → the next source change proceeds.

    🔴 WHY THIS PIN IS NOT A DUPLICATE. The neighboring instrument for the
    law itself (`kir/tests/test_a_gap_needs_a_declared_wall_type.py`) holds
    it on the `_scene()` assembled in memory. Here the same law is measured
    on the FILE that the public CLI `examples/residential_refinement.py
    --store` produces, that is, on the carrier of the final result: the
    red lived exactly there.
    """
    from examples import residential_refinement as example
    from examples import residential_typed_section as typed
    from kir.project import _digest
    from kir.project_refinement import (RefinementError, answer_question,
                                        answered_decisions, apply_source_change,
                                        open_questions, record_pending_change)
    from kir.tests.fixtures import GROUND_SNAPSHOT

    path = tmp_path / "untyped.sqlite"
    example.create_store(path)
    store = ProjectStore.open(path, readonly=False)
    source_id = output_id(_walkthrough().PROJECT, "tower-a-concept", "concept-volume")
    record_pending_change(store, store.head(), source_output_id=source_id,
                          change=_walkthrough().ATRIUM_TO_THE_WALL)
    asked = [question.question_id for question in open_questions(store)]
    address = {question.question_id: question.address for question in open_questions(store)}
    assert len(asked) == 3
    head_with_the_question = store.head().revision_id

    # 1. A REFUSAL BY NAME, WITH AN ADDRESS AND AN ACTION — instead of an
    # eternal question.
    for question_id in asked:
        with pytest.raises(RefinementError) as caught:
            answer_question(store, question_id, "keep_wall_and_shrink_atrium")
        assert caught.value.code == "wall_type_required_for_gap", str(caught.value)
        assert address[question_id][:12] in str(caught.value), "отказ без адреса"
        assert "create_wall_type" in str(caught.value), "отказ без действия"

    # 2. THE REFUSAL WRITES NOTHING: no decision, no resolved question, no
    # new head.
    assert answered_decisions(store) == ()
    assert len(open_questions(store)) == 3
    assert store.head().revision_id == head_with_the_question

    # 3. THE ACTION CLOSES THE QUESTION: the declared layers give a
    # half-width of 115 mm.
    head = store.head()
    section = next(item for item in head.instances if item.key == "tower-a")
    declared = typed.add_section_types(
        head,
        source=store.get(_digest(section.metadata["refinement"]["source"]["revision_id"],
                                 "source.revision_id")),
        expected_revision=head.revision_id,
        wall_name="KIR_Section_Wall_230",
        wall_layers=[{"width_mm": 15, "function": "Finish1"},
                     {"width_mm": 200, "function": "Structure", "material": "Бетон М300"},
                     {"width_mm": 15, "function": "Finish2"}],
        wall_source_type={"by": "element_id",
                          "value": GROUND_SNAPSHOT["wall_types"][0]["id"]},
        floor_name="KIR_Section_Floor_260",
        floor_layers=[{"width_mm": 200, "function": "Structure", "material": "Бетон М300"},
                      {"width_mm": 50, "function": "Substrate"},
                      {"width_mm": 10, "function": "Finish1"}],
        floor_source_type={"by": "element_id",
                           "value": GROUND_SNAPSHOT["floor_types"][0]["id"]})
    store.commit(declared, expected_revision=head.revision_id)
    assert len(open_questions(store)) == 3, "объявление типа не должно снимать вопрос само"

    for question_id in [item.question_id for item in open_questions(store)]:
        if any(item.question_id == question_id for item in open_questions(store)):
            answer_question(store, question_id, "keep_wall_and_shrink_atrium")
    assert len(open_questions(store)) == 0, "вопрос снова не закрылся — закон не держит"
    decisions = answered_decisions(store)
    assert len(decisions) == 1
    # The concession is a NUMBER: the author asked for an atrium up to
    # 9500, got 8885 (axis 9000 − 115).
    assert [row["conceded_mm"] for row in decisions] == [615.0]

    # 4. AND THE NEXT SOURCE CHANGE PROCEEDS — where before there stood an
    # eternal `decision_required`.
    before = store.head().revision_id
    after = apply_source_change(store, store.head(), source_output_id=source_id,
                                change=_walkthrough().FACADE_CURVE)
    assert after != before
    assert len(store.history()) == 9
    assert len(answered_decisions(store)) == 1, "второе изменение потеряло решение"


# ── mandate line 2: an EXISTING capture goes through the round trip ──────────
#
# 🔴 WHY THIS LIVES IN THE SAME FILE. The mandate names "The Final Result"
# as ONE section of three lines, and two of them are about the same
# question: does the public path hold the whole, not just a function.
# Separated into different files, they would drift apart on updates: one
# mandate line closed, the other silently not.
#
# 🔴 THE BUILDING IS REAL, AND WITHOUT IT THE TEST IS SKIPPED, RATHER THAN
# GOING GREEN ON SYNTHETIC DATA. The scenario does have a synthetic capture
# (a fallback path), but the numbers below are taken from `bench_A`:
# substituting the building and leaving the pins would mean measuring a
# different subject while looking green.
from kir.model.snapshot_io import snapshot_file_exists  # noqa: E402

@pytest.fixture(scope="module")
def reverse(tmp_path_factory):
    """ONE round-trip run per module: eight steps over a SINGLE run.

    🔴 THE CORPUS-BASED SKIP MOVED HERE FROM `pytest.mark.skipif`
    (07.09.2026), and this is NOT cosmetic. The marker evaluated
    `capture_walk.CORPUS` AT MODULE LEVEL, that is, it touched `examples/`
    AT COLLECTION time — a lazy import under that kind of check would have
    stayed lazy only in appearance. The reason for the skip is preserved
    verbatim; all ten tests that carried it take this fixture, so the
    number of skips does not change.
    """
    capture_walk = _capture_walk()
    capture_walk = _capture_walk()
    if not snapshot_file_exists(capture_walk.CORPUS / "L0.jsonl"):
        pytest.skip(f"корпус {capture_walk.CORPUS} недоступен на этой машине")
    root = tmp_path_factory.mktemp("reverse-path")
    return {row["step"]: row for row in capture_walk.run(root)}


def test_the_existing_capture_walks_every_step_of_the_reverse_path(reverse):
    assert len(reverse) == 8
    red = [(row["step"], row["red"]) for row in reverse.values() if row["red"]]
    assert red == [], red


def test_the_reverse_path_opens_the_real_run_and_names_its_binding(reverse):
    numbers = reverse["1. открыть существующий capture"]["numbers"]
    assert numbers["elements"] == 4223
    assert numbers["nodes"] == 4223
    assert numbers["edits"] == 0
    assert numbers["side_indexes"] == 4 and numbers["missing_side_indexes"] == 0
    # The binding is FIVE fields (wave 7: the fifth is the document
    # revision, `capture_revision`, a foreign revision →
    # `capture_revision_moved`): an address without it is just a
    # coincidence of numbers.
    assert numbers["binding_fields"] == 5


def test_the_ledger_splits_every_nonempty_field_into_four_states(reverse):
    """🔴 MEASUREMENT OF 07.09.2026 ON `bench_A`, AND THE READ MODE IS
    NAMED.

    The numbers are a property of the mode: `represented` = 26 330 at
    `profiles="none"`, **26 282** at `editable` (the `open_capture`
    default, that is, the public path), and 26 272 at `all`. The pin here
    is on the PUBLIC mode; the neighboring pin of the ledger
    (`kir/decompile/tests/test_a_field_that_never_arrives_must_be_
    named.py`) is on `none` — this is not a discrepancy but two different
    subjects, and each names its own mode.
    """
    numbers = reverse["2. ведомость полей по четырём состояниям"]["numbers"]
    assert numbers["profiles"] == "editable"
    assert numbers["nonempty"] == 58_451
    assert numbers["state_represented"] == 26_282
    assert numbers["state_approximate"] == 1_647
    assert numbers["state_source_data"] == 2_940
    assert numbers["state_unknown"] == 27_582
    assert (numbers["state_represented"] + numbers["state_approximate"]
            + numbers["state_source_data"] + numbers["state_unknown"]
            == numbers["nonempty"])
    assert numbers["state_represented"] + numbers["lost"] == numbers["nonempty"]
    # A loss without an address does not count as named.
    assert numbers["addressed"] == numbers["elements"] == 4223
    assert numbers["rows_total"] == 4223


def test_the_read_element_names_its_host_and_the_state_of_every_field(reverse):
    numbers = reverse["3. прочитать элемент и его связи"]["numbers"]
    assert numbers["door"] == "286533" and numbers["category"] == "OST_Doors"
    assert numbers["op"] == "create_door"
    assert numbers["host"] == "286530" and numbers["host_category"] == "OST_Walls"
    assert numbers["offset_mm"] == 3000.0
    assert "offset_mm" in numbers["editable_fields"]
    # 🔴 THE REAL BUILDING HAS ALL FOUR STATES, AND THIS IS THE MAIN POINT:
    # the loop is declared "with EXPLICIT losses," and an element with no
    # losses would prove the opposite.
    assert numbers["states_of_this_element"] == ["approximate", "represented",
                                                 "source_data", "unknown"]


def test_the_preview_changes_not_one_byte_of_the_run(reverse):
    numbers = reverse["4. предпросмотр без единой записи"]["numbers"]
    assert numbers["proposals"] == 2 and numbers["admissible"] == 2
    assert numbers["files_changed"] == 0 and numbers["files_watched"] >= 19
    assert numbers["wrote_nothing"] is True
    assert all(count > 0 for count in numbers["diff_leaves"])


def test_one_addressed_edit_touches_exactly_one_operation(reverse):
    numbers = reverse["5. приложить правку двери и сохранить в НОВЫЙ каталог"]["numbers"]
    assert numbers["changed_ops"] == 1
    assert numbers["untouched"] == 4222
    assert numbers["edits"] == 1
    assert numbers["saved_files"] >= 19


def test_the_second_change_comes_from_a_new_process_and_finds_the_first(reverse):
    """🔴 A PROPERTY OF DISK, NOT OF MEMORY: the second process sees the
    first fix."""
    numbers = reverse["6. продолжить вторым изменением из НОВОГО процесса"]["numbers"]
    assert numbers["edits_after_reopen"] == 2
    assert numbers["changed_ops"] == 1
    assert numbers["ring_in_saved"] == [[13000.0, 3000.0], [23000.0, 3000.0],
                                        [23000.0, 8500.0], [13000.0, 8500.0]]


def test_the_source_run_is_byte_identical_and_writing_into_it_is_refused_by_name(reverse):
    numbers = reverse["7. исходный прогон не тронут ни байтом"]["numbers"]
    assert numbers["changed"] == 0
    assert numbers["l0_identical"] is True
    assert numbers["l0_sha256_before"] == numbers["l0_sha256_after"]
    assert numbers["refusal_code"] in ("target_inside_source", "target_inside_capture")
    assert numbers["target_created"] is False


def test_the_export_of_the_edited_capture_compiles_and_names_its_refusals(reverse):
    """A compiler refusal is NAMED, not "some programs went missing."""
    numbers = reverse["8. экспорт правленого capture компилируется"]["numbers"]
    assert numbers["compiled"] == numbers["cs_files"]
    assert numbers["compiled"] >= 38
    assert numbers["programs"] >= numbers["compiled"]
    assert numbers["refusal_codes"] == ["KIR-G103"]
    assert numbers["bytes"] > 0


def test_no_step_of_the_reverse_path_claims_revit_or_a_lossless_rebuild(reverse):
    for row in reverse.values():
        assert row["not_run"]["revit_started"] is False, row["step"]
        assert row["not_run"]["real_llm_calls"] == 0, row["step"]
        assert row["not_run"]["native_execution"] == "not_run", row["step"]
        assert row["not_run"]["lossless_reconstruction"] == "not_claimed", row["step"]
