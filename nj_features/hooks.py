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
    "Quality Procedure": "public/js/quality_procedure.js",
    "Quality Review": "public/js/quality_review.js",
    "Product Bundle": "public/js/product_bundle.js",
    "Address": "public/js/address.js",
    "Sales Order": "public/js/sales_order.js",
    "Quotation": "public/js/quotation.js",
    "Request for Quotation": "public/js/request_for_quotation.js",
    "Purchase Invoice": "public/js/purchase_invoice_override.js",
    "Purchase Receipt": "public/js/purchase_receipt.js",
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
    "Request for Quotation": "nj_features.overrides.request_for_quotation.CustomRequestForQuotation",
    "Scheduled Job Log": "nj_features.overrides.scheduled_job_log.CustomScheduledJobLog",
    # "Journal Entry": "nj_features.overrides.journal_entry.CustomJournalEntry",
    "Purchase Invoice": "nj_features.overrides.purchase_invoice.CustomPurchaseInvoice",
}

# ========== Doc Events ==========

doc_events = {
    # "Item": {
    #     "after_insert": "nj_features.overrides.product.upload_erpnext_item",
    #     "on_update": "nj_features.overrides.product.upload_erpnext_item",
    # },
    "Purchase Receipt": {
        "before_save": "nj_features.overrides.purchase_receipt.generate_batch_no",
        "on_submit": "nj_features.overrides.purchase_receipt.get_batch",
        # "validate": "nj_features.overrides.purchase_receipt.mr_raise_from_pr",
    },
    "Purchase Order": {
        "before_save": "nj_features.overrides.purchase_order.restore_manual_conversion_on_po",
        "validate": "nj_features.overrides.purchase_order.validate_mandatory_links",
        "on_submit": [
            "nj_features.overrides.purchase_order.validate_warranty_on_submit",
            "nj_features.overrides.purchase_order.create_pr_on_submit",
        ],
    },
    "NJQCA": {
        "onload": "nj_features.nj_features.api.api_files.get_backup_duration",
        "before_submit":[
            "nj_features.nj_features.api.api_files.get_backup_duration",
            "nj_features.nj_features.doctype.njqca.njqca.previous_njqca_failed_result_validation",
        ] ,
    },
    # Blocks a Serial No from being saved if it would push the count
    # of Serial Nos against its (rfq_id, item_code) combination past
    # that RFQ Item line's qty. Runs alongside nj_p1_features's
    # CustomSerialNo.validate() (override_doctype_class), not instead
    # of it -- doc_events and class overrides are complementary, not
    # exclusive, so this doesn't touch or conflict with that app's own
    # BIOS-uniqueness checks there.
    "Serial No": {
        "validate": "nj_features.overrides.serial_no.validate_rfq_qty",
    },
    "NJ Quality Inspection": {
        "on_update": "nj_features.nj_features.doctype.department_recommendation_engine.department_recommendation_engine.apply_recommendation_rules",
        "on_submit": "nj_features.nj_features.doctype.department_recommendation_engine.department_recommendation_engine.apply_recommendation_rules",
        "on_update_after_submit": "nj_features.nj_features.doctype.department_recommendation_engine.department_recommendation_engine.apply_recommendation_rules",
    },
    "Sales Invoice": {
        "before_save": [
            "nj_features.overrides.sales_invoice.approve_validation",
            "nj_features.overrides.sales_invoice.deviding_tax_chargese",
            "nj_features.overrides.sales_invoice.add_missing_sales_order_tax_accounts",
        ],
        # "on_submit": [
        #     "nj_features.overrides.sales_invoice.send_invoice_email",
        # ],
    },
    "Laptop Box": {
        "before_save": "nj_features.nj_features.doctype.laptop_box.laptop_box.printing_barcode"
    },
    "Delivery Note": {
        "before_save": [
            "nj_features.overrides.delivery_note.deviding_tax_chargese_dn",
            "nj_features.overrides.delivery_note.deviding_tax_chargese_return_dn",
        ],
        # "before_save": [
        #     "nj_features.overrides.delivery_note.deviding_tax_chargese"
        # ],
        "on_update": [
            "nj_features.overrides.delivery_note.set_cod_details_critical"
        ]
    },
    "Employee": {
        "on_update": "nj_features.overrides.employee.update_item_group_and_max_qty_in_warehouse",
        "before_save": "nj_features.overrides.employee.updating_time_stamp",
    },
    # "Journal Entry": {
    #     "before_save": "nj_features.overrides.journal_entry.duplicate_jv_validation"
    # },
    "Purchase Invoice": {
        "on_submit": [
            "nj_features.overrides.purchase_invoice.on_submit_purchase_invoice",
            # "nj_features.overrides.purchase_invoice.send_invoice_email",
        ],
    },
    # =========================================================
    # 🔹 Targeted Inventory Sync on Sales Order Submission
    # =========================================================
    "Sales Order": {
        "on_submit": "nj_features.nj_features.api.shopify_inventory_targeted.trigger_inventory_sync_from_sales_order",
    },
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
    "frappe.desk.reportview.get_sidebar_stats": "nj_features.overrides.reportview.get_sidebar_stats",
}


