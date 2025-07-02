frappe.ui.form.on('Knowledge Base', {
    refresh: function (frm) {
        $('.col-lg-2.layout-side-section').hide();
        addAttachmentButtons(frm);
    },
    before_save: function (frm) {
        frappe.call({
            method: "nj_features.nj_features.doctype.knowledge_base.knowledge_base.validate_links",
            args: { doc: frm.doc },
        })
    },
    qc_name: function (frm) {
        let wrapper = $('[data-fieldname="qc_value"]').closest('.control-input-wrapper');
        if (frm.doc.qc_name  && frm.doc.qc_name !== '') {
            frappe.call({
                method: "nj_p1_features.nj_p1_features.doctype.nj_quality_checks.nj_quality_checks.process_check_name_options",
                args: { 'check_name': frm.doc.qc_name },
                callback: function (response) {
                    let options = response.message || [];

                    frm.set_df_property('qc_value', 'options', options.join('\n'));
                    frm.refresh_field('qc_value');

                    if (options.length > 0) {
                        wrapper.css({
                            'border-radius': '0.25rem',
                            'border': '2px solid #5cb85c'
                        });
                    } else {
                        wrapper.css({
                            'border-radius': '0.25rem',
                            'border': '2px solid red'
                        });
                    }
                }
            });
        } else {
            frm.set_df_property('qc_value', 'options', '');
            frm.refresh_field('qc_value');

            wrapper.css({
                'border': '',
                'border-radius': ''
            });
        }
    },
    qc_value: function (frm) {
        if (frm.doc.qc_value && frm.doc.qc_value.trim() !== '') {
            const newEntry = frm.doc.qc_name + '::' + frm.doc.qc_value;

            if (frm.doc.qc_options && frm.doc.qc_options.trim() !== '') {
                let existingEntries = frm.doc.qc_options
                    .split(',')
                    .map(entry => entry.trim());

                if (!existingEntries.includes(newEntry)) {
                    existingEntries.push(newEntry);
                    frm.set_value('qc_options', existingEntries.join(', '));
                }
            } else {
                frm.set_value('qc_options', newEntry);
            }
        }
    }
});

function addAttachmentButtons(frm) {
    addAttachmentButton(frm, 'attach1');
    addAttachmentButton(frm, 'attach2');
    addAttachmentButton(frm, 'attach3');
    addAttachmentButton(frm, 'attach4');
}

function addAttachmentButton(frm, fieldname) {
    let field = frm.fields_dict[fieldname];
    let field_row = field.$wrapper.closest('.frappe-control');

    // Increase the height of the input field
    field.$input.css('height', '40px');

    // Remove existing button wrapper if any
    field_row.find('.btn-attach-wrapper').remove();

    // Create a wrapper for the button
    var button_wrapper = $('<div class="btn-attach-wrapper"></div>').appendTo(field_row);
    var button = $('<button class="btn btn-default btn-xs">View</button>');

    // Append the button to the wrapper
    button.appendTo(button_wrapper);

    // Add click event to handle displaying the attachment
    button.on('click', function () {
        var attachment_link = frm.doc[fieldname];
        if (attachment_link) {
            var embeddableLink = getEmbeddableLink(attachment_link);
            displayInModal(embeddableLink); // Show the link in modal iframe
        } else {
            frappe.msgprint('No attachment available for this field');
        }
    });
}

function getEmbeddableLink(url) {
    if (url.includes('drive.google.com')) {
        // Convert Google Drive share link to embeddable link
        let match = url.match(/\/d\/([a-zA-Z0-9_-]+)/);
        if (match && match[1]) {
            return `https://drive.google.com/file/d/${match[1]}/preview`;
        }
        frappe.msgprint('Invalid Google Drive link');
    }
    return url; // Return the original URL if not Google Drive
}


function displayInModal(url) {
    let content = '';
    if (isImage(url)) {
        // Display image directly
        content = `<img src="${url}" class="img-fluid" alt="Attachment" style="max-width: 100%; height: auto;">`;
    } else if (isVideo(url)) {
        // Display video directly
        content = `
            <video controls style="width: 100%; height: auto;">
                <source src="${url}" type="video/mp4">
                Your browser does not support the video tag.
            </video>`;
    } else {
        // Default to iframe for other types
        content = `<iframe src="${url}" class="iframe-fluid" style="width: 100%; height: 500px; border: none;"></iframe>`;
    }

    var modal_content = `
        <div class="modal fade" tabindex="-1" role="dialog">
            <div class="modal-dialog modal-lg" role="document">
                <div class="modal-content">
                    <div class="modal-body text-center">
                        ${content}
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-default" data-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    var $modal = $(modal_content);
    $modal.modal('show');
}

function isImage(url) {
    return /\.(jpg|jpeg|png|gif|bmp|webp)$/i.test(url);
}

function isVideo(url) {
    return /\.(mp4|webm|ogg|mov)$/i.test(url);
}