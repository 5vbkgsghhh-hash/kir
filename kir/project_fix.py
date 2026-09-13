"""THE LOOP CLOSES: an analysis finding -> an edit to the AUTHOR'S project ->
a revision in history.

🔴 WHAT IS NEW HERE, AND WHAT WAS TAKEN READY-MADE. The 06.09.2026 recon
showed by measurement that the second half of the cycle is ALREADY built:
a parameter edit → a body recompute → `ChangeProposal` → `accept_proposal`
(CAS) → reopening the store yields a new head, a new body, and a new
parameter. So nothing new is introduced here — no proposal of its own, no
history of its own, no record of its own on disk: the module only
TRANSLATES the finding into an existing `ChangeProposal` and hands it to
the existing `accept_proposal`. `project_merge.py` and `project_store.py`
are not touched by a single line.

THE `raise_clear` STRATEGY AND ITS BOUNDARY. The finding supplies the
PENETRATION DEPTH and the policy clearance; the body is raised along z by
`depth + clearance`. This is an edit to an AUTHOR'S PARAMETER (the box
bounds in the scene's recipe), not a display shift: `touches_display_only`
on a real fix must be `False`, and it is — the body changes in the store,
not its display.

WHAT THE STRATEGY CANNOT DO, AND THIS IS NAMED:
  * only a body whose shape is set by a box in its own output's
    parameters can be raised; for a body whose shape is a recipe with a
    different parameterization, the lift is REFUSED by name, rather than
    forced;
  * the depth is taken from a ROUGH finding if there was no exact phase.
    Raising by the rough depth may turn out to be excessive — and that is
    exactly the case for calling `exact=True`, rather than trusting the
    box;
  * the decision of "which of the two to move" is not derived from
    geometry. What moves is whichever the caller named (`move`), or
    whichever has fewer connections in the scene; the choice is PRINTED
    in `describe()`, rather than made silently.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_CLEARANCE_MM = 50.0

#: Two strategies for the same lift, differing in WHAT EXACTLY they move.
#: `raise_clear` edits an AUTHOR'S PARAMETER — the box under the output's
#: name — and calls the author's callback to recompute the body.
#: `raise_clear_body` moves the BODY ITSELF by translating its frame and
#: does not touch the parameters at all.
#:
#: 🔴 WHY THE SECOND ONE WAS NEEDED (measured 07.09.2026). In an author's
#: program (`geometry_authoring.author_project` /
#: `attach_recipe_bodies`), all bodies of one instance share ONE set of
#: parameters: the shape is set by registry operations, not by a box
#: under the output's name. `raise_clear` refused — "needs a box
#: parameter named 'plinth' on instance 'tower-c'" — and the "finish,
#: then modify" loop never closed on rich geometry. Editing the shared
#: parameters was NOT ALLOWED: `validate_geometry_bindings` checks EVERY
#: body's manifest against the owning instance's parameters, and the
#: neighboring bundles would become foreign.
RAISE_CLEAR = "raise_clear"
RAISE_CLEAR_BODY = "raise_clear_body"


class FixError(Exception):
    """The fix was not constructed. A silent return would read as
    "nothing to fix"."""


@dataclass(frozen=True)
class Proposal:
    """A wrapper over the existing `ChangeProposal`, with the acceptance
    contract's fields."""

    change: Any                       # kir.project_merge.ChangeProposal
    changed_outputs: frozenset
    strategy: str
    explanation: str
    finding_id: str
    touches_display_only: bool = False
    #: The report the proposal was built FROM. It rides along with the
    #: proposal so that `apply_fix` can ask "did this make things worse
    #: for the neighbors" with the SAME measure and WITHOUT a second
    #: argument for every caller: a different measure would compare
    #: different things, and requiring everyone to remember it by hand
    #: would come down to "usually they remember."
    report: Any = None
    #: The world-space lift (mm) and what it became inside the instance's
    #: PARAMETERS. Both are printed: with a rotated frame these are
    #: different numbers, and staying silent about the second one was the
    #: owner's finding (2).
    world_lift_mm: float | None = None
    local_delta_mm: tuple = ()
    frame: tuple = ()

    @property
    def revision(self):
        return self.change.candidate

    def describe(self) -> str:
        return self.explanation


def _finding(report, finding_id):
    for item in report.findings:
        if item.finding_id == finding_id:
            return item
    raise FixError(f"finding is not in this report: {finding_id}")


def _output_of(revision, output_id):
    for instance, output, oid in revision.addressed_outputs():
        if oid == output_id:
            return instance, output
    raise FixError(f"output is not in this revision: {output_id}")


def _box_of(parameters, key):
    box = parameters.get(key)
    if not (isinstance(box, (list, tuple)) and len(box) == 2
            and all(isinstance(p, (list, tuple)) and len(p) == 3 for p in box)):
        return None
    return [[float(v) for v in box[0]], [float(v) for v in box[1]]]


