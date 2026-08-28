# Workflow Engine & Studio — User Manual (Odoo 19)

This guide explains how end-users, approvers, and admins work with the Workflow Engine (runtime) and Workflow Studio (designer).

## 1) Key Concepts
- **Workflow Category**: business process definition (e.g., Exit Clearance).
- **Version**: published snapshot of a category’s BPMN, rules, and UI config.
- **Request**: one instance of a workflow started by a user.
- **Task Instance**: an active step/token, supports parallel branches.
- **Meta Task/Action**: configured actions (approve/reject/rework/etc.) on a node.
- **Field Rules**: dynamic visible/required/readonly policies per user/task/action.
- **Two-Factor (2FA)**: QR-first or Email OTP confirmation on sensitive actions.

## 2) Who Does What
- **Requester**: starts requests, views their allowed fields/sections.
- **Approver**: sees tasks assigned to them (or delegated/shared).
- **Department Manager**: may see/act on tasks in their department when configured.
- **Workflow Admin**: designs flows, publishes versions, overrides/force transitions.
- **Studio Admin**: manages access lists, field rules, assignments, automations.

## 3) Access & Security
- Users must be in the base workflow group **and** allowed on the category (users/groups/departments) to see or start it.
- Request visibility is limited to requester (if allowed), assigned approvers, delegated/shares, managers (if enabled), and admins.
- Confidential fields are enforced server-side via field rules and record rules; UI invisibility alone is not relied upon.

## 4) Starting a Request
1. Go to *Workflow* menu → pick a visible category.
2. Fill required fields (highlighted). Hidden fields are controlled by field rules.
3. Submit. Engine spawns task instances (parallel where defined) and routes to assignees.

## 5) Acting on a Task
1. Open *My Approvals* (or request form) and click the task banner or action button.
2. Review your department section only; other sections stay hidden if confidential.
3. Click **Approve/Reject/Rework** (or custom action). If 2FA required:
   - Default QR mode: scan QR in mobile app → wait for confirmation → click Verify.
   - Need fallback: click *Request OTP instead*, enter code, then Verify.
4. Comments: if action requires reason, the dialog enforces it.

## 6) Delegation & Sharing
- **Delegation**: set date_from/date_to and delegate user; delegate can act during window.
- **Share**: grant view or act permission to a specific user with optional expiry.
- Audit always records acting user and on-behalf-of when delegation/share is used.

## 7) Rework & Resubmit
- If rework is triggered, the engine routes back per BPMN: either previous actor or re-computed assignee depending on node config.
- History is immutable; each iteration increases iteration number on the task branch.

## 8) Parallel & Conditional Branches
- Forks create one task instance per branch (e.g., HR, IT, Payroll).
- Join policies: **all_of** (default), **any_of**, or **min_n** as configured.
- Conditional branches (e.g., casino employee) evaluate request data; skipped branches are not created.

## 9) Two-Factor Actions (QR/OTP)
- Enable per action in Studio: set *require_2fa* and choose method (qr/email_otp).
- QR flow: dialog shows QR only; mobile app calls `/workflow_engine/2fa/qr/event` with `token` and `decision` (`scanned/approve/reject`). UI updates live via bus.
- OTP fallback: user clicks *Request OTP instead* to reveal code input.

## 10) Force Transition & Reassignment (Admin)
- From the request form, admins can force move a task/token to a target node (reason required) or reassign an active task. Actions are fully audited.

## 11) Workflow Studio (Design)
Steps to create or update a workflow:
1. **Access**: Studio Admin opens *Workflow Studio*.
2. **Category Access**: set allowed users/groups/departments (zero-trust default deny).
3. **BPMN Design**: draw user tasks, gateways (parallel/conditional), timers, service tasks.
4. **Assignment Rules**: per userTask, set users/groups/domain, multi-approver mode (ANY/ALL), and fallback (escalate/block).
5. **Join/Reject Policies**: configure gateway join (all_of/any_of/min_n) and parallel reject policy (strict/soft).
6. **Field Rules**: build rule sets (conditions on user/record/context) to set visible/required/readonly; attach at category/task/action scope. Preview to test.
7. **Action Rules**: mark action-required fields and comment requirements; enable 2FA on sensitive actions.
8. **Automations**: configure timer/service nodes (email/webhook/queue job/auto transition), schedule, retry policy, and logs.
9. **Versioning**: save draft, validate, then publish. Only one active version per category; old versions remain for history.

