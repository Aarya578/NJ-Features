from . import __version__ as app_version

app_name = "nj_features"
app_title = "NJ Features"
app_publisher = "NewJaisa - IT Team"
app_description = "Moving all custom developed apps to this app. Development from 28th Oct 2023 will be available in this app"
app_icon = "octicon octicon-file-directory"
app_color = "blue"
app_email = "itsupport@newjaisa.com"
app_license = "MIT"

# ========== Assets / Includes ==========
# include js, css files in header of desk.html
# app_include_css = "/assets/nj_features/css/nj_features.css"
app_include_js = "/assets/nj_features/js/nj_features.js"

# ========== Client Scripts ==========

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
    "Quotation": "public/js/quotation.js",
}

doctype_list_js = {
    "Employee": "public/js/employee_list.js",
    "Sales Order": "public/js/sales_order_list.js",
    "Serial No": "public/js/serial_no_list.js",
    "Sales Invoice": "public/js/sales_invoice_list.js",
}


# ========== Override Doctype Classes ==========

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
    "Quotation": "nj_features.overrides.quotation.CustomQuotation",
}

# ========== Doc Events ==========

doc_events = {
    "Item": {
        "after_insert": "nj_features.overrides.product.upload_erpnext_item",
        "on_update": "nj_features.overrides.product.upload_erpnext_item",
    },
    "Purchase Receipt": {
        "before_save": "nj_features.overrides.purchase_receipt.generate_batch_no",
        "on_submit": "nj_features.overrides.purchase_receipt.get_batch",
    },
    "Purchase Order": {
        "validate": "nj_features.overrides.purchase_order.validate_mandatory_links",
        "on_submit": "nj_features.overrides.purchase_order.validate_warranty_on_submit",
    },
    "NJQCA": {
        "onload": "nj_features.nj_features.api.api_files.get_backup_duration",
        "before_submit": "nj_features.nj_features.api.api_files.get_backup_duration",
    },
    "*": {
        "on_update": "nj_features.nj_features.doctype.department_recommendation_engine.department_recommendation_engine.apply_recommendation_rules",
        "on_submit": "nj_features.nj_features.doctype.department_recommendation_engine.department_recommendation_engine.apply_recommendation_rules",
        "on_update_after_submit": "nj_features.nj_features.doctype.department_recommendation_engine.department_recommendation_engine.apply_recommendation_rules",
    },
    # "Quotation": {
    #     "on_submit": "nj_features.nj_features.api.login.create_customer_response_token"
    # },
    # "Customer Response": {
    #     "before_save": "nj_features.nj_features.doctype.customer_response.customer_response.after_insert",
             
    # } ,    
    "Sales Invoice": {
        "before_save": "nj_features.overrides.sales_invoice.approve_validation",
        "before_save": "nj_features.overrides.sales_invoice.deviding_tax_chargese",
    },
    "Laptop Box": {
        "before_save": "nj_features.nj_features.doctype.laptop_box.laptop_box.printing_barcode"
    },
    "Delivery Note": {
        "before_save": "nj_features.overrides.delivery_note.deviding_tax_chargese"
    }

}

# ========== Override Whitelisted Methods ==========

override_whitelisted_methods = {
    "ecommerce_integrations.shopify.product.upload_erpnext_item": "nj_features.overrides.product.upload_erpnext_item",
    "ecommerce_integrations.shopify.order.sync_sales_order": "nj_features.overrides.order.sync_sales_order",
    "ecommerce_integrations.shopify.order.create_order": "nj_features.overrides.order.create_order",
    "ecommerce_integrations.shopify.order.create_sales_order": "nj_features.overrides.order.create_sales_order",
    "ecommerce_integrations.shopify.product.get_item_code": "nj_features.overrides.product.get_item_code",
    "ecommerce_integrations.shopify.product.create_items_if_not_exist": "nj_features.overrides.product.create_items_if_not_exist",
    "erpnext.regional.india.e_invoice.utils.make_einvoice": "nj_features.overrides.sales_invoice.custom_make_einvoice",
    "erpnext.controllers.accounts_controller.validate_einvoice_fields": "nj_features.overrides.sales_invoice.validate_einvoice_fields",
}

# ========== Scheduled Tasks ==========

scheduler_events = {
    "cron": {
        # DAILY AT 10:00 PM (22:00)
        # Runs daily non-compliance and daily report check
        "0 22 * * *": [
            "nj_features.nj_features.doctype.daily_individual_report.daily_individual_report.daily_report_not_submitted_warehouses_data",
            "njcompliance.nj_compliance.doctype.nj_non_compliance.nj_non_compliance.raise_nc_undone_daily_individual_report",
            "nj_features.nj_features.doctype.productivity.productivity.fetch_productivity_data",
        ],

        # DAILY AT 7:45 AM
        # Employee experience table update
        "45 7 * * *": [
            "nj_features.overrides.employee.update_employee_experience_table",
        ],

        # EVERY HOUR AT MINUTE 1
        # Product bundle quantity sync
        "1 * * * *": [
            "nj_features.overrides.product_bundle.update_product_bundle_quantities",
        ],
        "59 10 * * *": [
            "nj_features.nj_features.doctype.department_change_log.department_change_log.update_department_change_logs",
        ],

        # EVERY HOUR AT MINUTE 10
        # Department details + dispatch ETA updater
        "10 * * * *": [
            "nj_features.nj_features.doctype.nj_production_planning.nj_production_planning.get_department_details",
            "nj_features.overrides.sales_order.calculate_dispatch_eta_for_sales_order",
        ],

        # EVERY HOUR AT MINUTE 0
        # Shopify: fetch and stage
        # Production Planning: RUN EVERY 1 HOUR
        "0 * * * *": [
            "nj_features.nj_features.api.shopify_inventory.fetch_and_stage_inventory_sync",
            "nj_features.nj_features.doctype.nj_production_planning.nj_production_planning.nj_run_unified_production_plan",
        ],

        # EVERY HOUR AT MINUTES 20 & 40
        # Shopify: start sync
        "20,40 * * * *": [
            "nj_features.nj_features.api.shopify_inventory.start_shopify_inventory_sync",
        ],

        # EVERY 58 MINUTES
        # AWB tracking
        "*/58 * * * *": [
            "nj_features.nj_features.doctype.delivery_charges.delivery_charges.awb_number_tracking_status",
        ],
         "0 */2 * * *": [
            "nj_features.nj_features.doctype.delivery_charges.delivery_charges.criticalog_awb_number_tracking_status"

        ],

        # EVERY 59 MINUTES
        # Update Shopify status
        "*/59 * * * *": [
            "nj_features.nj_features.doctype.delivery_charges.delivery_charges.update_status_in_shopify",
        ],

        # EVERY 2 HOURS (AT MINUTE 0)
        # SLA department updater
        "0 */2 * * *": [
            "nj_features.nj_features.doctype.so_quantity_check.so_quantity_check.updting_sla_department",
        ],
    }
}

# ========== User Data Protection ==========

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
        "doctype": "{doctype_4}",
    },
]
