from . import __version__ as app_version

app_name = "nj_features"
app_title = "NJ Features"
app_publisher = "NewJaisa - IT Team"
app_description = "Moving all custom developed apps to this app. Development from 28th Oct 2023 will be available in this app"
app_icon = "octicon octicon-file-directory"
app_color = "blue"
app_email = "itsupport@newjaisa.com"
app_license = "MIT"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/nj_features/css/nj_features.css"
app_include_js = "/assets/nj_features/js/nj_features.js"

# include js, css files in header of web template
# web_include_css = "/assets/nj_features/css/nj_features.css"
# web_include_js = "/assets/nj_features/js/nj_features.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "nj_features/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
    "Item": "public/js/item.js",
    "Issue": "public/js/issue.js",
    "Employee": "public/js/employee.js",
    "Serial No": "public/js/serial_no.js",
    "Warehouse": "public/js/warehouse.js",
    "Department": "public/js/department.js",
	"Role Profile": "public/js/role_profile.js",
    "Delivery Note": "public/js/delivery_note.js",
    "Sales Invoice": "public/js/sales_invoice.js",
    "Purchase Order": "public/js/purchase_order.js",
    "Material Request": "public/js/material_request.js",
    "Purchase Receipt": "public/js/purchase_receipt.js",
    "Quality Procedure": "public/js/quality_procedure.js",
    "Quality Review": "public/js/quality_review.js",
    "Product Bundle": "public/js/product_bundle.js",
    "Address": "public/js/address.js",
    "Sales Order": "public/js/sales_order.js",
}

doctype_list_js = {
    "Employee": "public/js/employee_list.js",
    "Sales Order": "public/js/sales_order_list.js",
    "Serial No": "public/js/serial_no_list.js",
    "Sales Invoice": "public/js/sales_invoice_list.js"
}

# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Installation
# ------------

# before_install = "nj_features.install.before_install"
# after_install = "nj_features.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "nj_features.uninstall.before_uninstall"
# after_uninstall = "nj_features.uninstall.after_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "nj_features.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
#	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
#	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

