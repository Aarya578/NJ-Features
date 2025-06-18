frappe.listview_settings['Sales Invoice'] = {
  refresh: function(listview) {
    listview.page.add_inner_button('Set Approval', () => {
      let selected = listview.get_checked_items();

      if (!selected.length) {
        frappe.msgprint(__('Please select at least one Sales Invoice.'));
        return;
      }

      const selected_count = selected.length;

      frappe.prompt([
        {
          label: 'Approved?',
          fieldname: 'approved',
          fieldtype: 'Check',
          default: 1
        }
      ], (values) => {
        const names = selected.map(item => item.name);

        frappe.call({
          method: 'nj_features.overrides.sales_invoice.custom_bulk_update_approved',
          args: {
            names: names,
            approved_value: values.approved ? 1 : 0
          },
          callback: function(r) {
            frappe.msgprint(`${r.message.updated} invoice(s) updated.`);
            listview.refresh();
          }
        });
      }, 'Set Approved Value', `Update (${selected_count} selected)`);
    });
  }
};

