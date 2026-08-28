# Workflow Assignment Architecture Decision

## Decision

For mission-critical routing at scale, standardize on:

1. Node Meta Fields (`workflow.category.version.meta.field`) for field behavior (visible/readonly/required), including action-scoped required checks with `activity_action_ids`.
2. Symbol-based assignment domains for approvers (`assignment_user_domain` / `user_domain`), not deep object paths.

Do not continue adding new old-style inline XML field modifiers for new workflows.

## Why This Is The Stable Choice

- Symbol-based domains are deterministic and testable.
- Studio validation and runtime now share the same core symbols.
- Deep path expressions are fragile and are the most common cause of wrong approver routing.
- This model scales across many forms because routing rules are data-driven, not hard-coded view logic.

## Required Runtime Symbols For Approval Assignment

Use these symbols as the default language for assignment:

- `request_owner_id`
- `request_creator_id`
- `request_creator_manager_user_id`
- `request_owner_line_manager_user_id`
- `request_owner_department_manager_user_id`
- `request_owner_manager_chain_user_ids`
- `request_owner_team_code`
- `request_owner_line_code`
- `decided_approver_user_ids`
- `pending_approver_user_ids`
- `notification_submitter_and_decided_user_ids`

`manager_user_id` is legacy creator-manager semantics. Keep only for backward compatibility.

## Canonical Business Cases

- Creator only: `[('id', '=', request_creator_id)]`
- Creator manager: `[('id', '=', request_creator_manager_user_id)]`
- Request owner line manager: `[('id', '=', request_owner_line_manager_user_id)]`
- Request owner department manager: `[('id', '=', request_owner_department_manager_user_id)]`
- Escalation chain: `[('id', 'in', request_owner_manager_chain_user_ids)]`
- Same team as requester: `[('employee_ids.x_team_code', '!=', False), ('employee_ids.x_team_code', '=', request_owner_team_code)]`
- Same line as requester: `[('employee_ids.x_line_code', '!=', False), ('employee_ids.x_line_code', '=', request_owner_line_code)]`
- Previous decided approvers: `[('id', 'in', decided_approver_user_ids)]`
- Pending approvers only: `[('id', 'in', pending_approver_user_ids)]`

## Migration Rules (Old -> New)

- `request.request_owner_id.employee_id.parent_id.user_id.id`
  -> `request_owner_line_manager_user_id`
- `request.request_owner_emp_id.department_id.manager_id.user_id.id`
  -> `request_owner_department_manager_user_id`
- `request.create_uid.id`
  -> `request_creator_id`

## Rollout Policy For 7,000+ Users

1. Keep `zero_trust_enforced` on sensitive categories.
2. Require all new assignment rules to use symbols above.
3. Keep fallback policy explicit per task (`block` for strict control; `route_admin_queue` for operational continuity).
4. Block publish when Studio validator returns invalid domains.
5. Run assignment regression suite before deployment:
   - `workflow_engine/tests/test_runtime_services.py`
   - `workflow_studio/tests/test_form_only_policy.py`
   - `workflow_studio/tests/test_business_case_regression.py`

## Non-Negotiable Guardrails

- No hardcoded user IDs in production assignment domains.
- No deep object path domains for new config.
- Every task with custom assignment domain must define fallback behavior.
- Team/line-based routing must include `!= False` guards to avoid broad matches on empty requester data.
