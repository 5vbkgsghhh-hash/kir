"""Bytes-only AP03 authoring harness and deterministic conformance client.

The scripted client demonstrates the harness, not AI capability.  The only
project path used by the loop is the public offline AP02-W host constructor,
``handle_wire_request(bytes)``, and ``state_digest``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from kukai.ai_protocol.project_v0.wire_v0 import OfflineProjectWireV0
from kukai.design_source import FrozenMap, canonical_bytes, strict_json_loads

from .case_tower54 import (
    initial_prompt,
    initial_source,
    scripted_run_header,
    tower54_case,
)
from .contracts import (
    BenchmarkContractError,
    ModelOutputV0,
    PromptEventV0,
    TranscriptV0,
    WireExchangeV0,
)
from .schemas import (
    FINAL_BUILD_DIGEST,
    FINAL_SOURCE_DIGEST,
    MAX_CUMULATIVE_REQUEST_BYTES,
    MAX_MODEL_ATTEMPTS,
    MAX_MODEL_VISIBLE_RESPONSE_BYTES,
    MAX_UNIQUE_BUILD_ENTITIES,
    MODEL_OUTPUT_SCHEMA,
    PROTOCOL_VERSION,
)


class BenchmarkRunError(RuntimeError):
    """The harness could not produce a completed conformance transcript."""


class BytesOnlyModelV0(Protocol):
    """One provider invocation produces one raw JSON tool request wrapper."""

    def invoke(self, prompt_text: str) -> str: ...


def _wire_request(request_id: str, tool: str, arguments: Any) -> bytes:
    return canonical_bytes({
        "arguments": arguments,
        "protocol": PROTOCOL_VERSION,
        "request_id": request_id,
        "tool": tool,
    })


def _read_arguments(
    project_id: str,
    revision_digest: str,
    scope: str,
    target_id: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "project_id": project_id,
        "revision_digest": revision_digest,
        "schema": "kir-ai-project-read-command/0",
        "scope": scope,
    }
    if scope == "module":
        result["module_id"] = target_id
    elif scope == "exception":
        result["exception_id"] = target_id
    return result


def _receipt_ref(response: FrozenMap) -> dict[str, Any]:
    receipt = response["read_receipt"]
    if type(receipt) is not FrozenMap or receipt["authority"] != "OWNER":
        raise BenchmarkRunError("script requires an exact OWNER receipt")
    return {
        "receipt_digest": receipt["receipt_digest"],
        "receipt_id": receipt["receipt_id"],
        "schema": "kir-ai-project-read-receipt-ref/0",
    }


def _prompt_for_visible(exchanges: tuple[WireExchangeV0, ...]) -> str:
    return canonical_bytes({
        "instruction": "Continue with one complete kir_wire request.",
        "visible_responses": tuple({
            "exchange_seq": exchange.seq,
            "response_json": exchange.response_blob.decode("utf-8"),
        } for exchange in exchanges),
    }).decode("utf-8")


class ScriptedTower54ModelV0:
    """Deterministic bytes-only client used solely for harness conformance."""

    __slots__ = ("_invocation", "_responses", "_bootstrap")

    def __init__(self) -> None:
        self._invocation = 0
        self._responses: dict[str, FrozenMap] = {}
        self._bootstrap: FrozenMap | None = None

    @staticmethod
    def _decode_response_json(text: Any) -> FrozenMap:
        if type(text) is not str:
            raise BenchmarkRunError("visible response must be exact JSON text")
        value = strict_json_loads(text.encode("utf-8"))
        if type(value) is not FrozenMap:
            raise BenchmarkRunError("visible response must be an object")
        return value

    def _observe_prompt(self, prompt_text: str) -> None:
        prompt = strict_json_loads(prompt_text.encode("utf-8"))
        if type(prompt) is not FrozenMap:
            raise BenchmarkRunError("prompt must be an exact object")
        if self._invocation == 1:
            if set(prompt) != {"bootstrap", "instructions", "task"}:
                raise BenchmarkRunError("initial bootstrap prompt is not exact")
            self._bootstrap = prompt["bootstrap"]
            return
        if set(prompt) != {"instruction", "visible_responses"}:
            raise BenchmarkRunError("continuation prompt is not exact")
        visible = prompt["visible_responses"]
        if type(visible) is not tuple:
            raise BenchmarkRunError("visible responses must be an array")
        for item in visible:
            if type(item) is not FrozenMap or set(item) != {
                "exchange_seq", "response_json",
            }:
                raise BenchmarkRunError("visible response entry is not exact")
            response = self._decode_response_json(item["response_json"])
            self._responses[response["request_id"]] = response

    def _meta(self, response_id: str) -> tuple[str, str]:
        response = self._responses[response_id]
        result = response["result"]
        return result["project_id"], result["revision_digest"]

    def _read(
        self,
        request_id: str,
        scope: str,
        *,
        revision_from: str,
        target_id: str | None = None,
    ) -> bytes:
        project_id, revision_digest = self._meta(revision_from)
        return _wire_request(
            request_id,
            "project.read",
            _read_arguments(project_id, revision_digest, scope, target_id),
        )

    def _owner_refs(self, request_ids: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
        refs = tuple(_receipt_ref(self._responses[item]) for item in request_ids)
        return tuple(sorted(refs, key=lambda item: item["receipt_id"]))

    def _root_and_exception_patch(
        self,
        *,
        request_id: str,
        patch_id: str,
        root_read_id: str,
        exception_read_id: str,
        module_read_ids: tuple[str, str],
        width: str,
        depth: str,
        height: str,
        levels: int,
        exception_width: str,
    ) -> bytes:
        root_response = self._responses[root_read_id]
        exception_response = self._responses[exception_read_id]
        root = dict(root_response["result"]["value"].items())
        arguments = dict(root["arguments"].items())
        arguments.update({
            "floor_depth": depth,
            "floor_height": height,
            "floor_width": width,
            "level_keys": tuple(f"L{index:03d}" for index in range(1, levels + 1)),
        })
        root["arguments"] = arguments
        exception = dict(exception_response["result"]["value"].items())
        exception["expected_value"] = width
        exception["value"] = exception_width
        project_id = root_response["result"]["project_id"]
        base_revision = root_response["result"]["revision_digest"]
        refs = self._owner_refs((
            root_read_id, exception_read_id, *module_read_ids,
        ))
        return _wire_request(request_id, "source.patch", {
            "base_revision_digest": base_revision,
            "operations": (
                {
                    "op_id": f"{patch_id}.root",
                    "root": root,
                    "schema": "kir-ai-root-put/0",
                },
                {
                    "exception": exception,
                    "op_id": f"{patch_id}.exception",
                    "schema": "kir-ai-exception-put/0",
                },
            ),
            "patch_id": patch_id,
            "project_id": project_id,
            "receipt_refs": refs,
            "schema": "kir-ai-source-patch-command/0",
        })

    def _exception_patch(
        self,
        *,
        request_id: str,
        patch_id: str,
        root_read_id: str,
        exception_read_id: str,
        module_read_ids: tuple[str, str],
        exception_width: str,
    ) -> bytes:
        root_response = self._responses[root_read_id]
        exception = dict(
            self._responses[exception_read_id]["result"]["value"].items())
        exception["expected_value"] = "32000"
        exception["value"] = exception_width
        return _wire_request(request_id, "source.patch", {
            "base_revision_digest": root_response["result"]["revision_digest"],
            "operations": ({
                "exception": exception,
                "op_id": f"{patch_id}.exception",
                "schema": "kir-ai-exception-put/0",
            },),
            "patch_id": patch_id,
            "project_id": root_response["result"]["project_id"],
            "receipt_refs": self._owner_refs((
                root_read_id, exception_read_id, *module_read_ids,
            )),
            "schema": "kir-ai-source-patch-command/0",
        })

    def _next_request(self) -> bytes:
        index = self._invocation
        if index == 1:
            return _wire_request("cap_1", "capabilities.get", {})
        if index == 2:
            assert self._bootstrap is not None
            return _wire_request("read_manifest_a", "project.read", _read_arguments(
                self._bootstrap["project_id"],
                self._bootstrap["revision_digest"], "manifest"))
        if index == 3:
            return self._read("read_exc_index_a", "exception.index", revision_from="read_manifest_a")
        if index == 4:
            return self._read("read_root_a", "root_instance", revision_from="read_manifest_a")
        if index == 5:
            root = self._responses["read_root_a"]["result"]["value"]
            return self._read("read_mod_building_a", "module", revision_from="read_manifest_a", target_id=root["module_id"])
        if index == 6:
            root = self._responses["read_root_a"]["result"]["value"]
            return self._read("read_mod_floor_a", "module", revision_from="read_manifest_a", target_id=root["arguments"]["floor_module"])
        if index == 7:
            entry = self._responses["read_exc_index_a"]["result"]["value"][0]
            return self._read("read_exc_a", "exception", revision_from="read_manifest_a", target_id=entry["exception_id"])
        if index == 8:
            return self._root_and_exception_patch(
                request_id="patch_phase_a", patch_id="phase_a",
                root_read_id="read_root_a", exception_read_id="read_exc_a",
                module_read_ids=("read_mod_building_a", "read_mod_floor_a"),
                width="32000", depth="26000", height="3000", levels=60,
                exception_width="36000")
        if index == 9:
            return self._read("read_root_b", "root_instance", revision_from="patch_phase_a")
        if index == 10:
            return self._read("read_mod_building_b", "module", revision_from="patch_phase_a", target_id="mod_building")
        if index == 11:
            return self._read("read_mod_floor_b", "module", revision_from="patch_phase_a", target_id="mod_typical_floor")
        if index == 12:
            return self._read("read_exc_b", "exception", revision_from="patch_phase_a", target_id="exc_L027")
        if index == 13:
            return self._exception_patch(
                request_id="patch_phase_b_stale", patch_id="phase_b_stale",
                root_read_id="read_root_b", exception_read_id="read_exc_b",
                module_read_ids=("read_mod_building_b", "read_mod_floor_b"),
                exception_width="35000")
        if index == 14:
            environment = self._responses["env_patch_height_3100"]
            if self._responses["patch_phase_b_stale"]["status"] != "CONFLICT":
                raise BenchmarkRunError("script expected an explicit stale conflict")
            return self._read("read_root_recovery", "root_instance", revision_from="env_patch_height_3100")
        if index == 15:
            return self._read("read_mod_building_recovery", "module", revision_from="env_patch_height_3100", target_id="mod_building")
        if index == 16:
            return self._read("read_mod_floor_recovery", "module", revision_from="env_patch_height_3100", target_id="mod_typical_floor")
        if index == 17:
            return self._read("read_exc_recovery", "exception", revision_from="env_patch_height_3100", target_id="exc_L027")
        if index == 18:
            return self._root_and_exception_patch(
                request_id="patch_phase_b_recovery", patch_id="phase_b_recovery",
                root_read_id="read_root_recovery",
                exception_read_id="read_exc_recovery",
                module_read_ids=(
                    "read_mod_building_recovery", "read_mod_floor_recovery"),
                width="32000", depth="26000", height="3000", levels=60,
                exception_width="35000")
        raise BenchmarkRunError("script exhausted the pre-registered plan")

    def invoke(self, prompt_text: str) -> str:
        self._invocation += 1
        self._observe_prompt(prompt_text)
        request_json = self._next_request().decode("utf-8")
        return canonical_bytes({
            "request_json": request_json,
            "schema": MODEL_OUTPUT_SCHEMA,
        }).decode("utf-8")


@dataclass(slots=True)
class _Recorder:
    host: OfflineProjectWireV0
    exchanges: list[WireExchangeV0]

    def call(
        self,
        request: bytes,
        *,
        actor: str,
        model_visible: bool,
        provider_invocation: int | None,
    ) -> WireExchangeV0:
        before = self.host.state_digest
        response = self.host.handle_wire_request(request)
        after = self.host.state_digest
        previous = self.exchanges[-1].exchange_digest if self.exchanges else None
        exchange = WireExchangeV0.create(
            seq=len(self.exchanges) + 1,
            actor=actor,
            model_visible=model_visible,
            provider_invocation=provider_invocation,
            request=request,
            response=response,
            before_state_digest=before,
            after_state_digest=after,
            previous_exchange_digest=previous,
        )
        self.exchanges.append(exchange)
        return exchange


def _environment_injection(
    recorder: _Recorder,
    *,
    project_id: str,
    revision_digest: str,
) -> tuple[WireExchangeV0, WireExchangeV0]:
    read = recorder.call(
        _wire_request(
            "env_read_root_3100",
            "project.read",
            _read_arguments(project_id, revision_digest, "root_instance"),
        ),
        actor="ENVIRONMENT",
        model_visible=False,
        provider_invocation=None,
    )
    read_response = strict_json_loads(read.response_blob)
    root = dict(read_response["result"]["value"].items())
    arguments = dict(root["arguments"].items())
    arguments["floor_height"] = "3100"
    root["arguments"] = arguments
    patch = recorder.call(
        _wire_request("env_patch_height_3100", "source.patch", {
            "base_revision_digest": revision_digest,
            "operations": ({
                "op_id": "env_height_3100.root",
                "root": root,
                "schema": "kir-ai-root-put/0",
            },),
            "patch_id": "env_height_3100",
            "project_id": project_id,
            "receipt_refs": (_receipt_ref(read_response),),
            "schema": "kir-ai-source-patch-command/0",
        }),
        actor="ENVIRONMENT",
        model_visible=True,
        provider_invocation=None,
    )
    return read, patch


def _build_entity_ids(blob: bytes) -> set[str]:
    """Census exact entity records recursively in one model-visible response."""

    try:
        root = strict_json_loads(blob)
    except Exception as exc:
        raise BenchmarkRunError("host emitted non-strict response JSON") from exc
    found: set[str] = set()
    stack = [root]
    while stack:
        value = stack.pop()
        if type(value) is FrozenMap:
            if value.get("schema") == "kir-build-entity/0":
                logical_id = value.get("logical_id")
                if type(logical_id) is str:
                    found.add(logical_id)
            stack.extend(value.values())
        elif type(value) is tuple:
            stack.extend(value)
    return found


def _budget_state(exchanges: list[WireExchangeV0]) -> tuple[int, int, int, int]:
    model = [item for item in exchanges if item.actor == "MODEL"]
    attempts = len(model)
    request_bytes = sum(item.request_bytes for item in model)
    visible = [item for item in exchanges if item.model_visible]
    response_bytes = sum(item.response_bytes for item in visible)
    entities: set[str] = set()
    for item in visible:
        entities.update(_build_entity_ids(item.response_blob))
    return attempts, request_bytes, response_bytes, len(entities)


def _budget_terminal(exchanges: list[WireExchangeV0]) -> str | None:
    attempts, request_bytes, response_bytes, entities = _budget_state(exchanges)
    if entities > MAX_UNIQUE_BUILD_ENTITIES:
        return "DISQUALIFIED_CONTEXT_BYPASS"
    if (
        attempts > MAX_MODEL_ATTEMPTS
        or request_bytes > MAX_CUMULATIVE_REQUEST_BYTES
        or response_bytes > MAX_MODEL_VISIBLE_RESPONSE_BYTES
    ):
        return "FAILED"
    return None


def run_scripted_conformance() -> TranscriptV0:
    """Produce the deterministic AP03 conformance transcript.

    This function intentionally does not inspect ``host.state``.  The fresh
    replay verifier is the only component that invokes the hidden oracle.
    """

    source = initial_source()
    host = OfflineProjectWireV0.from_source(source)
    recorder = _Recorder(host, [])
    model = ScriptedTower54ModelV0()
    case = tower54_case()
    header = scripted_run_header()
    prompts: list[PromptEventV0] = []
    outputs: list[ModelOutputV0] = []
    pending_visible: list[WireExchangeV0] = []
    terminal = "FAILED"

    for invocation in range(1, MAX_MODEL_ATTEMPTS + 1):
        if invocation == 1:
            prompt_text = initial_prompt()
            visible_seqs: tuple[int, ...] = ()
        else:
            prompt_text = _prompt_for_visible(tuple(pending_visible))
            visible_seqs = tuple(item.seq for item in pending_visible)
        prompts.append(PromptEventV0(invocation, prompt_text, visible_seqs))
        pending_visible.clear()

        raw = model.invoke(prompt_text)
        output = ModelOutputV0.admit_raw(invocation, raw)
        outputs.append(output)
        request = output.request_json.encode("utf-8")

        if invocation == 13:
            phase_a_response = strict_json_loads(
                recorder.exchanges[-1].response_blob)
            project_id = phase_a_response["result"]["project_id"]
            revision_digest = phase_a_response["result"]["revision_digest"]
            _hidden, visible_environment = _environment_injection(
                recorder,
                project_id=project_id,
                revision_digest=revision_digest,
            )
            pending_visible.append(visible_environment)

        exchange = recorder.call(
            request,
            actor="MODEL",
            model_visible=True,
            provider_invocation=invocation,
        )
        pending_visible.append(exchange)

        budget_terminal = _budget_terminal(recorder.exchanges)
        if budget_terminal is not None:
            terminal = budget_terminal
            break
        response = strict_json_loads(exchange.response_blob)
        if invocation == 18:
            result = response.get("result")
            if (
                response.get("status") == "OK"
                and type(result) is FrozenMap
                and result.get("source_digest") == FINAL_SOURCE_DIGEST
                and result.get("build_digest") == FINAL_BUILD_DIGEST
            ):
                terminal = "COMPLETED"
            break

    return TranscriptV0(case, header, prompts, outputs, recorder.exchanges, terminal)


__all__ = [
    "BenchmarkRunError", "BytesOnlyModelV0", "ScriptedTower54ModelV0",
    "run_scripted_conformance",
]
