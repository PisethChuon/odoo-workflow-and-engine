# User Acceptance Testing

## 1. Project Information

| Field | Value |
| --- | --- |
| Project Name | Workflow |
| System Name | Item Repair |
| Version | 1.0.0 |
| UAT Start Date | [Insert Date] |
| UAT End Date | [Insert Date] |
| Prepared By | Software Development Team |

## 2. Purpose

This UAT confirms that the Item Repair process works as expected for business users and is ready for production use.

## 3. Test Scope

- Configure item request types
- Create item repair requests with one or more item lines
- Review, approve, reject, or send a request back for rework
- Resubmit a request after rework
- Delegate an approval when needed
- Capture vendor and repair details and complete the repair
- Track request progress and print the request report

## 4. Test Notes

- Use business roles only: Employee, Manager or HoD, and Admin.
- Record the actual result after each test.
- Mark each test as Pass, Fail, or N/A.
- If a request is sent back for rework, update it and submit it again.
- Use clear test data so the request can be identified easily during review.

<div style="page-break-after: always;"></div>

## 5. Refactored UAT Structure

The test cases are grouped by the way business users actually work:

1. Configuration of item request types
2. Creation and submission of item repair requests
3. Approval review and delegation
4. Rework and resubmission
5. Repair completion with vendor details
6. Tracking and reporting

## 6. Test Cases

### 6.1 Configuration of Item Request Types

| Test Case ID | Title | Description | Preconditions | Steps | Expected Result |
| --- | --- | --- | --- | --- | --- |
| UAT-IR-01 | Create an item request type | Verify that an admin can add a new item request type for use in repair requests. | User has Admin access and can open Workflow > Configuration > Item Repair > Item Request Types. | 1. Open Item Request Types.<br>2. Click New.<br>3. Enter the item type name and description.<br>4. Save the record. | The new item request type is saved and appears in the list for future repair requests. |
| UAT-IR-02 | Prevent duplicate item request type names | Verify that the system does not allow two item request types with the same name. | An item request type with the same name already exists. | 1. Open Item Request Types.<br>2. Click New.<br>3. Enter a name that already exists.<br>4. Save the record. | The system shows a clear message and does not allow the duplicate item request type to be saved. |
| UAT-IR-03 | Archive and restore an item request type | Verify that an admin can hide an item request type and use it again later if needed. | An item request type already exists. | 1. Open the item request type.<br>2. Turn off the Active option and save.<br>3. Confirm the item type no longer appears in active selections.<br>4. Turn the Active option back on and save. | The item request type is hidden when inactive and becomes available again when reactivated. |

### 6.2 Create and Submit a Repair Request

| Test Case ID | Title | Description | Preconditions | Steps | Expected Result |
| --- | --- | --- | --- | --- | --- |
| UAT-IR-04 | Create a new item repair request | Verify that an employee can create a repair request with the required item details. | User has Employee access and can open Workflow > Item Repair. | 1. Click New Request.<br>2. Enter the request details.<br>3. Add one item line.<br>4. Select the item type.<br>5. Enter the serial number if available.<br>6. Add a short remark about the issue.<br>7. Save the request. | The request is created in Draft status and the item details are saved correctly. |
| UAT-IR-05 | Add more than one item to the same request | Verify that one repair request can include multiple items when business users need to send several items together. | User is creating or editing a draft repair request. | 1. Open a draft repair request.<br>2. Add a second item line.<br>3. Enter the item type, serial number, and remark for the second item.<br>4. Save the request. | Both item lines are saved under the same request and can be reviewed together. |
| UAT-IR-06 | Submit a complete repair request | Verify that a completed draft request can be submitted for approval. | A draft repair request is ready for submission. | 1. Open the draft request.<br>2. Review the item details.<br>3. Click Submit. | The request moves to Waiting Approval and the approver receives the request for review. |
| UAT-IR-07 | Reject submission with missing item type | Verify that the system stops submission when the item type is not selected. | User is on a draft repair request form. | 1. Open a draft request.<br>2. Leave the item type empty.<br>3. Click Submit. | The system shows a clear validation message and does not submit the request. |
| UAT-IR-08 | Auto-fill the department from the requester | Verify that the department is filled automatically from the request owner. | The requester has an employee record linked to a department. | 1. Create a new repair request for the user.<br>2. Add an item line.<br>3. Save the request. | The Charge to Department field is filled automatically based on the requester's department. |
| UAT-IR-09 | Save a request with and without a serial number | Verify that the serial number can be captured when available and left blank when not available. | User is creating a draft repair request. | 1. Create one item line with a serial number.<br>2. Create another item line without a serial number.<br>3. Save the request. | The request saves successfully in both cases, and the serial number is recorded only where provided. |

### 6.3 Review, Approval, and Delegation