override_doctype_class = {
    "Product": "nj_features.overrides.product",
    "Order": "nj_features.overrides.order",
    "Issue": "nj_features.overrides.issue.CustomIssue",
    "Warehouse": "nj_features.overrides.warehouse.CustomWarehouse",
    "Address": "nj_features.overrides.address.CustomeAddress",
    "Sales Order": "nj_features.overrides.sales_order.CustomSalesOrder",
    "Workstation": "nj_features.overrides.workstation.CustomeWorkstation",
    "Delivery Note": "nj_features.overrides.delivery_note.CustomDeliveryNote",
    "Sales Invoice": "nj_features.overrides.sales_invoice.CustomSalesInvoice",	
    "Product Bundle": "nj_features.overrides.product_bundle.CustomProductBundle",
    "Quality Review": "nj_features.overrides.quality_review.CustomQualityReview",
    "Purchase Receipt": "nj_features.overrides.purchase_receipt.CustomPurchaseReceipt",
    "Stock Ledger Entry": "nj_features.overrides.stock_ledger_entry.CustomStockLedgerEntry",
}

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"Purchase Receipt": {
# 		"before_save": "nj_features.overrides.purchase_receipt.get_batch",
# 		"on_submit": "nj_features.overrides.purchase_receipt.update_serial_no_on_pr_submit",
# 	},
#     "Purchase Order": {
#         "validate": "nj_features.overrides.purchase_order.validate_mandatory_links"
#     },
#     "NJQCA": {
#         "onload": "nj_features.nj_features.api.api_files.get_backup_duration",
#         "before_submit": "nj_features.nj_features.api.api_files.get_backup_duration"
# 	}
# }
doc_events = {
    "Purchase Receipt": {
        "before_save": "nj_features.overrides.purchase_receipt.generate_batch_no",
        "on_submit": "nj_features.overrides.purchase_receipt.get_batch"
    },
    "Purchase Order": {
        "validate": "nj_features.overrides.purchase_order.validate_mandatory_links",
        "on_submit": "nj_features.overrides.purchase_order.validate_warranty_on_submit",
    },
    "NJQCA": {
        "onload": "nj_features.nj_features.api.api_files.get_backup_duration",
        "before_submit": "nj_features.nj_features.api.api_files.get_backup_duration"
    },
    "*": {
        "on_submit": "nj_features.nj_features.doctype.department_recommendation_engine.department_recommendation_engine.apply_recommendation_rules",
        "on_update_after_submit": "nj_features.nj_features.doctype.department_recommendation_engine.department_recommendation_engine.apply_recommendation_rules"
    }
}

# doc_events = {
#     "Sales Order": {
#         # "after_save": "nj_features.doctypes.amazon_sales_order.amazon_sales_order.tesing_one"
#         "on_submit": "nj_features.doctypes.amazon_sales_order.amazon_sales_order.on_submit"
#     },
#     "Delivery Note": {
#         # "after_save": "nj_features.doctypes.amazon_sales_order.amazon_sales_order.tesing>
#         "on_submit": "nj_features.doctypes.amazon_sales_order.amazon_sales_order.validate_delivery_note"
#     },
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
#	"all": [
#		"nj_features.tasks.all"
#	],
#	"daily": [
#		"nj_features.tasks.daily"
#	],
#	"hourly": [
#		"nj_features.tasks.hourly"
#	],
#	"weekly": [
#		"nj_features.tasks.weekly"
#	]
#	"monthly": [
#		"nj_features.tasks.monthly"
#	]
# }

# scheduler_events = {
# 	"cron": {
# 		# Every ten minutes
# 		"*/2 * * * *": [
# 			"nj_features.doctypes.amazon_sales_order.amazon_sales_order.schedule_get_order_details"
# 		],
# 		"0/30 * * * *": [
# 			"nj_features.doctypes.amazon_sales_order.amazon_sales_order.amazon_shiped_status",
# 		]
# 	}
# }

override_whitelisted_methods = {
    "ecommerce_integrations.shopify.order.sync_sales_order": "nj_features.overrides.order.sync_sales_order",
    "ecommerce_integrations.shopify.order.create_order": "nj_features.overrides.order.create_order",
    "ecommerce_integrations.shopify.order.create_sales_order": "nj_features.overrides.order.create_sales_order",
    "ecommerce_integrations.shopify.product.get_item_code": "nj_features.overrides.product.get_item_code",
    "ecommerce_integrations.shopify.product.create_items_if_not_exist": "nj_features.overrides.product.create_items_if_not_exist",
    "erpnext.regional.india.e_invoice.utils.make_einvoice": "nj_features.overrides.sales_invoice.custom_make_einvoice",
    "erpnext.controllers.accounts_controller.validate_einvoice_fields": "nj_features.overrides.sales_invoice.validate_einvoice_fields",
}


scheduler_events = {
    "cron": {
        "0 22 * * *": [
            "nj_features.nj_features.doctype.daily_individual_report.daily_individual_report.daily_report_not_submitted_warehouses_data",
            "njcompliance.nj_compliance.doctype.nj_non_compliance.nj_non_compliance.raise_nc_undone_daily_individual_report"
        ],
        "45 7 * * *": [ 
            "nj_features.overrides.employee.update_employee_experience_table",
        ],		
        "1 * * * *": [
            "nj_features.overrides.product_bundle.update_product_bundle_quantities",
        ],
        "50 12 * * *": [
            "nj_features.nj_features.doctype.department_change_log.department_change_log.update_department_change_logs",
        ],
        "10 * * * *": [
            "nj_features.nj_features.doctype.nj_production_planning.nj_production_planning.get_department_details"
        ],
        "0 * * * *": [
            "nj_features.nj_features.api.shopify_inventory.fetch_and_stage_inventory_sync"
        ],
        "20,40 * * * *": [
            "nj_features.nj_features.api.shopify_inventory.start_shopify_inventory_sync"
        ],
         "0 */2 * * *": [
            "nj_features.nj_features.doctype.delivery_charges.delivery_charges.awb_number_tracking_status"
        ],
         "0 */3 * * *": [
            "nj_features.nj_features.doctype.delivery_charges.delivery_charges.criticalog_awb_number_tracking_status"
        ],
         "0 */5 * * *": [
            "nj_features.nj_features.doctype.delivery_charges.delivery_charges.update_status_in_shopify"
        ],
        "0 */2 * * *": [
            "nj_features.nj_features.doctype.so_quantity_check.so_quantity_check.updting_sla_department"
        ]
    }
}

# update_status_in_shopify
# Testing
# -------

# before_tests = "nj_feyour_app_nameatures.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
#	"frappe.desk.doctype.event.event.get_events": "nj_features.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
#	"Task": "nj_features.task.get_dashboard_data"
# }

# override_doctype_class = {
# 	# "frappe.desk.doctype.event.event.get_events": "customizations_newjaisa.event.get_events"
# 	"Amazon SP API Settings": "nj_features.doctypes.amazon_sales_order.amazon_sales_order.Amazonoverride"
# }
# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Request Events
# ----------------
# before_request = ["nj_features.utils.before_request"]
# after_request = ["nj_features.utils.after_request"]

# Job Events
# ----------
# before_job = ["nj_features.utils.before_job"]
# after_job = ["nj_features.utils.after_job"]

# User Data Protection
# --------------------

user_data_fields = [
	{
		"doctype": "{doctype_1}",
		"filter_by": "{filter_by}",
		"redact_fields": ["{field_1}", "{field_2}"],
		"partial": 1,
	},
	{
		"doctype": "{doctype_2}",
		"filter_by": "{filter_by}",
		"partial": 1,
	},
	{
		"doctype": "{doctype_3}",
		"strict": False,
	},
	{
		"doctype": "{doctype_4}"
	}
]

# website_route_rules = [
#     {"from_route": "/stock-movement/&lt;name&gt;", "to_route": "stock-entry/new"},
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
#	"nj_features.auth.validate"
# ]