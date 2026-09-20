import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate

from slmfc.utils import series


class ShopfloorPlan(Document):
    def validate(self):
        if not self.company:
            self.company = (
                frappe.defaults.get_user_default("Company")
                or frappe.db.get_single_value("Global Defaults", "default_company")
            )
        if not self.items:
            frappe.throw(_("Add at least one item"))
        if len({self.source_warehouse, self.wip_warehouse, self.target_warehouse}) != 3:
            frappe.throw(_("Raw Material, WIP and Finished Goods warehouses must all be different"))
        for f in ("source_warehouse", "wip_warehouse", "target_warehouse"):
            w = frappe.db.get_value("Warehouse", self.get(f), ["company", "is_group", "disabled"], as_dict=1)
            if not w or w.company != self.company or w.is_group or w.disabled:
                frappe.throw(_("{0} must be an enabled, non-group warehouse of {1}").format(self.meta.get_label(f), self.company))
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
            if b.item != r.item_code or not b.is_active or b.docstatus != 1:
                frappe.throw(_("Row {0}: BOM {1} is not a valid active BOM for {2}").format(r.idx, r.bom, r.item_code))

    def on_submit(self):
        wos = self.create_work_orders()
        self.db_set("material_request", self.create_material_request(wos))

    def before_cancel(self):
        for r in self.items:
            if r.work_order and frappe.db.get_value("Shopfloor Work Order", r.work_order, "docstatus") == 1:
                frappe.throw(_("Work Order {0} is already completed. Cancel it first.").format(r.work_order))

    def on_cancel(self):
        for r in self.items:
            if r.work_order and frappe.db.get_value("Shopfloor Work Order", r.work_order, "docstatus") == 0:
                frappe.db.set_value("Shopfloor Plan Item", r.name, "work_order", None)
                frappe.delete_doc("Shopfloor Work Order", r.work_order, force=1, ignore_permissions=True)
        if self.material_request and frappe.db.get_value("Material Request", self.material_request, "docstatus") == 1:
            frappe.get_doc("Material Request", self.material_request).cancel()

    def create_work_orders(self):
        wos = []
        for r in self.items:
            bom = frappe.get_doc("BOM", r.bom)
            base = flt(bom.quantity) or 1
            wo = frappe.new_doc("Shopfloor Work Order")
            wo.update({
                "plan": self.name, "plan_date": self.plan_date, "company": self.company,
                "item_code": r.item_code, "item_name": r.item_name, "bom": r.bom, "uom": r.uom,
                "planned_qty": r.qty, "output_qty": r.qty,
                "wip_warehouse": self.wip_warehouse, "target_warehouse": self.target_warehouse,
            })
            for b in bom.items:
                per = flt(b.stock_qty) / base
                wo.append("items", {
                    "item_code": b.item_code, "item_name": b.item_name, "uom": b.stock_uom,
                    "qty_per_unit": per,
                    "required_qty": flt(per * flt(r.qty), 6),
                    "consumed_qty": flt(per * flt(r.qty), 6),
                })
            wo.flags.ignore_permissions = True
            wo.insert()
            frappe.db.set_value("Shopfloor Plan Item", r.name, "work_order", wo.name)
            wos.append(wo)
        return wos

    def create_material_request(self, wos):
        need = {}
        for wo in wos:
            for i in wo.items:
                need[i.item_code] = need.get(i.item_code, 0) + flt(i.consumed_qty)

        today = getdate(nowdate())
        sched = max(getdate(self.plan_date), today)
        mr = frappe.new_doc("Material Request")
        mr.naming_series = series("Material Request")
        mr.material_request_type = "Material Transfer"
        mr.company = self.company
        mr.transaction_date = today
        mr.schedule_date = sched
        mr.set_from_warehouse = self.source_warehouse
        mr.set_warehouse = self.wip_warehouse
        for code, qty in need.items():
            it = frappe.db.get_value("Item", code, ["item_name", "description", "stock_uom"], as_dict=1)
            mr.append("items", {
                "item_code": code, "item_name": it.item_name,
                "description": it.description or it.item_name,
                "qty": flt(qty, 6), "uom": it.stock_uom, "stock_uom": it.stock_uom, "conversion_factor": 1,
                "from_warehouse": self.source_warehouse, "warehouse": self.wip_warehouse,
                "schedule_date": sched,
            })
        mr.flags.ignore_permissions = True
        mr.insert()
        mr.submit()
        return mr.name
