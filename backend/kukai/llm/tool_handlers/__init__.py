"""Tool handlers — server-side dispatchers for purpose-built LLM tools.

Family-editor tools generate C# from verified-API templates and dispatch
through the standard bridge.execute path, eliminating LLM hallucination
on the API surface (each template is written once by us, not regenerated
by the model on every call).
"""
