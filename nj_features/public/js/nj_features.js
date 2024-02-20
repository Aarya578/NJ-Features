$(document).ready(function() {
    $(document.body).addClass('full-width');
    localStorage.setItem('container_fullwidth', true);
    $('.layout-side-section').hide();
    $('.widget.widget-shadow.shortcut-widget-box [data-widget-name="086f270dbb"]')
});

frappe.ui.form.on('NJ QC Check List', {
    refresh(frm) {
        frm.fields_dict.description.$input.css('height', '80px');
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
        cur_frm.page.wrapper.find(".comment-box").css({'display':'none'});
    }
});

frappe.ui.form.on('Department', {
    refresh() {
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
    }
});

frappe.ui.form.on('NJ Quality Checks', {
    refresh(frm) {
        frm.fields_dict.activity.$input.css('height', '80px');
        $('span.sidebar-toggle-btn').hide();
        $('.col-lg-2.layout-side-section').hide();
        cur_frm.page.wrapper.find(".comment-box").css({'display':'none'});
    }
});

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

        if (frappe.user.has_role('Administrator')) {
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
