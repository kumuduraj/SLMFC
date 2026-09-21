import frappe
from frappe import _
from frappe.utils import escape_html, flt, formatdate

RAW, ENTRY = "By Raw Material", "By Entry"
NOTE = "Costs use submitted Stock Entry rates; test-stock items at rate 10 are test values."


def execute(filters=None):
	f = frappe._dict(filters or {})
	if not f.work_order:
		frappe.throw(_("Select a Work Order"))
	wo = frappe.get_doc("Custom Work Order", f.work_order)
	wo.check_permission("read")
	view = f.view if f.view in (RAW, ENTRY) else RAW

	entries = get_entries(wo.name)
	rows = get_entry_rows(entries)
	columns = raw_columns() if view == RAW else entry_columns()
	summary = get_summary(wo, entries, rows)
	if not entries:
		return columns, [], get_message(wo, entries, empty=True), None, summary, True

	if view == RAW:
		data, chart = raw_view(wo, entries, rows, columns)
	else:
		data, chart = entry_view(wo, entries, columns), None
	return columns, data, get_message(wo, entries), chart, summary, True


# ------------------------------------------------------------------ data
def get_entries(work_order):
	"""Submitted entries of the Work Order, oldest first."""
	return frappe.get_all(
		"Custom Production Entry",
		filters={"work_order": work_order, "docstatus": 1},
		fields=[
			"name",
			"posting_date",
			"batch_no",
			"output_qty",
			"cum_before",
			"total_std_cost",
			"total_actual_cost",
			"cost_efficiency_pct",
			"stock_entry",
		],
		order_by="posting_date asc, creation asc",
	)


def get_entry_rows(entries):
	if not entries:
		return []
	return frappe.db.sql(
		"""
		SELECT parent, item_code, required_qty, consumed_qty, std_cost, actual_cost
		FROM `tabCustom Production Entry Item`
		WHERE parent IN %(names)s
		""",
		{"names": tuple(e.name for e in entries)},
		as_dict=True,
	)


def fg_rate(stock_entry):
	if not stock_entry:
		return 0
	return flt(
		frappe.db.get_value(
			"Stock Entry Detail", {"parent": stock_entry, "is_finished_item": 1}, "basic_rate"
		)
	)


def ratio(a, b, factor=1):
	return flt(a) / flt(b) * factor if flt(b) else 0


def raw_view(wo, entries, rows, columns):
	order = {e.name: i for i, e in enumerate(entries)}
	by_item = {}
	for r in rows:
		by_item.setdefault(r.item_code, []).append(r)

	data = []
	for i in wo.items:
		mine = by_item.get(i.item_code, [])
		std_qty = sum(flt(r.required_qty) for r in mine)
		act_qty = sum(flt(r.consumed_qty) for r in mine)
		std_cost = sum(flt(r.std_cost) for r in mine)
		act_cost = sum(flt(r.actual_cost) for r in mine)
		used = sorted((r for r in mine if flt(r.consumed_qty) > 0), key=lambda r: order[r.parent])
		last_price = ratio(used[-1].actual_cost, used[-1].consumed_qty) if used else 0
		avg_price = ratio(act_cost, act_qty)
		master = frappe.db.get_value(
			"Item", i.item_code, ["last_purchase_rate", "valuation_rate"], as_dict=True
		)
		master_price = flt(master.last_purchase_rate) or flt(master.valuation_rate) if master else 0
		balance_qty = flt(flt(i.qty_per_unit) * flt(wo.pending_qty), 3)
		data.append(
			{
				"item": i.item_code,
				"item_name": i.item_name,
				"uom": i.uom,
				"bom_qty": flt(flt(i.qty_per_unit) * flt(wo.planned_qty), 3),
				"std_qty": flt(std_qty, 3),
				"act_qty": flt(act_qty, 3),
				"qty_var": flt(act_qty - std_qty, 3),
				"qty_var_pct": flt(ratio(act_qty - std_qty, std_qty, 100), 2),
				"avg_price": avg_price,
				"last_price": last_price,
				"master_price": master_price,
				"std_cost": flt(std_cost, 2),
				"act_cost": flt(act_cost, 2),
				"cost_var": flt(act_cost - std_cost, 2),
				"cost_var_pct": flt(ratio(act_cost - std_cost, std_cost, 100), 2),
				"cost_share_pct": 0,
				"unit_cost": ratio(act_cost, wo.produced_qty),
				"balance_qty_needed": balance_qty,
				"balance_cost_est": flt(balance_qty * (avg_price or master_price), 2),
				"wip_qty": flt(
					frappe.db.get_value(
						"Bin", {"item_code": i.item_code, "warehouse": wo.wip_warehouse}, "actual_qty"
					)
					or 0,
					3,
				),
			}
		)

	total_act = sum(d["act_cost"] for d in data)
	for d in data:
		d["cost_share_pct"] = flt(ratio(d["act_cost"], total_act, 100), 2)

	# quantities are not added up: ingredients are in different units
	total = {c["fieldname"]: None for c in columns}
	total_std = sum(d["std_cost"] for d in data)
	total.update(
		{
			"item": _("Total"),
			"std_cost": flt(total_std, 2),
			"act_cost": flt(total_act, 2),
			"cost_var": flt(total_act - total_std, 2),
			"cost_var_pct": flt(ratio(total_act - total_std, total_std, 100), 2),
			"cost_share_pct": 100 if total_act else 0,
			"unit_cost": ratio(total_act, wo.produced_qty),
			"balance_cost_est": flt(sum(d["balance_cost_est"] for d in data), 2),
		}
	)
	data.append(total)

	labels = [d["item"] for d in data[:-1]]
	chart = {
		"data": {
			"labels": labels,
			"datasets": [
				{"name": _("Std Cost"), "values": [d["std_cost"] for d in data[:-1]]},
				{"name": _("Actual Cost"), "values": [d["act_cost"] for d in data[:-1]]},
			],
		},
		"type": "bar",
		"fieldtype": "Currency",
	}
	return data, chart


