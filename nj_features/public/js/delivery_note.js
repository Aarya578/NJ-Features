frappe.ui.form.on('Delivery Note', {
   
    refresh: function(frm) {
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
        } else {
            frm.remove_custom_button(__('Print QR Code'));
        }
        console.log("inside delivery note=============================");
        
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


frappe.ui.form.on('Delivery Note', {
    refresh: function(frm) {
        // Add 'Record' button for new documents (docstatus = 0)
        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__('Record'), function() {
                // Trigger the URL opening when 'Record' button is clicked
                openDjangoUrl(frm.doc.doctype,frm.doc.name);  // Pass DN number to the function
            }).addClass('btn-warning');
        }
    }
});

// Function to open the Django URL directly with the DN number
function openDjangoUrl(doctype,dn_number) {
    // Construct the URL by embedding the dn_number in it
    // let url = `https://njpulse.newjaisa.com/upload/${dn_number}/`;
    frappe.db.get_value("NJ Settings",{"parameter":"video_prefix"},"value").then((prefix)=>{

        console.log("prefix------183",prefix.message.value)
        let url = `${prefix.message.value}${doctype}/${dn_number}/`;
        
        // Open the URL in a new tab
        window.open(url, '_blank');
    })
}

