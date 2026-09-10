"""Run-scoped parts reservations and durable production planning evidence.

Only existing item variants are considered; no Items, MRs or stock entries are
created or changed here. Frappe imports are local so calculation tests need no DB.
"""
import frappe
import copy
import itertools
import json
import re
import uuid
from collections import defaultdict, deque
from datetime import datetime

EPSILON = 0.000001

STORES_STOCK_EXCLUDED_WAREHOUSES = {
    "L1 Store - NJ",
    "Stores - NJ",
    "L1. Desktop Team - NJ",
    "L2-Stores Not Found - NJ",
    "WIP - NJ",
    "First Stores - NJ",
    "L2 Store - NJ",
    "BG - WIP - NJ",
    "BG -  L1 Store - NJ",
    "Procurement - NJ",
    "WK-Santosh Kumar-EMP01180",
    "WK-Amit Kumar Sah-EMP02051 - NJ",
}

MR_EXCLUDED_ITEM_GROUPS = {
    "CAMERA LENS",
    "CONSUMABLE",
    "TRACK BALL CAP",
    "DESKTOP SPARE PARTS",
    "DESKTOP SMPS",
    "DESKTOP PROCESSORS",
    "SMPS",
    "LAPTOP RAM",
    "LAPTOP STORAGE",
    "LAPTOP HARDDISK",
}
MR_EXCLUDED_ITEM_GROUP_CONTAINS = ("BUSH", "DESKT")


def number(value):
    return float(value or 0)


def normalized(value):
    return " ".join(str(value or "").strip().upper().split())


def grade_a_item_code(value):
    """Convert Item Wizard default component code from UNKNOWN to GRADE A."""
    return re.sub(r"(?i)\bUNKNOWN\b", "GRADE A", str(value or "").strip())


def attribute_key(attribute, value):
    text = normalized(value)
    if attribute in ("RAM Capacity", "Storage Capacity"):
        match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(GB|TB)(?:\s+(?:SSD|HDD))?", text)
        if match:
            return "%g %s" % (float(match.group(1)), match.group(2))
    return text


def pending_reason(row):
    if row.get("allocation_exclusion_reason"):
        return row.get("allocation_exclusion_reason")
    if int(row.get("mr_docstatus") or 0) != 1:
        return "Material Request is not submitted"
    if row.get("mr_status") != "Pending":
        return "Material Request status is not Pending"
    if row.get("mr_post_order_status") == "Completed":
        return "Material Request is completed"
    if int(row.get("row_docstatus") or 0) != 1:
        return "Material Request item is not submitted"
    if (row.get("row_post_order_status") or "") not in ("", "Not Completed"):
        return "Material Request item is completed or not pending"
    if row.get("item_group") is None:
        return "Material Request item has no item group"
    item_group_name = normalized(row.get("item_group"))
    if item_group_name in MR_EXCLUDED_ITEM_GROUPS or any(token in item_group_name for token in MR_EXCLUDED_ITEM_GROUP_CONTAINS):
        return "Material Request item group excluded by Google Sheet allocation rules"
    if not row.get("item_code"):
        return "Material Request item has no item code"
    if number(row.get("stock_qty")) <= 0:
        return "Material Request item has no positive stock quantity"
    return None


