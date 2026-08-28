# Workflow Extension Contract (Mission-Critical)

This contract defines the only supported extension seams for Workflow Engine in production.
Use these hooks to extend behavior without editing legacy transition code paths.

## 1) Assignment Modes

Extension point:

- Model: `workflow.engine.assignment.service`
- Method: `_assignment_mode_collectors()`

Contract:

- Return a dict `{mode_key: collector_callable}`.
- `collector_callable(request_record, meta_task, warnings=None)` must return `res.users`.
- Callables must be deterministic and side-effect free.
- Do not write to request/runtime models inside collectors.

Required guarantees:

- Never throw uncaught exceptions for malformed domain/config; append warning and return empty set.
- Preserve backward compatibility for built-in keys:
  - `mixed`
  - `explicit_users`
  - `groups`
  - `domain`
  - `previous_actor`
  - `request_owner`

## 2) Fallback Policies

Extension point:

- Model: `workflow.engine.assignment.service`
- Method: `_fallback_policy_handlers()`

Contract:

- Return a dict `{policy_key: handler_callable}`.
- `handler_callable(request_record, meta_task)` must return `res.users`.
- Handlers must not mutate workflow runtime state.

Required guarantees:

- Keep `block` available as safe default.
- If a custom policy fails, fallback must degrade to `block`, not crash transition flow.

## 3) 2FA Methods

Extension points:

- Model: `workflow.engine.runtime.service`
- Method: `_twofa_issue_handlers()`
- Method: `_twofa_verify_handlers()`

Contract:

- Issue handler signature:
  - `(request_record, meta_action, actor_user, task_instance=False, ttl_seconds=90)`
- Verify handler signature:
  - `(challenge, otp_value=False, task_instance=False)`
- Return challenge/result objects compatible with existing runtime audit flow.

Required guarantees:

- 2FA verification failure must not transition request state.
- Record audit event with challenge id, method, actor, host, and ip.
- Method implementation must be idempotent for repeated mobile/app retries.

## 4) Legacy Flow Adapter

Extension point:

- Model: `workflow.engine.legacy.adapter.service`
- Methods:
  - `prepare_legacy_approver_rows(...)`
  - `build_unassigned_stage_reason(...)`

Purpose:

- Bridge old `approval_child_mixin` flow to modern assignment/domain services.
- Keep legacy transitions operational while moving policy logic into services.

Required guarantees:

- No direct domain `safe_eval` in legacy mixin assignment path.
- Adapter must rely on `workflow.engine.assignment.service.resolve_assignees(...)`.
- Returned approver rows must be deterministic and duplicate-safe by `(user, task, previous_task, iteration)`.

## 5) Security and Data Boundaries

Rules:

- UI/Studio configuration never authorizes transitions; server services do.
- Assignment eligibility must pass:
  - category allow-list policy (unless explicitly configured bypass),
  - company scope,
  - target record read ACL check.
- Any extension must preserve zero-trust checks.

## 6) Production-Safe Change Checklist

Before merge:

1. Add/adjust tests in `engine/workflow_engine/tests/`.
2. Run module regression:
   - `--test-tags=/workflow_engine`
3. Run combined regression:
   - `--test-tags=/workflow_engine,/workflow_studio`
4. Verify no new direct `safe_eval` in legacy assignment path.
5. Confirm fallback behavior when no assignee is resolved.

## 7) Non-Compliant Patterns (Do Not Use)

- Editing `approval_child_mixin` to add custom assignment logic directly.
- Introducing new assignment/fallback behavior without service registry hooks.
- Coupling transition authorization to client-side field visibility.
- Bypassing runtime audit event logging for decisions/2FA/force transitions.