def propose_fix(store, report, finding_id, *, strategy: str = "raise_clear",
                move: str | None = None, clearance_mm: float | None = None,
                lift_mm: float | None = None, rebuild=None):
    """A finding -> a `Proposal` on top of the existing `ChangeProposal`.
    Writes nothing.

    `rebuild(output_key, box) -> GeometryBundle` — how to recompute the
    body after the edit. The recompute is NOT guessed here: the shape is
    known by whoever declared it.
    """
    from kir.project import BodyRepresentation, ModuleInstance, NamedOutput
    from kir.project_merge import ChangeProposal, ProposalScope

    if strategy not in (RAISE_CLEAR, RAISE_CLEAR_BODY):
        raise FixError(f"unknown strategy: {strategy}")
    opened = _open(store)
    revision = opened.head()
    if revision.revision_id != report.revision:
        raise FixError("report describes another revision; analyze the current head")
    finding = _finding(report, finding_id)
    violated = getattr(finding, "status", None) == "clearance_violated"
    # 🔴 `clear` NO LONGER MEANS "NOTHING TO FIX" (owner, 07.09.2026). A
    # pair separated by 10 mm when the requirement is 50 does not
    # intersect — and yet it VIOLATES the requirement. The old line
    # answered "nothing to fix: the pair is clear" for exactly such a
    # finding, that is, it closed it with a word about the RELATION, when
    # the question was about the REQUIREMENT. A `clear` relation with no
    # violation is still nothing to fix, and that remains a refusal.
    # 🔴 "NOT CHECKED" IS NOT "CLEAN" (review6, B-1). The requirement is
    # declared, but the exact phase did not judge it: saying "the pair is
    # clear" would mean passing off IGNORANCE as proven cleanliness — the
    # same thing as the owner's earlier refusal.
    if getattr(finding, "status", None) == "clearance_unverified":
        raise FixError(
            f"clearance_unverified: требование "
            f"{finding.required_clearance_mm or 0.0:.3f} мм заявлено, но точная "
            f"фаза эту пару не судила (грубый зазор "
            f"{'—' if finding.gap_mm is None else format(finding.gap_mm, '.3f')} мм — "
            f"НИЖНЯЯ граница). Спроси `analyze_project(exact=True)` либо назови "
            f"причину, по которой тела недоступны: чинить непроверенное нельзя, "
            f"и объявлять его чистым — тоже")
    if finding.relation == "clear" and not violated:
        raise FixError("nothing to fix: the pair is clear")
    # The early `depth_mm is None` check was REMOVED on 06.09.2026 on
    # purpose: the lift is now computed from the envelope bounds, and a
    # finding with no `depth_mm` (the `contained` relation never has one)
    # is fixed exactly the same way. If there is nothing to compute from,
    # the refusal is named by `_z_clearing_depth` — in one place.
    target_id = move or _lighter(report, finding)
    # 🔴 `move` IS CHECKED AGAINST THE PAIR. Without this line, a third
    # body could be named, and the strategy would obediently raise IT,
    # reporting a fix for a pair it never touched. Measured 06.09.2026: it
    # went through silently.
    if target_id not in (finding.a_output_id, finding.b_output_id):
        raise FixError(
            f"move={target_id[:12]} не входит в пару "
            f"{finding.a_output_id[:12]}×{finding.b_output_id[:12]}: поднимать "
            f"постороннее тело значило бы отчитаться о починке, которой нет")
    instance, output = _output_of(revision, target_id)
    # 🔴 THE PROFILE IS ASKED BEFORE THE BOX, AND THAT IS THE WHOLE POINT
    # OF THE ORDER (B03, 07.09.2026). The "shape is parameterized
    # differently" refusal below speaks about PARAMETERIZATION, while the
    # question for an MEP run is about TYPE: an element that happens to
    # arrive alongside a box and also carries a connector graph,
    # `system_type`, or `slope_min_pct` in its parameters used to pass
    # this check and get raised SILENTLY — meaning a connector tore, the
    # system changed, and the KIR-X004 slope postcondition broke. The
    # declared profile and its named refusal live in
    # `kir/clash/repair_profile.py`; here there is only the seam.
    from kir.clash import repair_profile

    unsupported = repair_profile.classify(instance, output)
    if unsupported is not None:
        code, why = unsupported
        raise FixError(f"{code}: {why}. Заявленный профиль починки — "
                       f"{repair_profile.describe()}")
    box = _box_of(instance.parameters, output.key)
    # 🔴 FALLING BACK TO THE BODY STRATEGY HAPPENS ONLY BY AN EXPLICIT
    # NAME, AND THIS IS A DECISION, NOT AN OVERSIGHT. The first edition on
    # 07.09.2026 fell back BY ITSELF whenever there was no box: every such
    # call used to end in a refusal, so adding the fallback seemed safe. A
    # run showed the cost: `test_a_fix_survives_a_restart.py::
    # test_the_strategy_refuses_a_shape_it_cannot_raise` holds the
    # contract "shape set by a recipe -> the lift REFUSES BY NAME, rather
    # than being forced", and a silent fallback would turn a named
    # refusal into a silent success — exactly the kind of bug this module
    # catches in others. The caller names the strategy; the refusal below
    # says HOW it is named.
    authored = strategy == RAISE_CLEAR_BODY
    if box is None and not authored:
        raise FixError(
            f"raise_clear needs a box parameter named {output.key!r} on instance "
            f"{instance.key!r}; this output's shape is parameterised otherwise"
            + (f". Тело здесь есть: авторская программа кладёт форму в операции "
               f"реестра, а не в коробку на имя выхода — двигать его умеет "
               f"strategy={RAISE_CLEAR_BODY!r} (перенос фрейма тела, авторские "
               f"параметры не трогаются)" if output.geometry is not None else ""))
    if authored and output.geometry is None:
        raise FixError(
            f"{RAISE_CLEAR_BODY} двигает ТЕЛО, а выход {output.key!r} экземпляра "
            f"{instance.key!r} тела не несёт: двигать нечего")
    if not authored and rebuild is None:
        raise FixError("raise_clear needs an explicit rebuild(output_key, box, parameters) callback")

    # For a violated clearance, the margin is taken from the REQUIREMENT
    # ITSELF, not from a default: fixing a violation "by a default 50 mm"
    # when the requirement is 200 would mean reporting a fix that does not
    # exist.
    if clearance_mm is not None:
        clearance = float(clearance_mm)
    elif violated and getattr(finding, "required_clearance_mm", None):
        clearance = float(finding.required_clearance_mm)
    else:
        clearance = DEFAULT_CLEARANCE_MM
    # 🔴 NOT ALL DEPTHS ARE EQUAL, AND THIS IS NOT NITPICKING. For a ROUGH
    # finding, `depth_mm` is the overlap along the SHORTEST axis of the
    # bounds (for a passage with a podium that's 500 mm along z, exactly
    # what needs to be raised). For a neighbor's EXACT finding the same
    # field is computed differently (measured on the same pair: 3000.01),
    # and a z-lift strategy that takes it would raise MORE than needed.
    # Neither of the two numbers is "wrong" — they answer different
    # questions, and that is why the source is PRINTED, and the caller is
    # given `lift_mm` so they can name the lift directly. Choosing for
    # them silently would mean hiding the choice inside the code.
    if lift_mm is not None:
        depth, depth_source = float(lift_mm) - clearance, "явный lift_mm"
    else:
        depth, depth_source = _z_clearing_depth(report, finding, target_id)
    lift = depth + clearance
    # 🔴 THE LIFT IS COMPUTED IN WORLD SPACE, BUT ADDED IN LOCAL SPACE
    # (owner, item 2). `hull_bounds` are bounds IN PROJECT COORDINATES
    # (the one place analysis applies the frame — `_brep_bbox`), so `lift`
    # is a world-space quantity too. But
    # `instance.parameters[output_key]` is a box in the body's LOCAL
    # coordinates. Before 07.09.2026, `z + lift` used to be written here
    # directly, and with a frame rotated 37° around a horizontal axis, the
    # world-space shift came out as `R·(0,0,lift)` — shorter than what was
    # required along z. Measured on `impl3/red-geometry.json`: a lift of
    # 12485.618 was accepted, and after the "fix" the podium×passage pair
    # REMAINED (depth 2464.160). The same probe's control, with a rotation
    # around Z: the defect is INVISIBLE (the local z matches the world
    # one) — which is why the plan's "37° control" had been green:
    # `fixture.frame_translate_rotz` only rotates around z.
    frame = _frame_of(report, target_id)
    delta = _local_delta(frame, (0.0, 0.0, lift), target_id)
    if authored:
        bundle, parameters, axis_note = _move_authored_body(
            opened, instance, output, frame, lift, target_id)
        raised = None
    else:
        raised = [[box[0][k] + delta[k] for k in range(3)],
                  [box[1][k] + delta[k] for k in range(3)]]
    # The instance's parameters are edited AS A WHOLE and handed to the
    # recompute: the store checks the asset's inputs against the owner's
    # inputs, and a body taken with the OLD parameters no longer belongs
    # to this instance.
    if not authored:
        parameters = dict(instance.parameters)
        parameters[output.key] = raised
    # 🔴 THE AXIS RIDES WITH THE BODY, OTHERWISE ONE ELEMENT ENDS UP WITH
    # TWO ADDRESSES. The supported profile is a FREE segment
    # (`p0_mm`/`p1_mm` from `ops_mep`, with no connector graph, no
    # system, and no declared slope). Leaving the axis in place would mean
    # raising the body and abandoning its own route below; shifting ONE
    # end would break the slope. Here both ends get the SAME local
    # addition as the box, so the slope is preserved identically — and
    # this IS CHECKED by a number, not promised.
    axis = None if authored else repair_profile.axis_of(instance.parameters)
    if not authored:
        axis_note = ""
    if axis is not None:
        moved = ([axis[0][k] + delta[k] for k in range(3)],
                 [axis[1][k] + delta[k] for k in range(3)])
        was = repair_profile.slope_pct(axis)
        now = repair_profile.slope_pct(moved)
        if was is not None and (now is None or abs(now - was) > 1e-9):
            raise FixError(
                f"repair_profile_slope_broken: подъём изменил уклон свободного "
                f"отрезка {target_id[:12]} с {was!r} на {now!r} %. Сдвиг обязан "
                f"быть переносом обоих концов, а не правкой одного")
        parameters["p0_mm"], parameters["p1_mm"] = moved[0], moved[1]
        axis_note = ("; ось p0_mm/p1_mm поднята тем же вектором, уклон "
                     + ("не определён (стояк)" if was is None
                        else f"{was:.6f} % сохранён"))
    if not authored:
        bundle = _rebuild_body(rebuild, output.key, raised, parameters, frame, target_id)
    new_output = NamedOutput(output.key, output.operation,
                             BodyRepresentation(bundle.digest, bundle.body_digest))
    new_instance = ModuleInstance(
        instance.key, instance.module_key,
        [new_output if item.key == output.key else item for item in instance.outputs],
        parameters, metadata=instance.metadata)
    candidate = revision.revise(
        expected_revision=revision.revision_id,
        instances=[new_instance if item.key == instance.key else item
                   for item in revision.instances])
    scope = ProposalScope(instances=(instance.key,))
    source = depth_source
    explanation = (
        f"{target_id[:12]}: поднять на {lift:.3f} мм по z "
        f"({source} {depth:.3f} + зазор {clearance:.3f}); "
        f"пара {finding.a_output_id[:12]}×{finding.b_output_id[:12]}, "
        f"отношение {finding.relation}, источник глубины "
        f"{finding.exact_source or 'грубая оболочка (габарит)'}"
        # The local addition is printed ONLY when it differs from the
        # world-space one: for an identity frame it is the same number,
        # and a second name for the same fact in the explanation would
        # read as a second action.
        + ("" if _is_axis_lift(delta, lift) else
           f"; в параметрах экземпляра это сдвиг "
           f"({delta[0]:.3f}, {delta[1]:.3f}, {delta[2]:.3f}) — фрейм повёрнут, "
           f"и мировой подъём по z не равен локальному")
        + axis_note)
    change = ChangeProposal(revision, candidate, scope, "kir.project_fix", explanation)
    return Proposal(change, frozenset({target_id}), strategy, explanation, finding_id,
                    touches_display_only=False, report=report, world_lift_mm=lift,
                    local_delta_mm=tuple(delta), frame=tuple(frame)), bundle


