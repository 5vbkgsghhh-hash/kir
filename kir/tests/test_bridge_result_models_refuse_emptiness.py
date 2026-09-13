"""AN EMPTY BRIDGE RESPONSE DOES NOT BECOME A FACT ABOUT THE BUILDING.

WHY THIS FILE APPEARED ON 30.08.2026 (audit finding F-349).

`_call` returns `bridge_resp.result or {}`, meaning "the bridge answered
success WITHOUT A BODY" and "the bridge answered success with an empty body"
arrive at parsing as IDENTICAL. As long as a model has even one REQUIRED
field, it refuses on that field by name. `FamilyPassport` had not one required
field — all of them carried defaults — and `model_validate({})` produced a
full-fledged passport of an empty family with `partial_failures == []`: "the
inspection passed, there were no failures, there is nothing inside." Three
DIFFERENT facts ("no result arrived," "fields were lost to protocol drift,"
"the family really is empty") were ONE record.

🔴 THE RULE IS DERIVED FROM THE FILE'S OWN CONVENTION, NOT INVENTED:
`ExecuteResult`, `ContextResult`, and `PingResult` had always behaved this
way — three models out of four. Here this becomes a PROPERTY, checked for
every new model, rather than a coincidence that the fourth model silently
broke.

🔴 THE LIST OF MODELS IS TAKEN FROM THE CLIENT, NOT REWRITTEN HERE. Two
tables that are required to match diverge silently: if a separate list were
kept here, it would diverge from `BridgeClient` on the very first new model —
exactly the way everything this audit fixes has diverged.
"""
from __future__ import annotations

import asyncio
import inspect
import typing
import unittest

from pydantic import BaseModel, ValidationError

from kir.bridge import client as bridge_client
from kir.bridge import models as bridge_models


def _result_models() -> dict[str, type[BaseModel]]:
    """Models that `BridgeClient` returns outward — by ANNOTATIONS."""
    found: dict[str, type[BaseModel]] = {}
    for name, member in inspect.getmembers(bridge_client.BridgeClient):
        if not inspect.isfunction(member):
            continue
        try:
            hints = typing.get_type_hints(member, vars(bridge_models))
        except Exception:            # noqa: BLE001 — someone else's annotation is not our subject
            continue
        ret = hints.get("return")
        if isinstance(ret, type) and issubclass(ret, BaseModel):
            found[ret.__name__] = ret
    return found


class ОтветМостаОбязанБытьОтличимОтПустоты(unittest.TestCase):

    def test_the_client_returns_at_least_the_four_known_models(self) -> None:
        """If selection by annotations breaks, all the checks below become
        green BY CONSTRUCTION — on an empty set. We catch this here."""
        got = set(_result_models())
        self.assertLessEqual(
            {"PingResult", "ContextResult", "FamilyPassport", "ExecuteResult"},
            got,
            f"отбор моделей по аннотациям выродился, найдено: {sorted(got)}")

    def test_every_result_model_has_a_required_field(self) -> None:
        """A model without a single required field CANNOT refuse emptiness,
        and therefore must treat it as a fact. This is not a style choice but
        the reachability of refusal."""
        for name, model in sorted(_result_models().items()):
            with self.subTest(model=name):
                required = [
                    field for field, info in model.model_fields.items()
                    if info.is_required()
                ]
                self.assertTrue(
                    required,
                    f"{name}: ни одного обязательного поля — пустой ответ "
                    f"моста станет полноценным фактом о здании (F-349)")

    def test_every_result_model_refuses_an_empty_body(self) -> None:
        for name, model in sorted(_result_models().items()):
            with self.subTest(model=name):
                with self.assertRaises(ValidationError):
                    model.model_validate({})


