import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from slmfc.utils import round_up, series

TOLERANCE_PCT = 2.0  # variance above this needs a reason
MIN_VARIANCE_QTY = 0.005  # ignore variance smaller than this (ledger works in 3 decimals)


class ShopfloorWorkOrder(Document):
	def validate(self):
		if self.docstatus == 0:
			self.status = "Open"
		self.calculate_variance()

	def calculate_variance(self):
		out = flt(self.output_qty)
		for i in self.items:
			if flt(i.consumed_qty) < 0:
				frappe.throw(_("Row {0}: Actual Qty cannot be negative").format(i.idx))
			# the stock ledger holds every item to 3 decimals: standard and actual must be
			# the same 3-decimal numbers the Stock Entry and Material Request will carry
			i.required_qty = round_up(flt(i.qty_per_unit) * out)
			i.consumed_qty = round_up(i.consumed_qty)
			i.variance_qty = flt(flt(i.consumed_qty) - flt(i.required_qty), 3)
			i.variance_pct = flt(i.variance_qty / i.required_qty * 100, 2) if flt(i.required_qty) else 0
		self.yield_pct = flt(out / flt(self.planned_qty) * 100, 2) if flt(self.planned_qty) else 0

	def before_submit(self):
		if flt(self.output_qty) <= 0:
			frappe.throw(_("Output Qty must be greater than 0"))
		if not any(flt(i.consumed_qty) > 0 for i in self.items):
			frappe.throw(_("Enter actual quantity for at least one raw material"))
		for i in self.items:
			if (
				abs(flt(i.variance_pct)) > TOLERANCE_PCT
				and abs(flt(i.variance_qty)) > MIN_VARIANCE_QTY
				and not (i.variance_reason or "").strip()
			):
				frappe.throw(
					_("Row {0} ({1}): variance is {2}%. Enter a Variance Reason.").format(
						i.idx, i.item_code, i.variance_pct
					)
				)

	def on_submit(self):
		se = self.make_stock_entry()
		self.db_set({"stock_entry": se.name, "status": "Completed"})
		self.set_costs(se)

	def on_cancel(self):
		if self.stock_entry and frappe.db.get_value("Stock Entry", self.stock_entry, "docstatus") == 1:
			frappe.get_doc("Stock Entry", self.stock_entry).cancel()
		self.db_set("status", "Cancelled")

	def set_costs(self, se):
		# consumed SE rows were appended in the same order as WO rows with actual qty > 0
		rows = [i for i in self.items if flt(i.consumed_qty) > 0]
		consumed = [r for r in se.items if r.s_warehouse]
		tot_std = tot_act = 0.0
		for wo_row, se_row in zip(rows, consumed, strict=True):
			rate = flt(se_row.basic_rate)
			std = flt(flt(wo_row.required_qty) * rate, 2)
			act = flt(se_row.basic_amount or flt(wo_row.consumed_qty) * rate, 2)
			frappe.db.set_value(
				"Shopfloor Work Order Item", wo_row.name, {"std_cost": std, "actual_cost": act}
			)
			tot_std += std
			tot_act += act
		eff = flt(tot_std / tot_act * 100, 2) if tot_act else 0
		self.db_set(
			{
				"total_std_cost": flt(tot_std, 2),
				"total_actual_cost": flt(tot_act, 2),
				"cost_efficiency_pct": eff,
			}
		)

	def make_stock_entry(self):
		stock_uom = frappe.db.get_value("Item", self.item_code, "stock_uom")
		se = frappe.new_doc("Stock Entry")
		se.naming_series = series("Stock Entry")
		se.stock_entry_type = "Manufacture"
		se.purpose = "Manufacture"
		se.company = self.company
		se.from_bom = 0
		se.remarks = f"Shopfloor Work Order {self.name}"
		for i in self.items:
			q = flt(i.consumed_qty)
			if q <= 0:
				continue
			se.append(
				"items",
				{
					"item_code": i.item_code,
					"qty": q,
					"uom": i.uom,
					"stock_uom": i.uom,
					"conversion_factor": 1,
					"transfer_qty": q,
					"s_warehouse": self.wip_warehouse,
				},
			)
		se.append(
			"items",
			{
				"item_code": self.item_code,
				"qty": flt(self.output_qty),
				"uom": stock_uom,
				"stock_uom": stock_uom,
				"conversion_factor": 1,
				"transfer_qty": flt(self.output_qty),
				"t_warehouse": self.target_warehouse,
				"is_finished_item": 1,
				"bom_no": self.bom,
			},
		)
		se.flags.ignore_permissions = True
		se.insert()
		se.submit()
		return se
