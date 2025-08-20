frappe.ui.form.on('Delivery Note', {

    // onload: function(frm) {
    //     const snapmintItem = frm.doc.items.find(item => item.against_sales_order && item.against_sales_order.startsWith("SO-Snapmint-"));
    //     if (snapmintItem) {
    //         frm.set_value("courier_service", "Shiprocket Manifest");
    //         frm.set_df_property("courier_service", "read_only", 1);
    //     }
    // },

    refresh: function(frm) {
        // console.log("inside refresh=================================================");
        
        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__('View'), function() {
                fetchAndDisplayLinks(frm, 'nj_features.overrides.delivery_note.get_link_1', 'Video');
            }).addClass('btn-primary');

            frm.add_custom_button(__('Record'), function() {
                openDjangoUrl(frm.doc.doctype, frm.doc.name);
            }).addClass('btn-primary');
        }

        if (frm.doc.__islocal) {
            frm.set_value("posting_time", frappe.datetime.now_time());
        }

        frm.remove_custom_button(__('Print QR Code'));

        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__('Print QR Code'), function() {
                var docname = encodeURIComponent(frm.doc.name);
                var format = "Delivery Note Barcode";
                var print_trigger = 1;

                window.open(frappe.urllib.get_full_url("/printview?" +
                    "doctype=" + encodeURIComponent("Delivery Note") +
                    "&name=" + docname +
                    "&trigger_print=" + print_trigger +
                    "&format=" + format +
                    "&no_letterhead=0" +
                    "&_lang=" + (frappe.boot.lang || "en")));
            }).addClass('btn-primary');
        }
       if (frm.doc.docstatus === 0) {
    // Hide both first to avoid duplicates on refresh
            frm.clear_custom_buttons();
            
            // Show Critical Log button only if AWB number has NOT been generated AND courier_service is not CriticaLog
            if (!frm.doc.tracking_id && frm.doc.courier_service !== 'CriticaLog') {
                let critical_btn = frm.add_custom_button(__('Critical Log'), function() {
                    frappe.show_alert({ message: __('Generating AWB Number...'), indicator: 'blue' });
                    frappe.call({
                        method: 'nj_features.overrides.delivery_note.send_consignement_data',
                        args: { doc: JSON.stringify(frm.doc) },
                        callback: function(response) {
                            if (response.message) {
                                frappe.call({
                                    method: 'frappe.client.set_value',
                                    args: {
                                        doctype: 'Delivery Note',
                                        name: frm.doc.name,
                                        fieldname: 'courier_service',
                                        value: 'CriticaLog'
                                    },
                                    callback: function() {
                                        frm.reload_doc();
                                        frappe.show_alert({
                                            message: __('AWB Number generated successfully!'),
                                            indicator: 'green'
                                        });
                                    }
                                });
                            }
                        }
                    });
                });
                critical_btn.addClass('btn-primary');
            }
            
            // Show Shiprocket button only if AWB number has NOT been generated AND courier_service is not Shiprocket
            if (!frm.doc.tracking_id && frm.doc.courier_service !== 'Shiprocket') {
                let shiprocket_btn = frm.add_custom_button(__('Shiprocket'), function() {
                    frappe.show_alert({ message: __('Generating AWB Number...'), indicator: 'blue' });
                    frappe.call({
                        method: 'nj_features.overrides.delivery_note.shiprocket_awb_number',
                        args: { doc: JSON.stringify(frm.doc) },
                        callback: function(response) {
                            if (response.message) {
                                // Assuming your method sets courier_service to 'Shiprocket'
                                frm.reload_doc();
                                frappe.show_alert({
                                    message: __('AWB Number generated successfully!'),
                                    indicator: 'green'
                                });
                            }
                        }
                    });
                });
                shiprocket_btn.addClass('btn-primary');
            }
        }

        if (frm.doc.docstatus === 1) {
            let shiprocket_btn = frm.add_custom_button(__('Fetch Shiprocket data'), function() {
                frappe.show_alert({ message: __('Fetching Shiprocket data...'), indicator: 'blue' });
                frappe.call({
                    method: 'nj_features.overrides.delivery_note.fetch_shiprocket_details',
                   args: { doc: JSON.stringify(frm.doc) },
                     callback: function(response) {
                            if (response.message) {
                                // Assuming your method sets courier_service to 'Shiprocket'
                                frm.reload_doc();
                                frappe.show_alert({
                                    message: __('Fetched Shiprocket data successfully!'),
                                    indicator: 'green'
                                });
                            }
                        }
                });
            });
            shiprocket_btn.addClass('btn-primary');
        }

    },
    
    onload_post_render: function(frm) {
        frm.remove_custom_button('Credit Note', 'Create');
        frm.page.remove_inner_button('Credit Note', 'Create');
        $('.btn-group.dropdown-menu a:contains("Credit Note")').parent().remove();
    },


    validate:  function(frm) {
        frappe.call({
            method: "nj_features.overrides.delivery_note.validate_delivery_bios",
            args: { doc: frm.doc },
            callback: function(r) {
                if (r.message && Array.isArray(r.message) && r.message.length > 0) {
                    frappe.msgprint({
                        title: __('Validation Error'),
                        message: r.message.join('<br>'),
                        indicator: 'red'
                    });
                    frappe.validated = false;
                } else { frappe.validated = true; }
            }
        });



        frappe.call({
            method: 'nj_features.overrides.delivery_note.update_item_details',
            args: { self: frm.doc },
            callback: function(r) {
                if (r.message) {
                    const { weight, height, length, breadth } = r.message;

                    // Only set values if they are not null or undefined
                    if (weight !== null && weight !== undefined) {
                        frm.set_value('weight', weight);
                    }

                    if (height !== undefined && height !== null) {
                        frm.set_value('height', height);
                    }

                    if (length !== undefined && length !== null) {
                        frm.set_value('length', length);
                    }

                    if (breadth !== undefined && breadth !== null) {
                        frm.set_value('breadth', breadth);
                    }
                    if(cod_amount !== undefined && cod_amount !== null) {
                        frm.set_value('cod_amount', cod_amount);
                    }

                    frm.refresh_fields(['weight', 'height', 'length', 'breadth', 'cod_amount']);
                }
            }
        });

        frappe.call({
            method: "nj_features.overrides.delivery_note.validate_delivery_bios",
            args: { doc: frm.doc },
            callback: function(r) {
                if (r.message && Array.isArray(r.message) && r.message.length > 0) {
                    frappe.msgprint({
                        title: __('Validation Error'),
                        message: r.message.join('<br>'),
                        indicator: 'red'
                    });
                    frappe.validated = false;
                } else {
                    frappe.validated = true;
                }
            }
        });

    },


    // before_submit: async function(frm) {
    //     await frappe.call({
    //         method:'nj_features.overrides.delivery_note.allow_to_save',
    //         args: {
    //             "doc": frm.doc
    //         },
    //         callback: function(r) {
    //             if (r.message) {
    //                 if(r.message!="pass") {
    //                     frappe.validated=false
    //                     frappe.throw(r.message);

    //                 }else{
    //                     frappe.validated=true
    //                 }
    //             }
    //         }
    //     })

    // },
  
    // after_save: function(frm) {
    //     if (!frm.doc.supplier_address_name || frm.doc.supplier_address_name === '' || frm.doc.supplier_address_name === undefined) {
    //         frm.set_value('shipping_address_name', frm.doc.customer_address);
    //         frm.refresh_field('shipping_address_name');
    //     }
    // },
    after_save: function(frm) {
         
        // frappe.call({
        //     method: 'nj_features.overrides.delivery_note.total_item_group_sum',
        //     args: {
        //         doc: JSON.stringify(frm.doc)
        //     },
        //     callback: function(r) {
        //         console.log("Full response:", r);
        //         if (r.message) {
        //             console.log("Response message:", r.message);
        //             if (r.message.item_group_qty !== undefined) {
        //                 console.log("item_group_qty received:", r.message.item_group_qty);
                        
        //                 // Set the value and save the document
        //                 frm.set_value('item_group_qty', r.message.item_group_qty);
        //                 frm.refresh_field('item_group_qty');
                        
        //                 // Save the document to persist the changes
        //                 // frm.save();
        //             } else {
        //                 console.log("item_group_qty not found in response");
        //             }
        //         } else {
        //             console.log("No message in response");
        //         }
        //     },
        //     error: function(r) {
        //         console.log("Error in frappe call:", r);
        //     }
        // });
        frappe.call({
            method: "nj_features.overrides.delivery_note.setting_dispatch_address",
            args: { doc: frm.doc },
            callback: function(r) {
                    if (r.message) {
                        frm.set_value("dispatch_address_name", r.message);
                    }
                }
        });
        frappe.call({
            method: 'nj_features.overrides.delivery_note.fetch_cod_amount',
            args: {
                doc_name: frm.doc.name 
            },
            callback: function(r) {
                if (r.message) {
                    const { cod_amount } = r.message;
                    console.log("Fetched cod_amount:", cod_amount);
                    if (cod_amount !== undefined && cod_amount !== null) {
                        frm.set_value('cod_amount', cod_amount.toString());
                    }
                    frm.refresh_field('cod_amount');
                }
            }
        });
       
        if (!frm.doc.shipping_address_name && frm.doc.customer_address) {
            frm.set_value('shipping_address_name', frm.doc.customer_address);
            frm.refresh_field('shipping_address_name');
        }
    },

    
    // courier_service: function(frm) {
    //     frappe.call({
    //         method: "nj_features.overrides.delivery_note.set_tracking_id_for_delivery_note",
    //         args: { doc: frm.doc },
    //         callback: function(r) {
    //             if (r.message === true) {
    //                 frm.set_df_property('tracking_id', 'reqd', 0);
    //             } else {
    //                 frm.set_df_property('tracking_id', 'reqd', 1);
    //             }
    //         }
    //     });
    // },
    // fetch_cod: function(frm) {
    //     let first_so = frm.doc.items.find(item => item.against_sales_order)?.against_sales_order;
    //     if (first_so) {
    //         frappe.call({
    //             method: "nj_features.overrides.delivery_note.get_cod_amount",
    //             args: { so_name: first_so },
    //             callback: function(res) {
    //                 if (res.message) {
    //                     frm.set_value("cod_amount", res.message.cod_amount); 
    //                     frm.set_value("shopify_order_id", res.message.order_id); 
    //                 }
    //             }
    //         });
    //     }
    // }
});


