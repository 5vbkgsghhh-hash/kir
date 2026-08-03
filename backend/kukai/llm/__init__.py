"""LLM integration — litellm-based client with streaming and tool calling.

Re-exports are LAZY (PEP 562 ``__getattr__``): importing a *pure* sibling
module — e.g. ``kukai.llm.verbs`` for the Evaluator's read-only probe-code
builders — must NOT pull the heavy litellm client stack. The public names
(``LLMClient`` / ``get_tool_definitions`` / ``PromptAssembler``) still resolve on
first attribute access — identical names, deferred import.

Why this matters (Constitution IRON 3 / plan-020): the Will organ's probe layer
(``kukai.will.probes``) reuses ``kukai.llm.verbs.build_inspect_code``; with the
old eager re-exports that one import transitively loaded ~1.3k litellm/openai
modules, defeating the "import-cheap, LLM-free" guarantee at probe level 2.
Lazy re-export keeps the Evaluator organ import-light and litellm-free.
"""
import os


# LiteLLM otherwise performs a GitHub HTTP request while its module is being
# imported. Production uses the package-bundled cost map for deterministic,
# offline-first startup; an operator can still override this explicitly.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

__all__ = ["LLMClient", "get_tool_definitions", "PromptAssembler"]


def __getattr__(name: str):  # PEP 562 — lazy so importing pure siblings stays cheap
    if name == "LLMClient":
        from kukai.llm.client import LLMClient
        return LLMClient
    if name == "get_tool_definitions":
        from kukai.llm.tools import get_tool_definitions
        return get_tool_definitions
    if name == "PromptAssembler":
        from kukai.llm.prompts import PromptAssembler
        return PromptAssembler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(__all__)
