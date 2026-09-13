# THE DOOR'S BOUNDARY: `kir/mcp` IS NEITHER THE LANGUAGE NOR THE HAND

Set up on 2026-09-02 by the owner's word: "MCP needs to be separated out of KIR a
bit, so it doesn't confuse us and the project is clearer."

## Three subjects that are easy to confuse, and they are different

| directory | subject | who it talks to |
|---|---|---|
| `kir/` (everything else) | **THE LANGUAGE**: registry, compiler, building graph | no one; prints C# |
| `kir/bridge/` | **THE HAND**: the bridge protocol to the Revit plugin | to Revit |
| `kir/mcp/` | **THE DOOR**: presenting the language to a foreign host | to the host (Claude, an IDE) |

The `bridge` <-> `mcp` confusion is not hypothetical: both are "about a protocol", both
are "about JSON-RPC", both have the word "server" in them. What tells them apart is
DIRECTION: the hand reaches FROM us TO Revit, the door opens TOWARD us from outside. The
language knows about neither.

## What lives behind the door

| file | subject |
|---|---|
| `surface.py` | what the door PRESENTS: names, descriptions, schemas. The SDK doesn't know it |
| `server.py` | the wire: the door dispatcher, resources, transport. The SDK's only home |
| `app.py` | the MCP app document (`ui://`), self-contained HTML |
| `tests/` | instruments. NOT counted toward the boundary — the reasoning is in `_door_sources` |

## What is guarded BY NUMBER (`tests/test_the_door_is_separable.py`)

```
language -> door         0 references  no KIR module outside kir/mcp
                                       mentions kir.mcp
import kir -> kir.mcp    does NOT load  measured in a fresh process, not reasoned about
protocol SDK             1 file         `mcp`/`mcp_types` live only in
                                       kir/mcp/server.py and only INSIDE a function
door -> language         9 modules     A CLOSED LIST; a new module in it is
                                       a decision, not a side effect
surface without the SDK  imports       kir.mcp.surface is read by whoever
                                       installed KIR WITHOUT the [mcp] extra
```

Instruments (`tests/`) are excluded from these counts, and this is stated once in
`_door_sources`: everything listed is a promise to A FOREIGN PERSON, and instruments
don't run for them. An instrument that checks THE WIRE needs the SDK by its very subject.

## Stage 3: the MCP app (`io.modelcontextprotocol/ui`)

`kir_preview` carries `_meta.ui.resourceUri` -> `ui://kir/floorplan.html`, the door
serves this document via `resources/read`. Guarded by the same kind of numbers:

```
link -> served           the loop closes  the tool and the wire assemble the URI
                                        by DIFFERENT paths (surface vs
                                        served_resources), otherwise the instrument
                                        would be comparing a constant to itself
external resources       0              no src=, no href=, no fetch, no @import
MIME and extension id    == SDK         two carriers of one value cross-checked
the drawing twice        byte-for-byte  nondeterminism breaks the cache and the comparison
census without the app   exists         LAW No. 4 reaches even the text
```

## Why the "door -> language" direction is listed, not forbidden

The door MUST call the language -- otherwise it has nothing to present. A ban would be
a lie. But the list is closed for the same reason the KIR<->product boundary registry
is closed: an unclosed list grows silently, and one day the door will reach for something
a foreign person does not have (the host's port, the install directory, a live bridge) --
and the "stands offline" stage will stop being true, without anything visibly breaking.

## What is not in this door, and will not be without the owner's word

* a **write port**, `llm.revit_execution_pipeline` -- the door does not write to the model;
* **product ports** at all: `ports.need()` is never called here;
* a **KIR-mode gate**: MCP has no notion of a turn, and `revit_ir_enabled()` is not
  carried over here. Stage 4 of the plan opens this question separately.

## 🔴 NAME TRAP: `kir/mcp` SHADOWS THE PROTOCOL SDK

Our directory is called `mcp`, and so is the protocol SDK. As long as the import goes
through as `kir.mcp`, there is no collision. But the moment the `kir/` directory itself
lands on `sys.path` (which is what pytest does from the rootdir, and that's how the full
suite is run), `import mcp` resolves TO US.

Found by a full run on 2026-09-03, not by reasoning. The failure looked like this:

```
ImportError: cannot import name 'CacheHint' from 'mcp.server'
             (…/tree/kir/mcp/server.py)
```

-- that is, it pointed at OUR file and read as our defect.

**And the second half is more expensive than the first:** `pytest.importorskip("mcp")`
PASSED at the very same moment. It honestly imported a module named `mcp` -- just the
wrong one. The guard for the SDK's presence was fooled by our own package, and because of
it one instrument failed exactly where it was supposed to be skipped.

Held in place by two instruments:

```
build_server()   checks that `mcp` did NOT come from this directory, and on
                 shadowing refuses BY NAME, naming the cause and the next move
the door's       ask the SDK's presence from `mcp_types` -- a separate
instruments      distribution that does not collide with us
```

Renaming the directory is not proposed: the name has already shipped to PyPI since
0.3.0, and the trap is lifted with two lines and one named refusal.
