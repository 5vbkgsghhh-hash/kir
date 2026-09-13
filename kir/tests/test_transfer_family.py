"""DOCUMENT-TO-DOCUMENT FAMILY TRANSFER — guards for the `transfer_family` op.

There is ONE main test here, and it is structural: `LoadFamily(Document)` must
stand OUTSIDE the transaction, and `Activate` — INSIDE it. This is not a matter of style: RevitAPI.xml
forbids the former on a modifiable document and makes the latter impossible without a
transaction, identically across all six versions. An order broken by a fix
WILL PASS compilation and fail only live — that is, exactly the class of silent
breakage this file exists for.
"""
import unittest


def _emit(op_extra=None, ver="2024"):
    from kir import authoring, ground as ground_mod
    from kir.compiler import _parse_and_check
    from kir.tests.fixtures import GROUND_SNAPSHOT
    op = {"op": "transfer_family", "id": "TF1",
          "source_document": "MNVNK",
          "family_name": "СП_Унитаз универсальный"}
    op.update(op_extra or {})
    grounded = ground_mod.ground(
        _parse_and_check({"ir_version": "1.0", "ops": [op]}), GROUND_SNAPSHOT)
    return authoring.emit_program(grounded, ver)


def _emit_guarded(op_extra=None, ver="2024", *, doc=True, ids=True):
    """Emission via the SAME PROD CALL that A5 uses to build it for a solo op.

    `emit_program` forwards `expected_document`/`expected_identities` into
    `_SOLO_PROGRAMS[...]` (authoring.py, the "solo" branch) — a handwritten fixture
    here would be measuring itself, not the path.
    """
    from kir import authoring, ground as ground_mod
    from kir.compiler import _parse_and_check
    from kir.contracts import ElementIdentityProof
    from kir.tests.fixtures import GROUND_SNAPSHOT
    op = {"op": "transfer_family", "id": "TF1",
          "source_document": "MNVNK",
          "family_name": "СП_Унитаз универсальный"}
    op.update(op_extra or {})
    grounded = ground_mod.ground(
        _parse_and_check({"ir_version": "1.0", "ops": [op]}), GROUND_SNAPSHOT)
    return authoring.emit_program(
        grounded, ver,
        expected_document=({"title": "Проект1",
                            "path_name": "C:/p/Проект1.rvt",
                            "project_uid": "u-проект"} if doc else None),
        expected_identities=((ElementIdentityProof(
            element_id=311, unique_id="u-311",
            version_guid="a" * 32),) if ids else None))


class РеестрЗнаетОп(unittest.TestCase):
    def test_op_is_registered_and_solo(self):
        from kir import spec
        self.assertIn("transfer_family", spec.OPS)
        # SOLO is not a convenience, but a Revit prohibition: EditFamily and LoadFamily
        # throw InvalidOperationException when a transaction is open, while the body
        # of an ordinary KIR program runs inside one.
        self.assertIn("transfer_family", spec.SOLO_OPS)

    def test_op_has_a_solo_program_emitter(self):
        from kir import authoring
        self.assertIn("transfer_family", authoring._SOLO_PROGRAMS)

    def test_every_post_clause_names_an_axis(self):
        from kir import spec
        post = spec.OPS["transfer_family"].post
        clauses = [c for c in post.split(";") if c.strip()]
        self.assertTrue(clauses)
        for clause in clauses:
            self.assertTrue(
                any(f"({k})" in clause for k in spec.POST_CLAUSE_KINDS),
                f"клауза без названного рода: {clause.strip()[:70]}")

    def test_translation_refinement_names_both_api_links(self):
        # A single `LoadFamily` would not distinguish this op from `load_family`, which
        # takes a PATH: the certificate would stop telling the two mechanisms apart.
        from kir import translation_cert
        row = translation_cert._ensure_table()["transfer_family"]
        self.assertIn("EditFamily", row.materializer)
        self.assertIn("LoadFamily", row.materializer)


