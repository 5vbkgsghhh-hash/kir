"""THE BUILDING VIEWER — the thing everything else exists for.

The package deliberately imports NOTHING at module level, for exactly the
same reason as `kir/live/__init__.py`: `kir.__init__` pulls in the
compiler, so any module inside `kir` drags in the compiler by the mere
fact of its location. The viewer lives as a separate package and takes the
compiler ONLY where it actually judges compilability (`compilability`),
and geometry ONLY via a lazy import of `clash` (`scene`).

FIVE MODULES, AND WHY THERE ARE FIVE:

  * `honesty`  — the trust-and-precision vocabulary; not a single drawing
    call, not a single heavy import. It is a LEAF, and a load-bearing one:
    both the decompile scene and the live-journal scene read it, and they
    must speak about the same thing in the same words. Two honesty
    vocabularies would silently drift apart;
  * `codec`    — the scene's bytes. Stdlib only. Neither `clash` nor `ir`;
  * `scene`    — the DECOMPILED building: `clash` shells + `tree.json`;
  * `live_scene` — the DECLARED building: `kir.live.journal` programs,
    extruded via `preview`. Including what is not yet committed to Revit;
  * `compilability` — a continuous "this will compile right now" indicator,
    together with the full list of what it does NOT check.

ONE SCREEN, TWO SOURCES. `scene` and `live_scene` encode ONE format and use
ONE honesty vocabulary, so "open an existing model" and "watch a model
being written" are one screen, not two. The difference rides in the
`assertion` field: `independent` for a decompile, `self_reported` for a
journal. The client must display it, not compute it.

BOUNDARIES. Not a single line is written into `kir/clash/**`: another agent
works there, and only reads happen from here. `kir/serving.py`, `spec.py`,
`ops_*.py`, `authoring.py`, `decompile/**` — read-only as well.
"""