def entry_view(wo, entries, columns):
	data = []
	for e in entries:
		std, act = flt(e.total_std_cost), flt(e.total_actual_cost)
		data.append(
			{
				"entry": e.name,
				"posting_date": e.posting_date,
				"batch_no": e.batch_no,
				"output": flt(e.output_qty, 3),
				"cum_before": flt(e.cum_before, 3),
				"cum_after": flt(flt(e.cum_before) + flt(e.output_qty), 3),
				"std_cost": flt(std, 2),
				"act_cost": flt(act, 2),
				"cost_var": flt(act - std, 2),
				"cost_var_pct": flt(ratio(act - std, std, 100), 2),
				"cost_efficiency_pct": flt(e.cost_efficiency_pct, 2),
				"fg_rate": fg_rate(e.stock_entry),
				"stock_entry": e.stock_entry,
			}
		)
	tot_std = sum(d["std_cost"] for d in data)
	tot_act = sum(d["act_cost"] for d in data)
	total = {c["fieldname"]: None for c in columns}
	total.update(
		{
			"entry": _("Total"),
			"output": flt(sum(d["output"] for d in data), 3),
			"std_cost": flt(tot_std, 2),
			"act_cost": flt(tot_act, 2),
			"cost_var": flt(tot_act - tot_std, 2),
			"cost_var_pct": flt(ratio(tot_act - tot_std, tot_std, 100), 2),
			"cost_efficiency_pct": flt(ratio(tot_std, tot_act, 100), 2),
		}
	)
	data.append(total)
	return data


# ------------------------------------------------------------------ top of the report
def get_summary(wo, entries, rows):
	currency = frappe.get_cached_value("Company", wo.company, "default_currency")
	produced = flt(wo.produced_qty, 3)
	cards = [
		{"label": _("Plan Qty"), "value": flt(wo.planned_qty, 3), "datatype": "Float"},
		{"label": _("Produced Qty"), "value": produced, "datatype": "Float"},
		{"label": _("Balance Qty"), "value": flt(wo.pending_qty, 3), "datatype": "Float"},
		{"label": _("Completion %"), "value": flt(wo.completion_pct, 2), "datatype": "Percent"},
	]
	if entries:
		std = sum(flt(r.std_cost) for r in rows)
		act = sum(flt(r.actual_cost) for r in rows)
		var = act - std
		cards += [
			{
				"label": _("Total Std Cost"),
				"value": flt(std, 2),
				"datatype": "Currency",
				"currency": currency,
			},
			{
				"label": _("Total Actual Cost"),
				"value": flt(act, 2),
				"datatype": "Currency",
				"currency": currency,
			},
			{
				"label": _("Cost Variance"),
				"value": flt(var, 2),
				"datatype": "Currency",
				"currency": currency,
				"indicator": "Red" if var > 0 else "Green",
			},
			{
				"label": _("Unit Std Cost"),
				"value": flt(ratio(std, produced), 4),
				"datatype": "Currency",
				"currency": currency,
			},
			{
				"label": _("Unit Actual Cost"),
				"value": flt(ratio(act, produced), 4),
				"datatype": "Currency",
				"currency": currency,
			},
			{"label": _("Cost Efficiency %"), "value": flt(ratio(std, act, 100), 2), "datatype": "Percent"},
		]
	cards.append({"label": _("Entries"), "value": len(entries), "datatype": "Int"})
	return cards


