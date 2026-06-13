# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import copy
import json
import time
import frappe
import csv
import os
import traceback
from frappe import _
import datetime as dt
from frappe.utils import get_url
from frappe.model.document import Document
from nj_lib.nj_lib.doctype.nj_log.nj_log import log_error
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib
from nj_p1_features.overrides.serial_no import update_component_in_serial_no
from nj_features.nj_features.doctype.inward.inward import get_item_template,has_item_wizards
from nj_p1_features.nj_p1_features.doctype.nj_quality_inspection.nj_quality_inspection import validation_for_nj_readings_in_nj_qi
from nj_lib.utils.common_utils import get_active_emp, get_latest_item_wizard,check_item_code_vs_model_validation,get_item_wizard,get_item_wizard_data

frappe.utils.logger.set_log_level("DEBUG")
logger = frappe.logger("newjaisa_njqca", allow_site=True)

def njqca_qi_trace(step, docname=None, data=None, error=False):
    """
    Temporary debug logger for finding why QI is not created from NJQCA.
    Writes to frappe logger and also NJ Log/Error Log for important failures.
    """
    try:
        payload = {
            "step": step,
            "docname": docname,
            "user": frappe.session.user,
            "data": data or {}
        }

        message = json.dumps(payload, default=str, indent=2)

        logger.debug("[NJQCA_QI_TRACE] " + message)

        # Only create visible log records for important checkpoints/errors
        if error:
            log_error(message, "NJQCA_QI_TRACE - " + step)

    except Exception:
        frappe.log_error(frappe.get_traceback(), "NJQCA_QI_TRACE logger failed")

def _is_desktop_item_group(item_group):
    return str(item_group or '').strip().lower() == 'desktops'


def _extract_brand_from_item_code(item_code):
    item_code = str(item_code or '').strip()
    if not item_code:
        return None
    if item_code.startswith('S-'):
        item_code = item_code[2:].strip()
    if not item_code:
        return None
    return item_code.split()[0].strip() or None


def _resolve_item_brand(serial_brand=None, item_brand=None, item_code=None, variant_of=None):
    if serial_brand:
        return serial_brand
    if item_brand:
        return item_brand
    template_brand = frappe.db.get_value('Item', variant_of, 'brand') if variant_of else None
    if template_brand:
        return template_brand
    return _extract_brand_from_item_code(item_code)


@frappe.whitelist()
def get_manufacturer_models(item_group=None, brand=None):
    if not item_group or not brand:
        return []

    query = """
        SELECT DISTINCT mmc.manufacturer_model
        FROM `tabItem` i
        INNER JOIN `tabManufacturer Model Child` mmc
            ON mmc.parent = i.item_model
        WHERE i.item_group = %(item_group)s
          AND i.brand = %(brand)s
          AND IFNULL(i.item_model, '') != ''
          AND IFNULL(mmc.manufacturer_model, '') != ''
          AND i.disabled = 0
        ORDER BY mmc.manufacturer_model
    """

    return frappe.db.sql(query, {'item_group': item_group, 'brand': brand}, as_dict=True)


@frappe.whitelist()
def update_serial_no_componont_for_grade(self):
    try:
        serial_no_doc = frappe.get_doc("Serial No", self.serial_no, for_update=True)
        serial_no_doc.bios_serial_no = self.bios_serialno
        serial_no_doc.current_price = self.base_price

        if not serial_no_doc.model:
            model = frappe.db.get_value('Item', {'name':serial_no_doc.item_code}, 'item_model')
            if model:
                serial_no_doc.model = model
        
        item_template = frappe.db.get_value('Item', {'name':serial_no_doc.item_code}, 'variant_of')

        if item_template:
            item_wizard = get_latest_item_wizard(item_template, serial_no_doc.item_code)
            item_wizard_doc = frappe.get_doc("Item Wizards", {"name": item_wizard})
            update_component_in_serial_no(item_wizard_doc, serial_no_doc, serial_no_doc.model,db_insert=True)
        serial_no_doc.save()

    except Exception as e:
        return {f'Error while updating the Serial No Component: {str(e)}'}
    
@frappe.whitelist()
def get_inspection_types_for_user(doctype, txt, searchfield, start, page_len, filters):
    try:
        emp_data = get_active_emp(frappe.session.user, fields=['role_profile'])
        role_profile = emp_data.get('role_profile') if emp_data else None

        allowed_inspection_types = []

        if role_profile:
            # Step 1: Try Table MultiSelect child table (multiple inspection types)
            child_types = frappe.db.get_all(
                'Inspection Type Multiselect',
                filters={'parent': role_profile},
                fields=['inspection_type'],
                order_by='idx'
            )
            allowed_inspection_types = [
                row['inspection_type']
                for row in child_types
                if row.get('inspection_type')
            ]

            # Step 2: If child table empty, fallback to single 'inspection_type' field
            if not allowed_inspection_types:
                single_type = frappe.db.get_value(
                    'Role Profile',
                    {'name': role_profile},
                    'inspection_type'
                )
                if single_type:
                    allowed_inspection_types = [single_type]

            # Step 3: If still empty, try department's inspection type
            if not allowed_inspection_types:
                department = frappe.db.get_value(
                    'Role Profile',
                    {'name': role_profile},
                    'department'
                )
                if department:
                    dept_type = frappe.db.get_value(
                        'Department',
                        {'name': department},
                        'inspection_type'
                    )
                    if dept_type:
                        allowed_inspection_types = [dept_type]

        # Step 4: If nothing found anywhere, show all active inspection types
        if not allowed_inspection_types:
            return frappe.db.sql("""
                SELECT name FROM `tabInspection Type`
                WHERE active = 1
                AND name LIKE %(txt)s
                LIMIT %(page_len)s OFFSET %(start)s
            """, {"txt": f"%{txt}%", "page_len": page_len, "start": start})

        # Step 5: Show all matched inspection types from the list using IN
        return frappe.db.sql("""
            SELECT name FROM `tabInspection Type`
            WHERE active = 1
            AND name IN %(allowed)s
            AND name LIKE %(txt)s
            LIMIT %(page_len)s OFFSET %(start)s
        """, {
            "allowed": tuple(allowed_inspection_types),
            "txt": f"%{txt}%",
            "page_len": page_len,
            "start": start
        })

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_inspection_types_for_user error")
        return []

@frappe.whitelist()
def get_inspection_type():
    emp_data = get_active_emp(frappe.session.user, fields=['role_profile'])    
    if not emp_data.get('role_profile'):
        frappe.msgprint("Role Profile not found for the user")
        return None
    
    role_inspection_type, department = frappe.db.get_value('Role Profile', 
                                {'name': emp_data.get('role_profile')}, 
                                ['inspection_type', 'department'])
    if role_inspection_type:
        return role_inspection_type
    
    if not department:
        frappe.msgprint("<b>Department</b> is not set in Role Profile: {0}".format(emp_data.get('role_profile')))
        return None
    
    dept_inspection_type = frappe.db.get_value('Department', {'name': department}, 'inspection_type')
       
    if dept_inspection_type:
        return dept_inspection_type
    
    else:
        frappe.msgprint("<b>Inspection Type</b> is not updated in either <b>Role Profile</b> or <b>Department: {0}</b>".format(department))
        return None
    
def open_draft_qi(self, component_serial_no=None, brand=None, model=None, is_defective=None, re_check=None):
    try:
        njqca_qi_trace("open_draft_qi_start", self.name, {
            "serial_no": self.serial_no,
            "component_serial_no": self.component_serial_no,
            "passed_component_serial_no": component_serial_no,
            "bios_serialno": self.bios_serialno,
            "item_group": self.item_group,
            "inspection_type": self.inspection_type,
            "brand": brand,
            "model": model,
            "is_defective": is_defective,
            "re_check": re_check,
            "power_on": self.power_on
        })

        is_component=frappe.db.get_value('Item Group', self.item_group, 'is_component')
        if is_component is not None and is_component == 1:
            serial_num=self.component_serial_no
        else:
            serial_num = self.serial_no

        if serial_num:
            status = frappe.db.get_value('Serial No', {'name': serial_num}, 'status')
            log_error(str(status),"serial status for serial no "+str(serial_num)+" in open draft qi")
            if status and status.lower() == 'delivered':
                nj_serial_no = frappe.db.get_value('Serial No', {'bios_serial_no': self.bios_serialno}, 'name')
                serial_num = nj_serial_no

        inspection_type = self.inspection_type or get_inspection_type()

        if self.bios_serialno and not self.serial_no and is_component is not None and is_component == 0:
            serial_num = frappe.db.get_value('Serial No', {'bios_serial_no': self.bios_serialno}, 'name')
        elif (self.component_serial_no is None or self.component_serial_no == "") and component_serial_no is not None and is_component is not None and is_component == 1:
            serial_num = component_serial_no
        njqca_qi_trace("open_draft_qi_serial_resolved", self.name, {
            "is_component": is_component,
            "resolved_serial_num": serial_num,
            "inspection_type": inspection_type
        })

        if not serial_num:
            njqca_qi_trace("open_draft_qi_serial_missing", self.name, {
                "serial_no": self.serial_no,
                "component_serial_no": self.component_serial_no,
                "passed_component_serial_no": component_serial_no,
                "bios_serialno": self.bios_serialno
            }, error=True)

        create_new_qi = True
        new_qi = None
        
        sync_njqca_qis = frappe.get_list(
            'NJ Quality Inspection',
            filters={
                'barcode': serial_num,
                'docstatus': 0,
                'inspection_type': inspection_type,
                'owner':self.created,
                'sync_njqca': 1,
                'attribute_1': ['>', 0],
                'attribute_2': ['>', 0],
                'attribute_3': ['>', 0],
            },
            fields=['name', 'creation'],
            order_by='creation desc'
        )
        log_error(str(sync_njqca_qis),f"sync_njqca_qis for serial no {serial_num} {inspection_type} {self.created} in open draft qi")

        njqca_qi_trace("sync_njqca_qis_result", self.name, {
            "serial_num": serial_num,
            "inspection_type": inspection_type,
            "created": self.created,
            "sync_njqca_qis": sync_njqca_qis
        })

        if not sync_njqca_qis:
            existing_qis = frappe.get_list(
                'NJ Quality Inspection',
                filters={
                    'barcode': serial_num,
                    'docstatus': 0,
                    'inspection_type': inspection_type,
                    'brand': brand,
                    'model': model,
                    'attribute_1': ['>', 0],
                    'attribute_2': ['>', 0],
                    'attribute_3': ['>', 0],
                },
                fields=['name', 'creation'],
                order_by='creation desc'
            )

            njqca_qi_trace("existing_qis_result", self.name, {
                "serial_num": serial_num,
                "inspection_type": inspection_type,
                "brand": brand,
                "model": model,
                "existing_qis": existing_qis
            })

        if sync_njqca_qis:
            latest_qi = sync_njqca_qis[0]
            time_diff = frappe.utils.time_diff_in_seconds(frappe.utils.now_datetime(), latest_qi.creation)
            log_error(str(time_diff)+str(latest_qi.name),"time_diff for serial no "+str(serial_num)+" in open draft qi")
            if time_diff < 3600:
                new_qi = frappe.get_doc('NJ Quality Inspection', latest_qi.name)
                create_new_qi = False
        elif existing_qis:
            latest_qi = existing_qis[0]
            time_diff = frappe.utils.time_diff_in_seconds(frappe.utils.now_datetime(), latest_qi.creation)
            if time_diff < 1200:
                new_qi = frappe.get_doc('NJ Quality Inspection', latest_qi.name)
                new_qi.njqca_laptop_name = self.name
                if is_defective=="1":
                    new_qi.is_defective = 1
                create_new_qi = False

        if create_new_qi:
            log_error(str(create_new_qi),"create_new_qi for serial no "+str(serial_num)+" in open draft qi")
            njqca_qi_trace("creating_new_qi", self.name, {
                "serial_num": serial_num,
                "inspection_type": inspection_type,
                "brand": brand,
                "model": model,
                "warehouse": self.warehouse,
                "manual_repack_item_code": self.manual_repack_item_code
            })
            new_qi = frappe.new_doc('NJ Quality Inspection')
            new_qi.inspection_type = inspection_type
            new_qi.barcode = serial_num
            new_qi.njqca_laptop_name = self.name
            new_qi.inspected_by = new_qi.owner
            new_qi.brand = brand
            new_qi.model = model
            if is_defective =="1":
                new_qi.is_defective = 1
            new_qi.warehouse = self.warehouse
            if self.manual_repack_item_code:
                new_qi.item_code = self.manual_repack_item_code
            njqca_qi_trace("before_get_itm_code_on_barcode", self.name, {
                "qi_barcode": new_qi.barcode
            })

            new_qi = get_itm_code_on_barcode(new_qi)

            njqca_qi_trace("after_get_itm_code_on_barcode", self.name, {
                "new_qi_type": str(type(new_qi)),
                "disable_save": new_qi.get("disable_save") if isinstance(new_qi, dict) else None,
                "item_code": new_qi.get("item_code") if hasattr(new_qi, "get") else None,
                "warehouse": new_qi.get("warehouse") if hasattr(new_qi, "get") else None
            })

            if isinstance(new_qi, dict) and new_qi.get("disable_save"):
                njqca_qi_trace("qi_creation_stopped_disable_save", self.name, {
                    "reason": "get_itm_code_on_barcode returned disable_save",
                    "barcode": serial_num
                }, error=True)

                frappe.throw(
                    f"QI not created because Serial No <b>{serial_num}</b> has no warehouse."
                )
            
            njqca_qi_trace("before_fill_nj_quality_reading", self.name, {
                "barcode": new_qi.barcode,
                "inspection_type": inspection_type,
                "is_defective": is_defective,
                "re_check": re_check
            })

            new_qi = fill_nj_quality_reading_from_serial_or_itm_wizard(
                new_qi, inspection_type,
                is_defective="1" if is_defective else "0",
                re_check="1" if re_check else "0"
            )

            njqca_qi_trace("after_fill_nj_quality_reading", self.name, {
                "nj_quality_readings_count": len(new_qi.get("nj_quality_readings") or []),
                "mandatory_rows_count": len(new_qi.get("mandatory_rows") or []),
                "item_wizard": new_qi.get("item_wizard")
            })

        # config_data_2_qi = frappe.db.get_value("NJ Settings", {"doc_type": "NJQCA", "parameter": "config"}, "value")
        # config_data_2_qi = json.loads(config_data_2_qi) if config_data_2_qi else {}

        # item_group = tuple(config_data_2_qi.keys())
        # parameter = tuple(config_data_2_qi.values())

        # sql_check = """
        #     SELECT options.quality_check
        #     FROM `tabNJ Quality Checks` qc
        #     LEFT JOIN `tabNj QC Options` options ON qc.name = options.parent
        #     INNER JOIN `tabNJ QC Check List` qc_check ON options.quality_check = qc_check.name
        #     WHERE qc.item_group in %s AND qc.inspection_type = %s
        #       AND qc_check.diagnostic_type = 'Automatic'
        #       AND qc_check.njqca_parameter='Config' AND qc_check.parameter in %s
        # """
        # field_name_data_1 = frappe.db.sql(sql_check, (item_group, inspection_type, parameter), as_dict=True)

        # def extract_numeric_and_suffix(value):
        #     if not value or not value.strip():
        #         return None, ''
        #     match = re.match(r'(\d+)\s*(.*)', value)
        #     return (int(match.group(1)), match.group(2).strip()) if match else (None, '')

        # check_mapping = {
        #     0: {"query": "SELECT variant_9 FROM `tabNJQCA Child` WHERE item_group = %s AND parent = %s", "field": "variant_9", "item_group": item_group[0]},
        #     1: {"query": "SELECT variant_6 FROM `tabNJQCA Child` WHERE item_group = %s AND parent = %s", "field": "variant_6", "item_group": item_group[1]},
        #     2: {"query": "SELECT variant_10 FROM `tabNJQCA Child` WHERE item_group = %s AND parent = %s", "field": "variant_10", "item_group": item_group[2]},
        # }

        # for idx, field in enumerate(field_name_data_1):
        #     name_of_check = field['quality_check']
        #     if any(child.item_group in config_data_2_qi and child.check_name == name_of_check for child in new_qi.get("nj_quality_checks", [])):
        #         continue

        #     if idx in check_mapping:
        #         qdata = frappe.db.sql(check_mapping[idx]["query"], (check_mapping[idx]["item_group"], self.name), as_dict=True)
        #         field = check_mapping[idx]["field"]
        #         val = ''
        #         if qdata and qdata[0].get(field):
        #             if idx in (1, 2):
        #                 parts = [extract_numeric_and_suffix(x[field]) for x in qdata if extract_numeric_and_suffix(x[field])[0]]
        #                 if parts:
        #                     v, s = max(parts, key=lambda x: (x[0], x[1]))
        #                     val = f"{v} {s}".strip()
        #             else:
        #                 val = qdata[0][field]
        #         if val:
        #             row = new_qi.append("nj_quality_checks", {})
        #             row.check_name = name_of_check
        #             row.options = val
        #             row.automated_check_name = val
        #             row.item_group = check_mapping[idx]["item_group"]

        # MODIFIED BLOCK — LOOP OVER ALL item_group_idx matches
        # PARAMETER + SCORE BASED NJQCA → QI SYNC
        # This does NOT depend on NJQCA item_group or QI reading item_group.
        # It only uses:
        #   1. inspection_type
        #   2. NJQCA Result Parameter.parameter
        #   3. NJQCA Result Parameter.score
        #   4. QC Options score mapping
        def safe_int(value):
            try:
                return int(float(value or 0))
            except Exception:
                return 0

        existing = {
            (
                child.check_name,
                child.item_group,
                safe_int(child.get("item_group_idx"))
            ): child
            for child in new_qi.get("nj_quality_checks", [])
            if child.check_name
        }

        for data in self.njqca_result_parameters:
            parameter = (data.get("parameter") or "").strip()
            score = data.get("score")
            value = data.get("value")

            if not parameter:
                continue

            sql = """
                SELECT DISTINCT
                    qc.item_group AS target_item_group,
                    options.quality_check
                FROM `tabNJ Quality Checks` qc
                INNER JOIN `tabNj QC Options` options
                    ON qc.name = options.parent
                INNER JOIN `tabNJ QC Check List` qc_check
                    ON options.quality_check = qc_check.name
                WHERE qc.inspection_type = %s
                AND TRIM(qc_check.parameter) = %s
                AND qc_check.diagnostic_type = 'Automatic'
                AND qc.docstatus = 1
                AND qc.status = 'Active'
                AND qc_check.docstatus = 1
            """

            mapped_checks = frappe.db.sql(
                sql,
                (inspection_type, parameter),
                as_dict=True
            )

            if not mapped_checks:
                continue

            for mapped in mapped_checks:
                check_name = mapped.get("quality_check")
                target_item_group = mapped.get("target_item_group")

                if not check_name or not target_item_group:
                    continue

                # Default: use NJQCA value directly
                resolved_option = value
                resolved_score = score

                # Score-based option conversion:
                # score 0  -> Pass
                # score 41 -> Fail
                check_options = frappe.db.sql("""
                    SELECT check_options, score
                    FROM `tabQC Options`
                    WHERE parent = %s
                    AND active = 1
                    ORDER BY idx
                """, check_name, as_dict=True)

                if check_options and score not in (None, ""):
                    try:
                        score_value = float(score)
                        for opt in check_options:
                            opt_score = opt.get("score")
                            if opt_score not in (None, "") and score_value == float(opt_score):
                                resolved_option = opt.get("check_options") or value
                                resolved_score = float(opt_score)
                                break
                    except Exception:
                        pass

                # Get all QI reading rows for this item group.
                # This is the important fix for repeated Laptop RAM / LAPTOP STORAGE rows.
                matched_readings = [
                    r for r in new_qi.get("nj_quality_readings", [])
                    if r.get("item_group") == target_item_group
                ]

                # If no reading row exists, still create/update one automatic check row.
                if not matched_readings:
                    matched_readings = [None]

                for matched_reading in matched_readings:
                    item_group_idx = 0

                    if matched_reading:
                        item_group_idx = safe_int(matched_reading.get("item_group_idx"))

                    key = (check_name, target_item_group, item_group_idx)
                    child = existing.get(key)

                    if not child:
                        child = new_qi.append("nj_quality_checks", {})
                        existing[key] = child

                    child.item_group = target_item_group
                    child.check_name = check_name
                    child.options = resolved_option
                    child.automated_check_name = resolved_option
                    child.score = resolved_score
                    child.item_group_idx = item_group_idx

        njqca_qi_trace("before_new_qi_save", self.name, {
            "qi_name_before_save": new_qi.name,
            "barcode": new_qi.barcode,
            "inspection_type": new_qi.inspection_type,
            "item_code": new_qi.item_code,
            "warehouse": new_qi.warehouse,
            "nj_quality_readings_count": len(new_qi.get("nj_quality_readings") or []),
            "nj_quality_checks_count": len(new_qi.get("nj_quality_checks") or [])
        })

        new_qi.save()

        njqca_qi_trace("after_new_qi_save", self.name, {
            "qi_name": new_qi.name,
            "barcode": new_qi.barcode
        }, error=not bool(new_qi.name))

        base_url = frappe.get_value("NJ Settings", {'parameter': 'njpluse_url_for_qi'}, "value")
        if not base_url:
            frappe.throw("NJPulse URL is not found in NJ Settings.")

        njpulse_url = f"{base_url}qi/{new_qi.name}/0" if new_qi.name else base_url
        msg_pnt = f"NJ Quality readings updated successfully..!! for <strong>QI: {new_qi.name}</strong>" if new_qi.name else "Saved without name."

        if new_qi.name:
            frappe.db.set_value("NJQCA", self.name, "qi_name", new_qi.name)

            njqca_qi_trace("qi_name_set_in_njqca", self.name, {
                "qi_name": new_qi.name
            })

            frappe.db.commit()  # commit only if outside request cycle

        return {
            'qi_name': new_qi.name or '',
            'njpulse_url': njpulse_url,
            'msg_pnt': msg_pnt,
            'base_url': base_url
        }

    except Exception as e:
        log_error(traceback.format_exc(), "error in open_draft_qi NJQCA")
        frappe.throw(f"error in saving NJ QI {str(e)}")
        return None
    
@frappe.whitelist()
def get_itm_code_on_barcode(new_qi):
    try:
        barcode = new_qi.barcode
        if not barcode:
            frappe.throw("barcode not found")

        serial_no_data = frappe.db.get_value("Serial No", {"name": barcode},
                        ["item_code", "bios_serial_no", "item_group", "item_name",
                         "warehouse", "purchase_rate", "purchase_date","rfq_id"],
                        as_dict=True)
        
        if not serial_no_data:
            frappe.throw(_("Serial No '{0}' not found. Please select an existing Serial No.").format(barcode))
        
        result = {
            "item_code": serial_no_data.item_code,
            "bios_serial_number": serial_no_data.bios_serial_no,
            "item_group": serial_no_data.item_group,
            "item_name": serial_no_data.item_name,
            "rfq_id": serial_no_data.rfq_id,
            "base_price": serial_no_data.purchase_rate
        }

        for key,value in result.items():
            new_qi.set(key,value)

        if serial_no_data.warehouse and serial_no_data.rfq_id is None:
            emp_data = get_active_emp(frappe.session.user)
            work_warehouse = emp_data.get('work_warehouse')
            if not work_warehouse:
                frappe.msgprint(_("Work Warehouse is not set for Employee: <b>{0}</b>").format(frappe.session.user))
            return new_qi

        elif serial_no_data.warehouse is None and serial_no_data.rfq_id is None:
            frappe.msgprint(_("Warehouse is not updated in Serial No: <b>{0}</b>").format(barcode))
            return {"disable_save": True}

        return new_qi
        
    except Exception as e:
        log_error(traceback.format_exc(), "Error in get_itm_code_on_barcode in NJQCA")
        frappe.throw(f"Error in get_itm_code_on_barcode {str(e)}")
        return None

@frappe.whitelist()
def fill_nj_quality_reading_from_serial_or_itm_wizard(new_qi, inspection_type, is_defective="0", re_check="0"):
    try:
        barcode = new_qi.get("barcode")
        if not barcode:
            frappe.throw("Error: Barcode is not found.")

        if not inspection_type:
            frappe.throw("Error: Inspection Type is not found.")
        
        response = frappe._dict()
        
        response = validation_for_nj_readings_in_nj_qi(barcode, inspection_type, is_defective, re_check, is_njqca=True)

        doc_data = response.get('doc_data')

        if response.get('sequence_list_for_nj_readings_data'):
            nj_quality_readings = []
            for nj_readings_data in response.get('sequence_list_for_nj_readings_data'):
                if nj_readings_data.get('quality_check'):
                    nj_quality_readings.append({
                        'item_group': nj_readings_data.get('item_group'),
                        'quality_check': nj_readings_data.get('quality_check'),
                        'item': nj_readings_data.get('item'),
                        'item_group_idx': nj_readings_data.get('item_group_idx'),
                        'part_serial_no': nj_readings_data.get('part_serial_no'),
                        'previous_grade': nj_readings_data.get('previous_grade'),
                        'available_qty': nj_readings_data.get('available_qty'),
                        'previous_reference_doctype': nj_readings_data.get('previous_reference_doctype'),
                        'previous_reference_doctype_no': nj_readings_data.get('previous_reference_doctype_no'),
                        'plan_time': nj_readings_data.get('plan_time'),
                        'depends_on_linked_item_group': nj_readings_data.get('depends_on_linked_item_group'),
                    })
            new_qi.set('nj_quality_readings', [])
            for reading in nj_quality_readings:
                new_qi.append('nj_quality_readings', reading)
        
        if response.get('initial_mandatory_rows'):
            new_qi.set('mandatory_rows', response.get('initial_mandatory_rows'))

        if doc_data and doc_data[0].get('item_wizard'):
            new_qi.set('item_wizard', doc_data[0].get('item_wizard'))
        return new_qi

    except Exception as e:
        log_error(traceback.format_exc(), "Error in fill_nj_quality_reading_from_serial_or_itm_wizard in NJQCA")
        frappe.throw(f"Error in fill_nj_quality_reading_from_serial_or_itm_wizard {str(traceback.format_exc())}")
        return None
def upsert_njqca_result_parameter_row(doc, change):
    item_group = (change.get("item_group") or "").strip()
    parameter = (change.get("parameter") or "").strip()

    if not item_group or not parameter:
        return

    value = change.get("value")
    if value is None:
        value = ""

    score = change.get("score") or ""
    part_config_id = change.get("part_config_id") or 0

    existing_row = None

    # Use latest matching row if duplicate exists
    for row in reversed(doc.get("njqca_result_parameters") or []):
        if (
            (row.get("item_group") or "").strip() == item_group
            and (row.get("parameter") or "").strip() == parameter
        ):
            existing_row = row
            break

    if existing_row:
        existing_row.item_group = item_group
        existing_row.parameter = parameter
        existing_row.value = str(value)
        existing_row.score = score
        existing_row.part_config_id = part_config_id
    else:
        doc.append("njqca_result_parameters", {
            "item_group": item_group,
            "parameter": parameter,
            "value": str(value),
            "score": score,
            "part_config_id": part_config_id
        })

def _norm_njqca_param(value):
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def has_njqca_param_value(doc, parameter_name):
    target = _norm_njqca_param(parameter_name)

    for row in doc.get("njqca_result_parameters") or []:
        parameter = _norm_njqca_param(row.get("parameter"))
        value = str(row.get("value") or "").strip()

        if parameter == target and value:
            return True

    return False


def has_actual_test_file(doc):
    return (
        has_njqca_param_value(doc, "heavy_load_File_Updated_name")
        or has_njqca_param_value(doc, "performance_File_Updated_name")
        or has_njqca_param_value(doc, "sensors_File_Updated_name")
        or has_njqca_param_value(doc, "y_cruncher_File_Updated_name")
    )


def has_perf_or_heavyload_test_file(doc):
    return (
        has_njqca_param_value(doc, "heavy_load_File_Updated_name")
        or has_njqca_param_value(doc, "performance_File_Updated_name")
        or has_njqca_param_value(doc, "sensors_File_Updated_name")
    )
def apply_reliability_test_changes_to_doc(doc):
    try:
        inspection_type = (doc.get("inspection_type") or "").strip().lower()
        is_reliability_test = inspection_type == "reliability test"
        actual_test_file_present = has_actual_test_file(doc)

        # Reliability Test always allowed.
        # Other inspection types allowed only if actual test file exists.
        if not is_reliability_test and not actual_test_file_present:
            return

        res = get_reliability_test_status(doc.as_dict())
        changes = res.get("changes") or []

        for change in changes:
            upsert_njqca_result_parameter_row(doc, change)

    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "apply_reliability_test_changes_to_doc failed"
        )

def is_njqca_status_submit_validation_enabled():
    """
    NJ Settings:
    Parameter: njqca_status_submit_validation
    Doc Type: NJQCA

    Value:
        0 = Do not validate NJQCA_Status
        1 = Validate NJQCA_Status before submit
    """
    value = frappe.db.get_value(
        "NJ Settings",
        {
            "parameter": "njqca_status_submit_validation",
            "doc_type": "NJQCA"
        },
        "value"
    )

    return str(value or "0").strip() == "1"


def validate_njqca_status_completed_before_submit(doc):
    """
    If enabled in NJ Settings, NJQCA submit is allowed only when
    NJQCA Result Parameters has:

        parameter = NJQCA_Status
        value     = Completed

    Skip validation for BATTERY item group.
    """

    # Skip validation for BATTERY
    if str(doc.get("item_group") or "").strip().lower() == "battery":
        return

    # If setting is 0 or missing, skip validation
    if not is_njqca_status_submit_validation_enabled():
        return

    status_completed = False

    for row in doc.get("njqca_result_parameters") or []:
        parameter = str(row.get("parameter") or "").strip().lower()
        value = str(row.get("value") or "").strip().lower()

        if parameter == "njqca_status" and value == "completed":
            status_completed = True
            break

    if not status_completed:
        frappe.throw(
            _("NJQCA was not completed. Please re-run the script before submitting.")
        )

