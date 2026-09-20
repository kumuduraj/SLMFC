frappe.ui.form.on("Shopfloor Plan", {
  setup(frm) {
    ["source_warehouse", "wip_warehouse", "target_warehouse"].forEach((f) =>
      frm.set_query(f, () => ({ filters: { company: frm.doc.company, is_group: 0, disabled: 0 } }))
    );
    frm.set_query("bom", "items", (doc, cdt, cdn) => ({
      filters: { item: locals[cdt][cdn].item_code, is_active: 1, docstatus: 1 },
    }));
  },
  refresh(frm) {
    if (frm.is_new() && !frm.doc.company) {
      frm.set_value("company", frappe.defaults.get_user_default("Company"));
    }
    if (frm.doc.docstatus === 1 && frm.doc.material_request) {
      frm.add_custom_button(__("Material Request"), () =>
        frappe.set_route("Form", "Material Request", frm.doc.material_request)
      , __("View"));
    }
  },
});

frappe.ui.form.on("Shopfloor Plan Item", {
  item_code(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.item_code) return;
    frappe.db
      .get_value("BOM", { item: row.item_code, is_default: 1, is_active: 1, docstatus: 1 }, "name")
      .then((r) => frappe.model.set_value(cdt, cdn, "bom", (r.message || {}).name || ""));
  },
});
