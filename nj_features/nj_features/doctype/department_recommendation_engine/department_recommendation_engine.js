frappe.ui.form.on('Department Recommendation Engine', {
    refresh: function(frm) {
        // Add Test Rule button
        if (!frm.doc.__islocal && frm.doc.enabled) {
            frm.add_custom_button(__('Test Rule'), function() {
                test_recommendation_rule(frm);
            });
        }
        
        // Add Bulk Apply button  
        if (!frm.doc.__islocal && frm.doc.enabled) {
            frm.add_custom_button(__('Bulk Apply'), function() {
                bulk_apply_rules(frm);
            });
        }
        
        // Set field descriptions
        frm.set_df_property('python_condition', 'description', 
            'Python condition using "doc" object. Example: doc.docstatus == 1 and doc.total > 1000');
        
        frm.set_df_property('python_action', 'description', 
            'Python code to execute. Available functions: execute_query_and_update(), update_serial_no_warehouse(), update_document_field()');
    },
    
    document_type: function(frm) {
        if (frm.doc.document_type) {
            // Set default condition
            if (!frm.doc.python_condition) {
                frm.set_value('python_condition', 'doc.docstatus == 1');
            }
        }
    }
});

function test_recommendation_rule(frm) {
    if (!frm.doc.document_type) {
        frappe.msgprint(__('Please select a Document Type first'));
        return;
    }
    
    frappe.prompt([
        {
            label: 'Document Name',
            fieldname: 'doc_name',
            fieldtype: 'Dynamic Link',
            options: 'document_type',
            reqd: 1
        }
    ], function(values) {
        frappe.call({
            method: 'your_app.department_recommendation_engine.test_recommendation_rule',
            args: {
                rule_name: frm.doc.name,
                doc_name: values.doc_name,
                doc_type: frm.doc.document_type
            },
            callback: function(r) {
                if (r.message) {
                    frappe.msgprint(r.message);
                }
            }
        });
    }, __('Test Recommendation Rule'));
}

function bulk_apply_rules(frm) {
    frappe.prompt([
        {
            label: 'Select Documents',
            fieldname: 'documents',
            fieldtype: 'MultiSelectList',
            get_data: function(txt) {
                return frappe.db.get_link_options(frm.doc.document_type, txt);
            },
            reqd: 1
        }
    ], function(values) {
        frappe.call({
            method: 'nj_features.nj_features.doctype.department_recommendation_engine.department_recommendation_engine.bulk_apply',
            args: {
                doctype: frm.doc.document_type,
                docnames: values.documents
            },
            callback: function(r) {
                frappe.msgprint(__('Recommendation rules applied to selected documents'));
            }
        });
    }, __('Bulk Apply Recommendation Rules'));
}