class NJQCA(Document):
    def onload(self):
        is_component=frappe.db.get_value('Item Group', self.item_group, 'is_component')
        if is_component is not None and is_component == 1:
            return
        
        data = get_item_group_mapping(self.name)
        gen_score_map = {
        "CORE I3": 0.1,
        "CORE I4": 0.2,
        "CORE I5": 0.3,
        "CORE I7": 0.4,
        "CORE I8": 0.5,
        "CORE I9": 0.6,
        "CORE I10": 0.7,
        "CORE I11": 0.8,
        "CELERON(R) CPU": 0.9,
        "DUAL-CORE CPU": 0.10,
        "ATOM X5 CPU": 0.11,
        "XEON(R) E": 0.12,
        "PRO A10": 0.13,
        "GEN INTEL(R)": 0.14,
        "RYZEN 5": 0.15,
        "A8 PRO": 0.16,
        "A10 PRO": 0.17,
        "A6-6310 APU": 0.18,
        "RYZEN 7": 0.19,
        "A6-9225 RADEON": 0.20,
        "PENTIUM(R) CPU": 0.21,
        "PRO A6": 0.22,
        "A10-5750M APU": 0.23,
        "A6-7310 APU": 0.24,
        }

        for row in data:
            score = gen_score_map.get(row.variant_6.strip().upper(), 0)  # default score = 0 if not matched

            self.append("njqca_result_parameters", {
                "parameter": "laptop_gen",
                "value": row.variant_6,
                "item_group": "BODY C",
                "score": score
            })

        # Map brand to score
        brand_score_map = {
            "Lenovo": 1,
            "HP": 2,
            "Dell": 3
        }

        score = brand_score_map.get(self.brand)
        if score:
            self.append("njqca_result_parameters", {
                "parameter": "Brand",
                "value": self.brand,
                "item_group": "BODY C",
                "score": score
            })

    def before_save(self):
        update_storage_type(self)
        apply_reliability_test_changes_to_doc(self)
        set_fail_for_empty_reliability_params(self)
        
        # EXT-NJ Linkage: Set linked_ext to self.serial_no for external QC docs
        if self.rfq_id and self.serial_no:
            self.linked_ext = self.serial_no

    def on_update(self):
        # EXT-NJ Linkage: Update reference_doctype_no on the created external Serial No
        if self.rfq_id and self.serial_no:
            if frappe.db.exists("Serial No", self.serial_no):
                frappe.db.set_value(
                    "Serial No",
                    self.serial_no,
                    "reference_doctype_no",
                    self.name,
                    update_modified=False
                )
    def before_submit(self):
        validate_njqca_status_completed_before_submit(self)
        
    def on_submit(self):
        njqca_qi_trace("on_submit_start", self.name, {
            "serial_no": self.serial_no,
            "component_serial_no": self.component_serial_no,
            "bios_serialno": self.bios_serialno,
            "power_on": self.power_on,
            "inspection_type": self.inspection_type,
            "item_group": self.item_group,
            "qi_name": self.qi_name,
            "note": "Current on_submit does not create QI because open_draft_qi block is commented"
        })

        try:
            # self.performance_reports_update()
            self.check_for_repack_access()
            # self.updating_njqca_child_in_serial_no()
            # self.laptop_reports_update()
            # self.battery_reports_update()
            # self.adaptor_reports_update()
            # self.update_item_groups()
            self.validate_item_code_match()
            # self.battery_readings()
            self.update_serial_no_readings()
        except Exception as e:
            log_error(traceback.format_exc(), "Error in on_submit in NJQCA")
            frappe.throw(f"Error in before on_submit {str(traceback.format_exc())}")

        is_component=frappe.db.get_value('Item Group', self.item_group, 'is_component')

        if self.power_on == 'Yes':
            if self.manual_repack_item_code is None or self.manual_repack_item_code == '':
                frappe.throw("Please fill <b>Manual Repack Item Code</b>.")
                return None
            if self.item_template and is_component is not None and is_component != 1:
                tmp_model = frappe.db.get_value('Item', self.item_template, 'item_model')
                itm_model = frappe.db.get_value('Item', self.manual_repack_item_code, 'item_model')
                if tmp_model and tmp_model != self.model:
                    frappe.throw("Model: <b>" + tmp_model + "</b> in Item Template is not matching with Selected Model: <b>" + self.model + "</b><br>Please contact <b>NPD Team</b>.")
                    return None
                
                if itm_model and itm_model != self.model:
                    frappe.throw("Model: <b>" + itm_model + "</b> in Manual Repack Item Code is not matching with Selected Model: <b>" + self.model + "</b><br>Please contact <b>NPD Team</b>.")
                    return None
            
            try:
                qi_data = None
                
                s1 = time.time()
                logger.debug(f"Time for '{self.name}'")
                if is_component is not None and is_component != 1 :
                   sn_item_group = frappe.db.get_value('Serial No', self.serial_no, 'item_group')
                else:
                   sn_item_group = frappe.db.get_value('Serial No', self.component_serial_no, 'item_group')
                   
                if is_component is not None and is_component != 1:
                   check_item_code_vs_model_validation(self.manual_repack_item_code, self.model)
                logger.debug(f"Time after check_item_code_vs_model_validation '{self.name}': {time.time() - s1:.2f} seconds")

                if self.item_code != self.manual_repack_item_code and self.rfq_id is None and self.item_group == sn_item_group :
                    s2 = time.time()
                    self.make_stock_entry_using_nj_lib()
                    logger.debug(f"Time after stock entry '{self.name}': {time.time() - s2:.2f} seconds")
                
                nj_settings_item_group = frappe.db.get_value('NJ Settings', {'parameter': 'njqca_battery'}, 'value')
                if nj_settings_item_group and self.item_group != nj_settings_item_group and self.item_group == sn_item_group:
                    s5 = time.time()
                    update_serial_no_componont_for_grade(self)
                    logger.debug(f"Time after update_serial_no_componont_for_grade '{self.name}': {time.time() - s5:.2f} seconds")
                
                # if self.item_group == sn_item_group or self.item_group=='BATTERY' or  self.rfq_id!="":
                #     s4 = time.time()
                #     if self.qi_type is not None and self.qi_type=="is_defective":
                #         qi_data = open_draft_qi(self,self.component_serial_no,self.brand,self.model,is_defective="1")
                #     elif self.qi_type is not None and self.qi_type=="re_check":
                #         qi_data = open_draft_qi(self,self.component_serial_no,self.brand,self.model,re_check="1")
                #     else:
                #         qi_data = open_draft_qi(self,self.component_serial_no,self.brand,self.model)
                #     logger.debug(f"Time after open_draft_qi '{self.name}': {time.time() - s4:.2f} seconds")
                
                # if qi_data:
                #     if qi_data.get('msg_pnt'):
                #         frappe.msgprint(qi_data.get('msg_pnt'))

            except Exception as e:
                frappe.db.rollback()
                frappe.msgprint("Error during submission: " + traceback.format_exc())
                raise

        # EXT-NJ Linkage: remove bios from EXT serial after NJQCA submit
        self.remove_bios_from_linked_ext()

    def remove_bios_from_linked_ext(self):
        """
        EXT-NJ Linkage: called at the end of on_submit.
        If this NJQCA has a linked_ext serial, clear its bios_serial_no
        so that future BIOS scans no longer match it.
        """
        if not self.linked_ext:
            return
        try:
            frappe.db.set_value(
                "Serial No",
                self.linked_ext,
                "bios_serial_no",
                None,
                update_modified=False,
            )
            frappe.db.commit()
        except Exception as e:
            frappe.log_error(
                frappe.get_traceback(),
                f"EXT Linkage: failed to clear bios from {self.linked_ext}"
            )

    def check_for_repack_access(self):

        user = frappe.session.user
        role_profile = frappe.db.get_value('Employee', {'user_id': user, 'status': 'Active'}, 'role_profile')
        
        if not frappe.db.get_value('Role Profile', {'name': role_profile}, 'restrict_repack'):
            item_code = self.item_code if self.item_code else ""
            repack_item_code = self.manual_repack_item_code if self.manual_repack_item_code else ""

            if item_code != repack_item_code:
                frappe.throw(f"You don't have access to Repack to change the item code from <b>{item_code}</b> to <b>{repack_item_code}</b>")

    def make_stock_entry_using_nj_lib(self):

        accounting_cost_account = frappe.db.get_single_value('NewJaisa Configuration', 'default_operational_cost_account')
        stock_data = {
            "name": self.name,
            "doctype": self.doctype,
            "stock_entry_type": "Repack",
            "repack_items": get_repack_items(self),
            "expense_account": accounting_cost_account
        }
        stock_data_str = json.dumps(stock_data)
        stock_entry_using_nj_lib(stock_data_str)

    def validate_item_code_match(self):
            if self.item_group != "Laptops":
                return
                
            setting_value = frappe.db.get_value('NJ Settings', {'parameter': 'njqca_validate_item_code'}, 'value')
            
            if not setting_value:
                return
                
            allowed_inspection_types = [val.strip() for val in setting_value.split(",")]
            
            if hasattr(self, 'inspection_type') and self.inspection_type in allowed_inspection_types:
                if self.item_code and self.repack_item_code and self.item_code.strip() != self.repack_item_code.strip():
                    frappe.throw("Item Code and Repack Item Code do not match. Please correct them before submitting.")

            # RAM / SSD Item Wizard warning
            item_wizard = frappe.db.get_value("Serial No", self.serial_no, "item_wizard") if self.serial_no else None
            if not item_wizard:
                return

            bad_attributes = []

            for row in self.get("njqca_laptop_ram") or []:
                calculated = (row.get("calculated_item_code") or "").strip()
                fetched = (row.get("fetched_item_code") or "").strip()
                if calculated and fetched and calculated != fetched:
                    bad_attributes.append(
                        "<b>{}</b> Attribute of RAM is NOT as Per Item Wizard. "
                        "MAKE SURE to USE MPC to Replace the same.".format(calculated)
                    )

            for row in self.get("njqca_laptop_storage") or []:
                calculated = (row.get("calculated_item_code") or "").strip()
                fetched = (row.get("fetched_item_code") or "").strip()
                if calculated and fetched and calculated != fetched:
                    bad_attributes.append(
                        "<b>{}</b> Attribute of Storage is NOT as Per Item Wizard. "
                        "MAKE SURE to USE MPC to Replace the same.".format(calculated)
                    )

            if bad_attributes:
                frappe.msgprint(
                    "<br>".join(bad_attributes),
                    title="Item Wizard Mismatch",
                    indicator="red"
                )
    def updating_njqca_child_in_serial_no(self):
        # Only proceed for Core IQC and Laptops
        if self.inspection_type != "Final QC" or self.item_group != "Laptops":
            return

        if not self.serial_no:
            return

        # Fetch Serial No doc
        serial_doc = frappe.get_doc("Serial No", self.serial_no)

        # --- Update serial_no_result_parameters ---
        result_params = frappe.db.get_all(
            "NJQCA Result Parameters",
            filters={"parent": self.name},
            fields=[
                "part_config_id",
                "item_group",
                "parameter",
                "value",
                "score",
                "cpu_load",
                "discharge_rate"
            ]
        )
        serial_doc.set("serial_no_result_parameters", [])
        for row in result_params:
            serial_doc.append("serial_no_result_parameters", row)

        # --- Update serial_no_njqca_child ---
        njqca_child_rows = frappe.db.get_all(
            "NJQCA Child",
            filters={"parent": self.name},
            fields=[
                "part_config_id",
                "item_group",
                "part_item_code",
                "variant_1",
                "variant_2",
                "variant_3",
                "variant_4",
                "variant_5",
                "variant_6",
                "part_serial_no",
                "variant_7",
                "variant_8",
                "variant_9",
                "variant_10",
                "variant_11",
                "variant_12",
                "variant_13",
                "variant_14",
                "variant_15",
                "attr_data",
                "update_variant"
            ]
        )
        serial_doc.set("serial_no_njqca_child", [])
        for row in njqca_child_rows:
            serial_doc.append("serial_no_njqca_child", row)

        # Save Serial No doc
        serial_doc.save(ignore_permissions=True)
    def update_serial_no_readings(self):

        if self.rfq_id is not None:
            return

        is_component=frappe.db.get_value('Item Group', self.item_group, 'is_component')
        if is_component is not None and is_component == 1:
            return
        
        # Fetch relevant parameters from NJQCA Result Parameters
        results = frappe.db.sql("""
            SELECT parameter, value 
            FROM `tabNJQCA Result Parameters` 
            WHERE item_group = 'MOTHERBOARD' 
            AND parent = %s
            AND parameter IN (
                'Average_CPU_Load_IDLE', 
                'Average_Discharge_Rate_HEAVY', 
                'Average_Discharge_Rate_IDLE', 
                'Average_CPU_Load_HEAVY'
            )
        """, (self.name,), as_dict=True)

        if not self.serial_no:
            frappe.throw("Serial No not set on NJQCA document.")

        serial_no_doc = frappe.get_doc("Serial No", self.serial_no)

        parameter_map = {
            'Average_CPU_Load_IDLE': 'average_cpu_load_idle',
            'Average_Discharge_Rate_IDLE': 'average_discharge_rate_idle',
            'Average_CPU_Load_HEAVY': 'average_cpu_load_heavy',
            'Average_Discharge_Rate_HEAVY': 'average_discharge_rate_heavy'
        }

        for row in results:
            field_name = parameter_map.get(row.parameter)
            if field_name:
                serial_no_doc.set(field_name, row.value)

        serial_no_doc.set("njqca_reference_name", self.name)

        serial_no_doc.flags.ignore_permissions = True
        serial_no_doc.save(ignore_permissions=True)

    def battery_readings(self):
        if self.item_group != 'BATTERY':
            return
       
        if not self.component_serial_no:
            frappe.throw("Serial No not set on NJQCA document.")
        
        # Check if backup_duration_cycle_1 is more than 60
        if not self.backup_duration_cycle_1 or float(self.backup_duration_cycle_1) <= 60:
            return
        
        try:
            serial_no_doc = frappe.get_doc("Serial No", self.component_serial_no)
            if serial_no_doc.item_group != 'BATTERY':
                frappe.msgprint("Serial No's item group is not 'Battery'. Skipping update.")
                return
            
            # Fetch variant_3, variant_8, variant_10 from NJQCA Child table
            battery_data = frappe.db.get_value(
                "NJQCA Child",
                {
                    "parent": self.name,
                    "item_group": "BATTERY"
                },
                ["variant_3", "variant_8", "variant_10"],
                as_dict=True
            )
            
            if not battery_data:
                frappe.msgprint("No battery readings found in NJQCA Child.")
                return
            
            serial_no_doc.full_charge_capacity = battery_data.variant_3
            serial_no_doc.current_charge_capacity = battery_data.variant_8
            serial_no_doc.health = battery_data.variant_10
            
            # Fetch cpu_load and discharge_rate values
            readings = frappe.db.sql("""
                SELECT cpu_load, discharge_rate
                FROM `tabNJQCA Result Parameters`
                WHERE parent = %s
            """, (self.name,), as_dict=True)
            
            if readings:
                total_cpu = sum(float(row.cpu_load) for row in readings if row.cpu_load is not None)
                total_discharge = sum(float(row.discharge_rate) for row in readings if row.discharge_rate is not None)
                count = len(readings)
                average_cpu_load = round(total_cpu / count, 3) if count else 0
                average_discharge_rate = round(total_discharge / count, 3) if count else 0                
                # Update average fields in Serial No
                serial_no_doc.battery_average_cpu_load = average_cpu_load
                serial_no_doc.battery_average_discharge_rate = average_discharge_rate                
                serial_no_doc.save()
                frappe.msgprint("Battery readings and averages updated successfully.")
                
        except Exception as e:
            log_error(f"Failed to save Serial No: {str(e)}", "Error in battery_readings in NJQCA")
            frappe.msgprint(f"Error saving battery data: {str(e)}")

    def laptop_reports_update(self):
        # Only process Final QC for Laptops
        if self.inspection_type != "Final QC" or self.item_group != "Laptops":
            return

        bios_serialno = self.bios_serialno
        if not bios_serialno:
            frappe.msgprint("BIOS Serial No not found. QC Reports not updated.")
            return

        # Fetch QC check data from NJQCA Result Parameters
        checks_data = frappe.db.sql("""
            SELECT item_group, parameter, value
            FROM `tabNJQCA Result Parameters`
            WHERE parent = %s
        """, (self.name,), as_dict=1)

        if not checks_data:
            frappe.msgprint("No check data found for this inspection.")
            return

        try:
            serial_no_name = frappe.db.get_value("Serial No", {"bios_serial_no": bios_serialno}, "name")
            if not serial_no_name:
                frappe.msgprint(f"No Serial No found with BIOS Serial No {bios_serialno}.")
                return

            serial_doc = frappe.get_doc("Serial No", serial_no_name)

            # Remove all previous Laptop QC reports
            serial_doc.qc_reports = [row for row in serial_doc.qc_reports if row.item_group != "Laptops"]

            # Append only rows from NJQCA Result Parameters
            added_rows = set()
            for check in checks_data:
                key = (check['item_group'], check['parameter'], check['value'])
                if key not in added_rows:
                    serial_doc.append("qc_reports", {
                        "item_group": check['item_group'],
                        "test_details": check['parameter'],
                        "results": check['value']
                    })
                    added_rows.add(key)

            # Update final QC info
            serial_doc.final_qc_by = self.owner
            serial_doc.final_qc_date = self.creation

            serial_doc.save()

        except Exception as e:
            frappe.log_error(f"Error updating QC Reports: {str(e)}", "QC Reports Update Error")


    def performance_reports_update(self):
        if self.inspection_type != "Final QC" or self.item_group != "Laptops":
            return

        try:
            # 1. Get file name from NJQCA Result Parameters
            file_name = frappe.db.get_value(
                "NJQCA Result Parameters",
                {
                    "parent": self.name,
                    "parameter": "heavy_load_File_Updated_name"
                },
                "value"
            )

            if not file_name:
                frappe.msgprint("CSV file name not found.")
                return

            # 2. Get file_url from File doctype
            file_url = frappe.db.get_value("File", file_name, "file_url")
            if not file_url:
                frappe.msgprint("File URL not found.")
                return

            # 3. Build full file path
            file_path = frappe.get_site_path("public" + file_url)

            if not os.path.exists(file_path):
                frappe.msgprint("CSV file does not exist on server.")
                return

            # 4. Load Serial No doc using BIOS serial
            bios_serialno = self.bios_serialno
            if not bios_serialno:
                frappe.msgprint("BIOS Serial No not found.")
                return

            serial_no_name = frappe.db.get_value("Serial No", {"bios_serial_no": bios_serialno}, "name")
            if not serial_no_name:
                frappe.msgprint("Serial No document not found.")
                return

            serial_doc = frappe.get_doc("Serial No", serial_no_name)
            def clean(h):
                return h.replace("\ufeff", "").replace("|", "").strip().lower()

            with open(file_path, newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)

                # Build clean header map
                header_map = {clean(h): h for h in reader.fieldnames}
                serial_doc.set("performance_results", [])
                for row in reader:
                    serial_doc.append("performance_results", {
                        "item_group": "Laptop Adaptors",

                        "time": row.get(header_map.get("time")),
                        "cpu": row.get(header_map.get("cpu %")),
                        "load__cpu_total": row.get(header_map.get("load  cpu total")),

                        "temperature__cpu_package": row.get(header_map.get("temperature  cpu package")),
                        "temperature_cpu_core__two": row.get(header_map.get("temperature  cpu core #2")),
                        "temperature__cpu_core_four": row.get(header_map.get("temperature  cpu core #4")),
                    })

            serial_doc.save(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Performance Reports Update Error")
  
    # def laptop_reports_update(self):
    #     # Only process Final QC for Laptops
    #     if self.inspection_type != "Final QC" or self.item_group != "Laptops":
    #         return

    #     bios_serialno = self.bios_serialno
    #     if not bios_serialno:
    #         frappe.msgprint("BIOS Serial No not found. QC Reports not updated.")
    #         return

    #     # Fetch QC check data from child table
    #     checks_data = frappe.db.sql("""
    #         SELECT item_group, parameter, value
    #         FROM `tabNJQCA Result Parameters`
    #         WHERE parent = %s
    #     """, (self.name,), as_dict=1)

    #     if not checks_data:
    #         frappe.msgprint("No check data found for this inspection.")
    #         return

    #     try:
    #         # Find Serial No document matching BIOS Serial No
    #         serial_no_name = frappe.db.get_value("Serial No", {"bios_serial_no": bios_serialno}, "name")
    #         if not serial_no_name:
    #             frappe.msgprint(f"No Serial No found with BIOS Serial No {bios_serialno}.")
    #             return

    #         serial_doc = frappe.get_doc("Serial No", serial_no_name)

    #         # Keep QC reports for other item groups
    #         other_qc_reports = [row for row in serial_doc.qc_reports if row.item_group != "Laptops"]
    #         serial_doc.qc_reports = other_qc_reports

    #         # Track unique parameters to avoid duplicates in the new batch
    #         new_parameters = set()

    #         # Append new unique Laptop QC reports
    #         for check in checks_data:
    #             if check.parameter not in new_parameters:
    #                 serial_doc.append("qc_reports", {
    #                     "item_group": check.item_group,
    #                     "test_details": check.parameter,
    #                     "results": check.value,
    #                 })
    #                 new_parameters.add(check.parameter)

    #         # Update final QC info
    #         serial_doc.final_qc_by = self.owner
    #         serial_doc.final_qc_date = self.creation

    #         serial_doc.save()

    #     except Exception as e:
    #         frappe.log_error(f"Error updating QC Reports: {str(e)}", "QC Reports Update Error")

    def battery_reports_update(self):
        print("==========================battery_reports_update")
        if self.item_group != "BATTERY":
            return

        bios_serialno = self.bios_serialno
        if not bios_serialno:
            frappe.msgprint("BIOS Serial No not found. Battery Reports not updated.")
            return

        # Fetch QC check data from child table
        checks_data = frappe.db.sql("""
            SELECT item_group, parameter, value, cpu_load
            FROM `tabNJQCA Result Parameters`
            WHERE parent = %s
        """, (self.name,), as_dict=1)

        if not checks_data:
            frappe.msgprint("No check data found for this inspection.")
            return

        try:
            # Find Serial No document matching BIOS Serial No
            serial_no_name = frappe.db.get_value("Serial No", {"bios_serial_no": bios_serialno}, "name")
            if not serial_no_name:
                frappe.msgprint(f"No Serial No found with BIOS Serial No {bios_serialno}.")
                return

            serial_doc = frappe.get_doc("Serial No", serial_no_name)

            # Keep battery_reports for other item groups if needed
            other_reports = [row for row in serial_doc.battery_reports if row.item_group != "BATTERY"]
            serial_doc.battery_reports = other_reports

            # Track unique parameters to avoid duplicates in the new batch
            new_parameters = set()

            # Append new unique Battery QC reports
            for check in checks_data:
                if check.parameter not in new_parameters:
                    serial_doc.append("battery_reports", {
                        "item_group": check.item_group,
                        "test_details": check.parameter,
                        "results": check.value,
                        "cpu_load": check.cpu_load
                    })
                    new_parameters.add(check.parameter)

            serial_doc.save()

        except Exception as e:
            frappe.log_error(f"Error updating Battery Reports: {str(e)}", "Battery Reports Update Error")

    def adaptor_reports_update(self):
        if self.inspection_type != "Final QC - Adaptor" or self.item_group != "Laptop Adaptors":
            return

        bios_serialno = self.bios_serialno
        if not bios_serialno:
            frappe.msgprint("BIOS Serial No not found. Adaptor Reports not updated.")
            return

        # Fetch QC check data from child table
        checks_data = frappe.db.sql("""
            SELECT item_group, parameter, value
            FROM `tabNJQCA Result Parameters`
            WHERE parent = %s
        """, (self.name,), as_dict=1)
        if not checks_data:
            frappe.msgprint("No check data found for this inspection.")
            return

        try:
            # Find Serial No document matching BIOS Serial No
            serial_no_name = frappe.db.get_value("Serial No", {"bios_serial_no": bios_serialno}, "name")
            if not serial_no_name:
                frappe.msgprint(f"No Serial No found with BIOS Serial No {bios_serialno}.")
                return

            serial_doc = frappe.get_doc("Serial No", serial_no_name)

            # Keep other reports intact if any
            other_reports = [row for row in serial_doc.adaptor_reports if row.item_group != "Laptop Adaptors"]
            serial_doc.adaptor_reports = other_reports

            # Track unique parameters to avoid duplicates in the new batch
            new_parameters = set()

            # Append new unique Adaptor QC reports
            for check in checks_data:
                if check.parameter not in new_parameters:
                    serial_doc.append("adaptor_reports", {
                        "item_group": check.item_group,
                        "test_details": check.parameter,
                        "results": check.value
                    })
                    new_parameters.add(check.parameter)

            serial_doc.save()

        except Exception as e:
            frappe.log_error(f"Error updating Adaptor Reports: {str(e)}", "Adaptor Reports Update Error")

    def update_item_groups(self):
        if self.inspection_type != "Final QC" or frappe.db.get_value("Item Group", self.item_group, "is_component"):
            return

        serial_no = self.serial_no
        if not serial_no:
            frappe.msgprint("Serial No not found in serial no field. QC Reports not updated.")
            return

        try:
            if not frappe.db.exists("Serial No", serial_no):
                frappe.msgprint(f"Serial No {serial_no} does not exist in the system.")
                return

            serial_doc = frappe.get_doc("Serial No", serial_no)

            child_data = frappe.get_all(
                "NJQCA Child",
                filters={"parent": self.name},
                fields=[
                    "item_group", "variant_1", "variant_2", "variant_3",
                    "variant_6", "variant_7", "variant_8", "variant_10"
                ]
            )

            field_map = {
                "Laptop RAM": ["variant_6", "variant_7", "variant_8"],
                "Laptop Processors": ["variant_1", "variant_6", "variant_7"],
                "LAPTOP STORAGE": ["variant_6", "variant_10"],
                "WIFI CARD": ["variant_1", "variant_2", "variant_3"]
            }

            serial_doc.item_group_report = []

            for row in child_data:
                item_group = row.item_group
                if item_group not in field_map:
                    continue

                if item_group == "Laptop RAM":
                    if not all([row.variant_6, row.variant_7, row.variant_8]):
                        continue

                if item_group == "LAPTOP STORAGE":
                    if not row.variant_6 or not row.variant_10:
                        continue
                    try:
                        storage_size = int(row.variant_10.split()[0])
                        if storage_size < 64:
                            continue
                    except:
                        continue

                variant_fields = field_map[item_group]
                values = [row.get(field) for field in variant_fields if row.get(field)]

                if values:
                    specification = ", ".join(values)
                    serial_doc.append("item_group_report", {
                        "part": item_group,
                        "specification": specification
                    })

            serial_doc.save()

        except Exception as e:
            log_error(f"Error updating Item Group Report: {str(e)}", "Item Group Report Update Error")

def get_repack_items(self):
    get_repack_items_list = []

    get_repack_items_dict = {
		"repack_item_code": self.item_code,
		"repack_serial_no": self.serial_no,
		"repack_item_base_price": self.base_price,
        "repack_item_source_warehouse": self.warehouse,
	}
    get_repack_items_list.append(get_repack_items_dict)

    get_unpack_items_dict = {
        "unpack_serial_no": self.serial_no,
        "unpack_item_base_price": self.base_price,
        "unpack_item_target_warehouse": self.warehouse,
        "unpack_item_code": self.manual_repack_item_code,
    }
    get_repack_items_list.append(get_unpack_items_dict)

    return get_repack_items_list

def get_variant_for_grade(item_code, target_grade):
    variant_of = frappe.db.get_value("Item", item_code, "variant_of")
    if not variant_of:
        return None
        
    attrs = frappe.get_all(
        "Item Variant Attribute",
        filters={"parent": item_code},
        fields=["attribute", "attribute_value"],
    )
    
    target_attrs = []
    grade_found = False
    for a in attrs:
        if a.attribute.lower() == "grade":
            target_attrs.append({"attribute": a.attribute, "attribute_value": target_grade})
            grade_found = True
        else:
            target_attrs.append(a)
            
    if not grade_found:
        return None
        
    joins = []
    conditions = []
    for i, attr in enumerate(target_attrs):
        alias = f"a{i}"
        joins.append(f"JOIN `tabItem Variant Attribute` {alias} ON v.name = {alias}.parent AND {alias}.attribute = %s AND {alias}.attribute_value = %s")
        conditions.extend([attr['attribute'], attr['attribute_value']])
        
    query = f"SELECT v.name FROM `tabItem` v {' '.join(joins)} WHERE v.variant_of = %s AND v.disabled = 0 LIMIT 1"
    conditions.append(variant_of)
    
    res = frappe.db.sql(query, tuple(conditions))
    return res[0][0] if res else None

def get_serial_no_component_copy_fields():
    child_meta = frappe.get_meta("Serial No Component")

    skip_fields = {
        "name",
        "owner",
        "creation",
        "modified",
        "modified_by",
        "docstatus",
        "parent",
        "parentfield",
        "parenttype",
        "idx",
    }

    skip_fieldtypes = {
        "Section Break",
        "Column Break",
        "Tab Break",
        "HTML",
        "Button",
    }

    return [
        df.fieldname
        for df in child_meta.fields
        if df.fieldname
        and df.fieldname not in skip_fields
        and df.fieldtype not in skip_fieldtypes
    ]


def get_previous_serial_no_component_rows(serial_no_doc):
    copy_fields = get_serial_no_component_copy_fields()
    previous_rows = {}

    for row in serial_no_doc.get("serial_no_component") or []:
        item_group = (row.get("item_group") or "").strip()

        if not item_group:
            continue

        previous_rows.setdefault(item_group, []).append({
            fieldname: row.get(fieldname)
            for fieldname in copy_fields
        })

    return previous_rows


def get_unknown_grade():
    return frappe.db.get_value(
        "NJ Settings",
        {"parameter": "unk_grade"},
        "value"
    ) or "UNKNOWN"


def is_unknown_grade(grade):
    unk_grade = get_unknown_grade()
    return (grade or "").strip().lower() == (unk_grade or "UNKNOWN").strip().lower()


def get_item_code_for_model_change_grade(default_item_code, old_grade, item_group):
    """
    Take new Item Wizard default item code,
    then apply old Part List grade to get correct variant.
    """

    unk_grade = get_unknown_grade()
    old_grade = old_grade or unk_grade

    if is_unknown_grade(old_grade):
        return default_item_code, unk_grade

    target_variant = get_variant_for_grade(default_item_code, old_grade)

    if not target_variant:
        frappe.throw(
            f"When changing the model, Item Group <b>{item_group}</b> has old Grade "
            f"<b>{old_grade}</b>, but matching variant was not found for new Item Wizard item "
            f"<b>{default_item_code}</b>. Please contact <b>NPD</b> Team."
        )

    return target_variant, old_grade


def rebuild_serial_no_components_for_model_change(serial_no_doc, item_wizard_doc, newmodel):
    """
    Model-change Part List rebuild.

    Rules:
    1. Serialized old rows: keep exactly as-is.
    2. Non-serialized old rows:
       - use new Item Wizard default item code
       - apply old Part List grade
       - update item to matching grade variant
    3. New item_group from Item Wizard:
       - add default item code
       - grade UNKNOWN
    """

    previous_rows = get_previous_serial_no_component_rows(serial_no_doc)
    unk_grade = get_unknown_grade()

    serial_no_doc.model = newmodel
    serial_no_doc.item_wizard = item_wizard_doc.name

    item_group_idx_value = int(serial_no_doc.max_item_group_idx or 0)

    for old_rows in previous_rows.values():
        for old_row in old_rows:
            old_idx = int(old_row.get("item_group_idx") or 0)
            if old_idx > item_group_idx_value:
                item_group_idx_value = old_idx

    serial_no_doc.set("serial_no_component", [])

    processed_item_groups = set()

    for component in item_wizard_doc.get("component") or []:
        if int(component.get("mandatory") or 0) != 1:
            continue

        item_group = (component.get("component_type") or "").strip()

        if not item_group:
            continue

        if item_group in processed_item_groups:
            continue

        processed_item_groups.add(item_group)

        default_item_code = component.get("default_item_code")
        component_qty = component.get("quantity") or 1

        old_rows_for_group = previous_rows.get(item_group) or []

        if old_rows_for_group:
            for old_row in old_rows_for_group:
                # Serialized part: keep full old row.
                if old_row.get("component_serial_no"):
                    serial_no_doc.append("serial_no_component", old_row)
                    continue

                # Non-serialized part: new IW item code + old grade.
                new_row = dict(old_row)
                old_grade = old_row.get("grade") or unk_grade

                target_item_code, target_grade = get_item_code_for_model_change_grade(
                    default_item_code,
                    old_grade,
                    item_group
                )

                new_row["item"] = target_item_code
                new_row["grade"] = target_grade
                new_row["quantity"] = component_qty

                serial_no_doc.append("serial_no_component", new_row)

            continue

        # Item group not present in old Part List.
        item_group_idx_value += 1

        serial_no_doc.append("serial_no_component", {
            "is_available": 1,
            "item_group": item_group,
            "item": default_item_code,
            "quantity": component_qty,
            "grade": unk_grade,
            "item_group_idx": item_group_idx_value,
        })

    # Keep serialized rows even if that item_group is not in new Item Wizard.
    for item_group, old_rows in previous_rows.items():
        if item_group in processed_item_groups:
            continue

        for old_row in old_rows:
            if old_row.get("component_serial_no"):
                serial_no_doc.append("serial_no_component", old_row)

    serial_no_doc.max_item_group_idx = item_group_idx_value

    return serial_no_doc

def apply_previous_grades_to_components(serial_no_doc, previous_grades):
    unk_grade = frappe.db.get_value('NJ Settings', {'parameter': 'unk_grade'}, 'value') or "UNKNOWN"
    
    for row in serial_no_doc.get("serial_no_component"):
        # Only apply this to the new placeholders (those WITHOUT component_serial_no)
        if not row.component_serial_no:
            old_grade = previous_grades.get(row.item_group)
            if old_grade and old_grade != unk_grade:
                target_variant = get_variant_for_grade(row.item, old_grade)
                if target_variant:
                    row.item = target_variant
                    row.grade = old_grade
                else:
                    frappe.throw(f"When changing the model, we don't have a variant for Grade <b>{old_grade}</b> for Item <b>{row.item}</b> (Item Group: <b>{row.item_group}</b>). Please contact NPD Team.")

@frappe.whitelist()
def model_change_for_serial_no(newmodel, serial_no):
    user = frappe.session.user
    role_profile = frappe.db.get_value('Employee', {'user_id': user, 'status': 'Active'}, 'role_profile')
    
    if not frappe.db.get_value('Role Profile', {'name': role_profile}, 'restrict_repack'):
        frappe.msgprint("You don't have access to change 'Model'.")
        return {"status": "failed"}

    wizard_query = """Select name from `tabItem Wizards` where model = %s 
                    and part_list_status = 'Completed' order by modified desc"""
    new_item_wizard = frappe.db.sql(wizard_query, (newmodel,), as_dict=1)

    if not new_item_wizard:
        frappe.msgprint(f'Item Wizard is not there for Model <b>{newmodel}</b>. Please Contact NPD Team')
        return { "status": "failed" }

    qi_exists = """select name from `tabNJ Quality Inspection` where barcode = %s"""
    kitting_exists = """select name from `tabKitting` where serial_no = %s"""
    mpc_exists = """select name from `tabMachine Part Changes` where serial_no = %s"""
    mr_exists = """select parent from `tabMaterial Request Item` where serial_no = %s"""

    qi_exists_data = frappe.db.sql(qi_exists, (serial_no), as_dict=1)
    kitting_exists_data = frappe.db.sql(kitting_exists,serial_no,as_dict=1)
    mpc_exists_data = frappe.db.sql(mpc_exists,serial_no,as_dict=1)
    mr_exists_data = frappe.db.sql(mr_exists,serial_no,as_dict=1)

    serial_no_doc = frappe.get_doc('Serial No', serial_no)

    if qi_exists_data == [] and kitting_exists_data == [] and mpc_exists_data == [] and mr_exists_data == []:
        if new_item_wizard:
            item_wizard_doc = frappe.get_doc("Item Wizards",new_item_wizard[0]['name'])
            if item_wizard_doc.part_list_status != 'Completed':
                return { "status": "failed" }

            if newmodel:
                rebuild_serial_no_components_for_model_change(
                    serial_no_doc,
                    item_wizard_doc,
                    newmodel
                )
                serial_no_doc.save(ignore_permissions=True)
                return { "status": "success" }
        else:
            frappe.msgprint(f'Item Wizard is not there for Model <b>{newmodel}</b>. Please Contact NPD Team')
            return { "status": "failed" }

    else:
        new_item_wizard_query = """Select component_type,default_item_code from `tabComponent` where parent = %s"""
        new_item_wizard_data = frappe.db.sql(new_item_wizard_query, (new_item_wizard[0]['name']), as_dict=1)

        Serial_no_model = serial_no_doc.model

        if Serial_no_model:
            item_wizard = frappe.db.get_value('Item Wizards', {'model':Serial_no_model, 'part_list_status':'Completed'}, 'name')
            if item_wizard:
                old_item_wizard_query = """select component_type,default_item_code from `tabComponent` where parent = %s"""
                old_item_wizard_data = frappe.db.sql(old_item_wizard_query, (item_wizard), as_dict=1)

                not_matched_item_groups = []

                for old in old_item_wizard_data:
                    for new in new_item_wizard_data:
                        if old.get('component_type') == new.get('component_type'):
                            if old.get('default_item_code') == new.get('default_item_code'):
                                continue
                            else:
                                old_item_code = old.get('default_item_code')
                                new_item_wizard_name = new_item_wizard[0]['name']
                                item_group = old.get('component_type')
                                result = check_atrribute_data_is_matching_or_not(
                                    old_item_code,
                                    item_group,
                                    new_item_wizard_name
                                )
                                if not result:
                                    not_matched_item_groups.append(old.get('component_type'))

                if not not_matched_item_groups:
                    item_wizard_doc = frappe.get_doc("Item Wizards",new_item_wizard[0]['name'])

                    rebuild_serial_no_components_for_model_change(
                        serial_no_doc,
                        item_wizard_doc,
                        newmodel
                    )

                    serial_no_doc.save(ignore_permissions=True)
                    return { "status": "success" }
                
                else:
                    mr_data_query ="""select distinct(item_group) from `tabMaterial Request Item` where serial_no = %s AND post_order_status !='Completed' AND docstatus = 1"""
                    past_part_list_query = """select distinct(item_group) from `tabPast Part List` where parent = %s"""

                    mr_item_group_data = frappe.db.sql(mr_data_query, (serial_no), as_dict=1)
                    past_part_list_data = frappe.db.sql(past_part_list_query, (serial_no), as_dict=1)

                    if past_part_list_data or mr_item_group_data:
                        for group in past_part_list_data:
                            if group['item_group'] in not_matched_item_groups:
                                frappe.msgprint(f'Item Group <b>{group["item_group"]}</b> is in Past Part List.Cannot change Model and Part List. Please contact <b>NPD</b> Team.')
                                return { "status": "failed" }

                        for group in mr_item_group_data:
                            if group['item_group'] in not_matched_item_groups:
                                frappe.msgprint(f'Item Group <b>{group["item_group"]}</b> MR is Raised.Cannot change Model and Part List. Please contact <b>NPD</b> Team.')
                                return { "status": "failed" }
                    
                    item_wizard_doc = frappe.get_doc("Item Wizards",new_item_wizard[0]['name'])

                    rebuild_serial_no_components_for_model_change(
                        serial_no_doc,
                        item_wizard_doc,
                        newmodel
                    )

                    serial_no_doc.save(ignore_permissions=True)
                    return { "status": "success" }

            else:
                frappe.msgprint(f'Item Wizard is not there for Model <b>{Serial_no_model}</b>. Please Contact NPD Team')
                return { "status": "failed" }
        else:
            frappe.msgprint(f'Model not found in Serial No {serial_no}')
            return { "status": "failed" }



def check_atrribute_data_is_matching_or_not(old_item_code,item_group,new_item_wizard):
    item_code_attribute_query = """select attribute,attribute_value from `tabItem Variant Attribute` where parent = %s"""
    item_code_attribute_data = frappe.db.sql(item_code_attribute_query, (old_item_code), as_dict=1)

    new_item_wizard_attribute_query = """select item_group,item_attribute,attribute_value from `tabItems Attribute` where parent = %s"""
    new_item_wizard_attribute_data = frappe.db.sql(new_item_wizard_attribute_query, (new_item_wizard), as_dict=1)
    for old in item_code_attribute_data:
        same_attr_new = [new for new in new_item_wizard_attribute_data 
                        if new.get('item_attribute') == old.get('attribute') and new.get('item_group') == item_group]
        
        if same_attr_new:  # attribute exists in new data
            if not any(new.get('attribute_value') == old.get('attribute_value') 
                    for new in same_attr_new):
                return False
    return True


@frappe.whitelist()
def get_info_from_serial_no(doc=None):
    sle = []
    result = {}
    doc_json = json.loads(doc)
    is_component = frappe.db.get_value('Item Group', doc_json.get('item_group'), 'is_component')
    if is_component is not None and is_component == 1:
        return ""

    serial_no = doc_json.get('serial_no')

    emp_dept = get_active_emp(frappe.session.user, fields=['department'])
    if isinstance(emp_dept, list):
        emp_dept = emp_dept[0] if emp_dept else {}

    if 'bios_serialno' in doc_json:

        bios_serial_no_in_ui = doc_json['bios_serialno']

        sql_query = """
            SELECT name,item_code, warehouse, purchase_rate, status,
                bios_serial_no, model, item_group, brand
            FROM `tabSerial No`
            WHERE bios_serial_no = %s"""

        sle = frappe.db.sql(sql_query, (bios_serial_no_in_ui), as_dict=1)

        if 'serial_no' in doc_json and not sle:
            serial_no = doc_json['serial_no']

            sql_query = """
                SELECT name,item_code, warehouse, purchase_rate, status,
                    bios_serial_no, model, item_group, brand
                FROM `tabSerial No`
                WHERE name = %s"""

            sle = frappe.db.sql(sql_query, (serial_no,), as_dict=1)

        if sle:
            sle_entry = sle[0]
            if sle_entry.get('status') != 'Active' and sle_entry.get('item_group') in ['Laptop', 'Chromebooks']:
                frappe.throw(f"Serial No: <b>{serial_no}</b> is not active.")

            non_njqca_item_groups = frappe.db.get_value('NJ Settings', {'parameter': 'non_njqca_item_groups'}, 'value')
            serial_no = sle_entry.get('name')

            if non_njqca_item_groups:
                sn_model = frappe.get_value('Serial No', {'name': serial_no}, 'model')
                manufacturer_model = frappe.get_all('Manufacturer Model Child', {'parent': sn_model}, ['manufacturer_model'], order_by='idx')

                if sle_entry.get('item_group') in non_njqca_item_groups and manufacturer_model:
                    result.update({'manufacturer_model': manufacturer_model[0].get("manufacturer_model")})
                else:
                    if sle_entry.get('bios_serial_no') and sle_entry.get('bios_serial_no').upper() != bios_serial_no_in_ui.upper():
                        frappe.throw(f"BIOS Serial No is not matching for Serial No: <b>{serial_no}</b>.")
                    elif bios_serial_no_in_ui and not frappe.db.get_value('Item Group', doc_json.get('item_group'), 'is_component'):
                        frappe.db.sql(
                            """UPDATE `tabSerial No` SET bios_serial_no = %s WHERE serial_no = %s""",
                            (bios_serial_no_in_ui, serial_no)
                        )
            else:
                frappe.throw(f"NJ Settings for non_njqca_item_groups is not defined.")

    if sle:
        sle_entry = sle[0]
        item_code_data = frappe.get_value('Item', {'name': sle_entry.get('item_code')}, ['valuation_rate', 'item_model', 'brand', 'variant_of', 'item_group'], as_dict=1) or {}

        resolved_brand = _resolve_item_brand(
            serial_brand=sle_entry.get('brand'),
            item_brand=item_code_data.get('brand'),
            item_code=sle_entry.get('item_code'),
            variant_of=item_code_data.get('variant_of'),
        )
        resolved_model = sle_entry.get('model') or item_code_data.get('item_model')

        result.update({
            'warehouse': sle_entry.get('warehouse'),
            'base_price': sle_entry.get('purchase_rate'),
            'repack_itm_price': item_code_data.get('valuation_rate'),
            'department': emp_dept.get('department') if emp_dept else None,
            'brand': resolved_brand,
            'model': resolved_model,
        })

        item_group = sle_entry.get('item_group') or item_code_data.get('item_group')
        raw_item_groups = frappe.db.get_value('NJ Settings', {'parameter': 'njqca_battery_item_group'}, 'value') or ''
        nj_settings_item_group = [g.strip() for g in raw_item_groups.split(',') if g.strip()]
        doc_item_group = doc_json.get('item_group')

        if doc_item_group and doc_item_group not in nj_settings_item_group:
            result['item_group'] = item_group
            result['serial_no'] = sle_entry.get('name')

        if 'serial_no' in doc_json:
            result['item_code'] = frappe.db.get_value('Serial No', {'name': serial_no}, 'item_code')
        elif doc_item_group and doc_item_group in nj_settings_item_group:
            pass
        else:
            result['item_code'] = sle_entry.get('item_code')

    result['inspection_type'] = get_inspection_type() if 'inspection_type' not in doc_json else doc_json['inspection_type']

    return result

    
@frappe.whitelist()
def get_info_from_component_serial_no(doc=None):
    try:
        sle = []
        result = {}
        doc_json = json.loads(doc)
        serial_no = doc_json.get('component_serial_no')
        emp_dept = get_active_emp(frappe.session.user, fields=['department'])

        if 'component_serial_no' in doc_json:

            sql_query = """
                SELECT name,item_code, warehouse, purchase_rate,
                    item_group, brand
                FROM `tabSerial No`
                WHERE name = %s """

            sle = frappe.db.sql(sql_query, (serial_no), as_dict=1)
        
        if sle and len(sle) > 0:
            sle_entry = sle[0]
            item_code_data = frappe.get_value('Item', {'name': sle_entry.get('item_code')}, ['valuation_rate', 'item_model', 'brand', 'variant_of', 'item_group'], as_dict=1) or {}
            resolved_brand = _resolve_item_brand(
                serial_brand=sle_entry.get('brand'),
                item_brand=item_code_data.get('brand'),
                item_code=sle_entry.get('item_code'),
                variant_of=item_code_data.get('variant_of'),
            )
            resolved_model = item_code_data.get('item_model')

            result.update({
                'warehouse': sle_entry.get('warehouse',""),
                'base_price': sle_entry.get('purchase_rate'),
                'repack_itm_price': item_code_data.get('valuation_rate') if item_code_data else None,
                'department': emp_dept.get('department') if emp_dept else None,
                'brand': resolved_brand,
                'model': resolved_model,
            })

            result['item_code'] = sle_entry.get('item_code')
            result['manual_repack_item_code']=sle_entry.get('item_code')
    
        result['inspection_type'] = get_inspection_type() if not 'inspection_type' in doc_json else doc_json['inspection_type']

        return result
    
    except Exception as e:
        log_error(traceback.format_exc(), "Error on get_info_component_serial_no in NJQCA")
        return f"Error while getting component serial info: {str(e)}"

@frappe.whitelist()
def after_save_njqca(docname, component_serial_no=None, brand=None, model=None, qi_type=None):
    njqca_qi_trace("after_save_njqca_start", docname, {
        "component_serial_no": component_serial_no,
        "brand": brand,
        "model": model,
        "qi_type": qi_type
    })

    ignore_part_validation = frappe.db.get_value('Inspection Type', doc.inspection_type, 'ignore_part_validation')
    if not int(ignore_part_validation):
        update_part_item_code_from_child(doc)
    try:
        doc = frappe.get_doc("NJQCA", docname)

        njqca_qi_trace("after_save_doc_loaded", docname, {
            "docstatus": doc.docstatus,
            "serial_no": doc.serial_no,
            "component_serial_no": doc.component_serial_no,
            "bios_serialno": doc.bios_serialno,
            "power_on": doc.power_on,
            "inspection_type": doc.inspection_type,
            "item_group": doc.item_group,
            "manual_repack_item_code": doc.manual_repack_item_code,
            "existing_qi_name": doc.qi_name
        })

        ignore_part_validation = frappe.db.get_value(
            "Inspection Type",
            doc.inspection_type,
            "ignore_part_validation"
        )

        njqca_qi_trace("ignore_part_validation_value", docname, {
            "inspection_type": doc.inspection_type,
            "ignore_part_validation": ignore_part_validation
        })

        # Safer than int(ignore_part_validation), because None / "" can crash
        if not int(ignore_part_validation or 0):
            njqca_qi_trace("before_update_part_item_code_from_child", docname)
            update_part_item_code_from_child(doc)
            njqca_qi_trace("after_update_part_item_code_from_child", docname)
        else:
            njqca_qi_trace("skip_update_part_item_code_from_child", docname, {
                "reason": "Inspection Type has ignore_part_validation enabled"
            })

        if not doc.bios_serialno:
            njqca_qi_trace("qi_not_created_bios_missing", docname, {
                "serial_no": doc.serial_no,
                "power_on": doc.power_on
            }, error=True)

            frappe.throw(
                f"BIOS Serial No is not found for Serial No: <b>{doc.serial_no}</b>."
            )

        if doc.power_on != "Yes":
            njqca_qi_trace("qi_not_created_power_on_not_yes", docname, {
                "power_on": doc.power_on,
                "serial_no": doc.serial_no,
                "bios_serialno": doc.bios_serialno
            }, error=True)

            frappe.msgprint(
                f"QI Draft is not created for Serial No: <b>{doc.serial_no}</b> because Power On is <b>{doc.power_on}</b>."
            )
            return {
                "status": "skipped",
                "reason": "Power On is not Yes",
                "power_on": doc.power_on
            }

        njqca_qi_trace("before_open_draft_qi", docname, {
            "qi_type": qi_type,
            "serial_no": doc.serial_no,
            "component_serial_no": component_serial_no,
            "brand": brand,
            "model": model
        })

        if qi_type == "is_defective":
            qi_draft_data = open_draft_qi(
                doc,
                component_serial_no,
                brand,
                model,
                is_defective="1"
            )

        elif qi_type == "re_check":
            qi_draft_data = open_draft_qi(
                doc,
                component_serial_no,
                brand,
                model,
                re_check="1"
            )

        else:
            qi_draft_data = open_draft_qi(
                doc,
                component_serial_no,
                brand,
                model
            )

        njqca_qi_trace("after_open_draft_qi", docname, {
            "qi_draft_data": qi_draft_data
        }, error=not bool((qi_draft_data or {}).get("qi_name")))

        return qi_draft_data

    except Exception:
        njqca_qi_trace("after_save_njqca_exception", docname, {
            "traceback": frappe.get_traceback()
        }, error=True)

        frappe.throw(f"Error in after_save_njqca: {frappe.get_traceback()}")

from frappe.utils import cint
from nj_lib.utils.stock_entry import stock_entry_using_nj_lib
from nj_p1_features.nj_p1_features.doctype.machine_part_changes.machine_part_changes import get_part_ledger_entry


def update_part_item_code_from_child(doc):
    child_table_map = {
        "njqca_laptop_ram": "NJQCA Laptop Ram",
        "njqca_laptop_storage": "NJQCA Laptop Storage"
    }

    serial_no_doc = frappe.get_doc("Serial No", doc.serial_no)
    updated = False

    print(f"\n=== START update_part_item_code_from_child | Doc: {doc.doctype} | Name: {doc.name} | Serial No: {doc.serial_no} ===")

    # ---------------------------------------------------------
    # PRE-CLEAN: remove all existing Laptop RAM / Laptop Storage
    # rows from Serial No, but keep rows having component_serial_no
    # ---------------------------------------------------------
    target_item_groups = set()

    for table_field in child_table_map:
        for child in (doc.get(table_field) or []):
            if child.get("item_group"):
                target_item_groups.add(child.get("item_group"))

    if target_item_groups:
        for sn in list(serial_no_doc.serial_no_component):
            if sn.item_group in target_item_groups and not sn.component_serial_no:
                print(
                    f"[PRE-REMOVE] serial_component={sn.name} | "
                    f"item_group={sn.item_group} | item_group_idx={sn.item_group_idx} | "
                    f"item={sn.item} | grade={sn.grade}"
                )
                serial_no_doc.serial_no_component.remove(sn)
                updated = True

    # Build map by component_serial_no for serialized rows
    component_serial_map = {}
    for sn in serial_no_doc.serial_no_component:
        if sn.component_serial_no:
            component_serial_map[sn.component_serial_no] = sn

    # Build existing map by (item_group, item_group_idx) for non-serialized rows
    existing_map = {}
    for sn in serial_no_doc.serial_no_component:
        key = (sn.item_group, cint(sn.item_group_idx))
        existing_map[key] = sn

    # Always calculate fresh max idx from actual child table
    current_max_idx = max(
        [cint(d.item_group_idx) for d in serial_no_doc.serial_no_component if d.item_group_idx],
        default=0
    )

    # Fetch expense_account once
    expense_account = frappe.db.get_single_value(
        "NewJaisa Configuration",
        "default_operational_cost_account"
    )

    for table_field, item_group_label in child_table_map.items():
        child_items = doc.get(table_field) or []

        for child in child_items:
            grade = child.get("grade")
            calculated_item_code = child.get("calculated_item_code")
            item_group = child.get("item_group")
            item_group_idx = cint(child.get("item_group_idx"))
            component_serial_no = child.get("component_serial_no")

            if not (calculated_item_code and item_group):
                print(
                    f"[SKIP] table={table_field} child={child.get('name')} | "
                    f"missing calculated_item_code/item_group"
                )
                continue

            # ---------------------------------------------------------
            # CASE 1: Row has component_serial_no → match by it
            # Check if item code changed, if yes do full 3 step repack flow
            # STEP 1: Unpack parent laptop → component OUT (becomes Active)
            # STEP 2: Grade change component (now Active in stock)
            # STEP 3: Repack component back into parent laptop
            # ---------------------------------------------------------
            if component_serial_no:
                existing_row = component_serial_map.get(component_serial_no)

                if not existing_row:
                    print(
                        f"[SKIP] component_serial_no={component_serial_no} | "
                        f"no matching serial_no_component row found"
                    )
                    continue

                fetched_item_code = existing_row.item

                if not fetched_item_code:
                    print(
                        f"[SKIP] component_serial_no={component_serial_no} | "
                        f"fetched_item_code is empty"
                    )
                    continue

                if fetched_item_code == calculated_item_code:
                    print(
                        f"[NO CHANGE] component_serial_no={component_serial_no} | "
                        f"item already matches: {fetched_item_code}"
                    )
                    continue

                print(
                    f"[GRADE CHANGE] component_serial_no={component_serial_no} | "
                    f"fetched={fetched_item_code} → calculated={calculated_item_code}"
                )

                # Fetch parent laptop details
                parent_item = frappe.db.get_value("Serial No", doc.serial_no, "item_code")
                parent_warehouse = frappe.db.get_value("Serial No", doc.serial_no, "warehouse")

                if not parent_warehouse:
                    sle = frappe.db.sql("""
                        SELECT warehouse
                        FROM `tabStock Ledger Entry`
                        WHERE serial_no = %s
                          AND is_cancelled = 0
                          AND qty_after_transaction > 0
                        ORDER BY posting_date DESC, posting_time DESC
                        LIMIT 1
                    """, (doc.serial_no,), as_list=True)
                    parent_warehouse = sle[0][0] if sle else None

                if not parent_warehouse:
                    frappe.log_error(
                        f"Warehouse not found for parent serial_no={doc.serial_no}",
                        "update_part_item_code_from_child"
                    )
                    continue

                # Fetch component warehouse from SLE since it is packed inside parent
                comp_warehouse = frappe.db.sql("""
                    SELECT warehouse
                    FROM `tabStock Ledger Entry`
                    WHERE item_code = %s
                      AND serial_no = %s
                      AND is_cancelled = 0
                      AND qty_after_transaction > 0
                    ORDER BY posting_date DESC, posting_time DESC
                    LIMIT 1
                """, (fetched_item_code, component_serial_no), as_list=True)
                comp_warehouse = comp_warehouse[0][0] if comp_warehouse else parent_warehouse

                parent_val = get_part_ledger_entry(parent_item, doc.serial_no) or 0
                comp_val = get_part_ledger_entry(fetched_item_code, component_serial_no) or 0
                parent_base_value = parent_val - comp_val
                if parent_base_value < 0:
                    parent_base_value = 0

                # ==============================================
                # STEP 1 — UNPACK parent laptop
                # Parent laptop IN → component OUT + base parent back IN
                # ==============================================
                print(f"[STEP 1] Unpacking parent laptop={doc.serial_no} to bring component={component_serial_no} into stock")

                unpack_items = [
                    {
                        "repack_item_code": parent_item,
                        "repack_serial_no": doc.serial_no,
                        "repack_item_source_warehouse": parent_warehouse,
                        "repack_item_base_price": parent_val,
                    },
                    {
                        "unpack_item_code": fetched_item_code,
                        "unpack_serial_no": component_serial_no,
                        "unpack_item_target_warehouse": comp_warehouse,
                        "unpack_item_base_price": comp_val,
                    },
                    {
                        "unpack_item_code": parent_item,
                        "unpack_serial_no": doc.serial_no,
                        "unpack_item_target_warehouse": parent_warehouse,
                        "unpack_item_base_price": parent_base_value,
                    },
                ]

                stock_entry_using_nj_lib(frappe.as_json({
                    "name": doc.name,
                    "doctype": doc.doctype,
                    "stock_entry_type": "Repack",
                    "expense_account": expense_account,
                    "repack_items": unpack_items,
                }))

                print(f"[STEP 1 DONE] component={component_serial_no} is now Active in warehouse={comp_warehouse}")

                # ==============================================
                # STEP 2 — GRADE CHANGE component
                # fetched_item_code IN → calculated_item_code OUT
                # component is now Active in stock after step 1
                # ==============================================
                print(f"[STEP 2] Grade change component={component_serial_no} | {fetched_item_code} → {calculated_item_code}")

                grade_change_items = [
                    {
                        "repack_item_code": fetched_item_code,
                        "repack_serial_no": component_serial_no,
                        "repack_item_source_warehouse": comp_warehouse,
                        "repack_item_base_price": comp_val,
                        "unpack_item_code": calculated_item_code,
                        "unpack_serial_no": component_serial_no,
                        "unpack_item_target_warehouse": comp_warehouse,
                        "unpack_item_base_price": comp_val,
                    }
                ]

                stock_entry_using_nj_lib(frappe.as_json({
                    "name": doc.name,
                    "doctype": doc.doctype,
                    "stock_entry_type": "Repack",
                    "expense_account": expense_account,
                    "repack_items": grade_change_items,
                }))

                print(f"[STEP 2 DONE] component={component_serial_no} item changed to {calculated_item_code}")

                # ==============================================
                # STEP 3 — REPACK component back into parent laptop
                # base parent IN + calculated_item_code IN → parent laptop OUT
                # ==============================================
                print(f"[STEP 3] Repacking component={component_serial_no} back into parent laptop={doc.serial_no}")

                final_parent_val = get_part_ledger_entry(parent_item, doc.serial_no) or 0
                final_comp_val = get_part_ledger_entry(calculated_item_code, component_serial_no) or 0

                repack_items = [
                    {
                        "repack_item_code": parent_item,
                        "repack_serial_no": doc.serial_no,
                        "repack_item_source_warehouse": parent_warehouse,
                        "repack_item_base_price": final_parent_val,
                    },
                    {
                        "repack_item_code": calculated_item_code,
                        "repack_serial_no": component_serial_no,
                        "repack_item_source_warehouse": comp_warehouse,
                        "repack_item_base_price": final_comp_val,
                    },
                    {
                        "unpack_item_code": parent_item,
                        "unpack_serial_no": doc.serial_no,
                        "unpack_item_target_warehouse": parent_warehouse,
                        "unpack_item_base_price": final_parent_val + final_comp_val,
                    },
                ]

                stock_entry_using_nj_lib(frappe.as_json({
                    "name": doc.name,
                    "doctype": doc.doctype,
                    "stock_entry_type": "Repack",
                    "expense_account": expense_account,
                    "repack_items": repack_items,
                }))

                print(f"[STEP 3 DONE] parent laptop={doc.serial_no} repacked with updated component={component_serial_no}")

                # Update serial_no_component row
                existing_row.item = calculated_item_code
                existing_row.grade = grade
                existing_row.reference_doctype = doc.doctype
                existing_row.reference_doctype_no = doc.name
                updated = True

                # Update the component Serial No's item_code as well
                frappe.db.set_value(
                    "Serial No",
                    component_serial_no,
                    "item_code",
                    calculated_item_code,
                    update_modified=False
                )

                print(
                    f"[UPDATED] component_serial_no={component_serial_no} | "
                    f"item: {fetched_item_code} → {calculated_item_code}"
                )
                continue

            # ---------------------------------------------------------
            # CASE 2: No component_serial_no → match by (item_group, item_group_idx)
            # Original flow unchanged
            # ---------------------------------------------------------
            if not item_group_idx:
                current_max_idx += 1
                item_group_idx = current_max_idx
                child.item_group_idx = item_group_idx
                print(
                    f"[NEW IDX] table={table_field} child={child.get('name')} | "
                    f"item_group={item_group} | assigned item_group_idx={item_group_idx}"
                )

            key = (item_group, item_group_idx)
            existing_row = existing_map.get(key)

            if existing_row:
                changes = []

                if existing_row.item != calculated_item_code:
                    changes.append(f"item: {existing_row.item} -> {calculated_item_code}")
                    existing_row.item = calculated_item_code

                if existing_row.grade != grade:
                    changes.append(f"grade: {existing_row.grade} -> {grade}")
                    existing_row.grade = grade

                if existing_row.reference_doctype != doc.doctype:
                    changes.append(f"reference_doctype: {existing_row.reference_doctype} -> {doc.doctype}")
                    existing_row.reference_doctype = doc.doctype

                if existing_row.reference_doctype_no != doc.name:
                    changes.append(f"reference_doctype_no: {existing_row.reference_doctype_no} -> {doc.name}")
                    existing_row.reference_doctype_no = doc.name

                if changes:
                    updated = True
                    print(
                        f"[UPDATE] serial_component={existing_row.name} | "
                        f"item_group={item_group} | item_group_idx={item_group_idx} | "
                        + " | ".join(changes)
                    )
                else:
                    print(
                        f"[NO CHANGE] serial_component={existing_row.name} | "
                        f"item_group={item_group} | item_group_idx={item_group_idx}"
                    )

            else:
                row = serial_no_doc.append("serial_no_component", {})
                row.item = calculated_item_code
                row.item_group = item_group
                row.item_group_idx = item_group_idx
                row.is_available = 1
                row.grade = grade
                row.quantity = 1
                row.reference_doctype = doc.doctype
                row.reference_doctype_no = doc.name

                updated = True
                existing_map[key] = row

                print(
                    f"[ADD] serial_component={row.name} | "
                    f"item_group={item_group} | item_group_idx={item_group_idx} | "
                    f"item={calculated_item_code} | grade={grade}"
                )

    # Update max_item_group_idx
    serial_no_doc.max_item_group_idx = max(
        [cint(d.item_group_idx) for d in serial_no_doc.serial_no_component if d.item_group_idx],
        default=0
    )

    if updated:
        print(
            f"[SAVE] Serial No document {serial_no_doc.name} is being saved | "
            f"max_item_group_idx={serial_no_doc.max_item_group_idx}"
        )
        serial_no_doc.save(ignore_permissions=True)
    else:
        print(f"[NO SAVE] No changes found for Serial No {serial_no_doc.name}")


def get_item_code_for_each_part(doc):
    item_group, item_template = '', ''
    part_data, part_mapping, child_attr_data = [], [], []

    try:
        if isinstance(doc, str):
            try:
                doc = json.loads(doc)
            except json.JSONDecodeError:
                frappe.throw("Invalid JSON string provided for doc.")

        parent_part_mapping = frappe.get_all( "Part Mapping",
            filters={"parent": doc.get('item_group')},
            fields=["item_group", "mappng_fields", "attribute_name"],
            order_by="idx"
        )

        for parent_row in parent_part_mapping:
            part_item_group = parent_row.get('item_group')

            part_mapping = frappe.get_all( "Part Mapping",
                filters={"parent": part_item_group},
                fields=["item_group", "mappng_fields", "attribute_name"],
                order_by="idx"
            )

            for row in doc.get('njqca_item_component', []):
                skip_ram, skip_memory = False, False
                attribute_value, attribute_object = {}, {}
                
                for mapping in part_mapping:
                    last_variant_values = {}
                    item_group = row.get('item_group')

                    if item_group == mapping.get('item_group'):
                        
                        if not mapping.get('mappng_fields'): continue
                        if mapping.get('mappng_fields'):
                            variants = mapping.get('mappng_fields').split('::')
                            for variant in variants:
                                last_variant_values[item_group] = last_variant_values.get(item_group, {})
                                last_variant_values[item_group][variant] = row.get(variant)
                            attribute_value = last_variant_values.get(item_group, {})
                            
                        if item_group.lower() == cpu.lower():
                            any_undefined = any(value is None for value in attribute_value.values())
                            cpu_value = unk_cpu if any_undefined else list(attribute_value.values())[0]
                            normalize_cpu = normalize_gen(cpu_value, doc.get('model'),row.get('variant_7'))
                            if normalize_cpu and len(normalize_cpu) > 0:
                                attribute_object[mapping.get('attribute_name')] = get_attribute_from_erp(normalize_cpu, mapping.get('attribute_name'))

                        elif item_group.lower() == ram.lower() and (row.get('variant_1') != 'SYSTEM MEMORY' and row.get('variant_1') != '[EMPTY]'):
                            if part_item_group == item_group:
                                if variant == 'variant_6':
                                    if 'GB' not in row.get(variant) or 'NO MODULE INSTALLED' in row.get(variant):
                                        skip_ram = True
                                        continue
                                    else:
                                        attribute_object[mapping.get('attribute_name')] = get_attribute_from_erp(row.get(variant), mapping.get('attribute_name'))
                                
                                if skip_ram:
                                    continue

                                if variant == 'variant_7':
                                    if row.get(variant) == '26':
                                        attribute_object[mapping.get('attribute_name')] = get_attribute_from_erp('DDR4', mapping.get('attribute_name'))
                                    elif row.get(variant) == '23':
                                        attribute_object[mapping.get('attribute_name')] = get_attribute_from_erp('DDR3', mapping.get('attribute_name'))
                                    elif 'ddr' in row.get(variant).lower():
                                        attribute_object[mapping.get('attribute_name')] = get_attribute_from_erp(row.get(variant), mapping.get('attribute_name'))
                                
                                if variant == 'variant_8':
                                    match = re.search(r'\d+', row.get(variant))
                                    if match:
                                        attribute_object[mapping.get('attribute_name')] = get_attribute_from_erp(f"{match.group()} GHZ", mapping.get('attribute_name'))
                            
                            else:
                                if variant == 'variant_6':
                                    if 'GB' not in row.get(variant) or 'NO MODULE INSTALLED' in row.get(variant):
                                        continue
                                    else:
                                        attribute_object[mapping.get('attribute_name')] = get_attribute_from_erp(row.get(variant), mapping.get('attribute_name'))
                        
                        elif item_group.lower() == storage.lower() and row.get('variant_10') and row.get('variant_3') != 'USB':
                            variant_type = ''
                            
                            storage_text = " ".join([
                                str(row.get("variant_1") or ""),
                                str(row.get("variant_2") or ""),
                                str(row.get("variant_3") or ""),
                                str(row.get("variant_5") or ""),
                                str(row.get("variant_6") or ""),
                                str(row.get("variant_15") or ""),
                            ]).lower()

                            if "ssd" in storage_text or "nvme" in storage_text:
                                variant_type = " SSD"
                            elif "hdd" in storage_text or "hard disk" in storage_text or "harddisk" in storage_text:
                                variant_type = " HDD"

                            if variant == 'variant_10':
                                final_value = row.get(variant)
                                numeric_value = 0

                                if final_value and isinstance(final_value, str):
                                    match = re.search(r'\d+', final_value)
                                    if match:
                                        numeric_value = int(match.group())

                                # fallback when disk type is not detected from variant fields
                                # /DEV/SDA will not tell SSD/HDD, so for 64/128/256/512 we treat as SSD
                                if not variant_type:
                                    if numeric_value in [61, 62, 64, 128, 256, 512]:
                                        variant_type = " SSD"
                                    elif numeric_value in [200, 300, 320, 500, 1000]:
                                        variant_type = " HDD"

                                if numeric_value >= 60:
                                    if numeric_value >= 1000:
                                        tb_value = numeric_value // 1000
                                        formatted_value = f"{tb_value} TB"
                                    elif numeric_value >= 60 and numeric_value <= 80:
                                        formatted_value = "64 GB"
                                    else:
                                        formatted_value = f"{numeric_value} GB"

                                    # For HDD, do not add HDD suffix.
                                    # Example: 500 GB HDD should remain 500 GB.
                                    # For SSD, add SSD suffix.
                                    if str(variant_type).strip().upper() == "HDD":
                                        final_value = formatted_value
                                    else:
                                        final_value = formatted_value + (variant_type or "")

                                    attribute_object[mapping.get('attribute_name')] = get_attribute_from_erp(
                                        final_value,
                                        mapping.get('attribute_name')
                                    )
                                else:
                                    skip_memory = True
                                    continue

                            if skip_memory:
                                continue

                            process_variant_status = False
                            if variant == 'variant_5' and not skip_memory:
                                process_variant_status = process_variant(variant, row, mapping, attribute_object)

                            if not process_variant_status and not skip_memory:
                                process_variant('variant_6', row, mapping, attribute_object)

                part_data = set_part_data(item_group, attribute_object, row, part_data, doc)
        parent_item_group = doc.get('item_group')

        if parent_item_group:

            parent_attribute_names = [item['attribute_name'] for item in parent_part_mapping]

            for item in part_data:
                attr_data = item.get('attr_data', {})

                filtered_result = {key: attr_data[key] for key in parent_attribute_names if key in attr_data}
                
                if filtered_result:
                    child_attr_data.append(filtered_result)

            if doc.get('item_template'):
                
                consolidated = consolidate_ram_capacities(child_attr_data)
                consolidated = consolidate_storage(consolidated)
                item_template = doc.get('item_template')
                repack_item_code = get_variant_from_value(item_template, consolidated)

                if repack_item_code and 'error' in repack_item_code:
                    new_item = False
                    new_consolidated = copy.deepcopy(consolidated)
                    for arg in new_consolidated:
                        for key, value in arg.items():
                            if key.lower() == 'ram capacity':
                                ddr = frappe.db.sql("""SELECT variant_7 FROM `tabNJQCA Child`
                                    WHERE parent = '{0}' AND variant_6 IS NOT NULL and variant_7 IS NOT NULL and item_group = 'Laptop RAM' limit 1""".format(doc.get('name'),), as_dict=True)
                                if ddr and ddr[0].variant_7.lower() in ("ddr4", "26"):
                                    arg[key] = value + " DDR4"
                                    new_item = True
                            
                    if new_item:
                        repack_item_code = get_variant_from_value(item_template, new_consolidated)

                # if repack_item_code is None:
                #     old_commment = frappe.db.get_value("Comment", {'reference_doctype': doc.get('doctype'), 'reference_name': doc.get('name'), 'content': "Automated Item code not found: "+consolidated}, "content")
                #     if not old_commment:
                #         frappe.get_doc({
                #             'doctype': 'Comment',
                #             'comment_type': 'Comment',
                #             'reference_doctype': doc.get('doctype'),
                #             'reference_name': doc.get('name'),
                #             'content':  "Automated Item code not found: "+consolidated,
                #         }).insert(ignore_permissions=True)

                result_part_data = get_fetched_item_code(doc.get('serial_no'), part_data)

                if result_part_data:
                    part_data = result_part_data

                return {'data_attr': consolidated, 'repack_item_code': repack_item_code, 'part_data': part_data}
            else:
                return {'error': f'Item Template not found'}

    except Exception as e:
        frappe.throw("An error occurred: " + traceback.format_exc())
        return {"error": f"An error occurred: {traceback.format_exc()}"}
    
def get_attribute_from_erp(attribute_value, parent):
    erp_normalize_cpu_query = """SELECT attribute_value FROM `tabItem Attribute Value` WHERE attribute_value = %s AND parent = %s"""
    erp_normalize_cpu = frappe.db.sql(erp_normalize_cpu_query, (attribute_value, parent))

    if erp_normalize_cpu:
        return erp_normalize_cpu[0][0]
    return None

def process_variant(variant, row, mapping, attribute_object):

    print("\n\nvariant", variant)
    print("row", row)
    print("mapping", mapping)
    print("attribute_object", attribute_object)

    if 'interface' in mapping.get('attribute_name').lower() and row.get(variant):
        print("inside interface ------------- ", row)
        interfaces = {
            'SATA': ['sata', 'sata3', 'sata2', 'sata1', 'hdd', 'ssd'],
            'MSATA': ['msata'],
            'M.2 SATA': ['m.2 sata', 'ngff'],
            'M.2 NVME': ['m.2 nvme', 'nvme'],
            'M.2 PCL': ['pcl', 'pcie'],
        }

        print("interfaces_items -------------- ", interfaces.items())

        for interface, keywords in interfaces.items():
            for keyword in keywords:
                print(f'keyword -------------- {keyword} ------- row -- {row.get(variant)}')
                if keyword in row.get(variant).lower():
                    print("coming inside", interface)
                    attribute_object[mapping.get('attribute_name')] = interface
                    return True
                
    elif 'type' in mapping.get('attribute_name').lower() and row.get(variant):
        nj_types = {
            'SATA I': ['sata1', 'sata-1'],
            'SATA II': ['sata2', 'sata-2'],
            'SATA III': ['sata3', 'sata-3'],
            'MSATA': ['msata', 'm.2 msata'],
            'M.2 SATA 2280': ['m.2 sata 2280', 'm.2 sata', 'ngff 2280'],
            'M.2 SATA 2242': ['m.2 sata 2242', 'ngff 2242'],
            'M.2 NVMe 2280': ['m.2 nvme 2280', 'nvme 2280', 'pcie 2280'],
            'SSD': ['ssd', 'solid state drive'],
            'HDD': ['hdd', 'hard drive', 'harddisk'],
        }

        for nj_type, keywords in nj_types.items():
            for keyword in keywords:
                if keyword in row.get(variant).lower():
                    attribute_object[mapping.get('attribute_name')] = nj_type
                    return True
    

    print("attribute_object -------------- ", attribute_object)

    return False

def set_part_data(part_item_group, attribute_object, row, part_data, doc):
    print(f"[part_item_group]: {part_item_group}\n[attribute_object]: {attribute_object}\n[row]: {row}\n[part_data before]: {part_data}\n[doc]: {doc}")
    
    item_template = None
    if doc.get('item_group') == "Desktops" and part_item_group in ("Laptop RAM", "LAPTOP STORAGE"):
        component_types = []
        if part_item_group == "Laptop RAM":
            component_types = ["Laptop RAM", "Desktop RAM"]
        elif part_item_group == "LAPTOP STORAGE":
            component_types = ["LAPTOP STORAGE", "DESKTOP STORAGE"]
            
        if component_types:
            templates = frappe.db.sql("""
                select DISTINCT c.reference_template 
                from `tabSerial No` sn 
                inner join `tabItem Wizards` iw on sn.item_wizard = iw.name
                inner join `tabComponent` c on iw.name = c.parent
                where sn.name = %s and (c.component_type = %s or c.component_type = %s) 
            """, (doc.get('serial_no'), component_types[0], component_types[1]), as_dict=True)
            
            if templates:
                if len(templates) > 1:
                    item_template = [t.reference_template for t in templates if t.reference_template]
                elif len(templates) == 1:
                    item_template = templates[0].reference_template

    if not item_template:
        item_template = frappe.db.get_value('Item',
            {'item_group': part_item_group, 'has_variants': 1, 'disabled': 0}, 'name' )
    
    Grade = doc.get('grade')
    attribute_object['Grade'] = get_attribute_from_erp(Grade, "Grade")

    if len(attribute_object) > 1:
        if isinstance(item_template, list):
            part_data.append({
                'name': row.get('name'),
                'attr_data': attribute_object,
                'part_item_code': "",
                'item_group': part_item_group,
                'item_template': item_template,
                'response': 'error'
            })
            return part_data
            
        part_item_code = get_variant_from_value(item_template, [attribute_object])
        if part_item_code and 'error' not in part_item_code:
            part_item_code_from_db = frappe.db.get_value("Item",
                {'item_name': part_item_code, 'has_variants': 0, 'item_group': part_item_group, 'disabled': 0},
                'name' )
            if part_item_code_from_db:
                new_item_template = frappe.db.get_value( 'Item', {'name': part_item_code}, 'variant_of' )
                part_data.append({
                    'name': row.get('name'),
                    'attr_data': attribute_object,
                    'part_item_code': part_item_code,
                    'item_group': part_item_group,
                    'item_template': new_item_template if new_item_template else item_template,
                })
            else:
                part_data.append({
                    'name': row.get('name'),
                    'part_item_code': "",
                    'attr_data': attribute_object,
                    'item_group': part_item_group,
                    'item_template': item_template,
                    'response': 'error'
                })
        else:
            part_data.append({
                'name': row.get('name'),
                'part_item_code': "",
                'attr_data': attribute_object,
                'item_group': part_item_group,
                'item_template': item_template,
                'response': 'error'
            })

    return part_data

@frappe.whitelist()
def get_part_mapping(doc):
    
    if isinstance(doc, str):
        try:
            doc = json.loads(doc)

        except json.JSONDecodeError:
            frappe.throw("Invalid JSON string provided for part mapping.")

    if doc.get('njqca_item_component') and doc.get('item_group'):

        try:
            nj_settings = frappe.get_all("NJ Settings", filters={"doc_type": "NJQCA Child"},
                                fields=["parameter", "value"])

            for param in nj_settings:
                globals()[param.parameter] = param.value
            
            return json.dumps(get_item_code_for_each_part(doc))
            
        except Exception as e:
            # log_error(traceback.format_exc(), "An error occurred in get_part_mapping in NJQCA")
            frappe.throw(f"An error occurred in get_part_mapping: {traceback.format_exc()}")

def consolidate_ram_capacities(data):
    consolidated_data,ram_consolidation = [], {}
    ram_found = False

    for obj in data:
        for key, value in obj.items():
            if key.lower() == ram_capacity.lower():
                ram_found = True
                ram_value = value

                match = re.match(r'^(\d+)\s*GB\s*(\w+)?', ram_value, re.IGNORECASE)
                if match:
                    amount, type_ = match.groups()
                    total_amount = int(amount)
                    type_ = type_ or ''
                    
                    existing_value = ram_consolidation.get(key)
                    if existing_value:
                        existing_match = re.match(r'^(\d+)\s*GB\s*(\w+)?', existing_value, re.IGNORECASE)
                        if existing_match:
                            existing_amount, existing_type = existing_match.groups()
                            existing_type = existing_type or ''
                            
                            if existing_type.upper() == type_.upper():
                                ram_consolidation[key] = f"{int(existing_amount) + total_amount} GB"
                            else:
                                frappe.msgprint(f"Different RAM Type is not allowed")
                                return
                    else:
                        ram_consolidation[key] = ram_value
            else:
                consolidated_data.append({key: value})

    for key, value in ram_consolidation.items():
        consolidated_data.append({key: value})

    if not ram_found:
        consolidated_data.append({"Ram Capacity": unk_ram})

    return consolidated_data

def consolidate_storage(data):
    storage_parts, result_data = [], []
    total_storage_capacity = 0
    storage_type = None
    storage_found = False
    
    for obj in data:
        for key, value in obj.items():
            if key.lower() == 'storage capacity' and value:
                storage_found = True
                if 'SSD' in value.upper():
                    if storage_type and storage_type != 'SSD':
                        raise ValueError("Mix of SSD and HDD is not allowed")
                    storage_type = 'SSD'
                elif 'HDD' in value.upper():
                    if storage_type and storage_type != 'HDD':
                        raise ValueError("Mix of SSD and HDD is not allowed")
                    storage_type = 'HDD'
                
                match = re.match(r'^(\d+)\s*(TB|GB)\s*(SSD|HDD)?', value, re.IGNORECASE)
                if match:
                    amount = int(match.group(1))
                    unit = match.group(2).upper()
                    storage_kind = match.group(3) if match.group(3) else ""
                    
                    if unit == 'TB':
                        total_storage_capacity += amount * 1024
                        storage_parts.append(f"{amount} TB {storage_kind}".strip())
                    elif unit == 'GB':
                        total_storage_capacity += amount
                        storage_parts.append(f"{amount} GB {storage_kind}".strip())
                else:
                    result_data.append(obj)
            else:
                result_data.append(obj)

    if not storage_found:
        result_data.append({'Storage Capacity': unk_storage})
    
    if storage_parts:
        storage_parts.sort() 
        consolidated_storage = []
        current_capacity = 0
        
        for part in storage_parts:
            match = re.match(r'(\d+)\s*(TB|GB)\s*(SSD|HDD)?', part, re.IGNORECASE)
            if match:
                amount = int(match.group(1))
                unit = match.group(2)
                storage_kind = match.group(3) if match.group(3) else ""
                
                if unit == 'GB':
                    current_capacity += amount
                elif unit == 'TB':
                    current_capacity += amount * 1024

        if current_capacity >= 1024:
            tb_part = current_capacity // 1024
            gb_part = current_capacity % 1024
            if gb_part > 0:
                consolidated_storage.append(f"{tb_part} TB-{gb_part} GB {storage_kind}".strip())
            else:
                consolidated_storage.append(f"{tb_part} TB {storage_kind}".strip())
        else:
            consolidated_storage.append(f"{current_capacity} GB {storage_kind}".strip())
        
        if len(consolidated_storage) > 1:
            result_data = [item for item in result_data if 'Storage Capacity' not in item]
            result_data.append({'Storage Capacity': '-'.join(consolidated_storage)})
        else:
            result_data = [item for item in result_data if 'Storage Capacity' not in item]
            result_data.append({'Storage Capacity': consolidated_storage[0]})

    return result_data
                    
def normalize_gen(cpu_value, model, variant_7=None):
    match = None
    if 'core' in cpu_value.lower():
        match = re.search(r"(\bI\d+)-([A-Za-z0-9]+)", cpu_value, re.IGNORECASE)

        if match:
            core = 'Core ' + match.group(1).lower()
            alphanumeric_part = match.group(2)

            numeric_part = ''.join(filter(str.isdigit, alphanumeric_part))

            # check if generation is mentioned in cpu string directly
            gen_from_string = None
            gen_match = re.search(r'(\d+)\s*(?:th|st|nd|rd)?\s*gen', cpu_value, re.IGNORECASE)
            if gen_match:
                gen_from_string = gen_match.group(1)

            # use gen from string if found, else auto calculate
            if gen_from_string and int(gen_from_string) > 0:
                gen_number = gen_from_string
            else:
                gen_number = str(int(numeric_part) // 1000)

            # variant_7 overrides if filled and valid
            if variant_7:
                variant_7_digits = ''.join(filter(str.isdigit, str(variant_7)))
                if variant_7_digits and variant_7_digits != gen_number and int(variant_7_digits) > 0:
                    gen_number = variant_7_digits

            if gen_number == '1':
                gen_number += 'st'
            elif gen_number == '2':
                gen_number += 'nd'
            elif gen_number == '3':
                gen_number += 'rd'
            else:
                gen_number += 'th'

            return [f"{core} - {gen_number} Gen"]

    if 'ryzen' in cpu_value.lower():
        match = re.match(r"([\w\s]+)(?=\s\d)", cpu_value, re.IGNORECASE)
        if match:
            return [match.group(1).upper()]

    if 'amd' in cpu_value.lower() and 'ryzen' not in cpu_value.lower():
        match = re.match(r"([\w\s]+)-([\w\d]+)", cpu_value, re.IGNORECASE)
        if match:
            return [match.group(1).upper()]

    cpu_value_upper = cpu_value.upper()
    if not match:
        for cpu_type in ['XEON', 'PENTIUM', 'ATOM']:
            if cpu_type in cpu_value_upper:
                return [f"Intel {cpu_type.capitalize()}"]

    return []
    
# @frappe.whitelist()
# def get_variant_from_value(item_template=None, args=None):
#     try:
#         missing_attribute = []
#         args_list = []
#         if args:
#             args_list = frappe.parse_json(args)

#         if item_template and args_list:
#             conditions = []

#             # get_attribute_name = frappe.db.sql("SELECT attribute FROM `tabItem Variant Attribute` WHERE parent = %s", (item_template,))
#             # attribute_list = [row[0].strip().lower() for row in get_attribute_name]
#             # args_attribute_list = [key.lower() for key in args[0]]

#             # if len(set(attribute_list)) != len(set(args_attribute_list)):
#             #     item_code = construct_item_code(item_template, args_list)
#             #     return item_code
                
#             conditions = []
#             for condition_dict in args_list:
#                 for key, value in condition_dict.items():
#                     normalized_value = value.strip().lower()
#                     conditions.append(f"MAX(attribute = '{key.strip().lower()}' AND attribute_value = '{normalized_value}') = 1")

#             having_clause = " AND ".join(conditions)

#             if having_clause:
#                 query = """
#                     SELECT parent FROM `tabItem Variant Attribute`
#                     WHERE variant_of = %s GROUP BY parent HAVING {}
#                 """.format(having_clause)

#                 variants = frappe.db.sql(query, (item_template,), as_dict=True)

#                 if variants and variants[0]['parent']:
#                     return variants[0]['parent']
#                 else:
#                     item_code = construct_item_code(item_template, args_list)
#                     return item_code

#         return None

#     except Exception as e:
#         return None

@frappe.whitelist()
def get_variant_from_value(item_template=None, args=None):
    try:
        if not item_template or not args:
            return None

        args_list = frappe.parse_json(args)
        if not isinstance(args_list, list):
            return None

        joins = []
        conditions = []
        i = 0

        for condition_dict in args_list:
            for key, value in condition_dict.items():
                attribute = key.strip().lower()
                attribute_value = value.strip().lower()
                alias = f"a{i}"
                joins.append(f"""
                    JOIN `tabItem Variant Attribute` {alias}
                    ON base.parent = {alias}.parent
                    AND {alias}.attribute = %s
                    AND {alias}.attribute_value = %s
                """)
                conditions.append((attribute, attribute_value))
                i += 1

        if not joins:
            return None

        attr_count = len(conditions)

        query = f"""
            SELECT base.parent
            FROM `tabItem Variant Attribute` base
            INNER JOIN `tabItem` i ON i.name = base.parent
            {" ".join(joins)}
            WHERE base.variant_of = %s 
              AND i.disabled = 0 
              AND (i.end_of_life IS NULL OR i.end_of_life >= CURDATE())
            GROUP BY base.parent
            HAVING COUNT(DISTINCT base.parent) = 1
              AND (
                  SELECT COUNT(*) 
                  FROM `tabItem Variant Attribute` t
                  WHERE t.parent = base.parent
              ) = {attr_count}
            LIMIT 1
        """

        query_args = []
        for attr, val in conditions:
            query_args.extend([attr, val])
        query_args.append(item_template)

        variant = frappe.db.sql(query, tuple(query_args), as_dict=True)

        if variant and variant[0].get("parent"):
            return variant[0]["parent"]

        return construct_item_code(item_template, args_list)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_variant_from_value error")
        return None

@frappe.whitelist()
def construct_item_code(item_template, args_list):
    try:
        part_item_group = frappe.db.get_value('Item', {'name': item_template}, 'item_group')
        if isinstance(args_list, str):
            args_list = frappe.parse_json(args_list)
        concatenated_string = item_template

        for condition_dict in args_list:
            for key, value in condition_dict.items():
                get_abbr_attribute = frappe.db.sql("SELECT abbr FROM `tabItem Attribute Value` WHERE parent = %s AND attribute_value = %s", (key, value))
                if get_abbr_attribute:
                    concatenated_string += f"-{get_abbr_attribute[0][0]}"

        query = """
            SELECT item_code FROM `tabItem`
            WHERE item_code = %s and disabled = 0 AND end_of_life >= CURDATE()
        """

        item_code = frappe.db.sql(query, (concatenated_string,), as_dict=True)

        if item_code:
            return item_code[0]['item_code']
        
        elif part_item_group == 'Chromebooks' and (item_code is None or item_code == []):
            having_conditions = []
            query_args = []
            for cond in args_list:
                for attr, val in cond.items():
                    attr = attr.strip().lower()
                    if attr == "storage capacity" and val.lower().endswith(" ssd"):
                        val = val[:-4].strip()

                    val = val.lower()
                    having_conditions.append(f"SUM(attribute = %s AND attribute_value = %s) = 1")
                    query_args.extend([attr, val])

            num_attributes = len(args_list)

            query = f"""
                SELECT parent
                FROM `tabItem Variant Attribute`
                WHERE variant_of = %s
                GROUP BY parent
                HAVING COUNT(*) = %s AND {" AND ".join(having_conditions)}
                LIMIT 1
            """

            query_args = [item_template, num_attributes] + query_args

            variant = frappe.db.sql(query, tuple(query_args), as_dict=True)

            if variant and variant[0]['parent']:
                return variant[0]['parent']

        item_code = frappe.db.sql(query, (concatenated_string,), as_dict=True)

        if item_code:
            return item_code[0]['item_code']
        
        return None

    except Exception:
        log_error(f"An error occurred at construct_item_code: {str(traceback.format_exc())}", "Error in construct_item_code NJQCA")

@frappe.whitelist()
def get_model(manufacturer_model=None, item_group=None, brand=None):
    query, model_list = '', []

    if _is_desktop_item_group(item_group):
        if not brand:
            return model_list

        query = """
            SELECT DISTINCT i.item_model AS model
            FROM `tabItem` i
            WHERE i.item_group = %(item_group)s
              AND i.brand = %(brand)s
              AND IFNULL(i.item_model, '') != ''
              AND i.disabled = 0
            ORDER BY i.item_model
        """
        params = {
            'item_group': item_group,
            'brand': brand,
        }
        return frappe.db.sql(query, params, as_dict=True)

    if not manufacturer_model:
        return model_list

    query = """SELECT DISTINCT mmc.parent AS model
               FROM `tabManufacturer Model Child` AS mmc
               LEFT JOIN `tabMake Child` AS mc ON mc.parent = mmc.parent
               WHERE mmc.manufacturer_model = %s
               ORDER BY mmc.parent"""
    model_list = frappe.db.sql(query, (manufacturer_model,), as_dict=True)

    if not model_list:
        frappe.msgprint(f"Manufacturer Model: <strong>{manufacturer_model}</strong> not found. Please contact <strong>NPD department</strong> for mapping the model.")

    return model_list

@frappe.whitelist()
def get_part_item_code_filtered_data(item_group):
    get_part_item_code_query = """SELECT name FROM `tabItem` 
            WHERE item_group = %(item_group)s AND has_variants = 0 AND disabled = 0"""
    
    return frappe.db.sql(get_part_item_code_query, {'item_group': item_group})

@frappe.whitelist()
def get_sudden_drop(parent_name, item_group, manufacturer_model):
    try:  
        njqca_battery_item_group = frappe.db.get_value('NJ Settings', {'parameter': 'njqca_battery'}, 'value')
        sudden_drop_limit=""
        iw=""
        if (njqca_battery_item_group and  item_group in njqca_battery_item_group):
            iw=get_item_wizard(manufacturer_model)
            if iw:
               sudden_drop_limit = frappe.db.get_value('Item Wizards',{'name': iw},'sudden_drop_limit')
            if (sudden_drop_limit is  None) or (not sudden_drop_limit) :
                sudden_drop_limit="17"
            delta_query=""" 
                      WITH FilteredResults AS (
                        SELECT value, idx, parameter
                        FROM `tabNJQCA Result Parameters`
                        WHERE idx >= (
                            SELECT idx - 1
                            FROM `tabNJQCA Result Parameters`
                            WHERE parent = %(parent_name)s
                            AND parameter = 'Battery_Discharging_Start_Time' 
                            ORDER BY idx DESC LIMIT 1
                        )
                        AND parameter <> 'Battery_Discharging_Start_Time'
                        AND parent = %(parent_name)s
				        and value REGEXP '^[0-9]+$'
                        ORDER BY idx
                    ),
                    TimeParsed AS (
                        SELECT 
                            value,
                            idx,
                            parameter,
                            STR_TO_DATE(parameter, '%%H:%%i:%%s') AS time_obj
                        FROM FilteredResults
                    ),
                    DeltaValues AS (
                        SELECT 
                            curr.value,
                            curr.idx,
                            curr.parameter,
                            curr.value - LEAD(curr.value) OVER (ORDER BY curr.idx) AS delta_drop,
                            ROUND(
                                ABS(
                                    IF(
                                        LEAD(curr.time_obj) OVER (ORDER BY curr.idx) >= curr.time_obj,
                                        TIME_TO_SEC(TIMEDIFF(LEAD(curr.time_obj) OVER (ORDER BY curr.idx), curr.time_obj)),
                                        TIME_TO_SEC(TIMEDIFF(ADDTIME(LEAD(curr.time_obj) OVER (ORDER BY curr.idx), '24:00:00'), curr.time_obj))
                                    )
                                ), 2
                            ) AS delta_seconds
                        FROM TimeParsed curr
                    ),
                    RateValues AS (
                        SELECT 
                            idx,
                            parameter,
                            value,
                            delta_drop,
                            delta_seconds,
                            CASE 
                                WHEN delta_drop IS NOT NULL AND delta_drop <> 0 AND delta_seconds <> 0 
                                THEN delta_drop / delta_seconds 
                                ELSE NULL 
                            END AS rate
                        FROM DeltaValues
                    ),
                    avg_rate AS (
                        SELECT *,AVG(rate) AS avg_rate_value
                        FROM RateValues 
                        WHERE rate IS NOT NULL and value>%(sudden_drop_limit)s
                        
                    ),

                    stats AS (
                        SELECT *,
                            round(MAX(rate),4) AS max_rate,
                        round( (SELECT avg_rate_value FROM avg_rate),4) AS avg_rate,
                            SUM(CASE WHEN rate > 2 * (SELECT avg_rate_value FROM avg_rate) THEN 1 ELSE 0 END) AS count_gt_2x
                        FROM RateValues
                        WHERE rate IS NOT NULL and value>%(sudden_drop_limit)s
                    )
                    SELECT
                    max_rate,
                    avg_rate,
                    count_gt_2x as count,
                    CASE
                        WHEN (max_rate > 3 * avg_rate OR count_gt_2x >= 3 )THEN "Yes"
                        ELSE "NO"
                    END AS condition_met
                
                    FROM stats;

                """
            
            percentage_query="""
                    SELECT value
                    FROM `tabNJQCA Result Parameters`
                    WHERE
                        parent = %(parent_name)s
                        AND value REGEXP '^[0-9]+$'
                    ORDER BY idx DESC
                    LIMIT 1;
            """

            percentage = frappe.db.sql(percentage_query, {'parent_name': parent_name}, as_dict=True)
            if percentage is None or not percentage:
                return "No Valid Data"
            last_percentage = percentage[0].get('value')

            rbdt_status = frappe.db.get_value('NJQCA', {'name': parent_name}, 'rapid_bdt')
        
            if rbdt_status==None or rbdt_status=="":
                if last_percentage and int(last_percentage) >= int(sudden_drop_limit):
                    return "YES"
            
            delta = frappe.db.sql(delta_query, {'parent_name': parent_name, 'sudden_drop_limit': int(sudden_drop_limit)}, as_dict=True)
            sudden_drop=""
            max_rate=""
            avg_rate=""
            count_avg=""
            if delta is not None and delta:
                sudden_drop = delta[0].get('condition_met')
                max_rate = delta[0].get('max_rate')
                avg_rate = delta[0].get('avg_rate')
                count_avg = delta[0].get('count')

                if sudden_drop and sudden_drop == "Yes":
                    return f"YES max_rate: {max_rate} avg_rate: {avg_rate} count_avg: {count_avg}"
                else:
                    return f"NO max_rate: {max_rate} avg_rate: {avg_rate} count_avg: {count_avg}"
            else:
                return "YES"
          
        else:
            return None
            
    except Exception as e:
        frappe.msgprint("An error occurred at get_sudden_drop", str(e))
        log_error(traceback.format_exc(), "An error occurred at get_sudden_drop in NJQCA")
        return ''
        
@frappe.whitelist()
def get_njqca_item_template(item_group=None, brand=None, model=None):
    try:
        wizard_list, item_templates = '', None

        item_templates = get_item_template(brand, model, item_group)
        if item_templates:
            wizard_list = has_item_wizards(item_templates, ignore=False)
            
        return {'item_template': item_templates, 'wizard_list': wizard_list}
    
    except Exception as e:
        frappe.throw(f"An error occurred at get_njqca_item_template: {str(e)}")
        return None

@frappe.whitelist()
def get_serial_no_attribute_data(serial_no, item_group, item_template):

    if serial_no and item_group:
        adap_dis_item_code = frappe.db.get_all(
            'Serial No Component',
            filters={ 'parent': serial_no, 'item_group': item_group },
            fields=['item', 'item_group', 'grade', 'quantity'],
        )

        for item in adap_dis_item_code:
            if item['item'] is None or item['item'] == "":
                frappe.throw(_("Item Code not found in Part List for Serial No: {0} and Item Group: {1}").format(serial_no, item_group))
            item['item_template'] = frappe.db.get_value('Item', item['item'], 'variant_of')

        if adap_dis_item_code:
            return adap_dis_item_code
        
        get_item_wizard = get_latest_item_wizard(item_template)
        if get_item_wizard  :
            comp_item_template = frappe.db.get_value('Component', {'parent': get_item_wizard, 'component_type': item_group}, 'reference_template', as_dict=True)
        
        if comp_item_template:
            return [{'item_template': comp_item_template['reference_template']}]

    return None

@frappe.whitelist()
def update_serial_no_component_for_njqca(doc):
    if isinstance(doc, str):
        doc = json.loads(doc)

    serial_no_doc = frappe.get_doc("Serial No", doc.get('serial_no'), for_update=True)

    attribute_table = [
        {
            "item_group": item.get('item_group'),
            "calculated_item_code": item.get('calculated_item_code'),
            "reference_doctype": item.get('parent'),
            "docname": item.get('parenttype'),
            "grade": item.get('grade'),
        }
        for section in ['njqca_display', 'njqca_laptop_ram', 'njqca_laptop_storage', 'njqca_adaptor']
        for item in doc.get(section, [])
    ]

    existing_item_groups = [component['item_group'] for component in attribute_table]
    serial_no_doc.serial_no_component = [
        sn for sn in serial_no_doc.serial_no_component if sn.item_group not in existing_item_groups
    ]

    for component in attribute_table:
        serial_no_doc.append("serial_no_component", {
            "item_group": component.get('item_group', ''),
            "item": component.get('calculated_item_code', ''),
            "grade": component.get('grade', ''),
            "reference_doctype_no": component.get('reference_doctype', ''),
            "reference_doctype": component.get('docname', ''),
            "is_available" : 1,
            "quantity": 1
        })

    for index, row in enumerate(serial_no_doc.serial_no_component, start=1):
        row.idx = index

    serial_no_doc.save()

@frappe.whitelist()
def get_item_code_filtered_data(doctype, txt, searchfield, start, page_len, filters):
    txt = ''
    parent = filters.get('parent')

    filters_data = [ ["parent", "=", parent] ]

    return frappe.get_all(
        "Item Attribute Value",
        filters=filters_data,
        fields=["attribute_value"],
        as_list=1,
        or_filters=[ ["attribute_value", "like", f"%{txt}%"] ]
    )

@frappe.whitelist()
def get_result_parameter(name, item_group, parameter):
    try:
        result_dict = {}
        if isinstance(parameter, str):
            parameter = parameter.split(',')
        for param in parameter:
            result = frappe.db.sql("""SELECT value FROM `tabNJQCA Result Parameters` 
                                    WHERE item_group = %(item_group)s 
                                    AND parameter = %(parameter)s AND parent = %(name)s""", 
                                    {'name': name, 'item_group': item_group, 'parameter': param}, as_dict=True)
            param = param.strip()
            if result:
                value = result[0].get('value')
                base_url = get_url()
                result_dict[param] = f"{base_url}/app/file/{value}"
            else:
                result_dict[param] = ""
        
        return result_dict
    
    except Exception as e:
        return str(e)
    
@frappe.whitelist()
def get_options_for_label(item_group, label, item_template):
    options = None
    item_wizard = get_latest_item_wizard(item_template)
    label_defined = frappe.db.exists('Items Attribute', {
        'parent': item_wizard,
        'item_attribute': label,
        'item_group': item_group
    })

    if label_defined:
        options = frappe.db.get_all('Items Attribute', filters={'parent': item_wizard, 'item_attribute': label, 'item_group': item_group}, fields=['attribute_value'], order_by='idx')
    else:
        options = frappe.db.get_all('Item Attribute Value', filters={'parent': label}, fields=['attribute_value'], order_by='idx')

        if label.lower() == 'grade':
            options = [
                option for option in options
                if option['attribute_value'].strip().lower() != 'unknown'
            ]
    
    if not options:
        return {'error': f"Item attribute <b>{label}</b> is not defined in Item Wizard <b>{item_wizard}</b>. Contact NPD Team."}

    return [option['attribute_value'] for option in options]

@frappe.whitelist()
def get_fetched_item_code(serial_no, partData):
    print(f"get_fetched_item_code called with serial_no: {serial_no} and partData: {partData}")
    unmatched_item_code = []
    partData = frappe.parse_json(partData)

    serial_no_components = frappe.db.sql(
        """
            SELECT name, item_group, item, reference_doctype_no, item_group_idx, component_serial_no
            FROM `tabSerial No Component` WHERE parent = %s
        """, (serial_no,), as_dict=True
    )

    updated_part_data = []
    used_serial_rows = set()

    for data in partData:
        matched = False

        for row in serial_no_components:
            if row.get("name") in used_serial_rows:
                continue

            if row.get("item_group") == data.get("item_group"):
                query2 = frappe.db.sql("""
                    SELECT DISTINCT LOWER(attribute) AS item_attribute, LOWER(attribute_value) AS attribute_value
                    FROM `tabItem Variant Attribute` WHERE parent = %s
                """, (row.get("item")), as_dict=True)

                serial_no_attr_data = {
                    item["item_attribute"]: item["attribute_value"]
                    for item in query2
                }

                njqca_attr_data = {
                    (key.lower() if key else ""): (value.lower() if isinstance(value, str) else "")
                    for key, value in data.get("attr_data", {}).items()
                }

                serial_no_grade = serial_no_attr_data.pop("grade", None)
                njqca_attr_data.pop("grade", None)

                item_group = row.get("item_group", "").lower()

                if item_group == "laptop ram":
                    serial_filtered = {"ram capacity": serial_no_attr_data.get("ram capacity")}
                    data_filtered = {"ram capacity": njqca_attr_data.get("ram capacity")}
                elif item_group == "laptop storage":
                    data_capacity = normalize_storage_capacity(njqca_attr_data.get("storage capacity"))
                    serial_filtered = {"storage capacity": serial_no_attr_data.get("storage capacity")}
                    data_filtered = {"storage capacity": data_capacity}
                else:
                    serial_filtered = serial_no_attr_data
                    data_filtered = njqca_attr_data

                if serial_filtered == data_filtered:
                    data["fetched_item_code"] = row["item"]
                    matched = True
                    used_serial_rows.add(row["name"])

                    if serial_no_grade and serial_no_grade.upper() != "UNKNOWN":
                        data["attr_data"]["Grade"] = get_attribute_from_erp(serial_no_grade, "Grade")
                    break
                else:
                    unmatched_item_code.append(row.get("item"))
                    data["reference_docname"] = row["reference_doctype_no"]
                    data["item_group_idx"] = row["item_group_idx"]

        updated_part_data.append(data)

    partData_fetched_item = sum(
        [[data.get("part_item_code", ""), data.get("fetched_item_code", "")]
         for data in partData], []
    )
    partData_fetched_item = [item for item in partData_fetched_item if item]

    serial_no_components_list = [
        (row.get("name"), row.get("item"), row.get("item_group"),
         row.get("reference_doctype_no"), row.get("item_group_idx"), row.get("component_serial_no"))
        for row in serial_no_components
    ]
    partData_item_groups = {
        data.get("item_group")
        for data in partData if data.get("item_group")
    }

    for name, item, item_group, reference_docname, item_group_idx, component_serial_no in serial_no_components_list:
        if (item not in partData_fetched_item
                and item_group in partData_item_groups
                and name not in used_serial_rows):
            updated_part_data.append({
                "serial_no": component_serial_no,
                "fetched_item_code": item,
                "attr_data": {},
                "part_item_code": "",
                "item_group": item_group,
                "reference_docname": reference_docname,
                "item_group_idx": item_group_idx
            })

    print("updated_part_data >>>>>>>>>>>> ", updated_part_data)

    return updated_part_data if updated_part_data else partData

def normalize_storage_capacity(value):
    if not value:
        return ""
    value = value.lower()
    if value.endswith(" ssd"):
        value = value[:-4]
    return value.strip()

@frappe.whitelist()
def get_battery_auto_item_code(name,item_template,manufacturer_model):
    try:
        wizard=get_item_wizard(manufacturer_model)
        backup_duration="120"
        if wizard:
            wizard_criteria_query="""
                select backup_duration_mins,sudden_drop_limit from `tabItem Wizards` where name=%s ;
            """

            wizard_criteria=frappe.db.sql(wizard_criteria_query, (wizard), as_dict=True)

            if wizard_criteria:
                if wizard_criteria[0].backup_duration_mins: 
                    backup_duration_mins=wizard_criteria[0].backup_duration_mins


            item_code_query="""
                            Select name from `tabItem` where item_group="BATTERY" and variant_of=%(item_templete)s and disabled="NO" and name like 
                            case 
                            when 
                            (select 1 from `tabNJQCA` where ( backup_duration_cycle_3 >= %(backup_duration)s OR backup_duration_cycle_2 >= %(backup_duration)s OR backup_duration_cycle_1 >= %(backup_duration)s) and sudden_drop like "%%NO%%" and name=%(name)s)
                            Then  "%%A"
                            else "%%D"
                            END limit 1;
                        """
            backup_duration=int(backup_duration_mins)
            result=frappe.db.sql(item_code_query,{'item_templete':item_template,'backup_duration':backup_duration,'name':name},as_dict=True)
            if not result is  None and result:
                return result[0].get('name')
            else:
                return None
    except Exception as e:
        return None


@frappe.whitelist()
def validate_battery_storage_score(doc):
    try:
        parent_name=doc.get('name')
        model=doc.get('manufacturer_model')
        item_wizard=get_item_wizard(model)
        bad_sectors, wiz_storage_health= "", ""

        wizard_criteria_query="""select storage_health, bad_sectors from `tabItem Wizards` where name=%s;"""

        if item_wizard:
            wizard_criteria=frappe.db.sql(wizard_criteria_query, (item_wizard), as_dict=True)

            if wizard_criteria:

                if wizard_criteria[0].storage_health:
                    wiz_storage_health=wizard_criteria[0].storage_health
                if wizard_criteria[0].bad_sectors:
                    bad_sectors=wizard_criteria[0].bad_sectors
            
        else:
            return
        
        storage_query = """
            select replace(value, '%%', '') as value from `tabNJQCA Result Parameters`
            where parent=%s and item_group="Laptop storage" and parameter="Health" limit 1
        """

        bad_sector_query = """
            select REGEXP_REPLACE(value, '[^0-9]', '') AS value from `tabNJQCA Result Parameters`
            where parent=%s and item_group="Laptop storage" and parameter="status" and value like '%%bad sector%%' limit 1
        """

        if wiz_storage_health:
            storage = frappe.db.sql(storage_query,(parent_name), as_dict=True)
            bad_sector_data = frappe.db.sql(bad_sector_query,(parent_name), as_dict=True)

            if storage and storage[0].value:
                if ( bad_sector_data and bad_sector_data[0].value and bad_sectors and float(bad_sector_data[0].value) > float(bad_sectors)):
                    frappe.db.sql("""update `tabNJQCA Result Parameters` set score=41,value="FAIL" where parent=%(parent_name)s and item_group="Laptop storage" and parameter="HDD_Sentinel_Status";""",{'parent_name':parent_name})

                elif float(storage[0].value) >= float(wiz_storage_health):
                    frappe.db.sql("""update `tabNJQCA Result Parameters` set score=0 
                        where parent=%(parent_name)s and item_group="Laptop storage" and parameter="Health";""",{'parent_name':parent_name})
                    frappe.db.sql("""update `tabNJQCA Result Parameters` set score=0,value="PASS" 
                        where parent=%(parent_name)s and item_group="Laptop storage" and parameter="HDD_Sentinel_Status";""",{'parent_name':parent_name})
                
                else:
                    frappe.db.sql("""update `tabNJQCA Result Parameters` set score=41,value="FAIL" where parent=%(parent_name)s and item_group="Laptop storage" and parameter="HDD_Sentinel_Status";""",{'parent_name':parent_name})
                    frappe.db.sql("""update `tabNJQCA Result Parameters` set score=41 where parent=%(parent_name)s and item_group="Laptop storage" and parameter="Health";""",{'parent_name':parent_name})

    except Exception as e:
        frappe.msgprint("Error in NJQCA Storage Score", str(e))
        log_error(traceback.format_exc(), "Error in validate_battery_storage_score in NJQCA")
        return
    
@frappe.whitelist()
def update_storage_type(doc):
    for row in doc.njqca_laptop_storage:
        if row.storage_capacity in ["256 GB", "512 GB"]:
            row.storage_type = "SSD"
        elif row.storage_capacity in ["200 GB", "320 GB", "500 GB"]:
            row.storage_type = "HDD"

@frappe.whitelist()
def set_fail_for_empty_reliability_params(doc):
    """
    If inspection_type is 'Reliability Test':
    1. Fetch all required parameters from NJ Quality Checks
    2. For each required parameter:
       - If missing from njqca_result_parameters -> add new row with FAIL
       - If exists but value is empty -> set value = FAIL, score = 41
    """
    try:
        if not doc.inspection_type:
            return

        if doc.inspection_type.strip().lower() != 'reliability test':
            return

        bios_serial_no = doc.get('bios_serialno') or ''
        serial_no = doc.get('serial_no') or ''

        # ------------------------------------------------
        # STEP 1: Get required parameters from NJ Quality
        # Checks for Reliability Test inspection type
        # ------------------------------------------------
        if serial_no and bios_serial_no:
            rows = frappe.db.sql("""
                SELECT DISTINCT cl.parameter, qc.item_group
                FROM `tabNJ QC Check List` cl
                INNER JOIN `tabNj QC Options` qc_opts
                    ON qc_opts.quality_check = cl.name
                INNER JOIN `tabNJ Quality Checks` qc
                    ON qc.name = qc_opts.parent
                INNER JOIN `tabSerial No` Sr
                    ON Sr.bios_serial_no = %(bios_serial_no)s
                LEFT JOIN `tabModel Specific` MS
                    ON MS.parent = cl.name
                    AND MS.model = Sr.model
                WHERE cl.parameter IS NOT NULL
                AND qc.inspection_type = %(inspection_type)s
                AND qc.status = 'Active'
                AND qc.docstatus = 1
                AND cl.docstatus = 1
                AND (
                    (cl.is_model_specific = 1 AND MS.model IS NOT NULL)
                    OR (cl.exclude_models = 1 AND MS.model IS NULL)
                    OR (cl.is_model_specific = 0 AND cl.exclude_models = 0)
                )
            """, {
                'inspection_type': doc.inspection_type,
                'bios_serial_no': bios_serial_no
            }, as_dict=True)
        else:
            rows = frappe.db.sql("""
                SELECT DISTINCT cl.parameter, qc.item_group
                FROM `tabNJ QC Check List` cl
                INNER JOIN `tabNj QC Options` qc_opts
                    ON qc_opts.quality_check = cl.name
                INNER JOIN `tabNJ Quality Checks` qc
                    ON qc.name = qc_opts.parent
                WHERE cl.parameter IS NOT NULL
                AND qc.inspection_type = %s
                AND qc.status = 'Active'
                AND qc.docstatus = 1
                AND cl.docstatus = 1
            """, (doc.inspection_type,), as_dict=True)

        if not rows:
            return

        # ------------------------------------------------
        # STEP 2: Build map of existing parameters
        # key = parameter name lowercase
        # ------------------------------------------------
        existing_param_map = {}
        for row in doc.get('njqca_result_parameters') or []:
            param = row.get('parameter')
            if param and str(param).strip():
                existing_param_map[str(param).strip().lower()] = row

        # ------------------------------------------------
        # STEP 3: For each required parameter:
        # missing -> add new FAIL row
        # exists but empty value -> set FAIL
        # ------------------------------------------------
        for r in rows:
            param = (r.get('parameter') or '').strip()
            item_group = (r.get('item_group') or '').strip()

            if not param:
                continue

            param_key = param.lower()

            if param_key in existing_param_map:
                # Parameter exists - check if value is empty
                existing_row = existing_param_map[param_key]
                val = existing_row.get('value')
                if val is None or str(val).strip() == '':
                    existing_row.value = 'FAIL'
                    existing_row.score = 41
            else:
                # Parameter completely missing - add new row
                new_row = doc.append('njqca_result_parameters', {})
                new_row.parameter = param
                new_row.value = 'FAIL'
                new_row.score = 41
                new_row.item_group = item_group

    except Exception as e:
        log_error(
            frappe.get_traceback(),
            f"Error in set_fail_for_empty_reliability_params: {str(e)}"
        )

@frappe.whitelist()
def get_item_code_from_rfq_id(rfq_id):
    item_code_from_rfq_id_query = """SELECT item_code FROM `tabRequest for Quotation Item` where parent = %s"""
    return frappe.db.sql(item_code_from_rfq_id_query, rfq_id, as_dict=1)

# Configuration for parameter type detection
PARAMETER_TYPE_MAPPING = {
    'time': [
        'time',
        'restart',
        'excel_time',
        'duration',
        'latency',
        'delay',
        'switching_time'
    ],
    'speed': [
        'speed',
        'transfer_rate',
        'bandwidth',
        'throughput'
    ],
    'size': [
        'size',
        'capacity',
        'storage',
        'file_size'
    ]
}
def normalize_parameter_name(value):
    return str(value or "").strip().lower()


def get_status_parameter_list(setting_parameter):
    raw_value = frappe.db.get_value(
        "NJ Settings",
        {"doc_type": "NJQCA", "parameter": setting_parameter},
        "value"
    )

    if not raw_value:
        raw_value = frappe.db.get_value(
            "NJ Settings",
            {"parameter": setting_parameter},
            "value"
        )

    if not raw_value:
        return []

    raw_value = str(raw_value).strip()

    try:
        parsed = json.loads(raw_value)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except Exception:
        pass

    return [x.strip() for x in raw_value.replace("\n", ",").split(",") if x.strip()]


def evaluate_status_from_criteria(doc, criteria_rows, setting_parameter):
    allowed_parameters = get_status_parameter_list(setting_parameter)

    if not allowed_parameters:
        return []

    allowed_set = {
        normalize_parameter_name(p)
        for p in allowed_parameters
    }

    criteria_map = {}
    for row in criteria_rows or []:
        param = row.get("parameter")
        if param and normalize_parameter_name(param) in allowed_set:
            criteria_map[normalize_parameter_name(param)] = row

    result_map = {}
    for row in doc.get("njqca_result_parameters") or []:
        param = row.get("parameter")
        if param:
            result_map[normalize_parameter_name(param)] = row

    evaluation_results = []

    for parameter in allowed_parameters:
        key = normalize_parameter_name(parameter)

        criteria_row = criteria_map.get(key)
        result_row = result_map.get(key)

        # If parameter is in NJ Settings but not in Criteria Child,
        # skip it instead of failing with blank actual/expected.
        if not criteria_row:
            continue

        expected_value = criteria_row.get("parameter_value")

        # If criteria exists but NJQCA value is missing, then fail.
        if not result_row:
            evaluation_results.append({
                "parameter": parameter,
                "njqca_value": "",
                "expected_range": expected_value,
                "status": "Fail",
                "message": f"{parameter} is in Criteria Child but not found in NJQCA Result Parameters"
            })
            continue

        actual_value = ""

        if key == "average_restart_time":
            avg_time = convert_to_seconds(result_row.get("value"), parameter)

            for result_param in doc.get("njqca_result_parameters") or []:
                if result_param.get("parameter") in ["Restart_1", "Restart_2", "Restart_3"]:
                    if avg_time > convert_to_seconds(result_param.get("value"), result_param.get("parameter")):
                        actual_value = result_param.get("value")

        if not actual_value:
            actual_value = result_row.get("value") or result_row.get("score", "")

        is_passing, message = compare_parameter(
            parameter,
            actual_value,
            expected_value
        )

        evaluation_results.append({
            "parameter": parameter,
            "njqca_value": actual_value,
            "expected_range": expected_value,
            "status": "Pass" if is_passing else "Fail",
            "message": message
        })

    return evaluation_results


def get_final_status_result(status_parameter, evaluation_results, item_group):
    if not evaluation_results:
        return {
            "parameter": status_parameter,
            "value": "FAIL",
            "score": 41,
            "item_group": item_group,
            "part_config_id": 0
        }

    final_status = "PASS"
    final_score = 0

    for row in evaluation_results:
        if row.get("status") == "Fail":
            final_status = "FAIL"
            final_score = 41
            break

    return {
        "parameter": status_parameter,
        "value": final_status,
        "score": final_score,
        "item_group": item_group,
        "part_config_id": 0
    }

def get_direct_status_result(status_parameter, status_value, item_group):
    status_value = str(status_value or "").strip().upper()

    evaluation_results = [{
        "status": "Fail" if status_value == "FAIL" else "Pass"
    }]

    result = get_final_status_result(
        status_parameter=status_parameter,
        evaluation_results=evaluation_results,
        item_group=item_group
    )

    result["value"] = "FAIL" if status_value == "FAIL" else "PASS"
    return result
def update_or_append_result_parameter(njqca_name, result):
    if not njqca_name or not result:
        return

    parameter = result.get("parameter")
    item_group = result.get("item_group")

    if not parameter or not item_group:
        return

    # Dedup only for our new status/reason parameters.
    # This avoids touching other existing NJQCA result parameters.
    allowed_dedup_parameters = {
        "Performance_status",
        "Performance_status_reason",
        "heavy_load_status",
        "heavy_load_status_reason"
    }

    rows = frappe.db.sql("""
        SELECT name, idx
        FROM `tabNJQCA Result Parameters`
        WHERE parent = %s
          AND parameter = %s
          AND item_group = %s
        ORDER BY idx DESC
    """, (njqca_name, parameter, item_group), as_dict=True)

    if rows:
        # Keep latest row based on highest idx
        keep_row = rows[0]

        # Delete duplicate rows only for our status/reason parameters
        if parameter in allowed_dedup_parameters:
            for duplicate in rows[1:]:
                frappe.delete_doc(
                    "NJQCA Result Parameters",
                    duplicate.name,
                    force=True,
                    ignore_permissions=True
                )

        frappe.db.set_value("NJQCA Result Parameters", keep_row.name, {
            "item_group": item_group,
            "value": result.get("value"),
            "score": result.get("score"),
            "part_config_id": result.get("part_config_id") or 0
        })

    else:
        njqca_doc = frappe.get_doc("NJQCA", njqca_name)
        njqca_doc.append("njqca_result_parameters", {
            "item_group": item_group,
            "parameter": parameter,
            "value": result.get("value"),
            "score": result.get("score"),
            "part_config_id": result.get("part_config_id") or 0
        })
        njqca_doc.save(ignore_permissions=True)

def build_status_reason(evaluation_results, status_name):
    """
    Reason field should contain only failed parameter names.
    No prefix like Performance_status or heavy_load_status.
    Keep under 140 chars because NJQCA Result Parameters.value is Data(140).
    """

    MAX_LEN = 135

    if not evaluation_results:
        return "No criteria checked"[:MAX_LEN]

    failed_rows = [
        row for row in evaluation_results
        if str(row.get("status") or "").strip().lower() == "fail"
    ]

    if not failed_rows:
        return "All checked passed"[:MAX_LEN]

    failed_params = []

    for row in failed_rows:
        parameter = str(row.get("parameter") or "").strip()
        message = str(row.get("message") or "").strip()

        if not parameter:
            continue

        if "not found in NJQCA Result Parameters" in message:
            parameter = f"{parameter}(missing)"

        failed_params.append(parameter)

    if not failed_params:
        return "Failed reason unavailable"[:MAX_LEN]

    shown_params = []
    remaining = len(failed_params)

    for param in failed_params:
        suffix = f" +{remaining - 1} more" if remaining > 1 else ""
        test_value = ", ".join(shown_params + [param]) + suffix

        if len(test_value) <= MAX_LEN:
            shown_params.append(param)
            remaining -= 1
        else:
            break

    reason = ", ".join(shown_params)

    if remaining > 0:
        reason += f" +{remaining} more"

    return reason[:MAX_LEN]

def process_performance_and_heavyload_status(doc, criteria_rows):
    """
    Performance_status checks only:
        NJ Settings -> performance_status_parameters

    heavy_load_status checks only:
        NJ Settings -> heavy_load_status_parameters

    Important:
    Do not depend only on direct DB update here.
    This function must return all changes to JS, so JS can add rows into
    frm.doc.njqca_result_parameters before save.
    """

    performance_evaluation_results = evaluate_status_from_criteria(
        doc=doc,
        criteria_rows=criteria_rows,
        setting_parameter="performance_status_parameters"
    )

    performance_result = get_final_status_result(
        status_parameter="Performance_status",
        evaluation_results=performance_evaluation_results,
        item_group="Software Configuration"
    )

    performance_reason = build_status_reason(
        performance_evaluation_results,
        "Performance_status"
    )

    performance_reason_result = {
        "parameter": "Performance_status_reason",
        "value": performance_reason,
        "score": performance_result.get("score"),
        "item_group": "Software Configuration",
        "part_config_id": 0
    }

    heavyload_evaluation_results = evaluate_status_from_criteria(
        doc=doc,
        criteria_rows=criteria_rows,
        setting_parameter="heavy_load_status_parameters"
    )

    heavyload_result = get_final_status_result(
        status_parameter="heavy_load_status",
        evaluation_results=heavyload_evaluation_results,
        item_group="LAPTOP STORAGE"
    )

    heavyload_reason = build_status_reason(
        heavyload_evaluation_results,
        "heavy_load_status"
    )

    heavyload_reason_result = {
        "parameter": "heavy_load_status_reason",
        "value": heavyload_reason,
        "score": heavyload_result.get("score"),
        "item_group": "LAPTOP STORAGE",
        "part_config_id": 0
    }

    results = [
        performance_result,
        performance_reason_result,
        heavyload_result,
        heavyload_reason_result
    ]

    return {
        "changes": results
    }

def get_criteria_child_rows_from_name(criteria_name):
    """
    Load Criteria Child rows from Performance Criteria doctype.
    criteria_name is Performance Criteria doc name like Designer / Coding / Gamer.
    """

    criteria_name = (criteria_name or "").strip()

    if not criteria_name:
        return [], ""

    if not frappe.db.exists("Performance Criteria", criteria_name):
        frappe.log_error(
            f"Performance Criteria not found: {criteria_name}",
            "NJQCA Performance Criteria Lookup"
        )
        return [], criteria_name

    criteria_doc = frappe.get_doc("Performance Criteria", criteria_name)
    return criteria_doc.get("criteria_child") or [], criteria_name


def get_performance_heavyload_criteria_rows(doc, item_code, transformed_data, item_wizard_doc):
    """
    Criteria lookup priority:
    1. Shopify Item List: item_code -> performance_criteria
    2. Performance Config Criteria: processor + ram + ssd -> criteria
    3. NJ Settings fallback: performance_heavyload_fallback_criteria-> Performance Criteria
    """

    item_code = (item_code or "").strip()

    # 1. First check Shopify Item List by exact item_code
    for row in item_wizard_doc.get("shopify_item_list") or []:
        row_item_code = (row.get("item_code") or "").strip()
        criteria_name = (row.get("performance_criteria") or "").strip()

        if row_item_code == item_code and criteria_name:
            criteria_rows, criteria_name = get_criteria_child_rows_from_name(criteria_name)

            if criteria_rows:
                return criteria_rows, "shopify_item_list", criteria_name

    # 2. Fallback to Performance Config Criteria by processor + ram + ssd
    for row in item_wizard_doc.get("performance_config_criteria") or []:
        row_data = {
            "processor": (row.get("processor") or "").strip().lower(),
            "ram": (row.get("ram") or "").strip().lower(),
            "ssd": (row.get("ssd") or "").strip().lower()
        }

        if transformed_data == row_data:
            criteria_name = (row.get("criteria") or "").strip()
            criteria_rows, criteria_name = get_criteria_child_rows_from_name(criteria_name)

            if criteria_rows:
                return criteria_rows, "performance_config_criteria", criteria_name

    # 3. Final fallback from NJ Settings
    fallback_criteria_name = frappe.db.get_value(
        "NJ Settings",
        {
            "doc_type": "NJQCA",
            "parameter": "performance_heavyload_fallback_criteria"
        },
        "value"
    )

    criteria_rows, criteria_name = get_criteria_child_rows_from_name(fallback_criteria_name)

    if criteria_rows:
        return criteria_rows, "nj_settings_fallback", criteria_name

    return [], "not_found", ""

@frappe.whitelist()
def update_performance_criteria(doc):
    import json

    if isinstance(doc, str):
        doc = json.loads(doc)

    inspection_type = (doc.get("inspection_type") or "").strip().lower()
    is_reliability_test = inspection_type == "reliability test"
    perf_or_heavyload_file_present = has_perf_or_heavyload_test_file(doc)

    # Reliability Test always allowed.
    # Final QC / other inspection types allowed only when real performance/heavyload file exists.
    if not is_reliability_test and not perf_or_heavyload_file_present:
        return {
            "skip": True,
            "message": "Performance/HeavyLoad evaluation skipped because no actual test file is present"
        }

    item_code = (doc.get("manual_repack_item_code") or "").strip()

    if not item_code:
        frappe.msgprint(_("Item code is missing."), alert=True)
        return {
            "error": "Item code is missing."
        }

    # Get item config from Manual Repack Item Code
    get_item_config = """
        SELECT 
            LOWER(iva.attribute) AS attribute,
            LOWER(iva.attribute_value) AS value
        FROM `tabItem Variant Attribute` iva
        WHERE iva.parent = %s
    """

    item_config = frappe.db.sql(get_item_config, (item_code,), as_dict=True)
    transformed_data = transform_item_config(item_config)

    # Get latest completed Item Wizard for model + item_template
    item_wizard_list = frappe.db.sql(
        """
            SELECT `name`
            FROM `tabItem Wizards`
            WHERE `model` = %s
              AND `item_template` = %s
              AND `docstatus` = 1
              AND `part_list_status` = 'Completed'
            ORDER BY `modified` DESC
            LIMIT 1
        """,
        (doc.get("model"), doc.get("item_template")),
        as_dict=True
    )

    if not item_wizard_list:
        frappe.msgprint(_("No submitted Item Wizards found."), alert=True)
        return {
            "error": "No submitted Item Wizards found."
        }

    item_wizard_doc = frappe.get_doc("Item Wizards", item_wizard_list[0].name)

    # New criteria lookup order:
    # 1. Shopify Item List
    # 2. Performance Config Criteria
    # 3. NJ Settings fallback criteria
    criteria_rows, criteria_source, criteria_name = get_performance_heavyload_criteria_rows(
        doc=doc,
        item_code=item_code,
        transformed_data=transformed_data,
        item_wizard_doc=item_wizard_doc
    )

    if not criteria_rows:
        return {
            "error": (
                "No Performance Criteria found from Shopify Item List, "
                "Performance Config Criteria, or NJ Settings fallback."
            ),
            "debug": {
                "item_code": item_code,
                "transformed_data": transformed_data,
                "item_wizard": item_wizard_doc.name,
                "criteria_source": criteria_source,
                "criteria_name": criteria_name
            }
        }

    # Existing calculation logic remains same:
    # criteria_rows -> NJ Settings parameter list -> NJQCA values -> compare -> final status/reason
    result = process_performance_and_heavyload_status(
        doc,
        criteria_rows
    )

    # Debug info for bench console
    result["criteria_source"] = criteria_source
    result["criteria_name"] = criteria_name
    result["item_wizard"] = item_wizard_doc.name
    result["item_code"] = item_code
    result["transformed_data"] = transformed_data

    return result
def transform_item_config(item_config):
    """Transforms item attribute data into a structured dictionary."""

    attribute_map = {
        "storage capacity": "ssd",
        "ram capacity": "ram",
        "processor type": "processor",
        "processor type1": "processor",
        "processor": "processor"
    }

    transformed_data = {}

    for item in item_config:
        attribute = str(item.get("attribute") or "").strip().lower()
        value = str(item.get("value") or "").strip().lower()

        if attribute in attribute_map and value:
            transformed_key = attribute_map[attribute]
            transformed_data[transformed_key] = value

    return transformed_data

def get_parameter_type(param_name):
    """Determine the parameter type based on its name."""
    param_name_lower = param_name.lower()
    for param_type, keywords in PARAMETER_TYPE_MAPPING.items():
        if any(keyword in param_name_lower for keyword in keywords):
            return param_type
    return None

def compare_operator_condition(actual_value, expected_range):
    actual_text = str(actual_value or "").strip()
    expected_text = str(expected_range or "").strip().replace(" ", "")

    actual_numbers = extract_numbers(actual_text)
    expected_numbers = extract_numbers(expected_text)

    if expected_numbers and not actual_numbers:
        return False, f"{actual_value} has no numeric value to compare with {expected_range}"

    if not expected_numbers:
        if actual_text.lower() == str(expected_range or "").strip().lower():
            return True, f"{actual_value} matches expected {expected_range}"
        return False, f"{actual_value} does not match expected {expected_range}"

    actual = actual_numbers[0]

    if expected_text.startswith(">="):
        limit = expected_numbers[0]
        return actual >= limit, f"{actual_value} {'satisfies' if actual >= limit else 'does not satisfy'} {expected_range}"

    if expected_text.startswith(">"):
        limit = expected_numbers[0]
        return actual > limit, f"{actual_value} {'satisfies' if actual > limit else 'does not satisfy'} {expected_range}"

    if expected_text.startswith("<="):
        limit = expected_numbers[0]
        return actual <= limit, f"{actual_value} {'satisfies' if actual <= limit else 'does not satisfy'} {expected_range}"

    if expected_text.startswith("<"):
        limit = expected_numbers[0]
        return actual < limit, f"{actual_value} {'satisfies' if actual < limit else 'does not satisfy'} {expected_range}"

    if "-" in expected_text and len(expected_numbers) >= 2:
        min_val = expected_numbers[0]
        max_val = expected_numbers[1]
        ok = min_val <= actual <= max_val
        return ok, f"{actual_value} {'is within' if ok else 'is outside'} range {expected_range}"

    limit = expected_numbers[0]
    return actual == limit, f"{actual_value} {'equals' if actual == limit else 'does not equal'} {expected_range}"

def compare_parameter(param_name, actual_value, expected_range):
    """Compare actual value with expected range and return pass/fail status."""
    try:
        actual_text = str(actual_value or "").strip()
        expected_text = str(expected_range or "").strip()

        # If expected criteria is numeric/range/operator based,
        # but actual value is text like NOT RECOVERED / No I/O data / ERROR,
        # then it should fail directly.
        numeric_expected = bool(
            re.search(r"(>=|<=|>|<)", expected_text)
            or re.search(r"\d+\s*[-–]\s*\d+", expected_text)
            or re.search(r"\d+", expected_text)
        )

        actual_has_number = bool(re.search(r"\d+(?:\.\d+)?", actual_text))

        invalid_actual_words = [
            "NOT RECOVERED",
            "NO I/O DATA",
            "ERROR",
            "NO STRESS DATA",
            "NO TIME COLUMN",
            "NO VALID DATA"
        ]

        if numeric_expected and (
            not actual_has_number
            or any(word in actual_text.upper() for word in invalid_actual_words)
        ):
            return False, f"{actual_text or 'blank'} is not a valid numeric value for expected range {expected_text}"

        param_type = get_parameter_type(param_name)
        
        if param_type == 'time':
            actual_seconds = convert_to_seconds(actual_value,param_name)
            min_sec, max_sec = parse_time_range(expected_range)
            
            if min_sec <= actual_seconds <= max_sec:
                return True, f"{actual_value} is within range {expected_range}"
            return False, f"{actual_value} is outside range {expected_range}"
                
        elif param_type == 'speed':
            expected_text = str(expected_range or "").strip()

            if expected_text.startswith((">", "<")):
                return compare_operator_condition(actual_value, expected_range)

            actual_speed = extract_number(actual_value)
            min_speed, max_speed = parse_speed_range(expected_range)
            
            if min_speed <= actual_speed <= max_speed:
                return True, f"{actual_value} is within range {expected_range}"
            return False, f"{actual_value} is outside range {expected_range}"
                
        elif param_type == 'size':
            actual_size = convert_to_bytes(actual_value)
            expected_size = convert_to_bytes(expected_range)
            
            if actual_size == expected_size:
                return True, f"{actual_value} matches expected {expected_range}"
            return False, f"{actual_value} doesn't match expected {expected_range}"
                
        else:
            return compare_operator_condition(actual_value, expected_range)
                
    except Exception as e:
        log_error(f"Error comparing parameter {param_name}: {str(e)}", "An error occurred in compare_parameter in NJQCA")
        return False, f"Comparison error: {str(e)}"

def convert_to_seconds(time_str,param_name=""):
    """Convert time string to seconds."""
    if (not time_str or str(time_str).lower() == "none") and param_name.lower() == "excel_time":
        return 0
    if not time_str or str(time_str).lower() == "none":
        return 0
        
    time_str = str(time_str).strip()
    
    if "second" in time_str.lower():
        try:
            return float(time_str.split()[0])
        except (ValueError, IndexError):
            return 0
    
    hours = 0
    minutes = 0
    seconds = 0
    
    parts = time_str.split()
    for part in parts:
        part = part.lower()
        if 'h' in part:
            hours = float(part.replace('h', ''))
        elif 'm' in part:
            minutes = float(part.replace('m', ''))
        elif 's' in part:
            seconds_str = part.replace('s', '')
            seconds = float(seconds_str) if '.' in seconds_str else int(seconds_str)
    
    return hours * 3600 + minutes * 60 + seconds

def parse_time_range(range_str):
    """Parse time range into min and max seconds."""
    if not range_str:
        return 0, 0
    
    range_str = str(range_str).lower()
    numbers = extract_numbers(range_str)
    
    unit = 'sec'
    if 'min' in range_str:
        unit = 'min'
    
    if len(numbers) >= 2:
        min_val, max_val = numbers[0], numbers[1]
    elif numbers:
        min_val = max_val = numbers[0]
    else:
        min_val = max_val = 0
    
    if unit == 'min':
        return min_val * 60, max_val * 60
    return min_val, max_val

def parse_speed_range(range_str):
    """Parse speed range into min and max values."""
    numbers = extract_numbers(range_str)
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    elif numbers:
        return numbers[0], numbers[0]
    return 0, 0

def extract_numbers(text):
    """Extract all numbers from a string."""
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(text or ""))]

