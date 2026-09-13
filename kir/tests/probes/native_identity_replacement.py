"""Probe: does observe-after read the REPLACED element or the dead old uid.

Finding of the identity agent: per Autodesk documentation, `ChangeTypeId` may
create a NEW element («applying a change in type will result in a new element
being created… the new element id is returned»). The old one is then dead,
and observe-after, reading by the old UniqueId, gets null → `moved=false` →
`ok=false`. The unit declares FAILURE on a successful replacement.

Red until fixed. Return code 1 if even one property does not hold.
"""
import sys
from pathlib import Path

# Tree root — from ITS OWN file (the probe moved from `.work/` into the tree on 2026-09-07).
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from uuid import uuid4

from kir.emit_transaction_unit import prepare_transaction_unit
from kir.revit_connector import ContextPrecondition, RuntimeTarget, SessionCredentials
from kir.tests import test_a_transaction_owning_unit_owns_its_own_transaction as T

target = RuntimeTarget(str(uuid4()), str(uuid4()), "2026")
scope = (target, SessionCredentials(target, str(uuid4()), "t"), ContextPrecondition("native-doc", 21))
source = prepare_transaction_unit(T.duplicate_plan(scope), operation_id=str(uuid4())).source

after = source.split('__receipt["state"] = "committed_unverified"', 1)[1]
checks = [
    ("observe-after читает массив замен", "__replacement[__i]" in after),
    ("observe-after НЕ читает старый uid", "doc.GetElement(__reassign[__i])" not in after),
    # 🔴 WE CHECK THE ASSIGNMENT, NOT THE SUBSTRING. The probe's first
    # edition searched for `__replaced ? __newElement` — and stayed GREEN on
    # a mutation that removed the reading of the live element: the same
    # substring lives in the record-sheet line
    # (`__replaced ? __newElement.ToString()`). The third case of the same
    # trap in two shifts, now in the probe too.
    ("живой элемент читается по возвращённому id",
     "Element __live = doc.GetElement(__replaced ? __newElement : __wasId);" in source),
    ("живой uid попадает в массив",
     "__replacement[__i] = __live == null ? null : __live.UniqueId;" in source),
    ("ведомость названа схемой", '"kir-create-identity-replacement/1"' in source),
    ("ведомость отдельным полем квитанции",
     '__receipt["identity_replacements"] = __moved;' in source),
    ("пара old/new в квитанции", '"old_unique_id"' in source and '"new_unique_id"' in source),
    ("замена — не отказ", '"identity_replaced"' in source),
    ("адрес снят ДО вызова",
     source.index("ElementId __wasId = __u.Id;") < source.index("__u.ChangeTypeId(__dupId)")),
]
bad = 0
for name, ok in checks:
    print(f"  {'ДА ' if ok else 'НЕТ'} | {name}")
    bad += 0 if ok else 1
print(f"НЕ ДЕРЖИТСЯ СВОЙСТВ: {bad} (обязано быть 0)")
raise SystemExit(1 if bad else 0)
