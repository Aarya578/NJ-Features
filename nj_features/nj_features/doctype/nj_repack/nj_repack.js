frappe.ui.form.on("NJ Repack", {
  refresh: function (frm) {
    setTimeout(() => {
      show_checkbutton_for_field(frm, "repack_attributes");
    }, 1000);
  },
  scan_barcode: function (frm) {
    if (!frm.doc.scan_barcode) {
      return;
    }

    frappe.call({
      method:
        "nj_features.nj_features.api.api_files.search_for_serial_or_batch_or_barcode_no",

      args: {
        search_value: frm.doc.scan_barcode,
        raise_exp: 1,
      },

      callback: function (r) {
        if (r.message && r.message.serial_no) {
          frappe.db
            .get_value("Serial No", r.message.serial_no, ["item_code"])
            .then((res) => {
              let item_code = res.message.item_code;

              frappe.db
                .get_value("Item", item_code, "item_group")
                .then((item_res) => {
                  let item_group = item_res.message.item_group;

                  frappe.db
                    .get_value("Item Group", item_group, "is_component")
                    .then((group_res) => {
                      if (!group_res.message.is_component) {
                        frappe.msgprint({
                          title: "Repack Not Allowed",
                          message:
                            "Repack is allowed only for Component Items.<br><br>" +
                            "<b>Item Code:</b> " +
                            item_code +
                            "<br><b>Item Group:</b> " +
                            item_group,
                          indicator: "red",
                        });

                        frm.set_value("scan_barcode", "");
                        frm.set_value("serial_no", "");

                        return;
                      }

                      // Component item allowed
                      frm.set_value("serial_no", r.message.serial_no);
                    });
                });
            });
        } else {
          frappe.msgprint("Serial No not found for scanned barcode");

          frm.set_value("serial_no", "");
        }
      },
    });
  },
  serial_no: function (frm) {
    // Clear everything if Serial No is removed
    if (!frm.doc.serial_no) {
      clear_repack_data(frm);
      return;
    }

    // 1. Get Item Code from Serial No
    frappe.call({
      method: "frappe.client.get_value",
      args: {
        doctype: "Serial No",
        filters: {
          name: frm.doc.serial_no,
        },
        fieldname: ["item_code"],
      },
      callback: function (r) {
        if (!r.message || !r.message.item_code) {
          clear_repack_data(frm);

          frappe.msgprint(
            "Item Code not found for Serial No: " + frm.doc.serial_no,
          );
          return;
        }

        let item_code = r.message.item_code;

        // 2. Get Item details
        frappe.call({
          method: "frappe.client.get",
          args: {
            doctype: "Item",
            name: item_code,
          },
          callback: function (item_response) {
            if (!item_response.message) {
              clear_repack_data(frm);
              return;
            }

            let item = item_response.message;

            // 3. Check Item Group -> is_component
            frappe.call({
              method: "frappe.client.get_value",
              args: {
                doctype: "Item Group",
                filters: {
                  name: item.item_group,
                },
                fieldname: ["is_component"],
              },
              callback: function (group_response) {
                let is_component =
                  group_response.message && group_response.message.is_component;

                // NOT COMPONENT -> BLOCK
                if (!is_component) {
                  clear_repack_data(frm);

                  frappe.msgprint({
                    title: "Repack Not Allowed",
                    indicator: "red",
                    message:
                      "Repack is allowed only for Component Items.<br><br>" +
                      "<b>Item Code:</b> " +
                      item_code +
                      "<br>" +
                      "<b>Item Group:</b> " +
                      item.item_group,
                  });

                  return;
                }

                // COMPONENT -> ALLOW
                frm.set_value("current_item_code", item_code);

                // Clear previous rows
                frm.clear_table("current_attributes");
                frm.clear_table("repack_attributes");

                // Fill Current Item Attributes
                (item.attributes || []).forEach(function (attr) {
                  let current_row = frm.add_child("current_attributes");

                  current_row.variant_of = item.variant_of;
                  current_row.attribute = attr.attribute;
                  current_row.attribute_value = attr.attribute_value;
                });

                // Add Repack Attribute row
                let row = frm.add_child("repack_attributes");

                row.serial_no = frm.doc.serial_no;
                row.current_item_code = item_code;

                // Refresh
                frm.refresh_field("current_attributes");
                frm.refresh_field("repack_attributes");

                setTimeout(() => {
                  show_checkbutton_for_field(frm, "repack_attributes");
                }, 500);
              },
            });
          },
        });
      },
    });
  },
});

