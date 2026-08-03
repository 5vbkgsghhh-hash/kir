"""The obfuscator renames variables; C# shorthand members renamed the RESULT.

`new { minX, maxX }` takes its member NAMES from the variables, so obfuscating
a local silently renames the JSON key the model has to read back. Measured on
prod 2026-07-27: 22 of 873 bridge results returned `_0x…` keys, one of them the
element-id field. These lock the round-trip: whatever the obfuscator renames on
the way out is restored on the way in.
"""
from __future__ import annotations

from kukai.api.bridge_protocol import _deobfuscate_result
from kukai.security.obfuscator import obfuscate_code_with_map


def _inverse(rename_map: dict[str, str]) -> dict[str, str]:
    return {obf: orig for orig, obf in rename_map.items()}


def test_shorthand_member_names_are_obfuscated_in_the_first_place():
    """Guard the premise: if this ever stops being true the fix is dead code."""
    code = (
        "var levels = new List<object>();\n"
        "double minX = 0.0;\n"
        '__res["bounds"] = new { minX };\n'
        '__res["levels"] = levels;\n'
    )
    out, rename_map = obfuscate_code_with_map(code)
    assert "minX" in rename_map
    assert "new { _0x" in out          # the member name went with the variable
    assert '__res["bounds"]' in out    # string literals stay untouched


def test_result_keys_are_restored():
    rename_map = {"minX": "_0xa5cc", "maxX": "_0xb404", "levels": "_0x1e1b"}
    payload = {
        "_0x1e1b": [{"name": "L_01", "elevation_m": 0}],
        "bounds_m": {"_0xa5cc": -8.7, "_0xb404": 49.2, "maxY": 110.4},
        "ok": True,
    }
    out = _deobfuscate_result(payload, _inverse(rename_map))
    assert out["levels"] == [{"name": "L_01", "elevation_m": 0}]
    assert out["bounds_m"] == {"minX": -8.7, "maxX": 49.2, "maxY": 110.4}
    assert out["ok"] is True


def test_nested_lists_and_id_fields():
    """The prod case that mattered: ids arriving under a name nothing can read."""
    rename_map = {"elementId": "_0xa703"}
    payload = {"selection": [{"_0xa703": "874533", "category": "Стены"}]}
    out = _deobfuscate_result(payload, _inverse(rename_map))
    assert out["selection"][0]["elementId"] == "874533"
    assert out["selection"][0]["category"] == "Стены"


def test_string_values_only_replaced_on_exact_token_match():
    rename_map = {"wall": "_0xdead"}
    payload = {"note": "value _0xdead inside prose", "kind": "_0xdead"}
    out = _deobfuscate_result(payload, _inverse(rename_map))
    assert out["kind"] == "wall"                          # exact token → restored
    assert out["note"] == "value _0xdead inside prose"    # substring → untouched


def test_unmapped_tokens_and_scalars_survive():
    out = _deobfuscate_result({"_0xffff": 1, "n": 2, "s": "plain"}, {"_0x0001": "x"})
    assert out == {"_0xffff": 1, "n": 2, "s": "plain"}
    assert _deobfuscate_result(None, {"_0x0001": "x"}) is None
    assert _deobfuscate_result(5, {"_0x0001": "x"}) == 5
