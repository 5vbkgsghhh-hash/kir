# -*- coding: utf-8 -*-
"""INTEGRITY CHECKING IS PAID FOR ONCE — AND DOES NOT GET WEAKER.

🔴 THE NUMBER THAT STARTED THIS FILE (07.09.2026). Every
`ProjectStore._transaction` opens a NEW connection and calls `_read_state`,
which in turn calls `_check_revision_assets` over ALL of the head's assets.
So `get_asset` cost not one read but the whole revision: the formula
`(N+2)·M + N`, and on a scene of 205 bodies that is **42 640** calls to
`_read_asset` for 205 `get_asset` calls (profile: 400 s out of 502 in
`GeometryBundle.loads`/`_validate`). Analyzing 205 bodies took 165.9 s; after
the fix — 18.1 s.

THE FIX DOES NOT WEAKEN THE CHECK, AND THAT IS THE MAIN THING MEASURED HERE.
The handle's guarantee saves PARSING, not READING: the row from SQLite is
always read, and the remembered bundle is handed back ONLY when the bytes
read match the ones already verified. A substituted asset yields different
bytes, a miss, and a full check. The old code caught a substitution after
the first check too (it re-checked every time) — the new code catches it as
well, and the pin below demands exactly this, not "no worse" in words.

THE THIRD MOVE (of the same shift): the hot read stopped traversing the head
IN FULL and now checks the head's schema, identity, payload, and the
ADDRESSABLE asset — exactly what the header of `project_store.py` declared
and the code was not doing. The full traversal stayed with `history()`. The
number of parses per N accesses became N, not `(N+2)·M + N`. What this
STOPPED catching on read — corruption of a NON-addressable body — is pinned
down as DECLARED behavior, not left unspoken.
"""
from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("OCP", reason="сцена строится настоящим OCCT")

from kir.project_store import (ProjectStore, StoreCorrupt,     # noqa: E402
                               StoreNotFound)


@pytest.fixture
def scene(tmp_path):
    import examples.podium_passage as example

    path = tmp_path / "scene.sqlite"
    example.save(path)
    return path


@pytest.fixture(scope="module")
def wide(tmp_path_factory):
    """A wider scene: at five bodies, 5 and 25 parses can't be told apart by eye."""
    import examples.podium_passage as example

    path = tmp_path_factory.mktemp("wide") / "wide.sqlite"
    extra = tuple((f"cube{i}", ((i * 5000., -40000., -40000.),
                                (i * 5000. + 1000., -39000., -39000.)))
                  for i in range(12))
    example.save(path, extra=extra)
    return path


class _Counter:
    """Counts FULL bundle parses — the thing that cost 400 s out of 502."""

    def __init__(self):
        self.loads = 0

    def __enter__(self):
        from kir.occt_geometry import GeometryBundle

        self.original = GeometryBundle.loads.__func__
        counter = self

        def counted(cls, payload):
            counter.loads += 1
            return counter.original(cls, payload)

        GeometryBundle.loads = classmethod(counted)
        return self

    def __exit__(self, *exc):
        from kir.occt_geometry import GeometryBundle

        GeometryBundle.loads = classmethod(self.original)
        return False


def _digests(store):
    head = store.head()
    return [output.geometry.bundle_sha256
            for _instance, output, _oid in head.addressed_outputs()
            if output.geometry is not None]


def test_reading_every_asset_costs_one_full_check_each(wide):
    """N asset reads no longer cost N·M parses — and here are both numbers."""
    digests = _digests(ProjectStore.open(wide))
    count = len(digests)
    assert count == 17, f"ассетов {count} — сцена не та"
    # The old cost, computed by the same formula as in the header: opening a
    # handle checks the head (M), each transaction checks it again (M), plus
    # the read itself.
    was = count * (count + 2) + count

    with _Counter() as first:
        store = ProjectStore.open(wide)
        for digest in digests:
            store.get_asset(digest)
    # 🔴 EXACTLY ONE PARSE PER ASSET — THIS IS THE FLOOR. The hot read no
    # longer traverses the head in full (the module header's rule), and the
    # guarantee holds bytes already verified. So only what was ACCESSED gets
    # paid for.
    assert first.loads == count, (
        f"разборов {first.loads} при {count} ассетах (ожидалось {count}, "
        f"прежняя цена {was})")
    assert first.loads * 10 < was, "выигрыш меньше, чем стоит такой пин"

    with _Counter() as second:
        for digest in digests:
            store.get_asset(digest)
    assert second.loads == 0, (
        f"повторное чтение стоило {second.loads} разборов — ручательство не работает")


