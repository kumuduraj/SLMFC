frappe.query_reports["Work Order Costing"] = {
  filters: [
    { fieldname: "work_order", label: __("Work Order"), fieldtype: "Link", options: "Custom Work Order", reqd: 1 },
    {
      fieldname: "view",
      label: __("View"),
      fieldtype: "Select",
      options: ["By Raw Material", "By Entry"],
      default: "By Raw Material",
    },
  ],
  formatter(value, row, column, data, default_formatter) {
    value = default_formatter(value, row, column, data);
    if (data && ["cost_var", "cost_var_pct", "qty_var", "qty_var_pct"].includes(column.fieldname)) {
      const raw = flt(data[column.fieldname]);
      if (raw > 0) value = `<span style="color: var(--red-600, #c0392b)">${value}</span>`;
      else if (raw < 0) value = `<span style="color: var(--green-600, #2e8b57)">${value}</span>`;
    }
    return value;
  },
};