def get_message(wo, entries, empty=False):
	head = "<b>{0}:</b> {1} ({2}) &nbsp;|&nbsp; <b>{3}:</b> {4}".format(
		_("Item"),
		escape_html(wo.item_code),
		escape_html(wo.item_name or ""),
		_("Status"),
		escape_html(wo.status),
	)
	if empty:
		return f"{head}<br>{_('No submitted Production Entries yet')}"
	batches = []
	for e in entries:
		if e.batch_no and e.batch_no not in batches:
			batches.append(e.batch_no)
	return "{0}<br><b>{1}:</b> {2} &nbsp;|&nbsp; <b>{3}:</b> {4} &ndash; {5}<br><span class='text-muted'>{6}</span>".format(
		head,
		_("Batches"),
		escape_html(", ".join(batches) or "-"),
		_("Entries"),
		formatdate(entries[0].posting_date),
		formatdate(entries[-1].posting_date),
		_(NOTE),
	)


# ------------------------------------------------------------------ columns
def raw_columns():
	def col(label, name, ftype="Float", width=100, **kw):
		return {"label": _(label), "fieldname": name, "fieldtype": ftype, "width": width, **kw}

	return [
		col("Item", "item", "Link", 110, options="Item"),
		col("Item Name", "item_name", "Data", 170),
		col("UOM", "uom", "Link", 60, options="UOM"),
		col("BOM Qty", "bom_qty", precision=3),
		col("Std Qty", "std_qty", precision=3),
		col("Actual Qty", "act_qty", precision=3),
		col("Qty Variance", "qty_var", precision=3),
		col("Qty Variance %", "qty_var_pct", "Percent", 90),
		col("Avg Price", "avg_price", "Currency", precision=4),
		col("Last Price", "last_price", "Currency", precision=4),
		col("Master Price", "master_price", "Currency", precision=4),
		col("Std Cost", "std_cost", "Currency"),
		col("Actual Cost", "act_cost", "Currency"),
		col("Cost Variance", "cost_var", "Currency"),
		col("Cost Variance %", "cost_var_pct", "Percent", 90),
		col("Cost Share %", "cost_share_pct", "Percent", 90),
		col("Unit Cost", "unit_cost", "Currency", precision=4),
		col("Balance Qty Needed", "balance_qty_needed", width=120, precision=3),
		col("Balance Cost Est.", "balance_cost_est", "Currency", 115),
		col("In WIP", "wip_qty", precision=3),
	]


def entry_columns():
	def col(label, name, ftype="Float", width=100, **kw):
		return {"label": _(label), "fieldname": name, "fieldtype": ftype, "width": width, **kw}

	return [
		col("Entry", "entry", "Link", 140, options="Custom Production Entry"),
		col("Date", "posting_date", "Date", 95),
		col("Batch", "batch_no", "Data", 140),
		col("Output", "output", precision=3),
		col("Already Produced", "cum_before", width=115, precision=3),
		col("Produced After", "cum_after", width=115, precision=3),
		col("Std Cost", "std_cost", "Currency"),
		col("Actual Cost", "act_cost", "Currency"),
		col("Cost Variance", "cost_var", "Currency"),
		col("Cost Variance %", "cost_var_pct", "Percent", 95),
		col("Cost Efficiency %", "cost_efficiency_pct", "Percent", 110),
		col("FG Rate", "fg_rate", "Currency", precision=4),
		col("Stock Entry", "stock_entry", "Link", 140, options="Stock Entry"),
	]
