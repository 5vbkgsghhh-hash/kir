# -*- coding: utf-8 -*-
"""A BUILDING IS A BATCH OF PROGRAMS, and the links know each other by receipt.

    pack = Pack([PackLink("levels", program_a),
                 PackLink("shell",  program_b, needs=("levels",)),
                 PackLink("stairs", program_c, needs=("shell",))])
    run = run_pack(pack, executor=OfflineExecutor())

🔴 WHY THIS EXISTS, IN ONE MEASURED SENTENCE. `create_stairs` owns its own
transactions, so it is the ONLY op of its program (`spec.SOLO_OPS`, KIR-L002):
the levels it stands on are built by a NEIGHBOURING program. And a level
addressed by NAME does not ground offline — `KIR-G103` «программа требует
снапшот модели» — so the neighbour's `element_id` is the only address that
works, and it does not exist until that neighbour has run. Hence: **a batch
cannot be compiled whole offline; its links meet through receipts.**

Until now that meeting was done BY HAND — by a person or by a harness (the team
rehearsal of 13.09.2026 typed the ids from `facts.json`). This module makes it
the product's job.

🔴 AN UNRESOLVED REFERENCE IS A NAMED REFUSAL, NEVER A QUIET ZERO. The failure
this guards against is `element_id=0` slipping into a program because a receipt
was missing: it compiles, it ships, and it hits the model. Every placeholder
that cannot be resolved stops the batch with a name and a next move.

🔴 THE EXECUTOR IS A PORT. Offline there is a fake one that returns receipts in
the shape the tree already has (`kir-create-identity-assessment/1`); the live
one is the admin door, and it is NOT called from here. A batch that ran offline
claims nothing about Revit: every row carries `native_execution: "not_run"`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from kir import spec
from kir.project import ProjectError

#: The placeholder a link writes instead of an address it cannot know yet.
PACK_REF = "pack"
PACK_SCHEMA = "kir-program-pack/1"
ASSESSMENT_SCHEMA = "kir-create-identity-assessment/1"

#: Slots that address an element. A WRITE target is pinned by `unique_id`
#: (that is what `expected_identity` compares); a catalogue selector takes
#: `element_id` and does not know `unique_id` at all — measured 13.09.2026,
#: a re-grounded `level` came back KIR-T001 «level — селектор … получено
#: {"by": "unique_id"}».
#: 🔴 `targets_w` СНЯТ 13.09.2026 (заявка N 3): вида нет в `spec.PARAM_KINDS`,
#: и ни один оп его не носит. Живой вид пачки записи — `refs_w`.
_WRITE_KINDS = frozenset({"target_w", "refs_w"})
_SELECTOR_KINDS = frozenset({"sel", "sel_list", "target"}) | _WRITE_KINDS


class PackError(ProjectError):
    """A batch could not be carried out. Named code, never a guess."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def pack_ref(link: str, output: str) -> dict:
    """«Возьми у звена `link` выход `output`» — адрес, которого ещё нет."""
    if not isinstance(link, str) or not link.strip():
        raise PackError("pack_ref_without_a_link", "звено не названо")
    if not isinstance(output, str) or not output.strip():
        raise PackError("pack_ref_without_an_output", f"{link}: выход не назван")
    return {"by": PACK_REF, "link": link, "output": output}


@dataclass(frozen=True, slots=True)
class PackLink:
    """One link: a program plus the links it reads receipts from."""

    key: str
    program: dict
    needs: tuple = ()

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key.strip():
            raise PackError("pack_link_without_a_key", "звено без имени")
        if not isinstance(self.program, dict) or not isinstance(self.program.get("ops"), list):
            raise PackError("pack_link_is_not_a_program", f"{self.key}: нужна программа KIR")
        object.__setattr__(self, "needs", tuple(self.needs))