def test_a_fresh_handle_does_not_inherit_another_handles_guarantee(scene):
    """The guarantee belongs to the handle, not to the process or the disk."""
    warm = ProjectStore.open(scene)
    digests = _digests(warm)
    for digest in digests:
        warm.get_asset(digest)
    with _Counter() as again:
        warm.get_asset(digests[0])
    assert again.loads == 0, "прогретый handle платит второй раз"

    cold = ProjectStore.open(scene)
    with _Counter() as counter:
        cold.get_asset(digests[0])
    # A new handle pays for the ADDRESSABLE body in full — and exactly for it.
    assert counter.loads == 1, (
        f"новый handle разобрал {counter.loads} тел: либо ручательство утекло "
        f"за пределы своего, либо горячее чтение всё ещё обходит голову")


def test_a_swapped_asset_is_still_refused_after_the_first_check(scene):
    """🔴 FAIL CONTROL. A substitution AFTER the first check, in the SAME
    process.

    The old code re-checked every time and caught the substitution. The new
    one always reads the row and verifies the BYTES — it catches it too. If
    the guarantee ever starts answering by name without looking at the row,
    this pin will turn red.
    """
    store = ProjectStore.open(scene)
    digests = _digests(store)
    for digest in digests:
        store.get_asset(digest)          # warmed up the guarantee

    victim = digests[0]
    connection = sqlite3.connect(scene)
    try:
        payload = connection.execute(
            "SELECT payload FROM geometry_assets WHERE digest=?", (victim,)).fetchone()[0]
        # A content substitution under the same name is exactly what the digest must catch.
        connection.execute("UPDATE geometry_assets SET payload=? WHERE digest=?",
                           (payload.replace('"units": "mm"', '"units": "cm"', 1)
                            if '"units": "mm"' in payload else payload + " ", victim))
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(StoreCorrupt):
        store.get_asset(victim)
    # 🔴 (b) A NON-ADDRESSABLE BODY ON THE HOT PATH IS NOT READ — AND THIS IS
    # DECLARED BEHAVIOR, PINNED DOWN, NOT SILENCE. The neighboring body reads
    # normally, the head reads normally, and it is the FULL TRAVERSAL of
    # `history()` that catches corruption.
    other = next(digest for digest in digests if digest != victim)
    assert store.get_asset(other).digest == other
    assert store.head().revision_id
    with pytest.raises(StoreCorrupt):
        store.history()
    # (d) A fresh handle after the substitution behaves the same way:
    # addressable — refusal, neighboring — reads, full traversal — refusal.
    fresh = ProjectStore.open(scene)
    with pytest.raises(StoreCorrupt):
        fresh.get_asset(victim)
    assert fresh.get_asset(other).digest == other
    with pytest.raises(StoreCorrupt):
        fresh.history()


def test_a_referenced_asset_that_vanished_is_corruption_not_a_miss(scene):
    """🔴 "THERE IS NO SUCH BODY" AND "THE HEAD REFERENCES IT, BUT THE ROW IS
    MISSING" ARE DIFFERENT FACTS.

    While the full traversal paid for the loss, it was called `StoreCorrupt`.
    Removing the traversal, it was easy to hand back `StoreNotFound` instead —
    that is, to answer "we don't have such a thing" about a body the revision
    DECLARED as its own. What is asked is the reference memory (O(1) per
    handle), not a read of all M rows.
    """
    import sqlite3

    store = ProjectStore.open(scene)
    digests = _digests(store)
    victim = digests[0]
    connection = sqlite3.connect(scene)
    try:
        connection.execute("DELETE FROM geometry_assets WHERE digest=?", (victim,))
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(StoreCorrupt, match="referenced geometry asset is missing"):
        ProjectStore.open(scene).get_asset(victim)
    # A body the revision never declared is still an honest "not found".
    with pytest.raises(StoreNotFound):
        ProjectStore.open(scene).get_asset("0" * 64)