def extract_number(value_str):
    """Extract the first number from a string."""
    numbers = extract_numbers(value_str)
    return numbers[0] if numbers else 0

def convert_to_bytes(size_str):
    """Convert size string to bytes."""
    if not size_str:
        return 0
    
    size_str = str(size_str).upper()
    parts = size_str.split()
    
    if not parts:
        return 0
    
    try:
        size = float(parts[0])
    except ValueError:
        return 0
    
    if len(parts) == 1:
        return size
    
    unit = parts[1]
    size_map = {
        'KB': 1024,
        'MB': 1024 * 1024,
        'GB': 1024 * 1024 * 1024,
        'TB': 1024 * 1024 * 1024 * 1024
    }
    
    for unit_key, multiplier in size_map.items():
        if unit_key in unit:
            return size * multiplier
    return size

def update_njqca_doc(njqca_name, evaluation_results):
    """Update the NJQCA document with evaluation results."""
    if not njqca_name or not evaluation_results:
        return
    
    try:
        njqca_doc = frappe.get_doc("NJQCA", njqca_name)
        
        if hasattr(njqca_doc, "performance_evaluation"):
            njqca_doc.performance_evaluation = []
        
        for result in evaluation_results:
            njqca_doc.append("performance_evaluation", {
                "parameter": result["parameter"],
                "actual_value": str(result["njqca_value"]),
                "expected_range": str(result["expected_range"]),
                "status": result["status"],
                "message": result["message"]
            })
        
        njqca_doc.save()
    except Exception as e:
        log_error(f"Error updating NJQCA document {njqca_name}: {str(e)}")
        
