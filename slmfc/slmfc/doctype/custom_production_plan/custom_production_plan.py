import hashlib
import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate

from slmfc.utils import round_up, series

QTY_TOLERANCE = 0.0005


def per_unit(stock_qty, base):
	"""BOM qty per unit of output, at the 9 decimals the Work Order stores it."""
	return flt(flt(stock_qty) / (flt(base) or 1), 9)


def get_requirements(items):
	"""Raw material needed per item: sum over plan rows of round_up(per * row qty), across all BOMs."""
	need = {}
	for r in items:
		bom = frappe.get_doc("BOM", r.bom)
		base = flt(bom.quantity) or 1
		for b in bom.items:
			d = need.setdefault(
				b.item_code,
				{"required": 0.0, "bom_warehouse": None, "uom": b.stock_uom, "item_name": b.item_name},
			)
			d["required"] = flt(d["required"] + round_up(per_unit(b.stock_qty, base) * flt(r.qty)), 3)
			if not d["bom_warehouse"] and b.source_warehouse:
				d["bom_warehouse"] = b.source_warehouse
	return need


def get_signature(items):
	rows = [(r.item_code, r.bom, flt(r.qty, 3)) for r in items]
	return hashlib.md5(json.dumps(rows).encode()).hexdigest()


class CustomProductionPlan(Document):
	def validate(self):
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
				"Global Defaults", "default_company"
			)
		if not self.items:
			frappe.throw(_("Add at least one item"))
		self.validate_warehouses()
		self.validate_items()
		self.sync_materials()
		self.validate_split()

	# ---------------------------------------------------------------- validation
	def check_warehouse(self, name, label):
		w = frappe.db.get_value("Warehouse", name, ["company", "is_group", "disabled"], as_dict=1)
		if not w or w.company != self.company or w.is_group or w.disabled:
			frappe.throw(_("{0} must be an enabled, non-group warehouse of {1}").format(label, self.company))

	def validate_warehouses(self):
		for f in ("wip_warehouse", "target_warehouse", "default_source_warehouse"):
			if f == "default_source_warehouse" and not self.get(f):
				continue
			self.check_warehouse(self.get(f), self.meta.get_label(f))
		if self.wip_warehouse == self.target_warehouse:
			frappe.throw(_("WIP and Finished Goods warehouses must be different"))

	def validate_items(self):
		for r in self.items:
			if flt(r.qty) <= 0:
				frappe.throw(_("Row {0}: Qty must be greater than 0").format(r.idx))
			if not r.bom:
				r.bom = frappe.db.get_value(
					"BOM", {"item": r.item_code, "is_default": 1, "is_active": 1, "docstatus": 1}
				)
			if not r.bom:
				frappe.throw(_("Row {0}: no active BOM for {1}").format(r.idx, r.item_code))
			b = frappe.db.get_value("BOM", r.bom, ["item", "is_active", "docstatus"], as_dict=1)
			if not b or b.item != r.item_code or not b.is_active or b.docstatus != 1:
				frappe.throw(
					_("Row {0}: BOM {1} is not a valid active BOM for {2}").format(r.idx, r.bom, r.item_code)
				)

	# ---------------------------------------------------------------- raw material summary
	def default_warehouse(self, item_code, bom_warehouse):
		return (
			bom_warehouse
			or frappe.db.get_value(
				"Item Default", {"parent": item_code, "company": self.company}, "default_warehouse"
			)
			or self.default_source_warehouse
		)

	def has_manual_rows(self, need):
		counts = {}
		for m in self.materials:
			counts[m.item_code] = counts.get(m.item_code, 0) + 1
		for m in self.materials:
			d = need.get(m.item_code)
			if counts[m.item_code] > 1 or not d:
				return True
			if m.source_warehouse != self.default_warehouse(m.item_code, d["bom_warehouse"]):
				return True
		return False

	def sync_materials(self):
		need = get_requirements(self.items)
		signature = get_signature(self.items)
		if not self.materials or self.materials_signature != signature:
			if self.materials and self.has_manual_rows(need):
				frappe.msgprint(
					_(
						"The Raw Material rows you edited were rebuilt because the manufacturing items changed."
					),
					alert=True,
				)
			self.set("materials", [])
			for code, d in need.items():
				self.append(
					"materials",
					{
						"item_code": code,
						"item_name": d["item_name"],
						"uom": d["uom"],
						"source_warehouse": self.default_warehouse(code, d["bom_warehouse"]),
						"qty": flt(d["required"], 3),
					},
				)
			self.materials_signature = signature

		for m in self.materials:
			d = need.get(m.item_code)
			m.required_qty = flt(d["required"], 3) if d else 0
			if not m.item_name or not m.uom:
				it = frappe.db.get_value("Item", m.item_code, ["item_name", "stock_uom"], as_dict=1)
				if it:
					m.item_name = m.item_name or it.item_name
					m.uom = m.uom or it.stock_uom
			m.available_qty = (
				flt(
					frappe.db.get_value(
						"Bin", {"item_code": m.item_code, "warehouse": m.source_warehouse}, "actual_qty"
					)
					or 0,
					3,
				)
				if m.source_warehouse
				else 0
			)
			m.shortfall = flt(max(0, flt(m.qty) - flt(m.available_qty)), 3)

	def validate_split(self):
		need = get_requirements(self.items)
		allow_multiple = frappe.db.get_single_value("Buying Settings", "allow_multiple_items")
		totals, rows_per_item, seen = {}, {}, set()
		for m in self.materials:
			if m.item_code not in need:
				frappe.throw(
					_("Row {0}: {1} is not a raw material of the manufacturing items").format(
						m.idx, frappe.bold(m.item_code)
					)
				)
			if not m.source_warehouse:
				frappe.throw(
					_(
						"Row {0}: no source warehouse for {1}. Set a Default Raw Material Warehouse or choose a warehouse in the row."
					).format(m.idx, frappe.bold(m.item_code))
				)
			if (m.item_code, m.source_warehouse) in seen:
				frappe.throw(
					_("Row {0}: {1} is listed twice for warehouse {2}").format(
						m.idx, frappe.bold(m.item_code), m.source_warehouse
					)
				)
			seen.add((m.item_code, m.source_warehouse))
			self.check_warehouse(m.source_warehouse, _("Source Warehouse (row {0})").format(m.idx))
			if m.source_warehouse in (self.wip_warehouse, self.target_warehouse):
				frappe.throw(
					_("Row {0}: the source warehouse cannot be the WIP or Finished Goods warehouse").format(
						m.idx
					)
				)
			if flt(m.qty) <= 0:
				frappe.throw(_("Row {0}: Qty must be greater than 0").format(m.idx))
			totals[m.item_code] = flt(totals.get(m.item_code, 0) + flt(m.qty), 3)
			rows_per_item[m.item_code] = rows_per_item.get(m.item_code, 0) + 1

		if not allow_multiple:
			multi = [code for code, n in rows_per_item.items() if n > 1]
			if multi:
				frappe.throw(
					_(
						"{0} is taken from more than one warehouse, but Buying Settings does not allow the same item on several Material Request rows. Enable Allow Multiple Items or use one warehouse per item."
					).format(", ".join(frappe.bold(c) for c in multi))
				)

		for code, d in need.items():
			if abs(flt(totals.get(code, 0)) - flt(d["required"])) > QTY_TOLERANCE:
				frappe.throw(
					_("{0}: the warehouse quantities add up to {1} but {2} is required").format(
						frappe.bold(code), flt(totals.get(code, 0), 3), flt(d["required"], 3)
					)
				)

	# ---------------------------------------------------------------- submit / cancel
	def on_submit(self):
		self.create_work_orders()
		self.db_set("material_request", self.create_material_request())

	def create_work_orders(self):
		for r in self.items:
			bom = frappe.get_doc("BOM", r.bom)
			base = flt(bom.quantity) or 1
			wo = frappe.new_doc("Custom Work Order")
			wo.update(
				{
					"plan": self.name,
					"plan_date": self.plan_date,
					"company": self.company,
					"status": "Open",
					"item_code": r.item_code,
					"item_name": r.item_name,
					"bom": r.bom,
					"uom": r.uom,
					"planned_qty": r.qty,
					"produced_qty": 0,
					"pending_qty": r.qty,
					"completion_pct": 0,
					"wip_warehouse": self.wip_warehouse,
					"target_warehouse": self.target_warehouse,
				}
			)
			for b in bom.items:
				per = per_unit(b.stock_qty, base)
				wo.append(
					"items",
					{
						"item_code": b.item_code,
						"item_name": b.item_name,
						"uom": b.stock_uom,
						"qty_per_unit": per,
						"required_qty": round_up(per * flt(r.qty)),
					},
				)
			wo.flags.ignore_permissions = True
			wo.insert()
			frappe.db.set_value("Custom Production Plan Item", r.name, "work_order", wo.name)

	def create_material_request(self):
		today = getdate(nowdate())
		sched = max(getdate(self.plan_date), today)
		mr = frappe.new_doc("Material Request")
		mr.naming_series = series("Material Request")
		mr.material_request_type = "Material Transfer"
		mr.company = self.company
		mr.transaction_date = today
		mr.schedule_date = sched
		for m in self.materials:
			it = frappe.db.get_value(
				"Item", m.item_code, ["item_name", "description", "stock_uom"], as_dict=1
			)
			mr.append(
				"items",
				{
					"item_code": m.item_code,
					"item_name": it.item_name,
					"description": it.description or it.item_name,
					"qty": flt(m.qty, 3),
					"uom": it.stock_uom,
					"stock_uom": it.stock_uom,
					"conversion_factor": 1,
					"from_warehouse": m.source_warehouse,
					"warehouse": self.wip_warehouse,
					"schedule_date": sched,
				},
			)
		mr.flags.ignore_permissions = True
		mr.insert()
		mr.submit()
		return mr.name

	def work_orders(self):
		return frappe.get_all("Custom Work Order", filters={"plan": self.name}, pluck="name")

	def before_cancel(self):
		for wo in self.work_orders():
			entry = frappe.db.get_value("Custom Production Entry", {"work_order": wo, "docstatus": 1}, "name")
			if entry:
				frappe.throw(
					_(
						"Production Entry {0} of Work Order {1} is submitted. Cancel the entries first."
					).format(entry, wo)
				)

	def on_cancel(self):
		for r in self.items:
			if r.work_order:
				frappe.db.set_value("Custom Production Plan Item", r.name, "work_order", None)
		for wo in self.work_orders():
			for entry in frappe.get_all(
				"Custom Production Entry", filters={"work_order": wo, "docstatus": 0}, pluck="name"
			):
				frappe.delete_doc("Custom Production Entry", entry, ignore_permissions=True)
			frappe.delete_doc("Custom Work Order", wo, ignore_permissions=True)
		if (
			self.material_request
			and frappe.db.get_value("Material Request", self.material_request, "docstatus") == 1
		):
			frappe.get_doc("Material Request", self.material_request).cancel()
