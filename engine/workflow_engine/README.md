Workflow Engine
===============

This module provides the runtime approval engine for workflow requests in Odoo 19.

## What is included

- Legacy workflow runtime compatibility (`workflow.approval.approver` based)
- New runtime layer for scalable execution and audit:
  - `workflow.request.task.instance`
  - `workflow.request.task.assignee`
  - `workflow.request.task.event` (immutable)
  - `workflow.request.visibility.scope`
  - `workflow.approval.delegation`
  - `workflow.approval.action.challenge` (2FA)
  - `workflow.field.rule.*` (rule sets + bindings)
  - `workflow.automation.node` + `workflow.automation.run`
  - `workflow.request.department.payload` (confidential sections)
- Runtime services:
  - permission service
  - assignment service
  - runtime/locking service
  - audit service
  - field-rule service
  - two-factor service

## Zero-trust category access

Each category now supports allowlist controls:

- `zero_trust_enforced`
- `allowed_user_ids`
- `allowed_group_ids`
- `allowed_department_ids`

When enabled, users must be explicitly allowed to see/start category content.

## Assignment pipeline

The engine resolves assignees in deterministic order:

1. Task assignment config (explicit users/groups/domain/history/request owner)
2. Eligibility filtering (workflow group/company/category policy)
3. Delegation substitution (date-scoped)
4. Share overrides (`workflow.request.visibility.scope`, decision scope)
5. Fallback policy (`escalate_manager`, `route_admin_queue`, `block`)
6. Snapshot persistence in task-instance/assignee rows
7. Immutable assignment audit event

## 2FA approvals

Action-level 2FA is configurable on `workflow.category.version.meta.task.action`:

- `require_2fa`
- `twofa_method` (`email_otp`/`qr`)

## Two-Factor (QR-first with OTP fallback)
- When `require_2fa` is enabled on an action (optionally with a condition domain), the workflow action opens the 2FA dialog instead of executing immediately.
- Primary: QR challenge (90s). QR encodes `challenge_id`, token, and HMAC signature. Mobile calls `/workflow_2fa/mobile/confirm` after scan to approve/deny; bus channel `("workflow_2fa", challenge_id)` pushes `scanned/approved/denied/expired`.
- Fallback: OTP (5 digits). User can request/resend via `/workflow_2fa/challenge/request_otp`; verify via `/workflow_2fa/challenge/verify_otp`. Cooldown and attempt limits enforced; OTP emailed to the user’s address (UI shows masked email).
- Finalize: client calls `/workflow_2fa/finalize_action` which re-checks approved state and runs the original workflow action with idempotency protection.
- `twofa_condition_domain`

Current implementation includes Email OTP with expiry and one-time verification.

## Field-rule engine

Rule sets are modeled via:

- `workflow.field.rule.set`
- `workflow.field.rule`
- `workflow.field.rule.binding`

Rules evaluate JSON conditions and output per-field visibility/required/readonly states.
Action-time validation is enforced server-side in confirmation flow.

## Studio support

Studio metadata payload now serializes/writes runtime fields for task/action policies
(assignment mode, completion mode, join/reject policy, confidentiality, 2FA, idempotency).

## Scheduler jobs

New cron jobs:

- scheduled automation runner
- challenge expiry cleanup

## Regression gate

Run the MTF/workflow regression gate before deploying workflow engine changes that can affect request creation, routing, assignment, or approvals.

From the repository root:

```sh
sh ./naga/workflow/engine/workflow_engine/scripts/run_mtf_workflow_regression.sh --database workflow-v19 --config ../config/noc-prod.conf --suite gate
```

For a production-like validation, run the gate against a cloned preprod database, not an active shared/live database:

```sh
sh ./naga/workflow/engine/workflow_engine/scripts/run_mtf_workflow_regression.sh --database preprod-regression --config ../config/noc-prod.conf --suite gate
```

The gate upgrades `workflow_inventory`, `workflow_engine`, `workflow_studio`, and `medical_request`, then runs focused tests for:

- delegated MTF workflow-action execution without direct child-record write access
- Conditional Event Definition default routing for empty and invalid condition domains
- approval group/domain assignment, including child-record domain evaluation and request-owner department paths
- approval button visibility for workflow approval group members and non-members