frappe.ui.form.on('Packed Item', {
    serial_no: function(frm, cdt, cdn) {
        if (!frm.doc.name || frm.doc.__islocal) {  
            frappe.msgprint({
                title: __('Save Required'),
                message: __('Please save the document before entering the Serial Number.'),
                indicator: 'red'
            });
            frappe.model.set_value(cdt, cdn, 'serial_no', ''); 
        }
    }
});


// // Create the modal HTML and inject it into the body
// $(document).ready(function() {
//     var modalHTML = `
//     <div id="cameraModal" class="modal" tabindex="-1" role="dialog">
//         <div class="modal-dialog modal-lg" role="document">
//             <div class="modal-content">
//                 <div class="modal-header">
//                     <h5 class="modal-title">Select Camera & Start Recording</h5>
//                     <button type="button" class="close" data-dismiss="modal" aria-label="Close">
//                         <span aria-hidden="true">&times;</span>
//                     </button>
//                 </div>
//                 <div class="modal-body">
//                     <select id="cameraSelect" class="form-control mb-3"></select>
//                     <video id="videoElement" width="100%" height="400" autoplay></video>
//                     <button id="startRecording" class="btn btn-success">Start Recording</button>
//                     <button id="stopRecording" class="btn btn-danger" style="display:none;">Stop Recording</button>
//                 </div>
//                 <div class="modal-footer">
//                     <button type="button" class="btn btn-secondary" data-dismiss="modal">Close</button>
//                 </div>
//             </div>
//         </div>
//     </div>`;
    