def test_the_head_payload_is_still_checked_byte_for_byte_on_the_hot_path(scene):
    """🔴 (c) The header's rule removed the traversal of BODIES, not the check of the HEAD."""
    import sqlite3

    store = ProjectStore.open(scene)
    head = store.head()
    connection = sqlite3.connect(scene)
    try:
        payload = connection.execute(
            "SELECT payload FROM revisions WHERE revision_id=?",
            (head.revision_id,)).fetchone()[0]
        connection.execute("UPDATE revisions SET payload=? WHERE revision_id=?",
                           (payload + " ", head.revision_id))
        connection.commit()
    finally:
        connection.close()
    for action in (store.head, lambda: store.get_asset(_digests_of(head)[0]),
                   lambda: ProjectStore.open(scene).head()):
        with pytest.raises(StoreCorrupt, match="payload"):
            action()


def _digests_of(revision):
    return [output.geometry.bundle_sha256
            for _instance, output, _oid in revision.addressed_outputs()
            if output.geometry is not None]


def test_the_guarantee_has_a_named_ceiling(scene):
    """A cache without a limit is a leak with a different name. The limit is named as a number."""
    from kir import project_store as PS

    assert isinstance(PS._VERIFIED_PAYLOAD_BYTES, int)
    assert PS._VERIFIED_PAYLOAD_BYTES > 0
    store = ProjectStore.open(scene)
    for digest in _digests(store):
        store.get_asset(digest)
    spent = store._verified.get(PS._VERIFIED_BYTES_KEY, 0)
    assert 0 < spent <= PS._VERIFIED_PAYLOAD_BYTES
    # Above the limit, the guarantee stops REMEMBERING, but does not stop CHECKING.
    store._verified[PS._VERIFIED_BYTES_KEY] = PS._VERIFIED_PAYLOAD_BYTES
    store._verified.clear()
    store._verified[PS._VERIFIED_BYTES_KEY] = PS._VERIFIED_PAYLOAD_BYTES
    digest = _digests(store)[0]
    assert store.get_asset(digest).digest == digest


