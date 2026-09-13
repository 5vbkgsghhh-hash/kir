"""Probe FIRST: two PROCESSES reserve one plan. How many go through?"""
import json, os, subprocess, sys, tempfile
from pathlib import Path

# Tree root — from ITS OWN file, not from the machine: the probe used to live
# in `.work/` with the dev machine's absolute path and could not be found on a
# clean clone (the test was silently skipped).
ROOT = str(Path(__file__).resolve().parents[3])
sys.path.insert(0, ROOT)

CHILD = r'''
import json, sys, os
sys.path.insert(0, os.environ["KIR_PROBE_ROOT"])
from uuid import UUID
from kir.emit_transaction_unit import (prepare_transaction_unit, reserve_transaction_unit,
                                       TransactionUnitRefusal)
from kir.revit_connector import ContextPrecondition, RuntimeTarget, SessionCredentials
from kir.tests import test_a_transaction_owning_unit_owns_its_own_transaction as T

ledger, oid, tgt, doc = sys.argv[1], sys.argv[2], json.loads(sys.argv[3]), sys.argv[4]
# План обязан быть ОДНИМ И ТЕМ ЖЕ в обоих процессах, иначе гонка не про эффект,
# а про два разных эффекта, и журнал законно скажет ledger_operation_conflict.
T.uuid4 = lambda: UUID(oid)
target = RuntimeTarget(**tgt)
scope = (target, SessionCredentials(target, "00000000-0000-4000-8000-000000000000", "t"),
         ContextPrecondition(doc, 21))
prepared = prepare_transaction_unit(T.wall_plan(scope), operation_id=oid)
# Барьер: оба процесса подходят к резервированию одновременно.
barrier = ledger + ".barrier"
open(barrier, "a").close()
import time
while not os.path.exists(ledger + ".go"):
    time.sleep(0.01)
try:
    reserve_transaction_unit(prepared, ledger_path=ledger)
    print("RESERVED")
except TransactionUnitRefusal as error:
    print("REFUSED:" + error.code)
'''
import time
from uuid import uuid4
from kir.revit_connector import RuntimeTarget

path = tempfile.mkdtemp(prefix="race-")
child = os.path.join(path, "child.py")
open(child, "w").write(CHILD)
target = RuntimeTarget(str(uuid4()), str(uuid4()), "2026")
oid = str(uuid4())
ledger = os.path.join(path, "unit.json")
args = [sys.executable, child, ledger, oid, json.dumps(target.to_dict()), "native-doc"]
env = {**os.environ, "KIR_PROBE_ROOT": ROOT, "PYTHONPATH": ROOT}
procs = [subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
         for _ in range(2)]
time.sleep(2.0)
open(ledger + ".go", "w").close()
out = [p.communicate(timeout=90) for p in procs]
results = [o[0].strip().splitlines()[-1] if o[0].strip() else "ERR:" + o[1].strip()[-200:] for o in out]
print("процессов:", len(results))
for r in results:
    print("  ", r)
reserved = sum(1 for r in results if r == "RESERVED")
codes = [r.split(":", 1)[1] for r in results if r.startswith("REFUSED:")]
print(f"ПРОШЛО РЕЗЕРВИРОВАНИЙ: {reserved} (обязано быть ровно 1)")
print(f"причины отказов: {codes} (обязано быть ['effect_already_reserved'])")
raise SystemExit(0 if reserved == 1 and codes == ["effect_already_reserved"] else 1)