def _move_authored_body(opened, instance, output, frame, lift, target_id):
    """Move an AUTHOR'S body by translating its frame. Do NOT touch the
    instance's parameters.

    Returns `(bundle, parameters, axis_note)`. `parameters` are the exact
    same ones, and this is not laziness: the manifests of this instance's
    NEIGHBORING bodies carry exactly these, and editing them would break
    `validate_geometry_bindings` for all of them at once.

    A free axis (`p0_mm`/`p1_mm`) in the instance's SHARED parameters
    belongs to the instance, not to a single output: shifting it for the
    sake of one body would mean moving the neighbors too, silently. Such
    a case is a named refusal, not a guess.
    """
    from kir.clash import repair_profile
    from kir.geometry_authoring import rebind_body_frame
    from kir.occt_geometry import GeometryRefusal

    if repair_profile.axis_of(instance.parameters) is not None:
        raise FixError(
            f"authored_body_needs_recipe_rebind: у экземпляра {instance.key!r} ось "
            f"p0_mm/p1_mm лежит в ОБЩИХ параметрах, а тело {target_id[:12]} — лишь "
            f"один из его выходов. Сдвиг тела оставил бы ось на месте, а сдвиг оси "
            f"увёл бы соседей: нужна перепривязка рецепта, а не перенос")
    try:
        original = opened.get_asset(output.geometry.bundle_sha256)
        bundle = rebind_body_frame(original, world_delta_mm=(0.0, 0.0, float(lift)))
    except GeometryRefusal as exc:
        raise FixError(f"authored_body_needs_recipe_rebind: {exc}") from exc
    moved = bundle.to_dict()["manifest"]["frame"]
    # The translation IS CHECKED by a number, not promised: the
    # world-space lift must land exactly in the translation column, and
    # the rotation must stay unchanged.
    for index in range(16):
        want = float(frame[index]) + (lift if index == 11 else 0.0)
        if abs(float(moved[index]) - want) > 1e-9:
            raise FixError(
                f"перенос тела {target_id[:12]} изменил фрейм не переносом: "
                f"позиция {index} {frame[index]!r} -> {moved[index]!r}")
    return bundle, dict(instance.parameters), "; тело сдвинуто переносом фрейма, авторские параметры не тронуты"