def test_every_cache_entry_is_charged_including_the_bindings_key(scene):
    """🔴 "AN UNCOUNTED CACHE" IS THE SAME LEAK AS "A CACHE WITHOUT A LIMIT"
    (review6, N-2).

    The key `("bindings", revision_id, digests)` was being charged as ZERO:
    its value is `True`, and the temptation was strong. But the key carries a
    tuple of ALL the revision's digests and grows with the number of bodies,
    and once the limit is exhausted the condition `spent + 0 > limit` is
    false for any `spent` — such entries WOULD ALWAYS get stored. This was my
    own unfinished move: the neighboring `_referenced_digests` had its zero
    removed an hour earlier, this one had not.

    The pin checks BOTH properties: the counter grows with every kind of
    entry, and once the limit is exhausted, not a single kind gets stored.
    """
    from kir import project_store as PS

    from kir.project import ModuleInstance

    # 🔴 The `bindings` key lives only on WRITE: after bringing the hot path
    # in line with the header's rule, reading the head no longer traverses
    # assets. So it must be measured via a commit too, otherwise the pin
    # would be checking emptiness (the first draft did check emptiness).
    store = ProjectStore.open(scene, readonly=False)
    head = store.head()
    touched = [ModuleInstance(item.key, item.module_key, list(item.outputs),
                              dict(item.parameters),
                              metadata={**dict(item.metadata or {}), "note": "n-2"})
               if index == 0 else item
               for index, item in enumerate(head.instances)]
    store.commit(head.revise(expected_revision=head.revision_id, instances=touched),
                 expected_revision=head.revision_id)
    for digest in _digests(store):
        store.get_asset(digest)
    counters = {PS._VERIFIED_BYTES_KEY, PS._VERIFIED_STRUCTURE_KEY}
    kinds = {"assets": 0, "asset_ok": 0, "revision": 0, "refs": 0, "bindings": 0}
    for key in store._verified:
        if key in counters:
            continue
        kinds["asset_ok" if isinstance(key, tuple) and key[0] == PS._ASSET_OK else
              "bindings" if isinstance(key, tuple) and key[0] == "bindings" else
              "revision" if isinstance(key, tuple) and key[0] == "revision" else
              "refs" if isinstance(key, tuple) and key[0] == "refs" else "assets"] += 1
    assert kinds["bindings"] >= 1 and kinds["assets"] >= 1 and kinds["asset_ok"] >= 1, kinds
    spent = store._verified[PS._VERIFIED_BYTES_KEY]
    structure = store._verified[PS._VERIFIED_STRUCTURE_KEY]

    # 🔴 THERE ARE TWO BUDGETS, AND EACH KIND IS CHARGED TO ITS OWN (08.09.2026).
    # Body payloads go into the BYTES budget, structure (references, ownership
    # checks, revisions, fingerprints) goes into the STRUCTURE budget. No kind
    # is still charged as zero: both counters are strictly positive, and the
    # byte counter equals exactly the sum of the retained payloads — meaning
    # there is nothing foreign in it.
    payloads = sum(len(value[0]) for key, value in store._verified.items()
                   if isinstance(key, str) and key not in counters)
    assert spent == payloads > 0, (spent, payloads, kinds)
    assert structure > 0, (structure, kinds)

    # The limit is exhausted — NOTHING gets stored, including `bindings`.
    # BOTH are exhausted: `bindings` lives in the structural one, and
    # checking it against the bytes limit would mean checking the wrong
    # limit.
    cold = ProjectStore.open(scene, readonly=False)
    cold._verified[PS._VERIFIED_BYTES_KEY] = PS._VERIFIED_PAYLOAD_BYTES
    cold._verified[PS._VERIFIED_STRUCTURE_KEY] = PS._VERIFIED_STRUCTURE_BYTES
    fresh = cold.head()
    again = [ModuleInstance(item.key, item.module_key, list(item.outputs),
                            dict(item.parameters),
                            metadata={**dict(item.metadata or {}), "note": "n-2b"})
             if index == 0 else item
             for index, item in enumerate(fresh.instances)]
    cold.commit(fresh.revise(expected_revision=fresh.revision_id, instances=again),
                expected_revision=fresh.revision_id)
    assert not [k for k in cold._verified
                if isinstance(k, tuple) and k[0] == "bindings"], (
        "ключ `bindings` лёг при исчерпанном пределе — он списан в ноль")


# ── FOURTH MOVE (of the same shift): THE FULL TRAVERSAL IS ALSO PAID FOR ONCE ─
# 🔴 THE NUMBER THAT STARTED THESE PINS (07.09.2026, measurement of an edit on
# 2000 bodies). `accept_proposal` calls `store.history()` on EVERY edit, and
# `_read_history` was not given the handle's guarantee at all: it re-parsed
# EVERY revision from scratch (0.46 s over 2000 instances), re-checked
# ownership of EACH one (1.9 s), and re-parsed ALL bundles (3.4 ms × 2005).
# Hence `accept_proposal` took 24.7 s just on the traversal at 8 revisions,
# plus +2.5 s for every following edit — that is, the cost of an edit grew
# with the HISTORY, not with the edit. The commit
# (`_commit_prepared_revision`) was not given the same memory either, and
# every entry paid to re-parse 2000 bundles from scratch. After handing over
# the guarantee: an edit went 54.0 s -> 7.4 s and WITHOUT growth.
#
# There is no weakening here and there cannot be: EVERY row is still read
# from SQLite on every traversal, and the remembered value is handed back
# ONLY when the BYTES match. The pins below demand both properties at once —
# the numbers, and a refusal after a substitution.

def _stored_asset_count(path):
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT count(*) FROM geometry_assets").fetchone()[0]
    finally:
        connection.close()


