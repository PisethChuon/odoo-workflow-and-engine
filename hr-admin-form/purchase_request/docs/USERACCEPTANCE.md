# User Acceptance Testing

## 1. Project Information

| Field | Value |
| --- | --- |
| Project Name | Workflow |
| System Name | Purchase Request |
| Version | 1.0.0 |
| UAT Start Date | [Insert Date] |
| UAT End Date | [Insert Date] |
| Prepared By | Software Development Team |

## 2. Purpose

This UAT verifies that the Purchase Request process works as expected for business users and is ready for production use.

## 3. Test Scope

- Create and submit a purchase request
- Review, approve, reject, or rework a request
- Resubmit a request after rework
- Complete purchasing as Admin
- Cancel a request during rework
- Delegate approval to another user
- Track request progress and queue visibility
- Generate a printable request report

## 4. Test Notes

- Use business roles only: Employee, Manager or HoD, and Admin.
- Record the actual result after each test.
- Mark each test as Pass, Fail, or N/A.
- If a request is sent back for rework, update it and submit it again.
- Use realistic data (department, item, vendor, and cost) for testing.

<div style="page-break-after: always;"></div>

## 5. Test Scenarios

### 5.1 Request Submission

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-01 | Request submission | Create and submit a new purchase request | Employee | User can access Workflow and Purchase Request | 1. Open Workflow.<br>2. Go to Purchase Request.<br>3. Click New Request.<br>4. Enter required request, item, and vendor information.<br>5. Click Submit. | The request is created successfully and moves to Waiting Approval. The approver receives a notification. |  |  |
| UAT-02 | Request submission | Try to submit a request with missing required information | Employee | User is on a new request form | 1. Open a new request.<br>2. Leave one or more required fields empty.<br>3. Click Submit. | The system shows a clear message asking for missing information. The request is not submitted. |  |  |
| UAT-03 | Request submission | Save a request as draft and reopen it later | Employee | User can create a request | 1. Open a new request.<br>2. Enter partial information.<br>3. Save without submitting.<br>4. Reopen the same request. | The request remains in Draft and previously entered data is still available. |  |  |

<div style="page-break-after: always;"></div>

### 5.2 Review and Approval

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-04 | Approval review | Approve a request | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Request List.<br>3. Open the request.<br>4. Add a comment if needed.<br>5. Click Approve. | The request moves to the next workflow step and the requester receives a notification. |  |  |
| UAT-05 | Approval review | Reject a request with a reason | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Request List.<br>3. Open the request.<br>4. Add a reason in the comment field.<br>5. Click Reject. | The request status changes to Rejected and the requester receives a notification. |  |  |
| UAT-06 | Approval review | Send a request back for rework | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Request List.<br>3. Open the request.<br>4. Add a comment explaining what must be changed.<br>5. Click Rework. | The request status changes to Reworked and the requester receives a notification. |  |  |

### 5.3 Rework, Resubmission, and Cancellation

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-07 | Rework handling | Update a reworked request and submit it again | Employee | Request has been returned for rework | 1. Open the reworked request.<br>2. Review approver comment.<br>3. Update required information.<br>4. Submit again. | The request is resubmitted and returns to Waiting Approval. The approver receives a notification. |  |  |
| UAT-08 | Rework handling | Cancel a request instead of resubmitting | Employee | Request is in Reworked status | 1. Open the reworked request.<br>2. Click Cancel.<br>3. Confirm cancellation. | The request status changes to Cancelled and it is removed from active approval queues. |  |  |

<div style="page-break-after: always;"></div>

### 5.4 Purchase Completion and Tracking

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-09 | Purchase completion | Complete purchase details and finish request | Admin | The request is approved and assigned to Admin | 1. Open My Requests.<br>2. Open My Request List.<br>3. Open the approved request.<br>4. Enter purchase details.<br>5. Click Purchase. | The request moves to completed status and is no longer pending in admin queue. |  |  |
| UAT-10 | Purchase completion | Try to finish purchase with missing required details | Admin | Request is assigned to Admin | 1. Open the request.<br>2. Leave required purchase fields empty.<br>3. Click Purchase. | The system blocks completion and shows clear validation messages. |  |  |
| UAT-11 | Request tracking | Check workflow progress for a request | Any user with access | Request has moved through at least one step | 1. Open the request.<br>2. Select View Flow. | Workflow progress is displayed clearly, including current step. |  |  |
| UAT-12 | Request tracking | Confirm request appears in correct queue | Employee, Manager or HoD, Admin | Request is submitted or assigned | 1. Open the relevant queue.<br>2. Find the request in the list. | Request appears in the correct list for the current role and status. |  |  |

### 5.5 Delegation

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-13 | Delegation | Redirect approval to another person | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Request List.<br>3. Open the request.<br>4. Choose Redirected.<br>5. Select another user.<br>6. Confirm. | Request moves to selected approver and original approver no longer owns the task. |  |  |
| UAT-14 | Delegation | Share approval with another person | Manager or HoD | A request is waiting in My Approvals | 1. Open My Approvals.<br>2. Open My Request List.<br>3. Open the request.<br>4. Choose Share.<br>5. Select another user.<br>6. Confirm. | Both users can view and act on the request. Original approver keeps access. |  |  |

### 5.6 Reporting

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-15 | Report generation | Print Purchase Request report | Any user with report access | A Purchase Request record exists | 1. Open a Purchase Request record.<br>2. Click Print.<br>3. Select Purchase Request Form. | Report is generated successfully and values match the request record. |  |  |

## 6. Acceptance Criteria

The UAT is successful when all critical scenarios pass, no major business issue remains open, and business users confirm the process is ready for production.

<div style="page-break-after: always;"></div>

## 7. User Representative Information & Signature

| Field | Details |
| --- | --- |
| Full Name | ___________________________ |
| Position/Department | ___________________________ |
| Date Reviewed | ___________________________ |
| Signature | ___________________________ |

