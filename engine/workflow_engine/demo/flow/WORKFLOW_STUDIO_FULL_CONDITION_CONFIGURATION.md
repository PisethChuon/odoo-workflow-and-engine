# Workflow Studio Full Condition Configuration (BCJ + Exit Clearance)

This document is the full configuration guide for all condition logic in Workflow Studio for:

- `bcj_full_aligned.bpmn`
- `exit_clearance_full_aligned.bpmn`

For the complete 71-flow package index and baseline setup guide, see:
- `ALL_FLOWS_BPMN_INDEX.csv`
- `ALL_FLOWS_MASTER_CONFIGURATION_GUIDE.md`

## 1. Where Conditions Are Configured In Studio

Use these locations for each condition type:

1. Sequence route condition (gateway branch):
   - Diagram -> select the sequence line -> action record -> `Domain`
2. Approver group apply condition:
   - Task -> `User Groups` tab -> row field `Domain`
3. Approver user filter condition:
   - Task -> `User Groups` tab -> row field `User Domain`
4. Action button visibility condition:
   - Task -> `Actions` tab -> action row -> `Invisible Domain`
5. Conditional 2FA:
   - Task -> `Actions` tab -> action row -> `Require 2FA` + `2FA Condition Domain`
6. Assignment and fallback behavior:
   - Task -> `Runtime` tab -> `Assignment Mode`, `Completion Mode`, `Fallback Policy`, join settings

## 2. Data Fields Required On Request Model

Minimum fields used by BPMN conditions:

1. `total_amount` (Float/Monetary)
2. `branch_company` (Selection: `gaming`, `hotel`, `others`)
3. `allow_modification` (Boolean)
4. `request_owner_emp_type` (Selection, includes `employee`)

If any field is missing, the condition branch cannot evaluate correctly.

## 3. BCJ Full Condition Configuration

## 3.1 BCJ Route Conditions (Exact Domain Values)

Configure these in the action `Domain` field:

| Flow ID | Source -> Target | Domain |
|---|---|---|
| `Flow_22` | `Gateway_FinanceRoute -> Task_FinanceGaming` | `[('total_amount', '<=', 500), ('branch_company', '=', 'gaming')]` |
| `Flow_23` | `Gateway_FinanceRoute -> Task_FinanceHotel` | `[('total_amount', '<=', 500), ('branch_company', '=', 'hotel')]` |
| `Flow_24` | `Gateway_FinanceRoute -> Task_GroupFinance` | `[('total_amount', '<=', 500), ('branch_company', '=', 'others')]` |
| `Flow_25` | `Gateway_FinanceRoute -> Task_CFO_DYCFO` | `[('total_amount', '>', 500), ('total_amount', '<=', 100000)]` |
| `Flow_26` | `Gateway_FinanceRoute -> Task_CFO` | `[('total_amount', '>', 100000)]` |
| `Flow_51` | `Gateway_ModificationWindow -> Task_Modification` | `[('allow_modification', '=', True)]` |

Default path (no condition):

- `Flow_50`: `Gateway_ModificationWindow -> EndEvent_Completed`
- Meaning: when `allow_modification` is false/missing, complete directly.

## 3.2 BCJ Action Routing Per Human Stage

Configure action rows under each source task as below:

| Stage | Action Key | Source -> Target |
|---|---|---|
| `Task_Submitter` | `submit` | `Task_Submitter -> Event_Submit` (`Flow_02`) |
| `Task_HODApproval` | `approve` | `Task_HODApproval -> Event_HODApproved` (`Flow_04`) |
| `Task_HODApproval` | `rework` | `Task_HODApproval -> Event_HODReworked` (`Flow_06`) |
| `Task_HODApproval` | `reject` | `Task_HODApproval -> Event_HODRejected` (`Flow_08`) |
| `Task_LineDepartment` | `review` | `Task_LineDepartment -> Event_LineReviewed` (`Flow_10`) |
| `Task_LineDepartment` | `rework` | `Task_LineDepartment -> Event_LineReworked` (`Flow_12`) |
| `Task_LineDepartment` | `reject` | `Task_LineDepartment -> Event_LineRejected` (`Flow_14`) |
| `Task_DepartmentExecutive` | `review` | `Task_DepartmentExecutive -> Event_DeptExecReviewed` (`Flow_16`) |
| `Task_DepartmentExecutive` | `rework` | `Task_DepartmentExecutive -> Event_DeptExecReworked` (`Flow_18`) |
| `Task_DepartmentExecutive` | `reject` | `Task_DepartmentExecutive -> Event_DeptExecRejected` (`Flow_20`) |
| Finance tasks (`Task_FinanceGaming/Hotel/GroupFinance/CFO_DYCFO/CFO`) | `review` | Task -> `Event_FinanceReviewed` (`Flow_27`..`Flow_31`) |
| Finance tasks | `rework` | Task -> `Event_FinanceReworked` (`Flow_33`..`Flow_37`) |
| Finance tasks | `reject` | Task -> `Event_FinanceRejected` (`Flow_39`..`Flow_43`) |
| `Task_Purchasing` | `done` | `Task_Purchasing -> Event_PurchaseDone` (`Flow_48`) |
| `Task_Modification` | `save` | `Task_Modification -> Event_ModificationSaved` (`Flow_52`) |

