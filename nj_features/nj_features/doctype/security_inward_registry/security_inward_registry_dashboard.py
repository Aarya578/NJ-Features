from frappe import _


def get_data():
	return {
		"fieldname": "stock_registry_no",
		"non_standard_fieldnames": {
			# "Stock Entry": "registry_no",
			"Purchase Receipt": "registry_no",
			# "Delivery Note": "registry_no"
		},
		"transactions": [
			{"label": _("Inward"), "items": ["Purchase Receipt"]},
			{"label": _("Returns"), "items": ["Delivery Note"]},
			{"label": _("Transfer"), "items": ["Stock Entry"]}
		],
	}
