# -*- coding: utf-8 -*-
"""A real provider WITH NO KEY: file exchange with Claude Code agents.

🔴 WHY THIS IS NEITHER A STAND-IN NOR A CASSETTE. The owner's word,
07.09.2026: there will be no paid LLM, the bureau's workers will be Sonnet
agents of this same session. So the model exists, but not behind a network
key — behind a FILE: the request is placed on disk, a live agent reads it
and writes the answer. There is no key here, no network, no invented
answer — when there is no answer, a NAMED refusal arrives, not a record
from a cassette.

From this follows the main property of honesty: the response's
`provider_id` is `claude-code-agent`, and the bureau's honesty line counts
such calls as REAL. Substitution by a cassette is forbidden by
construction: this class of cassette does not read at all.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from kir.bureau.provider import (CompletionRequest, CompletionResponse, ProviderRefusal,
                                 request_key)

__all__ = ["FileExchangeProvider", "EXCHANGE_ENV", "PROVIDER_ID", "RESPONSE_SCHEMA"]

#: The exchange directory comes from the environment — the path to the
#: live agents is not hardcoded.
EXCHANGE_ENV = "KIR_BUREAU_EXCHANGE_DIR"
PROVIDER_ID = "claude-code-agent"
REQUEST_SCHEMA = "kir-bureau-exchange-request/1"
RESPONSE_SCHEMA = "kir-bureau-exchange-response/1"
#: The ceiling on the response SIZE in bytes. Tokens are not bytes: review
#: 6 measured an accepted `text` of 8 MiB at a ceiling of 2048 tokens. The
#: file is read whole, and the limit here is about process memory, not
#: about money.
MAX_RESPONSE_BYTES = 256 * 1024


def _write_atomically(path: Path, payload: dict) -> None:
    temporary = path.with_name(path.name + f".{os.getpid()}.part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
                         encoding="utf-8")
    os.replace(temporary, path)


class FileExchangeProvider:
    """`LlmProviderPort` via a directory: the request is a file, the answer is a file.

    `complete` places `requests/<request_id>.json`, waits for
    `responses/<request_id>.json`, and CHECKS the answer: schema, non-empty
    text, non-negative integers in `usage`, and above all —
    `output_tokens <= max_tokens` of the request. Exceeding the ceiling is a
    NAMED refusal, `budget_overrun`: a spending limit that is "mostly
    respected" is not a limit.

    `request_id` is the digest of the CANONICAL request (the same one the
    cassette uses). So a repeat of the same question does not create a
    second file: if the answer has already arrived, that is what is
    returned; if not yet, we wait for that same one.
    """

    provider_id = PROVIDER_ID

    def __init__(self, directory, *, timeout_s: float = 900.0, poll_s: float = 0.5):
        if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
            raise ProviderRefusal("bad_timeout", "timeout_s must be a positive number")
        if not isinstance(poll_s, (int, float)) or poll_s <= 0:
            raise ProviderRefusal("bad_poll", "poll_s must be a positive number")
        self.root = Path(directory)
        self.requests = self.root / "requests"
        self.responses = self.root / "responses"
        for path in (self.requests, self.responses):
            path.mkdir(parents=True, exist_ok=True)
        self.timeout_s, self.poll_s = float(timeout_s), float(poll_s)
        self.calls = 0

    # ── exchange ───────────────────────────────────────────────────────────
    @property
    def recovery_binding(self):
        return {"channel": "file_exchange", "directory": str(self.root.resolve())}

    def lookup(self, request):
        """Read an already supplied answer only; None grants no reinvocation.

        No request file, waiting loop, counter increment or external agent call.
        """
        key = request_key(request)
        path = self.responses / f"{key}.json"
        return self._read(path, key, request.max_tokens) if path.exists() else None

    def pending(self) -> tuple:
        """Requests with no answer yet. `status` prints this number."""
        return tuple(sorted(path.stem for path in self.requests.glob("*.json")
                            if not (self.responses / path.name).exists()))

    def complete(self, request) -> CompletionResponse:
        key = request_key(request)
        payload = request.to_dict() if isinstance(request, CompletionRequest) else dict(request)
        target = self.requests / f"{key}.json"
        answer = self.responses / f"{key}.json"
        if not answer.exists() and not target.exists():
            _write_atomically(target, {"schema": REQUEST_SCHEMA, "request_id": key,
                                       "sha256": key, "ts": time.time(), **payload})
        # 🔴 A HALF-WRITTEN ANSWER IS "STILL BEING WRITTEN," NOT "CORRUPT."
        # The answer is written by an EXTERNAL live agent, and we cannot
        # mandate the atomicity of its write. Review 6 measured: an ordinary
        # `open(...,'w')` with the second half arriving 1.5 s later produced
        # `provider_response_corrupt` at second 2.1 with a timeout of 6 —
        # that is, a refusal AHEAD OF SCHEDULE, and it cost the team a call
        # from the budget. So parsing on the waiting path does not raise: the
        # cause is remembered, polling continues, and
        # `provider_response_corrupt` is only voiced once time has run out
        # and the last parse attempt still failed.
        deadline = time.monotonic() + self.timeout_s
        last_failure = None
        while True:
            if answer.exists():
                try:
                    response = self._read(answer, key, int(payload.get("max_tokens") or 0))
                except ProviderRefusal as failure:
                    if failure.code != "provider_response_corrupt":
                        raise
                    last_failure = failure
                else:
                    self.calls += 1
                    return response
            if time.monotonic() >= deadline:
                if last_failure is not None:
                    raise ProviderRefusal(
                        "provider_response_corrupt",
                        f"{key[:16]}: за {self.timeout_s:.0f} с ответ так и не стал разбираемым; "
                        f"последняя причина — {last_failure}. Пишите ответ АТОМАРНО: "
                        f"во временный файл рядом и `os.replace` на место")
                raise ProviderRefusal(
                    "provider_timeout",
                    f"{key[:16]}: ответа нет за {self.timeout_s:.0f} с; запрос остался в "
                    f"{target} — тот же request_id подберёт ответ, когда он придёт")
            time.sleep(self.poll_s)

    # ── checking the answer ───────────────────────────────────────────────
    def _read(self, path: Path, key: str, ceiling: int) -> CompletionResponse:
        def corrupt(detail: str) -> ProviderRefusal:
            return ProviderRefusal("provider_response_corrupt", f"{path}: {detail}")

        try:
            size = path.stat().st_size
        except OSError as failure:
            raise corrupt(f"{type(failure).__name__}: {failure}") from failure
        if size > MAX_RESPONSE_BYTES:
            # Not `corrupt`: the file can be flawless JSON — it simply
            # doesn't fit within the declared limit, and reading it whole to
            # find that out is too late.
            raise ProviderRefusal(
                "response_too_large",
                f"{path}: {size} байт при потолке {MAX_RESPONSE_BYTES}; ответ модели — текст "
                f"программы, а не архив")
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as failure:
            raise corrupt(f"{type(failure).__name__}: {failure}") from failure
        if not isinstance(row, dict):
            raise corrupt(f"ответ обязан быть объектом, получено {type(row).__name__}")
        text = row.get("text")
        if not isinstance(text, str) or not text.strip():
            raise corrupt("`text` обязан быть непустым текстом")
        usage = row.get("usage")
        if not isinstance(usage, dict):
            raise corrupt("`usage` обязан быть объектом")
        numbers = {}
        for name in ("input_tokens", "output_tokens", "calls"):
            value = usage.get(name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise corrupt(f"usage.{name}: ожидается целое >= 0, получено {value!r}")
            numbers[name] = value
        if numbers["calls"] != 1:
            raise corrupt(f"usage.calls обязан быть 1 (один ответ — один вызов), "
                          f"получено {numbers['calls']}")
        # 🔴 THE CEILING IS CHECKED AT THE ANSWER, NOT MERELY DECLARED IN THE
        # REQUEST. The owner measured 07.09.2026: budget 2048, answer
        # 100 + 2048 — accepted.
        # 🔴 THE ANSWER MUST NAME WHAT IT IS ANSWERING AND WHO ANSWERED.
        # Review 6 measured: a file carrying someone else's `request_id`
        # inside was accepted, and an answer with no `provider_id` was
        # SILENTLY credited to the live agent — and that value rides into
        # the metadata of the accepted revision, meaning a falsehood about
        # who answered enters the project's history.
        stamped = row.get("request_id")
        if stamped is not None and str(stamped) != key:
            raise ProviderRefusal(
                "response_request_mismatch",
                f"{path}: ответ помечен запросом {str(stamped)[:16]}, а лежит под {key[:16]}")
        provider = row.get("provider_id")
        if not isinstance(provider, str) or not provider.strip():
            raise corrupt("`provider_id` обязателен: кто ответил — не догадка, а поле схемы")
        # 🔴 THIS IS A CHECK OF FORM, NOT OF AUTHENTICITY, AND THE TWO MUST
        # NOT BE CONFUSED. The acceptance instrument counts EXTERNAL calls
        # by this field, so a foreign string in it is not a typo but a wrong
        # count: review 6 (E2) measured an accepted answer with
        # `provider_id: "tape"`, and that value would have ridden into the
        # metadata of the accepted revision. What is required here is
        # EXACTLY the name of this exchange channel. This does NOT prove the
        # responder's authenticity: anyone with the right to write into the
        # directory can write this string too. Only the directory itself
        # (filesystem permissions) provides authenticity; inventing a
        # signature that the exchange does not have would mean declaring the
        # unproven proven.
        if provider.strip() != self.provider_id:
            raise ProviderRefusal(
                "provider_id_mismatch",
                f"{path}: ожидалось `{self.provider_id}`, пришло `{provider.strip()}`; "
                f"поле называет КАНАЛ обмена, и по нему считаются внешние вызовы")
        model = row.get("model")
        if model is not None and not isinstance(model, str):
            raise corrupt("`model` обязан быть текстом")
        note = row.get("agent_note")
        if note is not None and not isinstance(note, str):
            raise corrupt("`agent_note` обязан быть текстом")
        response = CompletionResponse(text=text, usage=dict(numbers), provider_id=provider.strip(),
                                      usage_basis="estimated_response_units")
        if ceiling and response.tokens > ceiling:
            raise ProviderRefusal("budget_overrun", "estimated response units exceed the requested budget",
                                  response=response)
        return response