def _is_axis_lift(delta, lift: float) -> bool:
    return (abs(delta[0]) <= 1e-9 and abs(delta[1]) <= 1e-9
            and abs(delta[2] - lift) <= 1e-9)


def _frame_of(report, output_id) -> tuple:
    """The body's frame from the report. Identity — only when it is
    DECLARED to be identity."""
    frames = getattr(report, "body_frames", None) or {}
    frame = frames.get(output_id)
    if frame is None:
        bodies = getattr(report, "bodies", None) or {}
        pair = bodies.get(output_id)
        frame = pair[1] if isinstance(pair, tuple) and len(pair) == 2 else None
    if frame is None:
        # An old-format report carries no frame. Silently assuming
        # identity would mean claiming the body is not rotated, without
        # checking anything of the sort.
        raise FixError(
            f"отчёт не несёт фрейма тела {output_id[:12]}: подъём считается в "
            f"мировых координатах и переводится в параметры обратным фреймом, "
            f"а без фрейма перевода нет. Пересними отчёт `analyze_project`")
    return tuple(float(v) for v in frame)


def _local_delta(frame, world, output_id) -> tuple:
    """A world-space shift -> an addition to the parameter's LOCAL box.

    The frame is rigid (`kir.occt_geometry._frame` rejects scale, shear,
    and reflection), so `R⁻¹ = Rᵀ`, and the translation cancels out in the
    difference. Invertibility IS CHECKED by a number, not taken on faith:
    an instrument that believes its own premise catches exactly the bugs
    that are not there.
    """
    local = tuple(sum(frame[4 * r + i] * world[r] for r in range(3)) for i in range(3))
    back = tuple(sum(frame[4 * r + i] * local[i] for i in range(3)) for r in range(3))
    if any(abs(back[k] - world[k]) > 1e-6 for k in range(3)):
        raise FixError(
            f"фрейм тела {output_id[:12]} не обратим переносом (Rᵀ·R ≠ I): "
            f"мировой сдвиг {world} вернулся как {back}. Подъём в таком фрейме "
            f"считать нечем — это масштаб, сдвиг или отражение, а не поворот")
    return local