class ПорядокТранзакции(unittest.TestCase):
    """🔴 THE MOST IMPORTANT CLASS IN THE FILE."""

    def test_load_family_stands_outside_the_transaction(self):
        cs = _emit()
        load = cs.index(".LoadFamily(doc)")
        txn = cs.index("new Transaction(doc")
        self.assertLess(
            load, txn,
            "LoadFamily(Document) обязан стоять ДО открытия транзакции: "
            "RevitAPI.xml бросает InvalidOperationException, когда целевой "
            "документ изменяем")

    def test_edit_family_stands_outside_the_transaction(self):
        cs = _emit()
        self.assertLess(cs.index(".EditFamily("), cs.index("new Transaction(doc"))

    def test_activate_stands_inside_the_transaction(self):
        cs = _emit()
        self.assertLess(
            cs.index("new Transaction(doc"), cs.index(".Activate()"),
            "Activate меняет документ и вне транзакции невозможен")

    def test_family_document_is_closed_in_finally(self):
        cs = _emit()
        tail = cs[cs.index(".EditFamily("):]
        fin = tail.index("finally")
        self.assertIn("Close(false)", tail[fin:fin + 500])


class ОтказыНазываютФакт(unittest.TestCase):
    def test_guards_precede_the_api_calls(self):
        """Revit's prohibitions are checked BEFORE the call, rather than caught afterward.

        RevitAPI.xml for EditFamily: ArgumentException «when the input argument
        is an in-place family or a non-editable family. (This can be checked
        with the IsInPlace and IsEditable properties)». The check returns the author a
        FACT ABOUT THE MODEL in advance, instead of the text of an exception.
        """
        cs = _emit()
        # 🔴 THE PROBE LOOKS FOR THE CALL `.EditFamily(`, NOT THE WORD `EditFamily`. The first
        # edition looked for the word and failed: the name also appears in a comment
        # that explains THESE SAME prohibitions and therefore sits ABOVE them. The instrument
        # was measuring the comment, not the branch — a form named after this very tree.
        edit = cs.index(".EditFamily(")
        for guard in (".IsInPlace", ".IsEditable"):
            self.assertLess(cs.index(guard), edit, guard)

    def test_zero_and_two_matches_are_different_refusals(self):
        cs = _emit()
        self.assertIn("не открыт в этой сессии", cs)
        self.assertIn("адрес неоднозначен", cs)

    def test_refusals_print_the_open_titles(self):
        # "not found" without a list sends you off to guess; the next move must
        # be visible from the refusal itself.
        cs = _emit()
        self.assertIn("__titles_", cs)

    def test_target_document_is_excluded_from_the_search(self):
        # Transferring a family into itself is a hidden address error, not idle
        # work; a silent success would teach the author something wrong.
        self.assertIn(".Equals(doc)) continue", _emit())

    def test_conflict_is_never_a_silent_overwrite(self):
        """The overload WITHOUT IFamilyLoadOptions was chosen for the sake of this property."""
        cs = _emit()
        self.assertNotIn("IFamilyLoadOptions", cs)
        self.assertNotIn("RevitUIFamilyLoadOptions", cs)
        self.assertIn("защита от тихой перезаписи", cs)

    def test_repeat_is_recognised_before_the_call(self):
        cs = _emit()
        self.assertIn("already_present", cs)
        self.assertLess(cs.index("__already_"), cs.index(".EditFamily("))


class ТипоразмерНеПодменяется(unittest.TestCase):
    def test_named_type_is_searched_within_the_transferred_family_only(self):
        cs = _emit({"type_name": "Унитаз с инсталляцией"})
        self.assertIn("__sc_", cs)
        self.assertIn(".Family.Id.ToString() != __dst_", cs)

    def test_missing_named_type_refuses_instead_of_substituting(self):
        cs = _emit({"type_name": "Унитаз с инсталляцией"})
        self.assertIn("Подставлять одноимённый тип", cs)

    def test_symbol_ids_are_not_read_through_the_system_dll_trap(self):
        """`GetFamilySymbolIds` returns `ISet<>`, and that lives in System.dll,
        which the shipped plugin does not reference — CS0012, the same mine that
        killed the tags stage live on 04.08.2026."""
        self.assertNotIn("GetFamilySymbolIds", _emit())


