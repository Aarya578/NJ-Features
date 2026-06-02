import frappe
import base64
import paramiko
import os
from io import BytesIO

@frappe.whitelist(allow_guest=True)
def upload_catalog(file_name, content):
    try:
        # Check if file_name and content are provided
        if not file_name:
            return {"status": "error", "message": "file_name is required"}

        if not content:
            return {"status": "error", "message": "content is required"}

        # Sanitize file name to avoid path injection issues
        safe_file_name = os.path.basename(file_name)

        # Decode base64 content
        file_content = base64.b64decode(content)

        # Upload to SFTP
        upload_to_sftp(safe_file_name, file_content)

        return {"status": "success", "file_name": safe_file_name}

    except Exception as e:
        # Log the error and return the error message
        frappe.log_error(frappe.get_traceback(), "Upload Catalog Error")
        return {"status": "error", "message": str(e)}


def upload_to_sftp(file_name, file_content):
    # Server credentials
    host = "ftp.newjaisa.org"
    port = 22
    username = "ubuntu"
    password = "Jaisa@321"  # Ideally, this should not be hardcoded

    # Remote directory and file path
    remote_dir = "/home/ubuntu/catalog"
    remote_path = f"{remote_dir}/{file_name}"

    transport = None
    sftp = None

    try:
        # Set up SFTP connection
        transport = paramiko.Transport((host, port))
        transport.connect(username=username, password=password)

        # Create SFTP client
        sftp = paramiko.SFTPClient.from_transport(transport)

        # Ensure the remote directory exists (optional)
        try:
            sftp.stat(remote_dir)
        except FileNotFoundError:
            sftp.mkdir(remote_dir)

        # Create a file object from the file content (in memory)
        file_obj = BytesIO(file_content)

        # Upload the file to the remote server
        sftp.putfo(file_obj, remote_path)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "SFTP Upload Error")
        raise e  # Reraise the exception for the caller to handle

    finally:
        # Close SFTP connection
        if sftp:
            sftp.close()

        # Close transport
        if transport:
            transport.close()