def build_combinations(wizard_attributes, requested_item, serial_attributes, group_settings, catalog):
    """Cartesian product, resolved to existing codes using Item attributes.

    Item attributes resolve real naming/abbreviations instead of inventing Item
    names. Only codes with the Item Group's required S- prefix are accepted.
    Missing wizard attributes retain the requested variant value. RAM/storage
    capacity always comes from the laptop's Item, never from its component rows.
    """
    info = {"wizard_attributes": copy.deepcopy(wizard_attributes),
            "prefix": "S-" if group_settings.get("is_serialised") else "",
            "retained_requested_attributes": {}, "capacity_source": None,
            "combinations": [], "eligible_item_codes": [], "reason": None}
    if not wizard_attributes or not any(k != "Grade" for k in wizard_attributes):
        info["reason"] = "No combination attributes for this item group in the Item Wizard"
        return info
    options = {}
    for attribute, values in wizard_attributes.items():
        if attribute == "Grade":
            continue
        unique = {}
        for value in values:
            if normalized(value):
                unique.setdefault(attribute_key(attribute, value), value)
        if unique:
            options[attribute] = list(unique.values())
    for attribute, value in requested_item.get("attributes", {}).items():
        if attribute != "Grade" and attribute not in options:
            options[attribute] = [value]
            info["retained_requested_attributes"][attribute] = value
    group = normalized(requested_item.get("item_group"))
    capacity_attribute = {"LAPTOP RAM": "RAM Capacity", "LAPTOP STORAGE": "Storage Capacity"}.get(group)
    if capacity_attribute:
        capacity = attribute_key(capacity_attribute, serial_attributes.get(capacity_attribute))
        if not re.fullmatch(r"\d+(?:\.\d+)? (?:GB|TB)", capacity):
            info["reason"] = "Serial Item has no usable %s" % capacity_attribute
            return info
        options[capacity_attribute] = [capacity]
        info["retained_requested_attributes"].pop(capacity_attribute, None)
        info["capacity_source"] = {"attribute": capacity_attribute, "serial_item_value": serial_attributes.get(capacity_attribute), "capacity": capacity}
    options["Grade"] = ["Grade A"]
    info["attribute_options_used"] = options
    attributes = list(options)
    by_key = defaultdict(list)
    for item in catalog:
        values = item.get("attributes", {})
        key = tuple(attribute_key(a, values.get(a)) for a in attributes)
        by_key[key].append(item)
    for values in itertools.product(*(options[a] for a in attributes)):
        combination = dict(zip(attributes, values))
        key = tuple(attribute_key(a, v) for a, v in zip(attributes, values))
        candidates = []
        for item in sorted(by_key.get(key, []), key=lambda i: i["item_code"]):
            reason = item.get("ineligible_reason")
            extra_attributes = {a: v for a, v in item.get("attributes", {}).items()
                                if a not in options and normalized(v)}
            if extra_attributes:
                reason = "Additional attributes are not specified by the wizard or requested part: " + ", ".join(sorted(extra_attributes))
            if bool(item["item_code"].startswith("S-")) != bool(group_settings.get("is_serialised")):
                reason = "Item code prefix differs from Item Group is_serialised"
            if group_settings.get("model_specific") and item.get("variant_of") != requested_item.get("variant_of"):
                reason = "Different model-specific template"
            candidates.append({"item_code": item["item_code"], "eligible": not bool(reason), "exclusion_reason": reason})
            if not reason and item["item_code"] not in info["eligible_item_codes"]:
                info["eligible_item_codes"].append(item["item_code"])
        info["combinations"].append({"attributes": combination, "matching_items": candidates,
                                     "reason": None if candidates else "No existing Item matches this combination"})
    info["combination_count"] = len(info["combinations"])
    if not info["eligible_item_codes"]:
        info["reason"] = "No eligible existing Grade A items match the combinations"
    return info


def distribute_alternatives(demands, choices, available):
    """Maximum flow avoids one flexible requirement starving a restricted one."""
    edges = defaultdict(dict)
    original = {}
    source, sink = ("source",), ("sink",)
    def edge(a, b, capacity):
        edges[a][b] = capacity
        edges[b][a] = 0.0
        original[(a, b)] = capacity
    for requirement, qty in demands.items():
        node = ("requirement", requirement)
        edge(source, node, qty)
        for item in choices.get(requirement, []):
            if available.get(item, 0) > EPSILON:
                edge(node, ("stock", item), qty)
    for item, qty in available.items():
        if qty > EPSILON:
            edge(("stock", item), sink, qty)
    while True:
        parents = {source: None}
        queue = deque([source])
        while queue and sink not in parents:
            current = queue.popleft()
            for target, capacity in edges[current].items():
                if capacity > EPSILON and target not in parents:
                    parents[target] = current
                    queue.append(target)
        if sink not in parents:
            break
        amount, current = float("inf"), sink
        while parents[current] is not None:
            previous = parents[current]
            amount = min(amount, edges[previous][current])
            current = previous
        current = sink
        while parents[current] is not None:
            previous = parents[current]
            edges[previous][current] -= amount
            edges[current][previous] += amount
            current = previous
    selected = defaultdict(dict)
    for (a, b), capacity in original.items():
        if a[0] == "requirement" and b[0] == "stock":
            used = capacity - edges[a][b]
            if used > EPSILON:
                selected[a[1]][b[1]] = used
    return dict(selected)