class СолоПравилоДержится(unittest.TestCase):
    def test_a_neighbour_op_in_the_same_program_is_refused(self):
        from kir import authoring, ground as ground_mod
        from kir.compiler import _parse_and_check
        from kir.diag import KirRefusal
        from kir.tests.fixtures import GROUND_SNAPSHOT
        prog = {"ir_version": "1.0", "ops": [
            {"op": "transfer_family", "id": "TF1", "source_document": "MNVNK",
             "family_name": "СП_Унитаз универсальный"},
            {"op": "create_level", "id": "L1", "elev_mm": 3000.0},
        ]}
        # The refusal arrives EARLIER than emission — at plan parsing (KIR-L002), and this
        # is stricter than I expected: the adjacency of a solo op is already inexpressible in the program,
        # not only in the C#. The guard holds BOTH moves, so that a fix moving the
        # check would not go unnoticed.
        with self.assertRaises(KirRefusal):
            grounded = ground_mod.ground(_parse_and_check(prog), GROUND_SNAPSHOT)
            authoring.emit_program(grounded, "2024")


class ЭмиссияОдинаковаНаШестиВерсиях(unittest.TestCase):
    def test_no_version_conditional_branch_sneaked_in(self):
        """The op is not version-fragile: all three members exist on 2021…2026 (measured against
        RevitAPI.xml). A divergent emission would mean that someone had introduced a
        branch without an entry in the version-fragility journal."""
        bodies = {ver: _emit(ver=ver)
                  for ver in ("2021", "2022", "2023", "2024", "2025", "2026")}
        self.assertEqual(len(set(bodies.values())), 1)


class КвитанцияРазличаетПереносИУзнавание(unittest.TestCase):
    """E-64: `created` separates a TRANSFER from RECOGNIZING something already present.

    🔴 THE COST OF AN ERROR HERE IS IRREVERSIBLE, AND THAT IS EXACTLY WHY THE GUARD HOLDS BOTH
    SIDES. `idempotence.collect_created_ids` skips a row EXACTLY on
    `created is False`, and `cleanup_created` sends a REAL deletion program
    against whatever remains and sits in a `finally` («ALWAYS runs on the live path»).
    So:

        no key / `created` always true   -> we delete SOMEONE ELSE'S type,
                                             which already lay in the document
        `created` always false           -> we do NOT delete OUR OWN -> AN ORPHAN

    The second trouble is quieter than the first and therefore more dangerous for a future reader: the temptation
    to "simplify" the fix down to one branch exists in both directions, and both
    are closed below BY NAME.

    🔴 THE GUARD STRIKES AT THE PATH, NOT AT A HELPER. The receipt line is not written
    by hand — it is LIFTED FROM THE EMISSION with a regex and fed to the LIVE
    cleanup reader. A check that called `collect_created_ids` on a
    made-up dictionary would prove that the reader is capable, not that the right value
    reaches it.
    """

    @staticmethod
    def _row(already: bool) -> dict:
        """The result line, LIFTED FROM THE EMISSION, for a given `__already_`."""
        import re
        row = {}
        for line in _emit().splitlines():
            m = re.match(r'\s*__rb_TF1\["([^"]+)"\]\s*=\s*(.+);\s*$', line)
            if not m:
                continue
            key, expr = m.group(1), m.group(2)
            if ".Id.ToString()" in expr:
                row[key] = "294076"
            elif "__symCount_TF1" in expr:
                row[key] = 3
            # 🔴 ALL BOOLEAN FORMS ARE PARSED, NOT ONLY THE EXPECTED ONE.
            # The first edition recognized only `!__already_TF1`, and the mutation
            # `= false;` fell through into the `else`, where the key became a STRING:
            # the test turned red on PARSING, not on the cleanup's behavior. The instrument was
            # right, but about a different subject. Now the mutation changes the VALUE
            # that `collect_created_ids` reads, and exactly the
            # assertion this class was written for turns red.
            elif expr == "!__already_TF1":
                row[key] = (not already)
            elif expr == "__already_TF1":
                row[key] = already
            elif expr in ("true", "false"):
                row[key] = (expr == "true")
            else:
                row[key] = "СП_Унитаз универсальный"
        return row

    def test_the_receipt_carries_created_at_all(self):
        self.assertIn('__rb_TF1["created"] = !__already_TF1;', _emit())

    def test_an_already_present_symbol_is_not_ours_to_delete(self):
        """THE FIRST SIDE: someone else's type does NOT go into cleanup."""
        from kir.idempotence import collect_created_ids, collect_created_by_op
        row = self._row(already=True)
        self.assertIs(row["already_present"], True)
        self.assertIs(row["created"], False)
        envelope = {"ok": True, "result": {"TF1": row}}
        self.assertEqual(collect_created_ids([envelope]), [],
                         "уже присутствовавший типоразмер попал в список на "
                         "УДАЛЕНИЕ — уборка А5 снесла бы ЧУЖОЙ элемент")
        self.assertEqual(collect_created_by_op(envelope), {})

    def test_a_real_transfer_stays_in_the_cleanup_list(self):
        """🔴 THE SECOND SIDE, AND WITHOUT IT THE FIRST IS DANGEROUS.

        A fix "simplified" down to an eternal `created=false` would pass the neighboring
        test and would introduce AN ORPHAN: the actual transferred item would remain in the document
        after cleanup. This is where it turns red.
        """
        from kir.idempotence import collect_created_ids, collect_created_by_op
        row = self._row(already=False)
        self.assertIs(row["already_present"], False)
        self.assertIs(row["created"], True)
        envelope = {"ok": True, "result": {"TF1": row}}
        self.assertEqual(collect_created_ids([envelope]), ["294076"],
                         "настоящий перенос ВЫПАЛ из списка уборки — "
                         "он останется в документе СИРОТОЙ")
        self.assertEqual(collect_created_by_op(envelope), {"TF1": "294076"})

    def test_identity_keys_are_not_dropped_by_a_later_simplification(self):
        """D3: `element_id` and `id` BOTH live on (F-274). `id` is required by the law
        of the census (KIR-X008), `element_id` is read from outside."""
        cs = _emit()
        self.assertIn('__rb_TF1["id"] = __sym_TF1.Id.ToString();', cs)
        self.assertIn('__rb_TF1["element_id"] = __sym_TF1.Id.ToString();', cs)



