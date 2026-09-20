import frappe
from frappe import _


def execute(filters=None):
	f = filters or {}
	cond, val = "e.docstatus = 1 AND e.posting_date BETWEEN %(from_date)s AND %(to_date)s", dict(f)
	if f.get("item_code"):
		cond += " AND e.item_code = %(item_code)s"
	if f.get("raw_item"):
		cond += " AND i.item_code = %(raw_item)s"
	if f.get("work_order"):
		cond += " AND e.work_order = %(work_order)s"

	cols = [
		{
			"label": _("Entry"),
			"fieldname": "entry",
			"fieldtype": "Link",
			"options": "Custom Production Entry",
			"width": 140,
		},
		{
			"label": _("Work Order"),
			"fieldname": "work_order",
			"fieldtype": "Link",
			"options": "Custom Work Order",
			"width": 140,
		},
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 95},
		{"label": _("FG Item"), "fieldname": "fg", "fieldtype": "Link", "options": "Item", "width": 110},
		{"label": _("Batch"), "fieldname": "batch_no", "fieldtype": "Data", "width": 130},
		{"label": _("Output"), "fieldname": "output", "fieldtype": "Float", "width": 90},
		{"label": _("Already Produced"), "fieldname": "cum_before", "fieldtype": "Float", "width": 110},
		{"label": _("Raw Material"), "fieldname": "rm", "fieldtype": "Link", "options": "Item", "width": 110},
		{"label": _("Standard Qty"), "fieldname": "std", "fieldtype": "Float", "width": 100},
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
        SELECT e.name entry, e.work_order work_order, e.posting_date posting_date, e.item_code fg,
               e.batch_no batch_no, e.output_qty output, e.cum_before cum_before, i.item_code rm,
               i.required_qty std, i.consumed_qty act, i.variance_qty `var`,
               i.variance_pct var_pct, i.std_cost std_cost, i.actual_cost act_cost,
               (i.actual_cost - i.std_cost) cost_var, i.variance_reason reason
        FROM `tabCustom Production Entry` e
        JOIN `tabCustom Production Entry Item` i ON i.parent = e.name
        WHERE {cond}
        ORDER BY e.posting_date DESC, e.name, i.idx
        """,
		val,
		as_dict=True,
	)
	return cols, data
