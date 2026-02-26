
from __future__ import unicode_literals

import frappe
import frappe.cache_manager
from frappe import _
from frappe.model import log_types
from frappe.model.document import Document

logger = frappe.logger('DREngine', allow_site=True, file_count=1)
class DepartmentRecommendationEngine(Document):
    def validate(self):
        if self.document_type == "ToDo":
            frappe.throw(
                _("Department Recommendation Engine is not allowed on {0} document type").format(frappe.bold("ToDo"))
            )

    def on_update(self):
        clear_recommendation_rule_cache(self)

    def after_rename(self, old, new, merge):
        clear_recommendation_rule_cache(self)

    def on_trash(self):
        clear_recommendation_rule_cache(self)

    def apply_recommendation(self, doc):
        """Apply recommendation rule when condition is met"""        
        # ✅ Check if document status is either Draft (0) or Submitted (1)
        if doc.get('docstatus') in [0, 1]:
            if self.safe_eval("python_condition", doc):
                print("safe eval true==================")

                # ✅ Step 1: Check SQL Condition
                if self.sql_condition:
                    try:
                        sql_query = self.sql_condition.strip()

                        # Replace {docname} with actual doc name
                        if "{docname}" in sql_query:
                            sql_query = sql_query.replace("{docname}", doc.name)

                        print("sql condition query====================", sql_query)

                        # Run the query
                        sql_result = frappe.db.sql(sql_query, as_dict=True)
                        print("sql condition result====================", sql_result)

                        # Extract result (0 or 1)
                        if sql_result and "result" in sql_result[0]:
                            condition_value = int(sql_result[0]["result"])
                        else:
                            condition_value = 0

                        print("sql condition result====================", condition_value)

                        # ✅ Step 2: Only execute python_action if condition_value == 1
                        if condition_value == 1:
                            return self.execute_python_action(doc)
                        else:
                            print("sql_condition returned 0, skipping python_action")
                            return False

                    except Exception as e:
                        frappe.log_error(
                            message=f"Error executing SQL Condition for rule {self.name}: {str(e)}",
                            title="Department Recommendation Engine SQL Error"
                        )
                        return False
                else:
                    # If no sql_condition provided → directly execute python_action
                    return self.execute_python_action(doc)

        return False

    # def apply_recommendation(self, doc):
    #     """Apply recommendation rule when condition is met"""        
    #     # Check if document status is either Draft (0) or Submitted (1)
    #     if doc.get('docstatus') in [0, 1]:
    #         if self.safe_eval("python_condition", doc):
    #             print("safe eval true==================")
    #             return self.execute_python_action(doc)
    #     return False

    def execute_python_action(self, doc):
        """Execute the python action"""
        if not self.python_action:
            return False

        try:
            # Create execution context
            context = self.get_execution_context(doc)
            python_action = self.python_action.strip()
            print("python action====================", python_action)

            # ✅ Replace placeholder with submitted doc name
            if "{docname}" in python_action:
                python_action = python_action.replace("{docname}", doc.name)
                print("python action with docname====================", python_action)

            # ✅ Check if it's a SQL query (starts with SELECT/UPDATE/DELETE/INSERT)
            if python_action.lower().startswith(("select", "update", "delete", "insert","with")):
                result = eq(python_action)
                print("Query Result ====================", result)

                # ✅ If query returned warehouse + barcode, update Serial No
                if result and isinstance(result, list) and "barcode" in result[0] and "warehouse" in result[0]:
                    suggest_warehouse_update(python_action)
            else:
                # ✅ Otherwise treat it as executable Python code
                exec(python_action, {"__builtins__": {}}, context)
                print("python action executed====================", python_action)

            frappe.db.commit()
            return True

        except Exception as e:
            frappe.log_error(
                message=f"Error executing Python Action for rule {self.name}: {str(e)}",
                title="Department Recommendation Engine Error"
            )
            frappe.msgprint(_("Recommendation rule execution failed: {0}").format(str(e)), indicator="orange")
            return False


    def get_execution_context(self, doc):
        """Get execution context for python action"""
        return {
            'doc': doc,
            'frappe': frappe,
            'db': frappe.db,
            'sql': frappe.db.sql,
            'get_doc': frappe.get_doc,
            'get_list': frappe.get_list,
            'get_all': frappe.get_all,
            'get_value': frappe.db.get_value,
            'set_value': frappe.db.set_value,
            'throw': frappe.throw,
            'msgprint': frappe.msgprint,
            'log_error': frappe.log_error,
            '_': _,
            'execute_query_and_update': execute_query_and_update,
            'update_serial_no_warehouse': update_serial_no_warehouse,
            'update_document_field': update_document_field
        }

    def safe_eval(self, fieldname, doc):
        """Safely evaluate python condition"""
        try:
            if self.get(fieldname):
                return frappe.safe_eval(self.get(fieldname), None, doc)
        except Exception as e:
            frappe.msgprint(
                frappe._("Recommendation rule evaluation failed: {0}").format(str(e)), 
                indicator="orange"
            )
        return False