class ОхраныСтоятДоНЕОБРАТИМОГОШАГА(unittest.TestCase):
    """🔴 F-275. `LoadFamily(doc)` GOES OUTSIDE THE TRANSACTION — Revit requires this, and
    it cannot be moved. So it is the GUARDS that must be moved: anything that decides "is it
    allowed" must execute BEFORE the irreversible step, because rolling back Phase B
    CANNOT undo Phase A.

    Both guards are PURE READS of the target document (`doc.Title`,
    `doc.PathName`, `doc.ProjectInformation.UniqueId`, `doc.GetElement(id)` against
    evidence captured beforehand), neither requires the family to be
    ALREADY LOADED — both are movable. The precedent belongs to someone else, but it is our own too:
    `emit_stairs_program` places `pre_doc_guard`/`pre_identity_guard` before
    `StairsEditScope` and repeats them inside the transaction.
    """

    def test_document_guard_precedes_the_irreversible_load(self):
        cs = _emit_guarded(ids=False)
        self.assertLess(
            cs.index("active document fingerprint changed"),
            cs.index(".LoadFamily(doc)"),
            "цель могла смениться после планирования: семейство уехало бы в "
            "ЧУЖОЙ документ, а откат Фазы Б этого не отменяет")

    def test_identity_guard_precedes_the_irreversible_load(self):
        # 🔴 «open model binding changed» БОЛЬШЕ НЕ ЭМИТИТСЯ. Волна N-2 заменила
        # текст этого отказа на именованный код со следующим ходом
        # (`identity_changed_since_read: … query_element_state`) и не поправила
        # здесь — тест стоял красным с 13.09 и ни один набор, который я гонял,
        # этот файл не покрывал. Предмет теста не изменился: страж личности
        # стоит ДО необратимой загрузки.
        cs = _emit_guarded(doc=False)
        self.assertLess(
            cs.index("identity_changed_since_read"),
            cs.index(".LoadFamily(doc)"))

    def test_the_in_transaction_copy_is_not_traded_away(self):
        """Moving the guard UP does not cancel it below: between the reading of Phase A and
        the first mutation of Phase B, a race still remains, and it is for its sake that the second
        instance is added."""
        cs = _emit_guarded()
        txn = cs.index("new Transaction(doc")
        self.assertGreater(cs.rindex("active document fingerprint changed"), txn)
        self.assertGreater(cs.rindex("identity_changed_since_read"), txn)

    def test_two_identity_guards_do_not_collide_on_one_local_name(self):
        """🔴 CS0136, bought on 21.08.2026 on `create_stairs`. The guard declares
        its own local `__kirBinding_N`; emitted TWICE — in the enclosing
        scope and in the nested one — it declares them twice, and C# forbids this.
        Fixed with its OWN PREFIX on the second one, exactly as with the landing and the flight."""
        cs = _emit_guarded(doc=False)
        self.assertEqual(cs.count("Element __kirBinding_0 = null;"), 1)
        self.assertEqual(cs.count("Element __kirXferTxnBinding_0 = null;"), 1)


