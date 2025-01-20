import frappe
from frappe.model.document import Document
from erpnext.support.doctype.issue.issue import Issue

class CustomIssue(Issue):
    pass

@frappe.whitelist()        
def raise_issue_in_model(doc):
    try:
        # Parse the doc if it is a JSON string
        if isinstance(doc, str):
            doc = frappe.parse_json(doc)

        # Ensure a model is selected
        if not doc.get("model"):
            frappe.throw("Please select a model before proceeding.")

        # Fetch the Models document
        model_doc = frappe.get_doc("Models", doc.get("model"))

        # If the Models document exists
        if model_doc:
            # Create a new row for the bdt_model child table
            new_bdt_row = {
                "subject": doc.get("subject"),
                "issue_id": doc.get("name"),
                "status": doc.get("status"),
                "created_date": doc.get("creation")
            }

            # Append the new row
            model_doc.append("bdt_model", new_bdt_row)

            # Ignore permission checks and mandatory field validation
            model_doc.flags.ignore_permission = True
            model_doc.flags.ignore_mandatory = True
            
            # Save the Models document
            model_doc.save()
            frappe.db.commit()

            # Optional: Notify the user
            frappe.msgprint(f"Issue {doc.get('name')} has been successfully added to the model {doc.get('model')}.")
        else:
            frappe.throw(f"Model {doc.get('model')} not found.")
    except frappe.DoesNotExistError:
        frappe.throw(f"Model {doc.get('model')} does not exist.")
    except Exception as e:
        frappe.log_error(f"Error: {str(e)}", "Raise Issue in Model")
        frappe.throw("An error occurred while raising the issue in the model.")
