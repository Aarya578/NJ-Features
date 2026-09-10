// Copyright (c) 2023, NewJaisa - IT Team and contributors
// For license information, please see license.txt

const genScoreMap = {
  "CORE I3": 0.1,
  "CORE I4": 0.2,
  "CORE I5": 0.3,
  "CORE I7": 0.4,
  "CORE I8": 0.5,
  "CORE I9": 0.6,
  "CORE I10": 0.7,
  "CORE I11": 0.8,
  "CELERON(R) CPU": 0.9,
  "DUAL-CORE CPU": 0.1,
  "ATOM X5 CPU": 0.11,
  "XEON(R) E": 0.12,
  "PRO A10": 0.13,
  "GEN INTEL(R)": 0.14,
  "RYZEN 5": 0.15,
  "A8 PRO": 0.16,
  "A10 PRO": 0.17,
  "A6-6310 APU": 0.18,
  "RYZEN 7": 0.19,
  "A6-9225 RADEON": 0.2,
  "PENTIUM(R) CPU": 0.21,
  "PRO A6": 0.22,
  "A10-5750M APU": 0.23,
  "A6-7310 APU": 0.24,
};

const brandScoreMap = {
  Lenovo: 1,
  HP: 2,
  Dell: 3,
};

frappe.ui.form.on("NJQCA", {
  change_model: function (frm) {
    openChangeModelDialog(frm);
  },

  onload: function (frm) {
    if (frm.doc.manufacturer_model && frm.doc.docstatus == 0) {
      frappe.call({
        method: "nj_features.nj_features.doctype.njqca.njqca.get_sudden_drop",
        args: {
          parent_name: frm.doc.name,
          item_group: frm.doc.item_group,
          manufacturer_model: frm.doc.manufacturer_model,
        },
        callback: function (r) {
          if (r.message) {
            frm.set_value("sudden_drop", r.message);
            frm.refresh_field("sudden_drop");
          }
        },
      });
    }

    if (frm.doc.docstatus === 0 && frm.doc.item_group == "Laptops") {
      frappe.call({
        method:
          "nj_features.nj_features.doctype.njqca.njqca.get_item_group_mapping",
        args: { parent: frm.doc.name },
        callback: function (r) {
          if (r.message && Array.isArray(r.message)) {
            r.message.forEach((row) => {
              const score =
                genScoreMap[row.variant_6?.trim()?.toUpperCase()] || 0;

              frm.add_child("njqca_result_parameters", {
                parameter: "laptop_gen",
                value: row.variant_6,
                item_group: "BODY C",
                score: score,
              });
            });
            frm.refresh_field("njqca_result_parameters");
          }

          const brand = frm.doc.brand;
          const brandScore = brandScoreMap[brand];

          if (brandScore) {
            frm.add_child("njqca_result_parameters", {
              parameter: "Brand",
              value: brand,
              item_group: "BODY C",
              score: brandScore,
            });
            frm.refresh_field("njqca_result_parameters");
          }
        },
      });
    }
  },

  refresh: function (frm) {
    resetNJQCATransferPromptState(frm);
    promptNJQCATransferForCreatedUser(frm);
    triggerNJQCAWarehouseValidationForDifferentWarehouse(frm);

    $(".col-lg-2.layout-side-section").hide();
    $(frm.layout.wrapper).find(".form-message.red").remove();
    frm.set_value("merged_ram_item_code", 0);
    frm.set_value("merged_storage_item_code", 0);
    frm.refresh_field("merged_ram_item_code");
    frm.refresh_field("merged_storage_item_code");
    frm.set_df_property("njqca_item_component", "cannot_add_rows", true);
    frm.set_df_property("njqca_item_component", "cannot_delete_rows", true);
    frm.set_df_property("njqca_laptop_processors", "cannot_delete_rows", true);
    frm.set_df_property("njqca_laptop_ram", "cannot_delete_rows", true);
    frm.set_df_property("njqca_laptop_storage", "cannot_delete_rows", true);
    frm.set_df_property("njqca_laptop_processors", "cannot_add_rows", true);
    frm.set_df_property("njqca_result_parameters", "cannot_add_rows", true);
    frm.refresh_field("njqca_item_component");
    frm.refresh_field("njqca_result_parameters");

    if (frm.doc.docstatus == 0) {
      console.log("Document is in draft state.", frm.doc.serial_no);
      if (!frm.doc.serial_no) {
        console.log("New document loaded, skipping serial no trigger.");
        trigger_serial_no(frm);
      }
      applyDesktopFieldState(frm);
      if (!isDesktopNJQCA(frm.doc)) {
        syncDesktopManufacturerModelFlow(frm);
      }
      frm.events.power_on();
      handleScannerInput(frm, "serial_no");
      setupNJQCABarcodeScannerOnly(frm);
      show_checkbutton_for_field(frm, "njqca_laptop_processors");
      show_checkbutton_for_field(frm, "njqca_laptop_ram");
      show_checkbutton_for_field(frm, "njqca_laptop_storage");

      frm.set_query("inspection_type", () => {
        return {
          query:
            "nj_features.nj_features.doctype.njqca.njqca.get_inspection_types_for_user",
        };
      });

      frm.set_query("rfq_id", () => {
        return { filters: { docstatus: 1 } };
      });

      frm.set_query("manual_repack_item_code", function () {
        var filters = {
          disabled: 0,
          has_variants: 0,
          end_of_life: [">", frappe.datetime.get_today()],
          brand: frm.doc.brand,
          item_group: frm.doc.item_group,
        };

        if (frm.doc.model) {
          filters.item_model = frm.doc.model;
        }
        if (frm.doc.item_template) {
          filters.variant_of = frm.doc.item_template;
        }

        return { filters: filters };
      });

      frm.set_query(
        "part_item_code",
        "njqca_item_component",
        function (doc, cdt, cdn) {
          const row = locals[cdt][cdn];
          return {
            filters: {
              item_group: row.item_group,
              disabled: 0,
              has_variants: 0,
            },
          };
        },
      );

      frm.set_query(
        "calculated_item_code",
        "njqca_laptop_processors",
        function (doc, cdt, cdn) {
          const row = locals[cdt][cdn];
          return {
            filters: {
              item_group: row.item_group,
              disabled: 0,
              has_variants: 0,
            },
          };
        },
      );

      frm.set_query(
        "calculated_item_code",
        "njqca_laptop_ram",
        function (doc, cdt, cdn) {
          const row = locals[cdt][cdn];
          return {
            filters: {
              item_group: row.item_group,
              disabled: 0,
              has_variants: 0,
            },
          };
        },
      );

      frm.set_query(
        "calculated_item_code",
        "njqca_laptop_storage",
        function (doc, cdt, cdn) {
          const row = locals[cdt][cdn];
          return {
            filters: {
              item_group: row.item_group,
              disabled: 0,
              has_variants: 0,
            },
          };
        },
      );

      if (
        !frappe.user.has_role("Ops Manager") &&
        frm.doc.item_group == "Laptops"
      ) {
        frm.set_df_property("manual_repack_item_code", "read_only", 1);
        let $fieldWrapper = frm.fields_dict["manual_repack_item_code"].$wrapper;

        $fieldWrapper.find("input").attr("disabled", true);

        let $inputArea = $fieldWrapper.find(".control-input");
        $inputArea.css("position", "relative");

        let fogOverlay = $(`
					<div class="fog-overlay" style="
						position: absolute;
						top: 0; left: 0;
						width: 100%; height: 100%;
						background: rgba(255, 255, 255, 0.3);
						z-index: 5;
						border-radius: 4px;
						pointer-events: none;">
					</div>
				`);
        $inputArea.append(fogOverlay);

        let lockIcon = $(`
					<i class="fa fa-lock" style="
						position: absolute;
						right: 10px; top: 50%;
						transform: translateY(-50%);
						font-size: 16px;
						color: #fff;
						z-index: 6;">
					</i>
				`);
        $inputArea.append(lockIcon);
      }
    }
  },

  onload_post_render: async function (frm) {
    if (frm.doc.docstatus == 0) {
      if (!frm.doc.manual_repack_item_code && frm.doc.item_code) {
        frm.set_value("manual_repack_item_code", frm.doc.item_code);
        frm.refresh_field("manual_repack_item_code");
      }

      if (!frm.doc.inspection_type) {
        await frappe.call({
          method:
            "nj_features.nj_features.doctype.njqca.njqca.get_inspection_type",
          callback: function (r) {
            frm.set_value("inspection_type", r.message);
            cur_frm.refresh_field("inspection_type");
          },
        });
      }

      if (frm.doc.inspection_type && frm.doc.item_group == "BATTERY") {
        frappe.call({
          method:
            "nj_features.nj_features.doctype.njqca.njqca.get_battery_serialno",
          args: {
            bios_serial_no: frm.doc.bios_serialno,
            inspection_type: frm.doc.inspection_type,
            creation_date: frm.doc.creation,
          },
          callback: function (r) {
            if (r.message) {
              frm.set_value("component_serial_no", r.message);
              frm.refresh_field("component_serial_no");
            }
          },
        });
      }

      if (!frm.doc.__islocal) {
        njqca.get_model(
          isDesktopNJQCA(frm.doc) ? null : frm.doc.manufacturer_model,
          frm.doc.item_group,
          frm.doc.brand,
          frm.doc.njqca_item_component,
        );
      }

      setup_merge_checkbox_handler(frm, "njqca_laptop_processors");
      setup_merge_checkbox_handler(frm, "njqca_laptop_ram");
      setup_merge_checkbox_handler(frm, "njqca_laptop_storage");
    }
  },

  validate: async function (frm) {
    (frm.doc.njqca_laptop_ram || []).forEach((row) => {
      delete row._item_templates;
    });
    (frm.doc.njqca_laptop_storage || []).forEach((row) => {
      delete row._item_templates;
    });

    if (
      frm.doc.manual_repack_item_code &&
      frm.doc.manual_repack_item_code !== frm.doc.repack_item_code
    ) {
      console.log(
        "Manual repack item code does not match automated item code. Clearing related fields.",
      );
      frm.set_value("merged_ram_item_code", 0);
      frm.set_value("merged_storage_item_code", 0);
      frm.refresh_field("merged_ram_item_code");
      frm.refresh_field("merged_storage_item_code");
      // processItemTemplate(frm);
    }
    var selectedModel = frm.doc.model;
    var selectedBrand = frm.doc.brand;
    var selectedItemGroup = frm.doc.item_group;

    if (frm.doc.item_code != "" && frm.doc.rfq_id && !frm.doc.serial_no) {
      await frappe.call({
        method: "nj_features.nj_features.api.qr_code.create_serial_no",
        args: { item_code: frm.doc.item_code, rfq: true },
        callback: function (r) {
          if (r.message) {
            frm.set_value("serial_no", r.message);
            frm.refresh_field("serial_no");
          }
        },
      });
    }

    if (frm.doc.rfq_id && frm.doc.serial_no) {
      frappe.call({
        method:
          "nj_features.nj_features.doctype.njqca.njqca.create_serial_no_based_on_rfq",
        args: { serial_info: frm.doc },
        callback: function (r) {
          if (r.message) {
            console.log(r.message);
          }
        },
      });
    }
    if (frm.doc.item_group == "Laptop Adaptors" && frm.doc.serial_no) {
      frappe.call({
        method:
          "nj_features.nj_features.doctype.njqca.njqca.adaptor_charge_gain_status",
        args: { njqca_name: frm.doc.name, serial_no: frm.doc.serial_no },
        callback: function (r) {
          if (r.message) {
            let newRow = frappe.model.add_child(
              frm.doc,
              "njqca_result_parameters",
            );
            if (r.message == "Pass") {
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "parameter",
                "Adapterbattery_status",
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "value",
                r.message,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "item_group",
                "Laptop Adaptors",
              );
              frappe.model.set_value(newRow.doctype, newRow.name, "score", "0");
            } else {
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "parameter",
                "Adapterbattery_status",
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "value",
                r.message,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "item_group",
                "Laptop Adaptors",
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "score",
                "41",
              );
            }
          }
        },
      });
    }

    if (selectedItemGroup == "BATTERY") {
      frappe.call({
        method:
          "nj_features.nj_features.doctype.njqca.njqca.get_avg_discharge_rate",
        args: { njqca_name: frm.doc.name },
        callback: function (r) {
          if (r.message) {
            frm.set_value("average_discharge_rate", r.message);
            frm.refresh_field("average_discharge_rate");
          }
        },
      });
    }

    if (
      frm.doc.item_group == "Laptops" &&
      frm.doc.serial_no &&
      frm.doc.bios_serialno != "" &&
      frm.doc.manufacturer_model &&
      frm.doc.name &&
      !frm.doc.rfq_id
    ) {
      let inspection_type_data = await frappe.db.get_value(
        "NJ Settings",
        { parameter: "battry_unknown_grade_inspection_types" },
        "value",
      );
      let inspection_type = inspection_type_data?.message?.value || "";
      let inspection_types = inspection_type.split(",").map((s) => s.trim());
      frappe.call({
        method: "nj_features.nj_features.api.api_files.get_battery_status",
        args: {
          serial_no: frm.doc.serial_no,
          bios_serialno: frm.doc.bios_serialno,
          njqca_name: frm.doc.name,
          manufacturer_model: frm.doc.manufacturer_model,
        },
        freeze: true,
        freeze_message: __("Checking battery status..."),
        callback: function (r) {
          if (r.message && inspection_types.includes(frm.doc.inspection_type)) {
            let newRow = frappe.model.add_child(
              frm.doc,
              "njqca_result_parameters",
            );

            frappe.model.set_value(
              newRow.doctype,
              newRow.name,
              "parameter",
              "Battery_status_1",
            );
            frappe.model.set_value(
              newRow.doctype,
              newRow.name,
              "value",
              r.message,
            );
            frappe.model.set_value(
              newRow.doctype,
              newRow.name,
              "item_group",
              "BATTERY",
            );

            if (r.message === "PASS") {
              frappe.model.set_value(newRow.doctype, newRow.name, "score", "0");
            } else if (r.message === "FAIL") {
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "score",
                "-3",
              );
            } else if (r.message === "Report Not found") {
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "score",
                "-2",
              );
            }
          } else {
            let newRow = frappe.model.add_child(
              frm.doc,
              "njqca_result_parameters",
            );

            frappe.model.set_value(
              newRow.doctype,
              newRow.name,
              "parameter",
              "Battery_status",
            );
            frappe.model.set_value(
              newRow.doctype,
              newRow.name,
              "value",
              r.message,
            );
            frappe.model.set_value(
              newRow.doctype,
              newRow.name,
              "item_group",
              "BATTERY",
            );

            if (r.message === "PASS") {
              frappe.model.set_value(newRow.doctype, newRow.name, "score", "0");
            } else if (r.message === "FAIL") {
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "score",
                "42",
              );
            } else if (r.message === "Report Not found") {
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "score",
                "41",
              );
            }
          }

          frm.refresh_field("njqca_result_parameters");
        },
        error: function (err) {
          console.error("Error while checking battery status:", err);
        },
      });
    }

    // ================= LAST QUALITY INSPECTION =================
    if (
      frm.doc.item_group === "Laptops" &&
      frm.doc.bios_serialno &&
      frm.doc.name
    ) {
      await frappe.call({
        method:
          "nj_features.nj_features.doctype.njqca.njqca.get_last_quality_status_from_bios",
        args: {
          njqca_name: frm.doc.name,
        },
        callback: function (r) {
          if (!r.message) return;

          let targetRow = null;

          // Check if row already exists
          (frm.doc.njqca_result_parameters || []).forEach((row) => {
            if (row.parameter === "Last_Quality_Inspection") {
              targetRow = row;
            }
          });

          // Create row if not exists
          if (!targetRow) {
            targetRow = frappe.model.add_child(
              frm.doc,
              "njqca_result_parameters",
            );
          }

          // Set common values
          frappe.model.set_value(
            targetRow.doctype,
            targetRow.name,
            "parameter",
            "Last_Quality_Inspection",
          );

          frappe.model.set_value(
            targetRow.doctype,
            targetRow.name,
            "value",
            r.message, // PASS / FAIL / NOT FOUND
          );

          frappe.model.set_value(
            targetRow.doctype,
            targetRow.name,
            "item_group",
            "Laptops",
          );

          // Optional score mapping
          if (r.message === "PASS") {
            frappe.model.set_value(targetRow.doctype, targetRow.name);
          } else if (r.message === "FAIL") {
            frappe.model.set_value(targetRow.doctype, targetRow.name);
          } else {
            frappe.model.set_value(targetRow.doctype, targetRow.name);
          }

          frm.refresh_field("njqca_result_parameters");
        },
      });
    }

    if (selectedModel && selectedBrand && selectedItemGroup == "Laptops") {
      frappe.call({
        method:
          "nj_features.nj_features.doctype.njqca.njqca.check_for_mis_config",
        args: { doc: frm.doc },
        callback: function (r) {
          if (r.message) {
            let updated = false;

            // Loop through existing rows to check if parameter exists
            frm.doc.njqca_result_parameters.forEach(function (row) {
              if (row.parameter === r.message.parameter) {
                row.value = r.message.value;
                row.item_group = r.message.item_group;
                row.score = r.message.score;
                updated = true;
              }
            });

            // If not found, add a new child row
            if (!updated) {
              var child = frappe.model.add_child(
                frm.doc,
                "njqca_result_parameters",
              );
              frappe.model.set_value(
                child.doctype,
                child.name,
                "parameter",
                r.message.parameter,
              );
              frappe.model.set_value(
                child.doctype,
                child.name,
                "value",
                r.message.value,
              );
              frappe.model.set_value(
                child.doctype,
                child.name,
                "item_group",
                r.message.item_group,
              );
              frappe.model.set_value(
                child.doctype,
                child.name,
                "score",
                r.message.score,
              );
            }

            frm.refresh_field("njqca_result_parameters");
          }
        },
      });
    }

    var requiredFields = ["serial_no", "item_group", "brand", "model"];

    if (!isDesktopNJQCA(frm.doc)) {
      requiredFields.splice(3, 0, "manufacturer_model");
    }
    if (frm.doc.rfq_id) {
      requiredFields.push("warehouse");
    }

    var errorMessages = [];
    var dbError = [];

    for (var i = 0; i < requiredFields.length; i++) {
      var fieldname = requiredFields[i];
      if (!frm.doc[fieldname]) {
        var fieldLabel = frm.fields_dict[fieldname]
          ? frm.fields_dict[fieldname].df.label
          : fieldname;
        if (frm.fields_dict[fieldname]) {
          frm.fields_dict[fieldname].$wrapper.addClass("has-error");
        }
        errorMessages.push(fieldLabel);
      }
    }

    if ($(frm.layout.wrapper).find(".form-message.red").length > 1) {
      $(frm.layout.wrapper).find(".form-message.red").last().remove();
    }

    // Get Reliability && Heavy Load && y_cruncher && gaming && performance
    // Get Reliability && Heavy Load && y_cruncher && gaming && performance
    const inspectionType = (frm.doc.inspection_type || "").trim().toLowerCase();
    const isReliabilityTest = inspectionType === "reliability test";
    const actualTestFilePresent = hasActualTestFile(frm);
    const perfOrHeavyLoadFilePresent = hasPerfOrHeavyLoadTestFile(frm);

    if (frm.doc.serial_no && (isReliabilityTest || actualTestFilePresent)) {
      await frappe.call({
        method:
          "nj_features.nj_features.doctype.njqca.njqca.get_reliability_test_status",
        args: { doc: frm.doc },
        freeze: true,
        callback: function (r) {
          if (r.message && Array.isArray(r.message.changes)) {
            applyChangesNoDuplicates(frm, r.message.changes);
            frm.refresh_field("njqca_result_parameters");
          }
        },
      });

      // Run Performance / HeavyLoad final status only after parsed rows are added
      if (
        selectedModel &&
        selectedItemGroup == "Laptops" &&
        !frm.doc.rfq_id &&
        (isReliabilityTest || perfOrHeavyLoadFilePresent)
      ) {
        await frappe.call({
          method:
            "nj_features.nj_features.doctype.njqca.njqca.update_performance_criteria",
          args: { doc: frm.doc },

          callback: function (r) {
            if (!r || !r.message) {
              return;
            }

            console.log("update_performance_criteria response:", r.message);

            if (r.message.error) {
              frappe.msgprint({
                title: __("Error"),
                message: r.message.error,
                indicator: "red",
              });
              frappe.validated = false;
              return;
            }

            if (Array.isArray(r.message.changes)) {
              applyChangesNoDuplicates(frm, r.message.changes);
              frm.refresh_field("njqca_result_parameters");
              return;
            }

            if (r.message.parameter) {
              applyChangesNoDuplicates(frm, [r.message]);
              frm.refresh_field("njqca_result_parameters");
            }
          },

          error: function (err) {
            console.error("Error while updating performance criteria:", err);
          },
        });
      }
    }

    // Check automated repack item code
    if (frm.doc.item_group == "Laptops" && !frm.doc.repack_item_code) {
        frappe.msgprint({
            title: "Missing Automated Item Code",
            message: "Automated Repack Item Code is not generated. Please contact NPD team.",
            indicator: "red"
        });

        frappe.validated = false;
        return;
    }
  },

  rfq_id: function (frm) {
    if (frm.doc.rfq_id) {
      frappe.call({
        method:
          "nj_features.nj_features.doctype.njqca.njqca.get_item_code_from_rfq_id",
        args: { rfq_id: frm.doc.rfq_id },
        callback: function (r) {
          if (r.message && r.message.length > 0) {
            frm.set_df_property("item_code", "read_only", 0);
            frm.set_value("item_code", "");

            if (r.message.length === 1) {
              frm.set_value("item_code", r.message[0].item_code);
              frm.set_df_property("item_code", "read_only", 1);
            } else {
              frm.set_query("item_code", function () {
                return {
                  filters: {
                    name: ["in", r.message.map((item) => item.item_code)],
                  },
                };
              });
            }
          } else {
            frappe.msgprint(__("No items found for this RFQ."));
          }
          frm.refresh_field("item_code");
        },
      });
    } else {
      frm.set_df_property("serial_no", "read_only", 0);
      frm.refresh_field("serial_no");
    }
  },

  on_submit: function (frm) {
    var openedUrls = JSON.parse(localStorage.getItem("openedUrls")) || [];
    if (frm.doc.serial_no || frm.doc.component_serial_no) {
      frappe.call({
        method: "nj_features.nj_features.doctype.njqca.njqca.after_save_njqca",
        args: {
          docname: frm.doc.name,
          component_serial_no: frm.doc.component_serial_no,
          brand: frm.doc.brand,
          model: frm.doc.model,
          qi_type: frm.doc.qi_type,
        },
        callback: function (r) {
          if (r && r.message) {
            let urlToCompare = r.message.njpulse_url.replace(/\/$/, "");
            let pwd_njpulse_url = urlToCompare;

            if (urlToCompare && !openedUrls.includes(urlToCompare)) {
              openedUrls.push(urlToCompare);
              localStorage.setItem("openedUrls", JSON.stringify(openedUrls));

              if (frm.doc.pwd && r.message.base_url) {
                pwd_njpulse_url =
                  r.message.base_url +
                  "api/authenticate?usr=" +
                  frm.doc.created +
                  "&pwd=" +
                  frm.doc.pwd +
                  "&encrypted_pwd=True&doctype_url=qi/" +
                  r.message.qi_name;
              }
              window.open(pwd_njpulse_url, "_blank");
            }

            if (r.message.qi_name) {
              frm.set_value("qi_name", r.message.qi_name);
              frm.refresh_field("qi_name");

              var $qiNameWrapper = frm.fields_dict["qi_name"].$wrapper;
              $qiNameWrapper
                .closest(".control-input-wrapper")
                .css("border-color", "rgba(173, 216, 230, 0.5)");

              $qiNameWrapper.css("cursor", "pointer");
              $qiNameWrapper.attr("title", "Click to open " + frm.doc.qi_name);

              $qiNameWrapper.on("click", function () {
                window.open(pwd_njpulse_url, "_blank");
              });

              $qiNameWrapper.css({
                "user-select": "none",
                "pointer-events": "auto",
              });
            }

            if (r.message.msg_pnt) {
              frappe.show_alert(
                {
                  message: r.message.msg_pnt,
                  indicator: "blue",
                },
                10,
              );
            }
          } else {
            console.error("QI name is not defined");
          }
        },
      });
    }
  },

  before_submit: async function (frm) {
    if (frm.doc.serial_no && frm.doc.item_group) {
      const { message: resp } = await frappe.db.get_value(
        "Item Group",
        frm.doc.item_group,
        "is_component",
      );

      if (resp && resp.is_component == 0) {
        let tablesToCheck = [
          "njqca_laptop_ram",
          "njqca_laptop_storage",
          "njqca_display",
        ];
        let mismatches = [];
        let i = 0;

        for (let table of tablesToCheck) {
          for (let row of frm.doc[table] || []) {
            if (
              row.component_serial_no &&
              row.component_serial_no.trim() !== ""
            ) {
              continue;
            }
            if (
              !row.calculated_item_code ||
              row.calculated_item_code.trim() === ""
            ) {
              mismatches.push(
                `<br><b>${++i}.</b> The calculated item code is missing in <b>${table}</b>.<br>`,
              );
            }
          }
        }

        if (mismatches.length > 0) {
          const { message: ign } = await frappe.db.get_value(
            "Inspection Type",
            frm.doc.inspection_type,
            "ignore_part_validation",
          );

          if (ign && ign.ignore_part_validation == 0) {
            const confirmed = await new Promise((resolve) => {
              frappe.confirm(
                `<b>The following issues were found:</b><br>${mismatches.join(
                  "<br>",
                )}<br>`,
                () => resolve(false),
                () => resolve(false),
              );
            });

            if (!confirmed) {
              frappe.validated = false;
              frappe.throw("Submission cancelled by user due to mismatches.");
            }
          }
        }

        if (frm.doc.automated_repack_item != frm.doc.repack_item_code) {
          const repackConfirmed = await new Promise((resolve) => {
            frappe.confirm(
              `<b>Automated Item Code: ${frm.doc.automated_repack_item}</b> <br> <b>Repack Item Code: ${frm.doc.repack_item_code}</b> are not the same.<br>Are you sure you want to Submit?`,
              () => {
                frappe.confirm(
                  "Are you sure you want to proceed with submitting this form with the current item codes?",
                  () => resolve(true),
                  () => resolve(false),
                );
              },
              () => resolve(false),
            );
          });

          if (!repackConfirmed) {
            frappe.validated = false;
            frappe.throw("Submission cancelled due to item code mismatch.");
          }
        }
      }
    }

    await frappe.call({
      method: "nj_features.nj_features.doctype.njqca.njqca.get_sudden_drop",
      args: {
        parent_name: frm.doc.name,
        item_group: frm.doc.item_group,
        manufacturer_model: frm.doc.manufacturer_model,
      },
      callback: function (r) {
        if (r.message) {
          frm.set_value("sudden_drop", r.message);
          frm.refresh_field("sudden_drop");
        }
      },
    });

    if (frm.doc.item_group == "BATTERY") {
      frappe.validated = true;
      await frappe.call({
        method: "nj_features.nj_features.doctype.njqca.njqca.get_bdt_status",
        args: { doc: frm.doc },
        callback: function (r) {
          if (r.message) {
            let newRow = frappe.model.add_child(
              frm.doc,
              "njqca_result_parameters",
            );
            if (r.message == "Pass") {
              frm.set_value("bdt_status", "Pass");
              frm.refresh_field("bdt_status");
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "parameter",
                "BDT_status",
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "value",
                r.message,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "item_group",
                "BATTERY",
              );
              frappe.model.set_value(newRow.doctype, newRow.name, "score", "0");
            } else if (r.message == "Fail") {
              frm.set_value("bdt_status", "Fail");
              frm.refresh_field("bdt_status");
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "parameter",
                "BDT_status",
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "value",
                r.message,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "item_group",
                "BATTERY",
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "score",
                "41",
              );
            } else {
              frappe.validated = false;
              frappe.throw(r.message);
            }
          } else {
            frappe.validated = false;
            frappe.throw("Error while getting BDT Status");
          }
          frm.refresh_field("njqca_result_parameters");
        },
      });
    }
  },

  power_on: function () {
    const isYes = cur_frm.doc.power_on === "Yes";
    const isNone = cur_frm.doc.power_on === "";
    cur_frm.set_df_property("iqc_section", "hidden", !isYes);
    cur_frm.set_df_property("section_break_6sw2s", "hidden", isNone || 0);
    cur_frm.set_df_property("section_break_56eed", "hidden", !isYes);
    cur_frm.set_df_property("warehouse", "hidden", !isYes);
    cur_frm.set_df_property("manual_repack_item_code", "hidden", !isYes);
    cur_frm.set_df_property("model", "hidden", !isYes);
  },

  barcode: function (frm) {
    setupNJQCABarcodeScannerOnly(frm);
    if (!isNJQCABarcodeFromScanner(frm)) {
      clearNJQCABarcodeField(frm);
      showNJQCABarcodeScannerMessage(frm);
      return;
    }

    if (frm.doc.barcode) {
      const scannerState = frm.__njqca_barcode_scanner_state || {};
      const now = Date.now();

      if (
        scannerState.lastProcessedValue === frm.doc.barcode &&
        now - scannerState.lastProcessedAt < 1000
      ) {
        return;
      }

      scannerState.lastProcessedValue = frm.doc.barcode;
      scannerState.lastProcessedAt = now;
      frm.__njqca_barcode_scanner_state = scannerState;

      frappe.call({
        method:
          "nj_features.nj_features.api.api_files.search_for_serial_or_batch_or_barcode_no",
        args: { search_value: frm.doc.barcode, raise_exp: 1 },
        callback: function (r) {
          if (r.message) {
            if (r.message.serial_no) {
              if (frm.doc.item_group) {
                frappe.db.get_value(
                  "Item Group",
                  frm.doc.item_group,
                  "is_component",
                  (ig) => {
                    if (ig.is_component == "0") {
                      frm.set_value("serial_no", r.message.serial_no);
                    } else {
                      frm.set_value("component_serial_no", r.message.serial_no);
                    }
                  },
                );
              }
              frm.set_value("serial_no", r.message.serial_no);
            } else if (r.message.scan) {
              frappe.msgprint("Please Scan the Serial No.");
              frm.set_value("serial_no", "");
              frm.set_value("barcode", "");
            }
            frm.refresh_field("serial_no");
            frm.refresh_field("barcode");
            $('[data-fieldname="barcode"]').focus();
          }
        },
        error: function (r) {
          frappe.msgprint("Error while scanning Serial No.");
          frm.set_value("barcode", "");
          frm.set_value("serial_no", "");
          frm.refresh_field("barcode");
          frm.refresh_field("serial_no");
          $('[data-fieldname="barcode"]').focus();
        },
      });
    }
  },

  serial_no: function (frm) {
    if (frm.doc.serial_no) {
      if (!frm.doc.rfq_id) {
        frm.set_value("warehouse", "");
        if (frm.__skip_serial_no_trigger_once) {
          frm.__skip_serial_no_trigger_once = false;
        } else {
          trigger_serial_no(frm);
        }
      }
    } else {
      frm.set_value("warehouse", "");
      frm.refresh_field("warehouse");
    }

    if (
      !frappe.user.has_role("NJ IQC Manager") &&
      frm.doc.serial_no &&
      frm.doc.serial_no.trim() !== "" &&
      !frm.doc.rfq_id
    ) {
      cur_frm.set_df_property("serial_no", "read_only", 1);
    }
  },

  component_serial_no: function (frm) {
    handleScannerInput(frm, "component_serial_no");
    if (frm.doc.component_serial_no) {
      if (!frm.doc.rfq_id) {
        frappe.call({
          method:
            "nj_features.nj_features.doctype.njqca.njqca.get_info_from_component_serial_no",
          args: { doc: frm.doc },
          callback: function (r) {
            Object.keys(r.message).forEach((field) => {
              frm.set_value(field, r.message[field]);
              cur_frm.refresh_field(field);
            });
            syncDesktopManufacturerModelFlow(frm);
          },
        });
      }
    } else {
      frm.set_value("warehouse", "");
      frm.refresh_field("warehouse");
    }
  },

  manufacturer_model: function (frm) {
    if (isDesktopNJQCA(frm.doc)) {
      return;
    }

    if (!frm.doc.manufacturer_model) {
      return;
    }

    njqca.get_model(
      frm.doc.manufacturer_model,
      frm.doc.item_group,
      frm.doc.brand,
      frm.doc.njqca_item_component
    );
  },

  brand: function (frm) {
    if (isDesktopNJQCA(frm.doc)) {
      frm.__desktop_resetting = true;
      resetDesktopSelection(frm);
      syncDesktopManufacturerModelFlow(frm);
      frm.__desktop_resetting = false;
    }
  },

  inspection_type: function (frm) {
    if (frm.doc.inspection_type) {
      frappe.call({
        method: "nj_features.nj_features.doctype.njqca.njqca.set_is_defective",
        args: { inspection_type: frm.doc.inspection_type },
        callback: function (r) {
          if (r && r.message && r.message == "1") {
            frm.set_value("qi_type", "is_defective");
            frm.refresh_field("qi_type");
          }
        },
      });
    }
  },

  warehouse: async function (frm) {
    if (isNJQCACreatedByCurrentUser(frm)) {
      promptNJQCATransferForCreatedUser(frm);
      return;
    }

    const promptKey = getNJQCAWarehouseTransferPromptKey(frm);
    if (
      isNJQCATransferDialogActive(frm) ||
      frm.__warehouse_transfer_prompt_running ||
      frm.__warehouse_transfer_prompted_for === promptKey
    ) {
      return;
    }

    if (
      frm.doc.warehouse &&
      (frm.doc.serial_no || frm.doc.component_serial_no) &&
      !frm.doc.rfq_id
    ) {
      let ware = frm.doc.warehouse;
      const currentUserEmail = getNJQCACurrentUserEmail();
      frm.__warehouse_transfer_prompt_running = true;
      let employeeData = await frappe.db.get_value(
        "Employee",
        { user_id: currentUserEmail, status: "Active" },
        "work_warehouse",
      );
      let item_group_data = await frappe.db.get_value(
        "Item Group",
        { name: frm.doc.item_group },
        "is_component",
      );
      const isComponent = item_group_data?.message?.is_component;
      const frmSerialNo =
        Number(isComponent) === 1
          ? frm.doc.component_serial_no
          : frm.doc.serial_no;
      const serialWarehouse = await getNJQCASerialWarehouse(frmSerialNo);

      const workWarehouse = employeeData?.message?.work_warehouse;
      frm.__warehouse_transfer_prompt_running = false;
      if (!workWarehouse) {
        frm.__warehouse_transfer_prompted_for = promptKey;
        frappe.msgprint(
          `Work Warehouse is not set for employee: ${currentUserEmail}. Please mail to <b>IT Infra Team</b> at <strong><a href="mailto:itinfra@newjaisa.com">itinfra@newjaisa.com</a></strong> to create an employee.`,
        );
      } else {
        const shouldPromptTransfer = serialWarehouse
          ? !isSameNJQCAWarehouse(serialWarehouse, workWarehouse)
          : !isSameNJQCAWarehouse(ware, workWarehouse);

        if (!shouldPromptTransfer) {
          frm.__warehouse_transfer_prompted_for = promptKey;
          await syncNJQCAFormWarehouse(frm, serialWarehouse || workWarehouse);
          return;
        }

        if (isNJQCATransferDialogActive(frm)) {
          return;
        }

        frm.__warehouse_transfer_prompted_for = promptKey;
        let dialog = new frappe.ui.Dialog({
          title: "Confirm Stock Transfer",
          fields: [
            {
              fieldtype: "HTML",
              fieldname: "message",
              options: `Do you want to transfer stock to your Work Warehouse: ${workWarehouse}?`,
            },
            {
              fieldtype: "Data",
              fieldname: "serial_num",
              label: "Scan Serial No",
              options: "Barcode",
            },
          ],
          static: true,
          primary_action_label: "Yes, Transfer",
          primary_action: function () {
            let scannedSerialNo = dialog.get_value("serial_num");
            let frm_serial_no = frmSerialNo;

            if (scannedSerialNo) {
              frappe.call({
                method:
                  "nj_features.nj_features.api.api_files.search_for_serial_or_batch_or_barcode_no",
                args: { search_value: scannedSerialNo, raise_exp: 1 },
                callback: function (r) {
                  if (r.message) {
                    if (r.message.serial_no) {
                      scannedSerialNo = r.message.serial_no;
                      if (
                        scannedSerialNo.toLowerCase() !==
                        frm_serial_no.toLowerCase()
                      ) {
                        $(".primary-action").hide();
                        frappe.msgprint({
                          title: "Serial Number Mismatch",
                          message: `The scanned serial number ${scannedSerialNo} does not match the available serial number ${frm.doc.serial_no}. Please try again.`,
                        });
                        dialog.hide();
                        return;
                      } else {
                        let btn = dialog.get_primary_btn();
                        if (btn) btn.prop('disabled', true);
                        dialog.hide();

                        let material_transfer_items = [
                          {
                            serial_no: frm_serial_no,
                            item_code: frm.doc.item_code,
                            t_warehouse: workWarehouse,
                            s_warehouse: serialWarehouse || frm.doc.warehouse,
                          },
                        ];

                        let data = {
                          doctype: frm.doc.doctype,
                          serial_no: frm_serial_no,
                          t_warehouse: workWarehouse,
                          stock_entry_type: "Material Transfer",
                          reference_serial_no: frm.doc.serial_no,
                          material_transfer_items: material_transfer_items,
                        };

                        frappe.call({
                          method:
                            "nj_lib.utils.stock_entry.stock_entry_using_nj_lib",
                          args: { data: JSON.stringify(data) },
                          freeze: true,
                          freeze_message: `<div style="text-align: center;">
                                                        <i class="fa fa-spinner fa-spin" style="font-size: 24px;"></i> 
                                                        <br>Transferring Stock... Please Wait
                                                    </div>`,
                          callback: function (response) {
                            if (response && response.message) {
                              $(".primary-action").show();
                              frm.set_value("warehouse", workWarehouse);
                              frm.refresh_field("warehouse");
                            } else {
                              if (btn) btn.prop('disabled', false);
                              dialog.show();
                            }
                          },
                          error: function (err) {
                            console.error(err);
                            $(".primary-action").hide();
                            if (btn) btn.prop('disabled', false);
                            dialog.show();
                          },
                        });
                      }
                    }
                  }
                },
              });
            }
          },
          secondary_action_label: "Cancel",
          secondary_action: function () {
            dismissNJQCATransferDialog(dialog);
            dialog.hide();
          },
        });
        bindNJQCATransferDialogEscape(frm, dialog);
        dialog.show();
      }
    }
  },

  model: async function (frm) {
    var selectedModel = frm.doc.model;
    var selectedBrand = frm.doc.brand;
    var selectedItemGroup = frm.doc.item_group;
    let item_group_data = await frappe.db.get_value(
      "Item Group",
      { name: frm.doc.item_group },
      "is_component",
    );
    const isComponent = item_group_data?.message?.is_component;

    if (selectedModel && !isDesktopNJQCA(frm.doc)) {
      await frappe.call({
        method: "nj_features.nj_features.doctype.njqca.njqca.validate_model",
        args: {
          model: frm.doc.model,
          manufacturer_model: frm.doc.manufacturer_model,
          components: frm.doc.njqca_item_component,
        },
        callback: function (r) {
          if (r.message && r.message == "0") {
            frm.set_value("model", "");
            frm.refresh_field("model");
          }
        },
      });
    }

    if (selectedModel && isDesktopNJQCA(frm.doc)) {
      frm.set_value("manufacturer_model", selectedModel);
    }

    if (
      frm.doc.model &&
      selectedBrand &&
      cur_frm.doc.serial_no &&
      isComponent == "0"
    ) {
      frappe.db.get_value(
        "Models",
        { name: selectedModel },
        "model_description",
        function (result) {
          if (result && result.model_description) {
            frm.set_value("model_description", result.model_description);
            frm.refresh_field("model_description");
          }
        },
      );

      frappe.db.get_value(
        "Serial No",
        { serial_no: cur_frm.doc.serial_no },
        "model",
        function (r) {
          if (
            !r.model &&
            selectedItemGroup.toLowerCase() != "battery" &&
            selectedItemGroup.toLowerCase() != "laptop ram"
          ) {
            frappe.throw(
              `Model is not filled in Serial no: <b>${cur_frm.doc.serial_no}</b>. Please contact the NPD Team.`,
            );
          }

          if (
            selectedModel &&
            selectedModel != r.model &&
            selectedItemGroup &&
            selectedItemGroup == "Laptops"
          ) {
            frappe.confirm(
              "Model in SerialNo and NJQCA are Different. Do you want to change the part list?",
              () => {
                frappe.call({
                  method:
                    "nj_features.nj_features.doctype.njqca.njqca.model_change_for_serial_no",
                  args: {
                    newmodel: frm.doc.model,
                    serial_no: frm.doc.serial_no,
                  },
                  callback: function (r) {
                    if (r.message.status === "success") {
                      var base_url = frappe.urllib.get_base_url();
                      var serial_no_link = `${base_url}/app/serial-no/${cur_frm.doc.serial_no}`;
                      frappe.msgprint(
                        `Part List and Model is updated for Serial No : <strong><a href='${serial_no_link}'>${cur_frm.doc.serial_no}</a></strong> has been submitted successfully.`,
                      );
                    } else if (r.message.status === "failed") {
                      $(".primary-action").hide();
                      frm.set_value("model", "");
                    }
                  },
                });
              },
              () => {
                if (selectedModel == r.model) {
                  $(".primary-action").show();
                } else {
                  frm.set_value("model", "");
                  $(".primary-action").hide();
                }
              },
            );
          }

          if (selectedModel == r.model) {
            $(".primary-action").show();
          }
        },
      );
    }

    if (
      isComponent == "0" &&
      selectedModel &&
      selectedBrand &&
      selectedItemGroup
    ) {
      get_item_template(selectedModel, selectedBrand, selectedItemGroup);
    }

    frm.refresh_field("item_template");

    if (!frm.doc.model) {
      if (!frm.__desktop_resetting) {
        // ← this check needs the flag set
        frm.set_value("manual_repack_item_code", "");
        frm.refresh_field("manual_repack_item_code");
      }
    }
  },

  item_template: function (frm) {
    if (
      frm.doc.item_template &&
      frm.doc.power_on == "Yes" &&
      frm.doc.item_group != "BATTERY"
    ) {
      processItemTemplate(frm);
    }
  },

  before_save: function (frm) {
    (frm.doc.njqca_laptop_ram || []).forEach((row) => {
      delete row._item_templates;
    });
    (frm.doc.njqca_laptop_storage || []).forEach((row) => {
      delete row._item_templates;
    });

    if (
      frm.doc.name &&
      frm.doc.item_template &&
      frm.doc.item_group == "Laptops"
    ) {
      frappe.call({
        method: "nj_features.nj_features.doctype.njqca.njqca.check_ram_speed",
        args: {
          njqca_name: frm.doc.name,
          item_template: frm.doc.item_template,
        },
        callback: function (r) {
          if (r.message) {
            let newRow = frappe.model.add_child(
              frm.doc,
              "njqca_result_parameters",
            );
            if (r.message == "PASS") {
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "parameter",
                "IW_Speed_Match",
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "value",
                r.message,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "item_group",
                "Laptop RAM",
              );
              frappe.model.set_value(newRow.doctype, newRow.name, "score", "0");
            } else if (r.message == "FAIL") {
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "parameter",
                "IW_Speed_Match",
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "value",
                r.message,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "item_group",
                "Laptop RAM",
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "score",
                "41",
              );
            }
          }
        },
      });
    }
  },

  item_code: function (frm) {
    if (
      frm.doc.item_group === "Laptop RAM" &&
      frm.doc.item_code &&
      frm.doc.item_code !== ""
    ) {
      frappe.call({
        method:
          "nj_features.nj_features.doctype.njqca.njqca.get_item_code_for_ram",
        args: { item_code: frm.doc.item_code, njqca_name: frm.doc.name },
        callback: function (r) {
          if (r.message) {
            frm.set_value("repack_item_code", r.message);
            frm.set_value("manual_repack_item_code", r.message);
            frm.refresh_field("repack_item_code");
            frm.refresh_field("manual_repack_item_code");
          }
        },
      });
    }
  },
});

