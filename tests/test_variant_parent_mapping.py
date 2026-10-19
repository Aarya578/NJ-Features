"""Regression tests for parent equivalence through Shopify variant mappings.

Run with: python -m unittest discover -s tests -p test_variant_parent_mapping.py -v
Database access and reservation writes are mocked.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

with patch.object(frappe, "logger"):
    from nj_features.nj_features.doctype.nj_production_planning import nj_production_planning as planning
    from nj_features.overrides import sales_order


TARGET_PARENT = "S-Dell 5400"
DONOR_PARENT = "S-Dell 5400(40PIN NT)-(IR-KBD WTB)"
TARGET = TARGET_PARENT + "-CORE I5 - 8TH GEN-8 GB-256 GB SSD"
MAPPED_DONOR = DONOR_PARENT + "-CORE I5 - 8TH GEN-8 GB-256 GB SSD"
DONOR = DONOR_PARENT + "-CORE I5 - 8TH GEN-16 GB-256 GB SSD"
CPU = "CORE I5 - 8TH GEN"


class TestVariantParentMapping(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db_patch = patch.object(frappe, "db", self.db)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        planning._EQUIVALENT_PARENT_MODELS_CACHE.clear()
        self.addCleanup(planning._EQUIVALENT_PARENT_MODELS_CACHE.clear)
        self.parents = {TARGET: TARGET_PARENT, MAPPED_DONOR: DONOR_PARENT, DONOR: DONOR_PARENT}
        self.db.get_value.side_effect = self.get_value
        self.db.sql.return_value = [{
            "source_item_codes": TARGET + ", " + MAPPED_DONOR,
            "item_code": TARGET + ", " + MAPPED_DONOR,
        }]

    def get_value(self, doctype, name, field):
        if doctype == "Item" and field == "variant_of":
            return self.parents.get(name)
        if doctype == "Item" and field == "item_group":
            return "Laptops"
        raise AssertionError((doctype, name, field))

    def test_mapped_nt_parent_matches_unspecified_parent(self):
        self.assertIn(DONOR_PARENT, planning._get_equivalent_parent_models(TARGET_PARENT))

    def test_different_base_name_is_allowed_when_explicitly_mapped(self):
        self.parents[MAPPED_DONOR] = "S-Dell E5400"
        self.assertIn("S-Dell E5400", planning._get_equivalent_parent_models(TARGET_PARENT))

    def test_shared_variant_can_span_separate_sync_rows(self):
        self.db.sql.return_value = [{"source_item_codes": TARGET, "item_code": MAPPED_DONOR}]
        self.assertIn(DONOR_PARENT, planning._get_equivalent_parent_models(TARGET_PARENT))

    def test_substring_only_source_does_not_establish_membership(self):
        self.db.sql.return_value = [{"source_item_codes": MAPPED_DONOR, "item_code": MAPPED_DONOR}]
        self.assertEqual(planning._get_equivalent_parent_models(TARGET_PARENT), {TARGET_PARENT})

    def test_unmapped_parent_is_not_equivalent(self):
        self.db.sql.return_value = []
        self.assertEqual(planning._get_equivalent_parent_models(TARGET_PARENT), {TARGET_PARENT})

    def test_explicit_touch_nt_conflict_is_excluded(self):
        touch_parent = "S-Dell 5400 TOUCH"
        self.parents[TARGET] = touch_parent
        self.assertNotIn(DONOR_PARENT, planning._get_equivalent_parent_models(touch_parent))

    def test_pir_chassis_conflict_is_excluded(self):
        self.parents[MAPPED_DONOR] = "S-Dell 5400(PIR)"
        self.assertNotIn("S-Dell 5400(PIR)", planning._get_equivalent_parent_models(TARGET_PARENT))

    def test_planner_preserves_mapped_reconfiguration_but_rejects_other_cpu(self):
        for donor_cpu, expected in [(CPU, True), ("CORE I7 - 8TH GEN", False)]:
            with self.subTest(donor_cpu=donor_cpu), patch.object(
                planning, "_cfg_tuple_from_item",
                side_effect=lambda code: (
                    self.parents[code], donor_cpu if code == DONOR else CPU, None, None
                ),
            ):
                self.assertEqual(planning._is_rebuild_compatible(DONOR, TARGET), expected)

    def test_c3_allocates_mapped_16gb_donor_for_8gb_order_before_next_department(self):
        for donor_cpu, expected_serial in [(CPU, "NJ-CB-196590"), ("CORE I7 - 8TH GEN", "FQC-EXACT")]:
            with self.subTest(donor_cpu=donor_cpu):
                self.db.reset_mock()
                self.db._cursor.rowcount = 1
                pools = {
                    "Packing & Dispatch - NJ": [{"name": "NJ-CB-196590", "item_code": DONOR, "to_make": DONOR, "warehouse": "RACK"}],
                    "FQC-NJ": [{"name": "FQC-EXACT", "item_code": TARGET, "to_make": TARGET, "warehouse": "FQC"}],
                }
                with patch.object(sales_order, "get_dept_available_serials", side_effect=lambda dept: pools[dept]), \
                     patch.object(sales_order, "is_serial_already_delivered", return_value=False), \
                     patch.object(planning, "_get_shopify_variant_id", return_value=None), \
                     patch.object(planning, "_cfg_tuple_from_item", side_effect=lambda code: (
                         self.parents[code], donor_cpu if code == DONOR else CPU, None, None
                     )), \
                     patch("nj_features.services.reservation_service.get_effective_order_source", return_value="Online"), \
                     patch.object(frappe, "log_error"):
                    allocated = sales_order.assign_serials("TEST-SO", TARGET, 1, [
                        {"name": "Packing & Dispatch - NJ", "department_sequence": 20},
                        {"name": "FQC-NJ", "department_sequence": 18},
                    ])
                self.assertEqual(allocated, 1)
                writes = [call for call in self.db.sql.call_args_list if "SET reserved_sales_order" in call.args[0]]
                self.assertEqual(len(writes), 1)
                self.assertEqual(writes[0].args[1][-1], expected_serial)


if __name__ == "__main__":
    unittest.main()
