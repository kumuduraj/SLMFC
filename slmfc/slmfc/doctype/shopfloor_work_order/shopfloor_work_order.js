const TOLERANCE_PCT = 2;

function recalc_row(cdt, cdn) {
  const r = locals[cdt][cdn];
  const v = flt(r.consumed_qty) - flt(r.required_qty);
  frappe.model.set_value(cdt, cdn, "variance_qty", flt(v, 6));
  frappe.model.set_value(cdt, cdn, "variance_pct", r.required_qty ? flt((v / r.required_qty) * 100, 2) : 0);
}

frappe.ui.form.on("Shopfloor Work Order", {
  refresh(frm) {
    if (frm.doc.docstatus === 0 && !frm.is_new()) {
      frm.set_intro(
        __("Enter Output Qty. Actual Qty defaults to the BOM qty. Change it to what was really used, then Submit."),
        "blue"
      );
    }
    if (frm.doc.stock_entry) {
      frm.add_custom_button(__("Stock Entry"), () =>
        frappe.set_route("Form", "Stock Entry", frm.doc.stock_entry)
      , __("View"));
    }
  },
  output_qty(frm) {
    if (frm.doc.docstatus !== 0) return;
    (frm.doc.items || []).forEach((r) => {
      const std = flt(r.qty_per_unit * flt(frm.doc.output_qty), 6);
      frappe.model.set_value(r.doctype, r.name, "required_qty", std);
      frappe.model.set_value(r.doctype, r.name, "consumed_qty", std);
    });
    frm.set_value("yield_pct", frm.doc.planned_qty ? flt((frm.doc.output_qty / frm.doc.planned_qty) * 100, 2) : 0);
  },
});

frappe.ui.form.on("Shopfloor Work Order Item", {
  consumed_qty(frm, cdt, cdn) {
    recalc_row(cdt, cdn);
    const r = locals[cdt][cdn];
    if (Math.abs(flt(r.variance_pct)) > TOLERANCE_PCT) {
      frappe.show_alert({
        message: __("{0}: variance {1}%. A reason is required.", [r.item_code, r.variance_pct]),
        indicator: "orange",
      });
    }
  },
});