async function openChangeModelDialog(frm) {
  if (!frm.doc.model) {
    frappe.msgprint(__("Please select the current Model first."));
    return;
  }

  const response = await frappe.call({
    method:
      "nj_features.nj_features.doctype.njqca.njqca.get_model_configuration_for_change",
    args: {
      model: frm.doc.model,
      item_group: frm.doc.item_group,
    },
    freeze: true,
    freeze_message: __("Loading model configuration..."),
  });
  const parameters = response.message || [];

  if (!parameters.length) {
    frappe.msgprint(
      __(
        "No Parameter Specification is configured for model {0}.",
        [frm.doc.model],
      ),
    );
    return;
  }

  const parameterFields = parameters.map((row, index) => ({
    fieldname: `model_parameter_${index}`,
    fieldtype: "Select",
    label: row.parameter,
    options: row.options,
    default: row.value,
    reqd: 1,
  }));

  const dialog = new frappe.ui.Dialog({
    title: __("Change Model Configuration"),
    fields: [
      ...parameterFields,
      {
        fieldname: "matching_model_section",
        fieldtype: "Section Break",
        label: __("Matching Models"),
        hidden: 1,
      },
      {
        fieldname: "matching_model",
        fieldtype: "Select",
        label: __("Model"),
        hidden: 1,
        reqd: 0,
      },
    ],
    primary_action_label: __("Find Models"),
    primary_action: async function (values) {
      if (dialog._selecting_matching_model) {
        await applyChangedModel(frm, dialog, values.matching_model);
        return;
      }

      const configuration = parameters.map((row, index) => ({
        parameter: row.parameter,
        value: values[`model_parameter_${index}`],
      }));
      const result = await frappe.call({
        method:
          "nj_features.nj_features.doctype.njqca.njqca.find_models_by_configuration",
        args: {
          configuration: JSON.stringify(configuration),
          item_group: frm.doc.item_group,
        },
        freeze: true,
        freeze_message: __("Finding matching models..."),
      });
      const models = result.message || [];

      if (!models.length) {
        frappe.msgprint(
          __("No model was found matching the selected configuration."),
        );
        return;
      }

      if (models.length === 1) {
        await applyChangedModel(frm, dialog, models[0]);
        return;
      }

      dialog._selecting_matching_model = true;
      dialog.set_df_property("matching_model_section", "hidden", 0);
      dialog.set_df_property("matching_model", "hidden", 0);
      dialog.set_df_property("matching_model", "reqd", 1);
      dialog.set_df_property("matching_model", "options", ["", ...models]);
      dialog.set_value("matching_model", "");
      dialog.get_primary_btn().text(__("Apply Model"));
    },
  });

  dialog.show();
}