Expected backward loops:

1. HOD rework -> Submitter (`Flow_07`)
2. Line Dept rework -> HOD (`Flow_13`)
3. Dept Exec rework -> Line Dept (`Flow_19`)
4. Finance rework -> Dept Exec (`Flow_38`)

## 3.3 BCJ Task Runtime Tab (Demo Baseline)

Recommended runtime values:

| Node ID | Assignment Mode | Completion Mode | Fallback Policy | Confidentiality |
|---|---|---|---|---|
| `Task_Submitter` | `request_owner` | `any` | `block` | `public` |
| `Task_HODApproval` | `groups` | `any` | `route_admin_queue` | `department` |
| `Task_LineDepartment` | `groups` | `any` | `route_admin_queue` | `department` |
| `Task_DepartmentExecutive` | `groups` | `any` | `route_admin_queue` | `restricted` |
| `Task_FinanceGaming` | `groups` | `any` | `route_admin_queue` | `restricted` |
| `Task_FinanceHotel` | `groups` | `any` | `route_admin_queue` | `restricted` |
| `Task_GroupFinance` | `groups` | `any` | `route_admin_queue` | `restricted` |
| `Task_CFO_DYCFO` | `groups` | `any` | `route_admin_queue` | `restricted` |
| `Task_CFO` | `groups` | `any` | `route_admin_queue` | `restricted` |
| `Task_Purchasing` | `groups` | `any` | `route_admin_queue` | `restricted` |
| `Task_Modification` | `groups` | `any` | `route_admin_queue` | `restricted` |

## 3.4 BCJ Approval Groups and Conditional Mapping

Use these source files:

1. `bcj_group_users.csv` for fixed groups:
   - Finance - Gaming
   - Finance - Hotel
   - Group Finance
   - CFO/DYCFO
   - CFO
   - Purchasing
   - Modification
2. `bcj_hod_mapping.csv` for requestor department -> HOD mapping
3. `bcj_line_dept_exec_mapping.csv` for list type -> line department + department executive mapping

In `User Groups` tab:

1. `Task_HODApproval`: link HOD mapping group(s)
2. `Task_LineDepartment`: link line department mapping group(s)
3. `Task_DepartmentExecutive`: link department executive mapping group(s)
4. Finance/Purchasing/Modification: link fixed groups from `bcj_group_users.csv`

## 4. Exit Clearance Full Condition Configuration

## 4.1 Exit Route Conditions (Exact Domain Values)

| Flow ID | Source -> Target | Domain |
|---|---|---|
| `Flow_43` | `Gateway_OffboardRoute -> Task_DisableAccounts` | `[('request_owner_emp_type', '=', 'employee')]` |
| `Flow_44` | `Gateway_OffboardRoute -> Task_NotifyChannels` | `[('id', '!=', 0)]` |

`Flow_44` is the always-true branch to keep notifications always active.

## 4.2 Exit Rework/Reject Conditions

Configure these exact paths:

1. HOD reject: `Task_HODDecision -> Event_HODReject` (`Flow_06`) -> `Task_RequestorRework` (`Flow_07`)
2. Requestor resubmit: `Task_RequestorRework -> Event_Resubmit` (`Flow_08`) -> `Task_HODDecision` (`Flow_09`)
3. IT reject: `Task_ITClearance -> Event_ITReject` (`Flow_20`) -> `Task_RequestorRework` (`Flow_21`)
4. Finance reject: `Task_FinanceClearance -> Event_FinanceReject` (`Flow_24`) -> `Task_RequestorRework` (`Flow_25`)