# Helper Functions for Python Actions
def execute_query_and_update(query, barcode_field=None, target_doctype=None, target_field=None, source_field='warehouse'):
    """
    Helper function to execute query and update target document
    Usage: execute_query_and_update(query_string, 'barcode', 'Serial No', 'suggested_warehouse')
    """
    try:
        result = frappe.db.sql(query, as_dict=True)
        
        if result:
            for row in result:
                if barcode_field and target_doctype and target_field:
                    barcode = row.get(barcode_field)
                    source_value = row.get(source_field)
                    
                    if barcode and source_value:
                        update_serial_no_warehouse(barcode, source_value, target_field)
        
        return result
    except Exception as e:
        frappe.log_error(f"Error executing query: {str(e)}", "Query Execution Error")
        return []


def update_serial_no_warehouse(barcode, warehouse, field_name='suggested_warehouse'):
    """
    Update warehouse in Serial No document based on barcode
    """
    try:
        # Method 1: Try finding by serial no name directly
        if frappe.db.exists('Serial No', barcode):
            frappe.db.set_value('Serial No', barcode, field_name, warehouse)
            frappe.msgprint(f"Updated {field_name} to {warehouse} for Serial No: {barcode}")
            return True
            
        # Method 2: Try finding by custom barcode field
        serial_nos = frappe.get_all(
            'Serial No',
            filters={'barcode': barcode},
            fields=['name']
        )
        
        if serial_nos:
            for serial_no in serial_nos:
                frappe.db.set_value('Serial No', serial_no.name, field_name, warehouse)
                frappe.msgprint(f"Updated {field_name} to {warehouse} for Serial No: {serial_no.name}")
            return True
        else:
            frappe.msgprint(f"Serial No with barcode {barcode} not found", indicator="orange")
            return False
            
    except Exception as e:
        frappe.log_error(f"Error updating serial no warehouse: {str(e)}", "Serial No Update Error")
        return False


def update_document_field(doctype, docname, field_name, value):
    """
    Generic function to update any document field
    """
    try:
        frappe.db.set_value(doctype, docname, field_name, value)
        frappe.msgprint(f"Updated {field_name} to {value} for {doctype}: {docname}")
        return True
    except Exception as e:
        frappe.log_error(f"Error updating document field: {str(e)}", "Document Update Error")
        return False


# Main execution functions (similar to assignment_rule.py)
def apply_recommendation_rules(doc, method=None, doctype=None, name=None):
    """Main function to apply recommendation rules"""
    print("apply recommendation rules=======23456=============")
    if not doctype:
        doctype = doc.doctype

    if (
        frappe.flags.in_patch
        or frappe.flags.in_install
        or frappe.flags.in_setup_wizard
        or doctype in log_types
    ):
        return

    if not doc and doctype and name:
        doc = frappe.get_doc(doctype, name)

    # Get all recommendation rules for this document type
    recommendation_rules = frappe.cache_manager.get_doctype_map(
        "Department Recommendation Engine",
        doc.doctype,
        dict(document_type=doc.doctype, enabled=1),
        order_by="priority desc",
    )

    if not recommendation_rules:
        return

    recommendation_rule_docs = []
    for d in recommendation_rules:
        recommendation_rule_docs.append(frappe.get_cached_doc("Department Recommendation Engine", d.get("name")))

    doc = doc.as_dict()

    # Apply recommendation rules in priority order
    for recommendation_rule in recommendation_rule_docs:
        try:
            recommendation_rule.apply_recommendation(doc)
        except Exception as e:
            frappe.log_error(
                message=f"Error applying recommendation rule {recommendation_rule.name}: {str(e)}",
                title="Department Recommendation Engine Error"
            )


def clear_recommendation_rule_cache(rule):
    """Clear cache when rule is updated"""
    frappe.cache_manager.clear_doctype_map("Department Recommendation Engine", rule.document_type)


@frappe.whitelist()
def bulk_apply(doctype, docnames):
    """Apply recommendation rules to multiple documents"""
    import json
    
    docnames = json.loads(docnames)
    
    background = len(docnames) > 5
    for name in docnames:
        if background:
            frappe.enqueue(
                "nj_features.nj_features.doctype.department_recommendation_engine.department_recommendation_engine.apply_recommendation_rules",
                doc=None,
                doctype=doctype,
                name=name,
            )
        else:
            apply_recommendation_rules(None, doctype=doctype, name=name)