## 12) Dashboards & Reports
- **My Workflow Dashboard**: shows totals by status and categories you can access.
- **Request Form**: timeline panel shows action logs; parallel summary indicates completed/remaining branches.
- **Audit Logs**: every action emits an immutable event with actor, on_behalf_of, from/to node, comment, payload, IP/user-agent when available.

## 13) Troubleshooting
- Cannot see category: ensure base group + category allow list.
- Cannot act: check assignment, delegation window, share scope, and 2FA completion.
- Field missing: field rules may hide it; verify rule sets and action-time requirements.
- Parallel stuck: verify join policy and that all required branches are assigned; admin can reassign or force transition if policy allows.
- QR not updating: confirm mobile calls `/workflow_engine/2fa/qr/event` and that bus is reachable; fall back to OTP if needed.

## 14) Mobile Integration Notes (QR)
- Mobile scans QR (token), calls `/workflow_engine/2fa/qr/event`:
  - `decision=scanned` → UI shows “Waiting”.
  - `decision=approve` → sets challenge verified; UI shows success.
  - `decision=reject` → sets failed; UI shows error.
- Bus channel format: `workflow_twofa_challenge:<token>`.

## 15) Roles & Minimal Rights Checklist
- Base: `workflow_engine.group_user`
- Design/Studio: `workflow_engine.group_studio_admin` (or equivalent)
- Runtime admin/override: `workflow_engine.group_admin`
- Category access: add user/group/department on each category
- Optional: department manager visibility, share/delegation permissions as policy allows.

Keep this file versioned alongside workflow definitions to align users, approvers, and studio admins on the same rules. 

## 16) Runtime Field Render Logic (Technical Note)
- Forms with `js_class="wf_form"` call server method `workflow_get_runtime_field_state_map` to fetch one payload:
  - `field_state_map[field] = { invisible, required, readonly }`
  - contextual metadata (node/action/user/request)
- The server computes this from node Meta Field configuration (`workflow.category.version.meta.field`) only.
- Studio contract for large-scale forms: configure visible/readonly/required rules on the BPMN node Meta Fields. View-level workflow field policies are not supported.
- Domain evaluation is server-side only, with a restricted safe-eval context (no raw `env` exposure).
- UI applies state map to form active field modifiers and refreshes on open, node/data changes, and action-button context.
- Zero-trust enforcement:
  - readonly fields are blocked on `write` (except system/workflow admins)
  - required fields are validated on `write` and before action transitions
  - invisible-only fields remain writable by policy (unless additionally readonly/required)

## 17) Business Cases For Workflow Configuration (By User Module)

Use this matrix to validate that each user role can configure and operate workflow behavior correctly.