@frappe.whitelist()
def get_battery_serialno(bios_serial_no,inspection_type,creation_date):
    try:
        inspection_types = frappe.db.get_value("NJ Settings",{"doc_type": "NJQCA","parameter":"get_battery_serial_no"},"value")

        if inspection_types is not None and inspection_types:
            if inspection_type in inspection_types:
                return ""
            else:
                pass
        else:
            return ""

        nj_serial_no_query="""
            Select name from `tabSerial No` where bios_serial_no=%s limit 1;          
        """
        serial_no=frappe.db.sql(nj_serial_no_query,bios_serial_no,as_dict=1)

        nj_serial_no=""
        if serial_no:
            nj_serial_no=serial_no[0].name
        # query="""
        #     SELECT tot_sed.serial_no as battery_serial_no
        #     FROM `tabStock Entry Detail` AS sed
        #     INNER JOIN `tabStock Entry Detail` AS tot_sed ON tot_sed.parent = sed.parent
        #     INNER JOIN `tabStock Entry` AS stock_entry ON stock_entry.name = sed.parent
        #     WHERE
        #         (sed.serial_no = %(serial_no)s OR 
        #             sed.serial_no LIKE CONCAT(%(serial_no)s, '\\n%%') OR 
        #             sed.serial_no LIKE CONCAT('%%\\n', %(serial_no)s) OR 
        #             sed.serial_no LIKE CONCAT('%%\\n', %(serial_no)s, '\\n%%')) AND
        #         stock_entry.purpose = 'Repack' AND 
        #         stock_entry.docstatus = 1 AND
        #         tot_sed.s_warehouse IS NOT NULL AND 
        #         tot_sed.item_group = 'Battery' AND
        #         tot_sed.creation < %(njqca_creation)s
        #     ORDER BY stock_entry.creation DESC
        #     LIMIT 1
        # """
        partlist_query="""
          Select component_serial_no as battery_serial_no from `tabSerial No Component` where parent=%s and item_group="BATTERY" and component_serial_no <> '' order by item_group_idx desc limit 1;
        """
        if nj_serial_no is not None and nj_serial_no:          
            data=frappe.db.sql(partlist_query, nj_serial_no, as_dict=1)
            log_error(str(data),"repacked battery serial_no  through part list for bios serial no "+bios_serial_no)
            if data is not None and data:  
                return data[0].get("battery_serial_no")
        
        return ""
        
    except Exception as e:
        log_error(traceback.format_exc(), "An error occurred in get_battery_serialno in battery NJQCA "+bios_serial_no)
        return ""