class ЧтоРешаетМожноЛиИдётДоЗагрузки(unittest.TestCase):
    """🔴 F-276, THE FIRST HALF. A legitimate request for a type that is not in the
    family TODAY loads the family and only then refuses in Phase B —
    there is NO compensating deletion ANYWHERE (`doc.Delete` has 0 occurrences in the file).
    The check "does this type exist" is a pure read of the SOURCE document and
    does not require the family to be loaded, so it belongs BEFORE `LoadFamily`."""

    def test_an_absent_named_type_is_refused_before_the_load(self):
        cs = _emit_guarded({"type_name": "Унитаз с инсталляцией"})
        self.assertLess(
            cs.index("проверено ДО загрузки"), cs.index(".LoadFamily(doc)"),
            "семейство грузится, потом отказ, и удалить его нечем")

    def test_a_family_without_a_single_type_is_refused_before_the_load(self):
        cs = _emit_guarded()
        self.assertLess(
            cs.index("ни одного типоразмера"), cs.index(".LoadFamily(doc)"))

    def test_the_precheck_reads_the_SOURCE_document(self):
        """The probe strikes at the subject: the roster is taken from `__src_`, not from `doc` —
        the family is not yet in the target, and a check against `doc` would be green
        by construction."""
        cs = _emit_guarded({"type_name": "Унитаз с инсталляцией"})
        head = cs[:cs.index(".LoadFamily(doc)")]
        self.assertIn("new FilteredElementCollector(__src_TF1)\n"
                      "    .OfClass(typeof(FamilySymbol))", head)
        # The denominator is the types of the SOURCE family specifically, not of the entire
        # source document: a document-wide roster would be green for the neighbor.
        self.assertIn("__ss_TF1.Family.Id.ToString() != __fam_TF1.Id.ToString()",
                      head)
        # And the refusal prints THIS roster, rather than staying silent.
        self.assertIn("__srcTypes_TF1", cs[:cs.index(".LoadFamily(doc)")])


class ОтказПослеЭффектаНазываетЭФФЕКТ(unittest.TestCase):
    """🔴 F-276, THE SECOND HALF — it is closed even when there is nothing to delete.

    A refusal AFTER an irreversible step has already occurred is never "just a refusal": it
    must name what remains in the document. Today the receipt stays
    silent about this."""

    @staticmethod
    def _phase_b(cs):
        return cs[cs.index("// ФАЗА Б"):]

    def test_the_notice_says_the_family_stays_in_the_document(self):
        cs = _emit_guarded({"type_name": "Унитаз с инсталляцией"})
        self.assertIn("ОСТАЁТСЯ в нём", cs)
        self.assertIn("компенсирующего удаления", cs)

    def test_the_notice_is_carried_by_an_OBSERVED_flag(self):
        """`__loaded_` is set AFTER a successful `LoadFamily`, rather than being derived from
        `__already_`: observed, not derived."""
        cs = _emit_guarded()
        self.assertIn("__loaded_TF1 = true;", cs)
        self.assertLess(cs.index(".LoadFamily(doc)"),
                        cs.index("__loaded_TF1 = true;"))

    def test_every_refusal_this_emitter_owns_in_phase_b_names_the_effect(self):
        """🔴 A PROPERTY, NOT THE APPEARANCE OF THE FIRST CASE (form 54). The question is not
        "does the refusal about the type have a note", but "does EVERY
        Phase B refusal whose text belongs to this emitter carry it".

        The A5 guards' refusals (`__Refuse("$program", ...)`) are NOT included here: their text
        is assembled by `emit_core._document_binding_guard` /
        `_element_identity_guard`, and there is nothing here to attribute that effect to.
        This is a named remainder, not an omission.
        """
        import re
        for extra in ({"type_name": "Унитаз с инсталляцией"}, None):
            cs = _emit_guarded(extra)
            body = self._phase_b(cs)
            marker = '"$program"'
            owned = [m for m in re.finditer(r"return __Refuse\(", body)
                     if not body.startswith(marker, m.end())]
            self.assertTrue(
                any(body.startswith(marker, m.end())
                    for m in re.finditer(r"return __Refuse\(", body)),
                "охран А5 в эмиссии нет — зонд не отличил бы остаток от "
                "починки (знаменатель пуст)")
            self.assertTrue(owned, "ни одного отказа не найдено — зонд слеп")
            for m in owned:
                stmt = body[m.start():body.index(";", m.start()) + 1]
                self.assertIn(
                    "__effect_TF1", stmt,
                    "отказ Фазы Б молчит о загруженном семействе: "
                    + stmt[:120])

    def test_the_postcondition_path_names_the_effect_too(self):
        cs = _emit_guarded()
        self.assertIn('__results["residual_effect"] = __effect_TF1;', cs)