@frappe.whitelist()
def suggest_warehouse_update(query):
    """Execute query, then update Serial No.s suggested_warehouse field (comma separated if multiple warehouses)."""
    try:
        result = eq(query)
        print("Query Result ====================", result)

        if not result or "error" in result:
            return {"error": f"Query failed: {result}"}

        # Group warehouses by barcode
        warehouse_map = {}
        for row in result:
            barcode = row.get("barcode")
            warehouse = row.get("warehouse")

            if barcode and warehouse:
                if barcode not in warehouse_map:
                    warehouse_map[barcode] = []
                warehouse_map[barcode].append(warehouse)

        updated = []
        for barcode, warehouses in warehouse_map.items():
            # Join warehouses with comma
            warehouse_str = ", ".join(warehouses)

            frappe.db.set_value("Serial No", barcode, "suggested_warehouse", warehouse_str)
            updated.append({"barcode": barcode, "warehouses": warehouse_str})
            print(f"Updated Serial No {barcode} with warehouses {warehouse_str}")

        frappe.db.commit()
        return {"status": "success", "updated": updated}

    except Exception as e:
        frappe.log_error(
            message=f"Error in suggest_warehouse_update: {str(e)}",
            title="Suggest Warehouse Update Error"
        )
        return {"error": str(e)}


@frappe.whitelist()
def eq(query):
    if not isinstance(query, str):
        return {"error": "Query must be a string."}

    try:
        result = frappe.db.sql(query, as_dict=1)
        return result
    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}
@frappe.whitelist()
def test_recommendation_rule(rule_name, doc_name, doc_type):
    """Test a recommendation rule against a specific document"""
    try:
        # Get the rule
        rule = frappe.get_doc("Department Recommendation Engine", rule_name)
        
        # Get the test document
        test_doc = frappe.get_doc(doc_type, doc_name)
        
        # Apply the rule
        result = rule.apply_recommendation(test_doc.as_dict())
        
        if result:
            return f"Rule executed successfully for {doc_type}: {doc_name}"
        else:
            return f"Rule condition not met for {doc_type}: {doc_name}"
            
    except Exception as e:
        frappe.throw(f"Error testing rule: {str(e)}")


def get_recommendation_rules():
    """Get all enabled recommendation rules"""
    return [
        d.document_type
        for d in frappe.db.get_all(
            "Department Recommendation Engine", 
            fields=["document_type"], 
            filters=dict(enabled=1)
        )
    ]

































# from __future__ import unicode_literals

# import frappe
# from frappe import _ 
# from frappe.model.document import Document

# class DepartmentRecommendationEngine(Document):
#     def validate(self):
#         """Prevent usage on disallowed doctypes"""
#         if self.document_type == "ToDo":
#             frappe.throw(
#                 _("Department Recommendation Engine is not allowed on {0} document type").format(frappe.bold("ToDo"))
#             )

#     def on_update(self):
#         clear_recommendation_rule_cache(self)

#     def after_rename(self, old, new, merge):
#         clear_recommendation_rule_cache(self)

#     def on_trash(self):
#         clear_recommendation_rule_cache(self)

#     def apply_recommendation(self, doc):
#         """Apply recommendation rule when condition is met"""
#         if self.safe_eval("python_condition", doc):
#             return self.execute_python_action(doc)
#         return False

#     def execute_python_action(self, doc):
#         """Execute the python action safely"""
#         if not self.python_action:
#             return False

#         try:
#             context = self.get_execution_context(doc)
#             exec(self.python_action, {"__builtins__": {}}, context)
#             frappe.db.commit()
#             return True
#         except Exception as e:
#             frappe.log_error(
#                 message=f"Error executing Python Action for rule {self.name}: {str(e)}",
#                 title="Department Recommendation Engine Error"
#             )
#             frappe.msgprint(_("Recommendation rule execution failed: {0}").format(str(e)), indicator="orange")
#             return False

#     def get_execution_context(self, doc):
#         """Execution context for python actions"""
#         return {
#             'doc': doc,
#             'frappe': frappe,
#             'db': frappe.db,
#             'sql': frappe.db.sql,
#             'get_doc': frappe.get_doc,
#             'get_list': frappe.get_list,
#             'get_all': frappe.get_all,
#             'get_value': frappe.db.get_value,
#             'set_value': frappe.db.set_value,
#             'throw': frappe.throw,
#             'msgprint': frappe.msgprint,
#             'log_error': frappe.log_error,
#             '_': _,
#             'execute_query_and_update': execute_query_and_update,
#             'update_serial_no_warehouse': update_serial_no_warehouse,
#             'update_document_field': update_document_field
#         }