# @frappe.whitelist()
# def get_item_group_mapping(parent):
#     data = frappe.get_all(
#         "NJQCA Child",
#         filters={"item_group": "Laptop Processors", "parent": parent},
        
#         fields=["item_group", "variant_6"]
#     )
#     return data

@frappe.whitelist()
def get_item_group_mapping(parent):
    data = frappe.get_all(
        "NJQCA Child",
        filters={"item_group": "Laptop Processors", "parent": parent},
        fields=["item_group", "variant_6"]
    )
    return data

@frappe.whitelist()
def check_for_mis_config(doc):
    if isinstance(doc, str):
        doc = json.loads(doc)

    serial_no_item_code = doc.get("item_code")
    automated_item_code = doc.get("repack_item_code")

    if serial_no_item_code == automated_item_code:
        return {
            "parameter": "mis_configuration_status",
            "value": "PASS",
            "score": 0,
            "item_group": "Software Configuration",
            "part_config_id": 0
        }
    else:
        return {
            "parameter": "mis_configuration_status",
            "value": "FAIL",
            "score": 41,
            "item_group": "Software Configuration",
            "part_config_id": 0
        }
    
@frappe.whitelist() 
def get_bdt_status(doc, method=None):
    try:
        if isinstance(doc, str):
            doc = frappe.parse_json(doc)
        if doc.item_group != 'BATTERY' :
            return 
        
        njqca_name=doc.name
        manufacturer_model=doc.manufacturer_model
        iw=get_item_wizard_data(manufacturer_model)
        required_backup=0
        backup=False
        sudden_drop=False
        sudden_drop_status=doc.sudden_drop

        backup1=doc.backup_duration_cycle_1
        backup2=doc.backup_duration_cycle_2
        backup3=doc.backup_duration_cycle_3

        if iw:
            try:
                required_backup=int(iw.get("backup_duration_mins"))
            except Exception as e:
                pass
        
        if required_backup==0:
            required_backup=110

        if backup3 is not None and backup3:
            if float(backup3)>=required_backup:
                backup=True
     
        elif backup2 is not None and backup2:
            if float(backup2)>=required_backup:
                backup=True

        elif backup1 is not None and backup1:
            if float(backup1)>=required_backup:
                backup=True
            
        if sudden_drop_status is not None and sudden_drop_status:
            if "NO" in sudden_drop_status:
                sudden_drop=True
            
        if sudden_drop and backup:
            return "Pass"
        else:
            return "Fail"
        
    except Exception:
        log_error(traceback.format_exc(), "An error occurred at get_bdt_status in NJQCA "+njqca_name)
        return f"ERROR While BDT status: {traceback.format_exc()}"