@dataclass(frozen=True, slots=True)
class Pack:
    """Ordered links. The order is the author's; the module only checks it."""

    links: tuple

    def __post_init__(self) -> None:
        object.__setattr__(self, "links", tuple(self.links))
        seen = set()
        for link in self.links:
            if type(link) is not PackLink:
                raise PackError("pack_holds_something_that_is_not_a_link", repr(link)[:120])
            if link.key in seen:
                raise PackError("pack_link_key_is_not_unique", link.key)
            for need in link.needs:
                if need not in seen:
                    # 🔴 THE ORDER IS PART OF THE BATCH, and a link that reads a
                    # receipt from further down cannot be run at all.
                    raise PackError(
                        "pack_link_needs_a_later_link",
                        f"{link.key} объявил, что берёт из {need}, но {need} идёт "
                        "позже или его нет. СЛЕДУЮЩИЙ ХОД: поставь звенья в том "
                        "порядке, в каком они исполняются")
            seen.add(link.key)

    def keys(self) -> tuple:
        return tuple(link.key for link in self.links)


# ── resolving one link against the receipts already collected ──────────────
def _identities(receipt: Any) -> dict:
    """A receipt blob -> {output_id: identity}. The shape is the tree's own."""
    blob = receipt.to_dict() if hasattr(receipt, "to_dict") else receipt
    if not isinstance(blob, dict) or blob.get("schema") != ASSESSMENT_SCHEMA:
        raise PackError("receipt_is_not_an_assessment",
                        f"ожидалась схема {ASSESSMENT_SCHEMA}")
    rows = {}
    for row in blob.get("outputs") or ():
        identity = (row or {}).get("element_identity")
        if isinstance(identity, dict) and identity.get("unique_id"):
            rows[row["output_id"]] = identity
    return rows


def _slot_kinds(op: dict) -> dict:
    ospec = spec.OPS.get(op.get("op"))
    if ospec is None:
        return {}
    return {p.name: p.kind for p in ospec.params}


def _address(identity: dict, kind: str, *, owner: str) -> dict:
    if kind in _WRITE_KINDS:
        return {"by": "unique_id", "value": identity["unique_id"]}
    element_id = identity.get("element_id")
    if element_id is None:
        raise PackError(
            "receipt_has_no_element_id",
            f"{owner}: квитанция дала личность без element_id, а слот-селектор "
            "принимает только его — unique_id этому слоту не подходит")
    return {"by": "element_id", "value": element_id}


def resolve_link(link: PackLink, receipts: dict) -> dict:
    """The link's program with every pack placeholder replaced by an address.

    Nothing is guessed and nothing defaults: a placeholder whose link has not
    run, or whose output is not in that link's receipt, stops the batch.
    """
    known = {key: _identities(value) for key, value in (receipts or {}).items()}
    used = []

    def resolve(value, *, kind: str | None, owner: str):
        if isinstance(value, dict) and value.get("by") == PACK_REF:
            target, output = value.get("link"), value.get("output")
            if target not in known:
                raise PackError(
                    "pack_link_not_executed",
                    f"{owner}: ссылка на звено «{target}», квитанции которого нет. "
                    "СЛЕДУЮЩИЙ ХОД: исполни звено «" + str(target) + "» и подай его "
                    "квитанцию — адрес элемента существует только ПОСЛЕ исполнения")
            identity = known[target].get(output)
            if identity is None:
                raise PackError(
                    "pack_output_not_in_receipt",
                    f"{owner}: в квитанции звена «{target}» нет выхода «{output}» "
                    f"(есть {len(known[target])}). СЛЕДУЮЩИЙ ХОД: сверь адрес выхода "
                    "с квитанцией того звена; догадываться об id нельзя")
            if kind not in _SELECTOR_KINDS:
                raise PackError(
                    "pack_ref_in_a_slot_that_takes_no_address",
                    f"{owner}: слот вида «{kind}» адресом элемента не заполняется")
            used.append({"link": target, "output": output, "slot": owner,
                         "unique_id": identity["unique_id"]})
            return _address(identity, kind, owner=owner)
        if isinstance(value, dict):
            return {key: resolve(item, kind=kind, owner=owner) for key, item in value.items()}
        if isinstance(value, list):
            return [resolve(item, kind=kind, owner=owner) for item in value]
        return value

    ops = []
    for op in link.program["ops"]:
        kinds = _slot_kinds(op)
        built = {}
        for name, value in op.items():
            built[name] = resolve(value, kind=kinds.get(name),
                                  owner=f"{link.key}.{op.get('id', '?')}.{name}")
        ops.append(built)
    return {**link.program, "ops": ops}, tuple(used)