| Case ID | User Module | Business Case | Configuration Scope | Expected Outcome |
|---|---|---|---|---|
| BC-CFG-001 | Studio Admin | Create a new workflow category for a business process | Category + model mapping | Category is created with target model and visible in Studio |
| BC-CFG-002 | Studio Admin | Configure zero-trust access using users/groups/departments | Category access policy | Only allowlisted users can see/open category |
| BC-CFG-003 | Workflow Admin | Prepare draft version and update BPMN | Version + BPMN | Metadata sync creates task/action rows from BPMN |
| BC-CFG-004 | Workflow Admin | Deploy a draft version | Version lifecycle | Version becomes active and routable |
| BC-CFG-005 | Workflow Admin | Publish and lock version for controlled release | Version lifecycle | Version is active, published, locked |
| BC-CFG-006 | Workflow Admin | Roll back to previously deployed version | Version lifecycle | Older deployed/published version becomes active |
| BC-CFG-007 | Studio Admin | Configure sequential approvals | userTask assignment + actions | Request routes from one task to next in order |
| BC-CFG-008 | Studio Admin | Configure parallel approvals with join policy all_of | gateway join + tasks | All required branches must approve before join continues |
| BC-CFG-009 | Studio Admin | Configure parallel approvals with join policy any_of/min_n | gateway join + tasks | Join completes when threshold policy is met |
| BC-CFG-010 | Studio Admin | Configure strict parallel rejection | parallel reject policy | One reject cancels remaining open sibling tasks |
| BC-CFG-011 | Studio Admin | Configure userTask with explicit users | task assignment | Task assignees resolve to explicit users |
| BC-CFG-012 | Studio Admin | Configure userTask with approval groups and user_domain | task assignment | Group users are filtered and assigned correctly |
| BC-CFG-013 | Studio Admin | Configure request_owner assignment mode | task assignment | Request owner receives task instance |
| BC-CFG-014 | Studio Admin | Configure previous_actor assignment mode for rework | task assignment | Rework routes to previous actor/delegate as configured |
| BC-CFG-015 | Studio Admin | Configure fallback policy block | task assignment | Task enters blocked status when no assignee found |
| BC-CFG-016 | Studio Admin | Configure fallback policy escalate_manager/admin_queue | task assignment | Fallback assignee is used when primary resolution fails |
| BC-CFG-017 | Studio Admin | Configure field rules at category scope | field rule set + binding | Visibility/required/readonly applies to all relevant tasks |
| BC-CFG-018 | Studio Admin | Configure field rules at task scope | field rule set + binding | Rule applies only on target node |
| BC-CFG-019 | Studio Admin | Configure field rules at action scope | field rule set + binding | Rule applies only for specific action execution |
| BC-CFG-020 | Studio Admin | Configure action requiring reason/comment | action policy | Transition is blocked until reason/comment is provided |
| BC-CFG-021 | Studio Admin | Configure action-level 2FA (QR) | action policy | Action requires successful QR challenge before completion |
| BC-CFG-022 | Studio Admin | Configure action-level 2FA (Email OTP) | action policy | Action requires valid OTP before completion |
| BC-CFG-023 | Workflow Admin | Configure delegation windows | delegation model | Delegate can act on behalf of delegator inside window |
| BC-CFG-024 | Workflow Admin | Configure temporary visibility/decision share | visibility scope | Shared user can view/act within granted scope and expiry |
| BC-CFG-025 | Studio Admin | Configure service task with conditional routing | BPMN node + action domain | Correct branch is selected based on request data |
| BC-CFG-026 | Studio Admin | Configure callActivity to subprocess | BPMN node + workflow map | Child workflow is started and parent waits/continues per mode |
| BC-CFG-027 | Studio Admin | Configure timer/automation node behavior | automation node + retries | Scheduled actions execute and audit runs are recorded |
| BC-CFG-028 | Compliance/Auditor | Validate immutable audit trail | runtime event logs | Assignment/decision/transition events are immutable and complete |

## 18) Full Test Case Checklist (Configuration + Runtime)

Use this checklist as the baseline regression suite for `workflow_engine` and `workflow_studio`.

