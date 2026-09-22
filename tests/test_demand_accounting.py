"""Unit tests for Stage 2 demand accounting logic and Hamilton's Largest Remainder distribution.

Verifies:
1. Bundle component multiplier: 1 bundle with 2 component units and 1 unit delivered yields 1 pending unit.
2. Repeated order lines with partial delivery: 2 lines of 1 unit each with 1 unit delivered yields 1 pending unit (not 0).
3. Multi-line order reservation deduplication: 2 lines of 2 units (total 4) and 1 serial reserved yields 3 unreserved demand (not 2).
4. Hamilton's Largest Remainder distribution (distribute_proportional_deduction):
   - S-Dell 7320(PIR) case: 2 siblings with 1 unit each and 1 unit shortfall -> removes exactly 1 unit (fixes double-subtraction).
   - 3 siblings with 1 unit each, 1 shortfall -> removes exactly 1 unit (fixes under-subtraction where round(0.333)=0).
   - 3 siblings with 1 unit each, 2 shortfall -> removes exactly 2 units (fixes over-subtraction where round(0.667)=1 each).
   - Shortfall exceeding total stock (R > S) -> update_qty2 driven to 0, remaining recorded in pending_allocation_qty.
   - Zero shortfall and zero stock edge cases.
   - Conservation invariant: sum(proportional_remove_qty) == remove_parent_qty.

Run:
    PYTHONPATH=. /home/upgrade/frappe-bench/env/bin/python tests/test_demand_accounting.py -v
"""
import unittest
import unittest.mock

# Mock frappe logger before importing so_quantity_check to allow standalone test execution
import frappe
frappe.logger = unittest.mock.MagicMock()

from nj_features.nj_features.doctype.so_quantity_check.so_quantity_check import (
    distribute_proportional_deduction,
)


def calculate_demand_and_unallocated_pending(order_lines, delivery_lines, reserved_serials):
    """Pure implementation of the Stage 2 demand calculation algorithm.

    order_lines: list of dicts with:
        sales_order, so_detail, item_code, is_bundle, component_item_code, qty, bundle_multiplier
    delivery_lines: list of dicts with:
        so_detail, qty
    reserved_serials: list of dicts with:
        reserved_sales_order, item_code (or to_make)
    """
    # 1. Delivery aggregation at line level (so_detail)
    deliv_map = {}
    for d in delivery_lines:
        deliv_map[d["so_detail"]] = deliv_map.get(d["so_detail"], 0.0) + float(d["qty"])

    # 2. Line-level pending demand calculation
    # (sales_order, component_item_code) -> total_pending_qty
    order_pending = {}
    for line in order_lines:
        so = line["sales_order"]
        comp = line["component_item_code"]
        ordered_units = float(line["qty"]) * float(line.get("bundle_multiplier", 1.0))
        delivered_bundle_or_item = deliv_map.get(line["so_detail"], 0.0)
        delivered_units = delivered_bundle_or_item * float(line.get("bundle_multiplier", 1.0))
        pending_units = max(0.0, ordered_units - delivered_units)

        key = (so, comp)
        order_pending[key] = order_pending.get(key, 0.0) + pending_units

    # 3. Active reservation aggregation per (reserved_sales_order, component_item)
    alloc_map = {}
    for s in reserved_serials:
        key = (s["reserved_sales_order"], s.get("to_make") or s["item_code"])
        alloc_map[key] = alloc_map.get(key, 0) + 1

    # 4. Deduct qualifying reservations ONCE per (sales_order, component_item)
    pending_qty_by_item = {}
    for (so, comp), raw_pending in order_pending.items():
        allocated = alloc_map.get((so, comp), 0)
        unallocated = max(0.0, raw_pending - allocated)
        if unallocated > 0:
            pending_qty_by_item[comp] = pending_qty_by_item.get(comp, 0.0) + unallocated

    return pending_qty_by_item