async function applyChangedModel(frm, dialog, model) {
  if (!model) {
    frappe.msgprint(__("Please select a Model."));
    return;
  }

  if (model === frm.doc.model) {
    dialog.hide();
    frappe.show_alert({
      message: __("Model {0} is already selected.", [model]),
      indicator: "blue",
    });
    return;
  }

  await frm.set_value("model", model);
  await frm.set_value("model_changed_using_change_model", 1);
  frm.refresh_field("model");
  dialog.hide();
  frappe.show_alert({
    message: __("Model changed to {0}.", [model]),
    indicator: "green",
  });
}

function getNJQCACurrentUserEmail() {
  return (frappe.session.user_email || frappe.session.user || "")
    .trim()
    .toLowerCase();
}

function getNJQCACreatedUserEmail(frm) {
  return (frm.doc.created || frm.doc.owner || "").trim().toLowerCase();
}

function isNJQCACreatedByCurrentUser(frm) {
  const currentUserEmail = getNJQCACurrentUserEmail();
  const createdUserEmail = getNJQCACreatedUserEmail(frm);

  return Boolean(
    currentUserEmail &&
    createdUserEmail &&
    currentUserEmail === createdUserEmail,
  );
}

function getNJQCAWarehouseTransferPromptKey(frm) {
  return [
    frm.doc.name,
    frm.doc.serial_no || frm.doc.component_serial_no || "",
    frm.doc.warehouse || "",
  ].join("::");
}

