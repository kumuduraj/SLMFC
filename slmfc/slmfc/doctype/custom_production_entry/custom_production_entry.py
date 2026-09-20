import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, nowdate

from slmfc.slmfc.doctype.custom_work_order.custom_work_order import update_work_order
from slmfc.utils import cum_std, round_up, series, suggest_batch

TOLERANCE_PCT = 2.0  # variance above this needs a reason
MIN_VARIANCE_QTY = 0.005  # ignore variance smaller than this (ledger works in 3 decimals)
QTY_TOLERANCE = 0.0005


class CustomProductionEntry(Document):
	# ---------------------------------------------------------------- validation
	def validate(self):
		if not self.work_order:
			frappe.throw(_("Select a Work Order"))
		wo = frappe.get_doc("Custom Work Order", self.work_order)
		if wo.status == "Cancelled":
			frappe.throw(_("Work Order {0} is cancelled").format(wo.name))
		if self.docstatus == 0:
			self.copy_from_work_order(wo)
			other = frappe.db.get_value(
				"Custom Production Entry",
				{"work_order": self.work_order, "docstatus": 0, "name": ("!=", self.name)},
				"name",
			)
			if other:
				frappe.throw(
					_("Draft Production Entry {0} already exists for Work Order {1}").format(
						other, self.work_order
					)
				)
		self.check_output(wo)
		self.calculate_rows()
		self.validate_batch()

	def copy_from_work_order(self, wo):
		for f in (
			"plan",
			"company",
			"item_code",
			"item_name",
			"bom",
			"uom",
			"wip_warehouse",
			"target_warehouse",
		):
			self.set(f, wo.get(f))
		self.planned_qty = wo.planned_qty
		self.has_batch = cint(frappe.db.get_value("Item", wo.item_code, "has_batch_no"))
		if not self.items or (not self.is_new() and self.has_value_changed("work_order")):
			self.set("items", [])
			for i in wo.items:
				self.append(
					"items",
					{
						"item_code": i.item_code,
						"item_name": i.item_name,
						"uom": i.uom,
						"qty_per_unit": i.qty_per_unit,
						"required_qty": 0,
						"consumed_qty": 0,
					},
				)

	def live_produced(self):
		return flt(
			frappe.db.sql(
				"select coalesce(sum(output_qty), 0) from `tabCustom Production Entry` where work_order = %s and docstatus = 1 and name != %s",
				(self.work_order, self.name or ""),
			)[0][0],
			3,
		)

	def check_output(self, wo):
		live = self.live_produced()
		self.cum_before = live
		pending = flt(flt(wo.planned_qty) - live, 3)
		if flt(self.output_qty) <= 0:
			frappe.throw(_("Output Qty must be greater than 0"))
		if flt(self.output_qty, 3) > pending + QTY_TOLERANCE:
			frappe.throw(
				_("Output Qty {0} is more than the pending {1} of Work Order {2}").format(
					flt(self.output_qty, 3), pending, self.work_order
				)
			)

	def calculate_rows(self):
		for i in self.items:
			if flt(i.consumed_qty) < 0:
				frappe.throw(_("Row {0}: Actual Qty cannot be negative").format(i.idx))
			i.required_qty = cum_std(i.qty_per_unit, self.cum_before, self.output_qty)
			i.consumed_qty = round_up(i.consumed_qty)
			i.variance_qty = flt(flt(i.consumed_qty) - flt(i.required_qty), 3)
			i.variance_pct = flt(i.variance_qty / i.required_qty * 100, 2) if flt(i.required_qty) else 0
		self.completion_pct = (
			flt((flt(self.cum_before) + flt(self.output_qty)) / flt(self.planned_qty) * 100, 2)
			if flt(self.planned_qty)
			else 0
		)

	def validate_batch(self):
		if not self.has_batch:
			return
		if not self.batch_no:
			if self.batch_mode == "Manual":
				frappe.throw(_("Enter the Batch No"))
			self.batch_no = suggest_batch(self.item_code, self.posting_date)
		res = batch_status(self.batch_no, self.item_code, self.work_order)
		if res["status"] == "duplicate":
			if self.batch_mode == "Auto":
				old = self.batch_no
				self.batch_no = suggest_batch(self.item_code, self.posting_date)
				frappe.msgprint(
					_("Batch {0} is already used. Batch {1} was assigned instead.").format(old, self.batch_no)
				)
			else:
				frappe.throw(res["message"])

	# ---------------------------------------------------------------- submit
	def before_submit(self):
		wo = frappe.get_doc("Custom Work Order", self.work_order)
		self.check_output(wo)
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
		if not any(flt(i.consumed_qty) > 0 for i in self.items):
			frappe.throw(_("Enter actual quantity for at least one raw material"))
		self.check_wip_stock()
		if self.has_batch:
			res = batch_status(self.batch_no, self.item_code, self.work_order)
			if res["status"] == "duplicate":
				if self.batch_mode == "Auto":
					old = self.batch_no
					self.batch_no = suggest_batch(self.item_code, self.posting_date)
					frappe.msgprint(
						_("Batch {0} is already used. Batch {1} was assigned instead.").format(
							old, self.batch_no
						)
					)
				else:
					frappe.throw(res["message"])

	def check_wip_stock(self):
		short = []
		for i in self.items:
			if flt(i.consumed_qty) <= 0:
				continue
			have = flt(
				frappe.db.get_value(
					"Bin", {"item_code": i.item_code, "warehouse": self.wip_warehouse}, "actual_qty"
				)
				or 0,
				3,
			)
			if flt(i.consumed_qty, 3) > have + QTY_TOLERANCE:
				short.append(
					_("{0} needs {1}, WIP has {2}").format(
						frappe.bold(i.item_code), flt(i.consumed_qty, 3), have
					)
				)
		if short:
			frappe.throw(
				_("Transfer raw material to WIP first ({0}):").format(self.wip_warehouse)
				+ "<br>"
				+ "<br>".join(short)
			)

	def on_submit(self):
		if self.has_batch and not frappe.db.exists("Batch", self.batch_no):
			frappe.get_doc({"doctype": "Batch", "item": self.item_code, "batch_id": self.batch_no}).insert(
				ignore_permissions=True
			)
		se = self.make_stock_entry()
		self.db_set("stock_entry", se.name)
		self.set_costs(se)
		update_work_order(self.work_order)

	def make_stock_entry(self):
		stock_uom = frappe.db.get_value("Item", self.item_code, "stock_uom")
		se = frappe.new_doc("Stock Entry")
		se.naming_series = series("Stock Entry")
		se.stock_entry_type = "Manufacture"
		se.purpose = "Manufacture"
		se.company = self.company
		se.set_posting_time = 1
		se.posting_date = self.posting_date
		se.from_bom = 0
		se.remarks = f"Custom Production Entry {self.name}"
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
		fg = {
			"item_code": self.item_code,
			"qty": flt(self.output_qty),
			"uom": stock_uom,
			"stock_uom": stock_uom,
			"conversion_factor": 1,
			"transfer_qty": flt(self.output_qty),
			"t_warehouse": self.target_warehouse,
			"is_finished_item": 1,
			"bom_no": self.bom,
		}
		if self.has_batch:
			fg.update({"batch_no": self.batch_no, "use_serial_batch_fields": 1})
		se.append("items", fg)
		se.flags.ignore_permissions = True
		se.insert()
		se.submit()
		return se

	def set_costs(self, se):
		# consumed SE rows were appended in the same order as entry rows with actual qty > 0
		rows = [i for i in self.items if flt(i.consumed_qty) > 0]
		consumed = [r for r in se.items if r.s_warehouse]
		tot_std = tot_act = 0.0
		for entry_row, se_row in zip(rows, consumed, strict=True):
			rate = flt(se_row.basic_rate)
			std = flt(flt(entry_row.required_qty) * rate, 2)
			act = flt(se_row.basic_amount or flt(entry_row.consumed_qty) * rate, 2)
			frappe.db.set_value(
				"Custom Production Entry Item", entry_row.name, {"std_cost": std, "actual_cost": act}
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

	# ---------------------------------------------------------------- cancel
	def before_cancel(self):
		later = frappe.db.get_value(
			"Custom Production Entry",
			{"work_order": self.work_order, "docstatus": 1, "cum_before": (">", flt(self.cum_before, 3))},
			"name",
		)
		if later:
			frappe.throw(_("Cancel {0} first").format(later))

	def on_cancel(self):
		if self.stock_entry and frappe.db.get_value("Stock Entry", self.stock_entry, "docstatus") == 1:
			frappe.get_doc("Stock Entry", self.stock_entry).cancel()
		update_work_order(self.work_order)


def batch_status(batch_no, item_code, work_order=None):
	"""ok = new batch; continue = same batch used by an earlier entry of this Work Order; duplicate = taken."""
	if not batch_no or not frappe.db.exists("Batch", batch_no):
		return {"status": "ok", "message": ""}
	batch_item = frappe.db.get_value("Batch", batch_no, "item")
	if batch_item != item_code:
		return {
			"status": "duplicate",
			"message": _("Batch {0} already exists for item {1}").format(batch_no, batch_item),
		}
	if work_order and frappe.db.exists(
		"Custom Production Entry", {"work_order": work_order, "batch_no": batch_no, "docstatus": 1}
	):
		return {
			"status": "continue",
			"message": _("Continues batch {0} from an earlier entry of this Work Order").format(batch_no),
		}
	return {"status": "duplicate", "message": _("Batch {0} already exists").format(batch_no)}


@frappe.whitelist()
def suggest_batch_no(item_code, posting_date=None):
	frappe.has_permission("Custom Production Entry", "read", throw=True)
	return suggest_batch(item_code, posting_date or nowdate())


@frappe.whitelist()
def check_batch(batch_no, item_code, work_order=None):
	frappe.has_permission("Custom Production Entry", "read", throw=True)
	return batch_status(batch_no, item_code, work_order)


@frappe.whitelist()
def make_production_entry(work_order):
	"""Return an unsaved Production Entry for the Work Order, pre-filled with the pending quantity."""
	wo = frappe.get_doc("Custom Work Order", work_order)
	wo.check_permission("read")
	frappe.has_permission("Custom Production Entry", "create", throw=True)
	if wo.status == "Cancelled":
		frappe.throw(_("Work Order {0} is cancelled").format(work_order))
	if wo.status == "Completed":
		frappe.throw(_("Work Order {0} is already completed").format(work_order))
	draft = frappe.db.get_value("Custom Production Entry", {"work_order": work_order, "docstatus": 0}, "name")
	if draft:
		frappe.throw(
			_("Draft Production Entry {0} already exists for Work Order {1}").format(draft, work_order)
		)

	doc = frappe.new_doc("Custom Production Entry")
	for f in ("plan", "company", "item_code", "item_name", "bom", "uom", "wip_warehouse", "target_warehouse"):
		doc.set(f, wo.get(f))
	doc.work_order = wo.name
	doc.posting_date = nowdate()
	doc.planned_qty = wo.planned_qty
	doc.cum_before = flt(wo.produced_qty, 3)
	doc.output_qty = flt(wo.pending_qty, 3)
	doc.has_batch = cint(frappe.db.get_value("Item", wo.item_code, "has_batch_no"))
	doc.batch_mode = "Auto"
	if doc.has_batch:
		doc.batch_no = suggest_batch(wo.item_code, doc.posting_date)
	for i in wo.items:
		std = cum_std(i.qty_per_unit, doc.cum_before, doc.output_qty)
		doc.append(
			"items",
			{
				"item_code": i.item_code,
				"item_name": i.item_name,
				"uom": i.uom,
				"qty_per_unit": i.qty_per_unit,
				"required_qty": std,
				"consumed_qty": std,
			},
		)
	doc.completion_pct = (
		flt((flt(doc.cum_before) + flt(doc.output_qty)) / flt(doc.planned_qty) * 100, 2)
		if flt(doc.planned_qty)
		else 0
	)
	out = doc.as_dict()
	out["__islocal"] = 1
	return out