@frappe.whitelist()
def check_ram_speed(njqca_name,item_template):
    try:
        get_ram_query="""
            SELECT 
            CAST(REGEXP_SUBSTR(`value`, '[0-9]+') AS UNSIGNED) AS ram_speed
            FROM `tabNJQCA Result Parameters`
            WHERE item_group = "LAPTOP RAM"
            AND parameter LIKE 'Ram_Speed%%' 
            AND parent = %s;
        """

        iw_speed_query="""
            select CAST(REGEXP_SUBSTR(attribute_value, '[0-9]+') AS UNSIGNED) AS ram_speed
            from `tabItems Attribute` where item_group="LAPTOP RAM" and item_attribute="RAM Speed" and parent=%s; 
            """

        iw=get_latest_item_wizard(item_template=item_template)

        if iw is None:
            return ""
        
        iw_speeds=frappe.db.sql(iw_speed_query, (iw), as_dict=1)

        required_speeds=[]

        if iw_speeds is not None and iw_speeds:
            for iw_speed in iw_speeds:
                if iw_speed.get("ram_speed"):
                    required_speeds.append(iw_speed.get("ram_speed"))
        
        if not required_speeds:
            return "PASS"

        njqca_ram_speeds=frappe.db.sql(get_ram_query, (njqca_name), as_dict=1)

        if njqca_ram_speeds is not None and njqca_ram_speeds:
            for njqca_ram_speed in njqca_ram_speeds:
                if njqca_ram_speed.get("ram_speed"):
                    if not (njqca_ram_speed.get("ram_speed") in required_speeds):
                        return "FAIL"
            return "PASS"
        else:
            return ""
    except Exception as e:
        return str(e)
    

@frappe.whitelist()
def set_is_defective(inspection_type):
    try:        
        allowed_inspection_types = frappe.db.get_value("Inspection Type",{"name":inspection_type},"check_only_defectives")

        if allowed_inspection_types is not None and allowed_inspection_types:
            if allowed_inspection_types == 1:
                return "1"
            else:
                return "0"
        else:
            return "0"
    except Exception as e:
        return str(e)   

@frappe.whitelist()
def get_item_code_for_ram(item_code, njqca_name):
    try:
        ram_data_query="""
            select variant_6 as size, variant_7 as type, variant_8 as speed 
            from `tabNJQCA Child` where parent=%s and item_group="Laptop RAM" LIMIT 1;
        """

        ram_size=""
        ram_type=""
        ram_speed=""

        ram_data=frappe.db.sql(ram_data_query, (njqca_name), as_dict=1)

        if ram_data is not None and ram_data:
            ram_size=ram_data[0].get("size").strip()
            ram_type=ram_data[0].get("type").strip()
            ram_speed_with_unit=ram_data[0].get("speed").strip()

            numbers = re.findall(r'\d+', ram_speed_with_unit)
            ram_speed= ''.join(numbers)           
        else:
            return ""
        
        sub_config=[]
        new_config=""
        item_code_query="""
            select '1' from `tabItem` where item_group="Laptop RAM" and disabled=0 and name=%s;
        """
        if item_code is not None and item_code:
            sub_config=item_code.split("-")
        if sub_config and len(sub_config)==6:
            new_config=sub_config[0]+"-"+sub_config[1]

            if sub_config[2]!=ram_type:
                new_config=new_config+"-"+ram_type
            else:
                new_config=new_config+"-"+sub_config[2]

            if sub_config[4]!=ram_size:
                new_config=new_config+"-"+ram_size
            else:
                new_config=new_config+"-"+sub_config[4]

            if sub_config[3]!=ram_speed:
                new_config=new_config+"-"+ram_speed + " GHZ"
            else:
                new_config=new_config+"-"+sub_config[3]

            new_config=new_config+"-"+sub_config[5]

            item_code_data=frappe.db.sql(item_code_query, (new_config), as_dict=1)

            if item_code_data is not None and item_code_data and item_code_data[0].get("1")=="1":
                return new_config
            else:
                return ""        

        else:
            return ""
    except Exception as e:
        return str(e)
    
@frappe.whitelist()
def get_product_key(doc,method=None):
    try:
      item_group=doc.get("item_group")
      if item_group!="Laptops":
          return
      njqca_name=doc.get("name")
      serial_no=doc.get("serial_no")

      if njqca_name:
        product_key=""
        product_key_query="""
            Select value from `tabNJQCA Result Parameters` where parent=%s and parameter='Product_key';
        """

        update_query="""
            update `tabSerial No` set product_key=%(product_key)s where parent=%(serial_no)s;
        """
        product_key_data=frappe.db.sql(product_key_query, (njqca_name), as_dict=1)
        if product_key_data is not None and product_key_data:
            product_key= product_key_data[0].get("value")
        if product_key and serial_no:
            frappe.db.sql(update_query, {"product_key":product_key,"serial_no":serial_no})
                   
    except Exception:
        log_error(traceback.format_exc(), "An error occurred in get_product_key in NJQCA "+njqca_name)


@frappe.whitelist()
def get_avg_discharge_rate(njqca_name):
    try:      
      query="""
        select round(avg(discharge_rate),4) as discharge_rate from `tabNJQCA Result Parameters` where parent=%s
      """

      avg_discharge_rate=frappe.db.sql(query, (njqca_name), as_dict=1)

      if avg_discharge_rate is not None and avg_discharge_rate:
        return avg_discharge_rate[0].get("discharge_rate")
      
    except Exception as e:
        log_error(traceback.format_exc(), "An error occurred in get_avg_discharge_rate in NJQCA "+njqca_name)

# @frappe.whitelist()   - not used because returning item template instead of item code
# def generate_automated_repack_item_code(doc):
#     import json
#     import re
#     from collections import defaultdict

#     if isinstance(doc, str):
#         doc = json.loads(doc)

#     # ===== Processor =====
#     processor_data = [
#         {"processor_type": item.get("processor_type")}
#         for item in doc.get("njqca_laptop_processors", [])
#     ]

#     # ===== RAM =====
#     total_ram_gb = sum(
#         int(re.search(r'(\d+)\s*GB', item.get("ram_capacity", "").upper()).group(1))
#         for item in doc.get("njqca_laptop_ram", [])
#         if re.search(r'(\d+)\s*GB', item.get("ram_capacity", "").upper())
#     )
#     merged_ram = [{"ram_capacity": f"{total_ram_gb} GB"}] if total_ram_gb else []

#     # ===== Storage =====
#     storage_table = doc.get("njqca_laptop_storage", [])
#     storage_by_type = defaultdict(float)

#     for item in storage_table:
#         raw_capacity = item.get("storage_capacity", "").upper()
#         storage_type = item.get("storage_type", "").upper()

#         match = re.search(r'(\d+(?:\.\d+)?)\s*(GB|TB)', raw_capacity)
#         if not match:
#             continue

#         size = float(match.group(1))
#         unit = match.group(2)
#         size_in_gb = size * 1024 if unit == "TB" else size

#         # ✅ Only consider SSD or HDD
#         if storage_type in ["SSD", "HDD"]:
#             final_type = storage_type
#         elif "SSD" in raw_capacity:
#             final_type = "SSD"
#         elif "HDD" in raw_capacity:
#             final_type = "HDD"
#         else:
#             continue  # Ignore types like MSATA, EMMC, etc.

#         storage_by_type[final_type] += size_in_gb

#     # ===== Format storage (with GB ➜ TB conversion if ≥ 1000 GB) =====
#     merged_storage = []
#     for s_type, total_gb in storage_by_type.items():
#         if total_gb >= 1000:
#             tb_value = round(total_gb / 1024, 1)
#             # Optional: round to int if it's exact TB
#             size_str = f"{int(tb_value)} TB" if tb_value.is_integer() else f"{tb_value:.1f} TB"
#         else:
#             size_str = f"{int(total_gb)} GB"
#         merged_storage.append({"storage_capacity": f"{size_str} {s_type}"})

#     # ===== Final Args =====
#     args = processor_data + merged_ram + merged_storage

#     variant_code = get_variant_from_value(doc.get("item_template"), args=args)

#     if not variant_code:
#         return {
#             "error": True,
#             "message": "❌ Automated item code not found. Please check the configuration."
#         }

#     return variant_code


@frappe.whitelist()
def create_serial_no_based_on_rfq(serial_info):
        try:
            if isinstance(serial_info, str):
                serial_info = json.loads(serial_info)
            query = """
                SELECT serial_no FROM `tabSerial No` WHERE serial_no = %s AND (rfq_id is null or rfq_id ="");
            """
            serial_no=serial_info.get('serial_no')
            result=None
            if serial_no:
                result=frappe.db.sql(query,(serial_no),as_dict=1)
            if result is not None and len(result)>0:
                frappe.throw("Serial No: <b>" + serial_info.get('serial_no') + "</b> already exists.")

            exist_query="""
                SELECT serial_no FROM `tabSerial No` WHERE serial_no = %s AND rfq_id is not null;
            """
            serial_no_result=None
            if serial_no:
                serial_no_result=frappe.db.sql(exist_query,(serial_no),as_dict=1)
            if serial_no_result is not None and len(serial_no_result)>0:
                return "Already exists"

            sn_doc = frappe.new_doc("Serial No")
            sn_doc.model = serial_info.get('model')
            sn_doc.rfq_id = serial_info.get('rfq_id')
            sn_doc.name = serial_info.get('serial_no')
            sn_doc.item_source = serial_info.get('doctype')
            sn_doc.item_code = serial_info.get('item_code')
            sn_doc.item_name = serial_info.get('item_code')
            sn_doc.serial_no = serial_info.get('serial_no')
            sn_doc.item_group = serial_info.get('item_group')
            sn_doc.description = serial_info.get('item_code')
            sn_doc.bios_serial_no = serial_info.get('bios_serialno')
            sn_doc.reference_doctype_no = serial_info.get('name')

            sn_doc.save()
            frappe.msgprint("Serial No: <b>" + serial_info.get('serial_no') + "</b> is created successfully.")

        except Exception as e:
            frappe.db.rollback()
            frappe.throw("Error creating Serial No: " + str(e))
            return None
        

@frappe.whitelist()
def validate_model(model,manufacturer_model):
    try:
        if manufacturer_model and model:
            query = """
                select parent from `tabManufacturer Model Child` where manufacturer_model=%s and parent=%s;
            """
            result=frappe.db.sql(query,(manufacturer_model,model),as_dict=1)
            if result is not None and len(result)>0:
                return "1"
        return "0"
    
    except Exception as e:
        frappe.throw("Error While validating Model: " + str(e))
        return None
    
@frappe.whitelist()
def get_empty_param_in_child(item_code):
    result = frappe.db.sql("""
        SELECT attribute, attribute_value 
        FROM `tabItem Variant Attribute` 
        WHERE parent = %s
    """, item_code, as_list=True)

    data = {to_snake_case(attr): value for attr, value in result}
    
    return data

def to_snake_case(s):
    """Convert a string like 'RAM Type' to 'ram_type'."""
    s = re.sub(r'[^a-zA-Z0-9 ]', '', s)
    return '_'.join(word.lower() for word in s.strip().split())

@frappe.whitelist()
def get_disp_and_adp_data(serial_no):
    disp_and_adp_data_query = """
        SELECT item as fetched_item_code, item_group, grade  
        FROM `tabSerial No Component` 
        WHERE parent = %s AND item_group IN ('Laptop Adaptors', 'Display')
    """
    disp_and_adp_data = frappe.db.sql(disp_and_adp_data_query, (serial_no,), as_dict=1)

    found_item_groups = {d['item_group'] for d in disp_and_adp_data}

    required_groups = {'Laptop Adaptors', 'Display'}
    missing_groups = required_groups - found_item_groups

    if missing_groups:
        item_wizards = frappe.db.get_value("Serial No", serial_no, "item_wizard")
        
        if item_wizards:
            for group in missing_groups:
                bag_list_query = """
                    SELECT item as fetched_item_code, item_group FROM `tabBag List`
                    WHERE parent = %s AND item_group = %s AND is_available = 1 AND quantity > 0
                    LIMIT 1
                """
                bag_list_data = frappe.db.sql(bag_list_query, (item_wizards, group), as_dict=1)
                if bag_list_data:
                    disp_and_adp_data.extend(bag_list_data)

                else:
                    component_query = """
                        SELECT default_item_code as fetched_item_code, component_type as item_group
                        FROM `tabComponent`
                        WHERE parent = %s AND component_type = %s
                        LIMIT 1
                    """
                    component_data = frappe.db.sql(component_query, (item_wizards, group), as_dict=1)
                    if component_data:
                        disp_and_adp_data.extend(component_data)

    for data in disp_and_adp_data:
        item_data = get_empty_param_in_child(data.get('fetched_item_code'))
        data.update(item_data)

    return disp_and_adp_data
    

@frappe.whitelist()
def duplicate_njqca(serial_no):
    """Fetch latest NJQCA by serial number and prepare a duplicate (unsaved)"""

    tech_inspection_type = frappe.db.get_value("NJ Settings", {"parameter": 'core-iqc-tech-inspection'}, "value")
    dismantle_inspection_type = frappe.db.get_value("NJ Settings", {"parameter": 'core-iqc-dismantle-inspection'}, "value")

    if not tech_inspection_type:
        frappe.throw("Please set Core IQC Dismantle Inspection in NJ Settings")
    if not dismantle_inspection_type:
        frappe.throw("Please set Core IQC Dismantle Inspection in NJ Settings")
    record = frappe.db.sql("""
        SELECT name 
        FROM `tabNJQCA` 
        WHERE serial_no=%s and inspection_type=%s and docstatus = 1 and item_group='Laptops'
        ORDER BY creation DESC 
        LIMIT 1
    """, (serial_no,tech_inspection_type), as_dict=True)

    if not record:
        return None

    doc = frappe.get_doc("NJQCA", record[0].name)

    new_doc = frappe.copy_doc(doc, ignore_no_copy=False)

    new_doc.set("name", None)
    new_doc.set("created", frappe.session.user)
    new_doc.set("inspection_type", dismantle_inspection_type)
    is_defective=frappe.db.get_value('Inspection Type', dismantle_inspection_type, 'check_only_defectives')
    if is_defective:
       new_doc.set('qi_type',"is_defective")

    return new_doc.as_dict(no_nulls=True)

@frappe.whitelist()
def adaptor_charge_gain_status(njqca_name, serial_no):
    if njqca_name and serial_no:
        sr_no_item_group=frappe.db.get_value("Serial No", serial_no, "item_group")
        if sr_no_item_group!="Laptop Adaptors":
            frappe.throw("Serial No: <b>" + serial_no + "</b> is not a Laptop Adaptor.")
        status=frappe.db.exists('NJQCA Result Parameters',{'parent':njqca_name,'parameter':'Adapterbattery_status'})
        print(status)
        if not status:
            return ""
        item_code=frappe.db.get_value("Serial No", serial_no, "item_code")
        wattage=frappe.db.get_value("Item Variant Attribute",{'parent':item_code,'attribute':"Wattage Capacity"},"attribute_value")
        wattage=''.join(str.isdigit(), wattage)
        print(wattage)
        query="""
            select parameter, value from `tabNJQCA Result Parameters` where parent=%s and item_group="Laptop Adaptors" and 
            (parameter="final_percentage" or parameter="initial_percentage");
        """
        percentage=frappe.db.sql(query,(njqca_name),as_dict=True)
        final_percentage=None
        initial_percentage=None
        if percentage:
            for p in percentage:
                if p.parameter=="final_percentage":
                    final_percentage=p.value
                if p.parameter=="initial_percentage":
                    initial_percentage=p.value
        print(final_percentage)
        print(initial_percentage)
        if final_percentage and initial_percentage and wattage:
            return check_charging_gain(int(wattage), int(initial_percentage), int(final_percentage))

        
                
def check_charging_gain(wattage: int, initial_percentage: int, final_percentage: int) -> str:
    gain = final_percentage - initial_percentage
    min_gain = max_gain = 0

    if initial_percentage < 20:
        soc_range = "0-20"
    elif initial_percentage < 40:
        soc_range = "20-40"
    elif initial_percentage < 70:
        soc_range = "40-70"
    elif initial_percentage < 80:
        soc_range = "70-80"
    elif initial_percentage < 95:
        soc_range = "80-95"
    else:
        soc_range = "95-100"

    if soc_range == "0-20":
        if wattage == 45: min_gain, max_gain = 3, 3
        elif wattage == 65: min_gain, max_gain = 4, 7
        elif wattage == 90: min_gain, max_gain = 6, 9
        elif wattage == 130: min_gain, max_gain = 7, 12
        elif 150 <= wattage <= 170: min_gain, max_gain = 8, 14
        elif wattage == 200: min_gain, max_gain = 9, 16

    elif soc_range == "20-40":
        if wattage == 45: min_gain, max_gain = 2, 4
        elif wattage == 65: min_gain, max_gain = 3, 6
        elif wattage == 90: min_gain, max_gain = 5, 8
        elif wattage == 130: min_gain, max_gain = 6, 11
        elif 150 <= wattage <= 170: min_gain, max_gain = 7, 13
        elif wattage == 200: min_gain, max_gain = 8, 15

    elif soc_range == "40-70":
        if wattage == 45: min_gain, max_gain = 2, 3
        elif wattage == 65: min_gain, max_gain = 4, 5
        elif wattage == 90: min_gain, max_gain = 5, 8
        elif wattage == 130: min_gain, max_gain = 6, 9
        elif 150 <= wattage <= 170: min_gain, max_gain = 7, 11
        elif wattage == 200: min_gain, max_gain = 8, 13

    elif soc_range == "70-80":
        if wattage == 45: min_gain, max_gain = 1, 2
        elif wattage == 65: min_gain, max_gain = 2, 3
        elif wattage == 90: min_gain, max_gain = 3, 5
        elif wattage == 130: min_gain, max_gain = 4, 6
        elif 150 <= wattage <= 170: min_gain, max_gain = 5, 7
        elif wattage == 200: min_gain, max_gain = 6, 8

    elif soc_range == "80-95":
        if wattage == 45: min_gain, max_gain = 1, 1
        elif wattage == 65: min_gain, max_gain = 1, 2
        elif wattage == 90: min_gain, max_gain = 2, 3
        elif wattage == 130: min_gain, max_gain = 2, 4
        elif 150 <= wattage <= 170: min_gain, max_gain = 3, 4
        elif wattage == 200: min_gain, max_gain = 3, 5

    elif soc_range == "95-100":
        if wattage == 45: min_gain, max_gain = 0, 0
        elif wattage == 65: min_gain, max_gain = 0, 1
        elif wattage == 90: min_gain, max_gain = 1, 1
        elif wattage == 130: min_gain, max_gain = 1, 1
        elif 150 <= wattage <= 170: min_gain, max_gain = 1, 2
        elif wattage == 200: min_gain, max_gain = 1, 2

    return "Pass" if gain >= min_gain else "Fail"



@frappe.whitelist()
def get_last_quality_status_from_bios(njqca_name):
    # Validate NJQCA
    if not njqca_name or not frappe.db.exists("NJQCA", njqca_name):
        return "NOT FOUND"

    njqca = frappe.get_doc("NJQCA", njqca_name)

    # Read BIOS serial number
    bios_serialno = njqca.bios_serialno
    if not bios_serialno:
        return "NOT FOUND"

    # Fetch Serial No using BIOS serial
    serial_no = frappe.db.get_value(
        "Serial No",
        {"bios_serial_no": bios_serialno},
        "name"
    )
    if not serial_no:
        return "NOT FOUND"

    # Fetch inspection type from NJ Settings
    inspection_type = frappe.db.get_value(
        "NJ Settings",
        {"parameter": "last_qc_inspection_type"},
        "value"
    )
    if not inspection_type:
        return "NOT FOUND"

    # Fetch latest Quality Inspection
    qi = frappe.db.sql("""
        SELECT status
        FROM `tabNJ Quality Inspection`
        WHERE barcode = %s AND inspection_type = %s
        ORDER BY modified DESC
        LIMIT 1
    """, (serial_no, inspection_type), as_dict=True)

    if not qi:
        return "NOT FOUND"

    # Status mapping
    if qi[0].status == "Accepted":
        return "PASS"
    elif qi[0].status == "Rejected":
        return "FAIL"
    else:
        return "NOT FOUND"


import csv
import io
import json
import os
import re
import statistics
from typing import Any, Dict, Optional, List, Tuple

import frappe
from frappe.utils import get_url
from frappe.model.document import Document


# ==========================================================
# CONFIG
# ==========================================================

HEAVYLOAD_REF_ITEM_GROUP = "LAPTOP STORAGE"
HEAVYLOAD_REF_PARAM = "heavy_load_File_Updated_name"

YCRUNCHER_REF_PARAM = "y_cruncher_File_Updated_name"
GAMING_FPS_REF_PARAM = "gaming_fps_file_uploaded"
PERFORMANCE_REF_PARAM = "performance_File_Updated_name"

# Where to write derived parameters (JS will upsert to these item_groups)
YCRUNCHER_TARGET_ITEM_GROUP = "Laptop RAM"
TEMP_TARGET_ITEM_GROUP = "Laptop Processors"
GAMING_TARGET_ITEM_GROUP = "Laptop RAM"
PERFORMANCE_TARGET_ITEM_GROUP = "Laptop RAM"
BATTERY_ITEM_GROUP = "BATTERY"
BATTERY_BDT_PARAM = "backup_duration_cycle_1"
BATTERY_BDT_INSPECTION_TYPE = "L2 Battery BDT"

TEMP_UNIT = "°C"
TEMP_SENSORS = [
    "CPU Core #1",
    "CPU Core #2",
    "CPU Core #3",
    "CPU Core #4",
    "CPU Package",
]

HEAVYLOAD_METRIC_UNITS = {
    "cpu_load_avg_pct": "%",
    "cpu_load_last_window_avg_pct": "%",
    "cpu_samples_ge_threshold_pct": "%",
    "cpu_core_peak_temp_last_20min_c": "°C",
    "clock_under_load_avg_ghz": "GHz",
    "clock_drop_detected": "",
    "clock_drop_pct": "%",
    "cpu_package_power_max_w": "W",
    "cpu_package_power_min_post5min_w": "W",
}

# YCRUNCHER_KEEP_KEYS_ORDERED = [
#     "Spot Check",
#     "Timer Sanity Check",
#     "ECC Recovered Errors",
#     "Decimal Digits",
#     "Hexadecimal Digits",
#     "Algorithm",
#     "Computation Mode",
#     "Working Memory",
#     "Total Computation Time",
#     "Start-to-End Wall Time",
#     "CPU Utilization",
#     "Multi-core Efficiency",
#     "Threading Mode",
#     "Logical Cores",
#     "Physical Cores",
#     "Base Frequency",
#     "Est. Frequency",
#     "Start Date",
#     "End Date",
# ]