# ========== Scheduled Tasks ==========

scheduler_events = {
    "cron": {
        "0 22 * * *": [
            "nj_features.nj_features.doctype.daily_individual_report.daily_individual_report.daily_report_not_submitted_warehouses_data",
            "njcompliance.nj_compliance.doctype.nj_non_compliance.nj_non_compliance.raise_nc_undone_daily_individual_report",
            "nj_features.nj_features.doctype.productivity.productivity.fetch_productivity_data",
        ],

        "45 7 * * *": [
            "nj_features.overrides.employee.update_employee_experience_table",
        ],

        "45 8 * * *": [
            "nj_features.overrides.employee.update_skill_experiance_table",
        ],

        "1 * * * *": [
            "nj_features.overrides.product_bundle.update_product_bundle_quantities",
        ],

        "2 * * * *": [
            "nj_features.overrides.product_bundle.update_zero_quantity_product_bundles",
        ],

        "45 9 * * *": [
            "nj_features.nj_features.doctype.department_change_log.department_change_log.update_department_change_logs",
        ],

        "05 10 * * *": [
            "nj_features.nj_features.doctype.department_change_log.department_change_log.update_department_change_logs",
        ],

        "25 10 * * *": [
            "nj_features.nj_features.doctype.department_change_log.department_change_log.update_department_change_logs",
        ],

        "10 * * * *": [
            "nj_features.nj_features.doctype.nj_production_planning.nj_production_planning.get_department_details",
            "nj_features.overrides.sales_order.calculate_dispatch_eta_for_sales_order",
        ],

        # Runs every hour
        "0 * * * *": [
            "nj_features.nj_features.api.shopify_inventory.fetch_and_stage_inventory_sync",
        ],

        # Runs every 12 hours: 12 AM and 12 PM server time
        "0 */12 * * *": [
            "nj_features.nj_features.doctype.nj_production_planning.nj_production_planning.enqueue_unified_production_plan",
        ],

        "20,40 * * * *": [
            "nj_features.nj_features.api.shopify_inventory.start_shopify_inventory_sync",
            # nj_features.nj_features.api.shopify_inventory.create_shopify_inventory_sync
        ],

        "*/58 * * * *": [
            "nj_features.nj_features.doctype.delivery_charges.delivery_charges.awb_number_tracking_status",
        ],

        "0 */2 * * *": [
            "nj_features.nj_features.doctype.delivery_charges.delivery_charges.criticalog_awb_number_tracking_status",
        ],

        "*/59 * * * *": [
            "nj_features.nj_features.doctype.delivery_charges.delivery_charges.update_status_in_shopify",
        ],
        "25 23 * * *": [
            "nj_features.nj_features.doctype.nj_production_planning.nj_production_planning.mr_raise_from_priduction_plan",
        ],
        "35 23 * * *": [
            "nj_features.nj_features.doctype.nj_production_planning.nj_production_planning.mr_raise_for_laptop_adaptors",
        ],

        "55 23 * * *": [
            "nj_features.nj_features.doctype.nj_production_planning.nj_production_planning.collect_all_purpose_material_issue",
        ],
        "30 23 * * *": [
            "nj_features.nj_features.doctype.nj_production_planning.nj_production_planning.cosumables_material_issue_mr",
        ],    
        "40 23 * * *":[
            "nj_features.nj_features.doctype.nj_production_planning.nj_production_planning.laptop_ram_mr_via_production_plan",
        ],

        "45 23 * * *": [
            "nj_features.nj_features.doctype.nj_production_planning.nj_production_planning.laptop_storage_mr_via_production_plan",
        ],

        "50 23 * * *": [
            "nj_features.overrides.product_bundle.update_variant_status",
        ],
        "40 21 * * *":[
            "nj_features.nj_features.doctype.auto_rfq_creation.auto_rfq_creation.auto_rfq_creation",

        ],
    }
}
# ========== Fixtures ==========
# Workflow fixtures removed — approval flow handled via custom Python methods
fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["name", "=", "Product Bundle-disable"]]
    },
    {
        "dt": "Custom Field",
        "filters": [["name", "=", "Department-expense_credit_account"]]
    }
]

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
