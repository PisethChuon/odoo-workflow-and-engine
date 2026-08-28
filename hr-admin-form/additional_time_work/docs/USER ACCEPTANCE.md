# User Acceptance Testing

## 1. Project Information

| Field | Value |
| --- | --- |
| Project Name | Workflow |
| System Name | Additional Time Work |
| Version | 1.0.0 |
| UAT Start Date | [Insert Date] |
| UAT End Date | [Insert Date] |
| Prepared By | Software Development Team |

## 2. Purpose

This UAT verifies that the Additional Time Work process works as expected for business users and is ready for production use.

## 3. Test Scope

- Create and submit a new Additional Time Work request
- Validate required fields during submission
- Review, approve, reject, or rework a request
- Resubmit or cancel a request after rework
- Complete HR review and close the request
- Delegate an approval to another user (Redirect and Share)
- Track request progress and status updates
- Generate request report output
- Verify notifications for key workflow actions

## 4. Test Notes

- Use business roles only: Employee, Manager or HoD, and HR Team.
- Record the actual result after each test.
- Mark each test as Pass, Fail, or N/A.
- If a request is sent back for rework, update it and submit it again.

<div style="page-break-after: always;"></div>

## 5. Test Scenarios

### 5.1 Request Submission

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-01 | Request submission | Create and submit a new Additional Time Work request | Employee | User can access Workflow and Additional Time Work | 1. Open Workflow.<br>2. Go to Additional Time Work.<br>3. Click New Request.<br>4. Add at least one line with Employee, Date, Work On category, and Hour.<br>5. Add a remark.<br>6. Submit the request. | The request is created successfully and moves to Waiting Approval. The approver receives a notification. |  |  |
| UAT-02 | Request submission | Try to submit a request with missing required information | Employee | User is on the new request form | 1. Open a new request.<br>2. Leave one or more required fields empty in the line details.<br>3. Click Submit. | The system shows a clear message asking the user to complete the missing information. The request is not submitted. |  |  |
| UAT-03 | Request submission | Submit one request with multiple line items | Employee | User can create a new request | 1. Open a new request.<br>2. Add multiple lines with valid data.<br>3. Click Submit. | The request is submitted with all line items saved correctly. |  |  |

<div style="page-break-after: always;"></div>

### 5.2 Review and Approval

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-04 | Approval review | Approve a request | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Contribute List.<br>3. Open the request.<br>4. Add a comment if needed.<br>5. Click Approve. | The request status changes to Approved and the requester receives a notification. |  |  |
| UAT-05 | Approval review | Reject a request with a reason | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Contribute List.<br>3. Open the request.<br>4. Add a reason in the comment field.<br>5. Click Reject. | The request status changes to Rejected and the requester receives a notification with the reason. |  |  |
| UAT-06 | Approval review | Send a request back for rework | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Contribute List.<br>3. Open the request.<br>4. Add a comment explaining what must be changed.<br>5. Click Rework. | The request status changes to Reworked and the requester receives a notification. |  |  |

### 5.3 Rework and Resubmission

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-07 | Rework handling | Update a reworked request and submit it again | Employee | The request has been returned for rework | 1. Open the reworked request.<br>2. Review the comment from the approver.<br>3. Update the required information.<br>4. Submit the request again. | The request is resubmitted and returns to Waiting Approval. The approver receives a new notification. |  |  |
| UAT-08 | Rework handling | Cancel a request during rework | Employee | The request has been returned for rework | 1. Open the reworked request.<br>2. Click Cancel.<br>3. Confirm the action. | The request status changes to Cancelled and no longer appears in active approval queues. |  |  |

<div style="page-break-after: always;"></div>

### 5.4 HR Review and Closure

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-09 | HR review | Close an approved request | HR Team | The request has already been approved and is assigned to HR review | 1. Open My Requests.<br>2. Open My Contribute List.<br>3. Open the approved request.<br>4. Review the details.<br>5. Click Close. | The request status changes to Closed and the workflow is completed. |  |  |
| UAT-10 | HR review | Send an approved request back for rework | HR Team | The request is in HR review | 1. Open My Requests.<br>2. Open My Contribute List.<br>3. Open the approved request.<br>4. Add a rework comment.<br>5. Click Rework. | The request is returned to the requester for correction with the HR comment. |  |  |

### 5.5 Tracking and Reporting

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-11 | Request tracking | Check the workflow progress for a request | Any user with access | The request has already moved through at least one step | 1. Open the request.<br>2. Select View Flow. | The workflow progress is displayed clearly so the user can see the current step and history. |  |  |
| UAT-12 | Request tracking | Confirm the request appears in the correct queue | Employee, Manager or HoD, HR Team | The request has been submitted or assigned | 1. Open the relevant queue.<br>2. Find the request in the list. | The request appears in the correct list for the current role and status. |  |  |
| UAT-13 | Reporting | Generate Additional Time Work request report | Employee, Manager or HoD, HR Team | At least one request exists | 1. Go to Workflow > Additional Time Work.<br>2. Click the gear icon (top-right corner).<br>3. Click Additional Time Work Request Report. | The report is generated successfully and displays the expected request data. |  |  |
| UAT-14 | Notifications | Verify notifications for key actions | Employee, Manager or HoD, HR Team | Users and inbox notifications are active | 1. Submit a new request.<br>2. Approve one request.<br>3. Rework one request.<br>4. Reject one request. | Notifications are sent to the correct users for submission, approval, rework, and rejection events. |  |  |

<div style="page-break-after: always;"></div>

### 5.6 Delegation

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-15 | Delegation | Redirect approval to another person | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Contribute List.<br>3. Open the request.<br>4. Choose Redirect.<br>5. Select another user.<br>6. Confirm the action. | The request moves to the selected approver and the original approver no longer owns the task. |  |  |
| UAT-16 | Delegation | Share approval with another person | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Contribute List.<br>3. Open the request.<br>4. Choose Share.<br>5. Select another user.<br>6. Confirm the action. | Both users can view and act on the request. The original approver still keeps access. |  |  |

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
