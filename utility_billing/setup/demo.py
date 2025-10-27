import frappe
from frappe import _
from ..utility_billing.patches.demo.setup import run_demo_setup, delete_demo_data


@frappe.whitelist()
def setup_demo_data():
    from frappe.utils.telemetry import capture
    frappe.only_for("System Manager")
    try:
        # IMPORTANT: this is the same codepath that works in console
        run_demo_setup()
        frappe.publish_realtime("demo_data_complete")
    except Exception:
        frappe.log_error("Failed to create demo data")
        capture(
            "demo_data_creation_failed",
            "utility_billing",
            properties={"exception": frappe.get_traceback()},
        )
        # re-raise so the UI actually shows that it failed
        raise
    capture("demo_data_creation_completed", "utility_billing")


@frappe.whitelist()
def clear_demo_data():
    frappe.only_for("System Manager")
    try:
        # same delete function you tested in console
        delete_demo_data()
    except Exception:
        frappe.db.rollback()
        frappe.log_error("Failed to erase demo data")
        frappe.throw(
            _("Failed to erase demo data, please delete the demo company manually."),
            title=_("Could Not Delete Demo Data"),
        )

