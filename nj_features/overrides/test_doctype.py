import frappe
from frappe.tests.utils import FrappeTestCase
import os, random, string

class TestRegression(FrappeTestCase):
    def test_all_doctypes_with_multiple_payloads(self):
        log_path = os.path.join(frappe.get_site_path(), "regression_results.txt")
        with open(log_path, "w") as log:
            log.write("=== ERP Doctype + Multiple Payloads Regression Test ===\n\n")

            # Example: test only one doctype
            doctypes = frappe.get_all("DocType", filters={"name": "Sales Order"}, pluck="name")
            # doctypes = frappe.get_all("DocType", filters={"istable": 0}, pluck="name")  # to test all

            for doctype in doctypes:
                if doctype in ["PayU API Settings", "Communication", "DocType"]:
                    msg = f"⚠️ Skipping {doctype} (special/complex type)\n"
                    print(msg.strip())
                    log.write(msg)
                    continue

                try:
                    meta = frappe.get_meta(doctype)
                    name = frappe.db.get_value(doctype, {}, "name")
                    if name:
                        frappe.get_doc(doctype, name)
                        print(f"✅ Loaded {doctype}: {name}")
                        log.write(f"✅ Loaded {doctype}: {name}\n")

                    # ✅ STEP 2: Generate multiple payloads (for example, 3)
                    for i in range(3):
                        payload = {"doctype": doctype}
                        for field in meta.fields:
                            if field.reqd and not field.read_only:
                                if field.fieldtype in ("Data", "Small Text", "Text", "Long Text"):
                                    payload[field.fieldname] = f"Test_{i}_" + ''.join(random.choices(string.ascii_uppercase, k=5))
                                elif field.fieldtype in ("Int", "Float", "Currency"):
                                    payload[field.fieldname] = random.randint(1, 100)
                                elif field.fieldtype == "Check":
                                    payload[field.fieldname] = random.choice([0, 1])
                                elif field.fieldtype == "Select" and field.options:
                                    options = [opt for opt in field.options.split("\n") if opt]
                                    payload[field.fieldname] = random.choice(options)
                                elif field.fieldtype == "Link" and field.options:
                                    ref_doctype = field.options
                                    ref = frappe.db.get_all(ref_doctype, pluck="name", limit=1)
                                    if ref:
                                        payload[field.fieldname] = ref[0]

                        print(f"\n🧩 Dummy Payload #{i+1} for {doctype}: {payload}\n")
                        log.write(f"\n🧩 Dummy Payload #{i+1} for {doctype}: {payload}\n")

                        # ✅ STEP 3: Try inserting record
                        try:
                            doc = frappe.get_doc(payload)
                            doc.insert(ignore_permissions=True)
                            frappe.db.rollback()
                            msg = f"✅ Created dummy record #{i+1} for {doctype}\n"
                            print(msg.strip())
                            log.write(msg)
                        except Exception as e:
                            msg = f"❌ Failed to insert #{i+1} in {doctype}: {e}\n"
                            print(msg.strip())
                            log.write(msg)

                except Exception as e:
                    msg = f"❌ Failed to load or test {doctype}: {e}\n"
                    print(msg.strip())
                    log.write(msg)

        print(f"\n📄 Regression results saved at: {log_path}")
