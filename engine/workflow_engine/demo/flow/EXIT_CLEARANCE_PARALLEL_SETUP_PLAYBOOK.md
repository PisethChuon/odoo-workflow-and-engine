# Exit Clearance Setup Playbook (Parallel Departments, No Sub-Process)

## 1) Architecture Decision

Use **one main BPMN process** with parallel department user tasks.
Do **not** create BPMN sub-process per department unless that department needs a multi-step internal workflow.

Baseline runtime pattern:

- `assignment_mode = groups`
- `completion_mode = all`
- `fallback_policy = route_admin_queue`
- `requires_department_payload = true`
- `join_key = exit_clearance_departments`
- `gateway_node_id = Gateway_DeptJoin`
- `join_policy = all_of`
- `parallel_reject_policy = strict`

This keeps configuration simple for 57+ workflows and stable for high concurrency.

## 2) Node Setup (Exit Clearance)

Use this for department parallel tasks:

- `Task_ITClearance`
- `Task_FinanceClearance`
- `Task_AdminClearance`
- `Task_SecurityClearance`
- `Task_FacilityClearance`
- `Task_PurchaseClearance`
- `Task_OperationsClearance`
- `Task_HRDeptClearance`

Final control nodes:

- `Task_HODFinalReview`: `confidentiality_level = restricted`
- `Task_PayrollReview`: `confidentiality_level = restricted`
- `Task_HRFinalClearance`: `confidentiality_level = restricted`, `requires_department_payload = true`

## 3) Form Strategy (Sub-Form Behavior via `wf_field`)

Use one shared form view, but department-specific fields must be controlled from the selected BPMN node Meta Fields.

Supported field contract for this rollout:

- Configure `visible`, `readonly`, and `required` rows in node Meta Fields.
- Keep form XML free of workflow-specific field policy attributes.

Action-specific required rule example (Approve required, Rework not required):

- Configure in `workflow.category.version.meta.field` (not in view XML).
- `field_type = required`
- `meta_id = Task_ITClearance`
- `activity_action_ids = [approve_action]` for required-on-approve field rows
- Add separate rows for rework only when needed

This keeps the form arch short and avoids large inline domain strings.

## 4) Department Payload Convention

Each department writes to its scoped payload row (`workflow.request.department.payload`) instead of overwriting common fields.

Recommended key format:

- `<task_node_id>:<section>`
- Example: `Task_ITClearance:asset_return`

Uniqueness is enforced by:

- `(request_id, department_id, key, iteration_no)`

This prevents collision when many departments update the same exit request in parallel.

## 5) Concurrency and Safety Controls

Runtime controls already in engine:

- Request lock: `FOR UPDATE NOWAIT` before transition.
- Idempotency event key: unique per `(request_id, event_type, idempotency_key)`.
- Strict parallel reject: one reject cancels remaining open siblings in same `join_key`.

Operational impact:

- If two users click transition at same time, one proceeds, one gets retry-safe message.
- Duplicate approval submission is blocked by idempotency key uniqueness.
- Parallel department consistency remains deterministic.

## 6) Migration from Old Style Fields

For existing configured forms, migrate with bulk policy wizard (no manual field-by-field rewrite):

1. Open Workflow Studio.
2. Select the target BPMN node.
3. Configure visible/readonly/required rows in the node Meta Fields section.
4. Configure action-specific required rules using `activity_action_ids` (Approve/Rework scoped).

Keep old static `invisible/required/readonly` only for fields that are truly global.

## 7) Must-Pass Regression Suite

Run these tests before production rollout:

- `test_exit_clearance_demo_assignment_and_group_links`
- `test_exit_clearance_demo_runtime_controls_for_parallel_departments`
- `test_parallel_strict_reject_cancels_open_siblings`
- `test_action_specific_required_fields_scoped_by_activity_and_action`
- `test_lock_request_raises_user_error_when_db_lock_fails`
- `test_department_payload_unique_per_request_department_key_iteration`
- `test_department_payload_scope_blocks_other_department_user`

## 8) When to Use a Department Sub-Process

Use BPMN sub-process only if a department has internal routing like:

- sequential approvers inside one department,
- SLA/escalation unique to that department,
- dynamic child tasks not representable as one user task.

If not needed, keep the flat parallel model for lower maintenance and faster incident recovery.
