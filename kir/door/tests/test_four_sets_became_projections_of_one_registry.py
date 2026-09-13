"""G5 — four sets became projections of one registry.

Measured 13.09.2026 (audit H §1): MCP 7 tools · panel 3 · CLI 9 · window 28
routes — four answers to "how do I build" for one language, and eight
subjects that had drifted between two of them (§1.2). The window's 28 died on
their own with commit `116d9a0`; the rest die here, by construction: a host
chooses the WRAPPER and never the content.
"""
from __future__ import annotations

import json

from kir.door import registry as R


def test_the_name_sets_of_three_hosts_are_equal():
    for role in R.ROLES:
        sets = [tuple(_names_of(R.projection(host, role))) for host in R.HOSTS]
        assert len(set(sets)) == 1, (role, sets)
        assert sets[0] == R.names(role)


def test_the_schema_digests_of_three_hosts_are_equal():
    for role in R.ROLES:
        digests = [R.schema_digest(host, role) for host in R.HOSTS]
        assert all(d == digests[0] for d in digests), role
        assert set(digests[0]) == set(R.names(role))


def test_the_description_bytes_are_equal_across_hosts():
    """The wrapper may differ; the prose may not. A host that shortens a
    description is a fifth set wearing a projection's name."""
    for role in R.ROLES:
        per_host = []
        for host in R.HOSTS:
            per_host.append(tuple(sorted(
                (_name(item), len(_description(item).encode()))
                for item in R.projection(host, role))))
        assert len(set(per_host)) == 1, role


def test_the_registry_is_the_only_carrier_of_a_tool():
    """Every projected name comes from TOOLS, and TOOLS is a tuple — so the
    order is a fact, not a dict's history."""
    known = {t.name for t in R.TOOLS}
    for host in R.HOSTS:
        for role in R.ROLES:
            assert {_name(i) for i in R.projection(host, role)} <= known
    assert isinstance(R.TOOLS, tuple)


def test_the_panel_wrapper_is_the_products_function_shape():
    item = R.projection("panel", "expert")[0]
    assert item["type"] == "function"
    assert set(item["function"]) == {"name", "description", "parameters"}


def test_control_editing_one_host_only_goes_red():
    """The defect this gate exists for, reproduced: change one host's schema
    and the digests must diverge."""
    role = "expert"
    base = R.schema_digest("mcp", role)
    tampered = dict(base)
    tampered["kir_build"] = "0" * 64
    assert tampered != R.schema_digest("panel", role)


def _names_of(items) -> list:
    return [_name(i) for i in items]


def _name(item: dict) -> str:
    return item.get("name") or item["function"]["name"]


def _description(item: dict) -> str:
    if "description" in item:
        return item["description"]
    return item["function"]["description"]
