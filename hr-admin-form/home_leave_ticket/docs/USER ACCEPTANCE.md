# User Acceptance Testing

## 1. Project Information

| Field | Value |
| --- | --- |
| Project Name | Workflow |
| System Name | Home Leave Ticket |
| Version | 1.0.0 |
| UAT Start Date | [Insert Date] |
| UAT End Date | [Insert Date] |
| Prepared By | Software Development Team |

## 2. Purpose

This UAT verifies that the Home Leave Ticket process works as expected for business users and is ready for production use.

## 3. Test Scope

- Create a new home leave ticket request
- Review, approve, reject, or rework a request
- Resubmit a request after rework
- Complete an approved request
- Delegate an approval to another user
- Track request progress and status updates

## 4. Test Notes

- Use business roles only: Employee, Manager or HoD, and Admin.
- Record the actual result after each test.
- Mark each test as Pass, Fail, or N/A.
- If a request is sent back for rework, update it and submit it again.

<div style="page-break-after: always;"></div>

## 5. Test Scenarios

### 5.1 Request Submission

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-01 | Request submission | Create and submit a new home leave ticket request | Employee | User can access Workflow and Home Leave Ticket | 1. Open Workflow.<br>2. Go to Home Leave Ticket.<br>3. Click New Request.<br>4. Enter the required information.<br>5. Submit the request. | The request is created successfully and moves to Waiting Approval. The approver receives a notification. |  |  |
| UAT-02 | Request submission | Try to submit a request with missing required information | Employee | User is on the new request form | 1. Open a new request.<br>2. Leave one or more required fields empty.<br>3. Click Submit. | The system shows a clear message asking the user to complete the missing information. The request is not submitted. |  |  |

<div style="page-break-after: always;"></div>

### 5.2 Review and Approval

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-03 | Approval review | Approve a request | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Request List.<br>3. Open the request.<br>4. Add a comment if needed.<br>5. Click Approve. | The request status changes to Approved and the requester receives a notification. |  |  |
| UAT-04 | Approval review | Reject a request with a reason | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Request List.<br>3. Open the request.<br>4. Add a reason in the comment field.<br>5. Click Reject. | The request status changes to Rejected and the requester receives a notification with the reason. |  |  |
| UAT-05 | Approval review | Send a request back for rework | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Request List.<br>3. Open the request.<br>4. Add a comment explaining what must be changed.<br>5. Click Rework. | The request status changes to Reworked and the requester receives a notification. |  |  |

### 5.3 Rework and Resubmission

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-06 | Rework handling | Update a reworked request and submit it again | Employee | The request has been returned for rework | 1. Open the reworked request.<br>2. Review the comment from the approver.<br>3. Update the required information.<br>4. Submit the request again. | The request is resubmitted and returns to Waiting Approval. The approver receives a new notification. |  |  |

<div style="page-break-after: always;"></div>

### 5.4 Completion and Tracking

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-07 | Request completion | Complete an approved request | Admin | The request has already been approved | 1. Open My Requests.<br>2. Open My Request List.<br>3. Open the approved request.<br>4. Complete the task. | The request is completed according to business rules and remains available for tracking. |  |  |
| UAT-08 | Request tracking | Check the workflow progress for a request | Any user with access | The request has already moved through at least one step | 1. Open the request.<br>2. Select View Flow. | The workflow progress is displayed clearly so the user can see the current step and history. |  |  |
| UAT-09 | Request tracking | Confirm the request appears in the correct queue | Employee, Manager or HoD, Admin | The request has been submitted or assigned | 1. Open the relevant queue.<br>2. Find the request in the list. | The request appears in the correct list for the current role and status. |  |  |

<div style="page-break-after: always;"></div>

### 5.5 Delegation

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-10 | Delegation | Redirect approval to another person | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Request List.<br>3. Open the request.<br>4. Choose Redirected.<br>5. Select another user.<br>6. Confirm the action. | The request moves to the selected approver and the original approver no longer owns the task. |  |  |
| UAT-11 | Delegation | Share approval with another person | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Request List.<br>3. Open the request.<br>4. Choose Share.<br>5. Select another user.<br>6. Confirm the action. | Both users can view and act on the request. The original approver still keeps access. |  |  |

## 6. Acceptance Criteria

The UAT is successful when all critical scenarios pass, no major business issue remains open, and the business users confirm the process is ready for production.

<div style="page-break-after: always;"></div>

## 7. User Representative Information and Signature

| Field | Details |
| --- | --- |
| Full Name | ___________________________ |
| Position/Department | ___________________________ |
| Date Reviewed | ___________________________ |
| Signature | ___________________________ |
