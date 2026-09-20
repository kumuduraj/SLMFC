import frappe


def series(doctype):
    opts = (frappe.get_meta(doctype).get_field("naming_series").options or "").split("\n")
    return next((o for o in opts if o), None)