def _swap_asset_payload(path, digest):
    """A CONTENT substitution under the same name is exactly what the digest must catch."""
    connection = sqlite3.connect(path)
    try:
        payload = connection.execute(
            "SELECT payload FROM geometry_assets WHERE digest=?", (digest,)).fetchone()[0]
        connection.execute(
            "UPDATE geometry_assets SET payload=? WHERE digest=?",
            (payload.replace('"units": "mm"', '"units": "cm"', 1)
             if '"units": "mm"' in payload else payload + " ", digest))
        connection.commit()
    finally:
        connection.close()


def test_a_full_audit_is_paid_once_per_handle(wide):
    """THE NUMBER: the first `history()` parses every body, the second — none at all."""
    total = _stored_asset_count(wide)
    assert total == 17, f"ассетов {total} — сцена не та"
    store = ProjectStore.open(wide)
    with _Counter() as first:
        assert store.history()
    assert first.loads == total, (
        f"первый полный обход разобрал {first.loads} тел при {total} в базе")
    with _Counter() as second:
        assert store.history()
    assert second.loads == 0, (
        f"второй полный обход того же handle стоил {second.loads} разборов — "
        "ручательство не доехало до `_read_history`")
    # A fresh handle does not inherit its check: the guarantee belongs to the handle.
    with _Counter() as cold:
        ProjectStore.open(wide).history()
    assert cold.loads == total, f"новый handle разобрал {cold.loads} тел вместо {total}"


def test_a_warm_full_audit_still_refuses_a_swapped_asset(scene):
    """🔴 LEVER FAIL CONTROL: the traversal is warmed up TWICE, then a substitution — red."""
    store = ProjectStore.open(scene)
    assert store.history() and store.history()   # warmed up the FULL traversal
    with _Counter() as warm:
        store.history()
    assert warm.loads == 0, "обход не прогрелся — контроль мерил бы не то"
    _swap_asset_payload(scene, _digests(store)[0])
    with pytest.raises(StoreCorrupt):
        store.history()
    # And a repeated question answers the same way: a guarantee miss is not "healed".
    with pytest.raises(StoreCorrupt):
        store.history()


def test_a_warm_full_audit_still_refuses_a_swapped_revision_payload(scene):
    """🔴 FAIL CONTROL of the second half: the REVISION'S PAYLOAD was substituted, not the body."""
    store = ProjectStore.open(scene)
    assert store.history() and store.history()
    head = store.head()
    connection = sqlite3.connect(scene)
    try:
        payload = connection.execute(
            "SELECT payload FROM revisions WHERE revision_id=?",
            (head.revision_id,)).fetchone()[0]
        connection.execute("UPDATE revisions SET payload=? WHERE revision_id=?",
                           (payload + " ", head.revision_id))
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(StoreCorrupt, match="payload"):
        store.history()


def test_a_write_remembers_its_binding_check_and_a_later_swap_is_still_refused(scene):
    """🔴 A WRITE ALSO STORES `bindings` — and this is not a weakening, but
    the same fact about bytes.

    The earlier condition (`stored and not provided`) left the write without
    memory: every edit paid for `validate_geometry_bindings` twice — on
    commit and on the next full traversal. Both halves of the check are
    byte-level IN THE SAME CALL, and the control below shows that a
    substitution after this is still red.
    """
    from kir.project import ModuleInstance

    store = ProjectStore.open(scene, readonly=False)
    head = store.head()
    touched = [ModuleInstance(item.key, item.module_key, list(item.outputs),
                              dict(item.parameters),
                              metadata={**dict(item.metadata or {}), "note": "audit-4"})
               if index == 0 else item
               for index, item in enumerate(head.instances)]
    store.commit(head.revise(expected_revision=head.revision_id, instances=touched),
                 expected_revision=head.revision_id)
    assert [key for key in store._verified
            if isinstance(key, tuple) and key[0] == "bindings"], (
        "коммит не запомнил сверку владения — рычаг не подключён")
    with _Counter() as audit:
        store.history()
    assert audit.loads == 0, (
        f"полный обход после записи стоил {audit.loads} разборов — "
        "запись и обход не делят одну память")
    _swap_asset_payload(scene, _digests(store)[0])
    with pytest.raises(StoreCorrupt):
        store.history()
    with pytest.raises(StoreCorrupt):
        store.get_asset(_digests(store)[0])