## 4.3 Exit Task Runtime Tab (Exact Demo Values)

From demo configuration:

| Node ID | Assignment Mode | Completion Mode | Fallback | Confidentiality | Extra |
|---|---|---|---|---|---|
| `Task_Submission` | `request_owner` | `any` | `block` | `public` | - |
| `Task_RequestorRework` | `request_owner` | `any` | `block` | `public` | - |
| `Task_HODDecision` | `groups` | `all` | `route_admin_queue` | `department` | `requires_department_payload=True` |
| Department branch tasks (`Task_ITClearance`, `Task_FinanceClearance`, `Task_AdminClearance`, `Task_SecurityClearance`, `Task_FacilityClearance`, `Task_PurchaseClearance`, `Task_OperationsClearance`, `Task_HRDeptClearance`) | `groups` | `all` | `route_admin_queue` | `department` | `requires_department_payload=True`, `join_key=exit_clearance_departments`, `gateway_node_id=Gateway_DeptJoin`, `join_policy=all_of`, `parallel_reject_policy=strict` |
| `Task_HODFinalReview` | `groups` | `all` | `route_admin_queue` | `restricted` | - |
| `Task_PayrollReview` | `groups` | `all` | `route_admin_queue` | `restricted` | - |
| `Task_HRFinalClearance` | `groups` | `all` | `route_admin_queue` | `restricted` | `requires_department_payload=True` |
| `Task_DisableAccounts` | system task | - | `route_admin_queue` | `restricted` | `activity_type_ids=server_action` |
| `Task_NotifyChannels` | system task | - | default | default | recipients + notification actions configured |

## 4.4 Exit Approval Group Conditions (Exact Demo)

Configure `User Groups` rows with:

1. `user_domain`: `[('active', '=', True)]` for all rows
2. `domain`:
   - IT stage only: `[('request_owner_emp_type', '=', 'employee')]`
   - others: `[]`

Group mapping:

1. `Task_HODDecision` -> `Exit Clearance - HOD`
2. `Task_ITClearance` -> `Exit Clearance - IT`
3. `Task_FinanceClearance` -> `Exit Clearance - Finance`
4. `Task_AdminClearance` -> `Exit Clearance - Admin`
5. `Task_SecurityClearance` -> `Exit Clearance - Security`
6. `Task_FacilityClearance` -> `Exit Clearance - Facility`
7. `Task_PurchaseClearance` -> `Exit Clearance - Purchase`
8. `Task_OperationsClearance` -> `Exit Clearance - Operations`
9. `Task_HRDeptClearance` -> `Exit Clearance - HR`
10. `Task_HODFinalReview` -> `Exit Clearance - HOD`
11. `Task_PayrollReview` -> `Exit Clearance - Payroll`
12. `Task_HRFinalClearance` -> `Exit Clearance - HR`

## 4.5 Exit Action Security Conditions (Exact Demo)

Configure these action rows:

1. `Task_Submission -> Event_Submit`:
   - `name=submit`
   - `dialog_type=confirm`
   - `invisible_domain=[('wf_actor_uid', '=', request_owner_id)]`
2. `Task_RequestorRework -> Event_Resubmit`:
   - `name=resubmit`
   - `dialog_type=confirm`
   - `invisible_domain=[('wf_actor_uid', '=', request_owner_id)]`
3. `Task_HODDecision -> Event_HODApprove`:
   - `name=hod_approve`
   - `dialog_type=confirm`
   - `comment_required=True`
   - `invisible_domain=[('wf_actor_is_hod', '=', True)]`
4. `Task_HODDecision -> Event_HODReject`:
   - `name=hod_reject`
   - `dialog_type=reject`
   - `require_reason=True`
   - `comment_required=True`
   - `invisible_domain=[('wf_actor_is_hod', '=', True)]`
5. `Task_PayrollReview -> Event_PayrollApprove`:
   - `name=payroll_approve`
   - `dialog_type=confirm`
   - `comment_required=True`
   - `require_2fa=True`
   - `twofa_method=email_otp`
   - `twofa_condition_domain=[('request_owner_emp_type', '=', 'employee')]`
6. `Task_HRFinalClearance -> Event_HRFinalDone`:
   - `name=hr_complete`
   - `dialog_type=proceed`
   - `comment_required=True`