class AllocationEngine:
    def __init__(self, stock, planned=None):
        self.stock = stock
        self.planned = planned if planned is not None else {}
        self.successful = set()
        self.prior_reservations = defaultdict(list)
        self.sequence = 0

    def decide(self, serial_no, mr_rows, bag_rows, alternatives):
        self.sequence += 1
        event = {"sequence": self.sequence, "checked_at": datetime.now().isoformat(),
                 "result": None, "reason": None, "requirements": [], "reserved_items": {},
                 "included_mr_lines": [], "excluded_mr_lines": [], "bag_rows": copy.deepcopy(bag_rows)}
        if serial_no in self.successful:
            event.update(result="ALREADY_ALLOCATED", reason="Reused this run's successful reservation; no further deduction")
            return True, event
        required = defaultdict(float)
        for row in mr_rows:
            reason = pending_reason(row)
            entry = dict(row)
            entry["exclusion_reason"] = reason
            event["excluded_mr_lines" if reason else "included_mr_lines"].append(entry)
            if not reason:
                required[row["item_code"]] += number(row["stock_qty"])
        if not required:
            event.update(result="NO_PENDING_REQUIREMENTS", reason="No positive pending MR stock quantities to verify")
            return False, event
        # Google Sheet matching mode: do not reduce requirements using this serial's own Bag List.
        # Every pending MR quantity is checked against eligible Stores - NJ stock only.
        tentative = defaultdict(float)
        lines = {}
        deficits = {}
        choices = {}
        # Give every requirement first access to its exact item before fallback.
        for code, qty in required.items():
            bag_qty = 0
            needed = qty
            available = max(0, number(self.stock.get(code)) - number(self.planned.get(code)))
            exact_qty = min(needed, available)
            tentative[code] += exact_qty
            line = {"requested_item": code, "required_stock_qty": qty, "bag_qty_used": bag_qty,
                    "needed_from_stores": needed, "initial_exact_stock": number(self.stock.get(code)),
                    "earlier_exact_reservations": number(self.planned.get(code)),
                    "exact_available_before": available, "exact_tentative_qty": exact_qty,
                    "combination_search": None, "candidate_checks": [], "selected_items": {}, "shortage": 0}
            if exact_qty > EPSILON:
                line["selected_items"][code] = exact_qty
            lines[code] = line
            deficit = needed - exact_qty
            if deficit > EPSILON:
                info = copy.deepcopy(alternatives(code))
                line["combination_search"] = info
                choices[code] = [c for c in info.get("eligible_item_codes", []) if c != code]
                deficits[code] = deficit
        alternative_codes = sorted({c for values in choices.values() for c in values})
        free = {c: max(0, number(self.stock.get(c)) - number(self.planned.get(c)) - tentative[c]) for c in alternative_codes}
        selected = distribute_alternatives(deficits, choices, free)
        for code, deficit in deficits.items():
            for actual, qty in selected.get(code, {}).items():
                lines[code]["selected_items"][actual] = qty
                tentative[actual] += qty
            lines[code]["shortage"] = max(0, deficit - sum(selected.get(code, {}).values()))
        success = not any(line["shortage"] > EPSILON for line in lines.values())
        for code, line in lines.items():
            checked_codes = [code] + choices.get(code, [])
            for actual in checked_codes:
                before = number(self.stock.get(actual)) - number(self.planned.get(actual))
                qty = line["selected_items"].get(actual, 0)
                line["candidate_checks"].append({
                    "item_code": actual, "initial_stock": number(self.stock.get(actual)),
                    "earlier_reserved_qty": number(self.planned.get(actual)),
                    "earlier_reservations": copy.deepcopy(self.prior_reservations.get(actual, [])),
                    "available_before_serial": before, "tentative_qty_for_requirement": qty,
                    "reserved_qty_for_requirement": qty if success else 0,
                    "available_after_serial": before - (tentative[actual] if success else 0)})
            line["reserved_items"] = dict(line["selected_items"]) if success else {}
            line["reason"] = ("Requirement covered" if success else
                              "Insufficient stock" if line["shortage"] > EPSILON else
                              "Covered tentatively, but another requirement failed; nothing reserved")
            event["requirements"].append(line)
        if not success:
            event.update(result="INSUFFICIENT_STOCK", reason="At least one requirement could not be covered; no deductions committed")
            return False, event
        for code, qty in tentative.items():
            if qty > EPSILON:
                self.planned[code] = number(self.planned.get(code)) + qty
                self.prior_reservations[code].append({"serial_no": serial_no, "sequence": self.sequence, "quantity": qty})
                event["reserved_items"][code] = qty
        self.successful.add(serial_no)
        event.update(result="ALLOCATED", reason="All pending requirements covered by exact bag items and exact or wizard-supported Stores items")
        return True, event