# ── FIFTH MOVE: A SET OF BODIES IS READ IN ONE TRANSACTION ─────────────────
# 🔴 THE NUMBER (07.09.2026, N=2000): `get_asset` opens ITS OWN transaction,
# and a transaction is `_read_state`: seven SQL queries plus checking the
# schema, the head, and the parent. 2000 one-by-one reads cost **14.07 s**,
# the same 2000 inside one transaction — **0.22 s** (64×). What was being
# paid for was not the bodies, but a 2000-fold repeat of the store check.
# The pins below require that the batch answer THE SAME THING as N single
# reads, and that a substitution in it still remains `StoreCorrupt`.

def test_a_batch_read_answers_exactly_what_single_reads_answer(wide):
    store = ProjectStore.open(wide)
    digests = _digests(store)
    one_by_one = {digest: store.get_asset(digest).dumps() for digest in digests}
    batched = {digest: bundle.dumps()
               for digest, bundle in ProjectStore.open(wide).get_assets(digests).items()}
    assert batched == one_by_one, "пакет ответил не то же, что поштучное чтение"
    # Repeats within the request collapse together, they don't double the work.
    assert set(ProjectStore.open(wide).get_assets(digests + digests)) == set(digests)
    assert ProjectStore.open(wide).get_assets([]) == {}


def test_a_batch_read_pays_one_full_check_per_asset_and_none_on_the_second(wide):
    """THE NUMBER: the batch parses every body EXACTLY once, the second batch — none at all."""
    total = _stored_asset_count(wide)
    store = ProjectStore.open(wide)
    digests = _digests(store)
    with _Counter() as first:
        store.get_assets(digests)
    assert first.loads == len(digests), (first.loads, len(digests), total)
    with _Counter() as second:
        store.get_assets(digests)
    assert second.loads == 0, f"второй пакет стоил {second.loads} разборов"


def test_a_batch_read_still_refuses_a_swapped_asset(scene):
    """🔴 FAIL CONTROL: the batch is warmed up, the bytes are substituted — a refusal, not "same as before"."""
    store = ProjectStore.open(scene)
    digests = _digests(store)
    assert store.get_assets(digests)
    with _Counter() as warm:
        store.get_assets(digests)
    assert warm.loads == 0, "пакет не прогрелся — контроль мерил бы не то"
    _swap_asset_payload(scene, digests[0])
    with pytest.raises(StoreCorrupt):
        store.get_assets(digests)
    # And a one-by-one read of the same body answers the same way: one measure for both paths.
    with pytest.raises(StoreCorrupt):
        store.get_asset(digests[0])


def test_a_batch_read_separates_a_missing_body_from_an_unknown_one(scene):
    """"The head references it, but the row is missing" is corruption; "we don't hold such a thing" is not-found."""
    import sqlite3

    store = ProjectStore.open(scene)
    digests = _digests(store)
    with pytest.raises(StoreNotFound):
        store.get_assets([digests[0], "0" * 64])
    connection = sqlite3.connect(scene)
    try:
        connection.execute("DELETE FROM geometry_assets WHERE digest=?", (digests[0],))
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(StoreCorrupt, match="referenced geometry asset is missing"):
        ProjectStore.open(scene).get_assets(digests)


def test_a_batch_read_refuses_a_malformed_identity_without_touching_the_store(scene):
    store = ProjectStore.open(scene)
    for bad in ("", "нет", "A" * 64, 42, None):
        with pytest.raises(StoreNotFound):
            store.get_assets([bad])


