# -*- coding: utf-8 -*-
"""An autonomous design bureau: a coordinator and model workers.

🔴 THERE IS NO REAL PROVIDER HERE, AND THIS IS STATED, NOT IMPLIED. The
owner's word: "A stand-in provider will test the mechanism, but will not
close this mission." So the package builds the MECHANISM — the port, the
cassette, the team budget, Stop, the chain "model text -> sandbox ->
proposal -> CAS" — and must report `настоящий LLM: 0 вызовов` everywhere.
"""
from kir.bureau.exchange import FileExchangeProvider
from kir.bureau.provider import (CompletionRequest, CompletionResponse, ProviderRefusal,
                                 RealProviderUnavailable, TapeProvider, real_provider)
from kir.bureau.runner import (Decisions, TeamBudget, WorkResult, assign, coordinate,
                               is_stopped, spend, stop, work)

__all__ = ["CompletionRequest", "CompletionResponse", "Decisions", "FileExchangeProvider",
           "ProviderRefusal",
           "RealProviderUnavailable", "TapeProvider", "TeamBudget", "WorkResult", "assign",
           "coordinate", "is_stopped", "real_provider", "spend", "stop", "work"]