function normalizeNJQCAWarehouse(value) {
  return (value || "").trim().toLowerCase();
}

function isSameNJQCAWarehouse(first, second) {
  return (
    normalizeNJQCAWarehouse(first) &&
    normalizeNJQCAWarehouse(first) === normalizeNJQCAWarehouse(second)
  );
}

async function getNJQCASerialWarehouse(serialNo) {
  if (!serialNo) return "";

  const serialData = await frappe.db.get_value(
    "Serial No",
    serialNo,
    "warehouse",
  );

  return serialData?.message?.warehouse || "";
}

async function syncNJQCAFormWarehouse(frm, warehouse) {
  if (!warehouse || isSameNJQCAWarehouse(frm.doc.warehouse, warehouse)) {
    return;
  }

  frm.__warehouse_transfer_prompted_for =
    getNJQCAWarehouseTransferPromptKey(frm);
  await frm.set_value("warehouse", warehouse);
  frm.refresh_field("warehouse");
  frm.__warehouse_transfer_prompted_for =
    getNJQCAWarehouseTransferPromptKey(frm);
}

function resetNJQCATransferPromptState(frm) {
  if (isNJQCATransferDialogActive(frm)) {
    return;
  }

  frm.__warehouse_transfer_prompted_for = "";
  frm.__created_user_transfer_prompted_for = "";
}

async function triggerNJQCAWarehouseValidationForDifferentWarehouse(frm) {
  if (
    frm.doc.__islocal ||
    frm.doc.docstatus === 1 ||
    isNJQCACreatedByCurrentUser(frm) ||
    isNJQCATransferDialogActive(frm) ||
    !frm.doc.warehouse ||
    !(frm.doc.serial_no || frm.doc.component_serial_no) ||
    frm.doc.rfq_id
  ) {
    return;
  }

  const promptKey = getNJQCAWarehouseTransferPromptKey(frm);
  if (
    frm.__warehouse_transfer_prompt_running ||
    frm.__warehouse_transfer_prompted_for === promptKey
  ) {
    return;
  }

  frm.__warehouse_transfer_prompt_running = true;
  const employeeData = await frappe.db.get_value(
    "Employee",
    { user_id: getNJQCACurrentUserEmail(), status: "Active" },
    "work_warehouse",
  );
  const workWarehouse = employeeData?.message?.work_warehouse;
  frm.__warehouse_transfer_prompt_running = false;

  frm.events.warehouse(frm);
}

async function promptNJQCATransferForCreatedUser(frm) {
  const currentTransferPromptKey = getNJQCAWarehouseTransferPromptKey(frm);

  if (
    frm.__created_user_transfer_running ||
    isNJQCATransferDialogActive(frm) ||
    frm.__created_user_transfer_prompted_for === currentTransferPromptKey ||
    frm.doc.__islocal ||
    frm.doc.docstatus === 1
  ) {
    return;
  }

  const currentUserEmail = getNJQCACurrentUserEmail();
  const createdUserEmail = getNJQCACreatedUserEmail(frm);

  if (
    !currentUserEmail ||
    !createdUserEmail ||
    currentUserEmail !== createdUserEmail ||
    !frm.doc.warehouse ||
    !(frm.doc.serial_no || frm.doc.component_serial_no) ||
    frm.doc.rfq_id
  ) {
    return;
  }

  frm.__created_user_transfer_running = true;

  const employeeData = await frappe.db.get_value(
    "Employee",
    { user_id: currentUserEmail, status: "Active" },
    "work_warehouse",
  );
  const workWarehouse = employeeData?.message?.work_warehouse;

  if (!workWarehouse) {
    frm.__created_user_transfer_prompted_for = currentTransferPromptKey;
    frm.__created_user_transfer_running = false;
    frappe.msgprint(
      `Work Warehouse is not set for employee: ${currentUserEmail}. Please mail to <b>IT Infra Team</b> at <strong><a href="mailto:itinfra@newjaisa.com">itinfra@newjaisa.com</a></strong> to create an employee.`,
    );
    return;
  }

  const itemGroupData = await frappe.db.get_value(
    "Item Group",
    { name: frm.doc.item_group },
    "is_component",
  );
  const isComponent = Number(itemGroupData?.message?.is_component) === 1;
  const serialNo = isComponent
    ? frm.doc.component_serial_no
    : frm.doc.serial_no;

  if (!serialNo) {
    frm.__created_user_transfer_running = false;
    return;
  }

  const serialWarehouse = await getNJQCASerialWarehouse(serialNo);
  const shouldPromptTransfer = serialWarehouse
    ? !isSameNJQCAWarehouse(serialWarehouse, workWarehouse)
    : !isSameNJQCAWarehouse(frm.doc.warehouse, workWarehouse);

  if (!shouldPromptTransfer) {
    frm.__created_user_transfer_prompted_for = currentTransferPromptKey;
    await syncNJQCAFormWarehouse(frm, serialWarehouse || workWarehouse);
    frm.__created_user_transfer_prompted_for =
      getNJQCAWarehouseTransferPromptKey(frm);
    frm.__created_user_transfer_running = false;
    return;
  }

  if (isNJQCATransferDialogActive(frm)) {
    frm.__created_user_transfer_running = false;
    return;
  }

  frm.__created_user_transfer_prompted_for = currentTransferPromptKey;

  let dialog = new frappe.ui.Dialog({
    title: "Confirm Stock Transfer",
    fields: [
      {
        fieldtype: "HTML",
        fieldname: "message",
        options: `Do you want to transfer stock to your Work Warehouse: ${workWarehouse}?`,
      },
    ],
    static: true,
    primary_action_label: "Yes",
    primary_action: function () {
      let btn = dialog.get_primary_btn();
      if (btn) btn.prop('disabled', true);
      dialog.hide();

      const materialTransferItems = [
        {
          serial_no: serialNo,
          item_code: frm.doc.item_code,
          t_warehouse: workWarehouse,
          s_warehouse: serialWarehouse || frm.doc.warehouse,
        },
      ];

      const data = {
        doctype: frm.doc.doctype,
        serial_no: serialNo,
        t_warehouse: workWarehouse,
        stock_entry_type: "Material Transfer",
        reference_serial_no: serialNo,
        material_transfer_items: materialTransferItems,
      };

      frappe.call({
        method: "nj_lib.utils.stock_entry.stock_entry_using_nj_lib",
        args: { data: JSON.stringify(data) },
        freeze: true,
        freeze_message: `<div style="text-align: center;">
          <i class="fa fa-spinner fa-spin" style="font-size: 24px;"></i>
          <br>Transferring Stock... Please Wait
        </div>`,
        callback: function (response) {
          if (response && response.message) {
            $(".primary-action").show();
            frm.set_value("warehouse", workWarehouse);
            frm.refresh_field("warehouse");
          } else {
            if (btn) btn.prop('disabled', false);
            dialog.show();
          }
        },
        error: function (err) {
          console.error(
            "[NJQCA Created User Transfer] Stock transfer error",
            err,
          );
          $(".primary-action").hide();
          if (btn) btn.prop('disabled', false);
          dialog.show();
        },
      });
    },
    secondary_action_label: "No",
    secondary_action: function () {
      dismissNJQCATransferDialog(dialog);
      dialog.hide();
    },
  });

  bindNJQCATransferDialogEscape(frm, dialog);
  frm.__created_user_transfer_running = false;
  dialog.show();
}

function isNJQCATransferDialogActive(frm) {
  return Boolean(frm && frm.__njqca_transfer_dialog_active);
}

function dismissNJQCATransferDialog(dialog) {
  if (dialog) {
    dialog.__njqca_transfer_dismissed = true;
  }

  $(".primary-action").hide();
}

function bindNJQCATransferDialogEscape(frm, dialog) {
  if (!dialog || !dialog.$wrapper) return;

  frm.__njqca_transfer_dialog_active = true;
  frm.__njqca_transfer_dialog = dialog;

  const namespace =
    ".njqca_transfer_dialog_" +
    Date.now() +
    "_" +
    Math.floor(Math.random() * 100000);

  $(document).on("keydown" + namespace, function (event) {
    if (event.key !== "Escape" || !dialog.$wrapper.is(":visible")) return;

    dismissNJQCATransferDialog(dialog);
    dialog.hide();
  });

  dialog.$wrapper.on("hidden.bs.modal", function () {
    if (dialog.__njqca_transfer_dismissed) {
      $(".primary-action").hide();
    }

    if (frm.__njqca_transfer_dialog === dialog) {
      frm.__njqca_transfer_dialog_active = false;
      frm.__njqca_transfer_dialog = null;
    }

    $(document).off(namespace);
  });
}

function isDesktopNJQCA(doc) {
  return (doc.item_group || "").trim().toLowerCase() === "desktops";
}

function applyDesktopFieldState(frm) {
  const isDesktop = isDesktopNJQCA(frm.doc);

  frm.set_df_property("manufacturer_model", "hidden", isDesktop ? 1 : 0);
  frm.set_df_property("model", "read_only", 0);

  frm.refresh_field("manufacturer_model");
  frm.refresh_field("model");
}

function resetDesktopSelection(frm, { keepManufacturerModel = false } = {}) {
  if (!keepManufacturerModel) {
    frm.set_value("manufacturer_model", "");
  }
  frm.set_value("model", "");
  frm.set_value("model_description", "");
  frm.set_value("item_template", "");
  frm.refresh_field("manufacturer_model");
  frm.refresh_field("model");
  frm.refresh_field("model_description");
  frm.refresh_field("item_template");
  frm.set_df_property("model", "read_only", 0);
  frm.set_df_property("model", "options", "\n");
}

function syncDesktopManufacturerModelFlow(
  frm,
  { clearSelections = false } = {},
) {
  if (!isDesktopNJQCA(frm.doc)) {
    return;
  }

  applyDesktopFieldState(frm);

  if (clearSelections) {
    resetDesktopSelection(frm);
  }

  if (!frm.doc.brand) {
    frm.set_df_property("model", "options", "\n");
    frm.refresh_field("model");
    return;
  }

  njqca.get_model(null, frm.doc.item_group, frm.doc.brand);
}

function trigger_serial_no(frm) {
  if (
    (cur_frm.doc.serial_no || cur_frm.doc.bios_serialno) &&
    cur_frm.doc.power_on == "Yes" &&
    !frm.doc.rfq_id
  ) {
    console.log("trigger_serial_no");

    frappe.call({
      method:
        "nj_features.nj_features.doctype.njqca.njqca.get_info_from_serial_no",
      args: { doc: frm.doc },
      callback: function (r) {
        Object.keys(r.message).forEach((field) => {
          frm.set_value(field, r.message[field]);
          cur_frm.refresh_field(field);
        });

        if (isDesktopNJQCA(frm.doc)) {
          if (!r.message.model) {
            resetDesktopSelection(frm);
          }
          syncDesktopManufacturerModelFlow(frm);
        }

        // EXT-NJ Linkage: check if BIOS maps to an EXT serial
        check_and_handle_ext_linkage(frm);
      },
      error: function (err) {
        console.error(err);
        $(".primary-action").hide();
      },
    });
  }
}