class ПовторУзнаётсяНеПоОДНОМУИМЕНИ(unittest.TestCase):
    """🔴 F-277. The preflight declares ANY target family with the required `.Name` to be
    THE SOUGHT DUPLICATE, skips `LoadFamily`, activates a type FROM SOMEONE ELSE'S
    family, and reports `already_present=true` — directly against the registry's
    postcondition ("a same-named family from a different source is never
    substituted in").

    There is NO cross-cutting IDENTITY for `Family` in the API — measured against RevitAPI.xml for all six
    versions: 27 members, no path and no identifier that survives the document
    boundary. So it is the CONTENTS that are compared: the category (`FamilyCategoryId` —
    BuiltInCategory is the same across all documents, 6/6) and the set of types.
    """

    # 🔴 THIS CLASS WAS REWRITTEN AFTER ITS OWN FAIL CONTROL. The first
    # edition searched the TEXT for the words `FamilyCategoryId` and `__srcTypes_`, and both
    # mutations — "compare only the category" and "revert the preflight to matching by name only" —
    # made by replacing the condition with `if (false)` — left the words in place.
    # The probe was GREEN with a dead comparison: it pinned down the appearance, not the property
    # (forms 8 and 52). Now what is asked is the CONDITION and the path leading to the assignment.

    def test_the_preflight_does_not_close_on_the_name_alone(self):
        cs = _emit()
        head = cs[cs.index("__nameHits_TF1++;"):
                  cs.index("__already_TF1 = true")]
        for cond in (
                "if (__dc_TF1.FamilyCategoryId.ToString() != __srcCat_TF1)",
                "if (__dstTypes_TF1 != __srcTypes_TF1)"):
            self.assertIn(cond, head,
                          "между совпадением имени и признанием повтора нет "
                          "этой сверки: " + cond)
            self.assertIn("continue;", head[head.index(cond):],
                          "несовпадение не отвергает кандидата")

    def test_nothing_else_can_declare_a_repeat(self):
        """There is exactly one assignment: a second path to `already_present=true`
        would bypass the comparison silently."""
        cs = _emit()
        self.assertEqual(cs.count("__already_TF1 = true"), 1)

    def test_a_same_name_stranger_is_refused_not_substituted(self):
        cs = _emit()
        self.assertIn("это ДРУГОЕ семейство", cs)

    def test_the_refusal_names_WHAT_differs(self):
        """"Did not match" without a value sends you off to guess."""
        cs = _emit()
        self.assertIn("__mismatch_TF1", cs)

    def test_the_receipt_states_the_basis_of_the_repeat(self):
        """The choice must be PRODUCED AS EVIDENCE, not just made: `already_present`
        without grounds is indistinguishable from a `.FirstOrDefault()` with a good reputation."""
        cs = _emit()
        self.assertIn('__rb_TF1["already_present_basis"]', cs)


if __name__ == "__main__":
    unittest.main()
