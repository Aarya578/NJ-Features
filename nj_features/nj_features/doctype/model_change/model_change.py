# Copyright (c) 2026, NewJaisa - IT Team and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _
from frappe.model.document import Document
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib
from nj_features.nj_features.doctype.njqca.njqca import (
    _get_target_laptop_item_code,
    rebuild_serial_no_components_for_model_change,
    update_serial_no_item_details,
    get_grade_a_item_variant,
)


@frappe.whitelist()
def get_serial_no_details(serial_no):
    if not serial_no:
        return None
    data = frappe.db.get_value(
        "Serial No",
        serial_no,
        ["name", "model", "warehouse", "item_code", "status"],
        as_dict=True,
    )
    if not data:
        frappe.throw(_(f"Serial No <b>{serial_no}</b> does not exist."))
    return data


class ModelChange(Document):

    def validate(self):
        self.validate_entries()

    def before_submit(self):
        self.set("updated_sn_model", [])
        for row in self.current_sn_model:
            sn = (row.serial_no or "").strip()
            if sn:
                self.append(
                    "updated_sn_model",
                    {
                        "serial_no": sn,
                        "model": self.model,
                    },
                )

    def validate_entries(self):
        if not self.current_sn_model or len(self.current_sn_model) == 0:
            frappe.throw(_("Please add at least one Serial No in Current SN Model table."))

        if not self.model:
            frappe.throw(_("Please select the Model."))

        # 1. Check all rows in current_sn_model have same model and no duplicates
        seen_serials = set()
        models_in_table = set()

        for row in self.current_sn_model:
            sn = (row.serial_no or "").strip()
            if not sn:
                continue

            if sn.lower() in seen_serials:
                frappe.throw(_(f"Duplicate Serial No <b>{sn}</b> found in Current SN Model table."))
            seen_serials.add(sn.lower())

            sn_doc_model = frappe.db.get_value("Serial No", sn, "model") or row.model
            if not sn_doc_model:
                frappe.throw(_(f"Model is not set for Serial No <b>{sn}</b>. Please check NPD Team."))

            row.model = sn_doc_model
            models_in_table.add(sn_doc_model)

        if len(models_in_table) > 1:
            frappe.throw(
                _(
                    f"Please select same model serial no. Multiple different models found in table: {', '.join(models_in_table)}"
                )
            )

        current_batch_model = list(models_in_table)[0]
        if str(self.model).strip().lower() == str(current_batch_model).strip().lower():
            frappe.throw(
                _(f"New Model <b>{self.model}</b> cannot be the same as current Model <b>{current_batch_model}</b>.")
            )

        # 2. Verify Item Wizard exists for the new model
        item_wizard_name = self.get_item_wizard_for_model(self.model)
        if not item_wizard_name:
            frappe.throw(
                _(
                    f"Item Wizard is not there for Model <b>{self.model}</b> with part list status 'Completed'. Please Contact NPD Team."
                )
            )

        item_wizard_doc = frappe.get_doc("Item Wizards", item_wizard_name)

        # 3. Verify target laptop item code can be resolved for each serial no
        for row in self.current_sn_model:
            sn = (row.serial_no or "").strip()
            if not sn:
                continue

            sn_doc = frappe.get_doc("Serial No", sn)
            target_item_code = _get_target_laptop_item_code(sn_doc, self.model, item_wizard_doc)
            if not target_item_code:
                frappe.throw(
                    _(
                        f"Matching Item Variant not found for Serial No <b>{sn}</b> under new Model <b>{self.model}</b>. Please contact NPD Team."
                    )
                )

    def get_item_wizard_for_model(self, model):
        res = frappe.db.sql(
            """
            SELECT name FROM `tabItem Wizards`
            WHERE model = %s AND part_list_status = 'Completed'
            ORDER BY modified DESC LIMIT 1
            """,
            (model,),
            as_dict=True,
        )
        return res[0]["name"] if res else None

    def on_submit(self):
        item_wizard_name = self.get_item_wizard_for_model(self.model)
        if not item_wizard_name:
            frappe.throw(
                _(
                    f"Item Wizard is not there for Model <b>{self.model}</b> with part list status 'Completed'. Please Contact NPD Team."
                )
            )

        item_wizard_doc = frappe.get_doc("Item Wizards", item_wizard_name)

        user = frappe.session.user or "Administrator"
        user_name = frappe.db.get_value("User", user, "full_name") or user
        date_str = frappe.utils.format_date(frappe.utils.nowdate(), "dd-mm-yyyy")

        company = (
            frappe.defaults.get_user_default("company")
            or frappe.db.get_single_value("Global Defaults", "default_company")
            or "National Traders"
        )
        accounting_cost_account = (
            frappe.db.get_single_value("NewJaisa Configuration", "default_operational_cost_account")
            or frappe.db.get_value("Company", company, "default_expense_account")
            or "Stock Adjustment - NT"
        )

        repack_items_list = []
        comment_lines = []
        laptops_data = []

        # ─── 1. COLLECT REPACK ITEMS FOR LAPTOPS ─────────────────────────
        for row in self.current_sn_model:
            sn = (row.serial_no or "").strip()
            if not sn:
                continue

            sn_doc = frappe.get_doc("Serial No", sn)
            cur_item = sn_doc.item_code
            sn_wh = sn_doc.warehouse

            if not sn_wh:
                sle = frappe.db.sql(
                    """
                    SELECT warehouse FROM `tabStock Ledger Entry`
                    WHERE serial_no = %s AND is_cancelled = 0 AND qty_after_transaction > 0
                    ORDER BY posting_date DESC, posting_time DESC LIMIT 1
                    """,
                    (sn,),
                    as_list=True,
                )
                sn_wh = sle[0][0] if sle else None

            if not sn_wh:
                sn_wh = (
                    frappe.db.get_single_value("Stock Settings", "default_warehouse")
                    or "Stores - NJ"
                )

            target_item_code = _get_target_laptop_item_code(sn_doc, self.model, item_wizard_doc)
            if not target_item_code:
                frappe.throw(
                    _(
                        f"Matching Item Variant not found for Serial No <b>{sn}</b> under new Model <b>{self.model}</b>. Please contact NPD Team."
                    )
                )

            sn_rate = (
                sn_doc.purchase_rate
                or frappe.db.get_value("Item", cur_item, "valuation_rate")
                or frappe.db.get_value("Item", target_item_code, "valuation_rate")
                or 1.0
            )

            # Laptop repack entry
            repack_items_list.append({
                "repack_item_code": cur_item,
                "repack_serial_no": sn,
                "repack_item_source_warehouse": sn_wh,
                "repack_item_base_price": sn_rate,
                "unpack_item_code": target_item_code,
                "unpack_serial_no": sn,
                "unpack_item_target_warehouse": sn_wh,
                "unpack_item_base_price": sn_rate,
            })

            comment_lines.append(
                f"changed from {cur_item} to {target_item_code} due to model change by {user_name} on {date_str}"
            )

            laptops_data.append({
                "serial_no": sn,
                "cur_item": cur_item,
                "target_item_code": target_item_code,
                "warehouse": sn_wh,
                "old_model": row.model,
            })

        # ─── 2. CREATE COMBINED REPACK STOCK ENTRY ───────────────────────
        repack_comments = "\n".join(comment_lines)
        stock_data = {
            "name": self.name,
            "doctype": self.doctype,
            "stock_entry_type": "Repack",
            "expense_account": accounting_cost_account,
            "repack_items": repack_items_list,
            "reason": "Others",
            "comments": repack_comments,
        }

        stock_entry_name = stock_entry_using_nj_lib(json.dumps(stock_data))
        if stock_entry_name:
            frappe.db.set_value(
                "Stock Entry",
                stock_entry_name,
                {
                    "reason": "Others",
                    "comments": repack_comments,
                },
                update_modified=False,
            )

        # ─── 3. UPDATE SERIAL NO DOCS & REBUILD COMPONENTS ───────────────
        for lap in laptops_data:
            sn = lap["serial_no"]
            target_item_code = lap["target_item_code"]
            old_model = lap["old_model"]

            sn_doc = frappe.get_doc("Serial No", sn)
            rebuild_serial_no_components_for_model_change(sn_doc, item_wizard_doc, self.model)
            sn_doc.save(ignore_permissions=True)

            update_serial_no_item_details(
                sn,
                target_item_code,
                {
                    "to_make": target_item_code,
                    "model": self.model,
                },
            )

            # Timeline comment on parent serial no
            try:
                c = frappe.new_doc("Comment")
                c.comment_type = "Comment"
                c.reference_doctype = "Serial No"
                c.reference_name = sn
                c.content = f"changed from {old_model} to {self.model} due to model change by {user_name} on {date_str}"
                c.insert(ignore_permissions=True)
            except Exception:
                pass

        # ─── 4. CLOSE OLD MR & RAISE NEW MR FOR EACH SERIAL NO ───────────
        schedule_date = frappe.utils.add_days(frappe.utils.nowdate(), 3)
        default_wh = frappe.db.get_single_value("Stock Settings", "default_warehouse") or "Stores - NJ"

        comp_type_to_item = {}
        for c in item_wizard_doc.get("component") or []:
            ctype = (c.get("component_type") or "").strip()
            dcode = c.get("default_item_code")
            if ctype and dcode and ctype.lower() not in comp_type_to_item:
                comp_type_to_item[ctype.lower()] = dcode

        for lap in laptops_data:
            sn = lap["serial_no"]

            old_mr_items = frappe.db.sql(
                """
                SELECT c.name, c.item_code, c.item_group, c.parent
                FROM `tabMaterial Request Item` c
                JOIN `tabMaterial Request` p ON p.name = c.parent
                WHERE c.serial_no = %s
                  AND p.docstatus = 1
                  AND p.material_request_type = 'Purchase'
                  AND IFNULL(c.post_order_status, '') != 'Completed'
                """,
                (sn,),
                as_dict=True,
            )

            if not old_mr_items:
                continue

            # Close old MR items
            frappe.db.sql(
                """
                UPDATE `tabMaterial Request Item` c
                JOIN `tabMaterial Request` p ON p.name = c.parent
                SET c.post_order_status = 'Completed'
                WHERE c.serial_no = %s
                  AND p.docstatus = 1
                  AND p.material_request_type = 'Purchase'
                  AND IFNULL(c.post_order_status, '') != 'Completed'
                """,
                (sn,),
            )

            # Map old MR item groups to new Grade A items
            distinct_item_groups = []
            seen_groups = set()
            for r in old_mr_items:
                ig = r.item_group or frappe.db.get_value("Item", r.item_code, "item_group")
                if ig and ig not in seen_groups:
                    seen_groups.add(ig)
                    distinct_item_groups.append(ig)

            comp_map = dict(comp_type_to_item)
            if not comp_map:
                sn_components = frappe.get_all(
                    "Serial No Component",
                    filters={"parent": sn},
                    fields=["item_group", "item"],
                )
                for sc in sn_components:
                    if sc.item_group and sc.item and sc.item_group.lower() not in comp_map:
                        comp_map[sc.item_group.lower()] = sc.item

            items_to_create = []
            for group in distinct_item_groups:
                g_key = (group or "").strip().lower()
                if g_key not in comp_map:
                    continue
                comp_default = comp_map[g_key]
                grade_a_item = get_grade_a_item_variant(comp_default) or comp_default

                items_to_create.append({
                    "item_code": grade_a_item,
                    "item_group": group,
                })

            if items_to_create:
                new_mr = frappe.new_doc("Material Request")
                new_mr.material_request_type = "Purchase"
                new_mr.naming_series = "MREQ-.YYYY.-.MM.-"
                new_mr.company = company
                new_mr.schedule_date = schedule_date
                new_mr.mr_create_reference = self.name
                new_mr.post_order_status = ""

                for itm in items_to_create:
                    icode = itm["item_code"]
                    igroup = itm.get("item_group")
                    fru_no, iuom = frappe.db.get_value("Item", icode, ["fru_number", "stock_uom"]) or (None, None)
                    fru_no = fru_no if fru_no else "NA"
                    iuom = iuom or "Nos"
                    iwh = (
                        frappe.db.get_value("Item Default", {"parent": icode, "company": company}, "default_warehouse")
                        or frappe.db.get_value("Item", icode, "default_warehouse")
                        or default_wh
                    )
                    new_mr.append(
                        "items",
                        {
                            "item_code": icode,
                            "qty": 1.0,
                            "schedule_date": schedule_date,
                            "serial_no": sn,
                            "uom": iuom,
                            "stock_uom": iuom,
                            "conversion_factor": 1,
                            "item_group": igroup,
                            "warehouse": iwh,
                            "fru_number": fru_no,
                        },
                    )

                new_mr.insert(ignore_permissions=True)
                new_mr.submit()
                frappe.msgprint(
                    _(
                        f"Old MR items completed and new Material Request <b>{new_mr.name}</b> submitted with {len(items_to_create)} item(s) for Serial No <b>{sn}</b>."
                    )
                )

        # ─── 5. POPULATE UPDATED SN MODEL CHILD TABLE ────────────────────
        frappe.db.sql("DELETE FROM `tabUpdated SN Model` WHERE parent = %s", (self.name,))
        for idx, row in enumerate(self.current_sn_model, 1):
            sn = (row.serial_no or "").strip()
            if not sn:
                continue
            child_name = frappe.generate_hash(length=10)
            frappe.db.sql(
                """
                INSERT INTO `tabUpdated SN Model`
                (name, creation, modified, modified_by, owner, docstatus, parent, parenttype, parentfield, idx, serial_no, model)
                VALUES (%s, NOW(), NOW(), %s, %s, 1, %s, %s, 'updated_sn_model', %s, %s, %s)
                """,
                (
                    child_name,
                    user,
                    user,
                    self.name,
                    self.doctype,
                    idx,
                    sn,
                    self.model,
                ),
            )
