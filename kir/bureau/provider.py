# -*- coding: utf-8 -*-
"""The provider port and the cassette stand-in. Not a single byte from the store enters here."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

#: The project store is recognized BY ITS CONTENTS, not by name: a SQLite
#: file's header is fixed by the format. A name only catches those who
#: follow it — and in this tree the store even appears with no extension at
#: all (`…/store`).
_SQLITE_MAGIC = b"SQLite format 3\x00"
_STORE_SUFFIXES = (".sqlite", ".sqlite3", ".db")
#: How many neighbors to inspect. The cassette lives in a small directory;
#: an unbounded walk would turn the constructor into a tree traversal.
_NEIGHBOUR_LIMIT = 256

__all__ = ["CompletionRequest", "CompletionResponse", "ProviderRefusal",
           "RealProviderUnavailable", "TapeProvider", "real_provider", "request_key"]

#: How many calls one answer carries. The unit is not decoration: it makes
#: `usage` additive, and "how many times we asked" is counted the same way
#: as "how much was spent."
_ONE_CALL = 1
USAGE_BASES = frozenset({'provider_reported_tokens', 'estimated_response_units'})


def _checked_usage_basis(value):
    if type(value) is not str or value not in USAGE_BASES:
        raise ProviderRefusal('bad_usage', 'unknown usage basis')
    return value


class ProviderRefusal(RuntimeError):
    """The provider refused. The refusal has a code, and it is not turned into empty text."""

    def __init__(self, code: str, message: str, *, response=None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.response = response


class RealProviderUnavailable(ProviderRefusal):
    """There is no real provider — and this is NAMED, not silently worked around by a stand-in.

    🔴 THIS REFUSAL IS THE HONEST BOUNDARY OF THIS SHIFT. The mechanism can
    be tested with a cassette; autonomy cannot: replaying recorded answers
    looks like the model's work right up to the first new assignment. Until
    there is access and an agreed spending limit, the only truthful answer
    to "give me a real provider" is this refusal.
    """

    def __init__(self, detail: str = "no real LLM provider is configured in this tree"):
        super().__init__("real_provider_unavailable", detail)


@dataclass(frozen=True)
class CompletionRequest:
    """What goes out to the model. No revisions, no paths, no store — only text."""

    messages: tuple
    max_tokens: int = 2048
    tags: tuple = ()

    def __post_init__(self):
        # 🔴 THE REQUEST IS CHECKED BY TYPES, NOT BY SHAPE. Review A3-2 put
        # a LIVE `ProjectStore` into `tags` and into `content`: the previous
        # check only looked at the set of keys, the object made it all the
        # way to `request_key` and broke there with an unnamed `TypeError`.
        # A different port implementation would have received the whole
        # store — meaning "the provider can't see the project" would have
        # rested on nobody having tried. Here the request is text, and
        # nothing else.
        if not self.messages:
            raise ProviderRefusal("empty_request", "a completion needs at least one message")
        for message in self.messages:
            if not isinstance(message, Mapping) or set(message) != {"role", "content"}:
                raise ProviderRefusal("bad_message", "each message is {role, content}")
            for name in ("role", "content"):
                if not isinstance(message[name], str) or isinstance(message[name], bool):
                    raise ProviderRefusal(
                        "bad_message",
                        f"message.{name}: ожидается текст, получено "
                        f"{type(message[name]).__name__} — запрос несёт СЛОВА, "
                        f"а не объекты процесса")
        if not isinstance(self.tags, (tuple, list)):
            raise ProviderRefusal("bad_tags", "tags is a sequence of strings")
        for tag in self.tags:
            if not isinstance(tag, str) or isinstance(tag, bool):
                raise ProviderRefusal("bad_tags",
                                      f"tag: ожидается текст, получено {type(tag).__name__}")
        # `bool` is a subclass of `int`, and `int(True) == 1`: `max_tokens=True`
        # produced the SAME cassette key as `max_tokens=1` (the only
        # collision found among ten pairs, review A3-9). A refusal is
        # cheaper than a collision.
        if isinstance(self.max_tokens, bool) or not isinstance(self.max_tokens, int) \
                or self.max_tokens <= 0:
            raise ProviderRefusal("bad_budget", "max_tokens must be a positive integer")

    def to_dict(self) -> dict:
        return {"messages": [dict(message) for message in self.messages],
                "max_tokens": int(self.max_tokens), "tags": list(self.tags)}


@dataclass(frozen=True)
class CompletionResponse:
    text: str
    usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0,
                                                 "calls": _ONE_CALL})
    provider_id: str = "unknown"
    usage_basis: str = "provider_reported_tokens"

    def __post_init__(self):
        if not isinstance(self.text, str):
            raise ProviderRefusal("bad_text", "a completion is text")
        if type(self.provider_id) is not str or not self.provider_id.strip():
            raise ProviderRefusal('bad_usage', 'reporting provider must be named')
        if type(self.usage) is not dict:
            raise ProviderRefusal("bad_usage", "usage must be an object")
        for name in ("input_tokens", "output_tokens", "calls"):
            if type(self.usage.get(name)) is not int or self.usage[name] < 0:
                raise ProviderRefusal("bad_usage", f"usage.{name} must be a non-negative integer")
        if self.usage['calls'] != 1:
            raise ProviderRefusal('bad_usage', 'one completion must report one call')
        _checked_usage_basis(self.usage_basis)

    @property
    def tokens(self) -> int:
        return int(self.usage["input_tokens"]) + int(self.usage["output_tokens"])

    def to_dict(self) -> dict:
        return {"text": self.text, "usage": dict(self.usage), "provider_id": self.provider_id,
                "usage_basis": self.usage_basis}


def request_key(request) -> str:
    """The cassette key is the sha256 of the CANONICAL request.

    There is one canon for both sides: the same key order and the same
    `ensure_ascii` as the acceptance instrument uses. Should they diverge,
    the cassette would "fail to find" its own answer, and the stand-in
    would start silently making things up.
    """
    payload = request.to_dict() if isinstance(request, CompletionRequest) else dict(request)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _is_store_file(path: Path) -> bool:
    if path.suffix.lower() in _STORE_SUFFIXES:
        return True
    try:
        with open(path, "rb") as handle:
            return handle.read(len(_SQLITE_MAGIC)) == _SQLITE_MAGIC
    except OSError:
        return False


def _refuse_cassette_beside_store(path: Path) -> None:
    """A cassette has no place inside the project's store directory — and this is a RULE, not a taste.

    🔴 WHY THIS IS NOT PEDANTRY. A cassette is a trace of SOMEONE ELSE'S
    answers, the journal is a trace of OUR OWN decisions; sitting in the
    same directory, they lose separate provenance, and with it the ability
    to say that a program was derived from the model's answer rather than
    peeked from the project. Review A3-2 measured that a cassette path
    inside the store directory was accepted silently.
    """
    if _is_store_file(path):
        raise ProviderRefusal("cassette_inside_store",
                              f"{path}: это хранилище проекта, а не кассета")
    try:
        entries = []
        for index, item in enumerate(path.parent.iterdir()):
            if index >= _NEIGHBOUR_LIMIT:
                break
            if item.is_file() and item != path and _is_store_file(item):
                entries.append(item)
                break
    except OSError:
        return
    if entries:
        raise ProviderRefusal(
            "cassette_inside_store",
            f"{path}: в каталоге лежит хранилище проекта ({entries[0].name}); кассета — "
            f"след ответов модели и обязана жить отдельно от журнала проекта")


class TapeProvider:
    """A cassette stand-in: `replay` answers with what was recorded, `record` records.

    🔴 WHAT IS TRUE HERE, AND WHAT WAS STATED MORE STRONGLY THAN MEASURED.
    True: `TapeProvider` does NOT ACCEPT the store as a parameter — neither
    `store`, nor `ProjectStore`, nor revisions; there is no such slot in the
    `__init__` signature. The previous edit called this "no access by
    construction," and review A3-2 showed by execution that the claim was
    wider than the measurement: the store made it in inside the
    `CompletionRequest` (in `tags` and in `content`), and the `record` mode's
    generator is CALLER CODE, and it is entitled to read whatever it likes
    through its own closure. The first is closed off by the request's types;
    the second cannot be closed off and there is no reason to hide it:
    **the `record` mode's generator is the caller's responsibility**, and a
    cassette it records is honest exactly to the degree that the caller is.

    `record` requires an explicit generator: the stand-in does not invent
    the answer itself. A cassette recorded this way remains the trace of
    SOMEONE ELSE'S decision, not our own.
    """

    def __init__(self, path, mode: str = "replay", *, generator=None,
                 provider_id: str = "tape/deterministic"):
        if mode not in ("replay", "record"):
            raise ProviderRefusal("bad_mode", f"{mode!r}: expected 'replay' or 'record'")
        if mode == "record" and generator is None:
            raise ProviderRefusal("record_needs_generator",
                                  "recording requires an explicit answer generator")
        self.path = Path(path)
        _refuse_cassette_beside_store(self.path)
        self.mode = mode
        self.provider_id = provider_id
        self._generator = generator
        self.calls = 0
        self.misses = 0
        self._tape = {}
        #: Exactly what I MYSELF wrote. On merge, disk outranks memory —
        #: otherwise my stale snapshot would resurrect someone else's
        #: deleted records.
        self._recorded = {}
        if self.path.exists():
            self._tape = json.loads(self.path.read_text(encoding="utf-8"))
        elif mode == "replay":
            raise ProviderRefusal("cassette_missing", f"{self.path}: no cassette to replay")

    # The store is not among the arguments of A SINGLE call — that is the proof.
    @property
    def recovery_binding(self):
        return {"channel": "tape", "path": str(self.path.resolve()), "provider_id": self.provider_id}

    def lookup(self, request):
        """A retained cassette row only, never the recording generator."""
        rows = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        row = rows.get(request_key(request))
        return (CompletionResponse(row['text'], dict(row['usage']), row.get('provider_id', self.provider_id),
                                   'estimated_response_units') if row is not None else None)

    def complete(self, request) -> CompletionResponse:
        key = request_key(request)
        row = self._tape.get(key)
        if row is None:
            if self.mode == "replay":
                self.misses += 1
                raise ProviderRefusal(
                    "cassette_miss",
                    f"{key[:16]}: this request is not on the cassette; replay refuses to invent")
            text = self._generator(request)
            if not isinstance(text, str) or not text.strip():
                raise ProviderRefusal("bad_generated_text", "generator returned no text")
            row = {"text": text,
                   "usage": {"input_tokens": len(json.dumps(
                       request.to_dict() if isinstance(request, CompletionRequest) else request,
                       ensure_ascii=False)) // 4,
                       "output_tokens": len(text) // 4, "calls": _ONE_CALL},
                   "provider_id": self.provider_id}
            self._tape[key] = row
            self._commit(key, row)
        self.calls += 1
        return CompletionResponse(text=row["text"], usage=dict(row["usage"]),
                                  provider_id=row.get("provider_id", self.provider_id), usage_basis='estimated_response_units')


    def _commit(self, key: str, row: dict) -> None:
        """Append a record WITHOUT losing someone else's.

        🔴 MEASURED, A3-8: two writers into one cassette — the first
        writer's record disappeared. The provider held the cassette in
        memory and on every write rewrote the WHOLE FILE, meaning the last
        writer won silently. Here the write is chained by a lock (`flock`)
        and done in a cycle of "re-read from disk -> merge -> replace
        atomically": one's own write only overwrites itself, someone else's
        remains.
        """
        lock_path = self.path.with_name(self.path.name + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                merged = {}
                if self.path.exists():
                    try:
                        merged = json.loads(self.path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError as broken:
                        raise ProviderRefusal(
                            "cassette_corrupt", f"{self.path}: {broken}") from broken
                self._recorded[key] = row
                merged.update(self._recorded)
                temporary = self.path.with_name(self.path.name + f".{os.getpid()}.part")
                temporary.write_text(json.dumps(merged, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
                os.replace(temporary, self.path)
                self._tape = merged
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def real_provider(*_args, **kwargs):
    """A real provider — file exchange with live agents, if one is named.

    🔴 THERE IS NO KEY AND THERE WILL BE NONE (the owner's word, 07.09.2026):
    the bureau's workers are Claude Code agents of this same session, and
    "realness" here means not a network but a LIVE responder. The exchange
    directory is named by the `KIR_BUREAU_EXCHANGE_DIR` variable; without
    it — the previous named refusal, and NO substitution by a cassette:
    silently answering with a recorded value would mean passing off a replay
    as the model's work.
    """
    # 🔴 THE DOOR, NOT `os.environ` (fix 07.09.2026): the package has one
    # door for reading the environment, `kir.env.get`, and it knows the old
    # variable name. The previous `import os` here was a SECOND place to
    # remember, and the guard `test_the_environment_has_one_door` named it
    # by name.
    from kir import env
    from kir.bureau.exchange import EXCHANGE_ENV, FileExchangeProvider

    directory = kwargs.pop("directory", None) or env.get(EXCHANGE_ENV)
    if not directory:
        raise RealProviderUnavailable(
            f"no real provider is configured: set {EXCHANGE_ENV} to the exchange directory "
            f"where live Claude Code agents answer request files")
    return FileExchangeProvider(directory, **kwargs)