def _rebuild_body(rebuild, output_key, box, parameters, frame, target_id):
    """Recompute the body via the author's callback — with the frame, and
    a frame CHECK afterward.

    🔴 THE SECOND HALF OF THE SAME BUG, FOUND BY THE PROBE (2b). The
    callback receives the box and the parameters, but NOT the frame, and
    `capture_body` defaults to identity. Meaning a fix on a rotated body
    was silently UN-ROTATING it: measured on `impl3/red-geometry.json` —
    the same pair remained after the "fix", but now at a different depth
    (760.792 instead of 2464.160), because the body had also drifted in
    its frame. Here the frame is passed to the callbacks that accept it,
    and is checked against all of them AFTER the recompute: a mismatch is
    a named refusal, not a silent drift.
    """
    import inspect

    try:
        accepts = "frame" in inspect.signature(rebuild).parameters
    except (TypeError, ValueError):
        accepts = False
    bundle = (rebuild(output_key, box, parameters, frame=tuple(frame)) if accepts
              else rebuild(output_key, box, parameters))
    got = ((bundle.to_dict() or {}).get("manifest") or {}).get("frame")
    if got is not None and any(abs(float(got[k]) - float(frame[k])) > 1e-9
                               for k in range(16)):
        raise FixError(
            f"пересчёт тела {target_id[:12]} сменил фрейм: было "
            f"{[round(v, 3) for v in frame]}, стало {[round(float(v), 3) for v in got]}. "
            f"Исправление обязано двигать тело, а не переставлять его систему "
            f"координат; колбэк `rebuild` должен принять `frame=` и отдать его "
            f"в `capture_body`")
    return bundle


def _z_clearing_depth(report, finding, target_id):
    """How much to raise the TARGET along z so the pair clears. And why
    not `depth_mm`.

    🔴 THIS IS A BREAKDOWN OF A BUG THE INSTRUMENT MADE RIGHT IN FRONT OF
    ME. The strategy is called `raise_clear` — "raise until clear" —
    meaning it moves along ONE axis. So the number it needs must be
    SINGLE-AXIS: how far the target intrudes under its neighbor ALONG Z.
    But `depth_mm` answers a different question, and does so differently
    across the two phases: the rough one gives the overlap along the
    SHORTEST axis (for a passage with a podium that happens to be 500 —
    coincidentally matching z), the exact one gives its own number by its
    own law (the same pair: 3000.01). Measured 06.09.2026: taking the
    exact depth, the strategy raised the passage by 3050.010 mm instead
    of 550.000 — six times higher than needed, and "no collisions" was
    TRUE the whole time. A quiet truth is no better than a quiet lie: the
    project would have drifted three meters, silently.

    The envelope bounds give this number, and give it PROVABLY: a body
    lies inside its own envelope, so if the envelopes are separated
    along z, the bodies are separated too. The lift
    `neighbor.max_z - target.min_z` is the minimum guaranteed by the
    ENVELOPES; below it the envelopes still intersect, and there would be
    nothing to back a promise of clearance with.

    If there are no envelope bounds, we fall back to `depth_mm` and SAY SO
    in the explanation, rather than substituting it silently.
    """
    bounds = getattr(report, "hull_bounds", None) or {}
    other_id = (finding.b_output_id if target_id == finding.a_output_id
                else finding.a_output_id)
    mine, other = bounds.get(target_id), bounds.get(other_id)
    if mine and other:
        need = float(other[1][2]) - float(mine[0][2])
        if need > 0:
            return need, "перекрытие по z у габаритов оболочек"
        # 🔴 UNREACHABLE FOR A RECONCILED PAIR, AND THIS IS STATED OUTRIGHT,
        # NOT PASSED OFF AS A POSSIBILITY. A finding is born from the
        # INTERSECTION of extents, so along every axis they overlap, so
        # `need > 0` on both sides. The line stands as a claim about internal
        # connectivity (no pin is set on it: the pin that would trip it does
        # not exist), and if it ever does fire — the link between the report
        # and the finding is broken, which is what must be shouted, not
        # silently raised to a negative value.
        raise FixError(
            f"raise_clear не разведёт эту пару: цель {target_id[:12]} уже выше "
            f"{other_id[:12]} по z (нужен подъём {need:.3f} мм). Назови `move` "
            f"на другую сторону или другую стратегию")
    if finding.depth_mm is None:
        raise FixError("finding carries no depth; nothing to raise by")
    return (float(finding.depth_mm),
            f"глубина находки ({'точная' if finding.exact_source else 'грубая, по короткой оси габаритов'}) "
            f"— габаритов оболочек в отчёте НЕТ")


