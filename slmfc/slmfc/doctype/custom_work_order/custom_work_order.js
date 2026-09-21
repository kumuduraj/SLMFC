frappe.ui.form.on("Custom Work Order", {
  refresh(frm) {
    if (frm.is_new()) return;
    frm.set_intro(
      __("Produced {0} of {1} {2} ({3}%). Pending {4}.", [
        format_number(frm.doc.produced_qty, null, 3),
        format_number(frm.doc.planned_qty, null, 3),
        frm.doc.uom || "",
        frm.doc.completion_pct || 0,
        format_number(frm.doc.pending_qty, null, 3),
      ]),
      frm.doc.status === "Completed" ? "green" : "blue"
    );
    if (frm.doc.status !== "Completed") {
      frm
        .add_custom_button(__("Make Production Entry"), () => {
          frappe.call({
            method: "slmfc.slmfc.doctype.custom_production_entry.custom_production_entry.make_production_entry",
            args: { work_order: frm.doc.name },
            callback(r) {
              if (!r.message) return;
              frappe.model.sync(r.message);
              frappe.set_route("Form", "Custom Production Entry", r.message.name);
            },
          });
        })
        .addClass("btn-primary");
    }
    frm.add_custom_button(
      __("Production Entries"),
      () => frappe.set_route("List", "Custom Production Entry", { work_order: frm.doc.name }),
      __("View")
    );
    frm.add_custom_button(
      __("Costing"),
      () => frappe.set_route("query-report", "Work Order Costing", { work_order: frm.doc.name }),
      __("View")
    );
  },
});
