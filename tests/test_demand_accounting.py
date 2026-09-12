"""Unit tests for Stage 2 demand accounting logic.

Verifies:
1. Bundle component multiplier: 1 bundle with 2 component units and 1 unit delivered yields 1 pending unit.
2. Repeated order lines with partial delivery: 2 lines of 1 unit each with 1 unit delivered yields 1 pending unit (not 0).
3. Multi-line order reservation deduplication: 2 lines of 2 units (total 4) and 1 serial reserved yields 3 unreserved demand (not 2).

Run:
    python -m unittest tests/test_demand_accounting.py -v
"""
import unittest


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


if __name__ == "__main__":
    unittest.main()