//     $('body').append(modalHTML);  // Append the modal to the page
// });
// // Frappe UI form script
// frappe.ui.form.on('Delivery Note', {
//     refresh: function(frm) {
//         // Add 'Record' button for new documents (docstatus = 0)
//         if (frm.doc.docstatus === 0) {
//             frm.add_custom_button(__('Record'), function() {
//                 // Trigger the modal with camera selection and recording options
//                 showCameraModal(frm.doc.name);  // Pass DN number to modal function
//             }).addClass('btn-warning');
//         }
//     }
// });

// // Function to display the camera modal
// function showCameraModal(dn_number) {
//     $('#cameraModal').modal('show');
    
//     // Get available video input devices (cameras)
//     navigator.mediaDevices.enumerateDevices().then(function(devices) {
//         const videoDevices = devices.filter(device => device.kind === 'videoinput');
//         const cameraSelect = document.getElementById('cameraSelect');
        
//         cameraSelect.innerHTML = '';
//         videoDevices.forEach((device, index) => {
//             const option = document.createElement('option');
//             option.value = device.deviceId;
//             option.text = device.label || `Camera ${index + 1}`;
//             cameraSelect.appendChild(option);
//         });
//     });

//     let mediaRecorder;
//     let recordedChunks = [];

//     document.getElementById('startRecording').onclick = function() {
//         const selectedCamera = document.getElementById('cameraSelect').value;
//         startVideoRecording(selectedCamera);
//     };