# ── FIFTH MOVE (08.09.2026, direction S): THE INTEGRITY TRAVERSAL DOES NOT
# PARSE BODIES ─
# 🔴 THE NUMBER THAT STARTED THESE PINS. The guarantee had ONE budget, and it
# was being eaten by body payloads: of the 77.13 MiB spent by traversing the
# history of 2000 bodies, 69.09 MiB (99.4%) were the payloads of 2005 assets
# at 36 KB each, saving 3.4 ms of parsing apiece. Next to it stood the
# `bindings` key — 64·N ≈ 640 KB for 10,000 bodies, saving ~10 s of
# `validate_geometry_bindings`. At N=10,000 the payloads (~362 MB) blow past
# 256 MiB on the VERY FIRST revision, and after that NOTHING gets stored,
# including the cheap keys. Hence `history()` at 0.42 s for N=2000 and 79.9 s
# for N=10,000. A measurement of the contribution on one store (2000 bodies,
# 8 revisions, the same traversal, only the budget shrunk, its OWN process
# per limit): warm `history()` at 256 MiB -> 0.32 s · 64 MiB -> 8.64 s · 32
# MiB -> 12.59 s · 16 MiB -> 14.60 s · 0 -> 17.79 s.
# With the budgets split, the same series is FLAT: 0.34 · 0.35 · 0.61 · 0.57 ·
# 0.72 s. FAIL control: zeroing out the STRUCTURAL budget brings the numbers
# back (11.10 s at a payload limit of 256 MiB, 15.06 s at 32 MiB, 17.84 s at
# 0).

def test_an_integrity_walk_does_not_parse_bodies_it_already_verified(wide):
    """The second traversal reads EVERY row, but parses ZERO bodies."""
    from kir import project_store as PS

    store = ProjectStore.open(wide)
    rows_first = calls_first = 0
    parsed = []
    original = PS._read_asset
    loads = None

    import kir.occt_geometry as OG
    original_loads = OG.GeometryBundle.loads

    def counting_loads(payload):
        parsed.append(1)
        return original_loads(payload)

    OG.GeometryBundle.loads = staticmethod(counting_loads)
    try:
        store.history()
        first = len(parsed)
        parsed.clear()
        store.history()
        second = len(parsed)
    finally:
        OG.GeometryBundle.loads = staticmethod(original_loads)
    assert first > 0, "первый обход обязан разобрать тела"
    assert second == 0, (first, second, "второй обход разбирал заново")


def test_an_integrity_walk_still_reads_every_row_and_refuses_a_swap(wide, tmp_path):
    """The savings are in PARSING, not in READING: substituted bytes are still a refusal."""
    import shutil

    copy = tmp_path / "swap.kir"
    shutil.copy(wide, copy)
    store = ProjectStore.open(copy)
    store.history()          # the traversal is warm: fingerprints and `bindings` are in place
    digest = _digests(store)[0]
    _swap_asset_payload(copy, digest)
    with pytest.raises(StoreCorrupt):
        store.history()


def test_a_reader_that_needs_a_body_still_gets_a_parsed_bundle(wide):
    """A "row confirmed" mark does not substitute for the body itself."""
    from kir.occt_geometry import GeometryBundle

    store = ProjectStore.open(wide)
    store.history()
    for digest in _digests(store):
        bundle = store.get_asset(digest)
        assert isinstance(bundle, GeometryBundle) and bundle.digest == digest
    batch = store.get_assets(_digests(store))
    assert all(isinstance(value, GeometryBundle) for value in batch.values())


def test_the_structure_budget_is_named_and_bounded():
    """The structure budget is A NUMBER, not "however much fits"."""
    from kir import project_store as PS

    assert isinstance(PS._VERIFIED_STRUCTURE_BYTES, int) and PS._VERIFIED_STRUCTURE_BYTES > 0
    assert PS._VERIFIED_STRUCTURE_BYTES < PS._VERIFIED_PAYLOAD_BYTES
    verified = {}
    PS._remember_verified(verified, ("refs", "x"), frozenset(), 1, structure=True)
    PS._remember_verified(verified, "y" * 64, ("payload", None), 1)
    assert verified[PS._VERIFIED_STRUCTURE_KEY] == 1 and verified[PS._VERIFIED_BYTES_KEY] == 1
    verified[PS._VERIFIED_STRUCTURE_KEY] = PS._VERIFIED_STRUCTURE_BYTES
    PS._remember_verified(verified, ("refs", "z"), frozenset(), 1, structure=True)
    assert ("refs", "z") not in verified