def _lighter(report, finding):
    """Whom to move when the caller did not name one: whichever has FEWER
    links in the scene.

    This is not a geometric argument, and it isn't passed off as one: the
    podium holds four pairs, the passage holds one, and moving the podium
    would mean fixing the scene around the mistake. The choice is printed in
    `describe()`.
    """
    pairs = report.bodies_in_pairs
    a, b = finding.a_output_id, finding.b_output_id
    return a if pairs.get(a, 0) <= pairs.get(b, 0) else b


def _pair_key(finding) -> tuple:
    return tuple(sorted((finding.a_output_id, finding.b_output_id)))


def _is_conflict(finding) -> bool:
    """What counts as a conflict. `refuted` is a cleared finding, everything
    else is not.

    `possible` (the coarse envelope), `confirmed` (the exact phase), and
    `clearance_violated` (a violated clearance requirement) equally mean
    "this pair will have to be explained." Counting only `confirmed` as a
    conflict would mean declaring the fix successful before the exact phase
    has even been asked.
    """
    return getattr(finding, "status", None) != "refuted"


def new_conflicts(before, after, *, ignore=()) -> list:
    """Pairs that did NOT exist BEFORE the fix and conflict AFTER it.

    The output address (`output_id`) does not change under a fix — it is
    computed from `project_id/instance_key/output_key`, not from the body —
    so pairs are directly comparable. `ignore` is the pair being fixed: its
    disappearance is the goal, and its reappearance is handled under a
    separate name.
    """
    was = {_pair_key(f) for f in before.findings if _is_conflict(f)}
    skip = {tuple(sorted(pair)) for pair in ignore}
    return sorted({_pair_key(f) for f in after.findings if _is_conflict(f)}
                  - was - skip)


#: WHAT "GOT WORSE" IS MEASURED BY. Ordered from most substantive to
#: coarsest; EVERY measure that has a number on BOTH sides is compared.
#:
#: 🔴 WHY A LIST, NOT A SINGLE NUMBER (KIR-F001, 07.09.2026). Overlap volume
#: is computed only by the EXACT phase; under `exact=False` it does not exist
#: at all (audit scene measurement: `overlap_volume_mm3=None` on both sides,
#: while depth goes 10.000000199999988 -> 30.000000199999988). A guard placed
#: on volume would have stayed silent on the coarse run — silent EXACTLY
#: where the defect was found.
WORSENING_MEASURES: tuple[tuple[str, str], ...] = (
    ("overlap_volume_mm3", "объём перекрытия, мм³"),
    ("depth_mm", "глубина проникания, мм"),
    ("surface_intersections", "пересечений граней"),
    ("deficit_mm", "дефицит зазора, мм"),
)

#: Growth tolerance. Recomputing the body gives noise in the last digits
#: (the same pair before and after an untouched recompute: 10.000000199999988
#: vs 10.000000199999999), and calling that a regression would mean setting
#: up a guard that goes red from arithmetic. 1e-6 mm is fourteen orders of
#: magnitude larger than the noise and six orders of magnitude smaller than
#: the regression that was found (20 mm).
WORSENING_EPSILON = 1e-6

#: A status meaning "the requirement is declared but NOT verified."
UNVERIFIED_STATUS = "clearance_unverified"


def _by_pair(report) -> dict:
    return {_pair_key(f): f for f in report.findings if _is_conflict(f)}


def _measure_gap(was, now) -> str | None:
    """The reason two findings for the same pair are INCOMPARABLE. Else None.

    🔴 THIS IS NOT CAUTION, IT IS A MEASURED DIFFERENCE IN LAWS. `depth_mm` for
    a coarse finding is the extent overlap along the SHORTEST axis; for an
    exact finding the same field is computed differently, and on one and the
    same pair of the tree these numbers come out 500 and 3000.01. Comparing
    them to each other would mean declaring a change of instrument a
    regression. The exact phase is meanwhile bounded by a budget
    (`exact_pair_budget`, `exact_budget_ms`, the `exact_budget_exhausted`
    refusal), so ONE AND THE SAME pair is legitimately judged exactly BEFORE
    and coarsely AFTER under identical run options.
    """
    if getattr(was, "exact_source", None) != getattr(now, "exact_source", None):
        return (f"измеритель сменился: exact_source "
                f"{getattr(was, 'exact_source', None)!r} -> "
                f"{getattr(now, 'exact_source', None)!r}")
    return None


def _worse_by(was, now) -> list:
    """Measures that GREW for this pair. `[(name, before, after)]`."""
    grew = []
    for field, human in WORSENING_MEASURES:
        a, b = getattr(was, field, None), getattr(now, field, None)
        if a is None or b is None:
            continue
        if float(b) > float(a) + WORSENING_EPSILON:
            grew.append((human, float(a), float(b)))
    return grew


def _measured(finding) -> bool:
    """Whether the finding had even one number it can be compared by."""
    return any(getattr(finding, field, None) is not None
               for field, _human in WORSENING_MEASURES)


