document.addEventListener('keydown', function(event) {
    if ((event.ctrlKey && event.shiftKey && (event.key === 'I' || event.key === 'J')) || event.key === 'F12') {
        event.preventDefault(); 
    }
});

$(document).ready(function() {
    $(document.body).addClass('full-width');
    localStorage.setItem('container_fullwidth', true);
    
});

frappe.listview_settings['Non Compliance'] = {
    onload() {
        $('.col-lg-2.layout-side-section').hide();
    }
};

frappe.ui.form.on('Serial No', {
    refresh() {
        $('.col-lg-2.layout-side-section').hide();
    }
});

frappe.ui.form.on('User', {
    refresh() {
        $('.col-lg-2.layout-side-section').hide();
        if (!frappe.user.has_role('Developer')) {

            cur_frm.set_df_property('sb1', 'hidden', 1);
            cur_frm.set_df_property('roles', 'hidden', 1);
            cur_frm.set_df_property('roles_html', 'hidden', 1);
            cur_frm.set_df_property('api_access', 'hidden', 1);
            cur_frm.set_df_property('role_profile_name', 'hidden', 1);
            cur_frm.refresh_field('sb1');
            cur_frm.refresh_field('roles');
            cur_frm.refresh_field('roles_html');
            cur_frm.refresh_field('api_access');
            cur_frm.refresh_field('sb_allow_modules');
            cur_frm.refresh_field('role_profile_name');
        
            cur_frm.set_df_property('restrict_ip', 'read_only', 1);
            cur_frm.set_df_property('simultaneous_sessions', 'read_only', 1);

            cur_frm.refresh_field('restrict_ip');
            cur_frm.refresh_field('simultaneous_sessions');
        }
    }
});

frappe.ui.form.on('Department', {
    refresh() {
        $('.col-lg-2.layout-side-section').hide();
    }
});

frappe.listview_settings['Prepared Report'] = {
    onload: function(listview) {
        filters: [['created_by', '=', frappe.session.user_email]],
        listview.refresh();
        $('.col-lg-2.layout-side-section').hide();
    }
};

frappe.provide('frappe.ui.misc');
frappe.ui.misc.about = function() {
    if (!frappe.ui.misc.about_dialog) {
        var d = new frappe.ui.Dialog({title: __('NewJaisa Technologies Limited')});

        var aboutContent = "<div>\
            <p>"+__("Follow us")+"</p>\
            <p><i class='fa fa-globe fa-fw'></i>\
                Website: <a href='https://newjaisa.com' target='_blank'>https://newjaisa.com</a></p>\
            <p><i class='fa fa-instagram fa-fw'></i>\
                Instagram: <a href='https://www.instagram.com/newjaisa/?igshid=MzRlODBiNWFlZA' target='_blank'>https://www.instagram.com/newjaisa</a></p>\
            <p><i class='fa fa-linkedin fa-fw'></i>\
                Linkedin: <a href='https://in.linkedin.com/company/newjaisa' target='_blank'>https://in.linkedin.com/company/newjaisa</a></p>\
            <p><i class='fa fa-facebook fa-fw'></i>\
                Facebook: <a href='https://www.facebook.com/people/NewJaisa-Technologies/100077760237912/' target='_blank'>https://www.facebook.com/people/NewJaisa-Technologies</a></p>\
            <hr>";

        if (frappe.user.has_role('Administrator') || frappe.user.has_role('Developer')) {
            aboutContent += "<h4>Installed Apps</h4>\
            <div id='about-app-versions'>Loading versions...</div>\
            <hr>";
        }

        aboutContent += "<p class='text-muted'>&copy; NewJaisa Technologies Limited </p>\
            </div>";

        $(d.body).html(repl(aboutContent, frappe.app));

        frappe.ui.misc.about_dialog = d;

        frappe.ui.misc.about_dialog.on_page_show = function() {
            if(!frappe.versions) {
                frappe.call({
                    method: "frappe.utils.change_log.get_versions",
                    callback: function(r) {
                        show_versions(r.message);
                    }
                })
            } else {
                show_versions(frappe.versions);
            }
        };

        var show_versions = function(versions) {
            var $wrap = $("#about-app-versions").empty();
            $.each(Object.keys(versions).sort(), function(i, key) {
                var v = versions[key];
                if(v.branch) {
                    var text = $.format('<p><b>{0}:</b> v{1} ({2})<br></p>',
                        [v.title, v.branch_version || v.version, v.branch])
                } else {
                    var text = $.format('<p><b>{0}:</b> v{1}<br></p>',
                        [v.title, v.version])
                }
                $(text).appendTo($wrap);
            });

            frappe.versions = versions;
        }
    }

    frappe.ui.misc.about_dialog.show();
}

frappe.provide('frappe.user');

$.extend(frappe.user, {
    get_role_profile: function(user_role_profile = null) {
        return new Promise(function(resolve, reject) {
            frappe.db.get_value('Employee', {'user_id': frappe.session.user, 'status': 'Active'}, 'role_profile', function(result) {
                if (result && result.role_profile !== undefined) {

                    if (user_role_profile !== null) {
                        if (result.role_profile === user_role_profile) {
                            resolve(true);
                        } else { resolve(false); }
                    } else { resolve(result.role_profile); }
                } else { resolve(null); }
            });
        });
    }
});