# External QC Process (NJQCA)

This document explains the workflow and technical implementation of the **External Quality Control (QC)** process within the `NJQCA` (NewJaisa Quality Control Analysis) module.

## Overview

The External QC process is used to perform quality inspections on items that are not yet part of the internal inventory. These items are typically being sourced from external vendors and are tracked using a **Request for Quotation (RFQ)**.

## Workflow

### 1. Prerequisite: Request for Quotation (RFQ)
The process starts with an existing RFQ in the system. The RFQ contains the list of items being considered for purchase from an external vendor.

### 2. Creating an NJQCA Record
When a technician performs an inspection for an external item:
- They create a new `NJQCA` document.
- They select the relevant **RFQ ID** in the `rfq_id` field.
- **Filtering**: Selecting an RFQ automatically filters the `item_code` field to show only the items linked to that specific RFQ.

### 3. Automated Serial Number Generation
If the external item does not yet have a serial number:
- Upon saving (`validate` event), the system checks if `rfq_id` is present and `serial_no` is empty.
- It triggers the `create_serial_no` API with the `rfq` flag set to `True`.
- **Prefix Logic**:
    - Standard serial numbers use the `NJ-` prefix.
    - External serial numbers use the **`EXT-`** prefix.
    - Example: `EXT-LP-123456` (where `LP` is the Item Group prefix).

### 4. Serial No Document Linking
The system doesn't just generate a string; it creates a formal `Serial No` record in the database.
- The `create_serial_no_based_on_rfq` function handles this.
- The generated serial number is saved as a new `Serial No` document.
- The `rfq_id` is stored on the `Serial No` document to maintain traceability back to the vendor quote.

## Technical Components

### Frontend (Javascript)
- **File**: `njqca.js`
- **Logic**:
    - `rfq_id`: Filters items based on the selected RFQ.
    - `validate`: Triggers serial number generation if `rfq_id` is present.

### Backend (Python)
- **File**: `njqca.py`
    - `get_item_code_from_rfq_id`: Fetches items for a given RFQ.
    - `create_serial_no_based_on_rfq`: Creates the `Serial No` record and links it to the RFQ.
- **File**: `qr_code.py`
    - `create_serial_no`: Handles the logic for the `EXT-` prefix and random number generation.

## Purpose and Benefits
- **Quality Verification**: Allows inspection of items before they are officially purchased.
- **Traceability**: Links QC results directly to vendor quotes (RFQs).
- **Inventory Readiness**: Ensures serial numbers are ready and quality is verified before the items hit the main warehouse.