| Test Case ID | Title | Description | Preconditions | Steps | Expected Result |
| --- | --- | --- | --- | --- | --- |
| UAT-IR-10 | Approve a repair request | Verify that a manager or HoD can approve a request waiting in the approval queue. | A request is in My Approvals > My Request List. | 1. Open My Approvals > My Request List.<br>2. Open the request.<br>3. Review the details.<br>4. Add a comment if needed.<br>5. Click Approve. | The request moves to the approved stage and the requester is informed of the decision. |
| UAT-IR-11 | Reject a repair request with a reason | Verify that a manager or HoD can reject a request and explain why. | A request is in My Approvals > My Request List. | 1. Open the request.<br>2. Enter a reason in the comment area.<br>3. Click Reject. | The request is rejected and the requester can see the rejection reason. |
| UAT-IR-12 | Send a repair request back for rework | Verify that a manager or HoD can return a request for changes. | A request is in My Approvals > My Request List. | 1. Open the request.<br>2. Enter a comment describing what must be changed.<br>3. Click Rework. | The request is returned to the requester with clear instructions for revision. |
| UAT-IR-13 | Redirect an approval to another person | Verify that an approver can hand the request to another person when needed. | A request is waiting in the approver's queue. | 1. Open the request.<br>2. Choose Redirected.<br>3. Select another user.<br>4. Confirm the action. | The request is moved to the selected user and removed from the original approver's queue. |
| UAT-IR-14 | Share an approval with another person | Verify that an approver can share the request with another person for joint handling. | A request is waiting in the approver's queue. | 1. Open the request.<br>2. Choose Share.<br>3. Select another user.<br>4. Confirm the action. | Both users can see and act on the request. The original approver still keeps access. |

### 6.4 Rework and Resubmission

| Test Case ID | Title | Description | Preconditions | Steps | Expected Result |
| --- | --- | --- | --- | --- | --- |
| UAT-IR-15 | Update and resubmit a reworked request | Verify that the requester can make changes after rework and send the request again. | The request was returned for rework. | 1. Open the reworked request.<br>2. Read the approver's comments.<br>3. Update the required item details.<br>4. Save the changes.<br>5. Click Submit again. | The request is resubmitted and returns to the approval queue. |

### 6.5 Repair Completion

| Test Case ID | Title | Description | Preconditions | Steps | Expected Result |
| --- | --- | --- | --- | --- | --- |
| UAT-IR-16 | Record vendor and repair details | Verify that an admin can capture vendor information and repair tracking details before completing the request. | The request has been approved and is ready for repair completion. | 1. Open the approved request from My Requests > My Request List.<br>2. Enter vendor name, contact number, email, address, and cost if available.<br>3. Enter the send date and receive date.<br>4. Add an admin remark if needed.<br>5. Save the request. | The vendor and repair details are saved on the request and can be reviewed later. |
| UAT-IR-17 | Complete the repair request | Verify that the admin can finish the request after the repair work is done. | The request has approved repair details and is ready to be closed. | 1. Open the request.<br>2. Confirm the repair details are complete.<br>3. Click Repair. | The request is marked as completed and the business process is finished. |

### 6.6 Tracking and Reporting

| Test Case ID | Title | Description | Preconditions | Steps | Expected Result |
| --- | --- | --- | --- | --- | --- |
| UAT-IR-18 | View workflow progress | Verify that a user can see where the request currently sits in the process. | The request has already moved through at least one step. | 1. Open the request.<br>2. Select View Flow. | The workflow progress is shown clearly, including the current step and history. |
| UAT-IR-19 | Confirm the request appears in the correct queue | Verify that each user sees the request in the correct list for their role and current status. | The request has been submitted or assigned to the relevant user. | 1. Open the relevant queue.<br>2. Search for the request.<br>3. Open the request if it appears. | The request appears in the correct queue for the current role and status. |
| UAT-IR-20 | Print the Item Repair Request report | Verify that users can generate the repair request report for business use or filing. | A repair request exists in the system. | 1. Open the request or the request list.<br>2. Select the print or report option.<br>3. Choose Item Repair Request or Item Repair Request Form. | The report opens or downloads successfully with the correct request information. |

## 7. Missing Scenarios Added

The following scenarios were added because they are important for real business use and were missing from the original UAT:

- Creating and maintaining item request types, including duplicate-name validation and archive/reactivate handling.
- Adding more than one item to a single repair request.
- Handling optional serial numbers without blocking submission.
- Auto-filling the department from the request owner so users do not enter it manually.
- Approval delegation through Redirected and Share.
- Capturing vendor, cost, send date, receive date, and admin remarks before closing the repair.
- Printing the Item Repair Request report for operational and audit use.
- Checking that the request appears in the correct queue at each stage.

## 8. Acceptance Criteria

The UAT is successful when all critical scenarios pass, no major business issue remains open, and the business users confirm the process is ready for production.

<div style="page-break-after: always;"></div>

## 9. User Representative Information & Signature

| Field | Details |
| --- | --- |
| Full Name | ___________________________ |
| Position/Department | ___________________________ |
| Date Reviewed | ___________________________ |
| Signature | ___________________________ |