function processItemTemplate(frm) {
  if (frm.doc.njqca_item_component && frm.doc.item_template) {
    frappe.call({
      method: "nj_features.nj_features.doctype.njqca.njqca.get_part_mapping",
      args: { doc: frm.doc },
      callback: function (r) {
        if (r.message.error) {
          frappe.show_alert(
            {
              message: __("<b>Error " + r.message.error + "</b>"),
              indicator: "red",
            },
            15,
          );
          return;
        }

        if (r.message) {
          if (typeof r.message === "string") {
            try {
              r.message = JSON.parse(r.message);
            } catch (e) {
              console.error("Failed to parse message:", e);
            }
          }

          if (r.message.repack_item_code) {
            frm.set_value("repack_item_code", r.message.repack_item_code);
            frm.set_value(
              "manual_repack_item_code",
              r.message.repack_item_code,
            );
          } else {
            frappe.utils.play_sound("error");
            var errorMessageString = (errorMessageString =
              "Repack Item code not found for attributes: " +
              r.message.data_attr
                .map((obj) => {
                  const key = Object.keys(obj)[0];
                  return `${key}: ${obj[key]}`;
                })
                .join(", "));
            var errorDiv = $('<div class="form-message red"></div>').html(
              errorMessageString,
            );
            $(frm.layout.wrapper).find(".form-message.red").remove();
            $(frm.layout.wrapper).prepend(errorDiv);

            frappe.show_alert(
              {
                message: errorMessageString,
                indicator: "red",
              },
              20,
            );
          }

          frm.refresh_fields([
            "repack_item_code",
            "manual_repack_item_code",
            "njqca_result_parameters",
          ]);

          const partData = r.message.part_data;

          frm.doc.njqca_item_component.forEach((row) => {
            const part = partData.find(
              (p) => p.name === row.name && p.response !== "error",
            );
            if (part) {
              frappe.model.set_value(
                row.doctype,
                row.name,
                "part_item_code",
                part.part_item_code,
              );
              frappe.model.set_value(
                row.doctype,
                row.name,
                "attr_data",
                JSON.stringify(part.attr_data),
              );
            }
          });
        }

        if (r.message.part_data) {
          const partData = r.message.part_data;

          console.log("Part Data:", partData);

          frm.clear_table("njqca_laptop_ram");
          frm.clear_table("njqca_laptop_processors");
          frm.clear_table("njqca_laptop_storage");

          partData.forEach((row) => {
            if (
              row.item_group === "Laptop RAM" &&
              frm.doc.merged_ram_item_code == 0
            ) {
              let newRow = frappe.model.add_child(frm.doc, "njqca_laptop_ram");
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "ram_type",
                row.attr_data["RAM Type"],
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "ram_capacity",
                row.attr_data["RAM Capacity"],
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "ram_speed",
                row.attr_data["RAM Speed"],
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "grade",
                row.attr_data["Grade"],
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "calculated_item_code",
                row.part_item_code,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "fetched_item_code",
                row.fetched_item_code,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "item_group",
                row.item_group,
              );
              newRow._item_templates = row.item_template;
              let initial_ram_template = "";
              if (Array.isArray(row.item_template)) {
                if (row.item_template.length === 1) {
                  initial_ram_template = row.item_template[0];
                }
              } else if (typeof row.item_template === "string") {
                initial_ram_template = row.item_template;
              }
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "item_template",
                initial_ram_template,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "reference_row_name",
                row.name,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "item_group_idx",
                row.item_group_idx,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "component_serial_no",
                row.serial_no,
              );
              if (row.reference_docname) {
                frappe.model.set_value(
                  newRow.doctype,
                  newRow.name,
                  "reference_docname",
                  row.reference_docname,
                );
              }
              show_checkbutton_for_field(frm, "njqca_laptop_ram");
            } else if (
              row.item_group === "Laptop Processors" &&
              frm.doc.fetched_processor_item_code == 0
            ) {
              console.log("Adding Laptop Processor Row:", row);
              let newRow = frappe.model.add_child(
                frm.doc,
                "njqca_laptop_processors",
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "item_group",
                row.item_group,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "calculated_item_code",
                row.part_item_code,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "fetched_item_code",
                row.fetched_item_code,
              );
              frappe.model.set_value(
                  newRow.doctype,
                  newRow.name,
                  "item_template",
                  frm.doc.item_group === "Desktops" ? "Desktop Processors" : "LAPTOP PROCESSOR"
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "processor_type",
                row.attr_data["Processor Type"] ||
                  row.attr_data["Processor Type1"],
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "grade",
                row.attr_data["Grade"],
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "reference_row_name",
                row.name,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "item_group_idx",
                row.item_group_idx,
              );
              if (row.reference_docname) {
                frappe.model.set_value(
                  newRow.doctype,
                  newRow.name,
                  "reference_docname",
                  row.reference_docname,
                );
              }
              if (row.fetched_item_code) {
                frm.set_value("fetched_processor_item_code", 0);
                frm.refresh_field("fetched_processor_item_code");
              }
              show_checkbutton_for_field(frm, "njqca_laptop_processors");
            } else if (
              row.item_group === "LAPTOP STORAGE" &&
              frm.doc.merged_storage_item_code == 0
            ) {
              let newRow = frappe.model.add_child(
                frm.doc,
                "njqca_laptop_storage",
              );
              if (row.name) {
                frappe.model.set_value(
                  newRow.doctype,
                  newRow.name,
                  "update_variant",
                  row.name,
                );
              }

              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "item_group",
                row.item_group,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "calculated_item_code",
                row.part_item_code,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "fetched_item_code",
                row.fetched_item_code,
              );
              newRow._item_templates = row.item_template;
              let initial_storage_template = "";
              if (Array.isArray(row.item_template)) {
                if (row.item_template.length === 1) {
                  initial_storage_template = row.item_template[0];
                }
              } else if (typeof row.item_template === "string") {
                initial_storage_template = row.item_template;
              }
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "item_template",
                initial_storage_template,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "storage_type",
                row.attr_data["Storage Type"],
              );
              let storageValue = row.attr_data["Storage Capacity"];
              if (storageValue) {
                storageValue = storageValue.replace(/\s*ssd\s*$/i, "");
                frappe.model.set_value(
                  newRow.doctype,
                  newRow.name,
                  "storage_capacity",
                  storageValue,
                );
              }
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "storage_interface",
                row.attr_data["Storage Interface"],
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "storage_length",
                row.attr_data["Storage Length"],
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "grade",
                row.attr_data["Grade"],
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "reference_row_name",
                row.name,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "item_group_idx",
                row.item_group_idx,
              );
              frappe.model.set_value(
                newRow.doctype,
                newRow.name,
                "component_serial_no",
                row.serial_no,
              );
              if (row.reference_docname) {
                frappe.model.set_value(
                  newRow.doctype,
                  newRow.name,
                  "reference_docname",
                  row.reference_docname,
                );
              }
              show_checkbutton_for_field(frm, "njqca_laptop_storage");
            }
          });

          frm.refresh_field("njqca_laptop_ram");
          frm.refresh_field("njqca_laptop_processors");
          frm.refresh_field("njqca_laptop_storage");

          // Dynamically set row-specific properties for item_template dropdown/read-only
          ["njqca_laptop_ram", "njqca_laptop_storage"].forEach((table_name) => {
            let grid = frm.fields_dict[table_name].grid;
            grid.grid_rows.forEach((grid_row) => {
              let doc = grid_row.doc;
              if (doc._item_templates) {
                let templates = [];
                if (Array.isArray(doc._item_templates)) {
                  templates = doc._item_templates;
                } else if (
                  typeof doc._item_templates === "string" &&
                  doc._item_templates
                ) {
                  templates = [doc._item_templates];
                }

                if (templates.length > 1) {
                  frm.set_df_property(
                    table_name,
                    "options",
                    templates,
                    frm.docname,
                    "item_template",
                    doc.name,
                  );
                  frm.set_df_property(
                    table_name,
                    "read_only",
                    0,
                    frm.docname,
                    "item_template",
                    doc.name,
                  );
                } else if (templates.length === 1) {
                  frm.set_df_property(
                    table_name,
                    "options",
                    templates,
                    frm.docname,
                    "item_template",
                    doc.name,
                  );
                  frm.set_df_property(
                    table_name,
                    "read_only",
                    1,
                    frm.docname,
                    "item_template",
                    doc.name,
                  );
                }
              }
            });
            grid.refresh();
          });
        }
      },
      error: function (err) {
        frappe.show_alert(
          {
            message: __("<b>Error " + err.message),
            indicator: "red",
          },
          10,
        );
      },
    });

    // if (frm.doc.serial_no) {
    //   frappe.call({
    //     method:
    //       "nj_features.nj_features.doctype.njqca.njqca.get_disp_and_adp_data",
    //     args: { serial_no: frm.doc.serial_no },
    //     callback: function (r) {
    //       if (r.message) {
    //         r.message.forEach((item) => {
    //           let newRow;

    //           if (item.item_group === "Display") {
    //             frm.clear_table("njqca_display");
    //             newRow = frappe.model.add_child(frm.doc, "njqca_display");
    //             show_checkbutton_for_field(frm, "njqca_display");
    //           } else if (item.item_group === "Laptop Adaptors") {
    //             frm.clear_table("njqca_adaptor");
    //             newRow = frappe.model.add_child(frm.doc, "njqca_adaptor");
    //             show_checkbutton_for_field(frm, "njqca_adaptor");
    //           }

    //           if (newRow) {
    //             for (let key in item) {
    //               if (
    //                 item.hasOwnProperty(key) &&
    //                 key.toLowerCase() != "model"
    //               ) {
    //                 frappe.model.set_value(
    //                   newRow.doctype,
    //                   newRow.name,
    //                   key,
    //                   item[key],
    //                 );
    //               }
    //             }
    //           }
    //           frm.set_value("fetched_adaptor");
    //         });
    //         frm.refresh_fields();
    //       }
    //     },
    //   });
    // }
  }
}

function get_item_template(model, brand, item_group) {
  frappe.call({
    method:
      "nj_features.nj_features.doctype.njqca.njqca.get_njqca_item_template",
    args: { model: model, brand: brand, item_group: item_group },
    callback: function (r) {
      if (r.message) {
        var itemTemplates = r.message.item_template
          ? r.message.item_template.map((item) => item.name)
          : [];

        cur_frm.set_value("item_template", "");
        if (Array.isArray(itemTemplates) && itemTemplates.length > 0) {
          if (itemTemplates.length == 1) {
            cur_frm.set_value("item_template", itemTemplates[0]);
            cur_frm.set_df_property("item_template", "read_only", 1);
            cur_frm.refresh_field("item_template");
            $('[data-fieldname="item_template"]')
              .closest(".control-input-wrapper")
              .css({
                "border-radius": "0.25rem",
                border: "2px solid rgba(173, 216, 230, 0.5)",
              });

            var selectedOption = itemTemplates[0];
            var wizardList = r.message.wizard_list || [];

            if (wizardList.includes(selectedOption)) {
              $('[data-fieldname="item_template"]')
                .closest(".control-input-wrapper")
                .css("border-color", "green");
            } else {
              $('[data-fieldname="item_template"]')
                .closest(".control-input-wrapper")
                .css("border-color", "red");
            }
          } else {
            cur_frm.set_df_property("item_template", "read_only", 0);
            var wizardList = r.message.wizard_list || [];
            cur_frm.set_df_property("item_template", "options", itemTemplates);
            cur_frm.refresh_field("item_template");
            $('[data-fieldname="item_template"]')
              .focus()
              .closest(".control-input-wrapper")
              .css({
                "border-radius": "0.25rem",
                border: "2px solid rgba(173, 216, 230, 0.5)",
              });

            cur_frm.fields_dict.item_template.$input.on("change", function () {
              var selectedOption = $(this).val();
              $('[data-fieldname="item_template"]')
                .closest(".control-input-wrapper")
                .css("border-color", "rgba(173, 216, 230, 0.5)");
              if (wizardList.includes(selectedOption)) {
                $(this)
                  .closest(".control-input-wrapper")
                  .css("border-color", "green");
              } else {
                $(this)
                  .closest(".control-input-wrapper")
                  .css("border-color", "red");
              }
            });

            frappe.show_alert({
              message: __("Select Item Template"),
              indicator: "green",
            });
          }
        } else {
          cur_frm.set_df_property("item_template", "options", []);
          cur_frm.refresh_field("item_template");
          $('[data-fieldname="item_template"]')
            .closest(".control-input-wrapper")
            .css({
              "border-radius": "0.25rem",
              border: "2px solid red",
            });

          frappe.msgprint(
            __(
              "Item Template is not found using <b>Brand: {0}</b>,<br><b>Model: {1}</b>,<br><b>Item Group: {2}</b>.<br>Please contact <b>NPD Team.</b>",
              [brand, model, item_group],
            ),
          );
        }
      }
    },
  });
}

frappe.provide("njqca");
njqca.get_manufacturer_models = function (
  frm,
  { selected_manufacturer_model = null } = {},
) {
  frappe.call({
    method:
      "nj_features.nj_features.doctype.njqca.njqca.get_manufacturer_models",
    args: {
      item_group: frm.doc.item_group,
      brand: frm.doc.brand,
    },
    callback: function (r) {
      const manufacturerModelList = r.message || [];
      const options = manufacturerModelList
        .map((item) => item.manufacturer_model)
        .filter(Boolean);

      frm.set_df_property(
        "manufacturer_model",
        "options",
        options.length ? [""].concat(options).join("\n") : "\n",
      );
      frm.refresh_field("manufacturer_model");

      if (!options.length) {
        frm.set_value("manufacturer_model", "");
        frm.set_value("model", "");
        frm.refresh_field("model");
        return;
      }

      const preferredValue =
        selected_manufacturer_model &&
        options.includes(selected_manufacturer_model)
          ? selected_manufacturer_model
          : frm.doc.manufacturer_model &&
              options.includes(frm.doc.manufacturer_model)
            ? frm.doc.manufacturer_model
            : null;

      if (preferredValue) {
        frm.set_value("manufacturer_model", preferredValue);
      } else if (options.length === 1) {
        frm.set_value("manufacturer_model", options[0]);
      }
    },
  });
};

njqca.get_model = function (
  manufacturer_model,
  item_group = null,
  brand = null,
  components = null,
) {
  const isDesktop = (item_group || "").trim().toLowerCase() === "desktops";

  frappe.call({
    method: "nj_features.nj_features.doctype.njqca.njqca.get_model",
    args: {
      manufacturer_model: manufacturer_model,
      item_group: item_group,
      brand: brand,
      components: components || (cur_frm ? cur_frm.doc.njqca_item_component : null),
    },
    callback: function (r) {
      const model_list = Array.isArray(r.message) ? r.message : [];
      const options = model_list.map((item) => item.model).filter(Boolean);

      cur_frm.set_df_property(
        "model",
        "options",
        options.length ? [""].concat(options).join("\n") : "\n",
      );

      if (!options.length) {
        cur_frm.set_value("model", "");
        cur_frm.refresh_field("model");
        return;
      }

      const preferredValue =
        cur_frm.doc.model && options.includes(cur_frm.doc.model)
          ? cur_frm.doc.model
          : options.length === 1
            ? options[0]
            : null;

      if (preferredValue) {
        cur_frm.set_value("model", preferredValue);
        cur_frm.set_df_property(
          "model",
          "read_only",
          options.length === 1 ? 1 : 0,
        );
      } else {
        cur_frm.set_df_property("model", "read_only", 0);

        $('[data-fieldname="model"]').focus().closest(".control-input").css({
          "border-radius": "0.25rem",
          border: "2px solid rgba(173, 216, 230, 0.5)",
        });

        frappe.show_alert({
          message: __("Select Model"),
          indicator: "green",
        });
      }

      if (isDesktop && cur_frm.doc.model) {
        cur_frm.set_value("manufacturer_model", cur_frm.doc.model);
      }

      cur_frm.events.model(cur_frm);
      cur_frm.refresh_field("model");
    },
  });
};

function generateAdaptorItemCode(frm, cdt, cdn, child) {
  const item_templates = child.item_template;
  const row_name = child.reference_row_name;

  let Brand = child.brand;
  let waltage = child.wattage_capacity;
  let adaptor_pins = child.adapter_pin_type;
  let grade = child.grade;

  const adaptor_properties = [
    {
      Brand: Brand,
      "Wattage Capacity": waltage,
      "Adapter Pin Type": adaptor_pins,
      Grade: grade,
    },
  ];

  if (Brand && waltage && adaptor_pins && grade) {
    frappe.call({
      method:
        "nj_features.nj_features.doctype.njqca.njqca.get_variant_from_value",
      args: { item_template: item_templates, args: adaptor_properties },
      callback: function (r) {
        if (r.message) {
          if (r.message.error) {
            frappe.utils.play_sound("error");
            var errorMessageString = "Item code not found: " + r.message.error;
            var errorDiv = $('<div class="form-message red"></div>').html(
              errorMessageString,
            );
            $(frm.layout.wrapper).find(".form-message.red").remove();
            $(frm.layout.wrapper).prepend(errorDiv);
            frappe.model.set_value(cdt, cdn, "calculated_item_code", "");
            frappe.show_alert(
              {
                message: __(
                  "Item code not found: <b> " + r.message.error + "</b>",
                ),
                indicator: "red",
              },
              10,
            );
          } else {
            frappe.model.set_value(cdt, cdn, "calculated_item_code", r.message);
            if (r.message) {
              frm.set_value("fetched_adaptor_item_code", 1);
              frm.refresh_field("fetched_adaptor_item_code");
            }
          }
        }
      },
    });
  } else {
    frappe.utils.play_sound("error");
    var missingFieldsMessage =
      "Please fill all the required fields in Adaptor.";
    var errorDiv = $('<div class="form-message red"></div>').html(
      missingFieldsMessage,
    );
    $(frm.layout.wrapper).find(".form-message.red").remove();
    $(frm.layout.wrapper).prepend(errorDiv);
  }
}

function generateStorageItemCode(frm, cdt, cdn, child) {
  const item_template = child.item_template;
  const row_name = child.reference_row_name;

  let storage_type = child.storage_type;
  let storage_capacity = child.storage_capacity;
  let storage_interface = child.storage_interface;
  let storage_length = child.storage_length;
  let grade = child.grade;

  const storage_properties = [
    {
      "Storage Type": storage_type,
      "Storage Interface": storage_interface,
      "Storage Capacity": storage_capacity,
      "Storage Length": storage_length,
      Grade: grade,
    },
  ];

  if (
    storage_type &&
    storage_capacity &&
    storage_interface &&
    storage_length &&
    grade
  ) {
    frappe.call({
      method:
        "nj_features.nj_features.doctype.njqca.njqca.get_variant_from_value",
      args: { item_template: item_template, args: storage_properties },
      callback: function (r) {
        if (r.message) {
          if (r.message.error) {
            frappe.utils.play_sound("error");
            var errorMessageString = "Item code not found: " + r.message.error;
            var errorDiv = $('<div class="form-message red"></div>').html(
              errorMessageString,
            );
            $(frm.layout.wrapper).find(".form-message.red").remove();
            $(frm.layout.wrapper).prepend(errorDiv);
            frappe.model.set_value(cdt, cdn, "calculated_item_code", "");
            frappe.show_alert(
              {
                message: __(
                  "Item code not found: <b> " + r.message.error + "</b>",
                ),
                indicator: "red",
              },
              10,
            );
          } else {
            frappe.model.set_value(cdt, cdn, "calculated_item_code", r.message);
            if (r.message) {
              frm.set_value("merged_storage_item_code", 0);
              frm.refresh_field("merged_storage_item_code");
            }
          }
        }
      },
    });
  } else {
    var missingFieldsMessage =
      "Please fill all the required fields in Storage.";
    frappe.utils.play_sound("error");
    var errorDiv = $('<div class="form-message red"></div>').html(
      missingFieldsMessage,
    );
    $(frm.layout.wrapper).find(".form-message.red").remove();
    $(frm.layout.wrapper).prepend(errorDiv);
  }
}

