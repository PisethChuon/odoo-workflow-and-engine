# Workflow Engine + Studio Architecture (Odoo 19)

## 1) Scope and design goals

This design upgrades `workflow_engine` and `workflow_studio` for enterprise approval workloads with:

- Parallel and conditional BPMN execution
- Zero-trust access controls (deny by default)
- Assignment correctness (delegation/share/fallback/history aware)
- Immutable audit logs
- Field-level confidentiality and action-time validation
- Optional action-level 2FA
- Studio-driven no-code configuration
- Backward compatibility with existing `workflow.approval.approver` semantics

## 2) Existing constraints in current codebase

- Runtime logic is mainly in `approval_child_mixin.py` and currently uses a single active node (`current_node_id`) + `workflow.approval.approver` rows that mix assignment and decision history.
- Studio already has metadata sync/write APIs on `workflow.approval.category.version`.
- Existing features must remain functional:
  - delegate/share wizard behavior
  - force transition
  - legacy meta fields (`required/readonly/invisible`)
  - current request list/form and action APIs

## 3) Chosen architecture

### 3.1 Core runtime model (token/task-instance model, additive migration)

We introduce additive models and keep old models intact:

1. `workflow.request.task.instance`
- One row per active/closed workflow node instance (branch aware)
- Holds workflow token state and join linkage

2. `workflow.request.task.assignee`
- Assignee snapshot rows for each task instance (supports multi-approver ANY/ALL)
- Stores original assignee and delegated actor mapping

3. `workflow.request.task.event` (immutable)
- Append-only audit log for assignment, decision, transition, fallback, 2FA, override

4. `workflow.request.visibility.scope`
- Explicit scoped visibility/edit/decision grants with expiry

5. `workflow.approval.delegation`
- Vacation delegation with date range and scope

6. `workflow.approval.action.challenge`
- Optional 2FA challenge bound to request/task/action/user

7. `workflow.field.rule.set` + `workflow.field.rule` + `workflow.field.rule.binding`
- Condition DSL and field state policies (visible/required/readonly)

8. `workflow.automation.node` + `workflow.automation.run`
- Versioned automation node config and run logs

This is a dual-runtime approach:
- Legacy UI/APIs continue to run.
- New runtime tables are written in parallel and used for security, audit, assignment correctness, and progressive execution control.

### 3.2 Why additive (vs hard replacement now)

Pros:
- Safe rollout with low regression risk for existing operations
- Incremental migration for live production data
- Ability to backfill runtime state from legacy approver rows

Tradeoff:
- Temporary overlap between legacy approver history and new immutable event logs
- Mitigated by an adapter service and reconciliation checks

### 3.3 Services (clean, testable modules)

Implemented as abstract service models:

- `workflow.engine.permission.service`
  - category access checks
  - request-level read/write/act checks
  - action authorization

- `workflow.engine.assignment.service`
  - deterministic assignment pipeline:
    1) source rule resolution
    2) candidate resolution (users/groups/domain)
    3) eligibility filter
    4) delegation substitution
    5) share overlay
    6) fallback escalation
    7) snapshot + assignment event

- `workflow.engine.runtime.service`
  - transition lock/idempotency
  - task instance lifecycle
  - join policy evaluation (`all_of/any_of/min_n`)
  - reject policy (`strict/soft`)

- `workflow.engine.audit.service`
  - append-only event writes with best-effort request metadata

- `workflow.engine.field.rule.service`
  - safe JSON DSL condition evaluation
  - state merge rules: invisible wins, readonly wins, required only if visible
  - action-time required checks

- `workflow.engine.twofactor.service`
  - challenge create/verify/expire/rate-limit hooks

### 3.4 Zero-trust security model

Default behavior: deny.

Category visibility:
- user must have `group_workflow_approval_user`
- and category allowlist match (`allowed_user_ids` OR `allowed_group_ids` OR `allowed_department_ids`)
- admin/system bypass

Request access:
- admin/system bypass
- else at least one of:
  - requester/creator (if category option allows)
  - active assigned task assignee (direct/delegated/shared)
  - explicit visibility scope
  - configured manager escalation scope

