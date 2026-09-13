"""SHARED DATA MODEL: what BOTH decompile AND clash use.

🔴 WHY IT WAS SET UP (02.09.2026). `snapshot_io`, `identity` and `schema`
used to live inside `kir/decompile/`, even though decompile does not OWN
them — it is a reader just like `kir/clash`. While the house was there, the
packages held a cycle: decompile pulled in the detector
(`decompile.graph_clash_query`, `decompile.federated_clash_query`), while
clash pulled the model out of decompile (`snapshot_io` — the package's most
frequent lazy target, 47 references; `identity`; `schema`).

🔴 AND THIS MOVE DOES NOT BREAK THE CYCLE — MEASURED BEFORE THE FIX, NOT
AFTER. A simulation of removing the three edges: `clash -> decompile` goes
11 -> 4, the cycle REMAINS, held up by four other edges that have nothing
to do with the model:

    clash.federation_transform        -> decompile.federation
    clash.tools.bundle_containment_gate -> decompile.lift, decompile.materialize
    clash_judgement                   -> decompile.extract

That is, clash consumes decompile's PRODUCTS (lift, materialize, extract),
and that is a genuine one-way need that moving files does not cure. What is
closed here is exactly the part that was a LAYOUT mistake: a shared model
that had wandered into someone else's house. The remaining cycle is named
and NOT hidden.

The old addresses live on by re-export: `from kir.decompile.snapshot_io
import …` works as it always did. There is ONE carrier — the definitions
are here.
"""
