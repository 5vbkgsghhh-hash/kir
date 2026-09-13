# -*- coding: utf-8 -*-
"""The bureau CLI: `python -m kir.bureau assign|work|coordinate|stop|status <store>`.

Every output carries the line `настоящий LLM: 0 вызовов; подставной: N` —
not as decoration but as a condition of honesty: the stand-in tests the
MECHANISM and does not close the mission (the owner's word).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kir import env
from kir.bureau.provider import ProviderRefusal, TapeProvider, real_provider
from kir.bureau.runner import (BureauRefusal, TeamBudget, assign, coordinate, is_stopped,
                               spend, stop, work, resume)
from kir.bureau.exchange import EXCHANGE_ENV, FileExchangeProvider
from kir.project_store import ProjectStore

#: There are no real calls in this tree and there cannot be: there is no provider.
REAL_CALLS = 0


def _honesty(store=None, *, provider=None) -> str:
    """The honesty line is printed ALWAYS, including when there is nothing to count.

    🔴 REVIEW A3-6 MEASURED TWO ORDINARY PATHS WHERE IT WAS MISSING: `status
    <nonexistent-path>` and `work --task no-such-task` printed a trace and
    stayed silent about the main thing. This file's header calls the line "a
    condition of honesty, not decoration" — meaning it must survive both a
    refusal and a crash, otherwise the condition rests on luck.
    """
    if store is None:
        return f"настоящий LLM: {REAL_CALLS} вызовов; подставной: расход не прочитан"
    try:
        used = spend(store)
    except Exception as failure:  # noqa: BLE001 — the journal is unavailable: say exactly that
        return (f"настоящий LLM: {REAL_CALLS} вызовов; подставной: расход не прочитан "
                f"({type(failure).__name__})")
    return ("настоящий LLM: личность и полный расход не измеряются этим интерфейсом; "
            f"зарезервированных попыток: {used['calls']}; "
            f"reported={used['reported_tokens']}, estimated={used['estimated_tokens']}, "
            f"reserved={used['reserved_tokens']}, unknown={used['unknown_tokens']}; не деньги")


def _is_real(provider) -> bool:

    return isinstance(provider, FileExchangeProvider)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kir.bureau", description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("assign", "work", "coordinate", "stop", "resume", "status"):
        one = sub.add_parser(name)
        one.add_argument("store")
        if name == "assign":
            one.add_argument("--text", required=True)
            one.add_argument("--worker", required=True)
            one.add_argument("--instance", default="tower-a")
            one.add_argument("--output", action="append", dest="outputs")
            one.add_argument("--remove-field", action="append", default=[], metavar="OUTPUT:FIELD")
        if name == "resume":
            one.add_argument("--reason", required=True)
        if name in ("work", "coordinate"):
            one.add_argument("--cassette", default="")
            # 🔴 REAL MODE IS A SEPARATE FLAG, NOT A SUBSTITUTION BY A
            # CASSETTE. Without an exchange directory it REFUSES by name:
            # "substitute a cassette since there is no real one" — exactly
            # the lie this mode exists to prevent.
            one.add_argument("--real", action="store_true")
            one.add_argument("--exchange", default="")
            one.add_argument("--timeout-s", type=float, default=900.0)
            one.add_argument("--max-calls", type=int, default=8)
            one.add_argument("--max-tokens", type=int, default=40000)
        if name == "work":
            one.add_argument("--task", required=True)
    args = parser.parse_args(argv)
    try:
        store = ProjectStore.open(args.store, readonly=args.action == "status")
    except Exception as failure:  # noqa: BLE001 — no store: name it and don't crash
        print(json.dumps({"refusal": f"store_unavailable: {type(failure).__name__}: "
                                     f"{str(failure)[:200]}", "honesty": _honesty()},
                         ensure_ascii=False))
        return 2
    try:
        if args.action == "assign":
            removals = {}
            for value in args.remove_field:
                if value.count(':') != 1:
                    raise BureauRefusal('bad_field_removal', 'use OUTPUT:FIELD')
                key, name = value.split(':')
                removals.setdefault(key, []).append(name)
            task_id = assign(store, args.text, worker_id=args.worker,
                             base_revision=store.head().revision_id, instance_key=args.instance,
                             outputs=args.outputs, remove_fields=removals or None)
            payload = {"task_id": task_id}
        elif args.action == "stop":
            stop(store)
            payload = {"stopped": True}
        elif args.action == "resume":
            resume(store, reason=args.reason)
            payload = {"stopped": is_stopped(store)}
        elif args.action == "status":
            payload = {"stopped": is_stopped(store), "spend": spend(store),
                       "head": store.head().revision_id, "exchange": None,
                       "pending_requests": 0}
            # 🔴 THE DOOR, NOT `os.environ` (fix 07.09.2026): the package has
            # one door for reading the environment, `kir.env.get`, and it
            # knows the old variable name — the fix owner's live service
            # won't notice a thing.
            directory = env.get(EXCHANGE_ENV)
            if directory:
                waiting = FileExchangeProvider(directory).pending()
                payload.update(exchange=str(directory), pending_requests=len(waiting),
                               waiting=[key[:16] for key in waiting[:8]])
        else:
            if args.real:
                provider = real_provider(directory=args.exchange or None,
                                         timeout_s=args.timeout_s)
            elif args.cassette:
                provider = TapeProvider(Path(args.cassette), mode="replay")
            else:
                raise BureauRefusal("no_provider",
                                    "назови --cassette (подстава) или --real (живые агенты)")
            budget = TeamBudget(max_calls=args.max_calls, max_tokens=args.max_tokens)
            if args.action == "work":
                result = work(store, args.task, provider=provider, budget=budget)
                payload = result.to_dict()
                # Who answered is taken from the RESULT, not from the
                # command-line flag: the flag says whom we approached, the
                # result says who answered.
                payload["provider"] = result.provider_id
            else:
                payload = coordinate(store, provider=provider, budget=budget).to_dict()
    except (BureauRefusal, ProviderRefusal) as refusal:
        print(json.dumps({"refusal": str(refusal), "honesty": _honesty(store)},
                         ensure_ascii=False))
        return 2
    except Exception as failure:  # noqa: BLE001 — any refusal rides along with the honesty line
        print(json.dumps({"refusal": f"{type(failure).__name__}: {str(failure)[:200]}",
                          "honesty": _honesty(store)}, ensure_ascii=False))
        return 2
    payload["honesty"] = _honesty(store, provider=locals().get("provider"))
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
