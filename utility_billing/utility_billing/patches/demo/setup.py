import json
import os
from typing import Dict, Any, Union

import frappe
from erpnext.setup.demo import create_transaction_deletion_record, delete_company

from .company import create_sample_company
from .utils import logger
from .billing import insert_meter_readings, clear_meter_readings, delete_sales_orders
from .service_request import (
    insert_bill_structures,
    clear_bill_structures,
    insert_service_requests,
    clear_service_requests,
    clear_existing_contracts,
)
from .property_setup import delete_assets


# ============================================
# ADDED: make sure utility item group + items exist
# ============================================
def ensure_utility_items() -> None:
    """
    Ensure demo billing won't explode on warehouse validation.

    This function guarantees:
    - A leaf Item Group 'Utility Services' under parent 'Utility and Rental'
      with is_utility_item_group = 1
    - Non-stock Items 'Water' and 'Electricity' that:
        * belong to 'Utility Services'
        * are marked is_utility_item = 1 (if field exists)
        * are is_stock_item = 0 (so ERPNext won't need Delivery Warehouse)
    It is safe to run multiple times (idempotent).
    """

    group_name = "Utility Services"
    parent_group = "Utility and Rental"

    # 1. ensure the Item Group exists and is normalized
    if not frappe.db.exists("Item Group", group_name):
        grp = frappe.get_doc({
            "doctype": "Item Group",
            "item_group_name": group_name,
            "parent_item_group": parent_group,
            "is_group": 0,
            "is_utility_item_group": 1,
        })
        grp.insert()
        frappe.db.commit()
    else:
        grp = frappe.get_doc("Item Group", group_name)
        changed = False

        # force it to be a leaf (not a parent)
        if getattr(grp, "is_group", None) != 0:
            grp.is_group = 0
            changed = True

        # force correct parent
        if getattr(grp, "parent_item_group", None) != parent_group:
            grp.parent_item_group = parent_group
            changed = True

        # force utility flag if available
        if getattr(grp, "is_utility_item_group", None) != 1:
            grp.is_utility_item_group = 1
            changed = True

        if changed:
            grp.save()
            frappe.db.commit()

    def ensure_item(item_code: str) -> None:
        """
        Create or normalize a single billable utility item.
        """
        if frappe.db.exists("Item", item_code):
            item = frappe.get_doc("Item", item_code)
        else:
            item = frappe.get_doc({
                "doctype": "Item",
                "item_code": item_code,
                "item_name": item_code,
                "item_group": group_name,
                "is_stock_item": 0,
                "include_item_in_manufacturing": 0,
                "has_batch_no": 0,
                "has_serial_no": 0,
                "stock_uom": "Nos",
                "disabled": 0,
                "is_utility_item": 1,  # custom field in this app
            })
            item.insert(ignore_permissions=True)
            frappe.db.commit()

        changed = False

        # must be non-stock to avoid ERPNext's Delivery Warehouse validation
        if getattr(item, "is_stock_item", None) != 0:
            item.is_stock_item = 0
            changed = True

        # must live in the utility services group
        if getattr(item, "item_group", None) != group_name:
            item.item_group = group_name
            changed = True

        # must be flagged utility if field exists
        if hasattr(item, "is_utility_item") and getattr(item, "is_utility_item", None) != 1:
            item.is_utility_item = 1
            changed = True

        if changed:
            item.save(ignore_permissions=True)
            frappe.db.commit()

    # 2. create/normalize core utility items used by billing
    ensure_item("Water")
    ensure_item("Electricity")


def run_demo_setup() -> None:
    """Run the complete demo setup process."""
    logger.info("Starting demo setup...")

    try:
        frappe.db.begin()

        create_sample_company()
        process_masters()

        # ============================================
        # CHANGED: ensure utility items/groups exist
        # before we submit Meter Readings (which
        # auto-create Sales Orders).
        # ============================================
        ensure_utility_items()  # <-- THIS IS THE PERMANENT FIX

        insert_meter_readings()
        insert_bill_structures()
        insert_service_requests()

        frappe.db.commit()
        frappe.msgprint("Demo setup completed successfully.")
        logger.info("Demo setup completed successfully.")
    except Exception as e:
        frappe.db.rollback()
        error_msg = f"Demo setup failed: {str(e)}"
        frappe.msgprint(error_msg, indicator="red")
        logger.exception(error_msg)
        raise