| Test ID | Area | Actor | Scenario | Expected Result |
|---|---|---|---|---|
| TC-ACCESS-001 | Access | Studio Admin | Category with zero-trust enabled and specific users | Non-allowlisted users cannot read category |
| TC-ACCESS-002 | Access | Approver | Assigned approver opens request | Request and category are readable |
| TC-ACCESS-003 | Access | Outsider | Unassigned user searches request/category | No records returned |
| TC-ACCESS-004 | Access | Manager | Manager access enabled on category | Manager has read/decision access per policy |
| TC-VERSION-001 | Versioning | Workflow Admin | Deploy draft version | `is_active=True`, category active version updated |
| TC-VERSION-002 | Versioning | Workflow Admin | Publish version | `is_published=True`, `is_locked=True`, active set |
| TC-VERSION-003 | Versioning | Workflow Admin | Roll back to previously deployed version | Target version becomes active |
| TC-VERSION-004 | Versioning | Workflow Admin | Attempt rollback to non-deployed draft | UserError is raised |
| TC-BPMN-001 | BPMN Sync | Studio Admin | Sync BPMN with start/user/end flow | Meta tasks/actions are generated |
| TC-BPMN-002 | BPMN Sync | Studio Admin | Update BPMN and remove node | Removed metadata is cleaned up |
| TC-BPMN-003 | BPMN Sync | Studio Admin | Invalid BPMN on activation | Activation is blocked with validation error |
| TC-SEQ-001 | Sequential Flow | Requester + Approver | Submission -> Manager -> End | Two decisions complete and request reaches end |
| TC-PAR-001 | Parallel Flow | Two Approvers | Parallel all_of both approve | Join proceeds only after both decisions |
| TC-PAR-002 | Parallel Flow | Two Approvers | Parallel any_of one approve | Join proceeds after first approval |
| TC-PAR-003 | Parallel Flow | Two Approvers | Parallel min_n threshold reached | Join proceeds when min_n is satisfied |
| TC-PAR-004 | Parallel Flow | Two Approvers | Strict reject on one branch | Sibling open tasks are cancelled |
| TC-ASSIGN-001 | Assignment | Studio Admin | Explicit user assignment mode | Assignees match explicit user set |
| TC-ASSIGN-002 | Assignment | Studio Admin | Group assignment with user_domain filter | Only filtered users are assigned |
| TC-ASSIGN-003 | Assignment | Studio Admin | Request owner assignment mode | Request owner assigned |
| TC-ASSIGN-004 | Assignment | Studio Admin | Previous actor assignment on rework | Previous actor/delegate assigned |
| TC-ASSIGN-005 | Assignment | Studio Admin | No assignee + fallback block | Task status becomes blocked |
| TC-ASSIGN-006 | Assignment | Studio Admin | No assignee + fallback manager/admin queue | Fallback user assigned |
| TC-DELEG-001 | Delegation | Delegator + Delegate | Active delegation window | Delegate can execute action on behalf |
| TC-DELEG-002 | Delegation | Delegate | Delegation outside time window | Delegate cannot execute action |
| TC-SHARE-001 | Share | Workflow Admin | Grant read scope to user | User can view request only |
| TC-SHARE-002 | Share | Workflow Admin | Grant decision scope to user | User can execute configured action |
| TC-2FA-001 | 2FA | Approver | QR challenge for action | Challenge verifies and decision completes |
| TC-2FA-002 | 2FA | Approver | OTP challenge with invalid code | Verification fails |
| TC-2FA-003 | 2FA | Approver | OTP challenge with valid code | Verification succeeds and action completes |
| TC-2FA-004 | 2FA | Approver | Expired challenge token | Finalization blocked |
| TC-FIELD-001 | Field Rules | Studio Admin | Category-level visible/required rule | Form state map applies for all target records |
| TC-FIELD-002 | Field Rules | Studio Admin | Task-level readonly rule | Field readonly only on matching node |
| TC-FIELD-003 | Field Rules | Studio Admin | Action-level required rule | Transition blocked if missing value |
| TC-FIELD-004 | Field Rules | User | Attempt write to readonly field | Server-side ValidationError/AccessError |
| TC-FIELD-005 | Field Rules | User | Invisible-only field policy | Field hidden in UI but follows configured write policy |
| TC-NODE-001 | Node Type | Studio Admin | serviceTask with conditional domain | Next node selected by evaluated condition |
| TC-NODE-002 | Node Type | Studio Admin | scriptTask executes configured workflow actions | Side effects/audit recorded |
| TC-NODE-003 | Node Type | Studio Admin | callActivity sync subprocess | Child request created; parent continuation per execution mode |
| TC-NODE-004 | Node Type | Studio Admin | message/timer intermediate events | Runtime handles asynchronous/auto transitions correctly |
| TC-NODE-005 | Node Type | Studio Admin | end event transition | Request/task marked completed |
| TC-AUTO-001 | Automation | Studio Admin | Configure scheduled automation node | Next run computed and execution logged |
| TC-AUTO-002 | Automation | System | Retry policy on transient failure | Retry attempts follow policy and are audited |
| TC-AUTO-003 | Automation | System | Failure policy abort/escalate | Failure outcome follows node policy |
| TC-AUDIT-001 | Audit | Auditor | Assignment event created | Immutable event row includes actor/context |
| TC-AUDIT-002 | Audit | Auditor | Decision event idempotency | Duplicate idempotency key is rejected |
| TC-AUDIT-003 | Audit | Auditor | Attempt update/delete task event | Operation is blocked (immutable logs) |
| TC-E2E-001 | End-to-End | Requester + Approver + Admin | Full configured flow with version publish, submit, approve, complete | Request reaches end state with complete audit trail |

### Execution Notes
- Run backend regression first (`TransactionCase`/`HttpCase`) before UI tours.
- Keep test data independent from demo XML IDs where possible to avoid environment-specific failures.
- For each new node type/policy added in Studio, add at least one positive and one negative test case in this matrix.
