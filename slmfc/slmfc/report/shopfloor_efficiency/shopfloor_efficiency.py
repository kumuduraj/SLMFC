import frappe
from frappe import _


def execute(filters=None):
	f = filters or {}
	cond, val = "wo.docstatus = 1 AND wo.plan_date BETWEEN %(from_date)s AND %(to_date)s", dict(f)
	if f.get("item_code"):
		cond += " AND wo.item_code = %(item_code)s"
	if f.get("raw_item"):
		cond += " AND i.item_code = %(raw_item)s"

	cols = [
		{
			"label": _("Work Order"),
			"fieldname": "wo",
			"fieldtype": "Link",
			"options": "Shopfloor Work Order",
			"width": 140,
		},
		{"label": _("Date"), "fieldname": "plan_date", "fieldtype": "Date", "width": 95},
		{"label": _("FG Item"), "fieldname": "fg", "fieldtype": "Link", "options": "Item", "width": 110},
		{"label": _("Planned"), "fieldname": "planned", "fieldtype": "Float", "width": 90},
		{"label": _("Output"), "fieldname": "output", "fieldtype": "Float", "width": 90},
		{"label": _("Yield %"), "fieldname": "yield_pct", "fieldtype": "Percent", "width": 80},
		{"label": _("Raw Material"), "fieldname": "rm", "fieldtype": "Link", "options": "Item", "width": 110},
		{"label": _("BOM Qty"), "fieldname": "std", "fieldtype": "Float", "width": 95},
		{"label": _("Actual Qty"), "fieldname": "act", "fieldtype": "Float", "width": 95},
		{"label": _("Variance"), "fieldname": "var", "fieldtype": "Float", "width": 90},
		{"label": _("Variance %"), "fieldname": "var_pct", "fieldtype": "Percent", "width": 90},
		{"label": _("Std Cost"), "fieldname": "std_cost", "fieldtype": "Currency", "width": 100},
		{"label": _("Actual Cost"), "fieldname": "act_cost", "fieldtype": "Currency", "width": 100},
		{"label": _("Cost Variance"), "fieldname": "cost_var", "fieldtype": "Currency", "width": 105},
		{"label": _("Reason"), "fieldname": "reason", "fieldtype": "Data", "width": 220},
	]
	data = frappe.db.sql(
		f"""
        SELECT wo.name wo, wo.plan_date, wo.item_code fg, wo.planned_qty planned,
               wo.output_qty output, wo.yield_pct, i.item_code rm,
               i.required_qty std, i.consumed_qty act, i.variance_qty `var`,
               i.variance_pct var_pct, i.std_cost, i.actual_cost act_cost,
               (i.actual_cost - i.std_cost) cost_var, i.variance_reason reason
        FROM `tabShopfloor Work Order` wo
        JOIN `tabShopfloor Work Order Item` i ON i.parent = wo.name
        WHERE {cond}
        ORDER BY wo.plan_date DESC, wo.name, i.idx
        """,
		val,
		as_dict=True,
	)
	return cols, data
