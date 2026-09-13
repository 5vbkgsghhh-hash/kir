"""Folding a REPEAT in the receipt: the same thing is said once and counted.

🔴 THE MEASUREMENT THAT PAID FOR THIS (21.08.2026, a live program of 100 walls).

A receipt for a hundred elements weighs **85,046 characters**, and four keys
eat up 80.6% — all four grow LINEARLY with the number of operations:

```
26.2 %  resolved_refs        what resolved into what, per op
25.7 %  grounding_report     how the type/level was chosen, per op
18.3 %  result               what Revit returned, per op
10.4 %  defaults_note_ru     which defaults were substituted
```

The growth is **785 bytes per element**. From this, 20,000 operations give
~16 MB, and 100,000 give ~78 MB. The owner's correction on 20.08 says
exactly this: "at 100,000 operations the receipt will drown the author, and
attention will run out before the building does."

🔴 BUT WHAT MUST BE FOLDED IS NOT DETAIL, IT IS REPETITION — AND THEN
NOTHING IS LOST. A breakdown of those same hundred records:

```
resolved_refs      100 records · MEANINGFULLY DIFFERENT — ONE
grounding_report   100 records · MEANINGFULLY DIFFERENT — ONE
defaults_note_ru   8,821 characters — one phrase about «Типовой - 200мм», a hundred times
```

Forty-four kilobytes out of eighty-five are a pure repeat of one fact. "A
summary instead of the details" would have been both a loss and extra work
here: it is enough to state the fact ONCE and attach how many and which ops
it applies to.

WHY THE SIGNATURE IS BUILT BY SUBSTITUTION, NOT BY A LIST OF FIELDS. In
`grounding_report`, the `read_from` field carries `"result.wall1.type_name"`
— that is, the op's name sits INSIDE the string, and letter for letter such
records are all different. A list of fields to strip out ("op_id,
read_from") would have to be maintained by hand, and it would drift from the
data on the very first new field that also mentions the op. So the
signature replaces ANY occurrence of its own `op_id` with a marker: one
rule, derived from the data, that survives new fields.

WHAT THIS FOLDING DOES NOT DO, AND WILL NOT DO:

* **it does not lose a single `op_id`.** All of them are listed in the
  folded record. The canon forbids silent truncation: "if the work limits
  its scope, print what was dropped" — here nothing is dropped;
* **it does not fold DIFFERENT things.** Two records with a different type
  choice remain two records, however many there are. If they differ ONLY at
  the spot where the record's own `op_id` sits, the folded record carries a
  TEMPLATE with the marker `op_id_placeholder`, not the body of the first
  one: substituting any `op_ids[i]` restores the original string byte for
  byte. Before 29.08.2026 the body of the first one was printed, and
  «Стеклопакет S1-2100» was passed off as the shared choice for `S1` and
  `S2` (F-367);
* **it does not decide what matters to the author.** It is arithmetic, not
  editorial.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Sequence

#: The key by which a record knows its op. Receipt records have no other
#: address, and adding a second one would mean adding a second way to get
#: it wrong.
OP_KEY = "op_id"

#: A marker in place of the op's name in the signature. Not an empty
#: string: an empty one would merge with a genuinely empty value, and two
#: DIFFERENT records would become one.
_OP_MARK = "\x00op\x00"

#: 🔴 A READABLE MARKER FOR OUTPUT (29.08.2026, audit finding F-367).
#: `_OP_MARK` is a control character: it works for the SIGNATURE and does
#: not work for the receipt, which a human reads and a foreign program
#: parses. There are two markers, not one, and this is not duplication: the
#: internal one must NEVER OCCUR in the data, the external one must be
#: READABLE. One value cannot be both.
OP_PLACEHOLDER = "«op_id»"


def _render(value: Any) -> Any:
    """Turn the internal marker into the readable one, at any depth."""
    if isinstance(value, str):
        return value.replace(_OP_MARK, OP_PLACEHOLDER)
    if isinstance(value, Mapping):
        return {k: _render(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_render(v) for v in value]
    return value


def _mask(value: Any, oid: str) -> Any:
    """Replace any occurrence of the op's name in a value with the marker.

    Recursively: the op's name occurs both in a string
    (`result.wall1.type_name`) and inside nested objects. Numbers and
    booleans are not touched — an op's name cannot be there.
    """
    if isinstance(value, str):
        return value.replace(oid, _OP_MARK) if oid and oid in value else value
    if isinstance(value, Mapping):
        return {k: _mask(v, oid) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mask(v, oid) for v in value]
    return value


def _signature(row: Mapping[str, Any], oid: str) -> str:
    body = {k: _mask(v, oid) for k, v in row.items() if k != OP_KEY}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)


def fold_rows(rows: Sequence[Any]) -> tuple[list[Any], dict[str, int]]:
    """A list of receipt records -> a folded list and a fold count.

    Order is preserved by FIRST occurrence: the author reads the receipt
    top to bottom, and reordering records would change the story told about
    the program.

    A record seen once is returned AS IS — without a single added field. A
    folded record carries `op_ids` and `applies_to` instead of `op_id`, and
    they let everything that was there be recovered.
    """
    if not isinstance(rows, (list, tuple)) or len(rows) < 2:
        return list(rows or []), {"rows_in": len(rows or []),
                                  "rows_out": len(rows or []), "folded": 0}
    groups: dict[str, list[Mapping[str, Any]]] = {}
    #: 🔴 A TAPE, NOT TWO LISTS (30.08.2026, audit finding F-368). Before, a
    #: foreign shape was accumulated separately and appended AFTER all the
    #: groups: a record that stood BETWEEN two folded ones moved to the
    #: end. This same function's contract forbids exactly that — "order is
    #: preserved by FIRST occurrence: the author reads the receipt top to
    #: bottom, and reordering records would change the story told about the
    #: program."
    #:
    #: The defect was INVISIBLE BY THE COUNTERS: `rows_in == rows_out`,
    #: `folded == 0`, not a single record lost. Only the MEANING changed — a
    #: note that referred to what came BEFORE it ended up after everything.
    #:
    #: The tape stores the place of EVERY record: the signature for a group,
    #: the record itself for a foreign shape. A group is placed where it was
    #: FIRST seen.
    лента: list[tuple[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            # Not a record — we neither fold nor discard it. The shape is
            # foreign, so the rule is foreign too, but the PLACE is its own.
            лента.append(("plain", row))
            continue
        oid = str(row.get(OP_KEY) or "")
        sig = _signature(row, oid)
        if sig not in groups:
            groups[sig] = []
            лента.append(("group", sig))
        groups[sig].append(row)

    out: list[Any] = []
    folded = 0
    for род, что in лента:
        if род == "plain":
            out.append(что)
            continue
        members = groups[что]
        first = members[0]
        if len(members) == 1:
            out.append(dict(first))
            continue
        folded += len(members) - 1
        ids = [str(m.get(OP_KEY) or "") for m in members]
        # 🔴 A TEMPLATE, NOT THE FIRST INSTANCE (29.08.2026, audit finding
        # F-367). The signature compares strings WITH `op_id` MASKED, while
        # the RAW body of the first one traveled into the receipt. Where
        # `op_id` sits INSIDE the value (a type name like «Стеклопакет
        # S1-2100» at op `S1`), two records about DIFFERENT types produced
        # one signature, and the second one disappeared: a human read ONE
        # type where Revit had applied TWO, while right next to it stood
        # "not one op_id lost" — a truth about a DIFFERENT subject.
        #
        # The root was exactly here: the signature compared TEMPLATES, while
        # an INSTANCE was printed. As long as the two diverge, no mask —
        # neither by word boundary nor by schema — saves you: it only
        # changes the set of matches.
        #
        # The template is REVERSIBLE: substituting each `op_ids[i]` for
        # `op_id_placeholder` gives back the original string byte for byte.
        # So the header's promise, "nothing is lost," becomes a PROPERTY.
        body = {k: _render(_mask(v, str(first.get(OP_KEY) or "")))
                for k, v in first.items() if k != OP_KEY}
        body["applies_to"] = len(members)
        body["op_ids"] = ids
        #: The reader must learn about the substitution FROM THE RECORD
        #: ITSELF, not from the module's docstring, which is not in front of
        #: them.
        body["op_id_placeholder"] = OP_PLACEHOLDER
        out.append(body)
    return out, {"rows_in": len(rows), "rows_out": len(out), "folded": folded}


def fold_sentences(note: str, sep: str = "; ") -> tuple[str, dict[str, int]]:
    """The same for the human-readable note: one phrase instead of a hundred identical ones.

    `defaults_note_ru` for a hundred walls is 8,821 characters, of which one
    phrase is repeated a hundred times. We count the repeats and print
    "×N" next to the phrase: the number here is not decoration, it answers
    the question "how many ops does this apply to," which would otherwise
    have to be looked up in the machine report.
    """
    if not isinstance(note, str) or not note.strip():
        return note, {"parts_in": 0, "parts_out": 0}
    parts = [p.strip() for p in note.split(sep) if p.strip()]
    if len(parts) < 2:
        return note, {"parts_in": len(parts), "parts_out": len(parts)}
    counts: dict[str, int] = {}
    order: list[str] = []
    for p in parts:
        if p not in counts:
            counts[p] = 0
            order.append(p)
        counts[p] += 1
    out = sep.join(p if counts[p] == 1 else f"{p} ×{counts[p]}" for p in order)
    return out, {"parts_in": len(parts), "parts_out": len(order)}


def fold_note_ru(stats: Iterable[tuple[str, dict[str, int]]]) -> str:
    """One line about WHAT was folded. Empty if nothing was folded.

    Printed alongside the fold itself: the reader must learn that the
    receipt has been shortened FROM IT, not from knowing about this module.
    """
    parts = []
    for name, s in stats:
        folded = s.get("folded") or (s.get("parts_in", 0) - s.get("parts_out", 0))
        if folded and folded > 0:
            was = s.get("rows_in", s.get("parts_in", 0))
            now = s.get("rows_out", s.get("parts_out", 0))
            parts.append(f"{name} {was}→{now}")
    if not parts:
        return ""
    return ("свёрнут ПОВТОР (одинаковое сказано один раз и посчитано, "
            "ни один op_id не потерян): " + " · ".join(parts))