function generateProcessorItemCode(frm, cdt, cdn, child) {
  const item_template = child.item_template;
  const row_name = child.reference_row_name;

  let processor_type = child.processor_type;
  let grade = child.grade;

  const processor_properties = [
    { "Processor Type": processor_type, Grade: grade },
  ];

  if (processor_type && grade) {
    frappe.call({
      method:
        "nj_features.nj_features.doctype.njqca.njqca.get_variant_from_value",
      args: { item_template: item_template, args: processor_properties },
      callback: function (r) {
        if (r.message) {
          if (r.message.error) {
            frappe.utils.play_sound("error");
            var errorMessageString = "Item code not found: " + r.message.error;
            var errorDiv = $('<div class="form-message red"></div>').html(
              errorMessageString,
            );
            $(frm.layout.wrapper).find(".form-message.red").remove();
            $(frm.layout.wrapper).prepend(errorDiv);
            frappe.show_alert(
              {
                message: __(
                  "Item code not found: <b> " + r.message.error + "</b>",
                ),
                indicator: "red",
              },
              10,
            );
            frappe.model.set_value(cdt, cdn, "calculated_item_code", "");
          } else {
            frappe.model.set_value(cdt, cdn, "calculated_item_code", r.message);
            if (r.message) {
              frm.set_value("fetched_processor_item_code", 0);
              frm.refresh_field("fetched_processor_item_code");
            }
          }
        }
      },
    });
  } else {
    frappe.utils.play_sound("error");
    var missingFieldsMessage =
      "Please fill all the required fields in Processor.";
    var errorDiv = $('<div class="form-message red"></div>').html(
      missingFieldsMessage,
    );
    $(frm.layout.wrapper).find(".form-message.red").remove();
    $(frm.layout.wrapper).prepend(errorDiv);
  }
}

function generateDisplayItemCode(frm, cdt, cdn, child) {
  const item_template = child.item_template;
  const row_name = child.reference_row_name;
  let model = child.model;
  let display_tech = child.display_tech;
  let display_pin_type = child.display_pin_type;
  let display_size = child.display_size;
  let resolution = child.resolution;
  let thickness = child.thickness;
  let display_bracket = child.display_bracket;
  let grade = child.grade;

  const display_properties = [
    {
      MODEL: model,
      "Display Tech": display_tech,
      "Display PIN Type": display_pin_type,
      "Display Size": display_size,
      Resolution: resolution,
      Thickness: thickness,
      "Display Bracket": display_bracket,
      Grade: grade,
    },
  ];

  if (
    display_tech &&
    display_pin_type &&
    display_size &&
    resolution &&
    thickness &&
    display_bracket &&
    grade
  ) {
    frappe.call({
      method:
        "nj_features.nj_features.doctype.njqca.njqca.get_variant_from_value",
      args: { item_template: item_template, args: display_properties },
      callback: function (r) {
        if (r.message) {
          if (r.message.error) {
            frappe.utils.play_sound("error");
            var errorMessageString = "Item code not found: " + r.message.error;
            var errorDiv = $('<div class="form-message red"></div>').html(
              errorMessageString,
            );
            $(frm.layout.wrapper).find(".form-message.red").remove();
            $(frm.layout.wrapper).prepend(errorDiv);
            frappe.model.set_value(cdt, cdn, "calculated_item_code", "");
            frappe.show_alert(
              {
                message: __(
                  "Item code not found: <b> " + r.message.error + "</b>",
                ),
                indicator: "red",
              },
              10,
            );
          } else {
            frappe.model.set_value(cdt, cdn, "calculated_item_code", r.message);
            if (r.message) {
              frm.set_value("fetched_display_item_code", 1);
              frm.refresh_field("fetched_display_item_code");
            }
          }
        }
      },
    });
  } else {
    frappe.utils.play_sound("error");
    var missingFieldsMessage =
      "One or more required attributes are not filled in Display.";
    var errorDiv = $('<div class="form-message red"></div>').html(
      missingFieldsMessage,
    );
    $(frm.layout.wrapper).find(".form-message.red").remove();
    $(frm.layout.wrapper).prepend(errorDiv);
  }
}

function generateRamItemCode(frm, cdt, cdn, child) {
  const item_template = child.item_template;
  const row_name = child.reference_row_name;

  const ram_properties = [
    {
      "RAM Type": child.ram_type,
      "RAM Capacity": child.ram_capacity,
      "RAM Speed": child.ram_speed,
      Grade: child.grade,
    },
  ];
  if (child.ram_type && child.ram_capacity && child.ram_speed && child.grade) {
    frappe.call({
      method:
        "nj_features.nj_features.doctype.njqca.njqca.get_variant_from_value",
      args: { item_template: item_template, args: ram_properties },
      callback: function (r) {
        if (r.message) {
          if (r.message.error) {
            frappe.utils.play_sound("error");
            var errorMessageString = "Item code not found: " + r.message.error;
            var errorDiv = $('<div class="form-message red"></div>').html(
              errorMessageString,
            );
            $(frm.layout.wrapper).find(".form-message.red").remove();
            $(frm.layout.wrapper).prepend(errorDiv);
            frappe.model.set_value(cdt, cdn, "calculated_item_code", "");
            frappe.show_alert(
              {
                message: __(
                  "Item code not found: <b> " + r.message.error + "</b>",
                ),
                indicator: "red",
              },
              10,
            );
          } else {
            frappe.model.set_value(cdt, cdn, "calculated_item_code", r.message);
            if (r.message) {
              frm.set_value("merged_ram_item_code", 0);
              frm.refresh_field("merged_ram_item_code");
            }
          }
        }
      },
    });
  } else {
    frappe.utils.play_sound("error");
    var missingFieldsMessage = "Please fill all the required fields in RAM.";
    var errorDiv = $('<div class="form-message red"></div>').html(
      missingFieldsMessage,
    );
    $(frm.layout.wrapper).find(".form-message.red").remove();
    $(frm.layout.wrapper).prepend(errorDiv);
  }
}

frappe.ui.form.on("NJQCA Display", {
  njqca_display_add: function (frm, cdt, cdn) {
    setTimeout(() => show_checkbutton_for_field(frm, "njqca_display"), 300);
  },

  check_button: async function (frm, cdt, cdn) {
    let child = locals[cdt][cdn];
    let item_group = child.item_group;
    let grid = frm.get_field(child.parentfield);

    let d = new frappe.ui.Dialog({
      title: "Edit Display Attributes",
      fields: [
        {
          label: "Model",
          fieldname: "model",
          fieldtype: "Select",
          options: ["Loading..."],
          default: "",
        },
        {
          label: "Display Tech",
          fieldname: "display_tech",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.display_tech || "",
        },
        {
          label: "Display PIN Type",
          fieldname: "display_pin_type",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.display_pin_type || "",
        },
        {
          label: "Display Size",
          fieldname: "display_size",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.display_size || "",
        },
        {
          label: "Resolution",
          fieldname: "resolution",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.resolution || "",
        },
        {
          label: "Thickness",
          fieldname: "thickness",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.thickness || "",
        },
        {
          label: "Display Bracket",
          fieldname: "display_bracket",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.display_bracket || "",
        },
        {
          label: "Grade",
          fieldname: "grade",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.grade || "",
        },
      ],
      primary_action_label: "Save",
      primary_action(values) {
        Object.keys(values).forEach((fieldname) => {
          if (values[fieldname]) {
            frm.set_df_property(
              grid.df.fieldname,
              "options",
              values[fieldname],
              frm.docname,
              fieldname,
              cdn,
            );
          }
        });

        frm.refresh_field(grid.df.fieldname);

        // fetch_item_template_disp_adp(
        //   frm,
        //   item_group,
        //   function (item_template_data) {
        //     frappe.model.set_value(
        //       cdt,
        //       cdn,
        //       "item_template",
        //       item_template_data,
        //     );

        //     frm.refresh_field(grid.df.fieldname);

        //     generateDisplayItemCode(frm, cdt, cdn, child);
        //   },
        // );

        d.hide();
      },
    });

    const fieldToAttribute = {
      model: "Model",
      display_tech: "Display Tech",
      display_pin_type: "Display PIN Type",
      display_size: "Display Size",
      resolution: "Resolution",
      thickness: "Thickness",
      display_bracket: "Display Bracket",
      grade: "Grade",
    };

    Object.keys(fieldToAttribute).forEach(async (fieldname) => {
      try {
        let attributeName = fieldToAttribute[fieldname];
        let options = await get_options(attributeName, item_group);

        d.set_df_property(fieldname, "options", options);

        if (child[fieldname]) {
          d.set_value(fieldname, child[fieldname]);
        }
      } catch (error) {
        console.error(`Error loading options for ${fieldname}:`, error);
      }
    });

    d.show();
  },
});

async function get_options(attributeName, item_group) {
  return new Promise((resolve, reject) => {
    frappe.call({
      method:
        "nj_features.nj_features.doctype.njqca.njqca.get_options_for_label",
      args: {
        label: attributeName,
        item_template: cur_frm.doc.item_template,
        item_group: item_group,
      },
      callback: function (r) {
        console.log(`Options for ${attributeName}:`, r.message);

        if (r.message && r.message.error) {
          frappe.show_alert({ message: r.message.error, indicator: "red" }, 10);
          return;
        }

        if (r.message && Array.isArray(r.message)) {
          let filtered = r.message.filter(
            (opt) => String(opt).toLowerCase() !== "unknown",
          );

          // Add 2666 GHZ only for RAM Speed
          if (attributeName === "RAM Speed") {
            filtered.push("2666 GHZ");
          }

          // Remove duplicates
          filtered = [...new Set(filtered)];

          resolve(filtered);
        } else {
          resolve([]);
        }
      },
      error: function (err) {
        console.error("API Error:", err);
        reject(err);
      },
    });
  });
}

