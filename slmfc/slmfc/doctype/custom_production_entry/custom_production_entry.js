const TOLERANCE_PCT = 2;
const MIN_VARIANCE_QTY = 0.005;
const ENTRY_METHOD = "slmfc.slmfc.doctype.custom_production_entry.custom_production_entry.";

const ceil3 = (x) => Math.ceil(flt(x) * 1000 - 1e-6) / 1000;
const cum_std = (per, before, out) =>
  flt(ceil3(flt(per) * (flt(before) + flt(out))) - ceil3(flt(per) * flt(before)), 3);

function recalc_row(cdt, cdn) {
  const r = locals[cdt][cdn];
  const v = flt(r.consumed_qty) - flt(r.required_qty);
  frappe.model.set_value(cdt, cdn, "variance_qty", flt(v, 3));
  frappe.model.set_value(cdt, cdn, "variance_pct", r.required_qty ? flt((v / r.required_qty) * 100, 2) : 0);
}

function recalc_all(frm) {
  (frm.doc.items || []).forEach((r) => {
    const std = cum_std(r.qty_per_unit, frm.doc.cum_before, frm.doc.output_qty);
    frappe.model.set_value(r.doctype, r.name, "required_qty", std);
    frappe.model.set_value(r.doctype, r.name, "consumed_qty", std);
  });
  const planned = flt(frm.doc.planned_qty);
  frm.set_value(
    "completion_pct",
    planned ? flt(((flt(frm.doc.cum_before) + flt(frm.doc.output_qty)) / planned) * 100, 2) : 0
  );
}

const SHORT_CSS = ".grid-row.slmfc-short .data-row { background-color: var(--bg-orange, #fff3e0); }";

function short_of(r) {
  return flt(Math.max(0, flt(r.consumed_qty) - flt(r.wip_qty)), 3);
}

function update_shortfall(frm) {
  if (frm.doc.docstatus !== 0) return;
  const rows = frm.doc.items || [];
  const n = rows.filter((r) => flt(r.short_qty) > 0).length;
  frappe.dom.set_style(SHORT_CSS, "slmfc-short-style");
  const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
  if (grid) {
    grid.grid_rows.forEach((gr) => $(gr.wrapper).toggleClass("slmfc-short", flt(gr.doc.short_qty) > 0));
  }
  if (n) {
    frm.set_intro(
      __("{0} item(s) short in WIP ({1}). Transfer raw material to WIP before submitting.", [n, frm.doc.wip_warehouse || ""]),
      "orange"
    );
  } else {
    frm.set_intro(
      __("Enter Output Qty. Standard and Actual Qty follow it. Adjust Actual Qty to what was really used, then Submit."),
      "blue"
    );
  }
}

function refresh_wip(frm) {
  const rows = frm.doc.items || [];
  if (!frm.doc.wip_warehouse || !rows.length) return;
  frappe.call({
    method: ENTRY_METHOD + "get_wip_balances",
    args: { warehouse: frm.doc.wip_warehouse, item_codes: rows.map((r) => r.item_code) },
    callback(r) {
      const bal = r.message || {};
      rows.forEach((row) => {
        const have = flt(bal[row.item_code], 3);
        frappe.model.set_value(row.doctype, row.name, "wip_qty", have);
        frappe.model.set_value(row.doctype, row.name, "short_qty", short_of({ consumed_qty: row.consumed_qty, wip_qty: have }));
      });
      frm.refresh_field("items");
      update_shortfall(frm);
      frappe.show_alert({ message: __("WIP stock refreshed"), indicator: "green" });
    },
  });
}

function suggest_batch(frm) {
  if (!frm.doc.has_batch || frm.doc.batch_mode !== "Auto" || !frm.doc.item_code) return;
  frappe.call({
    method: ENTRY_METHOD + "suggest_batch_no",
    args: { item_code: frm.doc.item_code, posting_date: frm.doc.posting_date },
    callback(r) {
      if (r.message) frm.set_value("batch_no", r.message);
    },
  });
}

