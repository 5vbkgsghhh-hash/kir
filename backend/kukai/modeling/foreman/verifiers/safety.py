"""Transaction-safety verifier — rollback, leaked refs, stale-object post-commit."""
from __future__ import annotations
import re

from kukai.modeling.schemas.foreman import ReviewIssue, ReviewSeverity
from kukai.modeling.schemas.llm import CodeProposal


_RE_TRY = re.compile(r'\btry\s*\{', re.IGNORECASE)
_RE_CATCH = re.compile(r'\bcatch\b', re.IGNORECASE)
_RE_ROLLBACK = re.compile(r'\btx\s*\.\s*RollBack\s*\(\s*\)', re.IGNORECASE)
_RE_COMMIT = re.compile(r'\btx\s*\.\s*Commit\s*\(\s*\)')
_RE_VAR_DECL = re.compile(r'^\s*var\s+(?P<name>\w+)\s*=', re.MULTILINE)
_RE_TX_BLOCK = re.compile(
    r'using\s*\(\s*var\s+tx\s*=\s*new\s+Transaction.*?\)\s*\{(?P<body>.*?)^\}',
    re.DOTALL | re.MULTILINE,
)


def _warn(category: str, detail: str) -> ReviewIssue:
    return ReviewIssue(
        severity=ReviewSeverity.WARNING, category=category, detail=detail,
        verifier_source="safety",
    )


def check_safety(proposal: CodeProposal) -> list[ReviewIssue]:
    issues: list[ReviewIssue] = []
    code = proposal.csharp_code

    has_commit = bool(_RE_COMMIT.search(code))
    safe_rollback = (_RE_TRY.search(code) and _RE_CATCH.search(code)
                     and _RE_ROLLBACK.search(code))

    # 1. Commit without try/catch+RollBack
    if has_commit and not safe_rollback:
        issues.append(_warn("missing_transaction_rollback",
            "Transaction.Commit() without try/catch+RollBack — partial-failure unsafe"))

    # 2. LookupParameter() after tx.Commit()
    commit_idx = code.find("tx.Commit()")
    if commit_idx >= 0:
        post = code[commit_idx + len("tx.Commit()") :]
        if re.search(r'\.LookupParameter\s*\(', post):
            issues.append(_warn("post_commit_parameter_access",
                "LookupParameter() called after tx.Commit() — possible stale element reference"))

    # 3. Variable declared outside transaction used inside its body
    decls = {m["name"] for m in _RE_VAR_DECL.finditer(code)}
    for tx in _RE_TX_BLOCK.finditer(code):
        body = tx.group("body")
        prefix_decls = {m["name"] for m in _RE_VAR_DECL.finditer(code[:tx.start()])}
        for name in prefix_decls & decls:
            if re.search(rf'\b{re.escape(name)}\b\s*\.', body):
                issues.append(_warn("leaked_reference_into_transaction",
                    f"variable {name!r} declared outside transaction is used inside its body"))
                break

    return issues
