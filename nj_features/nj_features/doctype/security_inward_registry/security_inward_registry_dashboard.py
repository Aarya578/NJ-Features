from frappe import _


def get_data():
	return {
		# "fieldname": "stock_registry_no",
		# "non_standard_fieldnames": {
		# 	"Stock Entry": "ste_number",
		# 	"Purchase Receipt": "registry_no",
		# 	"Delivery Note": "dn_reference"
		# },
		"internal_links": {
			"Purchase Receipt": ["items", "registry_no"],
			"Stock Movement": ["items", "registry_no"],
			"Stock Entry": ["items", "registry_no"],
		},
		"transactions": [
			{"label": _("Inward"), "items": ["Purchase Receipt"]},
			{"label": _("Transfer"), "items": ["Stock Entry", "Stock Movement"]},
			{"label": _("Returns"), "items": ["Delivery Note"]},
		],
	}
