from math import ceil

import frappe
from frappe.utils import flt


def series(doctype):
    opts = (frappe.get_meta(doctype).get_field("naming_series").options or "").split("\n")
    return next((o for o in opts if o), None)


def round_up(qty, precision=3):
    f = 10 ** precision
    return flt(ceil(round(flt(qty) * f, 6)) / f, precision)
