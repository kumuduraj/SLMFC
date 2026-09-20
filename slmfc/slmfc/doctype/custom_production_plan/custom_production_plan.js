frappe.ui.form.on("Custom Production Plan", {
  setup(frm) {
    ["wip_warehouse", "target_warehouse", "default_source_warehouse"].forEach((f) =>
      frm.set_query(f, () => ({ filters: { company: frm.doc.company, is_group: 0, disabled: 0 } }))
    );
    frm.set_query("source_warehouse", "materials", () => ({
      filters: { company: frm.doc.company, is_group: 0, disabled: 0 },
    }));
    frm.set_query("bom", "items", (doc, cdt, cdn) => ({
      filters: { item: locals[cdt][cdn].item_code, is_active: 1, docstatus: 1 },
    }));
  },
  refresh(frm) {
    if (frm.is_new() && !frm.doc.company) {
      frm.set_value("company", frappe.defaults.get_user_default("Company"));
    }
    if (frm.doc.docstatus === 0) {
      if (!frm.is_new()) {
        frm.add_custom_button(__("Recalculate Materials"), () => {
          frm.clear_table("materials");
          frm.set_value("materials_signature", "");
          frm.save();
        });
      }
      const short = (frm.doc.materials || []).filter((r) => flt(r.shortfall) > 0);
      if (short.length) {
        frm.set_intro(
          __("Stock is short for {0} raw material row(s): {1}", [
            short.length,
            short.map((r) => r.item_code).join(", "),
          ]),
          "orange"
        );
      } else if (!frm.is_new()) {
        frm.set_intro(
          __("Check the Raw Material Summary: split an item across warehouses by adding rows, then Submit."),
          "blue"
        );
      }
    }
    if (frm.doc.docstatus === 1) {
      if (frm.doc.material_request) {
        frm.add_custom_button(
          __("Material Request"),
          () => frappe.set_route("Form", "Material Request", frm.doc.material_request),
          __("View")
        );
      }
      frm.add_custom_button(
        __("Work Orders"),
        () => frappe.set_route("List", "Custom Work Order", { plan: frm.doc.name }),
        __("View")
      );
    }
  },
});

frappe.ui.form.on("Custom Production Plan Item", {
  item_code(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.item_code) return;
    frappe.db
      .get_value("BOM", { item: row.item_code, is_default: 1, is_active: 1, docstatus: 1 }, "name")
      .then((r) => frappe.model.set_value(cdt, cdn, "bom", (r.message || {}).name || ""));
  },
});
