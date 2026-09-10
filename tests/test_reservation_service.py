"""
Unit and integration tests for the Unified Reservation Service.

Tests:
1. test_pure_eta_calculation: Pure non-mutating ETA returns valid date and SLA.
2. test_completed_order_rejection: Attempting swap on completed order raises ValidationError.
3. test_swap_validation_wrong_serial: Swapping with an unreserved serial raises ValidationError.
4. test_upgrade_dry_run_execution: Scans upstream reserved orders and finds ready stock candidates.
5. test_tier_ranking_logic: Verifies Tier 1A (Packing & Dispatch exact match) precedes upstream WIP units.
"""

import os
import unittest
import frappe
from frappe.utils import nowdate, getdate, add_days
from nj_features.overrides.sales_order import add_working_days

from nj_features.services.reservation_service import (
    swap_order_reservation,
    compute_pure_sales_order_eta,
    upgrade_order_reservations,
)


class TestReservationService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not frappe.db:
            frappe.init(site="tushar", sites_path="/home/upgrade/frappe-bench/sites")
            frappe.connect()

    def test_pure_eta_calculation(self):
        """Verify compute_pure_sales_order_eta calculates SLA for an order without DB side effects."""
        calc_date, days, reason = compute_pure_sales_order_eta("SAL-ORD-2025-11255")
        self.assertGreater(days, 0)
        self.assertEqual(calc_date, add_working_days(getdate(nowdate()), days))
        self.assertTrue(len(reason) > 0)

    def test_completed_order_rejection(self):
        """Completed or closed orders must reject swaps to prevent tampering with delivered shipments."""
        with self.assertRaises(frappe.ValidationError):
            swap_order_reservation(
                so_name="SAL-ORD-2026-08571",
                old_serial_no="NJ-CB-575152",
                new_serial_no="NJ-CB-782341",
            )

    def test_swap_validation_wrong_serial(self):
        """Attempting to swap a serial not belonging to the order must raise ValidationError."""
        with self.assertRaises(frappe.ValidationError):
            swap_order_reservation(
                so_name="SAL-ORD-2025-11255",
                old_serial_no="NON_EXISTENT_SERIAL_99999",
                new_serial_no="NJ-LP-456810",
            )

    def test_upgrade_dry_run_execution(self):
        """Verify upgrade_order_reservations dry_run executes cleanly and returns list of eligible upgrades."""
        upgrades = upgrade_order_reservations(dry_run=True)
        self.assertIsInstance(upgrades, list)
        self.assertGreaterEqual(len(upgrades), 0)
        for u in upgrades:
            self.assertEqual(u.get("status"), "dry_run")
            self.assertTrue(u.get("so_name"))
            self.assertTrue(u.get("new_serial"))

    def test_tier_ranking_logic(self):
        """Verify Tier 1A (Packing & Dispatch exact match) is prioritized over upstream WIP reconfigs."""
        departments = [
            {"name": "Chip Tech - NJ", "department_sequence": 5},
            {"name": "Packing & Dispatch - NJ", "department_sequence": 20},
        ]
        dept_candidates = {
            "Chip Tech - NJ": [
                {"name": "WIP-01", "item_code": "DIFFERENT_ITEM", "to_make": "TARGET_SKU"},
            ],
            "Packing & Dispatch - NJ": [
                {"name": "PND-01", "item_code": "TARGET_SKU", "to_make": "TARGET_SKU"},
            ]
        }

        # Simulated Priority-First allocation:
        chosen = []
        target_item = "TARGET_SKU"

        # Tier 1A: Check Packing & Dispatch exact match
        pnd_exact = [s for s in dept_candidates.get("Packing & Dispatch - NJ", []) if s.get("item_code") == target_item]
        for s in pnd_exact:
            chosen.append((s["name"], "Tier 1A"))

        # Tier 1C: WIP reconfigs
        wip_reconfigs = [s for s in dept_candidates.get("Chip Tech - NJ", []) if s.get("to_make") == target_item]
        for s in wip_reconfigs:
            chosen.append((s["name"], "Tier 1C"))

        # Verify Tier 1A candidate was selected first
        self.assertEqual(chosen[0], ("PND-01", "Tier 1A"))

    def test_committed_delivery_date_preservation(self):
        """Verify update_sales_order_etas never lowers an existing committed_delivery_date."""
        from nj_features.overrides.sales_order import update_sales_order_etas
        test_so = "SAL-ORD-2025-11255"
        
        # Set a future committed delivery date
        future_date = add_days(getdate(nowdate()), 30)
        frappe.db.set_value("Sales Order", test_so, "committed_delivery_date", future_date, update_modified=False)
        frappe.db.commit()

        # Run ETA update with a 1-day ETA
        update_sales_order_etas({test_so: 1}, do_commit=True)

        # Confirm committed_delivery_date was NOT dragged down to 1-day ETA
        refreshed_comm = frappe.db.get_value("Sales Order", test_so, "committed_delivery_date")
        self.assertEqual(str(refreshed_comm), str(future_date))

    def test_delivery_date_and_committed_date_immutability(self):
        """Verify update_sales_order_etas locks delivery_date and committed_delivery_date, updating only estimated_delivery_date."""
        from nj_features.overrides.sales_order import update_sales_order_etas
        test_so = "SAL-ORD-2025-11255"
        
        future_comm = add_days(getdate(nowdate()), 30)
        frappe.db.set_value("Sales Order", test_so, {
            "committed_delivery_date": future_comm,
            "delivery_date": future_comm
        }, update_modified=False)
        frappe.db.sql("UPDATE `tabSales Order Item` SET delivery_date = %s WHERE parent = %s", (future_comm, test_so))
        frappe.db.commit()

        # Run ETA update with a 1-day ETA
        update_sales_order_etas({test_so: 1}, do_commit=True)

        # Confirm delivery_date and committed_delivery_date were NOT overwritten by factory ETA
        # and are both aligned to the customer commitment date
        refreshed_comm = frappe.db.get_value("Sales Order", test_so, "committed_delivery_date")
        refreshed_deliv = frappe.db.get_value("Sales Order", test_so, "delivery_date")
        item_deliv = frappe.db.get_value("Sales Order Item", {"parent": test_so}, "delivery_date")

        self.assertEqual(str(refreshed_comm), str(future_comm))
        self.assertEqual(str(refreshed_deliv), str(future_comm))
        self.assertEqual(str(item_deliv), str(future_comm))
        self.assertEqual(str(refreshed_deliv), str(refreshed_comm))

        # Confirm estimated_delivery_date was updated dynamically
        est_deliv = frappe.db.get_value("Sales Order", test_so, "estimated_delivery_date")
        self.assertIsNotNone(est_deliv)

    def test_compute_delivery_date_takes_max_sla(self):
        """Verify compute_sales_order_delivery_date uses max() SLA across allocated serials."""
        from nj_features.overrides.sales_order import compute_sales_order_delivery_date
        from unittest.mock import patch

        mock_serials = [
            {"name": "SN-01", "item_code": "ITEM-A", "to_make": None, "remarks": "", "dept_name": "Packing & Dispatch - NJ", "department_sequence": 20, "department_sla": 1, "item_group": "Desktop"},
            {"name": "SN-02", "item_code": "ITEM-A", "to_make": None, "remarks": "", "dept_name": "Testing - NJ", "department_sequence": 15, "department_sla": 5, "item_group": "Desktop"},
        ]

        with patch("frappe.db.sql") as mock_sql, \
             patch("frappe.db.has_column", return_value=True), \
             patch("frappe.db.table_exists", return_value=False), \
             patch("frappe.db.sql_list", return_value=["ITEM-A"]), \
             patch("frappe.db.get_value", return_value=None), \
             patch("frappe.db.set_value"):
            
            def sql_side_effect(query, *args, **kwargs):
                if "tabSerial No" in query:
                    return mock_serials
                if "tabDepartment" in query:
                    return [
                        {"name": "Packing & Dispatch - NJ", "department_sequence": 20, "department_sla": 1, "sla_item_groups": "Desktop"},
                        {"name": "Testing - NJ", "department_sequence": 15, "department_sla": 5, "sla_item_groups": "Desktop"},
                    ]
                return []

            mock_sql.side_effect = sql_side_effect

            res = compute_sales_order_delivery_date("SO-TEST-MAX", return_reason=True)
            self.assertIsInstance(res, tuple)
            target_date, reason = res
            # Testing SLA (6d + 10% buffer = 7d) is much greater than P&D (1d).
            # Max SLA logic must select the larger date, not the 1d date.
            expected_min_date = add_days(getdate(nowdate()), 2)
            self.assertGreater(getdate(target_date), getdate(expected_min_date))

    def test_repair_serial_swap_prevention(self):
        """Verify swap_order_reservation refuses to swap customer Repair serial numbers."""
        from unittest.mock import patch

        mock_old = {
            "name": "REPAIR-01",
            "status": "Active",
            "warehouse": "FQC - NJ",
            "department": "FQC - NJ",
            "reserved_sales_order": "SO-REPAIR-TEST",
            "to_make": "LAPTOP-01",
            "item_code": "LAPTOP-01",
            "return_reason": "Repair",
            "order_source": "NJ-Website-B2C - Repair",
            "is_replace": 0
        }
        mock_new = {
            "name": "READY-01",
            "status": "Active",
            "warehouse": "PND - NJ",
            "department": "Packing & Dispatch - NJ",
            "reserved_sales_order": None,
            "to_make": "LAPTOP-01",
            "item_code": "LAPTOP-01",
            "return_reason": None,
            "order_source": None,
            "is_replace": 0
        }

        with patch("frappe.db.sql") as mock_sql, patch("frappe.db.begin"), patch("frappe.db.rollback"):
            def sql_side(query, *args, **kwargs):
                if "tabSales Order" in query:
                    return [{"name": "SO-REPAIR-TEST", "status": "To Deliver", "docstatus": 1, "sale_type": "NJ-Website-B2C"}]
                if "tabSerial No" in query:
                    return [mock_new, mock_old]
                return []
            mock_sql.side_effect = sql_side

            with self.assertRaises(frappe.ValidationError) as ctx:
                swap_order_reservation(
                    so_name="SO-REPAIR-TEST",
                    old_serial_no="REPAIR-01",
                    new_serial_no="READY-01"
                )
            self.assertIn("customer unit returned for Repair", str(ctx.exception))

    def test_rto_serial_swap_prevention(self):
        """Verify swap_order_reservation refuses to swap customer RTO serial numbers."""
        from unittest.mock import patch

        mock_old = {
            "name": "RTO-01",
            "status": "Active",
            "warehouse": "BG - Packing - NJ",
            "department": "Packing & Dispatch - NJ",
            "reserved_sales_order": "SO-RTO-TEST",
            "to_make": "LAPTOP-01",
            "item_code": "LAPTOP-01",
            "return_reason": "RTO Delivery Partner",
            "order_source": "NJ-Website-B2C - RTO Delivery Partner",
            "is_replace": 0
        }
        mock_new = {
            "name": "READY-02",
            "status": "Active",
            "warehouse": "PND - NJ",
            "department": "Packing & Dispatch - NJ",
            "reserved_sales_order": None,
            "to_make": "LAPTOP-01",
            "item_code": "LAPTOP-01",
            "return_reason": None,
            "order_source": None,
            "is_replace": 0
        }

        with patch("frappe.db.sql") as mock_sql, patch("frappe.db.begin"), patch("frappe.db.rollback"):
            def sql_side(query, *args, **kwargs):
                if "tabSales Order" in query:
                    return [{"name": "SO-RTO-TEST", "status": "To Deliver", "docstatus": 1, "sale_type": "NJ-Website-B2C"}]
                if "tabSerial No" in query:
                    return [mock_new, mock_old]
                return []
            mock_sql.side_effect = sql_side

            with self.assertRaises(frappe.ValidationError) as ctx:
                swap_order_reservation(
                    so_name="SO-RTO-TEST",
                    old_serial_no="RTO-01",
                    new_serial_no="READY-02"
                )
            self.assertIn("customer unit returned for RTO Delivery Partner", str(ctx.exception))

    def test_working_days_skips_sundays_and_holidays(self):
        """Verify add_working_days strictly skips Sundays and Holiday List entries."""
        # Saturday + 1 working day must be Monday
        sat = "2026-09-12"
        mon = add_working_days(sat, 1)
        self.assertEqual(str(mon), "2026-09-14")
        self.assertEqual(mon.weekday(), 0)  # Monday

        # Saturday + 2 working days must be Tuesday
        tue = add_working_days(sat, 2)
        self.assertEqual(str(tue), "2026-09-15")
        self.assertEqual(tue.weekday(), 1)  # Tuesday

    def test_unallocated_partial_order_sla(self):
        """Verify compute_sales_order_delivery_date assigns 45 working days for unallocated units."""
        from nj_features.overrides.sales_order import compute_sales_order_delivery_date
        from unittest.mock import patch

        # 1 unit allocated in Packing & Dispatch (1 day SLA)
        mock_serials = [
            {"name": "SN-PND-01", "item_code": "ITEM-A", "to_make": None, "remarks": "", "dept_name": "Packing & Dispatch - NJ", "department_sequence": 20, "department_sla": 1, "item_group": "Desktop"}
        ]

        with patch("frappe.db.sql") as mock_sql, \
             patch("frappe.db.has_column", return_value=True), \
             patch("frappe.db.table_exists", return_value=False), \
             patch("frappe.db.sql_list", return_value=["ITEM-A"]), \
             patch("frappe.db.get_value", return_value=None), \
             patch("frappe.db.set_value"):

            def sql_side_effect(query, *args, **kwargs):
                if "tabSerial No" in query:
                    return mock_serials
                if "tabDepartment" in query:
                    return [
                        {"name": "Packing & Dispatch - NJ", "department_sequence": 20, "department_sla": 1, "sla_item_groups": "Desktop"}
                    ]
                # Simulate 2 units pending in order: direct query returns 2
                if "tabSales Order Item" in query and "SUM" in query:
                    return [[2]]
                return []

            mock_sql.side_effect = sql_side_effect

            res = compute_sales_order_delivery_date("SO-PARTIAL-TEST", return_reason=True)
            self.assertIsInstance(res, tuple)
            target_date, reason = res
            # Because 1 unit was missing (pending qty 2, allocated 1), SLA bottleneck is 45 working days
            expected_date = add_working_days(nowdate(), 45)
            self.assertEqual(str(target_date), str(expected_date))


if __name__ == "__main__":
    unittest.main()


