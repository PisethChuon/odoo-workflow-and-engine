# User Acceptance Testing

## 1. Project Information

| Field | Value |
| --- | --- |
| Project Name | Workflow |
| System Name | Request Document |
| Version | 1.0.0 |
| UAT Start Date | [Insert Date] |
| UAT End Date | [Insert Date] |
| Prepared By | Software Development Team |

## 2. Purpose

This UAT verifies that the Request Document process works as expected for business users and is ready for production use.

## 3. Test Scope

- Create and submit a new request document
- Validate required data before submission
- Review, approve, reject, or rework a request
- Resubmit a request after rework
- Cancel a request when it is no longer needed
- Complete HR/Admin implementation and finalize the request
- Delegate an approval to another user
- Track request progress, queue visibility, and notifications
- Print the request document report

## 4. Test Notes

- Use business roles only: Employee, Manager or HoD, and Admin/HR.
- Record the actual result after each test.
- Mark each test as Pass, Fail, or N/A.
- If a request is sent back for rework, update it and submit it again.

<div style="page-break-after: always;"></div>

## 5. Test Scenarios

### 5.1 Request Submission

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-01 | Request submission | Create and submit a new request document | Employee | User can access Workflow and Request Document | 1. Open Workflow.<br>2. Go to Request Document.<br>3. Click New Request.<br>4. Enter required information.<br>5. Click Submit. | The request is created successfully and moves to Waiting Approval. The approver receives a notification. |  |  |
| UAT-02 | Request submission | Try to submit with missing required information | Employee | User is on the new request form | 1. Open a new request.<br>2. Leave one or more required fields empty.<br>3. Click Submit. | The system shows a clear message asking the user to complete missing information. The request is not submitted. |  |  |
| UAT-03 | Request submission | Verify only allowed document types are used | Employee | User is on the new request form | 1. Open Document Type.<br>2. Check available options.<br>3. Select a valid type and submit. | Only approved document types are available and the request can be submitted with a valid type. |  |  |

<div style="page-break-after: always;"></div>

### 5.2 Review and Approval

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-04 | Approval review | Approve a request | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Request List.<br>3. Open the request.<br>4. Add a comment if needed.<br>5. Click Approve. | The request status changes to Approved and the requester receives a notification. |  |  |
| UAT-05 | Approval review | Reject a request with a reason | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Request List.<br>3. Open the request.<br>4. Add a reason in the comment field.<br>5. Click Reject. | The request status changes to Rejected and the requester receives a notification with the reason. |  |  |
| UAT-06 | Approval review | Send a request back for rework | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Request List.<br>3. Open the request.<br>4. Add a comment explaining what must be changed.<br>5. Click Rework. | The request status changes to Reworked and the requester receives a notification. |  |  |

### 5.3 Rework and Resubmission

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-07 | Rework handling | Update a reworked request and submit it again | Employee | The request has been returned for rework | 1. Open the reworked request.<br>2. Review the comment from the approver.<br>3. Update required information.<br>4. Click Resubmit. | The request is resubmitted and returns to Waiting Approval. The approver receives a new notification. |  |  |
| UAT-08 | Rework handling | Cancel a reworked request | Employee | The request is in Reworked status | 1. Open the reworked request.<br>2. Click Cancel.<br>3. Confirm action if prompted. | The request changes to Cancelled and is removed from active workflow processing. |  |  |

<div style="page-break-after: always;"></div>

### 5.4 Implementation, Issuance, and Tracking

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-09 | Request implementation | Complete implementation for an approved request | Admin/HR | The request has already been approved | 1. Open My Requests.<br>2. Open My Request List.<br>3. Open the approved request.<br>4. Complete the task.<br>5. Click Done or Issue (based on action label). | The request is completed successfully and the requester is informed. |  |  |
| UAT-10 | Request implementation | Send request back for rework from implementation step | Admin/HR | The request is assigned for implementation | 1. Open implementation task.<br>2. Add comment for required correction.<br>3. Click Rework. | The request status changes to Reworked and returns to requester with clear action needed. |  |  |
| UAT-11 | Request implementation | Reject request from implementation step | Admin/HR | The request is assigned for implementation | 1. Open implementation task.<br>2. Add rejection reason.<br>3. Click Reject. | The request status changes to Rejected and requester receives rejection information. |  |  |
| UAT-12 | Request tracking | Check workflow progress for a request | Any user with access | The request has already moved through at least one step | 1. Open the request.<br>2. Select View Flow. | The workflow progress is displayed clearly so users can see current step and history. |  |  |
| UAT-13 | Request tracking | Confirm request appears in the correct queue | Employee, Manager or HoD, Admin/HR | The request has been submitted or assigned | 1. Open the relevant queue.<br>2. Find the request in the list. | The request appears in the correct list for the current role and status. |  |  |
| UAT-14 | Request notification | Verify notifications for key status changes | Employee, Manager or HoD, Admin/HR | Notifications are enabled | 1. Submit a request.<br>2. Approve, reject, or rework the request.<br>3. Resubmit a reworked request. | Correct users receive notifications for submit, approve, reject, rework, and resubmit actions. |  |  |
| UAT-15 | Data accuracy | Verify charge department auto-fills from requester | Employee | Requester has linked employee and department data | 1. Create a request.<br>2. Check Charge To Department field. | Department is auto-filled correctly from requester profile. |  |  |
| UAT-16 | Report output | Generate Request Document report | Employee or Admin/HR | Request exists and user has print access | 1. Open the request record.<br>2. Click Print.<br>3. Select Request Document report. | Report is generated successfully with correct request details. |  |  |

<div style="page-break-after: always;"></div>

### 5.5 Delegation

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-17 | Delegation | Redirect approval to another person | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Request List.<br>3. Open the request.<br>4. Choose Redirected.<br>5. Select another user.<br>6. Confirm action. | The request moves to the selected approver and the original approver no longer owns the task. |  |  |
| UAT-18 | Delegation | Share approval with another person | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Request List.<br>3. Open the request.<br>4. Choose Share.<br>5. Select another user.<br>6. Confirm action. | Both users can view and act on the request. The original approver keeps access. |  |  |

## 6. Acceptance Criteria

The UAT is successful when all critical scenarios pass, no major business issue remains open, and the business users confirm the process is ready for production.

<div style="page-break-after: always;"></div>

## 7. User Representative Information & Signature

| Field | Details |
| --- | --- |
| Full Name | ___________________________ |
| Position/Department | ___________________________ |
| Date Reviewed | ___________________________ |
| Signature | ___________________________ |