class TestDemandAccounting(unittest.TestCase):
    def test_bundle_component_multiplier(self):
        """1 bundle with 2 component units per bundle; 0.5 bundle (1 component unit) delivered -> 1 unit pending."""
        order_lines = [
            {
                "sales_order": "SO-001",
                "so_detail": "line-1",
                "item_code": "BUNDLE-LAPTOP-PACK",
                "is_bundle": True,
                "component_item_code": "LAPTOP-STOCK-ITEM",
                "qty": 1.0,
                "bundle_multiplier": 2.0,
            }
        ]
        # 0.5 bundle delivered = 1 component unit delivered
        delivery_lines = [{"so_detail": "line-1", "qty": 0.5}]
        reserved_serials = []

        result = calculate_demand_and_unallocated_pending(order_lines, delivery_lines, reserved_serials)
        self.assertEqual(result.get("LAPTOP-STOCK-ITEM"), 1.0)

    def test_repeated_order_lines_partial_delivery(self):
        """2 order lines of 1 unit each (total 2). Delivery note delivers against Line 1 only.

        Under line-level matching, pending must be 1.0 (not 0.0 from double-subtraction).
        """
        order_lines = [
            {
                "sales_order": "SO-002",
                "so_detail": "line-1",
                "item_code": "LAPTOP-STOCK-ITEM",
                "is_bundle": False,
                "component_item_code": "LAPTOP-STOCK-ITEM",
                "qty": 1.0,
                "bundle_multiplier": 1.0,
            },
            {
                "sales_order": "SO-002",
                "so_detail": "line-2",
                "item_code": "LAPTOP-STOCK-ITEM",
                "is_bundle": False,
                "component_item_code": "LAPTOP-STOCK-ITEM",
                "qty": 1.0,
                "bundle_multiplier": 1.0,
            },
        ]
        # Delivery Note specifies line-1
        delivery_lines = [{"so_detail": "line-1", "qty": 1.0}]
        reserved_serials = []

        result = calculate_demand_and_unallocated_pending(order_lines, delivery_lines, reserved_serials)
        self.assertEqual(result.get("LAPTOP-STOCK-ITEM"), 1.0)

    def test_multiline_order_reservation_deduplication(self):
        """2 lines of 2 units each (total 4 units). 1 serial reserved.

        Reservation must be deducted ONCE per (sales_order, component_item), leaving 3.0 unallocated (not 2.0).
        """
        order_lines = [
            {
                "sales_order": "SO-003",
                "so_detail": "line-1",
                "item_code": "DESKTOP-STOCK-ITEM",
                "is_bundle": False,
                "component_item_code": "DESKTOP-STOCK-ITEM",
                "qty": 2.0,
                "bundle_multiplier": 1.0,
            },
            {
                "sales_order": "SO-003",
                "so_detail": "line-2",
                "item_code": "DESKTOP-STOCK-ITEM",
                "is_bundle": False,
                "component_item_code": "DESKTOP-STOCK-ITEM",
                "qty": 2.0,
                "bundle_multiplier": 1.0,
            },
        ]
        delivery_lines = []
        reserved_serials = [
            {"reserved_sales_order": "SO-003", "item_code": "DESKTOP-STOCK-ITEM", "to_make": None}
        ]

        result = calculate_demand_and_unallocated_pending(order_lines, delivery_lines, reserved_serials)
        self.assertEqual(result.get("DESKTOP-STOCK-ITEM"), 3.0)