Server-side only for enforcement:
- record rules on `workflow.base.approval.request`, `workflow.request.task.instance`,
  `workflow.request.task.assignee`, confidential department submodels
- no reliance on client-side invisibility

### 3.5 Confidential data strategy

For strict confidentiality:
- keep shared request header in base model
- department-sensitive fields are stored in department-specific payload model (`workflow.request.department.payload`)
  with strict record rules by department/scope
- field-rule engine controls UI behavior but storage isolation enforces server-side privacy

### 3.6 Execution semantics

- Parallel fork creates multiple task instances
- Join node checks policy and required branch completion
- Rework/resubmit loops:
  - keep immutable events
  - increment `iteration_no`
  - rework assignment can target historical actor (`assign_to_previous_actor`) or request owner
- Multi-approver:
  - `ANY`: first approval closes task and auto-closes remaining assignees with audit
  - `ALL`: complete when all required assignees approve

### 3.7 Concurrency and idempotency

- Lock request row with `FOR UPDATE NOWAIT` inside transition block
- Action idempotency key (`idempotency_key`) checked in audit/event stream
- Unique constraints prevent duplicate active assignment snapshots
- Conflict-safe writes with savepoints and explicit user-facing errors

### 3.8 Studio configuration model

Studio must configure and version:

- Category access allowlists
- Node assignment rules and fallback policy
- Completion mode ANY/ALL
- Join policy and reject policy
- Action rules (required fields/comment/2FA)
- Field rule sets + binding to category/task/action
- Automation node config (schedule/action/timeout/retry)
- Rule simulation endpoint for preview

All write operations are audited using chatter + immutable task events.

### 3.9 Backward compatibility and migration

- Existing `workflow.approval.approver` remains supported
- New services write synchronization events/task instances alongside existing flow
- Existing APIs and buttons unchanged
- Legacy per-task field config still read and mapped into new rule evaluation output
- Migration strategy:
  - new models and constraints are additive
  - optional post-init backfill for active requests

## 4) Safe defaults (configurable)

- Join policy default: `all_of`
- Parallel reject policy default: `strict`
- Multi-approver completion default: `any`
- No-assignee fallback default: `route_admin_queue`
- Delegation scope default: approvals only
- Request owner can view own request header by default; department confidential payload hidden unless explicit scope
- 2FA default: disabled globally, enabled per category/action rule

## 5) Implementation plan

1. Add core models, constraints, indexes, and ACL/record rules.
2. Add runtime services (permission, assignment, audit, rule, 2FA).
3. Integrate existing transition flow (`action_do_transition` / `_run_engine`) with:
   - request lock
   - assignment snapshot + immutable task events
   - multi-approver ANY/ALL control
   - fallback and delegation/share checks
4. Extend Studio payload APIs and BPMN sidebar persistence for new config fields.
5. Add automation node scheduling and run logs.
6. Add tests for assignment correctness/security/concurrency/join behavior.
7. Add README operational guidance.

## 6) Planned file tree changes

`workflow_engine`
- `models/workflow_task_instance.py`
- `models/workflow_task_event.py`
- `models/workflow_visibility_scope.py`
- `models/workflow_delegation.py`
- `models/workflow_action_challenge.py`
- `models/workflow_field_rule.py`
- `models/workflow_automation_node.py`
- `models/workflow_department_payload.py`
- `models/workflow_engine_services.py`
- `security/access_workflow_runtime.xml`
- `security/rule_workflow_runtime.xml`
- updates in existing runtime models for integration

`workflow_studio`
- extend `models/workflow_approval_category_version.py` serialization/write APIs
- optional OWL sidebar field support in BPMN editor for new config sections

Tests:
- `workflow_engine/tests/test_assignment_pipeline.py`
- `workflow_engine/tests/test_parallel_join_policy.py`
- `workflow_engine/tests/test_security_zero_trust.py`
- `workflow_engine/tests/test_rework_previous_actor.py`
- `workflow_engine/tests/test_multi_approver_modes.py`
- `workflow_engine/tests/test_concurrency_locking.py`