YCRUNCHER_KEEP_KEYS_ORDERED = [
    "Spot Check",
    "Timer Sanity Check",
    "ECC Recovered Errors",
]

GAMING_METRIC_UNITS = {
    "avg_fps": "FPS",
    "fps_1pct_low": "FPS",
    "fps_01pct_low": "FPS",
    "frame_drop_pct": "%",
    "gpu_load_pct": "%",
    "frame_time_avg_ms": "ms",
    "frame_time_stdev_ms": "ms",
}

PERFORMANCE_METRIC_UNITS = {
    "CPU Cores": "",
    "CPU Max Frequency": "MHz",
    "Blender total time taken": "s",
    "PPT loading time (launch + open file)": "s",
    "VS Code open": "s",
    "VS Code close": "s",
    "Django server start": "s",
    "Browser close": "s",
    "Static server stop": "s",
    "URL load time": "s",
    "tab_switching_time": "s",
}


# ==========================================================
# Helpers
# ==========================================================

def _get_doc_serial_no(doc: Document) -> str:
    """Best-effort get serial no from NJQCA/NJ Quality Inspection doc."""
    # try common fieldnames
    for fn in ("serial_no", "serial", "serial_number", "serialno", "serial_no_id", "serial_no_name"):
        try:
            v = getattr(doc, fn, None) if hasattr(doc, fn) else (doc.get(fn) if isinstance(doc, dict) else None)
            if v:
                return str(v).strip()
        except Exception:
            continue

    # fallback: sometimes serial is in meta.serial inside json, but here doc is a Frappe doc, so ignore
    return ""


def _has_col(doctype: str, fieldname: str) -> bool:
    try:
        return bool(frappe.db.has_column(f"tab{doctype}", fieldname))
    except Exception:
        # fallback to meta check
        try:
            return frappe.get_meta(doctype).has_field(fieldname)
        except Exception:
            return False

def _key(s) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()

def _extract_float(val):
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None

def _display_sensor_name(sensor: str) -> str:
    return sensor.replace("#", "").replace("  ", " ").strip()

def _norm_header(h: str) -> str:
    h = (h or "")
    h = h.replace("|", " ")
    h = h.replace("#", " ")
    h = re.sub(r"\s+", " ", h).strip().lower()
    return h

def _get_child_meta(doc: Document):
    child_dt = doc.meta.get_field("njqca_result_parameters").options
    return frappe.get_meta(child_dt)

def _detect_value_and_unit_fields(doc: Document):
    meta = _get_child_meta(doc)

    value_field = None
    for f in ("value", "parameter_value", "param_value", "parameter_val"):
        if meta.has_field(f):
            value_field = f
            break

    unit_field = None
    for f in ("units", "unit"):
        if meta.has_field(f):
            unit_field = f
            break

    return value_field, unit_field

def _get_row_value(row, value_field: str):
    if not value_field:
        return None
    return row.get(value_field)

def _get_bios_serialno_from_serial(serial_no: str) -> str:
    """Fetch BIOS serial number from Serial No doctype (best-effort fieldnames)."""
    serial_no = (serial_no or "").strip()
    if not serial_no:
        return ""

    for fn in ("bios_serial_no", "bios_serialno", "bios_serial", "bios_serial_number"):
        try:
            v = frappe.db.get_value("Serial No", serial_no, fn)
            if v:
                return str(v).strip()
        except Exception:
            continue

    return ""


def _get_backup_duration_cycle_1_from_bdt(bios_serialno: str):
    """
    Fetch latest approved L2 Battery BDT -> backup_duration_cycle_1
    using BIOS serial match.
    """
    bios_serialno = (bios_serialno or "").strip()
    if not bios_serialno:
        return None

    bios_field = None
    if _has_col("NJQCA", "bios_serialno"):
        bios_field = "bios_serialno"
    elif _has_col("NJQCA", "bios_serial_no"):
        bios_field = "bios_serial_no"

    if not bios_field:
        return None

    q = f"""
        SELECT backup_duration_cycle_1
        FROM `tabNJQCA`
        WHERE docstatus = 1
          AND inspection_type = %(it)s
          AND {bios_field} = %(bios)s
        ORDER BY creation DESC
        LIMIT 1
    """
    row = frappe.db.sql(q, {"bios": bios_serialno, "it": BATTERY_BDT_INSPECTION_TYPE}, as_dict=True)
    if not row:
        return None

    v = row[0].get("backup_duration_cycle_1")
    if v is None or str(v).strip() == "":
        return None
    return v  # keep original type (float/int/str)

def _collect_battery_bdt_change(doc: Document, add_change) -> dict:
    """
    NO mutation. Collects last L2 Battery BDT backup_duration_cycle_1 into:
    item_group=BATTERY, parameter=backup_duration_cycle_1
    """
    try:
        serial_no = _get_doc_serial_no(doc)
        if not serial_no:
            return {"status": "skip", "reason": "serial_no not found on document"}

        bios_sn = _get_bios_serialno_from_serial(serial_no)
        if not bios_sn:
            return {"status": "skip", "reason": f"BIOS serial not found for Serial No {serial_no}"}

        bdt_val = _get_backup_duration_cycle_1_from_bdt(bios_sn)
        if bdt_val is None or str(bdt_val).strip() == "":
            return {"status": "skip", "reason": f"no backup_duration_cycle_1 found for BIOS {bios_sn}"}

        # Optional: numeric normalize if you want
        # num = _extract_float(bdt_val)
        # value_to_write = round(num, 2) if num is not None else str(bdt_val).strip()

        value_to_write = str(bdt_val).strip()

        add_change(
            BATTERY_ITEM_GROUP,
            BATTERY_BDT_PARAM,
            value_to_write,
            "",  # unit (set "min" or "sec" if your field is standardized)
        )

        return {"status": "ok", "serial_no": serial_no, "bios_serial": bios_sn, "value": value_to_write}

    except Exception as e:
        return {"status": "error", "error": str(e)}

# ==========================================================
# File read
# ==========================================================

def _read_file_bytes_from_filedoctype(file_doc) -> bytes:
    file_url = (getattr(file_doc, "file_url", None) or "").strip()
    if not file_url:
        frappe.throw("File URL is missing for file.")

    local_path = None
    filename = file_url.split("/")[-1].strip()

    if file_url.startswith("/private/files/"):
        local_path = frappe.get_site_path("private", "files", filename)
    elif file_url.startswith("/files/"):
        local_path = frappe.get_site_path("public", "files", filename)

    if local_path and os.path.exists(local_path):
        with open(local_path, "rb") as f:
            return f.read()

    full_url = file_url if file_url.startswith("http") else (get_url().rstrip("/") + file_url)
    sess = frappe.utils.get_request_session()
    resp = sess.get(full_url, timeout=30)
    resp.raise_for_status()
    return resp.content


# ==========================================================
# Change Collector (NO doc mutation)
# ==========================================================

def _collect_upserts():
    """
    Collect upsert changes: last write wins per (item_group, parameter).
    """
    changes_map: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def add_change(
        item_group: str,
        parameter: str,
        value: Any,
        unit: str,
        score=None,
        part_config_id=0
    ):
        k = (_key(item_group), _key(parameter))

        change = {
            "item_group": item_group,
            "parameter": parameter,
            "value": value,
            "units": unit,
        }

        if score not in (None, ""):
            change["score"] = score

        if part_config_id not in (None, ""):
            change["part_config_id"] = part_config_id

        changes_map[k] = change

    def flush_changes() -> List[Dict[str, Any]]:
        return list(changes_map.values())

    return add_change, flush_changes

# ==========================================================
# CSV parsing: Avg + Max Temperature
# ==========================================================

def _parse_temp_stats(csv_bytes: bytes) -> dict:
    text = csv_bytes.decode("utf-8-sig", errors="ignore")
    if not text.strip():
        return {}

    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return {}

    header = rows[0]
    header_norm = [_norm_header(h) for h in header]

    col_idx = {}
    for sensor in TEMP_SENSORS:
        s_norm = _norm_header(sensor)
        for i, h in enumerate(header_norm):
            if ("temperature" in h) and (s_norm in h):
                col_idx[sensor] = i
                break

    if not col_idx:
        return {}

    stats = {}
    for sensor, idx in col_idx.items():
        vals = []
        for r in rows[1:]:
            if idx < len(r):
                f = _extract_float(r[idx])
                if f is not None:
                    vals.append(f)

        if vals:
            stats[sensor] = {"avg": (sum(vals) / len(vals)), "max": max(vals)}

    return stats


# ==========================================================
# HeavyLoad: 9-metric summary from CSV
# ==========================================================

def _parse_heavyload_summary_from_csv_bytes(
    csv_bytes: bytes,
    last_minutes_for_temp: int = 20,
    load_threshold: float = 95.0,
    clock_drop_pct: float = 15.0,
    min_after_minutes: int = 5,
) -> dict:
    text = csv_bytes.decode("utf-8-sig", errors="ignore")
    if not text.strip():
        return {}

    def _to_float(x):
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if not s:
            return None
        s = s.replace(",", ".")
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if not m:
            return None
        try:
            return float(m.group(0))
        except Exception:
            return None

    def _find_col(fieldnames, must_have_words):
        for c in (fieldnames or []):
            cl = c.lower()
            ok = True
            for w in must_have_words:
                if w.lower() not in cl:
                    ok = False
                    break
            if ok:
                return c
        return None

    def _t_to_sec(t):
        parts = str(t).strip().split(":")
        if len(parts) != 3:
            return None
        h, m, s = parts
        try:
            return int(h) * 3600 + int(m) * 60 + int(s)
        except Exception:
            return None

    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return {}

    fieldnames = reader.fieldnames or []

    time_col = "Time" if "Time" in fieldnames else (_find_col(fieldnames, ["time"]) or "")
    if not time_col:
        return {"heavy_load_error": f"Missing Time column. Found: {fieldnames[:25]}"}

    cpu_col = _find_col(fieldnames, ["cpu", "%"]) or _find_col(fieldnames, ["cpu", "usage"]) or _find_col(fieldnames, ["cpu"])
    if not cpu_col:
        return {"heavy_load_error": f"CPU column not found. Found: {fieldnames[:25]}"}

    pwr_col = (
        _find_col(fieldnames, ["power", "cpu", "package"])
        or _find_col(fieldnames, ["power", "package"])
        or _find_col(fieldnames, ["cpu", "package", "power"])
    )
    if not pwr_col:
        return {"heavy_load_error": f"CPU package power column not found. Found: {fieldnames[:25]}"}

    temp_cols = [c for c in fieldnames if ("temperature" in c.lower() and "cpu core" in c.lower())]
    if not temp_cols:
        return {"heavy_load_error": "No temperature columns like 'Temperature | CPU Core #x' found."}

    clock_cols = [c for c in fieldnames if ("clock" in c.lower() and "cpu core" in c.lower())]
    if not clock_cols:
        return {"heavy_load_error": "No clock columns like 'Clock | CPU Core #x' found."}

    t0 = _t_to_sec(rows[0].get(time_col))
    if t0 is None:
        return {"heavy_load_error": f"Time parse failed. First={rows[0].get(time_col)}"}

    for rr in rows:
        ts = _t_to_sec(rr.get(time_col))
        rr["_elapsed_s"] = (ts - t0) if ts is not None else None

    cpu_all = [_to_float(rr.get(cpu_col)) for rr in rows]
    cpu_all_num = [x for x in cpu_all if x is not None]
    if not cpu_all_num:
        return {"heavy_load_error": "CPU column has no numeric values."}

    max_elapsed = max([rr["_elapsed_s"] for rr in rows if rr["_elapsed_s"] is not None] or [0])
    last_start = max_elapsed - last_minutes_for_temp * 60
    last_rows = [rr for rr in rows if (rr["_elapsed_s"] is not None and rr["_elapsed_s"] >= last_start)]

    load_rows = [rr for rr in rows if (_to_float(rr.get(cpu_col)) is not None and _to_float(rr.get(cpu_col)) >= load_threshold)]

    after_rows = [rr for rr in rows if (rr["_elapsed_s"] is not None and rr["_elapsed_s"] >= min_after_minutes * 60)]
    after_load_rows = [rr for rr in after_rows if (_to_float(rr.get(cpu_col)) is not None and _to_float(rr.get(cpu_col)) >= load_threshold)]
 
    cpu_avg = statistics.mean(cpu_all_num)

    cpu_last_avg = None
    if last_rows:
        vals = []
        for rr in last_rows:
            v = _to_float(rr.get(cpu_col))
            if v is not None:
                vals.append(v)
        cpu_last_avg = statistics.mean(vals) if vals else None

    cpu_pct_ge = (sum(1 for x in cpu_all_num if x >= load_threshold) / len(cpu_all_num)) * 100.0

    peak_temp = None
    if last_rows:
        vals = []
        for rr in last_rows:
            for c in temp_cols:
                v = _to_float(rr.get(c))
                if v is not None:
                    vals.append(v)
        peak_temp = max(vals) if vals else None

    use_clock_rows = load_rows if load_rows else rows
    all_clock_vals = []
    for rr in use_clock_rows:
        for c in clock_cols:
            v = _to_float(rr.get(c))
            if v is not None:
                all_clock_vals.append(v)

    clock_under = None
    if all_clock_vals:
        med = statistics.median(all_clock_vals)
        if med > 100:  # MHz
            clock_under = statistics.mean(all_clock_vals) / 1000.0
        else:  # already GHz
            clock_under = statistics.mean(all_clock_vals)

    def _core_clock_list(rrs):
        arr = []
        for rr in rrs:
            for c in clock_cols:
                v = _to_float(rr.get(c))
                if v is not None:
                    arr.append(v)
        return arr

    first2 = [rr for rr in load_rows if (rr.get("_elapsed_s") is not None and rr["_elapsed_s"] <= 120)] if load_rows else []
    base_list = _core_clock_list(first2) if len(first2) >= 3 else _core_clock_list(load_rows or rows)
    later = [rr for rr in load_rows if (rr.get("_elapsed_s") is not None and rr["_elapsed_s"] >= min_after_minutes * 60)] if load_rows else []
    later_list = _core_clock_list(later) if later else _core_clock_list(rows)

    drop_detected = None
    drop_pct_val = None
    if base_list and later_list:
        base_med = statistics.median(base_list)
        later_min = min(later_list)
        if base_med > 100:
            base = base_med / 1000.0
            later_min = later_min / 1000.0
        else:
            base = base_med

        if base and base > 0:
            drop_pct_val = ((base - later_min) / base) * 100.0
            drop_detected = drop_pct_val >= clock_drop_pct

    pwr_all = [_to_float(rr.get(pwr_col)) for rr in rows]
    pwr_all = [x for x in pwr_all if x is not None]
    pwr_max = max(pwr_all) if pwr_all else None

    pwr_min_post = None
    if after_load_rows:
        p = [_to_float(rr.get(pwr_col)) for rr in after_load_rows]
        p = [x for x in p if x is not None]
        pwr_min_post = min(p) if p else None

    return {
        "cpu_load_avg_pct": round(cpu_avg, 2),
        "cpu_load_last_window_avg_pct": round(cpu_last_avg, 2) if cpu_last_avg is not None else None,
        "cpu_samples_ge_threshold_pct": round(cpu_pct_ge, 2),
        "cpu_core_peak_temp_last_20min_c": round(peak_temp, 2) if peak_temp is not None else None,
        "clock_under_load_avg_ghz": round(clock_under, 3) if clock_under is not None else None,
        "clock_drop_detected": bool(drop_detected) if drop_detected is not None else None,
        "clock_drop_pct": round(drop_pct_val, 2) if drop_pct_val is not None else None,
        "cpu_package_power_max_w": round(pwr_max, 2) if pwr_max is not None else None,
        "cpu_package_power_min_post5min_w": round(pwr_min_post, 2) if pwr_min_post is not None else None,
    }


# ==========================================================
# Y-cruncher parsing
# ==========================================================

def _parse_ycruncher_content_to_kv(text: str) -> Dict[str, str]:
    text = (text or "").replace("\ufeff", "").strip()
    if not text:
        return {}

    wanted = set(YCRUNCHER_KEEP_KEYS_ORDERED)
    found: Dict[str, str] = {}

    kv_rx = re.compile(r"^([A-Za-z][A-Za-z0-9 ()/_\-\.\#]{0,80})\s*:\s*(.+)$")

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower().startswith("benchmark validation file"):
            continue

        m = kv_rx.match(line)
        if not m:
            continue

        k = (m.group(1) or "").strip()
        v = (m.group(2) or "").strip()
        if k in wanted and v and k not in found:
            found[k] = v

    ordered: Dict[str, str] = {}
    for k in YCRUNCHER_KEEP_KEYS_ORDERED:
        if k in found:
            ordered[k] = found[k]
    return ordered

def _evaluate_ycruncher_status(kv: Dict[str, str]) -> tuple[str, str]:
    spot_check = (kv.get("Spot Check") or "").strip()
    timer_check = (kv.get("Timer Sanity Check") or "").strip()
    ecc_errors = (kv.get("ECC Recovered Errors") or "").strip()

    if not kv:
        return "FAIL", "No y-cruncher values parsed from report"

    if not spot_check.startswith("Good through"):
        return "FAIL", f"Spot Check failed: {spot_check or 'missing'}"

    if timer_check != "Passed":
        return "FAIL", f"Timer Sanity Check failed: {timer_check or 'missing'}"

    if ecc_errors != "0":
        return "FAIL", f"ECC Recovered Errors is {ecc_errors or 'missing'}"

    return "PASS", "Spot Check good, Timer Sanity Check passed, ECC errors 0"

# ==========================================================
# Gaming FPS parsing (correct, using TimeInSeconds etc.)
# ==========================================================

def _parse_gaming_fps_metrics_from_csv_bytes(csv_bytes: bytes) -> dict:
    import csv, io, statistics
    from typing import Optional

    def _to_float(val) -> Optional[float]:
        try:
            f = float(val)
            return f if f == f else None
        except (TypeError, ValueError):
            return None

    def _percentile_inc(sorted_data: list, p: float) -> float:
        n = len(sorted_data)
        idx = p * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        return sorted_data[lo] + (idx - lo) * (sorted_data[hi] - sorted_data[lo])

    def _get_col(norm: dict, name: str) -> Optional[str]:
        key = name.lower()
        if key in norm:
            return norm[key]
        for k, orig in norm.items():
            if key in k:
                return orig
        return None

    def r2(x):
        return None if x is None else round(float(x), 2)

    text = csv_bytes.decode("utf-8-sig", errors="ignore")
    if not text.strip():
        return {"gaming_error": "FPS log is empty"}

    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return {"gaming_error": "No rows in FPS log"}

    fieldnames = reader.fieldnames or []
    norm = {f.lower().strip(): f for f in fieldnames if f}

    col_dropped = _get_col(norm, "Dropped")
    col_time = _get_col(norm, "TimeInSeconds")
    col_mbp = _get_col(norm, "msBetweenPresents")
    col_bdc = _get_col(norm, "msBetweenDisplayChange")
    col_gpu = _get_col(norm, "msGPUActive")

    missing = [
        name for name, col in [
            ("Dropped", col_dropped),
            ("TimeInSeconds", col_time),
            ("msBetweenPresents", col_mbp),
            ("msBetweenDisplayChange", col_bdc),
        ] if not col
    ]
    if missing:
        return {"gaming_error": f"Missing required columns: {missing}. Found: {fieldnames[:30]}"}

    total_frames = len(rows)
    displayed_rows = []
    dropped_count = 0

    for r in rows:
        try:
            is_dropped = int(float(r[col_dropped])) != 0
        except (TypeError, ValueError):
            is_dropped = False

        if is_dropped:
            dropped_count += 1
        else:
            displayed_rows.append(r)

    if not displayed_rows:
        return {"gaming_error": "No displayed frames found (all rows have Dropped=1)"}

    times = [_to_float(r[col_time]) for r in displayed_rows]
    times = [t for t in times if t is not None]
    if len(times) < 2:
        return {"gaming_error": "Not enough valid TimeInSeconds values to compute avg_fps"}

    elapsed = times[-1] - times[0]
    if elapsed <= 0:
        return {"gaming_error": f"Invalid elapsed time: {elapsed}"}

    avg_fps = (len(times) - 1) / elapsed

    bdc_vals = [
        _to_float(r[col_bdc])
        for r in displayed_rows
        if _to_float(r[col_bdc]) is not None and _to_float(r[col_bdc]) > 0
    ]

    fps_1pct_low = None
    fps_01pct_low = None
    frame_time_avg_ms = None
    frame_time_stdev_ms = None

    if bdc_vals:
        fps_from_bdc = sorted(1000.0 / b for b in bdc_vals)
        fps_1pct_low = _percentile_inc(fps_from_bdc, 0.01)
        fps_01pct_low = _percentile_inc(fps_from_bdc, 0.001)
        frame_time_avg_ms = statistics.mean(bdc_vals)
        frame_time_stdev_ms = statistics.pstdev(bdc_vals) if len(bdc_vals) >= 2 else 0.0

    mbp_disp = [_to_float(r[col_mbp]) for r in displayed_rows]
    gpu_disp = [_to_float(r[col_gpu]) for r in displayed_rows] if col_gpu else []

    paired = [(b, g) for b, g in zip(mbp_disp, gpu_disp) if b is not None and b > 0 and g is not None and g > 0]
    gpu_load_pct = None
    if paired:
        mean_gpu = statistics.mean(p[1] for p in paired)
        mean_mbp = statistics.mean(p[0] for p in paired)
        gpu_load_pct = (mean_gpu / mean_mbp) * 100.0

    frame_drop_pct = (dropped_count / total_frames) * 100.0

    return {
        "avg_fps": r2(avg_fps),
        "fps_1pct_low": r2(fps_1pct_low),
        "fps_01pct_low": r2(fps_01pct_low),
        "frame_drop_pct": r2(frame_drop_pct),
        "gpu_load_pct": r2(gpu_load_pct),
        "frame_time_avg_ms": r2(frame_time_avg_ms),
        "frame_time_stdev_ms": r2(frame_time_stdev_ms),
    }


# ==========================================================
# Performance TXT parsing (FIXED: full parameter names)
# ==========================================================

def _parse_performance_txt_metrics(text: str) -> dict:
    text = (text or "").replace("\ufeff", "")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    metrics: Dict[str, Tuple[Any, str]] = {}

    current_project = None
    current_ppt_file = None

    rx_running = re.compile(r"^---\s+Running\s+([A-Z]+)\s+project:\s*(.+?)\s*---$", re.I)
    rx_ppt_opened = re.compile(r"^PPT opened:\s*(.+)$", re.I)
    rx_ppt_load = re.compile(r"^PPT loading time \(launch \+ open file\):\s*([0-9.]+)\s*seconds?$", re.I)

    rx_cpu_cores = re.compile(r"CPU Cores:\s*([0-9]+)", re.I)
    rx_cpu_maxfreq = re.compile(r"CPU Max Frequency:\s*([0-9.]+)\s*MHz", re.I)

    rx_blender_total = re.compile(r"^Blender total time taken\s*,\s*([0-9.]+)\s*s$", re.I)

    rx_vscode_open = re.compile(r"^vs code open\s*,\s*([^,]+)\s*,.*Time taken\s*=\s*([0-9.]+)\s*s$", re.I)
    rx_vscode_close = re.compile(r"^vs code close\s*,.*Time taken\s*=\s*([0-9.]+)\s*s$", re.I)

    rx_django_start = re.compile(r"^Django server start\s*\((\d+)\)\s*,.*Time taken\s*=\s*([0-9.]+)\s*s$", re.I)
    rx_browser_close = re.compile(r"^Browser close\s*,.*Time taken\s*=\s*([0-9.]+)\s*s$", re.I)

    rx_static_stop = re.compile(r"^Static server stop\s*,.*Time taken\s*=\s*([0-9.]+)\s*s$", re.I)
    rx_url = re.compile(r"^url\s*,\s*(https?://[^,]+)\s*,\s*([0-9.]+)\s*$", re.I)
    rx_tab_switching_1 = re.compile(
    r"^tab_switching\s*,\s*Total time taken for switching tabs\s*,\s*([0-9.]+)\s*$",
        re.I
    )

    rx_tab_switching_2 = re.compile(
        r"^tab_switching_time\s*,\s*([0-9.]+)\s*(?:seconds?|s)?$",
        re.I
    )

    def _set_metric(param: str, value: Any, unit: str):
        metrics[param] = (value, unit)

    for ln in lines:
        m = rx_running.match(ln)
        if m:
            current_project = (m.group(2) or "").strip()
            continue

        m = rx_cpu_cores.search(ln)
        if m:
            _set_metric("CPU Cores", int(m.group(1)), PERFORMANCE_METRIC_UNITS["CPU Cores"])
            continue

        m = rx_cpu_maxfreq.search(ln)
        if m:
            _set_metric("CPU Max Frequency", float(m.group(1)), PERFORMANCE_METRIC_UNITS["CPU Max Frequency"])
            continue

        m = rx_blender_total.match(ln)
        if m:
            _set_metric("Blender total time taken", float(m.group(1)), PERFORMANCE_METRIC_UNITS["Blender total time taken"])
            continue

        m = rx_ppt_opened.match(ln)
        if m:
            path = (m.group(1) or "").strip()
            current_ppt_file = os.path.basename(path) if path else None
            continue

        m = rx_ppt_load.match(ln)
        if m:
            sec = float(m.group(1))
            param = f"({current_ppt_file})" if current_ppt_file else "PPT loading time (launch + open file)"
            _set_metric(param, sec, PERFORMANCE_METRIC_UNITS["PPT loading time (launch + open file)"])
            continue

        m = rx_vscode_open.match(ln)
        if m:
            proj = (m.group(1) or "").strip()
            sec = float(m.group(2))
            _set_metric(f"({proj})", sec, PERFORMANCE_METRIC_UNITS["VS Code open"])
            continue

        m = rx_django_start.match(ln)
        if m:
            port = (m.group(1) or "").strip()
            sec = float(m.group(2))
            proj = current_project or "Unknown"
            _set_metric(f"({proj}) [{port}]", sec, PERFORMANCE_METRIC_UNITS["Django server start"])
            continue

        m = rx_browser_close.match(ln)
        if m:
            sec = float(m.group(1))
            proj = current_project or "Unknown"
            _set_metric(f"({proj})", sec, PERFORMANCE_METRIC_UNITS["Browser close"])
            continue

        m = rx_static_stop.match(ln)
        if m:
            sec = float(m.group(1))
            proj = current_project or "Unknown"
            _set_metric(f"({proj})", sec, PERFORMANCE_METRIC_UNITS["Static server stop"])
            continue

        m = rx_vscode_close.match(ln)
        if m:
            sec = float(m.group(1))
            proj = current_project or "Unknown"
            _set_metric(f"({proj})", sec, PERFORMANCE_METRIC_UNITS["VS Code close"])
            continue

        m = rx_url.match(ln)
        if m:
            url = (m.group(1) or "").strip()
            sec = float(m.group(2))
            _set_metric(f"({url})", sec, PERFORMANCE_METRIC_UNITS["URL load time"])
            continue
        m = rx_tab_switching_1.match(ln) or rx_tab_switching_2.match(ln)
        if m:
            sec = float(m.group(1))
            _set_metric(
                "tab_switching_time",
                sec,
                PERFORMANCE_METRIC_UNITS["tab_switching_time"]
            )
            continue

    out: Dict[str, Any] = {}
    for k, (v, u) in metrics.items():
        if isinstance(v, float):
            out[k] = (round(v, 2), u)
        else:
            out[k] = (v, u)
    return out


# ==========================================================
# Connectivity from njqca_item_component (NO mutation)
# ==========================================================

def _get_component_meta(doc: Document):
    child_dt = doc.meta.get_field("njqca_item_component").options
    return frappe.get_meta(child_dt)

def _detect_component_variant3_field(doc: Document) -> str:
    meta = _get_component_meta(doc)
    for f in ("variant_3", "variant3", "variant_three"):
        if meta.has_field(f):
            return f
    return "variant_3"

def _collect_connectivity_changes(doc: Document, add_change) -> dict:
    variant3_field = _detect_component_variant3_field(doc)

    rows = list(doc.get("njqca_item_component") or [])
    if not rows:
        return {"status": "skip", "reason": "njqca_item_component empty"}

    wifi_val = None
    bt_val = None
    lan_val = None

    for r in rows:
        ig = (r.get("item_group") or "").strip()
        v3 = r.get(variant3_field)
        v3 = str(v3).strip() if v3 is not None else None
        if not v3:
            continue

        if _key(ig) == _key("WIFI CARD") and wifi_val is None:
            wifi_val = v3
            continue

        if _key(ig) == _key("BLUETOOTH") and bt_val is None:
            bt_val = v3
            continue

        if _key(ig) == _key("LAN PORT") and lan_val is None:
            lan_val = v3
            continue

    written = []
    if wifi_val is not None:
        add_change("WIFI CARD", "wifi_speed", wifi_val, "")
        written.append("WIFI CARD.wifi_speed")

    if bt_val is not None:
        add_change("BLUETOOTH", "bluetooth_speed", bt_val, "")
        written.append("BLUETOOTH.bluetooth_speed")

    if lan_val is not None:
        add_change("LAN PORT", "lan_speed", lan_val, "")
        written.append("LAN PORT.lan_speed")

    if not written:
        return {"status": "skip", "reason": "no connectivity speeds found in njqca_item_component"}

    return {"status": "ok", "written": written}

def _parse_ram_metrics_from_csv_bytes(csv_bytes: bytes) -> dict:
    text = csv_bytes.decode("utf-8-sig", errors="ignore")
    if not text.strip():
        return {}

    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        return {}

    raw_header = rows[0]
    header_norm = [
        h.strip().replace("\ufeff", "").replace("|", " ").replace("#", " ").lower().strip()
        for h in raw_header
    ]

    def find_col(*keyword_sets):
        for keywords in keyword_sets:
            for i, h in enumerate(header_norm):
                if all(k.lower() in h for k in keywords):
                    return i
        return None

    ram_col       = find_col(["ram free mb"], ["ram free"], ["free mb"])
    cpu_col       = find_col(["cpu %"], ["cpu%"], ["cpu"])
    disk_write_col= find_col(["disk write mbs"], ["disk write mb/s"], ["disk write"], ["write mbs"], ["write mb"])
    time_col      = find_col(["time"])

    if ram_col is None or cpu_col is None:
        return {
            "Baseline Free RAM %":        "ERROR: RAM/CPU column not found",
            "Minimum Free RAM % (Stress)":"ERROR: RAM/CPU column not found",
            "RAM Stability (Std Dev)":    "ERROR: RAM/CPU column not found",
            "Paging Events":              "ERROR: RAM/CPU column not found",
            "Recovery Time":              "ERROR: RAM/CPU column not found",
        }

    def _to_float(val):
        try:
            return float(str(val).strip().replace(",", "."))
        except (ValueError, TypeError):
            return None

    def _to_sec(t):
        if not t:
            return None
        parts = str(t).strip().split(":")
        if len(parts) == 3:
            try:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            except Exception:
                return None
        return None

    data = []
    for r in rows[1:]:
        ram  = _to_float(r[ram_col])  if ram_col  < len(r) else None
        cpu  = _to_float(r[cpu_col])  if cpu_col  < len(r) else None
        disk = _to_float(r[disk_write_col]) if disk_write_col and disk_write_col < len(r) else 0.0
        t    = r[time_col].strip()    if time_col and time_col < len(r) else None
        if ram is not None and cpu is not None:
            data.append({"ram": ram, "cpu": cpu, "disk": disk or 0.0, "time": t})

    if not data:
        return {
            "Baseline Free RAM %":        "ERROR: no valid data rows",
            "Minimum Free RAM % (Stress)":"ERROR: no valid data rows",
            "RAM Stability (Std Dev)":    "ERROR: no valid data rows",
            "Paging Events":              "ERROR: no valid data rows",
            "Recovery Time":              "ERROR: no valid data rows",
        }

    total_ram = max(d["ram"] for d in data)
    if total_ram <= 0:
        return {
            "Baseline Free RAM %":        "ERROR: total RAM is zero",
            "Minimum Free RAM % (Stress)":"ERROR: total RAM is zero",
            "RAM Stability (Std Dev)":    "ERROR: total RAM is zero",
            "Paging Events":              "ERROR: total RAM is zero",
            "Recovery Time":              "ERROR: total RAM is zero",
        }

    idle_rows   = [d["ram"] for d in data if d["cpu"] < 40]
    stress_rows = [d["ram"] for d in data if d["cpu"] >= 90]

    results = {}

    # Metric 3: Baseline Free RAM %
    if idle_rows:
        baseline_pct = (sum(idle_rows) / len(idle_rows)) / total_ram * 100
        results["Baseline Free RAM %"] = round(baseline_pct, 2)
    else:
        results["Baseline Free RAM %"] = None

    # Metric 4: Minimum Free RAM % (Stress)
    if stress_rows:
        min_free_pct = min(stress_rows) / total_ram * 100
        results["Minimum Free RAM % (Stress)"] = round(min_free_pct, 2)
    else:
        results["Minimum Free RAM % (Stress)"] = None

    # Metric 5: RAM Stability (Std Dev)
    if len(stress_rows) >= 2:
        mean_s = sum(stress_rows) / len(stress_rows)
        variance = sum((x - mean_s) ** 2 for x in stress_rows) / len(stress_rows)
        results["RAM Stability (Std Dev)"] = round(variance ** 0.5, 2)
    else:
        results["RAM Stability (Std Dev)"] = None

    # Metric 6: Paging Events
    results["Paging Events"] = sum(1 for d in data if d["ram"] < 500 and d["disk"] > 100)

    # Metric 7: Recovery Time
    # Metric 7: Recovery Time
    # If time column missing OR RAM never recovered, still write a value so the row appears
    if not stress_rows:
        results["Recovery Time"] = "NO STRESS DATA"
    elif time_col is None:
        results["Recovery Time"] = "NO TIME COLUMN"
    else:
        target_ram = 0.70 * total_ram
        stress_indexed = [(i, d) for i, d in enumerate(data) if d["cpu"] >= 90]

        if not stress_indexed:
            results["Recovery Time"] = "NO STRESS DATA"
        else:
            t1_idx, t1_row = min(stress_indexed, key=lambda x: x[1]["ram"])
            t1_sec = _to_sec(t1_row["time"])
            recovery_sec = None

            for j in range(t1_idx + 1, len(data)):
                if data[j]["ram"] >= target_ram:
                    t2_sec = _to_sec(data[j]["time"])
                    if t1_sec is not None and t2_sec is not None:
                        recovery_sec = round(t2_sec - t1_sec, 1)
                    break

            if recovery_sec is not None:
                results["Recovery Time"] = recovery_sec
            else:
                # RAM never recovered to 70% baseline after stress ended
                # Calculate total elapsed time from stress peak to end of recording
                # as a fallback worst-case value
                last_row = data[-1]
                t_last = _to_sec(last_row["time"])
                t1_sec_safe = _to_sec(t1_row["time"])
                if t_last is not None and t1_sec_safe is not None and t_last > t1_sec_safe:
                    results["Recovery Time"] = round(t_last - t1_sec_safe, 1)
                else:
                    results["Recovery Time"] = "NOT RECOVERED"

    return results

