
# User Acceptance Testing

## 1. Project Information

| Field | Value |
| --- | --- |
| Project Name | Workflow |
| System Name | User Access |
| Version | 1.0.0 |
| UAT Start Date | [Insert Date] |
| UAT End Date | [Insert Date] |
| Prepared By | Software Development Team |

## 2. Purpose

This UAT verifies that the User Access workflow works as expected for business users and is ready for production use.

## 3. Test Scope

- Create and submit user access requests
- Add multiple access lines to a request
- Review, approve, reject, or send requests back for rework
- Resubmit a reworked request
- Complete (implement) an approved request and close it
- Delegate approvals (redirect and share)
- Notifications, flow tracking and reporting
- Configuration of Items and Types
- Permissions and attachments
- Edge cases and concurrent approval handling

## 4. Test Notes

- Use business roles only: Employee, HOD/Manager, HR Review, HR Approval, HR Implementation, Admin.
- Record the actual result after each test.
- Mark each test as Pass, Fail, or N/A.
- Capture screenshots for failures or unclear behaviour.
- If a request is sent back for rework, update it and submit it again.

<div style="page-break-after: always;"></div>

## 5. Test Scenarios

### 5.1 Request Submission

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-01 | Request submission | Create and submit a new user access request | Employee | User can access Workflow and User Access | 1. Open Workflow.<br>2. Go to User Access.<br>3. Click New Request.<br>4. Enter the required information (requester, employee, reason).<br>5. Add an access line and Submit. | The request is created successfully and moves to HOD Approval (or configured next stage). Approver receives a notification. |  |  |
| UAT-02 | Request submission | Submit request with multiple access lines | Employee | Same as UAT-01 | 1. Create new request.<br>2. Add 2–3 access lines with different items/types.<br>3. Submit the request. | All lines are saved and visible in the request; status is Submission. |  |  |
| UAT-03 | Validation | Prevent submission with missing required fields | Employee | User on New Request form | 1. Leave one or more required fields blank.<br>2. Click Submit. | System prevents submission and shows clear messages highlighting the missing fields. |  |  |

<div style="page-break-after: always;"></div>

### 5.2 Review and Approval

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-04 | Approval review | HOD approves a request | HOD/Manager | Request waiting in My Approvals | 1. Open My Approvals.<br>2. Open the request.<br>3. Review details and attachments.<br>4. Click Approve. | Request advances to HR Review (or next configured stage). Notification recorded. |  |  |
| UAT-05 | Approval review | HOD rejects a request with reason | HOD/Manager | Request waiting in My Approvals | 1. Open request.<br>2. Add rejection reason.<br>3. Click Reject. | Request status becomes Rejected and requester receives notification with reason. |  |  |
| UAT-06 | Approval review | HOD sends request back for rework | HOD/Manager | Request waiting in My Approvals | 1. Open request.<br>2. Add rework comment.<br>3. Click Rework. | Request status becomes Reworked and requester is notified with the comment. |  |  |

<div style="page-break-after: always;"></div>

### 5.3 Rework and Resubmission

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-07 | Rework handling | Update reworked request and resubmit | Employee | Request is in Reworked status with approver comments | 1. Open reworked request.<br>2. Review approver comments.<br>3. Make required changes.<br>4. Submit request. | Request returns to the appropriate approval queue and a new notification is sent to approver(s). |  |  |

<div style="page-break-after: always;"></div>

### 5.4 HR Implementation and Closure

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-08 | Implementation | HR implements access and closes request | HR Implementation / Admin | Request is in HR Implementation stage | 1. Open My Requests.<br>2. Open the approved request.<br>3. Perform implementation tasks.<br>4. Mark task complete and Close request. | Request status becomes Closed and requester + approvers receive completion notifications. |  |  |

<div style="page-break-after: always;"></div>

### 5.5 Delegation

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-09 | Delegation | Redirect approval to another person | HOD/Manager | Request waiting in My Approvals | 1. Open request.<br>2. Choose Redirected.<br>3. Select another user and Confirm. | Request moves to selected approver; original approver no longer owns the task. |  |  |
| UAT-10 | Delegation | Share approval with another person | HOD/Manager | Request waiting in My Approvals | 1. Open request.<br>2. Choose Share.<br>3. Select another user and Confirm. | Both users can view and act on the request. Original approver retains access. |  |  |

<div style="page-break-after: always;"></div>

### 5.6 Notifications, Tracking and Reporting

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-11 | Notifications | Notifications and View Flow | Any user | Request moves between stages | 1. Move a request through stages (Submission → HOD → HR Review).<br>2. Check notifications for requester and approvers.<br>3. Open request and click View Flow. | Notifications are delivered; View Flow shows current step and history with timestamps. |  |  |
| UAT-12 | Tracking | Request appears in correct queues | Employee / HOD / HR / Admin | Request has been submitted or assigned | 1. Open relevant queue.<br>2. Find the request. | Request appears in the appropriate list for the role and status. |  |  |

<div style="page-break-after: always;"></div>

### 5.7 Configuration and Permissions

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-13 | Configuration | Add Item/Type in configuration | Admin | User has configuration privileges | 1. Go to Workflow → Configuration → User Access.<br>2. Click New under Items or Types.<br>3. Fill fields and Save. | New record appears in selection lists when creating requests. |  |  |
| UAT-14 | Permissions | Block unauthorized request creation | Restricted user | Test user lacks create permission | 1. Log in as restricted user.<br>2. Attempt to create New Request. | New Request option is not available or access denied message appears. |  |  |

<div style="page-break-after: always;"></div>

### 5.8 Attachments, Concurrency and Edge Cases

| Scenario ID | Business Flow | Test Scenario | Role | Preconditions | Steps | Expected Result | Actual Result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UAT-15 | Attachments | Add and view attachment | Employee / Approver | Requester can attach files | 1. Attach a document when creating a request.<br>2. Submit and have approver open the attachment. | Attachment uploads and opens for approver. |  |  |
| UAT-16 | Concurrency | Concurrent approvals conflict handling | Approvers A & B | Request assigned to multiple approvers | 1. Approver A loads request.<br>2. Approver B approves.<br>3. Approver A then attempts to approve. | System reflects updated status to Approver A and prevents duplicate conflicting actions; user sees informative message. |  |  |
| UAT-17 | Cancellation | Requester cancels a request before approval | Employee | Request is still in Submission or early approval stage | 1. Open own request.<br>2. Choose Cancel (if supported).<br>3. Confirm. | Request becomes Cancelled (or Closed) and notifications are sent to stakeholders. |  |  |
| UAT-18 | Audit | Audit trail and history verification | Auditor / Admin | Request has activity history | 1. Open request.<br>2. Review history and timestamps. | All actions are recorded with user, timestamp and comments for compliance. |  |  |

## 6. Acceptance Criteria

UAT is successful when all critical scenarios pass, no major business issue remains open, and business users confirm the process is ready for production.

<div style="page-break-after: always;"></div>

## 7. User Representative Information & Signature

| Field | Details |
| --- | --- |
| Full Name | ___________________________ |
| Position/Department | ___________________________ |
| Date Reviewed | ___________________________ |
| Signature | ___________________________ |


