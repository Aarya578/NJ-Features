import frappe
from frappe.model.document import Document


class ChangeManagementSettings(Document):

	def validate(self):
		self._block_child_tables()

	def _block_child_tables(self):
		for row in self.controlled_doctypes:
			if not row.doctype_name:
				continue
			istable = frappe.db.get_value("DocType", row.doctype_name, "istable")
			if not istable:
				continue
			parents = frappe.get_all(
				"DocField",
				filters={"options": row.doctype_name, "fieldtype": "Table"},
				pluck="parent",
			)
			parent_hint = (
				f"Add {', '.join(parents)} instead"
				if parents
				else "Its parent doctype could not be determined automatically -- "
				     "check which doctype embeds it as a Table field"
			)
			frappe.throw(
				f"'{row.doctype_name}' is a child table, not a standalone doctype -- "
				f"it never fires its own save event, so controlling it directly has no "
				f"effect. {parent_hint}. Child table rows are captured automatically "
				f"once their parent doctype is controlled."
			)