# ── the executor port ──────────────────────────────────────────────────────
class OfflineExecutor:
    """A FAKE executor: it hands back identities, and says so in every answer.

    🔴 IT IS NOT REVIT AND DOES NOT PRETEND. `native_execution` stays
    `"not_run"` in the run's claims, and the identities are synthetic —
    shaped like the live receipt (`live-20260913-slice-receipt.json`), which is
    what makes the shape testable, and nothing more. The live executor is the
    admin door; it is section N's and is not called from here.
    """

    provider = "offline-fake"

    def __init__(self, *, base_element_id: int = 500000):
        self.base = base_element_id
        self.issued = 0

    def execute(self, link_key: str, program: dict) -> dict:
        outputs = []
        for op in program["ops"]:
            oid = op.get("id")
            if not isinstance(oid, str):
                continue
            self.issued += 1
            element_id = self.base + self.issued
            outputs.append({
                "output_id": oid, "source_op": op["op"], "state": "created_here",
                "element_identity": {
                    "schema_version": "revit-element-identity/1",
                    "unique_id": f"7ff4b512-b299-4d75-8107-62effd492f45-{element_id:08x}",
                    "element_id": element_id,
                    "version_guid": "7ff4b512b2994d75810762effd492f45"}})
        return {"schema": ASSESSMENT_SCHEMA, "receipt_digest": sha256(
            json.dumps(outputs, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            "outputs": outputs, "program_as_published": program,
            "link": link_key, "executor": self.provider}


# ── running a whole pack ───────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class PackRun:
    """What a batch did, link by link. Inert; grants nothing."""

    rows: tuple
    receipts: dict
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "digest", sha256(json.dumps(
            [dict(row) for row in self.rows], sort_keys=True, ensure_ascii=False,
            default=str).encode()).hexdigest())

    def to_dict(self) -> dict:
        return {"schema": PACK_SCHEMA, "links": [dict(row) for row in self.rows],
                "run_digest": self.digest,
                "claims": {"native_execution": "not_run", "revit_started": False,
                           "dispatch_permission": "none"}}

    def operations(self) -> int:
        return sum(row.get("ops", 0) for row in self.rows)


def run_pack(pack: Pack, *, executor, revit_version: str = "2026",
             previous: dict | None = None) -> PackRun:
    """Resolve → plan (if the link ran before) → compile → execute, link by link.

    `previous` — `{link key: <its receipt from the last run>}`. With it, each
    link is REPLANNED instead of rebuilt: a repeat with no changes produces no
    operations at all, per link, through `kir.project_republish`.
    """
    from kir.compiler import compile_program
    from kir.diag import KirRefusal

    # 🔴 A REPEAT IS A REPEAT OF THE WHOLE BATCH, AND A MISSING RECEIPT IS THE
    # DANGEROUS CASE. If `previous` carries some links and not others, the
    # silent reading is «этого звена ещё не было» — and the batch would BUILD
    # ITS LEVELS AGAIN, over the ones already standing. That is the duplicate
    # arriving by the back door, and it is exactly what the whole «без дублей»
    # programme exists against. So: once a repeat is declared, every link must
    # bring its receipt, and a gap stops the run by name.
    if previous:
        lost = [link.key for link in pack.links if link.key not in previous]
        if lost:
            raise PackError(
                "pack_receipt_lost",
                f"повтор пачки, а квитанций нет у звеньев: {', '.join(lost)}. "
                "Исполнять их заново значит построить то, что уже стоит. "
                "СЛЕДУЮЩИЙ ХОД: достань квитанцию из store — "
                "`kir.republish_archive.previous_from_stored_publication(store, "
                "<адрес публикации звена>)`, он выводит личности продуктовым "
                "путём из того, что store ДЕЙСТВИТЕЛЬНО хранит; либо прочитай "
                "личности живьём (`query_element_state`) и подай их как квитанцию; "
                "если звено ДЕЙСТВИТЕЛЬНО не исполнялось — гони пачку без `previous`")
    receipts, rows = {}, []
    for link in pack.links:
        program, used = resolve_link(link, receipts)
        row = {"link": link.key, "needs": list(link.needs), "resolved_refs": list(used)}

        earlier = (previous or {}).get(link.key)
        if earlier is not None:
            from kir.project_republish import plan_republish
            from kir.project_republish_program import republish_program

            plan = plan_republish(None, program, {"identity": earlier,
                                                  "program": earlier.get("program_as_published")})
            derived = republish_program(plan, program)
            row["republish"] = {"counts": plan.counts(),
                                "creates_over_known": len(plan.creates_over_known_identity())}
            program_to_run = derived.program
        else:
            program_to_run = program

        row["ops"] = len(program_to_run["ops"])
        if not program_to_run["ops"]:
            # Nothing to send is a RESULT, not a failure: the link is already
            # what it should be, and the previous receipt stays the current one.
            row["compile"] = {"sent": False, "why": "повтор без изменений — отправлять нечего"}
            receipts[link.key] = earlier
            rows.append(row)
            continue
        try:
            out = compile_program(program_to_run, revit_version)
            row["compile"] = {"sent": True, "ok": bool(out.ok),
                              "codes": sorted({d.code for d in (out.diagnostics or ())}),
                              "cs_bytes": len(getattr(out, "csharp", "") or "")}
        except KirRefusal as failure:
            row["compile"] = {"sent": True, "ok": False,
                              "codes": sorted({d.code for d in failure.diagnostics}),
                              "messages": [d.message_ru[:200] for d in failure.diagnostics][:2]}
        if not row["compile"].get("ok"):
            raise PackError(
                "pack_link_did_not_compile",
                f"{link.key}: звено не скомпилировалось ({row['compile'].get('codes')}); "
                "пачка остановлена — исполнять звено, которое не собралось, значит "
                "оставить пачку наполовину построенной")
        receipt = executor.execute(link.key, program_to_run)
        if earlier is not None:
            # A republication's receipt must keep the AUTHORED values, not the
            # delta's: the next round diffs the author against the author.
            receipt = {**receipt, "program_as_published": program}
        receipts[link.key] = receipt
        row["receipt_outputs"] = len(receipt.get("outputs") or ())
        rows.append(row)
    return PackRun(tuple(rows), receipts)


def pack_as_previous(run: PackRun) -> dict:
    """The run's receipts, ready to be handed to the NEXT run of the same pack."""
    return {key: value for key, value in run.receipts.items() if value is not None}


def pack_previous_from_store(store, publications: dict) -> dict:
    """`{звено: адрес публикации}` -> `{звено: квитанция}`, из НАСТОЯЩЕГО store.

    🔴 WITHOUT THIS THE REPEAT LIVES ONLY IN THE RUN'S MEMORY, and a batch whose
    process died would have no way back except building everything again.
    Section N measured on a real SQLite store that a stored receipt row holds no
    identity blob; the identities are DERIVED from what the store does keep, by
    the product's own path — `kir.republish_archive` — and this helper is the
    batch-shaped door to it, not a second deriver.
    """
    from kir.project_store import ProjectStoreError
    from kir.republish_archive import (RepublishArchiveError,
                                       previous_from_stored_publication)

    rows = {}
    for link, digest in (publications or {}).items():
        try:
            previous = previous_from_stored_publication(store, digest)
        except RepublishArchiveError as failure:
            raise PackError(
                getattr(failure, "code", "pack_receipt_lost"),
                f"звено «{link}»: {failure}") from failure
        except ProjectStoreError as failure:
            # 🔴 THE STORE'S OWN ABSENCE IS NOT «этого звена не было». A digest
            # the store does not know must stop the batch by name: read as
            # «первый прогон», it would build the link again over what already
            # stands. Measured 13.09.2026 — an unknown digest arrives as
            # `StoreNotFound` from `project_create_store`, one layer below the
            # deriver, so it is named here rather than left to escape raw.
            raise PackError(
                "pack_publication_unknown_to_the_store",
                f"звено «{link}»: публикации {str(digest)[:12]} в store нет "
                f"({type(failure).__name__}). СЛЕДУЮЩИЙ ХОД: сверь адрес публикации "
                "звена; считать её несуществующей и строить звено заново — это "
                "дубль поверх уже стоящего") from failure
        rows[link] = {**previous["identity"],
                      "program_as_published": previous["program"]}
    return rows
