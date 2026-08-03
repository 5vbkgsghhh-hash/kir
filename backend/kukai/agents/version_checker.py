"""VersionChecker — post-flight cross-version (2021-2026) API compatibility audit.

Runs in parallel with CodeCritic after code generation, before compile. Reads
the generated C# and flags Revit API calls that don't exist (or were removed)
in some subset of the target Revit versions.

Output JSON contract (see prompts/version_checker.md):
  {
    "compatible_versions": ["2021","2022","2024","2026"],
    "issues": [
      {
        "api": "Toposolid.Create",
        "min_version": "2024",
        "max_version": null,
        "fix_hint": "Use TopographySurface for 2021-2023"
      }
    ]
  }

Design notes:
- ``compatible_versions`` is the intersection of "versions where every API call
  in the code exists" — a subset of the requested ``target_versions``.
- If the code uses zero version-gated APIs, ``compatible_versions`` equals the
  full input ``target_versions`` and ``issues`` is empty.
- The agent is conservative: APIs not in its authoritative table are assumed
  present in ALL 2021-2026 (avoids false positives that would force
  unnecessary regeneration).
"""
from __future__ import annotations

import json
from typing import Any

from .base import AgentBase, parse_json_block


_VALID_ISSUE_KEYS = frozenset({"api", "min_version", "max_version", "fix_hint"})

_CODE_MAX_CHARS = 3000


class VersionChecker(AgentBase):
    """LLM-based cross-version (2021-2026) Revit API compatibility checker."""

    name = "version_checker"
    model = "gemini-3.5-flash"
    thinking_level = "medium"
    max_tokens = 64000  # no cap per Token budget policy
    timeout_s = 12.0    # post-flight stage, parallel with CodeCritic
    prompt_file = "version_checker"

    _VALID_VERSIONS = frozenset({"2021", "2022", "2023", "2024", "2025", "2026"})

    def build_user_message(
        self,
        code: str,
        target_versions: list[str] | None = None,
    ) -> str:
        """Serialize ``{code, target_versions}`` as JSON.

        Caps:
          - code[:3000]
          - target_versions: must be subset of {2021..2026}; defaults to all 6
            (sorted).

        Raises ``ValueError`` if any element of ``target_versions`` is not a
        recognized Revit version string.
        """
        if target_versions is None:
            targets = sorted(self._VALID_VERSIONS)
        else:
            if not isinstance(target_versions, list):
                raise ValueError(
                    f"target_versions must be a list of strings: {target_versions!r}"
                )
            normalized: list[str] = []
            for v in target_versions:
                vs = str(v)
                if vs not in self._VALID_VERSIONS:
                    raise ValueError(
                        f"invalid target version {vs!r}; expected one of "
                        f"{sorted(self._VALID_VERSIONS)}"
                    )
                normalized.append(vs)
            # Stable, deduplicated ordering
            targets = sorted(set(normalized))

        payload = {
            "code": (code or "")[:_CODE_MAX_CHARS],
            "target_versions": targets,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def parse_response(self, text: str) -> dict[str, Any]:
        data = parse_json_block(text)
        if not isinstance(data, dict):
            raise ValueError(f"expected JSON object, got: {type(data).__name__}")

        raw_compat = data.get("compatible_versions")
        if not isinstance(raw_compat, list):
            raise ValueError(
                f"compatible_versions must be a list: {raw_compat!r}"
            )
        compatible_versions: list[str] = []
        for v in raw_compat:
            if not isinstance(v, str):
                raise ValueError(
                    f"compatible_versions must contain strings: got {v!r}"
                )
            if v not in self._VALID_VERSIONS:
                raise ValueError(
                    f"invalid version in compatible_versions: {v!r}; "
                    f"expected one of {sorted(self._VALID_VERSIONS)}"
                )
            compatible_versions.append(v)

        raw_issues = data.get("issues", []) or []
        if not isinstance(raw_issues, list):
            raise ValueError(f"issues must be a list: {raw_issues!r}")

        issues: list[dict[str, Any]] = []
        for it in raw_issues:
            if not isinstance(it, dict):
                raise ValueError(
                    f"each issue must be an object: got {type(it).__name__}"
                )
            api = it.get("api")
            if not isinstance(api, str) or not api.strip():
                raise ValueError(
                    f"issue.api must be a non-empty string: {api!r}"
                )

            min_v = it.get("min_version", None)
            if min_v is not None:
                if not isinstance(min_v, str) or min_v not in self._VALID_VERSIONS:
                    raise ValueError(
                        f"issue.min_version must be null or a valid version "
                        f"string: {min_v!r}"
                    )

            max_v = it.get("max_version", None)
            if max_v is not None:
                if not isinstance(max_v, str) or max_v not in self._VALID_VERSIONS:
                    raise ValueError(
                        f"issue.max_version must be null or a valid version "
                        f"string: {max_v!r}"
                    )

            fix_hint = it.get("fix_hint", "")
            if fix_hint is not None and not isinstance(fix_hint, str):
                raise ValueError(
                    f"issue.fix_hint must be string or null: {fix_hint!r}"
                )

            issues.append({
                "api": api,
                "min_version": min_v,
                "max_version": max_v,
                "fix_hint": fix_hint if fix_hint is not None else "",
            })

        return {
            "compatible_versions": compatible_versions,
            "issues": issues,
        }
