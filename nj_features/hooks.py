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
    "Employee": "public/js/employee.js",
    "Serial No": "public/js/serial_no.js",
    "Warehouse": "public/js/warehouse.js",
    "Purchase Order": "public/js/purchase_order.js",
    "Purchase Receipt": "public/js/purchase_receipt.js",
    "Delivery Note": "public/js/delivery_note.js",
    "Sales Invoice": "public/js/sales_invoice.js",
}
doctype_list_js = {
    "Sales Order": "public/js/sales_order.js",
    "Serial No": "public/js/serial_no_list.js",
    "Purchase Order": "public/js/purchase_order_list.js",
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
	"Stock Ledger Entry": "nj_features.overrides.stock_ledger_entry.CustomStockLedgerEntry"
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Purchase Receipt": {
		"before_save": "nj_features.overrides.purchase_receipt.get_batch",
		"on_submit": "nj_features.overrides.purchase_receipt.update_serial_no_on_pr_submit",
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
# 		"*/10 * * * *": [
# 			"nj_features.doctypes.amazon_sales_order.amazon_sales_order.schedule_get_order_details"
# 		],
# 		"0/30 * * * *": [
# 			"nj_features.doctypes.amazon_sales_order.amazon_sales_order.amazon_shiped_status",
# 		]
# 	}
# }

scheduler_events = {
	"cron": {
		"0 22 * * *": [
			"nj_features.nj_features.doctype.daily_individual_report.daily_individual_report.all_no_selected_serial_no_data",
			"nj_features.nj_features.doctype.daily_individual_report.daily_individual_report.daily_report_not_submitted_warehouses_data",
			"nj_features.nj_features.doctype.daily_individual_report.daily_individual_report.daily_report_to_send_personal_mail",
		]
	}
}

# Testing
# -------

# before_tests = "nj_features.install.before_tests"

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

override_whitelisted_methods = {
    "nj_features.nj_features.api.date_time_api.current_date_time": "nj_features.nj_features.api.date_time_api.current_date_time"
}