frappe.ui.form.on("NJ Repack Attribute", {
  check_button: function (frm, cdt, cdn) {
    let row = locals[cdt][cdn];

    if (!row.current_item_code) {
      frappe.msgprint({
        title: "Missing Data",
        indicator: "red",
        message: "Current Item Code is missing",
      });
      return;
    }

    frappe.call({
      method: "frappe.client.get",

      args: {
        doctype: "Item",
        name: row.current_item_code,
      },

      callback: function (r) {
        if (!r.message) {
          frappe.msgprint("Unable to fetch Item");
          return;
        }

        let item = r.message;

        let fields = [];

        (item.attributes || []).forEach(function (attr) {
          fields.push({
            label: attr.attribute,

            fieldname: frappe.scrub(attr.attribute),

            fieldtype: "Select",

            options: ["Loading..."],

            default: attr.attribute_value,
          });
        });

        let promises = fields.map(function (field) {
          return new Promise(function (resolve) {
            frappe.call({
              method:
                "nj_features.nj_features.doctype.njqca.njqca.get_variant_attribute_options",

              args: {
                item_template: item.variant_of,
                attribute: field.label,
              },

              callback: function (r) {
                field.options = [...new Set(r.message || [])];

                resolve();
              },

              error: function (err) {
                console.error("Error loading options for", field.label, err);

                field.options = [];

                resolve();
              },
            });
          });
        });

        Promise.all(promises).then(function () {
          let d = new frappe.ui.Dialog({
            title: __("Create Variant"),
            fields: fields,
          });
          d.show();
          d.set_primary_action(__("Create"), function () {
            let values = d.get_values();

            if (!values) {
              return;
            }
            let attributes = [];

            Object.keys(values).forEach(function (key) {
              if (!values[key]) {
                return;
              }

              let field = fields.find((f) => f.fieldname == key);

              if (!field) return;

              attributes.push({
                attribute: field.label,
                attribute_value: values[key],
              });
            });

            frappe.call({
              method:
                "nj_features.nj_features.doctype.njqca.njqca.get_variant_from_value",

              args: {
                item_template: item.variant_of,
                args: JSON.stringify(
                  attributes.map((a) => ({
                    [a.attribute]: a.attribute_value,
                  })),
                ),
              },

              callback: function (r) {
                if (r.message) {
                  let repack_item_code = r.message;

                  frappe.db
                    .exists("Item", repack_item_code)
                    .then(function (exists) {
                      if (!exists) {
                        frappe.msgprint({
                          title: "Invalid Repack Item",
                          indicator: "red",
                          message:
                            "Repack Item Code not found:<br><b>" +
                            repack_item_code +
                            "</b><br><br>Please contact NPD team for item creation.",
                        });

                        return;
                      }

                      frappe.model.set_value(
                        cdt,
                        cdn,
                        "repack_item_code",
                        repack_item_code,
                      );

                      frappe.model.set_value(
                        cdt,
                        cdn,
                        "remark",
                        "Changed from " +
                          row.current_item_code +
                          " to " +
                          repack_item_code,
                      );

                      frm.refresh_field("repack_attributes");

                      frappe.msgprint({
                        title: "Success",
                        indicator: "green",
                        message:
                          "Repack Item Generated: <b>" +
                          repack_item_code +
                          "</b>",
                      });
                      d.hide();
                    });
                } else {
                  let selected_attributes = attributes
                    .map(function (a) {
                      return "<b>" + a.attribute + ":</b> " + a.attribute_value;
                    })
                    .join("<br>");

                  frappe.msgprint({
                    title: "Repack Item Not Found",
                    indicator: "red",
                    message:
                      "Repack Item not found for selected attributes.<br><br>" +
                      "<b>Selected Attributes:</b><br>" +
                      selected_attributes +
                      "<br><br>" +
                      "Please contact <b>NPD team</b> for item creation.",
                  });
                }
              },
              error: function (err) {
                console.error(err);

                frappe.msgprint({
                  title: "Repack Failed",
                  indicator: "red",
                  message: "Unable to generate Repack Item",
                });
              },
            });
          });
        });
      },
    });
  },
});

frappe.ui.form.on("NJ Repack Attribute", {
  repack_attributes_add: function (frm) {
    setTimeout(() => {
      show_checkbutton_for_field(frm, "repack_attributes");
    }, 300);
  },
});

function clear_repack_data(frm) {
  frm.set_value("current_item_code", "");

  frm.clear_table("current_attributes");
  frm.clear_table("repack_attributes");

  frm.refresh_field("current_attributes");
  frm.refresh_field("repack_attributes");
}

function show_checkbutton_for_field(frm, fieldname) {
  const field = frm.fields_dict[fieldname];

  if (!field || !field.$wrapper) return;

  field.$wrapper.find(".grid-body .rows .grid-row").each(function (i, item) {
    let $row = $(item);

    let $checkButtonCell = $row.find('[data-fieldname="check_button"]');

    $checkButtonCell.empty();

    $checkButtonCell.css({
      display: "flex",
      "justify-content": "center",
      "align-items": "center",
      padding: "0",
    });

    $checkButtonCell.append(
      `<button class="btn btn-primary btn-xs check-button"
                style="
                    padding: 2px 10px;
                    font-size: 12px;
                    line-height: 1.5;
                    border-radius: 3px;
                    background-color: #589ffc;
                    border: none;
                    width: auto;
                    min-width: 50px;">
                Check
            </button>`,
    );

    $checkButtonCell
      .find(".check-button")
      .off("click.nj_repack")
      .on("click.nj_repack", function (e) {
        e.preventDefault();
        e.stopPropagation();

        let cdn = $row.attr("data-name");
        let cdt = field.grid.doctype;

        frm.script_manager.trigger("check_button", cdt, cdn);
      });
  });
}