//     function startVideoRecording(cameraDeviceId) {
//         navigator.mediaDevices.getUserMedia({
//             video: {
//                 deviceId: { exact: cameraDeviceId }
//             }
//         }).then(function(stream) {
//             const videoElement = document.getElementById('videoElement');
//             videoElement.srcObject = stream;

//             mediaRecorder = new MediaRecorder(stream);
//             recordedChunks = [];

//             mediaRecorder.ondataavailable = function(event) {
//                 if (event.data.size > 0) {
//                     recordedChunks.push(event.data);
//                 }
//             };

//             mediaRecorder.onstop = function() {
//                 const blob = new Blob(recordedChunks, {
//                     type: 'video/webm'
//                 });
//                 uploadVideo(blob, dn_number);  // Pass DN number to upload function
//             };

//             mediaRecorder.start();

//             // UI adjustments
//             document.getElementById('startRecording').style.display = 'none';
//             document.getElementById('stopRecording').style.display = 'inline-block';
//         });
//     }

//     document.getElementById('stopRecording').onclick = function() {
//         mediaRecorder.stop();
//         document.getElementById('startRecording').style.display = 'inline-block';
//         document.getElementById('stopRecording').style.display = 'none';
//     };
// }

// function uploadVideo(blob, dn_number) {
//     // Convert blob to base64
//     let reader = new FileReader();
//     reader.readAsDataURL(blob);
//     reader.onloadend = function() {
//         let base64data = reader.result;
        
//         frappe.call({
//             method: 'nj_features.api_files.upload_video',
//             args: {
//                 file_content: base64data,
//                 file_name: 'recorded_video.webm',
//                 dn_number: dn_number  // Pass DN number to the backend
//             },
//             freeze: true,
//             freeze_message: __("Uploading video..."),z
//             callback: function(r) {
//                 if (r.message === "success") {
//                     frappe.msgprint(__('Video uploaded successfully!'));
//                 } else {
//                     frappe.msgprint(__('Failed to upload video. Error: ') + r.exc);
//                 }
//             },
//             error: function(r) {
//                 frappe.msgprint(__('Failed to upload video. Network error.'));
//             }
//         });
//     }
// }


// Function to open the Django URL directly with the DN number
function openDjangoUrl(doctype,dn_number) {
    // Construct the URL by embedding the dn_number in it
    // let url = `https://njpulse.newjaisa.com/upload/${dn_number}/`;
    frappe.db.get_value("NJ Settings",{"parameter":"video_prefix"},"value").then((prefix)=>{
        let url = `${prefix.message.value}${doctype}/${dn_number}/`;
        window.open(url, '_blank');
    })
}


function fetchAndDisplayLinks(frm, method, type) {
    frappe.call({
        method: method,
        args: { 'name': frm.doc.name },
        callback: function(r) {
            var links = r.message;
            if (links && links.length > 0) {
                var dialog = new frappe.ui.Dialog({
                    title: __('Preview')
                });

                var contentContainer = document.createElement('div');
                for (var i = 0; i < links.length; i++) {
                    var link = links[i].linked_data;
                    var buttonLabel = type + ' ' + (i + 1);
                    var button = document.createElement('button');
                    button.textContent = buttonLabel;
                    button.setAttribute('data-link-url', link);
                    button.classList.add('btn', 'btn-primary', 'preview-button', 'margin-right');
                    button.style.marginRight = '10px';
                    button.style.marginBottom = '10px';
                    button.addEventListener('click', function() {
                        var linkUrl = this.getAttribute('data-link-url');
                        window.open(linkUrl, '_blank');
                    });
                    contentContainer.appendChild(button);
                }

                dialog.body.appendChild(contentContainer);
                dialog.show();
            } else {
                frappe.msgprint(__('No ' + type.toLowerCase() + ' links found.'));
            }
        }
    });
}