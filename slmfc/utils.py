from math import ceil

import frappe
from frappe.utils import flt, getdate


def series(doctype):
	opts = (frappe.get_meta(doctype).get_field("naming_series").options or "").split("\n")
	return next((o for o in opts if o), None)


def round_up(qty, precision=3):
	f = 10**precision
	return flt(ceil(round(flt(qty) * f, 6)) / f, precision)


def cum_std(per, before, out):
	"""Standard qty for one production step: round_up of the cumulative standard minus what was already booked.

	Cumulative rounding keeps the sum of all steps equal to round_up(per * total), so partial completions
	never consume more than the Material Request transferred."""
	return flt(round_up(flt(per) * (flt(before) + flt(out))) - round_up(flt(per) * flt(before)), 3)


def suggest_batch(item_code, on_date):
	prefix = f"{item_code}-{getdate(on_date).strftime('%y%m%d')}-"
	n = 1
	while frappe.db.exists("Batch", f"{prefix}{n:02d}"):
		n += 1
	return f"{prefix}{n:02d}"