class TestProportionalDeduction(unittest.TestCase):
    def test_sdell_7320_pir_no_double_subtraction(self):
        """S-Dell 7320(PIR) test case:
        2 siblings with update_qty = 1 each (total 2).
        Parent has a 1-unit shortfall (remove_parent_qty = 1).
        
        Old ROUND() method:
            Row 1: ROUND((1/2) * 1) = ROUND(0.5) = 1 -> update_qty2 = 0
            Row 2: ROUND((1/2) * 1) = ROUND(0.5) = 1 -> update_qty2 = 0
            Total removed: 2 units for a 1-unit shortfall (DOUBLE-SUBTRACTION BUG)!
        
        Largest-Remainder (Hamilton's) method:
            Row 1: base = 0, rem = 0.5 -> gets surplus 1 -> remove = 1, update_qty2 = 0
            Row 2: base = 0, rem = 0.5 -> remove = 0, update_qty2 = 1
            Total removed: exactly 1 unit!
        """
        rows = [
            {"name": "soqc-row-1", "item_code": "S-Dell 7320(PIR)-16G", "update_qty": "1", "pending_allocation_qty": "0"},
            {"name": "soqc-row-2", "item_code": "S-Dell 7320(PIR)-32G", "update_qty": "1", "pending_allocation_qty": "0"},
        ]
        result = distribute_proportional_deduction(rows, total_remove_qty=1)

        total_removed = sum(r["proportional_remove_qty"] for r in result)
        total_remaining = sum(r["update_qty2"] for r in result)

        self.assertEqual(total_removed, 1, "Must remove exactly 1 unit for 1 unit parent shortfall")
        self.assertEqual(total_remaining, 1, "Exactly 1 unit must remain across siblings")
        self.assertEqual(result[0]["proportional_remove_qty"], 1)
        self.assertEqual(result[0]["update_qty2"], 0)
        self.assertEqual(result[1]["proportional_remove_qty"], 0)
        self.assertEqual(result[1]["update_qty2"], 1)

    def test_three_siblings_one_shortfall(self):
        """3 siblings with 1 unit each (total 3). remove_parent_qty = 1.
        Old behavior: ROUND(0.333) = 0 for all three -> 0 removed (under-deduction).
        Hamilton: exactly 1 removed.
        """
        rows = [
            {"name": "r1", "item_code": "ITEM-A", "update_qty": 1, "pending_allocation_qty": 0},
            {"name": "r2", "item_code": "ITEM-B", "update_qty": 1, "pending_allocation_qty": 0},
            {"name": "r3", "item_code": "ITEM-C", "update_qty": 1, "pending_allocation_qty": 0},
        ]
        result = distribute_proportional_deduction(rows, total_remove_qty=1)
        total_removed = sum(r["proportional_remove_qty"] for r in result)
        self.assertEqual(total_removed, 1)

    def test_three_siblings_two_shortfall(self):
        """3 siblings with 1 unit each (total 3). remove_parent_qty = 2.
        Old behavior: ROUND(0.667) = 1 for all three -> 3 removed (over-deduction).
        Hamilton: exactly 2 removed.
        """
        rows = [
            {"name": "r1", "item_code": "ITEM-A", "update_qty": 1, "pending_allocation_qty": 0},
            {"name": "r2", "item_code": "ITEM-B", "update_qty": 1, "pending_allocation_qty": 0},
            {"name": "r3", "item_code": "ITEM-C", "update_qty": 1, "pending_allocation_qty": 0},
        ]
        result = distribute_proportional_deduction(rows, total_remove_qty=2)
        total_removed = sum(r["proportional_remove_qty"] for r in result)
        self.assertEqual(total_removed, 2)

    def test_shortfall_greater_than_total_stock(self):
        """Shortfall (5) exceeds total available stock (2 across 2 siblings).
        Stock must be driven to 0 (update_qty2 = 0) and unfulfilled backlog recorded
        as negative pending_allocation_qty.
        """
        rows = [
            {"name": "r1", "item_code": "ITEM-A", "update_qty": 1, "pending_allocation_qty": 0},
            {"name": "r2", "item_code": "ITEM-B", "update_qty": 1, "pending_allocation_qty": 0},
        ]
        result = distribute_proportional_deduction(rows, total_remove_qty=5)

        for r in result:
            self.assertEqual(r["update_qty2"], 0)
            self.assertLess(r["pending_allocation_qty"], 0)

        total_alloc = sum(r["proportional_remove_qty"] for r in result)
        self.assertEqual(total_alloc, 5)

    def test_zero_shortfall(self):
        """remove_parent_qty = 0: All update_qty2 remain unchanged, proportional_remove_qty = 0."""
        rows = [
            {"name": "r1", "item_code": "ITEM-A", "update_qty": 5, "pending_allocation_qty": 0},
            {"name": "r2", "item_code": "ITEM-B", "update_qty": 3, "pending_allocation_qty": 0},
        ]
        result = distribute_proportional_deduction(rows, total_remove_qty=0)
        self.assertEqual(result[0]["proportional_remove_qty"], 0)
        self.assertEqual(result[0]["update_qty2"], 5)
        self.assertEqual(result[1]["proportional_remove_qty"], 0)
        self.assertEqual(result[1]["update_qty2"], 3)

    def test_zero_update_qty(self):
        """All update_qty = 0: Nothing available, update_qty2 = 0, proportional_remove_qty = 0."""
        rows = [
            {"name": "r1", "item_code": "ITEM-A", "update_qty": 0, "pending_allocation_qty": 0},
            {"name": "r2", "item_code": "ITEM-B", "update_qty": 0, "pending_allocation_qty": 0},
        ]
        result = distribute_proportional_deduction(rows, total_remove_qty=2)
        self.assertEqual(result[0]["proportional_remove_qty"], 0)
        self.assertEqual(result[0]["update_qty2"], 0)
        self.assertEqual(result[1]["proportional_remove_qty"], 0)
        self.assertEqual(result[1]["update_qty2"], 0)

    def test_unequal_remainders_priority(self):
        """Verify largest remainder takes priority:
        Row A: update_qty = 10 (share = 1.5 -> base 1, rem 0.5)
        Row B: update_qty = 5  (share = 0.75 -> base 0, rem 0.75)
        Row C: update_qty = 5  (share = 0.75 -> base 0, rem 0.75)
        Total stock = 20, remove_qty = 3.
        Surplus = 3 - (1 + 0 + 0) = 2.
        Rows B and C have larger remainders (0.75 > 0.5) so each gets +1 surplus.
        Final: A=1, B=1, C=1. Total removed = 3.
        """
        rows = [
            {"name": "rA", "item_code": "ITEM-A", "update_qty": 10, "pending_allocation_qty": 0},
            {"name": "rB", "item_code": "ITEM-B", "update_qty": 5, "pending_allocation_qty": 0},
            {"name": "rC", "item_code": "ITEM-C", "update_qty": 5, "pending_allocation_qty": 0},
        ]
        result = distribute_proportional_deduction(rows, total_remove_qty=3)
        alloc_map = {r["name"]: r["proportional_remove_qty"] for r in result}
        self.assertEqual(alloc_map["rA"], 1)
        self.assertEqual(alloc_map["rB"], 1)
        self.assertEqual(alloc_map["rC"], 1)
        self.assertEqual(sum(alloc_map.values()), 3)


if __name__ == "__main__":
    unittest.main()
