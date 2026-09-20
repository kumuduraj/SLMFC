frappe.query_reports["Shopfloor Efficiency"] = {
  filters: [
    { fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.month_start(), reqd: 1 },
    { fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
    { fieldname: "item_code", label: __("FG Item"), fieldtype: "Link", options: "Item" },
    { fieldname: "raw_item", label: __("Raw Material"), fieldtype: "Link", options: "Item" },
  ],
};
