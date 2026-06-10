frappe.listview_settings['Daily Individual Report'] = {
    filters: [["owner", "=", frappe.session.user]],

    onload: function() {
        toggleFilterSelector();
    },

    refresh: function() {
        hideSidebarElements();
        toggleFilterSelector();
    }
};

function toggleFilterSelector() {
    const isAdminOrDeveloper = frappe.boot.user.roles.some(role => role === "Developer" || role === "Administrator");
    $('.filter-selector').toggle(isAdminOrDeveloper);
}

function hideSidebarElements() {
    $('span.sidebar-toggle-btn').hide();
    $('.col-lg-2.layout-side-section').hide();
}