function fetch_item_template_disp_adp(frm, item_group, callback) {
  if (!frm.doc.serial_no) {
    frappe.msgprint("Please Scan the Serial No.");
    return;
  }

  frappe.call({
    method:
      "nj_features.nj_features.doctype.njqca.njqca.get_serial_no_attribute_data",
    args: {
      serial_no: frm.doc.serial_no,
      item_group: item_group,
      item_template: frm.doc.item_template,
    },
    callback: function (r) {
      if (r.message && r.message.length > 0) {
        callback(r.message[0].item_template);
      } else {
        console.warn("No item template found.");
      }
    },
    error: function (err) {
      console.error("API Error:", err);
    },
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// EXT-NJ Serial Linkage via BIOS
// ─────────────────────────────────────────────────────────────────────────────

function check_and_handle_ext_linkage(frm) {
  // Only run for non-EXT NJQCAs (skip if this NJQCA itself belongs to an EXT/RFQ serial)
  if (!frm.doc.bios_serialno || !frm.doc.serial_no || frm.doc.rfq_id) return;

  frappe.call({
    method:
      "nj_features.nj_features.doctype.njqca.njqca.check_ext_serial_linkage",
    args: {
      bios_serial_no: frm.doc.bios_serialno,
      nj_serial_no: frm.doc.serial_no,
    },
    callback: function (r) {
      if (!r.message || !r.message.found) return;
      // CASE D: already linked to each other — silently skip
      if (r.message.already_linked) return;

      // CASE C: EXT found but not yet linked — ask the user
      let ext_serial = r.message.ext_serial;
      frappe.confirm(
        __(
          `BIOS <b>${frm.doc.bios_serialno}</b> is already mapped to EXT serial 
          <b>${ext_serial}</b>.<br><br>
          Do you want to link <b>${ext_serial}</b> component data to NJ serial 
          <b>${frm.doc.serial_no}</b>?`,
        ),
        // YES
        function () {
          frappe.call({
            method:
              "nj_features.nj_features.doctype.njqca.njqca.link_ext_to_nj_serial",
            args: {
              ext_serial_no: ext_serial,
              nj_serial_no: frm.doc.serial_no,
              njqca_name: frm.doc.name,
            },
            callback: function (r2) {
              if (r2.message && r2.message.success) {
                frm.set_value("linked_ext", ext_serial);
                frm.refresh_field("linked_ext");
                frappe.show_alert(
                  {
                    message: __(
                      `EXT serial <b>${ext_serial}</b> linked. Component data copied to <b>${frm.doc.serial_no}</b>.`,
                    ),
                    indicator: "green",
                  },
                  7,
                );
              }
            },
          });
        },
        // NO — do nothing, proceed normally
        function () {},
      );
    },
  });
}

frappe.ui.form.on("NJQCA Adaptor", {
  njqca_adaptor_add: function (frm, cdt, cdn) {
    setTimeout(() => show_checkbutton_for_field(frm, "njqca_adaptor"), 300);
  },

  check_button: async function (frm, cdt, cdn) {
    let child = locals[cdt][cdn];
    let item_group = "Laptop Adaptors";
    let grid = frm.get_field(child.parentfield);

    let d = new frappe.ui.Dialog({
      title: "Edit Adaptor Attributes",
      fields: [
        {
          label: "Brand",
          fieldname: "brand",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.brand || "",
          reqd: 1,
        },
        {
          label: "Wattage Capacity",
          fieldname: "wattage_capacity",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.wattage_capacity || "",
          reqd: 1,
        },
        {
          label: "Adapter Pin Type",
          fieldname: "adapter_pin_type",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.adapter_pin_type || "",
          reqd: 1,
        },
        {
          label: "Grade",
          fieldname: "grade",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.grade || "",
          reqd: 1,
        },
      ],
      primary_action_label: "Save",
      primary_action(values) {
        Object.keys(values).forEach((fieldname) => {
          if (values[fieldname]) {
            frm.set_df_property(
              grid.df.fieldname,
              "options",
              values[fieldname],
              frm.docname,
              fieldname,
              cdn,
            );
          }
        });

        frm.refresh_field(grid.df.fieldname);

        fetch_item_template_disp_adp(
          frm,
          item_group,
          function (item_template_data) {
            frappe.model.set_value(
              cdt,
              cdn,
              "item_template",
              item_template_data,
            );

            frm.refresh_field(grid.df.fieldname);

            generateAdaptorItemCode(frm, cdt, cdn, child);
          },
        );

        d.hide();
      },
    });

    const fieldToAttribute = {
      brand: "Brand",
      wattage_capacity: "Wattage Capacity",
      adapter_pin_type: "Adapter Pin Type",
      grade: "Grade",
    };

    Object.keys(fieldToAttribute).forEach(async (fieldname) => {
      try {
        let attributeName = fieldToAttribute[fieldname];
        let options = await get_options(attributeName, item_group);

        d.set_df_property(fieldname, "options", options);

        if (child[fieldname]) {
          d.set_value(fieldname, child[fieldname]);
        }
      } catch (error) {
        console.error(`Error loading options for ${fieldname}:`, error);
      }
    });

    d.show();
  },
});

frappe.ui.form.on("NJQCA Laptop Storage", {
  check_button: async function (frm, cdt, cdn) {
    let child = locals[cdt][cdn];
    if (!child.item_template) {
      frappe.throw(
        __(
          "Item Template is not defined. Please select an Item Template first.",
        ),
      );
      return;
    }
    let item_group = child.item_group;
    let grid = frm.get_field(child.parentfield);

    const relationshipMap = {
      interfaces: {
        SATA: ['2.5"', "2280", "2242", "2230"],
        "M.2 NVME": ["2242", "2280"],
        "M.2 SATA": ["2242", "2230"],
        "M.2 PCI": ["2280"],
        "M.SATA": ["2242"],
      },
      lengths: {
        '2.5"': ["SATA"],
        2242: ["M.2 NVME", "M.2 SATA", "M.SATA"],
        2280: ["M.2 NVME", "M.2 PCI"],
        2230: ["M.2 SATA"],
      },
    };

    const storage_filters = {
      SSD: {
        interfaces: ["SATA", "M.2 NVME", "M.2 SATA", "M.2 PCI", "M.SATA"],
        lengths: ["2280", "2242", "22110", '2.5"', '3.5"'],
      },
      HDD: {
        interfaces: ["SATA"],
        lengths: ['2.5"', "2280", "2242", "2230", '3.5"'],
      },
    };

    const updateFieldOptions = (sourceField, targetField) => {
      const sourceValue = d.get_value(sourceField);
      const storageType = d.get_value("storage_type");

      let baseOptions = [];
      if (targetField === "storage_interface") {
        baseOptions = storage_filters[storageType]?.interfaces || [];
      } else if (targetField === "storage_length") {
        baseOptions = storage_filters[storageType]?.lengths || [];
      }

      if (sourceValue) {
        let relationshipKey =
          sourceField === "storage_interface" ? "interfaces" : "lengths";
        let allowedValues = relationshipMap[relationshipKey][sourceValue] || [];

        let filteredOptions = baseOptions.filter((option) =>
          allowedValues.includes(option),
        );
        d.set_df_property(targetField, "options", filteredOptions);

        if (filteredOptions.length === 1 && !d.get_value(targetField)) {
          d.set_value(targetField, filteredOptions[0]);
        }

        const currentValue = d.get_value(targetField);
        if (currentValue && !filteredOptions.includes(currentValue)) {
          d.set_value(targetField, "");
        }
      } else {
        d.set_df_property(targetField, "options", baseOptions);
      }
    };

    let d = new frappe.ui.Dialog({
      title: "Laptop Storage Attributes",
      fields: [
        {
          label: "Storage Type",
          fieldname: "storage_type",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.storage_type || "",
          reqd: !child.storage_type,
        },
        {
          label: "Storage Interface",
          fieldname: "storage_interface",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.storage_interface || "",
          reqd: !child.storage_interface,
          // read_only: !!child.storage_interface,
        },
        {
          label: "Storage Capacity",
          fieldname: "storage_capacity",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.storage_capacity || "",
          reqd: !child.storage_capacity,
          read_only: !!child.storage_capacity,
        },
        {
          label: "Storage Length",
          fieldname: "storage_length",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.storage_length || "",
          reqd: !child.storage_length,
          read_only: !!child.storage_length,
        },
        {
          label: "Grade",
          fieldname: "grade",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.grade || "",
          reqd: !child.grade,
          // read_only: !!child.grade,   // 👈 add this
        },
      ],
      primary_action_label: "Save",
      primary_action(values) {
        Object.keys(values).forEach((fieldname) => {
          if (values[fieldname]) {
            frm.set_df_property(
              grid.df.fieldname,
              "options",
              values[fieldname],
              frm.docname,
              fieldname,
              cdn,
            );
            frappe.model.set_value(cdt, cdn, fieldname, values[fieldname]);
          }
        });
        frm.refresh_field(grid.df.fieldname);
        generateStorageItemCode(frm, cdt, cdn, child);
        d.hide();
      },
    });

    // ─── Inject reference image below dialog title ────────────────────────
    frappe.db.get_value("File", "bd09102d7c", "file_url", function (r) {
      if (r && r.file_url) {
        const base_url = frappe.urllib.get_base_url();
        const img_url = r.file_url.startsWith("http")
          ? r.file_url
          : base_url + r.file_url;

        const $img = $(`
          <div style="
            text-align: center;
            padding: 8px 16px 4px 16px;
            border-bottom: 1px solid #444;
            margin-bottom: 4px;
          ">
            <img
              src="${img_url}"
              alt="Storage Reference"
              style="
                width: 600px;
                max-width: 100%;
                border-radius: 6px;
                border: 1px solid #555;
                object-fit: contain;
              "
            />
          </div>
        `);

        d.$wrapper.find(".modal-header").after($img);
      }
    });
    // ─────────────────────────────────────────────────────────────────────

    const fieldToAttribute = {
      storage_type: "Storage Type",
      storage_interface: "Storage Interface",
      storage_capacity: "Storage Capacity",
      storage_length: "Storage Length",
      grade: "Grade",
    };

    for (const [fieldname, attributeName] of Object.entries(fieldToAttribute)) {
      try {
        if (
          fieldname !== "storage_interface" &&
          fieldname !== "storage_length"
        ) {
          let options = await get_options(attributeName, item_group);
          d.set_df_property(fieldname, "options", options);
        }

        if (child[fieldname]) {
          d.set_value(fieldname, child[fieldname]);
        }
      } catch (error) {
        console.error(`Error loading options for ${fieldname}:`, error);
      }
    }

    try {
      let storageTypeOptions = await get_options("Storage Type", item_group);
      d.set_df_property("storage_type", "options", storageTypeOptions);

      if (child.storage_type) {
        d.set_value("storage_type", child.storage_type);

        if (storage_filters[child.storage_type]) {
          d.set_df_property(
            "storage_interface",
            "options",
            storage_filters[child.storage_type].interfaces,
          );

          d.set_df_property(
            "storage_length",
            "options",
            storage_filters[child.storage_type].lengths,
          );
        }
      } else {
        let interfaceOptions = await get_options(
          "Storage Interface",
          item_group,
        );
        let lengthOptions = await get_options("Storage Length", item_group);

        d.set_df_property("storage_interface", "options", interfaceOptions);
        d.set_df_property("storage_length", "options", lengthOptions);
      }
    } catch (error) {
      console.error("Error initializing storage type options:", error);
    }

    if (child.storage_interface) {
      d.set_value("storage_interface", child.storage_interface);
    }

    if (child.storage_length) {
      d.set_value("storage_length", child.storage_length);
    }

    d.show();
  },

  storage_type: function (frm, cdt, cdn) {
    let child = locals[cdt][cdn];
    if (
      child.storage_type === "SSD" &&
      child.update_variant &&
      (!frm.doc.repack_item_code ||
        (!frm.doc.repack_item_code.toLowerCase().includes("ssd") &&
          child.variant_15 !== "SSD"))
    ) {
      frappe.model.set_value(
        "NJQCA Child",
        child.update_variant,
        "variant_15",
        "SSD",
      );
    } else if (child.storage_type !== "SSD" && child.update_variant) {
      frappe.model.set_value(
        "NJQCA Child",
        child.update_variant,
        "variant_15",
        "",
      );
    }
  },
  item_template: function (frm, cdt, cdn) {
    let child = locals[cdt][cdn];
    generateStorageItemCode(frm, cdt, cdn, child);
  },
});

function shouldBeRequired(child) {
  return (
    !child.fetched_item_code ||
    (child.fetched_item_code &&
      child.calculated_item_code &&
      child.fetched_item_code !== child.calculated_item_code)
  );
}

function validate_mandatory_fields(frm) {
  if (!frm.doc.njqca_laptop_storage) return;

  frm.doc.njqca_laptop_storage.forEach((row, idx) => {
    if (shouldBeRequired(row)) {
      [
        "storage_type",
        "storage_interface",
        "storage_capacity",
        "storage_length",
        "grade",
      ].forEach((field) => {
        frm.fields_dict.njqca_laptop_storage.grid.grid_rows[idx].doc[field] =
          frm.fields_dict.njqca_laptop_storage.grid.grid_rows[idx].doc[field] ||
          "";

        frm.fields_dict.njqca_laptop_storage.grid.grid_rows[idx].toggle_reqd(
          field,
          true,
        );
      });
    }
  });
}

frappe.ui.form.on("NJQCA Laptop Ram", {
  check_button: async function (frm, cdt, cdn) {
    let child = locals[cdt][cdn];
    if (!child.item_template) {
      frappe.throw(
        __(
          "Item Template is not defined. Please select an Item Template first.",
        ),
      );
      return;
    }
    let item_group = child.item_group;
    let grid = frm.get_field(child.parentfield);

    let d = new frappe.ui.Dialog({
      title: "Laptop RAM Attributes",
      fields: [
        {
          label: "RAM Type",
          fieldname: "ram_type",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.ram_type || "",
          reqd: !child.ram_type,
          read_only: !!child.ram_type,
        },
        {
          label: "RAM Capacity",
          fieldname: "ram_capacity",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.ram_capacity || "",
          reqd: !child.ram_capacity,
          read_only: !!child.ram_capacity,
        },
        {
          label: "RAM Speed",
          fieldname: "ram_speed",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.ram_speed || "",
          reqd: !child.ram_speed,
        },
        {
          label: "Grade",
          fieldname: "grade",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.grade || "",
          reqd: !child.grade,
        },
      ],
      primary_action_label: "Save",
      primary_action(values) {
        Object.keys(values).forEach((fieldname) => {
          if (values[fieldname]) {
            frm.set_df_property(
              grid.df.fieldname,
              "options",
              values[fieldname],
              frm.docname,
              fieldname,
              cdn,
            );
            frappe.model.set_value(cdt, cdn, fieldname, values[fieldname]);
          }
        });

        frm.refresh_field(grid.df.fieldname);

        generateRamItemCode(frm, cdt, cdn, child);

        d.hide();
      },
    });

    const fieldToAttribute = {
      ram_type: "RAM Type",
      ram_capacity: "RAM Capacity",
      ram_speed: "RAM Speed",
      grade: "Grade",
    };

    Object.keys(fieldToAttribute).forEach(async (fieldname) => {
      try {
        let attributeName = fieldToAttribute[fieldname];
        let options = await get_options(attributeName, item_group);

        d.set_df_property(fieldname, "options", options);

        if (child[fieldname]) {
          d.set_value(fieldname, child[fieldname]);
        }
      } catch (error) {
        console.error(`Error loading options for ${fieldname}:`, error);
      }
    });
    d.show();
  },
  item_template: function (frm, cdt, cdn) {
    let child = locals[cdt][cdn];
    generateRamItemCode(frm, cdt, cdn, child);
  },
});

frappe.ui.form.on("NJQCA PROCESSOR", {
  check_button: async function (frm, cdt, cdn) {
    let child = locals[cdt][cdn];
    let item_group = child.item_group;
    let grid = frm.get_field(child.parentfield);

    let d = new frappe.ui.Dialog({
      title: "Processor Attributes",
      fields: [
        {
          label: "Processor Type",
          fieldname: "processor_type",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.processor_type || "",
          reqd: !child.processor_type,
          read_only: !!child.processor_type,
        },
        {
          label: "Grade",
          fieldname: "grade",
          fieldtype: "Select",
          options: ["Loading..."],
          default: child.grade || "",
          reqd: !child.grade,
        },
      ],
      primary_action_label: "Save",
      primary_action(values) {
        Object.keys(values).forEach((fieldname) => {
          if (values[fieldname]) {
            frm.set_df_property(
              grid.df.fieldname,
              "options",
              values[fieldname],
              frm.docname,
              fieldname,
              cdn,
            );
            frappe.model.set_value(cdt, cdn, fieldname, values[fieldname]);
          }
        });

        frm.refresh_field(grid.df.fieldname);

        // frappe.model.set_value(cdt, cdn, "item_template", "LAPTOP PROCESSOR");
        frm.refresh_field(grid.df.fieldname);
        generateProcessorItemCode(frm, cdt, cdn, child);

        d.hide();
      },
    });

    const fieldToAttribute = {
      processor_type: "Processor Type",
      grade: "Grade",
    };

    Object.keys(fieldToAttribute).forEach(async (fieldname) => {
      try {
        let attributeName = fieldToAttribute[fieldname];
        let options = await get_options(attributeName, item_group);

        d.set_df_property(fieldname, "options", options);

        if (child[fieldname]) {
          d.set_value(fieldname, child[fieldname]);
        }
      } catch (error) {
        console.error(`Error loading options for ${fieldname}:`, error);
      }
    });

    d.show();
  },
});

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
      `<button class='btn btn-primary btn-xs check-button'
				style='
					padding: 2px 10px;
					font-size: 12px;
					line-height: 1.5;
					border-radius: 3px;
					background-color: #589ffc;
					border: none;
					width: auto;
					min-width: 50px;'>Check</button>`,
    );

    $checkButtonCell.find(".check-button").click(function () {
      let cdn = $row.attr("data-name");
      let cdt = field.grid.doctype;
      frm.script_manager.trigger("check_button", cdt, cdn);
    });
  });
}

function setup_merge_checkbox_handler(frm, child_name) {
  const field = frm.fields_dict[child_name];

  if (!field || !field.grid) return;

  const grid = field.grid;

  bind_checkbox_listener(grid, child_name);

  grid.on_grid_rendered = function (g) {
    bind_checkbox_listener(g, child_name);
  };
}

function bind_checkbox_listener(grid, child_name) {
  const formGrid = grid.wrapper;

  if (!formGrid.hasClass("merge-handler-bound")) {
    formGrid.addClass("merge-handler-bound");

    formGrid.on("click", ".grid-row-check", function () {
      setTimeout(() => {
        const selected = grid.get_selected_children();

        if (selected.length === 2) {
          show_merge_button(grid, selected, child_name);
          remove_delete_button(grid);
        } else if (selected.length === 1) {
          show_delete_button(grid, selected, child_name);
          remove_merge_button(grid);
        } else {
          remove_merge_button(grid);
          remove_delete_button(grid);
        }
      }, 100);
    });
  }
}

function show_delete_button(grid, selected_rows, child_name) {
  remove_delete_button(grid);

  const [row] = selected_rows;
  if (!row) return;

  const allowed_roles = ["Process Engineer", "Ops Manager"];
  const has_permission = frappe.user_roles.some((role) =>
    allowed_roles.includes(role),
  );
  if (!has_permission) return;

  const isCalcItemCode =
    row.fetched_item_code == null ||
    row.fetched_item_code === "" ||
    row.fetched_item_code.trim() === "";

  const isNotMerged = row.merged == 0 || row.merged == null;

  if (isCalcItemCode && isNotMerged) {
    const btn =
      $(`<button class="btn btn-xs btn-danger delete-btn" style="margin-right: 8px;">
            Delete
        </button>`);

    grid.wrapper.find(".grid-buttons").prepend(btn);

    btn.on("click", function () {
      frappe.confirm("Are you sure you want to delete this row?", function () {
        const frm = cur_frm;
        const field = frm.fields_dict[child_name];

        if (!field || !field.grid) {
          frappe.show_alert(
            { message: "Could not find grid: " + child_name, indicator: "red" },
            5,
          );
          return;
        }

        const gridRow = field.grid.grid_rows_by_docname[row.name];
        if (!gridRow) {
          frappe.show_alert(
            { message: "Row not found in grid.", indicator: "red" },
            5,
          );
          return;
        }

        gridRow.remove();
        field.grid.refresh();
        frm.refresh_field(child_name);
        remove_delete_button(grid);

        frappe.show_alert(
          { message: "Row deleted successfully.", indicator: "green" },
          5,
        );
      });
    });
  }
}

function remove_delete_button(grid) {
  grid.wrapper.find(".delete-btn").remove();
}

function show_merge_button(grid, selected_rows, child_name) {
  remove_merge_button(grid);

  const btn =
    $(`<button class="btn btn-xs btn-primary merge-btn" style="margin-right: 8px;">
        Merge
    </button>`);

  grid.wrapper.find(".grid-buttons").prepend(btn);

  btn.on("click", function () {
    handle_merge(grid.frm || cur_frm, selected_rows, child_name);
  });
}