class КонвертОбязанБытьОтветомНаЭТОТЗапрос(unittest.TestCase):
    """🔴 `req.id` WAS NEVER CHECKED AFTER SENDING, NOT ONCE (F-350, 30.08.2026).

    `BridgeResponse` declared `jsonrpc` as a free-form string, and
    `result`/`error` were independently optional; `_call` never once compared
    `bridge_resp.id` to `req.id`. That meant a response to SOMEONE ELSE'S
    request was accepted as one's own, a non-JSON-RPC envelope passed
    through, an envelope WITHOUT a body was treated as success and turned
    into `{}`, and an envelope carrying BOTH `result` AND `error` at once was
    accepted — with `is_error` winning, and the result vanishing without a
    trace.

    The protocol is declared JSON-RPC 2.0, where checking `id` is part of the
    PROTOCOL, not a precaution.
    """

    @staticmethod
    def _клиент(body):
        class _Resp:
            def raise_for_status(self): pass
            def json(self): return body

        клиент = bridge_client.BridgeClient.__new__(
            bridge_client.BridgeClient)
        клиент._timeout = 5.0
        клиент._execute_timeout = 5.0
        клиент._connected = True
        клиент._last_ping = None
        клиент._base_url = "http://x"

        async def _get_client():
            class _C:
                async def post(self, *a, **k): return _Resp()
            return _C()

        клиент._get_client = _get_client
        return клиент

    def _вызов(self, body):
        import uuid
        настоящий = uuid.uuid4
        uuid.uuid4 = lambda: "ФИКС"
        try:
            return asyncio.run(bridge_client.BridgeClient._call(
                self._клиент(body), "ping"))
        finally:
            uuid.uuid4 = настоящий

    def test_a_response_to_another_request_is_refused(self):
        with self.assertRaises(bridge_models.BridgeError) as поймано:
            self._вызов({"jsonrpc": "2.0", "id": "ЧУЖОЙ", "result": {"a": 1}})
        self.assertEqual(поймано.exception.code, -32012)

    def test_success_without_a_body_is_refused_by_name(self):
        """"Success without a body" does not answer the question asked.
        Before, it turned into `{}` and fell through as an unclear
        ValidationError at every method."""
        with self.assertRaises(bridge_models.BridgeError) as поймано:
            self._вызов({"jsonrpc": "2.0", "id": "ФИКС"})
        self.assertEqual(поймано.exception.code, -32011)

    def test_result_and_error_together_are_refused(self):
        """Silently picking one would mean deciding on the bridge's behalf.
        Before, `error` used to win, and the result vanished without a
        trace."""
        with self.assertRaises(bridge_models.BridgeError) as поймано:
            self._вызов({"jsonrpc": "2.0", "id": "ФИКС", "result": {"a": 1},
                         "error": {"code": -1, "message": "м"}})
        self.assertEqual(поймано.exception.code, -32014)

    def test_a_matching_envelope_still_passes(self):
        """🔴 THE NARROWNESS CONTROL, and it matters more than the others:
        the three refusals above must not turn the client into one that
        accepts nothing."""
        self.assertEqual(
            self._вызов({"jsonrpc": "2.0", "id": "ФИКС", "result": {"a": 1}}),
            {"a": 1})

    def test_a_non_jsonrpc_envelope_is_refused_by_the_model(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            bridge_models.BridgeResponse.model_validate(
                {"jsonrpc": "мусор", "id": "x", "result": {}})

    def test_no_method_legitimately_accepts_an_empty_body(self):
        """🔴 THE GROUND FOR THE RIGHT TO REFUSE, not an argument in words:
        the "success without a body" refusal cannot trigger on legitimate
        input precisely because no response model accepts an empty body. If a
        model without required fields appears tomorrow, it will turn red
        HERE, not at the user's end."""
        for имя, модель in sorted(_result_models().items()):
            with self.subTest(model=имя):
                self.assertTrue(
                    [f for f, i in модель.model_fields.items() if i.is_required()])


class ЧастичныйПаспортОстаётсяЗаконным(unittest.TestCase):
    """NARROWNESS CONTROL. The `FamilyPassport` docstring's argument about
    independent try/catch on the C# side is CORRECT — it is about a PART.
    The F-349 fix must not override it: otherwise, instead of a false fact we
    get a false refusal."""

    def test_a_passport_with_only_failures_is_accepted(self) -> None:
        p = bridge_models.FamilyPassport.model_validate(
            {"inspected": True, "partial_failures": ["solids: API threw"]})
        self.assertEqual(p.partial_failures, ["solids: API threw"])
        self.assertEqual(p.parameters, [])

    def test_a_genuinely_empty_but_inspected_family_is_accepted(self) -> None:
        """"Inspected, empty inside" is a legitimate fact, and it must
        remain expressible. It differs from an empty response by EXACTLY the
        mark of inspection."""
        p = bridge_models.FamilyPassport.model_validate({"inspected": True})
        self.assertTrue(p.inspected)
        self.assertEqual(p.partial_failures, [])


if __name__ == "__main__":
    unittest.main()