The gate also verifies that all 11 focused tests ran. It fails when Odoo
silently skips a missing or stale test selector.

For a deeper backend run, use:

```sh
sh ./naga/workflow/engine/workflow_engine/scripts/run_mtf_workflow_regression.sh --database preprod-regression --config ../config/noc-prod.conf --suite full-backend
```

Use `gate` before every deployment. Use `full-backend` for nightly validation or before high-risk workflow releases.

## Main references

- Architecture design: `workflow_engine/README_ARCHITECTURE.md`
- Development guide: `workflow_engine/DEVELOPMENT_GUIDELINES.md`
- Workflow Studio UI/UX reference: [workflow_studio/README.md](../workflow_studio/README.md)


## Release notes

- 3.26
    - fix compute function for request_owner_emp_type
    
- 3.25
    - add report apprval directory
    - add redirect and share base on the config studio business actor'
    - update workflow secutiry
    - fix permission when request is done state
    - add the import_wizard using

- 3.18
    - fix style on report base layout
    
- 3.17
    - fix problem showing non-submitter in submission state
    - remove unnecessary demo data

- 3.16
    - add comment to default visible field
    - remove comment from base form view
    - set default value of comment_required to True, and comment_required_domain to False

- 3.15
    - add meta action mode with route default and execute_path side-effect traversal
    - support loop-back notify actions that execute send/script/executor tasks and reassign current user task
    - clarify Exclusive, Parallel, and Inclusive gateway runtime behavior and Studio guidance
    - add Odoo-style date domain support for current_date, context_today(), and today +/- tokens
    - make runtime domain guard authoritative for manual, execute-path, timer, and auto actions
    - harden scheduled reminders with bounded recurrence and active-branch stop conditions
    - split reason and comment requirements with independent domains and wizard fields
    - add Studio date presets, action mode config, gateway help, and separate reason/comment domain builders
    - fix workflow action config sudo reads for automation execution
    - avoid Studio crash when optional email recipient table is missing
    - add backend and Studio regression coverage
    - change access rule: model_workflow_approval_action to be accessible by workflow user

- 3.14
    - If context: automated_sequence is not given, it is default to True

- 3.13
    - Delegate button is hidden for request owner and request creator
    - Create context automated_sequence for when creating a new request

- 3.12
    - Update request owner phone

- 3.11
    - Fix on update activity
    - Hide chatter and attachment preview

- 3.10
    - Fix force transition
    - Fix style (category not shown in workflow dashboard page because it is hidden by style)

- 3.9
    - Fix style
    - Remove unused files, unused config

- 3.8
    - Fix condition node engine

- 3.7
    - Update

- 3.6
    - Add meta field configuration to end event node.
    - Fix duplicate request error

- 3.5
    - update on base view

- 3.4
    - extract create button logic to a function

- 3.3
    - add field submit_date to base view
    - set noupdate=1 for all data, but remove it other type of documents

- 3.2
    - remove unused fields: auto_approve_timeout, and allow_admin_to_edit_timeout
    - fix error because counter fields are not stored
    - fix error comment is still required in refused, cancelled, and auto_cancelled
    - fix error there is no cancelled in user_status

- 3.1
    - apply different colors on action buttons
    - add submit_date field to workflow.base.approval.request and its automation rule
    - fix the permission issue when tryhing to access company detail

- 3.0
    - add runtime task instance/event models and immutable audit trail
    - add zero-trust category access model
    - add assignment pipeline service with delegation/share/fallback
    - add action-level OTP challenge framework and wizard integration
    - add field rule set models and runtime evaluation hooks
    - add automation node/run models and scheduler
    - add runtime insight views and security ACL/rules

- 2.1
    - restored base form view to show chatter
    - fixed error alerted when user clicks on bpmn node in configuration page

- 2.0
    - request owner fields to be the related fields
    - use create_date in activity history
    - rename field label to standard

- 1.9
    - add age after activity change
    - if invisible domain validates to false, don't add approver button
    - move the logic of setting completed date to base request class

- 1.8
  - fix create duplicate activity for request owner
  - request owner field in view can be editable only in draft and new
  - fix create duplicate activity for request owner
  - request owner field in view can be editable only in draft and new
  - move out integration provider to api controller

- 1.7
  - fix `_compute_updated_date`
  - update approval request view
