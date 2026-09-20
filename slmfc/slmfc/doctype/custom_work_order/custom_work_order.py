import frappe
from frappe.model.document import Document
from frappe.utils import flt

QTY_TOLERANCE = 0.0005


class CustomWorkOrder(Document):
	def onload(self):
		"""Show the WIP on-hand of each ingredient (in memory only, never saved)."""
		from slmfc.slmfc.doctype.custom_production_entry.custom_production_entry import wip_balance

		for i in self.items:
			i.wip_qty = wip_balance(i.item_code, self.wip_warehouse)

	def refresh_progress(self):
		"""Recompute produced/pending/status from the submitted Production Entries."""
		cancelled = frappe.db.get_value("Custom Work Order", self.name, "status") == "Cancelled"
		produced = flt(
			frappe.db.sql(
				"select coalesce(sum(output_qty), 0) from `tabCustom Production Entry` where work_order = %s and docstatus = 1",
				self.name,
			)[0][0],
			3,
		)
		planned = flt(self.planned_qty, 3)
		if cancelled:
			status = "Cancelled"
		elif produced <= 0:
			status = "Open"
		elif produced >= planned - QTY_TOLERANCE:
			status = "Completed"
		else:
			status = "Partially Completed"
		self.db_set(
			{
				"produced_qty": produced,
				"pending_qty": flt(planned - produced, 3),
				"completion_pct": flt(produced / planned * 100, 2) if planned else 0,
				"status": status,
			}
		)


def update_work_order(name):
	frappe.get_doc("Custom Work Order", name).refresh_progress()