class PartAllocationRun:
    def __init__(self, department_flags):
        import frappe
        self.run_id = uuid.uuid4().hex
        self.started_at = frappe.utils.now_datetime()
        self.department_flags = department_flags
        self.stock_snapshot = {"run_id": self.run_id, "captured_at": str(self.started_at), "warehouses": [], "items": {}}
        self.stock = self.build_stock() if any(department_flags.values()) else {}
        self.engine = AllocationEngine(self.stock)
        self.planned = self.engine.planned
        self.serials = {}
        self.mrs = defaultdict(list)
        self.bags = defaultdict(list)
        self.wizards = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        self.items = {}
        self.group_settings = {}
        self.catalogs = {}
        self.combination_cache = {}
        self.audits = {}

    def build_stock(self):
        import frappe
        all_store_warehouses = frappe.get_all("Warehouse", filters={"department": "Stores - NJ", "disabled": ["!=", 1]}, pluck="name")
        warehouses = [wh for wh in all_store_warehouses if wh not in STORES_STOCK_EXCLUDED_WAREHOUSES]
        self.stock_snapshot["excluded_warehouses"] = sorted(wh for wh in all_store_warehouses if wh in STORES_STOCK_EXCLUDED_WAREHOUSES)
        self.stock_snapshot["warehouses"] = sorted(warehouses)
        if not warehouses:
            return {}
        params = {"warehouses": tuple(warehouses)}
        serialized = frappe.db.sql("""
            SELECT sn.item_code, sn.warehouse, COUNT(*) AS eligible_qty,
                SUM(CASE WHEN bag.serial_no IS NOT NULL THEN 1 ELSE 0 END) AS bagged_qty
            FROM `tabSerial No` sn
            JOIN `tabItem` i ON i.name=sn.item_code AND IFNULL(i.has_serial_no,0)=1
            LEFT JOIN (
                SELECT DISTINCT serial_no FROM `tabBag List`
                WHERE is_available=1 AND serial_no IS NOT NULL AND serial_no!=''
            ) bag ON bag.serial_no=sn.name
            WHERE sn.warehouse IN %(warehouses)s
                AND (sn.status IS NULL OR sn.status NOT IN ('Delivered','Scrapped','Inactive'))
            GROUP BY sn.item_code, sn.warehouse
        """, params, as_dict=True)
        bins = frappe.db.sql("""
            SELECT b.item_code, b.warehouse, SUM(b.actual_qty) AS actual_qty
            FROM `tabBin` b JOIN `tabItem` i ON i.name=b.item_code
            WHERE b.warehouse IN %(warehouses)s AND IFNULL(i.has_serial_no,0)=0
                AND b.actual_qty > 0
            GROUP BY b.item_code,b.warehouse
        """, params, as_dict=True)
        bagged = frappe.db.sql("""
            SELECT bl.item AS item_code, SUM(IFNULL(bl.quantity,1)) AS bagged_qty
            FROM `tabBag List` bl JOIN `tabItem` i ON i.name=bl.item
            WHERE (bl.serial_no IS NULL OR bl.serial_no='') AND bl.is_available=1
                AND IFNULL(i.has_serial_no,0)=0 GROUP BY bl.item
        """, as_dict=True)
        nonserial_bagged = {r.item_code: number(r.bagged_qty) for r in bagged}
        stock = defaultdict(float)
        details = self.stock_snapshot["items"]
        serial_codes = set()
        for r in serialized:
            serial_codes.add(r.item_code)
            # Do not deduct global Bag List rows from the Stores stock snapshot.
            # Priority-run virtual reservations below still prevent over-allocation
            # inside the same production plan run.
            qty = number(r.eligible_qty)
            stock[r.item_code] += qty
            d = details.setdefault(r.item_code, {"serialized": True, "warehouses": [], "eligible_qty": 0, "bagged_qty": 0})
            d["warehouses"].append({"warehouse": r.warehouse, "eligible_qty": number(r.eligible_qty), "bagged_qty": number(r.bagged_qty), "available_qty": qty})
            d["eligible_qty"] += number(r.eligible_qty)
            d["bagged_qty"] += number(r.bagged_qty)
        for r in bins:
            if r.item_code in serial_codes:
                continue
            stock[r.item_code] += number(r.actual_qty)
            d = details.setdefault(r.item_code, {"serialized": False, "warehouses": [], "eligible_qty": 0, "bagged_qty": nonserial_bagged.get(r.item_code, 0)})
            d["eligible_qty"] += number(r.actual_qty)
            d["warehouses"].append({"warehouse": r.warehouse, "actual_qty": number(r.actual_qty)})
        for code in stock:
            details[code]["initial_available_qty"] = stock[code]
        self.stock_snapshot["warehouse_scope"] = "Stores - NJ enabled warehouses minus Google Sheet exclusion list"
        self.stock_snapshot["nonserial_qty_scope"] = "Only positive Bin actual_qty rows are counted"
        self.stock_snapshot["bag_exclusion_scope"] = "Skipped global Bag List deduction from pooled Stores quantity"
        return dict(stock)

    def load_items(self, item_codes):
        import frappe
        missing = sorted(set(item_codes) - set(self.items) - {None, ""})
        for offset in range(0, len(missing), 500):
            batch = missing[offset:offset+500]
            for row in frappe.get_all("Item", filters={"name": ["in", batch]}, fields=["name", "item_group", "variant_of", "disabled", "has_variants", "end_of_life"]):
                self.items[row.name] = dict(row, item_code=row.name, attributes={})
            for row in frappe.get_all("Item Variant Attribute", filters={"parent": ["in", batch]}, fields=["parent", "attribute", "attribute_value"]):
                if row.parent in self.items:
                    self.items[row.parent]["attributes"][row.attribute] = row.attribute_value

    def load_inputs(self, serial_nos):
        import frappe
        serial_nos = sorted(set(serial_nos))
        if serial_nos:
            batch = serial_nos
            for row in frappe.get_all("Serial No", filters={"name": ["in", batch]}, fields=["name", "item_code", "item_wizard", "warehouse"]):
                self.serials[row.name] = dict(row)

            wizard_names_for_defaults = sorted({s.get("item_wizard") for s in self.serials.values()} - {None, ""})
            default_items_by_wizard_group = defaultdict(lambda: defaultdict(list))
            for offset in range(0, len(wizard_names_for_defaults), 500):
                batch_wizards = wizard_names_for_defaults[offset:offset+500]
                if not batch_wizards:
                    continue
                for row in frappe.db.sql("""
                    SELECT
                        parent AS item_wizard,
                        component_type AS item_group,
                        default_item_code,
                        idx
                    FROM `tabComponent`
                    WHERE parent IN %(wizards)s
                      AND IFNULL(component_type, '') != ''
                      AND IFNULL(default_item_code, '') != ''
                    ORDER BY parent, idx ASC
                """, {"wizards": tuple(batch_wizards)}, as_dict=True):
                    item_group_key = normalized(row.item_group)
                    if item_group_key:
                        default_items_by_wizard_group[row.item_wizard][item_group_key].append({
                            "item_group": row.item_group,
                            "default_item_code": row.default_item_code,
                            "grade_a_item_code": grade_a_item_code(row.default_item_code),
                        })

            rows = frappe.db.sql("""
                SELECT MRI.name AS mr_line, MRI.parent AS material_request,
                    MRI.serial_no, MRI.item_code, MRI.item_group, MRI.against_item_group,
                    MRI.qty AS mr_qty, MRI.stock_qty, MRI.uom, MRI.stock_uom, MRI.conversion_factor,
                    MR.docstatus AS mr_docstatus, MR.status AS mr_status,
                    MRI.docstatus AS row_docstatus, MRI.post_order_status AS row_post_order_status,
                    MR.post_order_status AS mr_post_order_status, MRI.modified
                FROM `tabMaterial Request Item` MRI JOIN `tabMaterial Request` MR ON MR.name=MRI.parent
                WHERE MRI.serial_no IN %(serials)s ORDER BY MRI.modified DESC, MRI.name
            """, {"serials": tuple(batch)}, as_dict=True)
            for row in rows:
                entry = dict(row)
                effective_item_group = row.item_group or row.against_item_group
                effective_stock_qty = number(row.stock_qty) or number(row.mr_qty)
                entry["item_group"] = effective_item_group
                entry["stock_qty"] = effective_stock_qty
                entry["effective_item_group_source"] = "item_group" if row.item_group else "against_item_group"
                entry["effective_qty_source"] = "stock_qty" if number(row.stock_qty) else "qty"
                serial = self.serials.get(row.serial_no) or {}
                wizard = serial.get("item_wizard")
                component_defaults = (default_items_by_wizard_group.get(wizard) or {}).get(normalized(effective_item_group)) or []
                component_default = component_defaults[0] if component_defaults else None
                entry["mr_item_code"] = row.item_code
                entry["requirement_source"] = "Material Request Item"
                if component_default:
                    entry["item_code"] = component_default.get("grade_a_item_code")
                    entry["wizard_default_item_code"] = component_default.get("default_item_code")
                    entry["wizard_component_item_group"] = component_default.get("item_group")
                    entry["requirement_item_replaced_from_mr"] = 1
                    entry["requirement_match_rule"] = "MR item group matched Item Wizard Component group; stock item uses Component default item code converted to Grade A"
                else:
                    entry["requirement_item_replaced_from_mr"] = 0
                    entry["wizard_component_candidates"] = []
                    entry["allocation_exclusion_reason"] = "Material Request item group does not match any Item Wizard Component group"
                self.mrs[row.serial_no].append(entry)

            for row in frappe.get_all("Bag List", filters={"parent": ["in", batch]}, fields=["name", "parent", "item", "item_group", "serial_no", "quantity", "is_available"]):
                self.bags[row.parent].append(dict(row))
        self.load_items([s["item_code"] for s in self.serials.values()] + [r["item_code"] for rows in self.mrs.values() for r in rows])
        wizard_names = sorted({s.get("item_wizard") for s in self.serials.values()} - {None, ""})
        for offset in range(0, len(wizard_names), 500):
            for row in frappe.get_all("Items Attribute", filters={"parent": ["in", wizard_names[offset:offset+500]]}, fields=["parent", "item_group", "item_attribute", "attribute_value"], order_by="idx asc"):
                values = self.wizards[row.parent][row.item_group][row.item_attribute]
                if row.attribute_value not in values:
                    values.append(row.attribute_value)
        groups = {r.get("item_group") for rows in self.mrs.values() for r in rows} - {None, ""}
        if groups:
            self.group_settings = {r.name: dict(r) for r in frappe.get_all("Item Group", filters={"name": ["in", sorted(groups)]}, fields=["name", "is_serialised", "model_specific"])}

    def catalog(self, group):
        import frappe
        if group not in self.catalogs:
            codes = frappe.get_all("Item", filters={"item_group": group, "has_variants": 0}, pluck="name")
            self.load_items(codes)
            items = []
            today = frappe.utils.getdate()
            for code in codes:
                item = self.items[code]
                reason = None
                if item.get("disabled"):
                    reason = "Item is disabled"
                elif item.get("end_of_life") and frappe.utils.getdate(item["end_of_life"]) <= today:
                    reason = "Item reached end of life"
                items.append(dict(item, ineligible_reason=reason))
            self.catalogs[group] = items
        return self.catalogs[group]

    def alternatives(self, serial_no, code):
        serial = self.serials.get(serial_no, {})
        requested = self.items.get(code, {})
        group = requested.get("item_group")
        wizard = serial.get("item_wizard")
        key = (wizard, serial.get("item_code"), code)
        if key not in self.combination_cache:
            if not wizard or not group:
                return {"reason": "Serial Item Wizard or requested Item is missing", "combinations": [], "eligible_item_codes": []}
            result = build_combinations(self.wizards.get(wizard, {}).get(group, {}), requested,
                self.items.get(serial.get("item_code"), {}).get("attributes", {}),
                self.group_settings.get(group, {}), self.catalog(group))
            result["item_wizard"] = wizard
            result["serial_item_code"] = serial.get("item_code")
            self.combination_cache[key] = result
        return self.combination_cache[key]

    def allocate(self, serial_no, department, planning_reason=None, target_item_code=None):
        audit = self.audits.setdefault(serial_no, {"serial_no": serial_no, "current_department": department,
            "serial_snapshot": copy.deepcopy(self.serials.get(serial_no, {})), "attempts": []})
        if not self.department_flags.get(department):
            event = {"result": "ALLOCATION_DISABLED", "reason": "Allocate Parts is disabled for this department", "sequence": None}
            success = False
        else:
            success, event = self.engine.decide(serial_no, self.mrs.get(serial_no, []), self.bags.get(serial_no, []), lambda code: self.alternatives(serial_no, code))
        event["department"] = department
        event["planning_reason"] = planning_reason
        event["target_item_code"] = target_item_code
        audit["attempts"].append(event)
        if event["result"] != "ALREADY_ALLOCATED":
            audit["result"] = event["result"]
        return success


    def build_plan_child_rows(self, plan_doc, serial_nos=None):
        """Return Part Allocation audit rows for the NJ Production Planning child table."""
        serial_filter = set(serial_nos or [])
        row_map = defaultdict(list)
        for row in plan_doc.get("lines") or []:
            if serial_filter and row.serial_no not in serial_filter:
                continue
            row_map[row.serial_no].append({
                "row_name": row.name,
                "row_number": row.idx,
                "department": row.current_department,
                "warehouse": row.current_warehouse,
                "priority_rank": row.priority_rank,
                "reason": row.reason,
                "item_code_to_make": row.item_code,
                "part_allocation": int(bool(row.part_allocation)),
            })

        rows = []
        for sn in sorted(serial_filter or set(self.audits)):
            audit = copy.deepcopy(self.audits.get(sn) or {})
            plan_rows = row_map.get(sn) or []
            audit.update(plan=plan_doc.name, run_id=self.run_id, plan_rows=plan_rows, included_in_plan=bool(plan_rows))
            attempts = audit.get("attempts") or []
            event = attempts[-1] if attempts else {}
            requirements = event.get("requirements") or []
            shortages = [req for req in requirements if number(req.get("shortage")) > EPSILON]
            selected_items = defaultdict(float)
            candidate_checks = []
            combinations = []

            for req in requirements:
                for item_code, qty in (req.get("selected_items") or {}).items():
                    selected_items[item_code] += number(qty)
                for check in req.get("candidate_checks") or []:
                    candidate_checks.append(dict(check, requested_item=req.get("requested_item")))
                combo = req.get("combination_search")
                if combo:
                    combinations.append({
                        "requested_item": req.get("requested_item"),
                        "eligible_item_codes": combo.get("eligible_item_codes") or [],
                        "reason": combo.get("reason"),
                        "item_wizard": combo.get("item_wizard"),
                    })

            shortage_summary = "; ".join(
                "{item} shortage={shortage} stock={stock} reserved={reserved} available={available}".format(
                    item=req.get("requested_item"),
                    shortage=number(req.get("shortage")),
                    stock=number((req.get("candidate_checks") or [{}])[0].get("initial_stock")),
                    reserved=number((req.get("candidate_checks") or [{}])[0].get("earlier_reserved_qty")),
                    available=number((req.get("candidate_checks") or [{}])[0].get("available_before_serial")),
                )
                for req in shortages[:5]
            )
            selected_summary = "; ".join(
                f"{item_code}={qty:g}" for item_code, qty in sorted(selected_items.items())
            )
            combination_summary = "; ".join(
                "{item}: {count} candidates{reason}".format(
                    item=combo.get("requested_item"),
                    count=len(combo.get("eligible_item_codes") or []),
                    reason=(" (" + combo.get("reason") + ")") if combo.get("reason") else "",
                )
                for combo in combinations[:5]
            )
            primary_shortage = shortages[0] if shortages else {}
            primary_candidate = (primary_shortage.get("candidate_checks") or [{}])[0]
            primary_combo = primary_shortage.get("combination_search") or {}
            plan_row = plan_rows[0] if plan_rows else {}
            rows.append({
                "allocation_run_id": self.run_id,
                "allocation_sequence": event.get("sequence") or 0,
                "serial_no": sn,
                "current_department": event.get("department") or audit.get("current_department") or plan_row.get("department"),
                "current_warehouse": plan_row.get("warehouse") or (audit.get("serial_snapshot") or {}).get("warehouse"),
                "priority_rank": plan_row.get("priority_rank"),
                "plan_row": plan_row.get("row_name"),
                "planning_reason": event.get("planning_reason") or plan_row.get("reason"),
                "target_item_code": event.get("target_item_code") or plan_row.get("item_code_to_make"),
                "part_allocation": 1 if event.get("result") in ("ALLOCATED", "ALREADY_ALLOCATED") else 0,
                "allocation_result": event.get("result") or audit.get("result") or "NOT_CHECKED",
                "allocation_reason": event.get("reason") or audit.get("reason"),
                "required_items_count": len(requirements),
                "shortage_items_count": len(shortages),
                "included_mr_count": len(event.get("included_mr_lines") or []),
                "excluded_mr_count": len(event.get("excluded_mr_lines") or []),
                "bag_rows_count": len(event.get("bag_rows") or []),
                "selected_items_summary": selected_summary,
                "shortage_summary": shortage_summary,
                "shortage_item": primary_shortage.get("requested_item"),
                "required_qty": number(primary_shortage.get("required_stock_qty")),
                "bag_qty_used": number(primary_shortage.get("bag_qty_used")),
                "needed_from_stores": number(primary_shortage.get("needed_from_stores")),
                "stores_stock": number(primary_candidate.get("initial_stock")),
                "earlier_reserved_qty": number(primary_candidate.get("earlier_reserved_qty")),
                "available_qty": number(primary_candidate.get("available_before_serial")),
                "shortage_qty": number(primary_shortage.get("shortage")),
                "combination_candidate_count": len(primary_combo.get("eligible_item_codes") or []),
                "combination_failure_reason": primary_combo.get("reason"),
                "combination_summary": combination_summary,
                "requirements_json": json.dumps(requirements, indent=2, default=str, ensure_ascii=False),
                "candidate_checks_json": json.dumps(candidate_checks, indent=2, default=str, ensure_ascii=False),
                "combinations_json": json.dumps(combinations, indent=2, default=str, ensure_ascii=False),
                "audit_json": json.dumps(audit, indent=2, default=str, ensure_ascii=False),
            })
        return rows

    def persist_to_plan_child(self, plan_doc, serial_nos=None):
        """Replace the plan's Part Allocation Details child rows with this run's audit.

        This writes the audit child table directly instead of saving the parent
        NJ Production Planning document. Some historical plan rows can contain
        links to cancelled Sales Orders; saving the parent revalidates those
        existing links and can block allocation audit storage even though the
        audit rows themselves are valid.
        """
        child_rows = self.build_plan_child_rows(plan_doc, serial_nos=serial_nos)
        child_doctype = "NJ Production Planning Part Allocation Detail"
        parent_filters = {
            "parent": plan_doc.name,
            "parenttype": "NJ Production Planning",
            "parentfield": "part_allocation_details",
        }

        frappe.db.delete(child_doctype, parent_filters)
        for idx, row in enumerate(child_rows, start=1):
            child_doc = frappe.get_doc({
                "doctype": child_doctype,
                **parent_filters,
                "idx": idx,
                **row,
            })
            child_doc.flags.ignore_validate_update_after_submit = True
            child_doc.insert(ignore_permissions=True)

        self.stock_snapshot["plan"] = plan_doc.name
        self.stock_snapshot["final_reserved_qty"] = dict(self.planned)
        return {"run_id": self.run_id, "child_rows": len(child_rows)}

    def persist(self, plan_doc):
        """Backward-compatible wrapper. Allocation audit now stays on NJ Production Planning."""
        return self.persist_to_plan_child(plan_doc)