def worsened_conflicts(before, after, *, ignore=()) -> tuple[list, list]:
    """-> `(worsened, incomparable)` over pairs that conflict in BOTH reports.

    🔴 WHY THIS FUNCTION EXISTS (external audit KIR-F001, P1). `new_conflicts`
    compares SETS of pair keys, so a pair that existed before and still exists
    drops out of the reconciliation along with all its numbers. Audit scene:
    three 100x100 boxes, along z A=[0,100], B=[-90,10], C=[90,200]; raising A
    by 20 mm separates A/B and drives A into C from 10 mm to 30 mm.
    `new_conflicts` returns `[]`, and the fix would go into history as "no
    worse than before."

    THREE KINDS OF REGRESSION, AND THE THIRD IS NOT A NUMBER:
      1. A measure GREW (volume/depth/face intersections/clearance deficit);
      2. MEASURABILITY WAS LOST: a pair that was measured became
         `clearance_unverified` or was left without a single number.
         "Not verified" is not "no worse";
      3. THE INSTRUMENT CHANGED — there is nothing to compare, and this is a
         separate list: the caller must say `proposal_unverifiable`, not
         "no worse."

    A pair that DISAPPEARS from the report is not counted as a regression: the
    broad phase drops a pair exactly when the extents no longer overlap, and
    that is precisely the goal of the fix.
    """
    was_pairs, now_pairs = _by_pair(before), _by_pair(after)
    skip = {tuple(sorted(pair)) for pair in ignore}
    worse, incomparable = [], []
    for key in sorted(set(was_pairs) & set(now_pairs) - skip):
        was, now = was_pairs[key], now_pairs[key]
        # (2) LOSS OF MEASURABILITY is handled FIRST: it may have no numbers
        # on either side, and trying to compare them would give "no growth,"
        # i.e. it would pass off ignorance as being fine.
        if _measured(was) and (getattr(now, "status", None) == UNVERIFIED_STATUS
                               or not _measured(now)):
            worse.append((key, "измеримость",
                          "измерено (" + ", ".join(
                              f"{human} {float(getattr(was, field)):.3f}"
                              for field, human in WORSENING_MEASURES
                              if getattr(was, field, None) is not None) + ")",
                          f"НЕ измерено (status={getattr(now, 'status', None)})"))
            continue
        reason = _measure_gap(was, now)
        if reason is not None:
            incomparable.append((key, reason))
            continue
        for human, a, b in _worse_by(was, now):
            worse.append((key, human, f"{a:.3f}", f"{b:.3f}"))
    return worse, incomparable


def apply_fix(store, proposal, *, expected_revision=None, assets=(), verify=True):
    """`accept_proposal` is the existing CAS. There is no history write of its own here.

    🔴 RECONCILIATION HAPPENS BEFORE THE WRITE, AND THIS IS A DECISION (owner,
    item 3). "To fix" means to make no worse, not "remove one line from the
    report." Measurement on `impl3/red-geometry.json`: raising the passage by
    550 mm moved it out from under the podium INTO the canopy above — the old
    pair disappeared, a new one appeared, and `apply_fix` printed success. A
    refusal AFTER `accept_proposal` would be no better: history would still
    hold a revision it had itself called unfit, and the "rollback" would look
    like yet another commit. So the candidate is analyzed in memory
    (`analyze_revision` + a new bundle), and only "zero new conflicts" opens
    the write. `verify=False` is left to the caller, who then verifies it
    themselves, and this is PRINTED as a refusal, not implied.
    """
    from kir.project_merge import accept_proposal, merge_proposal
    from kir.project_store import StoreConflict

    opened = _open(store, write=True)
    change = proposal.change if isinstance(proposal, Proposal) else proposal
    scope = change.scope
    current = opened.head()
    expected = current.revision_id if expected_revision is None else expected_revision
    if current.revision_id != expected:
        raise StoreConflict("repair acceptance expected a different current head")
    assets = tuple(assets)
    if verify:
        # A compatible neighbour may have changed since the proposal was made.
        # Validate the exact three-way merge, not the proposal's old candidate.
        # The expected head is pinned BEFORE analysis and is never refreshed
        # after it: accept_proposal checks stored ancestry and the same head,
        # then repeats this pure merge before its atomic CAS append.
        merged = merge_proposal(change, current, authorized_scope=scope)
        if not merged.clean:
            raise FixError("merge is not clean: " + str(merged.to_dict())[:200])
        _verify_no_new_conflicts(opened, proposal, assets,
                                 current=current, candidate=merged.revision)
    acceptance = accept_proposal(opened, change, expected_revision=expected,
                                 authorized_scope=scope, assets=list(assets))
    if not acceptance.merge.clean:
        raise FixError("merge is not clean: " + str(acceptance.merge.report)[:200])
    # Exact redelivery can acknowledge a previously stored revision while a
    # later head already exists. Return the accepted payload, not that later,
    # unexamined head. Callers can read the current head separately.
    return acceptance.merge.revision.revision_id


