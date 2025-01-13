import frappe
from frappe.model.document import Document
from erpnext.support.doctype.issue.issue import Issue

class CustomIssue(Issue):
    def validate(self):
        super().validate()
        if self.issue_type == "MDT":
            self.raise_issue_in_model()
            
    def raise_issue_in_model(self):
        try:
            # Ensure a model is selected
            if not self.model:
                frappe.throw("Please select a model before proceeding.")

            model_doc = frappe.get_doc("Models", self.model)
            
            # If the Models document exists
            if model_doc:
                # Create a new row for the bdt_model child table
                new_bdt_row = {
                    "subject": self.subject,
                    "issue_id": self.name,
                    "status": self.status,
                    "created_date": self.creation
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
                frappe.msgprint(f"Issue {self.name} has been successfully added to the model {self.model}.")
            else:
                frappe.throw(f"Model {self.model} not found.")
        except frappe.DoesNotExistError:
            frappe.throw(f"Model {self.model} does not exist.")
        