def delete_demo_data() -> None:
    """Delete all demo data created by the setup process."""
    logger.info("Starting demo data deletion...")

    try:
        frappe.db.begin()
        company = "Utility and Rental (Demo)"

        create_transaction_deletion_record(company)
        delete_sales_orders()
        clear_meter_readings()
        clear_existing_contracts()
        clear_service_requests()
        clear_bill_structures()
        delete_assets()
        process_masters_deletion()
        delete_company(company)

        frappe.db.commit()
        frappe.msgprint("Demo data deletion completed successfully.")
        logger.info("Demo data deletion completed successfully.")
    except Exception as e:
        frappe.db.rollback()
        error_msg = f"Demo data deletion failed: {str(e)}"
        frappe.msgprint(error_msg, indicator="red")
        logger.exception(error_msg)
        raise


def process_masters() -> None:
    """Process and create master data records from JSON files."""
    try:
        for doctype in frappe.get_hooks("utility_demo_master_doctypes"):
            try:
                data = read_data_file_using_hooks(doctype)
                if data:
                    for item in json.loads(data):
                        create_demo_record(item)
            except Exception as e:
                error_msg = f"Failed to process master doctype {doctype}: {str(e)}"
                frappe.msgprint(error_msg, indicator="orange")
                logger.error(error_msg)
    except Exception as e:
        error_msg = f"Failed to process masters: {str(e)}"
        frappe.msgprint(error_msg, indicator="red")
        logger.error(error_msg)
        raise


def create_demo_record(item: Dict[str, Any]) -> None:
    """Create a single demo record in the database.

    Args:
        item: Dictionary containing the record data to be inserted
    """
    try:
        doctype = item.get("doctype")
        if not doctype:
            frappe.log_error("Demo Setup Error", f"Missing doctype in item: {item}")
            return

        filters: Dict[str, Union[str, int, float, bool]] = {}
        for field, value in item.items():
            # Only add primitive types to filters
            if (
                field != "doctype"
                and isinstance(value, (str, int, float, bool))
                and not isinstance(value, list)
                and not isinstance(value, dict)
            ):
                filters[field] = value

        if filters and frappe.db.exists(doctype, filters):
            frappe.logger().debug(
                f"Record already exists for {doctype} with filters {filters}"
            )
            return

        doc = frappe.get_doc(item)
        doc.insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
    except frappe.exceptions.DuplicateEntryError:
        frappe.logger().debug(
            f"Duplicate record for {item.get('doctype', 'Unknown')}, skipping"
        )
    except Exception as e:
        frappe.log_error(
            "Demo Setup Error",
            f"Failed to create demo record for {item.get('doctype', 'Unknown')}: {str(e)}",
        )


def read_data_file_using_hooks(doctype: str) -> str:
    """Read JSON data file for a specific doctype.

    Args:
        doctype: The doctype name to read data for

    Returns:
        The contents of the JSON file as a string
    """
    path = os.path.join(os.path.dirname(__file__), "data")
    with open(os.path.join(path, f"{doctype}.json")) as f:
        data = f.read()

    return data


def process_masters_deletion() -> None:
    """Delete all master data records created during demo setup."""
    try:
        # Process doctypes in reverse order to handle dependencies
        for doctype in reversed(frappe.get_hooks("utility_demo_master_doctypes")):
            try:
                data = read_data_file_using_hooks(doctype)
                if data:
                    for item in reversed(json.loads(data)):
                        delete_demo_record(item)
            except Exception as e:
                frappe.log_error(
                    "Demo Deletion Error",
                    f"Failed to process deletion for doctype {doctype}: {str(e)}",
                )
    except Exception as e:
        frappe.log_error(
            "Demo Deletion Error",
            f"Failed to delete masters: {str(e)}",
        )


def delete_demo_record(item: Dict[str, Any]) -> None:
    """Delete a single demo record from the database.

    Args:
        item: Dictionary containing the record data to identify what to delete
    """
    try:
        doctype = item.get("doctype")
        if not doctype:
            frappe.log_error(
                "Demo Deletion Error", f"Missing doctype in item: {item}"
            )
            return

        filters: Dict[str, Union[str, int, float, bool]] = {}
        for field, value in item.items():
            if (
                field != "doctype"
                and isinstance(value, (str, int, float, bool))
                and not isinstance(value, list)
                and not isinstance(value, dict)
            ):
                filters[field] = value

        if filters and frappe.db.exists(doctype, filters):
            frappe.delete_doc(
                doctype,
                frappe.db.get_value(doctype, filters, "name"),
                force=True,
            )
            frappe.logger().debug(
                f"Deleted record for {doctype} with filters {filters}"
            )
    except Exception as e:
        frappe.log_error(
            "Demo Deletion Error",
            f"Failed to delete demo record for {item.get('doctype', 'Unknown')}: {str(e)}",
        )

