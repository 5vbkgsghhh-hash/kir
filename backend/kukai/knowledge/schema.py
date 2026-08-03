"""Canonical capability syntax shared by corpus build and live routing."""

from __future__ import annotations

import re
from dataclasses import dataclass

_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class Capability:
    action: str
    object_kinds: tuple[str, ...]

    def canonical(self) -> str:
        objects = ",".join(self.object_kinds) if self.object_kinds else "-"
        return f"{self.action}×{objects}"


def parse_capability(value: str, *, allow_bare_action: bool = False) -> Capability:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("empty capability")
    if "×" not in raw:
        if not allow_bare_action:
            raise ValueError(f"capability must use action×objects syntax: {raw!r}")
        action, objects_raw = raw, "-"
    else:
        action, objects_raw = raw.split("×", 1)
    action = action.strip().lower()
    if not _IDENT_RE.fullmatch(action):
        raise ValueError(f"invalid capability action: {action!r}")
    objects: list[str] = []
    seen: set[str] = set()
    for item in objects_raw.split(","):
        item = item.strip().lower()
        if item in {"", "-"}:
            continue
        if not _IDENT_RE.fullmatch(item):
            raise ValueError(f"invalid capability object kind: {item!r}")
        if item not in seen:
            seen.add(item)
            objects.append(item)
    return Capability(action=action, object_kinds=tuple(objects))