frappe.ui.form.on("Custom Production Entry", {
  setup(frm) {
    frm.set_query("work_order", () => ({ filters: { status: ["!=", "Completed"] } }));
  },
  refresh(frm) {
    if (frm.doc.docstatus === 0) {
      update_shortfall(frm);
      frm.add_custom_button(__("Refresh WIP Stock"), () => refresh_wip(frm));
    }
    if (frm.doc.stock_entry) {
      frm.add_custom_button(
        __("Stock Entry"),
        () => frappe.set_route("Form", "Stock Entry", frm.doc.stock_entry),
        __("View")
      );
    }
    if (frm.doc.work_order) {
      frm.add_custom_button(
        __("Work Order"),
        () => frappe.set_route("Form", "Custom Work Order", frm.doc.work_order),
        __("View")
      );
    }
  },
  work_order(frm) {
    if (!frm.is_new() || !frm.doc.work_order) return;
    frappe.call({
      method: ENTRY_METHOD + "make_production_entry",
      args: { work_order: frm.doc.work_order },
      callback(r) {
        const d = r.message;
        if (!d) return;
        [
          "plan", "company", "item_code", "item_name", "bom", "uom", "wip_warehouse", "target_warehouse",
          "planned_qty", "cum_before", "output_qty", "completion_pct", "has_batch", "batch_mode", "batch_no",
        ].forEach((f) => frm.set_value(f, d[f]));
        frm.clear_table("items");
        (d.items || []).forEach((row) =>
          frm.add_child("items", {
            item_code: row.item_code,
            item_name: row.item_name,
            uom: row.uom,
            qty_per_unit: row.qty_per_unit,
            required_qty: row.required_qty,
            consumed_qty: row.consumed_qty,
            wip_qty: row.wip_qty,
            short_qty: row.short_qty,
          })
        );
        frm.refresh_field("items");
        update_shortfall(frm);
      },
    });
  },
  output_qty(frm) {
    if (frm.doc.docstatus !== 0) return;
    recalc_all(frm);
  },
  posting_date(frm) {
    if (frm.doc.docstatus === 0) suggest_batch(frm);
  },
  batch_mode(frm) {
    if (frm.doc.docstatus !== 0) return;
    if (frm.doc.batch_mode === "Auto") {
      suggest_batch(frm);
    } else {
      frm.set_value("batch_no", "");
      if (frm.fields_dict.batch_no && frm.fields_dict.batch_no.$input) frm.fields_dict.batch_no.$input.focus();
    }
  },
  batch_no(frm) {
    if (frm.doc.docstatus !== 0 || !frm.doc.has_batch || !frm.doc.batch_no) return;
    frappe.call({
      method: ENTRY_METHOD + "check_batch",
      args: { batch_no: frm.doc.batch_no, item_code: frm.doc.item_code, work_order: frm.doc.work_order },
      callback(r) {
        const res = r.message || {};
        if (res.status === "duplicate") {
          frappe.msgprint({ title: __("Batch"), message: res.message, indicator: "red" });
          frm.set_value("batch_no", "");
        } else if (res.status === "continue") {
          frappe.show_alert({ message: res.message, indicator: "blue" });
        }
      },
    });
  },
});

frappe.ui.form.on("Custom Production Entry Item", {
  consumed_qty(frm, cdt, cdn) {
    recalc_row(cdt, cdn);
    const r = locals[cdt][cdn];
    frappe.model.set_value(cdt, cdn, "short_qty", short_of(r));
    update_shortfall(frm);
    if (Math.abs(flt(r.variance_pct)) > TOLERANCE_PCT && Math.abs(flt(r.variance_qty)) > MIN_VARIANCE_QTY) {
      frappe.show_alert({
        message: __("{0}: variance {1}%. A reason is required.", [r.item_code, r.variance_pct]),
        indicator: "orange",
      });
    }
  },
});