# ==========================================================
# MAIN: Apply enrichment (NO mutation) -> returns info + changes
# ==========================================================

def _apply_reliability_enrichment_no_mutation(doc: Document) -> dict:

    info = {
        "heavyload": {"status": "skip"},
        "y_cruncher": {"status": "skip"},
        "gaming_fps": {"status": "skip"},
        "performance": {"status": "skip"},
        "connectivity": {"status": "skip"},
        "battery_bdt": {"status": "skip"},
    }

    add_change, flush_changes = _collect_upserts()
    value_field, _unit_field = _detect_value_and_unit_fields(doc)

    # -------------------------
    # HEAVYLOAD (temps + summary)
    # -------------------------
    heavy_file_docname = None
    for row in doc.get("njqca_result_parameters") or []:
        ig = (row.get("item_group") or "").strip()
        p = (row.get("parameter") or "").strip()
        if _key(ig) == _key(HEAVYLOAD_REF_ITEM_GROUP) and _key(p) == _key(HEAVYLOAD_REF_PARAM):
            val = _get_row_value(row, value_field)
            if val:
                heavy_file_docname = str(val).strip()
            break

    if heavy_file_docname:
        try:
            file_doc = frappe.get_doc("File", heavy_file_docname)
            csv_bytes = _read_file_bytes_from_filedoctype(file_doc)

            # temps avg/max
            stats = _parse_temp_stats(csv_bytes)
            if stats:
                out = {}
                for sensor, s in stats.items():
                    disp = _display_sensor_name(sensor)
                    avg_param = f"Avg Temperature({disp})"
                    max_param = f"Max Temperature({disp})"

                    avg_val = round(float(s["avg"]), 2)
                    max_val = round(float(s["max"]), 2)

                    add_change(TEMP_TARGET_ITEM_GROUP, avg_param, avg_val, TEMP_UNIT)
                    add_change(TEMP_TARGET_ITEM_GROUP, max_param, max_val, TEMP_UNIT)
                    out[disp] = {"avg": avg_val, "max": max_val}

                temps_res = {"status": "ok", "temps": out}
            else:
                temps_res = {"status": "skip", "reason": "No temperature columns found in CSV"}

            # summary
            summary = _parse_heavyload_summary_from_csv_bytes(csv_bytes)
            if "heavy_load_error" in summary:
                info["heavyload"] = {"status": "error", "error": summary.get("heavy_load_error"), "temps": temps_res}
            else:
                for k, v in summary.items():
                    if v is None:
                        continue
                    unit = HEAVYLOAD_METRIC_UNITS.get(k, "")
                    add_change(TEMP_TARGET_ITEM_GROUP, k, v, unit)
                info["heavyload"] = {"status": "ok", "temps": temps_res, "summary": summary}
            # RAM metrics from heavyload CSV
            ram_metrics = _parse_ram_metrics_from_csv_bytes(csv_bytes)
            RAM_METRIC_UNITS = {
                "Baseline Free RAM %":         "%",
                "Minimum Free RAM % (Stress)": "%",
                "RAM Stability (Std Dev)":     "MB",
                "Paging Events":               "",
                "Recovery Time":               "sec",
            }
            for param_name, value in ram_metrics.items():
                if value is None:
                    continue
                unit = RAM_METRIC_UNITS.get(param_name, "")
                add_change("LAPTOP STORAGE", param_name, str(value), unit)
            info["heavyload"]["ram_metrics"] = ram_metrics
            # Disk metrics from heavyload CSV
            disk_metrics = _parse_disk_metrics_from_csv_bytes(csv_bytes)
            DISK_METRIC_UNITS = {
                "Disk Response Time":         "MB/s",
                "Sequential Read Stability":  "MB/s",
                "Sequential Write Stability": "MB/s",
                "Disk Active Time at Idle":   "MB/s",
                "CPU-Disk Bottleneck Ratio":  "%",
            }
            for param_name, value in disk_metrics.items():
                if value is None:
                    continue
                unit = DISK_METRIC_UNITS.get(param_name, "")
                add_change("LAPTOP STORAGE", param_name, str(value), unit)
            info["heavyload"]["disk_metrics"] = disk_metrics
        except Exception as e:
            info["heavyload"] = {"status": "error", "error": str(e)}

    # -------------------------
    # Y-CRUNCHER
    # -------------------------
    y_file_docname = None
    for row in doc.get("njqca_result_parameters") or []:
        p = (row.get("parameter") or "").strip()
        if _key(p) == _key(YCRUNCHER_REF_PARAM):
            val = _get_row_value(row, value_field)
            if val:
                y_file_docname = str(val).strip()
            break

    if y_file_docname:
        try:
            file_doc = frappe.get_doc("File", y_file_docname)
            raw_bytes = _read_file_bytes_from_filedoctype(file_doc)
            text = raw_bytes.decode("utf-8-sig", errors="ignore")

            kv = _parse_ycruncher_content_to_kv(text)
            if not kv:
                y_result = get_direct_status_result(
                    "y_cruncher_status",
                    "FAIL",
                    YCRUNCHER_TARGET_ITEM_GROUP
                )
                add_change(
                    y_result.get("item_group"),
                    y_result.get("parameter"),
                    y_result.get("value"),
                    "",
                    y_result.get("score"),
                    y_result.get("part_config_id")
                )
                add_change(YCRUNCHER_TARGET_ITEM_GROUP, "y_cruncher_result_reason", "No y-cruncher values parsed from report", "")
                info["y_cruncher"] = {"status": "skip", "reason": "no whitelisted keys found"}
            else:
                for k, v in kv.items():
                    add_change(YCRUNCHER_TARGET_ITEM_GROUP, k, v, "")

                y_status, y_reason = _evaluate_ycruncher_status(kv)
                y_result = get_direct_status_result(
                    "y_cruncher_status",
                    y_status,
                    YCRUNCHER_TARGET_ITEM_GROUP
                )
                add_change(
                    y_result.get("item_group"),
                    y_result.get("parameter"),
                    y_result.get("value"),
                    "",
                    y_result.get("score"),
                    y_result.get("part_config_id")
                )
                add_change(YCRUNCHER_TARGET_ITEM_GROUP, "y_cruncher_result_reason", y_reason, "")
                info["y_cruncher"] = {
                    "status": "ok",
                    "keys_written": list(kv.keys()),
                    "final_status": y_status,
                    "reason": y_reason
                }
        except Exception as e:
            y_result = get_direct_status_result(
                "y_cruncher_status",
                "FAIL",
                YCRUNCHER_TARGET_ITEM_GROUP
            )
            add_change(
                y_result.get("item_group"),
                y_result.get("parameter"),
                y_result.get("value"),
                "",
                y_result.get("score"),
                y_result.get("part_config_id")
            )
            add_change(YCRUNCHER_TARGET_ITEM_GROUP, "y_cruncher_result_reason", f"Error while parsing y-cruncher file: {str(e)}", "")
            info["y_cruncher"] = {"status": "error", "error": str(e)}

    # -------------------------
    # GAMING FPS
    # -------------------------
    g_file_docname = None
    for row in doc.get("njqca_result_parameters") or []:
        p = (row.get("parameter") or "").strip()
        if _key(p) == _key(GAMING_FPS_REF_PARAM):
            val = _get_row_value(row, value_field)
            if val:
                g_file_docname = str(val).strip()
            break

    if g_file_docname:
        try:
            file_doc = frappe.get_doc("File", g_file_docname)
            csv_bytes = _read_file_bytes_from_filedoctype(file_doc)

            metrics = _parse_gaming_fps_metrics_from_csv_bytes(csv_bytes)
            if "gaming_error" in metrics:
                info["gaming_fps"] = {"status": "error", "error": metrics.get("gaming_error")}
            else:
                for k, v in metrics.items():
                    unit = GAMING_METRIC_UNITS.get(k, "")
                    add_change(GAMING_TARGET_ITEM_GROUP, k, v, unit)
                info["gaming_fps"] = {"status": "ok", "metrics": metrics}
        except Exception as e:
            info["gaming_fps"] = {"status": "error", "error": str(e)}

    # -------------------------
    # PERFORMANCE TXT
    # -------------------------
    perf_file_docname = None
    for row in doc.get("njqca_result_parameters") or []:
        p = (row.get("parameter") or "").strip()
        if _key(p) == _key(PERFORMANCE_REF_PARAM):
            val = _get_row_value(row, value_field)
            if val:
                perf_file_docname = str(val).strip()
            break

    if perf_file_docname:
        try:
            file_doc = frappe.get_doc("File", perf_file_docname)
            raw_bytes = _read_file_bytes_from_filedoctype(file_doc)
            text = raw_bytes.decode("utf-8-sig", errors="ignore")

            perf = _parse_performance_txt_metrics(text)
            if not perf:
                info["performance"] = {"status": "skip", "reason": "no requested performance metrics found"}
            else:
                written = []
                for param, (val, unit) in perf.items():
                    add_change(PERFORMANCE_TARGET_ITEM_GROUP, param, val, unit)
                    written.append(param)
                info["performance"] = {"status": "ok", "metrics_written": written}
        except Exception as e:
            info["performance"] = {"status": "error", "error": str(e)}

    # CONNECTIVITY (from components)
    try:
        info["connectivity"] = _collect_connectivity_changes(doc, add_change)
    except Exception as e:
        info["connectivity"] = {"status": "error", "error": str(e)}

    print('_collect_battery_bdt_change(doc, add_change)', _collect_battery_bdt_change(doc, add_change))

    # BATTERY BDT (latest backup_duration_cycle_1)
    info["battery_bdt"] = _collect_battery_bdt_change(doc, add_change)

    return {"info": info, "changes": flush_changes()}

def _parse_disk_metrics_from_csv_bytes(csv_bytes: bytes) -> dict:
    text = csv_bytes.decode("utf-8-sig", errors="ignore")
    if not text.strip():
        return {}

    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        return {}

    raw_header = rows[0]
    header_norm = [
        h.strip().replace("\ufeff", "").replace("|", " ").replace("#", " ").lower().strip()
        for h in raw_header
    ]

    def find_col(*keyword_sets):
        for keywords in keyword_sets:
            for i, h in enumerate(header_norm):
                if all(k.lower() in h for k in keywords):
                    return i
        return None

    # Find all required columns
    cpu_col        = find_col(["cpu %"], ["cpu%"], ["cpu"])
    disk_read_col  = find_col(["disk read mbs"], ["disk read mb/s"], ["disk read"], ["read mbs"], ["read mb"])
    disk_write_col = find_col(["disk write mbs"], ["disk write mb/s"], ["disk write"], ["write mbs"], ["write mb"])
    time_col       = find_col(["time"])

    if cpu_col is None:
        return {
            "Disk Response Time":          "ERROR: CPU column not found",
            "Sequential Read Stability":   "ERROR: CPU column not found",
            "Sequential Write Stability":  "ERROR: CPU column not found",
            "Disk Active Time at Idle":    "ERROR: CPU column not found",
            "CPU-Disk Bottleneck Ratio":   "ERROR: CPU column not found",
        }

    if disk_read_col is None or disk_write_col is None:
        return {
            "Disk Response Time":          "ERROR: Disk Read/Write column not found",
            "Sequential Read Stability":   "ERROR: Disk Read/Write column not found",
            "Sequential Write Stability":  "ERROR: Disk Read/Write column not found",
            "Disk Active Time at Idle":    "ERROR: Disk Read/Write column not found",
            "CPU-Disk Bottleneck Ratio":   "ERROR: Disk Read/Write column not found",
        }

    def _to_float(val):
        try:
            return float(str(val).strip().replace(",", "."))
        except (ValueError, TypeError):
            return None

    def _to_sec(t):
        if not t:
            return None
        parts = str(t).strip().split(":")
        if len(parts) == 3:
            try:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            except Exception:
                return None
        return None

    # Parse all rows
    data = []
    for r in rows[1:]:
        cpu   = _to_float(r[cpu_col])        if cpu_col        < len(r) else None
        read  = _to_float(r[disk_read_col])  if disk_read_col  < len(r) else None
        write = _to_float(r[disk_write_col]) if disk_write_col < len(r) else None
        t     = r[time_col].strip()          if time_col and time_col < len(r) else None

        if cpu is not None:
            data.append({
                "cpu":   cpu,
                "read":  read  if read  is not None else 0.0,
                "write": write if write is not None else 0.0,
                "time":  t,
            })

    if not data:
        return {
            "Disk Response Time":          "ERROR: no valid data rows",
            "Sequential Read Stability":   "ERROR: no valid data rows",
            "Sequential Write Stability":  "ERROR: no valid data rows",
            "Disk Active Time at Idle":    "ERROR: no valid data rows",
            "CPU-Disk Bottleneck Ratio":   "ERROR: no valid data rows",
        }

    results = {}

    # ── Metric 4: Disk Response Time ─────────────────────────────────────────
    # Avg I/O latency in ms = (sample interval in seconds / total IO MB/s) * 1000
    # Only during high CPU load rows

    def _to_sec(t):
        if not t:
            return None
        parts = str(t).strip().split(":")
        if len(parts) == 3:
            try:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            except Exception:
                return None
        return None

    high_cpu_data = [d for d in data if d["cpu"] >= 80]

    latency_vals = []
    for i in range(1, len(high_cpu_data)):
        prev = high_cpu_data[i - 1]
        curr = high_cpu_data[i]

        t1 = _to_sec(prev["time"])
        t2 = _to_sec(curr["time"])

        if t1 is None or t2 is None:
            continue

        interval_sec = t2 - t1
        if interval_sec <= 0:
            continue

        total_io = curr["read"] + curr["write"]
        if total_io <= 0:
            continue

        # latency = how many ms to process 1 MB
        latency_ms = (interval_sec / total_io) * 1000
        latency_vals.append(latency_ms)

    if latency_vals:
        results["Disk Response Time"] = round(
            sum(latency_vals) / len(latency_vals), 2
        )
    else:
        results["Disk Response Time"] = "No I/O data during high CPU load"

    # ── Metric 5: Sequential Read Stability ──────────────────────────────────
    # AVG(Disk Read MB/s) where CPU >= 80%
    read_under_load = [d["read"] for d in data if d["cpu"] >= 80]
    if read_under_load:
        results["Sequential Read Stability"] = round(
            sum(read_under_load) / len(read_under_load), 2
        )
    else:
        results["Sequential Read Stability"] = None

    # ── Metric 6: Sequential Write Stability ─────────────────────────────────
    # AVG(Disk Write MB/s) where CPU >= 80%
    write_under_load = [d["write"] for d in data if d["cpu"] >= 80]
    if write_under_load:
        results["Sequential Write Stability"] = round(
            sum(write_under_load) / len(write_under_load), 2
        )
    else:
        results["Sequential Write Stability"] = None

    # ── Metric 7: Disk Active Time at Idle ───────────────────────────────────
    # Disk usage (read + write MB/s) when CPU < 10%
    idle_rows = [d for d in data if d["cpu"] < 10]
    if idle_rows:
        idle_io = [d["read"] + d["write"] for d in idle_rows]
        results["Disk Active Time at Idle"] = round(
            sum(idle_io) / len(idle_io), 2
        )
    else:
        results["Disk Active Time at Idle"] = "CPU never dropped below 10%"

    # ── Metric 8: CPU-Disk Bottleneck Ratio ──────────────────────────────────
    # High CPU (>= 80%) + low disk read throughput (< 10 MB/s)
    # Count of such rows as % of total high-CPU rows
    high_cpu_rows = [d for d in data if d["cpu"] >= 80]
    if high_cpu_rows:
        bottleneck_rows = [d for d in high_cpu_rows if d["read"] < 10]
        bottleneck_pct = round(
            len(bottleneck_rows) / len(high_cpu_rows) * 100, 2
        )
        results["CPU-Disk Bottleneck Ratio"] = bottleneck_pct
    else:
        results["CPU-Disk Bottleneck Ratio"] = None

    return results
# ==========================================================
# Whitelisted endpoint: returns changes (NOT updated_result_parameters)
# ==========================================================

@frappe.whitelist()
def get_reliability_test_status(doc):
    """
    Called from JS validate.
    DOES NOT mutate doc child table. Returns list of changes for JS to upsert.
    """
    if isinstance(doc, str):
        doc = json.loads(doc)

    if isinstance(doc, dict):
        for key in ("njqca_laptop_ram", "njqca_laptop_storage"):
            if key in doc and isinstance(doc[key], list):
                for row in doc[key]:
                    if isinstance(row, dict) and "_item_templates" in row:
                        del row["_item_templates"]

    d = frappe.get_doc(doc)

    res = _apply_reliability_enrichment_no_mutation(d)
    return {
        "info": res["info"],
        "changes": res["changes"],
    }

@frappe.whitelist()
def get_item_variant_attributes(item_code):
    return frappe.get_all(
        "Item Variant Attribute",
        filters={"parent": item_code},
        fields=["attribute", "attribute_value"],
        ignore_permissions=True,
    )


def previous_njqca_failed_result_validation(doc, method=None):

    log_prefix = "previous_njqca_failed_result_validation"
    logger.info("%s: started %s", log_prefix, frappe.as_json({
        'njqca_name': doc.name,
        'created': doc.created,
        'creation': doc.creation,
        'inspection_type': doc.inspection_type,
        'docstatus': doc.docstatus,
    }))

    current_user_email = frappe.session.user
    current_employee_data = frappe.db.get_value(
        "Employee",
        {"user_id": current_user_email, "status": "Active"},
        ["name", "allow_qc"],
        as_dict=True,
    )
    logger.info("%s: current_user_allow_qc_check %s", log_prefix, frappe.as_json({
        "current_user_email": current_user_email,
        "employee": current_employee_data,
    }))

    if current_employee_data and int(current_employee_data.get("allow_qc") or 0) == 0:
        frappe.throw(_("You are not allowed to submit this DOC. Please contact your Manager."))

    disabled_qc_parameters = frappe.db.sql("""
        SELECT DISTINCT
            cl.name AS qc_name,
            cl.parameter
        FROM `tabNJQCA` AS nj
        INNER JOIN `tabNJ Quality Checks` AS njq
            ON njq.inspection_type = nj.inspection_type
        INNER JOIN `tabNj QC Options` AS qco
            ON qco.parent = njq.name
        INNER JOIN `tabNJ QC Check List` AS cl
            ON cl.name = qco.quality_check
        WHERE
            cl.disable_qc = 1
            AND nj.inspection_type = %(inspection_type)s
            AND nj.name = %(njqca_name)s
    """, {
        "inspection_type": doc.inspection_type,
        "njqca_name": doc.name,
    }, as_dict=True)
    logger.info("%s: disabled_qc_parameters %s", log_prefix, frappe.as_json(disabled_qc_parameters))

    disabled_parameters = [
        row.parameter
        for row in disabled_qc_parameters
        if row.get("parameter")
    ]

    if not disabled_parameters:
        logger.info("%s: skipped because no disabled QC parameters found", log_prefix)
        return {
            "disabled_qc_parameters": disabled_qc_parameters,
            "failed_parameters": [],
            "latest_njqca_records": [],
        }

    failed_parameter_map = {}

    for row in doc.get("njqca_result_parameters") or []:
        parameter = (row.get("parameter") or "").strip()
        value = (row.get("value") or "").strip()

        if parameter in disabled_parameters and "FAIL" in value.upper():
            failed_parameter_map[parameter] = row

    if not failed_parameter_map:
        failed_parameter_rows = frappe.db.sql("""
            SELECT parameter, value
            FROM `tabNJQCA Result Parameters`
            WHERE parent = %(njqca_name)s
                AND UPPER(value) LIKE %(fail_value)s
                AND parameter IN %(parameters)s
        """, {
            "njqca_name": doc.name,
            "parameters": tuple(disabled_parameters),
        }, as_dict=True)

        failed_parameter_map = {
            row.parameter: row
            for row in failed_parameter_rows
            if row.get("parameter")
        }

    failed_parameters = list(failed_parameter_map.keys())
    logger.info("%s: current_failed_parameters %s", log_prefix, frappe.as_json(failed_parameters))

    if not failed_parameters:
        logger.info("%s: skipped because current NJQCA has no failed disabled parameters", log_prefix)
        return {
            "disabled_qc_parameters": disabled_qc_parameters,
            "failed_parameters": [],
            "latest_njqca_records": [],
        }

    employee_data = frappe.db.get_value(
        "Employee",
        {"user_id": doc.created},
        ["name", "allow_qc", "qc_time_stamp"],
        as_dict=True,
    )
    employee_qc_time_stamp = employee_data.get("qc_time_stamp") if employee_data else None
    logger.info("%s: employee_data %s", log_prefix, frappe.as_json(employee_data or {}))

    latest_njqca_filters = {
        "created": doc.created,
        "njqca_name": doc.name,
    }
    latest_njqca_creation_condition = ""

    if employee_qc_time_stamp:
        latest_njqca_filters["qc_time_stamp"] = employee_qc_time_stamp
        latest_njqca_creation_condition = """
            AND creation > %(qc_time_stamp)s
        """

    logger.info("%s: latest_njqca_query_filters %s", log_prefix, frappe.as_json({
        'filters': latest_njqca_filters,
        'qc_time_stamp_filter_applied': bool(employee_qc_time_stamp),
    }))

    latest_njqca_records = frappe.db.sql(f"""
        SELECT
            name,
            inspection_type,
            created,
            docstatus,
            creation
        FROM `tabNJQCA`
        WHERE created = %(created)s
            AND name != %(njqca_name)s
            {latest_njqca_creation_condition}
        ORDER BY creation DESC
        LIMIT 3
    """, latest_njqca_filters, as_dict=True,debug=1)
    logger.info("%s: latest_njqca_records %s", log_prefix, frappe.as_json(latest_njqca_records))

    repeatedly_failed_parameters = []
    latest_njqca_names = [
        row.name
        for row in latest_njqca_records
        if row.get("name")
    ]

    if len(latest_njqca_names) >= 3:
        logger.info("%s: checking_previous_failures %s", log_prefix, frappe.as_json({
            'latest_njqca_names': latest_njqca_names,
            'failed_parameters_to_check': failed_parameters,
        }))
        previous_failed_rows = frappe.db.sql("""
            SELECT
                parameter,
                COUNT(DISTINCT parent) AS failed_count
            FROM `tabNJQCA Result Parameters`
            WHERE parent IN %(latest_njqca_names)s
                AND parameter IN %(failed_parameters)s
                AND UPPER(IFNULL(value, '')) = 'FAIL'
            GROUP BY parameter
        """, {
            "latest_njqca_names": tuple(latest_njqca_names),
            "failed_parameters": tuple(failed_parameters),
        }, as_dict=True)
        logger.info("%s: previous_failed_rows %s", log_prefix, frappe.as_json(previous_failed_rows))

        repeatedly_failed_parameters = [
            row.parameter
            for row in previous_failed_rows
            if row.get("parameter") and row.get("failed_count") == len(latest_njqca_names)
        ]
        logger.info("%s: repeatedly_failed_parameters %s", log_prefix, frappe.as_json(repeatedly_failed_parameters))
    else:
        logger.info("%s: skipped repeat-failure check because fewer than 3 NJQCA records were found %s", log_prefix, frappe.as_json({
            'latest_njqca_count': len(latest_njqca_names),
            'latest_njqca_names': latest_njqca_names,
        }))

    if repeatedly_failed_parameters:
        employee_name = employee_data.get("name") if employee_data else None
        employee_allow_qc = int(employee_data.get("allow_qc") or 0) if employee_data else 0
        employee_qc_time = employee_data.get("qc_time_stamp") if employee_data else None
        doc_creation = getattr(doc, "creation", None)

        if employee_allow_qc and employee_qc_time and doc_creation:
            employee_qc_time = frappe.utils.get_datetime(employee_qc_time)
            doc_creation = frappe.utils.get_datetime(doc_creation)

            if employee_qc_time >= doc_creation:
                logger.info("%s: allow_qc_override_allowed %s", log_prefix, frappe.as_json({
                    'employee': employee_name,
                    'allow_qc': employee_allow_qc,
                    'qc_time_stamp': employee_qc_time,
                    'doc_creation': doc_creation,
                    'repeatedly_failed_parameters': repeatedly_failed_parameters,
                }))

                return {
                    "disabled_qc_parameters": disabled_qc_parameters,
                    "failed_parameters": failed_parameters,
                    "latest_njqca_records": latest_njqca_records,
                    "repeatedly_failed_parameters": repeatedly_failed_parameters,
                    "allow_qc_override": True,
                }

        if employee_name:
            frappe.db.set_value(
                "Employee",
                employee_name,
                "allow_qc",
                0,
                update_modified=False,
            )
            frappe.db.commit()
            logger.info("%s: unchecked_employee_allow_qc %s", log_prefix, frappe.as_json({
                'employee': employee_name,
                'user_id': doc.created,
                'repeatedly_failed_parameters': repeatedly_failed_parameters,
            }))

        logger.info("%s: blocking_submit %s", log_prefix, frappe.as_json({
            'njqca_name': doc.name,
            'employee': employee_name,
            'latest_njqca_names': latest_njqca_names,
            'repeatedly_failed_parameters': repeatedly_failed_parameters,
        }))

        frappe.throw(_(
            "You are not allowed to submit this DOC because parameter {0} failed in Previous 3 NJQCA ({1}). Please Contact your Manager To submit this Doc"
        ).format(
            ", ".join(repeatedly_failed_parameters),
            ", ".join(latest_njqca_names),
        ))

    logger.info("%s: validation_passed %s", log_prefix, frappe.as_json({
        'njqca_name': doc.name,
        'latest_njqca_count': len(latest_njqca_names),
        'latest_njqca_names': latest_njqca_names,
        'failed_parameters': failed_parameters,
        'repeatedly_failed_parameters': repeatedly_failed_parameters,
    }))

    return {
        "disabled_qc_parameters": disabled_qc_parameters,
        "failed_parameters": failed_parameters,
        "latest_njqca_records": latest_njqca_records,
        "repeatedly_failed_parameters": repeatedly_failed_parameters,
    }
# ─────────────────────────────────────────────────────────────────────────────
# EXT-NJ Serial Linkage: BIOS-based bridge functions
# ─────────────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def check_ext_serial_linkage(bios_serial_no, nj_serial_no):
    """
    Read-only check: does any EXT serial (rfq_id is set) carry this BIOS?
    Returns a dict consumed by JS to decide whether to show the confirm dialog.

    Possible outcomes:
      { found: False }                          → no EXT serial has this BIOS
      { found: True, already_linked: True, ... } → already linked to each other (idempotent)
      { found: True, already_linked: False, ext_serial: "EXT-XXX" } → prompt user
    Throws frappe error for conflict situations (Cases A and B).
    """
    print("bios_serial_no >>>>>>", bios_serial_no)
    print("nj_serial_no >>>>>>", nj_serial_no)
    if not bios_serial_no or not nj_serial_no:
        return {"found": False}

    # Look for an EXT serial with this BIOS (rfq_id IS NOT NULL means external)
    ext_serials = frappe.get_all(
        "Serial No",
        filters={"bios_serial_no": bios_serial_no},
        fields=["name", "linked_ext"],
        limit=1,
    )
    ext_serial = ext_serials[0] if ext_serials else None

    if not ext_serial:
        return {"found": False}

    # CASE A: EXT already linked to a DIFFERENT NJ serial
    if ext_serial.linked_ext and ext_serial.linked_ext != nj_serial_no:
        frappe.throw(
            f"EXT serial <b>{ext_serial.name}</b> is already linked to NJ serial "
            f"<b>{ext_serial.linked_ext}</b>. Cannot link again."
        )

    # CASE B: NJ serial already linked to a different EXT serial
    nj_linked_ext = frappe.db.get_value("Serial No", nj_serial_no, "linked_ext")
    if nj_linked_ext and nj_linked_ext != ext_serial.name:
        frappe.throw(
            f"NJ Serial <b>{nj_serial_no}</b> is already linked to a different EXT serial "
            f"<b>{nj_linked_ext}</b>. Cannot link again."
        )

    # CASE D: Already linked to each other (idempotent re-load)
    if ext_serial.linked_ext == nj_serial_no and nj_linked_ext == ext_serial.name:
        return {"found": True, "already_linked": True, "ext_serial": ext_serial.name}

    # CASE C: EXT found and not yet linked — prompt the user
    return {"found": True, "already_linked": False, "ext_serial": ext_serial.name}


@frappe.whitelist()
def link_ext_to_nj_serial(ext_serial_no, nj_serial_no, njqca_name):
    """
    Called when user confirms YES in the dialog.
    - Copies serial_no_component rows from EXT serial → NJ serial (clears NJ first)
    - Sets linked_ext on both Serial No documents
    - Sets linked_ext on the NJQCA document for reference
    Does NOT remove bios_serial_no from EXT (that happens on NJQCA submit).
    """
    ext_doc = frappe.get_doc("Serial No", ext_serial_no)
    nj_doc  = frappe.get_doc("Serial No", nj_serial_no, for_update=True)

    # Clear existing serial_no_component on NJ serial
    nj_doc.set("serial_no_component", [])

    # Copy all component rows from EXT serial to NJ serial
    for row in ext_doc.serial_no_component:
        nj_doc.append("serial_no_component", {
            "item_group":           row.item_group,
            "item":                 row.item,
            "grade":                row.grade,
            "is_available":         row.is_available,
            "quantity":             row.quantity,
            "component_serial_no":  row.component_serial_no,
            "item_group_idx":       row.item_group_idx,
            "reference_doctype":    row.reference_doctype,
            "reference_doctype_no": row.reference_doctype_no,
        })

    # Link NJ serial → EXT serial
    nj_doc.linked_ext = ext_serial_no
    nj_doc.save(ignore_permissions=True)

    # Link EXT serial → NJ serial
    frappe.db.set_value(
        "Serial No", ext_serial_no, "linked_ext", nj_serial_no, update_modified=False
    )

    # Set linked_ext on NJQCA doc for reference
    frappe.db.set_value(
        "NJQCA", njqca_name, "linked_ext", ext_serial_no, update_modified=False
    )

    return {"success": True}
