frappe.ui.form.on('Knowledge Base', {
    onload: function(frm) {
        $('.col-lg-2.layout-side-section').hide();
        // Fetch the attachment URL from NJ Settings
        frappe.db.get_value('NJ Settings', {'parameter': 'kb_url'}, 'value', function(response) {
			
            if (response) {	
				var attachmentUrl = response.value;
				console.log("attachmentUrl", attachmentUrl)
                // Add attachment buttons with fetched attachment URL
                addAttachmentButton(frm, 'attach1', attachmentUrl);
                addAttachmentButton(frm, 'attach2', attachmentUrl);
                addAttachmentButton(frm, 'attach3', attachmentUrl);
                addAttachmentButton(frm, 'attach4', attachmentUrl);
            }
        });
       

    },
    refresh: function(frm) {
        $('.col-lg-2.layout-side-section').hide();
        if(frm.doc.docstatus == 1) {
            frappe.db.get_value('NJ Settings', {'parameter': 'kb_url'}, 'value', function(response) {
                // console.log("attachmentUrl", response)
                if (response) {	
                    var attachmentUrl = response.value;
                    console.log("attachmentUrl", attachmentUrl)
                    // Add attachment buttons with fetched attachment URL
                    addAttachmentButton(frm, 'attach1', attachmentUrl);
                    addAttachmentButton(frm, 'attach2', attachmentUrl);
                    addAttachmentButton(frm, 'attach3', attachmentUrl);
                    addAttachmentButton(frm, 'attach4', attachmentUrl);
                }
            });
        }
    }
});

function addAttachmentButton(frm, fieldname, attachmentUrl) {
    // Check if the button is already added to the field
    let smallText = ['attach1', 'attach2', 'attach3', 'attach4'];

    smallText.forEach(fieldName => {
        frm.fields_dict[fieldName].$input.css('height', '40px');
    });
    if (!frm.fields_dict[fieldname].$wrapper.find('.btn-attach-wrapper').length) {
        var field = frm.fields_dict[fieldname];
        var field_row = field.$wrapper.closest('.frappe-control');

        var button_wrapper = $('<div class="btn-attach-wrapper"></div>').appendTo(field_row);
        var button = $('<button class="btn btn-default btn-xs">View</button>');

        button.appendTo(button_wrapper);
        button.on('click', function() {
            var attachment_link = frm.doc[fieldname];
            if (attachment_link) {
                var fullAttachmentUrl = attachmentUrl + attachment_link;
                displayAttachment(fullAttachmentUrl);
            } else {
                frappe.msgprint('Attachment link is empty');
            }
        });
    }
}


function displayAttachment(attachment_link) {
    console.log("Displaying attachment:", attachment_link);

    // Determine the attachment type and display accordingly
    if (isImage(attachment_link)) {
        displayImage(attachment_link);
    } else if (isVideo(attachment_link)) {
        displayVideo(attachment_link);
    } else if (isTextFile(attachment_link)) {
        displayTextFile(attachment_link);
    } else {
        frappe.msgprint('Unsupported attachment type');
    }
}

function isImage(url) {
    return /\.(jpeg|jpg|gif|png)$/i.test(url);
}

function isVideo(url) {
    return /\.(mp4|webm|ogg)$/i.test(url);
}

function isTextFile(url) {
    return /\.(txt)$/i.test(url);
}

function displayImage(url) {
    var modal_content = `
        <div class="modal fade" tabindex="-1" role="dialog">
            <div class="modal-dialog modal-lg" role="document">
                <div class="modal-content">
                    <div class="modal-body">
                        <img src="${url}" class="img-fluid" style="width: 100%; height: auto;" alt="Attachment Image">
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-default" data-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    $(modal_content).modal('show');
}

function displayVideo(url) {
    var modal_content = `
        <div class="modal fade" id="videoModal" tabindex="-1" role="dialog">
            <div class="modal-dialog modal-lg" role="document"> 
                <div class="modal-content">
                    <div class="modal-body">
                        <video id="videoPlayer" controls style="width: 100%; height: auto;" class="img-fluid">
                            <source src="${url}" type="video/mp4">
                            Your browser does not support the video tag.
                        </video>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-default" id="closeModal" data-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    var $modal = $(modal_content);
    $modal.modal('show');

    // Bind to the modal's hidden event
    $modal.on('hidden.bs.modal', function (e) {
        var video = document.getElementById('videoPlayer');
        video.pause(); // Pause the video when the modal is closed
    });
}

function displayTextFile(url) {
    var modal_content = `
        <div class="modal fade" tabindex="-1" role="dialog">
            <div class="modal-dialog modal-lg" role="document"> <!-- Increase modal size for text files -->
                <div class="modal-content">
                    <div class="modal-body">
                        <iframe src="${url}" class="iframe-fluid"  style="width: 100%; height: 300px;"></iframe>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-default" data-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        </div>
    `;


    $(modal_content).modal('show');
}