def _verify_no_new_conflicts(opened, proposal, assets, *, current, candidate) -> None:
    """Analysis of the CANDIDATE by the same measure: the pair is cleared and neighbors are no worse."""
    from kir.clash.project_analysis import analyze_revision

    original_report = getattr(proposal, "report", None)
    if original_report is None:
        # 🔴 "VERIFIED" AND "THERE WAS NOTHING TO VERIFY" MUST BE DISTINCT
        # (review6, C-4). The previous edition returned SILENTLY, and
        # `apply_fix` wrote the revision exactly as it would after a
        # successful reconciliation — even though `verify=True` is the
        # default, while the header promised "`verify=False` ... is PRINTED
        # as a refusal, not implied." A silent default in a place that
        # promised to print is the same kind of thing as "nothing changed" in
        # response to a request to change something.
        raise FixError(
            "proposal_unverifiable: предложение не несёт отчёта анализа "
            f"({type(proposal).__name__}), поэтому сверить «не стало ли хуже "
            f"соседям» нечем: не с чем сравнить набор пар ДО исправления. "
            f"Возьми предложение у `propose_fix` (оно везёт отчёт с собой) либо "
            f"скажи `verify=False` — тогда сверка на вызывающем, и это НАЗВАНО, "
            f"а не подразумевается")
    fresh = {getattr(item, "digest", None): item for item in assets}

    def get_asset(sha):
        found = fresh.get(sha)
        return found if found is not None else opened.get_asset(sha)

    options = {"exact": bool(getattr(original_report, "exact", False)),
               "tolerance_policy": dict(getattr(original_report, "tolerance_policy", None)
                                        or {}) or None}
    # Compare against the current revision, so a pre-existing conflict in a
    # concurrent author's change is not attributed to this repair. Only the
    # candidate may resolve fresh assets; the baseline belongs to the store.
    before = analyze_revision(current, opened.get_asset, **options)
    after = (before if candidate.revision_id == current.revision_id else
             analyze_revision(candidate, get_asset, **options))
    fixed = None
    for finding in original_report.findings:
        if finding.finding_id == proposal.finding_id:
            fixed = _pair_key(finding)
            break
    appeared = new_conflicts(before, after, ignore=() if fixed is None else (fixed,))
    if appeared:
        raise FixError(
            "fix_creates_new_conflict: исправление разводит пару "
            + (f"{fixed[0][:12]}×{fixed[1][:12]}" if fixed else proposal.finding_id)
            + ", но создаёт "
            + ", ".join(f"{a[:12]}×{b[:12]}" for a, b in appeared)
            + f" (новых пар {len(appeared)}); подъём "
            + (f"{proposal.world_lift_mm:.3f} мм по z"
               if getattr(proposal, "world_lift_mm", None) is not None else "предложения")
            + " в историю НЕ записан — назови `move` на другую сторону, другую "
              "стратегию или явный `lift_mm`")
    # 🔴 "THE PAIR DID NOT APPEAR" IS NOT YET "THE NEIGHBOR GOT NO WORSE"
    # (KIR-F001). The evaluation runs against the SAME `after`, i.e. on the
    # FINAL three-way merge, and over all pairs involving the moved body —
    # not only the one being fixed.
    worse, incomparable = worsened_conflicts(
        before, after, ignore=() if fixed is None else (fixed,))
    if incomparable:
        raise FixError(
            "proposal_unverifiable: сверить «не стало ли хуже» нечем — у "
            + ", ".join(f"{a[:12]}×{b[:12]} ({why})" for (a, b), why in incomparable)
            + ". Числа двух измерителей отвечают на разные вопросы, и объявить "
              "их сравнение благополучием значило бы выдать смену прибора за "
              "результат. Пересними отчёт той же мерой (`exact=`) либо скажи "
              "`verify=False` — тогда сверка на вызывающем, и это НАЗВАНО")
    if worse:
        raise FixError(
            "fix_worsens_existing_conflict: "
            + "; ".join(f"{a[:12]}×{b[:12]} {measure} {had}→{got}"
                        for (a, b), measure, had, got in worse)
            + f" (ухудшившихся пар {len({pair for pair, *_ in worse})}); подъём "
            + (f"{proposal.world_lift_mm:.3f} мм по z"
               if getattr(proposal, "world_lift_mm", None) is not None else "предложения")
            + " в историю НЕ записан. Пара, которая БЫЛА и ОСТАЛАСЬ, из счёта "
              "новых пар выпадает целиком — вместе со своими числами; здесь "
              "сравниваются сами числа. Назови `move` на другую сторону, другую "
              "стратегию или явный `lift_mm`")
    if fixed is not None and any(_pair_key(f) == fixed and _is_conflict(f)
                                 for f in after.findings):
        still = next(f for f in after.findings if _pair_key(f) == fixed and _is_conflict(f))
        raise FixError(
            f"fix_did_not_separate: после подъёма пара {fixed[0][:12]}×{fixed[1][:12]} "
            f"осталась ({still.relation}, глубина "
            + ("—" if still.depth_mm is None else f"{still.depth_mm:.3f}")
            + " мм). Правка в историю НЕ записана")


#: A second name for the same action — the acceptance instrument called it this.
def apply_proposal(store_path, proposal, *, expected_revision):
    return apply_fix(store_path, proposal, expected_revision=expected_revision,
                     assets=getattr(proposal, "assets", ()))


def _open(store, *, write: bool = False):
    """Store as an object or a path. WRITE ACCESS IS OPENED EXPLICITLY.

    `ProjectStore.open` defaults to read-only access, and that is not
    pedantry: `apply_fix` writes to history, and write permission must be
    named in that same call, not inherited silently.
    """
    from kir.project_store import ProjectStore

    if type(store) is ProjectStore:
        return store
    return ProjectStore.open(store, readonly=not write)


__all__ = ["propose_fix", "apply_fix", "apply_proposal", "new_conflicts",
           "worsened_conflicts", "WORSENING_MEASURES",
           "Proposal", "FixError", "DEFAULT_CLEARANCE_MM"]
