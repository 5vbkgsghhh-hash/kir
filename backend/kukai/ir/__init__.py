"""KIR — Kukai Revit-IR (SPEC: /root/kukai-ir/SPEC_V1.md on yta).

Canonical home of the IR spec, registry, schema generator and compiler
(arbitration Q3). Query family v1. Public surface:

    from kukai.ir import (
        compile_program, plan_program, program_schema, export_capability_cells,
    )
"""
from kukai.ir.compiler import (                                      # noqa: F401
    CompileOutput,
    compile_program,
    plan_program,
)
from kukai.ir.midend import PlannedProgram                            # noqa: F401
from kukai.ir.schema_gen import program_schema                        # noqa: F401
from kukai.ir.spec import export_capability_cells, IR_VERSION         # noqa: F401
# NOTE: kukai.ir.compile_cache (CachedCompileClient) is deliberately NOT
# re-exported here: it pulls compile_client -> httpx into this package's
# import chain, which must stay light and offline-safe (decompile subprocess
# tests run under interpreters without httpx). Import it from its own module:
#     from kukai.ir.compile_cache import CachedCompileClient
