import frappe

REQUIRED_FIELDS = [
    {
        "dt": "Sales Invoice",
        "fieldname": "utility_property",
        "label": "Utility Property",
        "fieldtype": "Link",
        "options": "Utility Property",
        "insert_after": "customer",
    },
    {
        "dt": "Sales Invoice Item",
        "fieldname": "utility_property",
        "label": "Utility Property",
        "fieldtype": "Link",
        "options": "Utility Property",
        "insert_after": "project",
    },
    {
        "dt": "Sales Order Item",
        "fieldname": "utility_property",
        "label": "Utility Property",
        "fieldtype": "Link",
        "options": "Utility Property",
        "insert_after": "project",
    },
]

def execute():
    """Ensure required utility_property fields exist on core sales doctypes."""
    for spec in REQUIRED_FIELDS:
        # Check Custom Field record
        if not frappe.db.exists(
            "Custom Field",
            {"dt": spec["dt"], "fieldname": spec["fieldname"]},
        ):
            cf = frappe.get_doc({
                "doctype": "Custom Field",
                "dt": spec["dt"],
                "fieldname": spec["fieldname"],
                "label": spec["label"],
                "fieldtype": spec["fieldtype"],
                "options": spec["options"],
                "insert_after": spec["insert_after"],
                "reqd": 0,
                "read_only": 0,
                "hidden": 0,
            })
            cf.insert(ignore_permissions=True)

    frappe.db.commit()