function remove_merge_button(grid) {
  grid.wrapper.find(".merge-btn").remove();
}

async function handle_merge(frm, selected_rows, child_name) {
  console.log("handle_merge_child__name__ -------------", child_name);

  const [row1, row2] = selected_rows;

  if (!row1.fetched_item_code && !row2.fetched_item_code) {
    frappe.show_alert(
      {
        message: "No Fetched Item Code(Serial No.) found in either row(s).",
        indicator: "red",
      },
      10,
    );
    return;
  }

  if (row2.merged === 1 || row1.merged === 1) {
    frappe.show_alert(
      { message: "One of the rows has already been merged.", indicator: "red" },
      10,
    );
    return;
  }

  let source_row, target_row;

  if (row1.fetched_item_code && !row2.fetched_item_code) {
    source_row = row1;
    target_row = row2;
  } else if (row2.fetched_item_code && !row1.fetched_item_code) {
    source_row = row2;
    target_row = row1;
  }

  // ─── Validate attributes before merging ───────────────────────────────────
  if (source_row && source_row.component_serial_no) {
    const field_attribute_map = {
      njqca_laptop_ram: [
        { fieldname: "ram_type", attribute: "RAM Type" },
        { fieldname: "ram_capacity", attribute: "RAM Capacity" },
        { fieldname: "ram_speed", attribute: "RAM Speed" },
      ],
      njqca_laptop_storage: [
        { fieldname: "storage_type", attribute: "Storage Type" },
        { fieldname: "storage_interface", attribute: "Storage Interface" },
        { fieldname: "storage_capacity", attribute: "Storage Capacity" },
        { fieldname: "storage_length", attribute: "Storage Length" },
      ],
    };

    const fields_to_check = field_attribute_map[child_name];

    if (fields_to_check) {
      // Step 1: Check if target_row has all required fields filled
      for (const { fieldname, attribute } of fields_to_check) {
        if (!target_row[fieldname]) {
          frappe.show_alert(
            {
              message: `Please fill "${attribute}" in the other row before merging.`,
              indicator: "red",
            },
            10,
          );
          return;
        }
      }

      // Step 2: Fetch attributes using custom whitelisted method
      let item_attributes = {};
      try {
        const r = await frappe.call({
          method:
            "nj_features.nj_features.doctype.njqca.njqca.get_item_variant_attributes", // 👈 update this path if needed
          args: {
            item_code: source_row.fetched_item_code,
          },
        });

        if (r && r.message) {
          r.message.forEach((row) => {
            item_attributes[row.attribute] = row.attribute_value;
          });
        }
      } catch (e) {
        console.error("Error fetching item attributes:", e);
        frappe.show_alert(
          {
            message: "Error fetching item attributes. Please try again.",
            indicator: "red",
          },
          10,
        );
        return;
      }

      // Step 3: Compare target_row field values against fetched item attributes
      for (const { fieldname, attribute } of fields_to_check) {
        const fetched_value = item_attributes[attribute];
        const target_value = target_row[fieldname];

        if (fetched_value && target_value) {
          const normalize = (v) => String(v).trim().toLowerCase();

          if (normalize(fetched_value) !== normalize(target_value)) {
            frappe.show_alert(
              {
                message: `"${attribute}" does not match. Expected "${fetched_value}" but found "${target_value}". Please select the correct attribute before merging.`,
                indicator: "orange",
              },
              12,
            );
            return;
          }
        }
      }
    }
  }
  // ─── END validation ───────────────────────────────────────────────────────

  // Proceed with merge
  target_row.fetched_item_code = source_row.fetched_item_code;
  target_row.reference_docname = source_row.reference_docname;
  target_row.component_serial_no = source_row.component_serial_no;
  source_row.reference_docname = null;
  target_row.merged = 1;

  frm.fields_dict[child_name].grid.grid_rows_by_docname[
    source_row.name
  ].remove();
  update_empty_param_in_child(frm, source_row, target_row);
  frm.refresh_field(child_name);

  frappe.show_alert(
    { message: "Rows merged successfully.", indicator: "blue" },
    5,
  );

  if (child_name == "njqca_laptop_ram") {
    frm.set_value("merged_ram_item_code", 0);
    frm.refresh_field("merged_ram_item_code");
  }
  if (child_name == "njqca_laptop_storage") {
    frm.set_value("merged_storage_item_code", );
    frm.refresh_field("merged_storage_item_code");
  }
}

function update_empty_param_in_child(frm, source_row, target_row) {
  frappe.call({
    method:
      "nj_features.nj_features.doctype.njqca.njqca.get_empty_param_in_child",
    args: { item_code: target_row.fetched_item_code },
    callback: function (r) {
      if (r.message) {
        for (let key in r.message) {
          if (r.message.hasOwnProperty(key)) {
            if (
              target_row.reference_docname &&
              ((key == "grade" && target_row[key] != r.message[key]) ||
                !target_row[key])
            ) {
              frappe.model.set_value(
                target_row.doctype,
                target_row.name,
                key,
                r.message[key],
              );
            }
          }
        }
      }
    },
  });
}

// Reliability JS

function _key(s) {
  return (s || "").toString().trim().toLowerCase().replace(/\s+/g, " ");
}
function hasActualTestFile(frm) {
  const fileParams = new Set([
    "heavy_load_file_updated_name",
    "performance_file_updated_name",
    "sensors_file_updated_name",
    "y_cruncher_file_updated_name",
  ]);

  return (frm.doc.njqca_result_parameters || []).some((row) => {
    const parameter = _key(row.parameter);
    const value = (row.value || "").toString().trim();

    return fileParams.has(parameter) && value;
  });
}

function hasPerfOrHeavyLoadTestFile(frm) {
  const fileParams = new Set([
    "heavy_load_file_updated_name",
    "performance_file_updated_name",
    "sensors_file_updated_name",
  ]);

  return (frm.doc.njqca_result_parameters || []).some((row) => {
    const parameter = _key(row.parameter);
    const value = (row.value || "").toString().trim();

    return fileParams.has(parameter) && value;
  });
}

function getChildDoctype(frm) {
  return frm.fields_dict.njqca_result_parameters.df.options;
}

function getChildValueField(frm) {
  const childDoctype = getChildDoctype(frm);
  const candidates = [
    "value",
    "parameter_value",
    "param_value",
    "parameter_val",
  ];
  for (const f of candidates) {
    if (frappe.meta.has_field(childDoctype, f)) return f;
  }
  return "value";
}

function getChildUnitField(frm) {
  const childDoctype = getChildDoctype(frm);
  const candidates = ["units", "unit"];
  for (const f of candidates) {
    if (frappe.meta.has_field(childDoctype, f)) return f;
  }
  return "units";
}

function upsertResultParam(frm, change) {
  const valueField = getChildValueField(frm);
  const unitField = getChildUnitField(frm);

  const igKey = _key(change.item_group);
  const pKey = _key(change.parameter);

  const rows = frm.doc.njqca_result_parameters || [];

  // Use latest matching row if duplicate exists
  let existing = null;
  for (let i = rows.length - 1; i >= 0; i--) {
    const r = rows[i];
    if (_key(r.item_group) === igKey && _key(r.parameter) === pKey) {
      existing = r;
      break;
    }
  }

  if (existing) {
    existing.item_group = change.item_group;
    existing.parameter = change.parameter;
    existing[valueField] = change.value;

    if (change.units !== undefined) {
      existing[unitField] = change.units;
    }

    if (change.score !== undefined) {
      existing.score = change.score;
    }

    if (change.part_config_id !== undefined) {
      existing.part_config_id = change.part_config_id;
    }
  } else {
    const child = frm.add_child("njqca_result_parameters");
    child.item_group = change.item_group;
    child.parameter = change.parameter;
    child[valueField] = change.value;

    if (change.units !== undefined) {
      child[unitField] = change.units;
    }

    if (change.score !== undefined) {
      child.score = change.score;
    }

    if (change.part_config_id !== undefined) {
      child.part_config_id = change.part_config_id;
    }
  }
}

function applyChangesNoDuplicates(frm, changes) {
  if (!Array.isArray(changes) || !changes.length) return;

  const map = {};
  for (const c of changes) {
    const k = _key(c.item_group) + "||" + _key(c.parameter);
    map[k] = c;
  }

  Object.values(map).forEach((c) => upsertResultParam(frm, c));
}

function dedupeChildTable(frm) {
  const rows = frm.doc.njqca_result_parameters || [];
  if (!rows.length) return;

  const seen = new Set();
  const kept = [];

  for (let i = rows.length - 1; i >= 0; i--) {
    const r = rows[i];
    const k = _key(r.item_group) + "||" + _key(r.parameter);
    if (seen.has(k)) continue;
    seen.add(k);
    kept.push(r);
  }

  kept.reverse();
  frm.doc.njqca_result_parameters = kept;
}

const NJQCA_BARCODE_SCANNER_MESSAGE = "Please use the scanner to scan barcode.";

function setupNJQCABarcodeScannerOnly(frm) {
  const fieldname = "barcode";
  const field = frm.get_field(fieldname);
  if (!field || !field.$input || frm.doc.docstatus !== 0) return;

  const inputField = field.$input;
  let state = frm.__njqca_barcode_scanner_state;

  if (!state) {
    state = frm.__njqca_barcode_scanner_state = {
      chars: "",
      firstKeyTime: 0,
      lastKeyTime: 0,
      manualTimer: null,
      validValue: "",
      validUntil: 0,
      lastMessageAt: 0,
      suppressManualCheck: false,
    };
  }

  inputField.off(".njqca_barcode_scanner");

  inputField.on("paste.njqca_barcode_scanner", function (event) {
    event.preventDefault();
    clearNJQCABarcodeField(frm);
    showNJQCABarcodeScannerMessage(frm);
    return false;
  });

  inputField.on("beforeinput.njqca_barcode_scanner", function (event) {
    const inputType = event.originalEvent && event.originalEvent.inputType;
    if (inputType === "insertFromPaste" || inputType === "insertFromDrop") {
      event.preventDefault();
      clearNJQCABarcodeField(frm);
      showNJQCABarcodeScannerMessage(frm);
      return false;
    }
  });

  inputField.on("drop.njqca_barcode_scanner", function (event) {
    event.preventDefault();
    clearNJQCABarcodeField(frm);
    showNJQCABarcodeScannerMessage(frm);
    return false;
  });

  inputField.on("contextmenu.njqca_barcode_scanner", function (event) {
    event.preventDefault();
    showNJQCABarcodeScannerMessage(frm);
    return false;
  });

  inputField.on("keydown.njqca_barcode_scanner", function (event) {
    const now = Date.now();

    if (state.validValue && now > state.validUntil) {
      state.validValue = "";
      state.validUntil = 0;
    }

    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v") {
      event.preventDefault();
      clearNJQCABarcodeField(frm);
      showNJQCABarcodeScannerMessage(frm);
      return false;
    }

    if (event.key === "Enter") {
      const value = inputField.val().trim();
      const isScanner = isNJQCABarcodeScannerBurst(state, value, now);

      window.clearTimeout(state.manualTimer);
      state.manualTimer = null;

      if (!isScanner) {
        event.preventDefault();
        resetNJQCABarcodeScannerState(state);
        clearNJQCABarcodeField(frm);
        showNJQCABarcodeScannerMessage(frm);
        return false;
      }

      event.preventDefault();
      acceptNJQCABarcodeScannerValue(frm, value, state);
      return false;
    }

    if (isNJQCABarcodeControlKey(event)) {
      return true;
    }

    if (event.key.length !== 1) {
      return true;
    }

    if (!state.firstKeyTime) {
      state.firstKeyTime = now;
    }

    if (state.lastKeyTime && now - state.lastKeyTime > 350) {
      event.preventDefault();
      resetNJQCABarcodeScannerState(state);
      clearNJQCABarcodeField(frm);
      showNJQCABarcodeScannerMessage(frm);
      return false;
    }

    state.lastKeyTime = now;
    state.chars += event.key;

    window.clearTimeout(state.manualTimer);
    state.manualTimer = window.setTimeout(function () {
      if (state.chars) {
        const value = inputField.val().trim();
        if (isNJQCABarcodeScannerBurst(state, value)) {
          acceptNJQCABarcodeScannerValue(frm, value, state);
        } else {
          resetNJQCABarcodeScannerState(state);
          clearNJQCABarcodeField(frm);
          showNJQCABarcodeScannerMessage(frm);
        }
      }
    }, 600);

    return true;
  });

  inputField.on("input.njqca_barcode_scanner", function () {
    if (state.suppressManualCheck) return;

    const value = inputField.val().trim();
    if (!value) return;

    if (state.validValue === value && Date.now() <= state.validUntil) {
      return;
    }

    if (!state.chars) {
      clearNJQCABarcodeField(frm);
      showNJQCABarcodeScannerMessage(frm);
    }
  });
}

function isNJQCABarcodeScannerBurst(state, value, now = Date.now()) {
  if (!value || state.chars.length < 3) return false;

  const lastKeyTime = state.lastKeyTime || now;
  const totalDuration = lastKeyTime - state.firstKeyTime;
  const lastKeyGap = now - lastKeyTime;

  return totalDuration >= 0 && totalDuration <= 3000 && lastKeyGap <= 600;
}

function acceptNJQCABarcodeScannerValue(frm, value, state) {
  state.validValue = value;
  state.validUntil = Date.now() + 3000;
  resetNJQCABarcodeScannerTyping(state);

  const setValue = frm.set_value("barcode", value);
  const triggerBarcode = function () {
    frm.trigger("barcode");
  };

  if (setValue && setValue.then) {
    setValue.then(triggerBarcode);
  } else {
    triggerBarcode();
  }
}

function isNJQCABarcodeFromScanner(frm) {
  const value = (frm.doc.barcode || "").trim();
  const state = frm.__njqca_barcode_scanner_state;
  if (!value) return true;

  return Boolean(
    state && state.validValue === value && Date.now() <= state.validUntil,
  );
}

function clearNJQCABarcodeField(frm) {
  const state = frm.__njqca_barcode_scanner_state;
  if (state) {
    state.suppressManualCheck = true;
    resetNJQCABarcodeScannerState(state);
  }

  frm.set_value("barcode", "");
  frm.refresh_field("barcode");

  const field = frm.get_field("barcode");
  if (field && field.$input) {
    field.$input.val("");
    field.$input.focus();
  }

  if (state) {
    window.setTimeout(function () {
      state.suppressManualCheck = false;
    }, 0);
  }
}

function showNJQCABarcodeScannerMessage(frm) {
  const state = frm.__njqca_barcode_scanner_state || {};
  const now = Date.now();

  if (state.lastMessageAt && now - state.lastMessageAt < 1200) return;

  state.lastMessageAt = now;
  frm.__njqca_barcode_scanner_state = state;
  frappe.msgprint(__(NJQCA_BARCODE_SCANNER_MESSAGE));
}

function isNJQCABarcodeControlKey(event) {
  return (
    event.ctrlKey ||
    event.metaKey ||
    event.altKey ||
    [
      "Tab",
      "Shift",
      "Control",
      "Alt",
      "Meta",
      "Escape",
      "ArrowLeft",
      "ArrowRight",
      "ArrowUp",
      "ArrowDown",
      "Home",
      "End",
      "Backspace",
      "Delete",
    ].includes(event.key)
  );
}

function resetNJQCABarcodeScannerState(state) {
  window.clearTimeout(state.manualTimer);
  state.manualTimer = null;
  state.validValue = "";
  state.validUntil = 0;
  resetNJQCABarcodeScannerTyping(state);
}

function resetNJQCABarcodeScannerTyping(state) {
  state.chars = "";
  state.firstKeyTime = 0;
  state.lastKeyTime = 0;
}