## 5. End-To-End Studio Steps

1. Quick Start modal:
   - Create new model, or
   - Select existing model where `has_approve = true`
2. Import BPMN (`bcj_full_aligned.bpmn` or `exit_clearance_full_aligned.bpmn`)
3. Click `Sync`
4. Open each human task and configure `Runtime` tab values
5. Configure `User Groups` tab rows (`approval_group_id`, `user_domain`, `domain`)
6. Open `Actions` tab and configure each action key, label, dialog, reason/2FA conditions
7. Configure sequence route conditions in action `Domain` for gateway branches
8. Save -> Deploy
9. Run tests for approve/rework/reject for every stage

## 6. Test Cases (Must Pass)

1. BCJ approve happy path reaches `EndEvent_Completed`
2. BCJ finance routing picks exactly one finance branch by amount/company
3. BCJ each rework returns to expected previous stage
4. Exit any IT/Finance reject returns to `Task_RequestorRework`
5. Exit department parallel join waits for all branches (`join_policy=all_of`)
6. Exit payroll action enforces 2FA only when condition matches

## 7. Runtime Assignment vs Approval Groups (How They Work Together)

In current engine behavior, these are related but not the same pipeline:

1. Runtime Assignment (`Runtime` tab on task):
   - Computes candidates from `assignment_mode` (`mixed`, `explicit_users`, `groups`, `domain`, `previous_actor`, `request_owner`)
   - Applies delegation, access eligibility, and fallback policy
   - Stores result in runtime models (`workflow.request.task.instance`, `workflow.request.task.assignee`)
2. Approval Groups (`User Groups` tab on task):
   - Creates actionable approver rows (`workflow.approval.approver`) during transitions
   - Uses group row `domain` (request-level filter) and `user_domain` (group-user filter)
   - Drives visible approver actions and current pending approver state in request UI

Important:

1. Transition buttons, pending approver summary, and blocked badge currently depend on `workflow.approval.approver` rows.
2. Runtime assignment rows alone do not make buttons actionable if no approver rows exist for the current stage.
3. For this reason, stage configuration must keep `Runtime Assignment` and `User Groups` aligned.

## 8. Why Your Domain Can Still Lead To Blocked Stage

Your runtime domain:

- `[('share', '=', False), ('active', '=', True)]`

is syntactically valid for runtime assignment. But blocked can still happen because:

1. This domain is evaluated in Runtime Assignment service, not in legacy approver-row creation path by itself.
2. If next stage has no matching `User Groups` assignment (or group/user domain filters remove everyone), no new `workflow.approval.approver` rows are created.
3. Request then shows:
   - `Workflow is blocked at stage <stage> — no pending approver is assigned.`
4. Even when a user matches domain, final eligibility filters can still remove them:
   - missing workflow user group
   - no category access in zero-trust policy
   - no read access to target record
   - company mismatch

## 9. Recommended Configuration Pattern (Current Engine)

For production-safe behavior now:

1. Use `User Groups` as primary assignment source for actionable user tasks.
2. Use row `user_domain` for filtering users dynamically (for example active/non-share or request-based symbols).
3. Keep `Runtime Assignment` configured to the same intent for runtime audit/diagnostic consistency.
4. Keep `Fallback Policy` as `route_admin_queue` and set `admin_queue_user_id` on category.
5. Ensure every human stage has at least one effective approver row after filters.

If you want domain-driven assignment behavior at a stage, do this:

1. Keep at least one Approval Group link on that stage.
2. Put dynamic filtering logic in the group row `user_domain`.
3. Optionally keep the same expression in `assignment_user_domain` for runtime parity.

## 10. Engine Verification Snapshot (2026-03-07)

Runtime assignment mode behavior was validated by running:

```bash
python odoo-core-19/odoo-bin -c config/naga-odoo-19.conf -d wf_runtime_check_20260307 -i workflow_engine --test-enable --test-tags=/workflow_engine/tests/test_runtime_services.py --stop-after-init --log-level=test --http-port=8170 --without-demo=True
```

Key output:

1. All runtime-service tests executed for assignment modes (`Mixed`, `Explicit Users`, `Groups`, `Domain`, `Previous Actor`, `Request Owner`) and fallback/block scenarios.
2. Result reported no failures/errors:
   - `workflow_engine: 25 tests ...`
   - `0 failed, 0 error(s) ...`