#     def safe_eval(self, fieldname, doc):
#         """Safely evaluate python condition"""
#         try:
#             if self.get(fieldname):
#                 return frappe.safe_eval(
#                     self.get(fieldname),
#                     {"doc": doc, "frappe": frappe}
#                 )
#         except Exception as e:
#             frappe.msgprint(
#                 _("Recommendation rule evaluation failed: {0}").format(str(e)), 
#                 indicator="orange"
#             )
#         return False


# # -------------------- Helper Functions --------------------

# def execute_query_and_update(query, barcode_field=None, target_doctype=None, target_field=None, source_field='warehouse'):
#     try:
#         result = frappe.db.sql(query, as_dict=True)
#         if result and barcode_field and target_doctype and target_field:
#             for row in result:
#                 barcode = row.get(barcode_field)
#                 source_value = row.get(source_field)
#                 if barcode and source_value:
#                     update_serial_no_warehouse(barcode, source_value, target_field)
#         return result
#     except Exception as e:
#         frappe.log_error(f"Error executing query: {str(e)}", "Query Execution Error")
#         return []

# def update_serial_no_warehouse(barcode, warehouse, field_name='suggested_warehouse'):
#     try:
#         if frappe.db.exists('Serial No', barcode):
#             frappe.db.set_value('Serial No', barcode, field_name, warehouse)
#             return True
#         serial_nos = frappe.get_all('Serial No', filters={'barcode': barcode}, fields=['name'])
#         if serial_nos:
#             for sn in serial_nos:
#                 frappe.db.set_value('Serial No', sn.name, field_name, warehouse)
#             return True
#         return False
#     except Exception as e:
#         frappe.log_error(f"Error updating serial no warehouse: {str(e)}", "Serial No Update Error")
#         return False

# def update_document_field(doctype, docname, field_name, value):
#     try:
#         frappe.db.set_value(doctype, docname, field_name, value)
#         return True
#     except Exception as e:
#         frappe.log_error(f"Error updating document field: {str(e)}", "Document Update Error")
#         return False


# # -------------------- Main Engine --------------------

# def apply_recommendation_rules(doc=None, method=None, doctype=None, name=None):
#     """Apply recommendation rules to a document"""
#     if not doctype and doc:
#         doctype = doc.doctype

#     if (
#         frappe.flags.in_patch
#         or frappe.flags.in_install
#         or frappe.flags.in_setup_wizard
#     ):
#         return

#     if not doc and doctype and name:
#         doc = frappe.get_doc(doctype, name)

#     # Get all enabled recommendation rules
#     rules = frappe.cache_manager.get_doctype_map(
#         "Department Recommendation Engine",
#         key=doc.doctype,
#         filters={"document_type": doc.doctype, "enabled": 1},
#         order_by="priority desc"
#     )

#     if not rules:
#         return

#     for r in rules:
#         rule_doc = frappe.get_cached_doc("Department Recommendation Engine", r.get("name"))
#         try:
#             rule_doc.apply_recommendation(doc)
#         except Exception as e:
#             frappe.log_error(
#                 message=f"Error applying recommendation rule {rule_doc.name}: {str(e)}",
#                 title="Department Recommendation Engine Error"
#             )

# def clear_recommendation_rule_cache(rule):
#     """Clear cache when a rule is updated"""
#     frappe.cache_manager.clear_doctype_map("Department Recommendation Engine", rule.document_type)


# # -------------------- Utilities --------------------

# @frappe.whitelist()
# def bulk_apply(doctype, docnames):
#     """Apply recommendation rules to multiple documents"""
#     import json
#     docnames = json.loads(docnames)
#     background = len(docnames) > 5

#     for name in docnames:
#         if background:
#             frappe.enqueue(
#                 "your_app.department_recommendation_engine.apply_recommendation_rules",
#                 doc=None,
#                 doctype=doctype,
#                 name=name,
#             )
#         else:
#             apply_recommendation_rules(None, doctype=doctype, name=name)

# @frappe.whitelist()
# def test_recommendation_rule(rule_name, doc_name, doc_type):
#     """Test a rule against a document"""
#     try:
#         rule = frappe.get_doc("Department Recommendation Engine", rule_name)
#         test_doc = frappe.get_doc(doc_type, doc_name)
#         result = rule.apply_recommendation(test_doc)
#         return "Rule executed successfully" if result else "Rule condition not met"
#     except Exception as e:
#         frappe.throw(f"Error testing rule: {str(e)}")

# def get_recommendation_rules():
#     """Get all enabled recommendation rules"""
#     return [
#         d.document_type
#         for d in frappe.get_all(
#             "Department Recommendation Engine",
#             filters={"enabled": 1},
#             fields=["document_type"]
#         )
#     ]
