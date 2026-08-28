# Workflow Studio User Manual (Odoo 19)

This manual explains every property panel option used to configure BPMN nodes and transitions in Workflow Studio.

Scope:
- Module: `workflow_studio`
- Focus: node/transition property configuration, assignment, domains, approval groups, workflow mapping
- Runtime behavior reference: `../workflow_engine/USER_MANUAL.md`

## 1. Who Should Use This

Use this guide if you are:
- Workflow Admin / Designer
- Business analyst configuring approval flows
- Support engineer reviewing production category setup

## 2. Access Requirements

You must have:
- Workflow Studio access (Workflow Approval Admin or System Admin)
- Category access based on category access control

## 3. Recommended Design Sequence

1. Create or open the category version.
2. Build BPMN nodes/transitions.
3. Click **Save Diagram**.
4. Click **Sync Metadata**.
5. Configure node properties.
6. Configure transition (Meta Action) properties.
7. Validate with sample records/users.
8. Deploy/Publish.

## 4. Property Panel Basics

In the right panel (**Properties** tab):
- Select a BPMN node to edit **Meta Task** properties.
- Select a transition line or action icon node to edit **Meta Action** properties.
- Some sections appear only for specific node types.

## 5. Supported BPMN Element Types

### 5.1 Task/Node Types

- `startEvent`
- `startEventMessage`
- `startEventTimer`
- `startEventSignal`
- `startEventConditional`
- `userTask`
- `manualTask`
- `task`
- `serviceTask`
- `sendTask`
- `receiveTask`
- `scriptTask`
- `businessRuleTask`
- `callActivity`
- `subProcess`
- `endEvent`
- `endEventMessage`
- `endEventSignal`
- `endEventTerminate`
- `intermediateCatchEvent`
- `conditionalEventDefinition`
- `intermediateEventSignal`
- `exclusiveGateway`
- `parallelGateway`
- `inclusiveGateway`
- `eventBasedGateway`
- `complexGateway`

### 5.2 Action/Transition Types (Meta Action nodes)

- `intermediateEventMessage`
- `timerEvent`
- `intermediateThrowEvent`
- `intermediateThrowEventMessage`
- `intermediateThrowEventSignal`

## 6. Node Type Matrix (Which Section Appears Where)

- **Action Window**: human/collaboration tasks, automation tasks, `sendTask`
- **Email Template**: assignment tasks, `sendTask`, start events, end events
- **Activity Type**: assignment tasks, automation tasks, notification nodes
- **Activity Message Template**: assignment tasks, notification nodes
- **Notification Recipients**: notification nodes
- **Workflow Actions**: notification nodes, automation nodes
- **Approval Group Domain**: assignment tasks
- **Notification Domain**: notification nodes
- **Runtime Assignment**: assignment tasks
- **Parallel and Rework**: gateways
- **Confidentiality**: most task-like nodes (human/collaboration/automation/send/receive)
- **Meta Fields**: human/collaboration/automation/send
- **Approval Groups**: human tasks + `callActivity` + `subProcess`
- **Workflow Mapping**: `callActivity` only

## 7. Meta Task (Node) Property Reference

### 7.1 Common Properties

- **Node ID** (readonly): technical BPMN node identifier.
- **Node Type** (readonly): engine type (for example `userTask`).
- **Name**: internal node name.
- **Description**: admin-facing notes.
- **Sequence**: order value used by metadata processing.
- **Label (`attr_label`)**: display label in runtime/UI.
- **CSS Class (`attr_class`)**: custom CSS classes.
- **Element Type (`element`)**:
  - `sequence`
  - `parallel`
  - `loop`
- **Is End Node** (readonly): computed from node type.

### 7.2 Action Window

- **Action Window (`action_id`)**: opens form/list/dialog for this node action context.
- Use **+ New** to create `ir.actions.act_window` from Studio.

### 7.3 Templates and Notifications

- **Email Template (`email_template_external_id`)**: optional mail template.
- **Notification Recipients (`notification_recipient_ids`)**: explicit user targets.
- **Notification Domain (`notification_recipient_domain`)**: dynamic recipient filter.
- **Activity Type (`activity_type`)**: currently `Log Activity`.
- **Activity Message Template (`activity_message_template`)**: template for task activity messages.

### 7.4 Workflow Actions (Notification/Automation Channels)

- **Workflow Actions (`activity_type_ids`)**: reusable action channels attached to node.
- Use **+ New Channel** to create reusable `workflow.approval.action` records.

Supported channel types:
- `log`
- `email`
- `sms`
- `telegram`
- `webhook`
- `server_action`
- `workflow`

### 7.5 Approval Group Domain

- **Approval Group Domain (`approval_group_domain`)**: dynamic candidate filter used in assignment fallback behavior.
- Use **Builder** or preset list.

### 7.6 Runtime Assignment

#### Assignment Mode (`assignment_mode`)

- `mixed`: merge explicit users + group rules + assignment user domain
- `explicit_users`: use only explicit users
- `groups`: use approval groups/group rules
- `domain`: use assignment user domain only
- `previous_actor`: assign previous actor (or request owner fallback)
- `request_owner`: assign request owner

#### Explicit Users (`explicit_user_ids`)

- Multi-select user list.
- Search supports name, login, email, employee code.

#### Assignment User Domain (`assignment_user_domain`)

- User-domain expression over `res.users` with request/runtime symbols.

#### Completion Mode (`completion_mode`)

- `any`: one assignee decision can complete node
- `all`: all active assignees must complete

#### Fallback Policy (`fallback_policy`)

- `route_admin_queue`
- `escalate_manager`
- `block`

#### Fallback User (`fallback_user_id`)

- Optional explicit user for admin-queue routing.

### 7.7 Parallel and Rework (Gateway/Join Controls)

- **Join Key (`join_key`)**: correlation key for joins.
- **Gateway Node ID (`gateway_node_id`)**: explicit gateway binding identifier.
- **Join Policy (`join_policy`)**:
  - `all_of`
  - `any_of`
  - `min_n` (requires `join_min_n > 0`)
- **Join Min N (`join_min_n`)**: minimum completed branches when `min_n`.
- **Parallel Reject Policy (`parallel_reject_policy`)**:
  - `strict`
  - `soft`
- **Assign to Previous Actor (`assign_to_previous_actor`)**: additive candidate source.
- **Previous Actor Node Ref (`previous_actor_node_ref`)**: optional source node for previous actor lookup.
- **Assign to Request Owner (`assign_to_request_owner`)**: additive candidate source.

### 7.8 Confidentiality

- **Confidentiality Level (`confidentiality_level`)**:
  - `public`
  - `department`
  - `restricted`
- **Department (`department_id`)**: department scope for department-level confidentiality.
- **Requires Department Payload (`requires_department_payload`)**: requires scoped payload for department.
- **Enable Share Override (`enable_share_override`)**: allow decision-scope share override.

### 7.9 Meta Fields (Field Rule Binding)

For each row:
- **Fields**: one or more request fields (includes related model fields from allowed relations).
- **Types (`field_types`)**:
  - `visible`
  - `required`
  - `readonly`
- **Limit To Actions (`activity_action_keys`)**: applies only to `required` rules.

Buttons:
- **+ Add Field Rule**
- Use the main **Save** button to save field rules with the diagram metadata.

### 7.10 Outgoing Actions

- Read-only list of transitions from selected node.
- Click one to open **Meta Action** properties.

### 7.11 Approval Groups (Node-Level Rule Editor)

This section has 3 parts:

1. **Configured Group Rules**
- shows linked rules on current node
- `Configure` opens group profile
- `Unlink` removes rule from node immediately

2. **Existing Approval Groups Catalog**
- filter by name/department/member
- mode: all/linked/available
- `Link to node` / `Unlink from node` saves immediately

3. **Rule Detail Editor**
- **Approval Group**
- **Sequence**
- **User Domain (`user_domain`)**
- **Record Domain (`domain`)**
- **Note**
- **Save Rule Details** persists sequence/domain/note edits

### 7.12 Workflow Mapping (`callActivity` only)

Per map row:
- **Called Workflow (`called_workflow_ref`)**
- **Execution Mode (`execution_mode`)**:
  - `sync` = Required
  - `async` = Optional
- **Field Mapping JSON (`field_mapping`)**
- **Domain (`domain`)**: request-scope domain for map applicability

Buttons:
- **+ Add Workflow Map**
- **Save Workflow Maps**

## 8. Meta Action (Transition) Property Reference

### 8.1 Basic

- **Transition** (readonly): `source -> target`
- **Flow Name (`name`)**
- **Label (`attr_label`)**
- **Flow Type (`flow_type`, readonly)**
- **Button Label (`action_button_label`)**
- **Description (`description`)**

### 8.2 Action Button Styling

For `emailAction` and `noEmailAction` transitions:
- **Button CSS Preset**
- **Custom Button CSS Classes (`attr_class`)**
- **Font Awesome Icon Preset**
- **Custom Font Awesome Icon (`icon_class`)**

For other flow types:
- **CSS Class (`attr_class`)**
- **Icon Class (`icon_class`)**

### 8.3 Confirmation and Input Controls

- **Show Confirmation Dialog (`show_confirm_dialog`)**
- **Require Reason (`require_reason`)**
- **Comment Required (`comment_required`)**
- **Idempotency Required (`idempotency_required`)**

### 8.4 2FA Controls

- **Require 2FA (`require_2fa`)**
- **2FA Method (`twofa_method`)**:
  - `email_otp`
  - `qr`
- **2FA Condition Domain (`twofa_condition_domain`)**

### 8.5 Validation and Policy

- **Action Rule Set (`required_rule_set_id`)**: optional rule set for action-time required-field checks.
- **Dialog Type (`dialog_type`)**:
  - `confirm`
  - `proceed`
  - `reject`
- **Required Approvals (`approval_require_number`)**: minimum 1.
- **Auto Action Condition (`auto_action_condition`)**: advanced auto execution condition.

### 8.6 Visibility and Execution Domains

- **Button Visibility Domain (`invisible_domain`)**
- **Action Execution Domain (`domain`)**

How they differ:
- `invisible_domain`: controls whether Submit/Approve/Reject button is shown in UI.
- `domain`: advanced runtime condition for action behavior (for example, confirmation/execute condition). It is not the primary button-visibility switch.

Both support presets and builder.

### 8.7 Messaging

- **Confirm Message (`confirm_message`)**

## 9. Domain Builder Manual

### 9.1 Dialog Modes

- **Simple Builder**: guided clause builder
- **Advanced**: manual expression editing

### 9.2 Context Types Used in Studio

- `generic`: default domain editing
- `assignment_users`: user filtering with request/runtime symbols
- `request_scope`: request-record filtering
- `twofa`: action 2FA conditional domain
- `field_modifiers`: visible/readonly/required field conditions

### 9.3 Runtime Symbols (Common)

You can use:
- `request` (request object)
- `user` / `current_user` (actor user object)
- `uid` (actor user id)
- `request_owner_id`
- `request_creator_id`
- `manager_user_id` (creator manager legacy symbol)
- `request_creator_manager_user_id`
- `request_owner_manager_user_id`
- `request_owner_line_manager_user_id`
- `request_owner_department_manager_user_id`
- `request_owner_manager_chain_user_ids`
- `request_owner_team_code`
- `request_owner_line_code`
- request model fields directly (for example `x_amount_total`)

Deep path example:
- `[('id', '=', request.request_owner_id.employee_id.parent_id.user_id.id)]`
Prefer stable symbols instead of deep path for production.

### 9.4 Assignment Presets (User Domains)

Common presets include:
- `[('id', '=', uid)]`
- `[('share', '=', False), ('active', '=', True)]`
- `[('id', '=', request_owner_id)]`
- `[('id', '=', manager_user_id)]`
- `[('id', '=', request_creator_id)]`
- `[('id', '=', request_creator_manager_user_id)]`
- `[('id', '=', request_owner_manager_user_id)]`
- `[('id', '=', request_owner_line_manager_user_id)]`
- `[('id', '=', request_owner_department_manager_user_id)]`
- `[('id', 'in', request_owner_manager_chain_user_ids)]`
- `[('id', 'in', [request_owner_id, manager_user_id])]`
- `[('employee_ids.x_team_code', '!=', False), ('employee_ids.x_team_code', '=', request_owner_team_code)]`
- `[('employee_ids.x_line_code', '!=', False), ('employee_ids.x_line_code', '=', request_owner_line_code)]`
- `[('id', 'in', [uid, request_owner_id])]`
- `[('company_id', '=', user.company_id.id)]`
- `[('id', '!=', request_owner_id)]`
- `[('id', 'in', decided_approver_user_ids)]`
- `[('id', 'in', pending_approver_user_ids)]`
- `[('id', 'in', notification_submitter_and_decided_user_ids)]`

### 9.5 Record Scope Presets

Common presets include:
- `[]`
- `[('request_owner_id', '=', uid)]`
- `[('manager_user_id', '=', uid)]`
- `[('manager_user_id', '!=', False)]`
- `[('company_id', '=', user.company_id.id)]`
- `[('state', 'in', ['draft', 'new'])]`
- `[('state', '=', 'waiting')]`

### 9.6 Action Visibility Presets

- Always show
- Pending only
- Waiting only

## 10. Form Designer: Field Policies At Scale (100-300 Fields)

You can configure field-level workflow conditions directly in Form Designer using:
- **Workflow Visible**
- **Workflow Readonly**
- **Workflow Required**

These are domain-driven and evaluated with runtime request + actor symbols.

### 10.1 Bulk Apply (Recommended for Large Forms)

From any field in Form Designer:
1. Configure the source rule(s) on that field.
2. Click **Apply To Multiple Fields**.
3. Search/select target fields.
4. Choose which source rules to copy (Visible/Readonly/Required).
5. Click **Apply Rules**.

This is designed for high-volume setup and keeps the same rule behavior across many fields.

### 10.2 Example Scenario (Submitter, HOD, Doctor)

Example for field `description`:
- Submitter: visible, editable, required
- HOD: visible, readonly
- Doctor: visible (editable if readonly rule does not match)

Sample approach:
- **Visible**: allow all three actors/stages
- **Readonly**: match HOD stage/actor only
- **Required**: match submitter action/stage only

Typical domain patterns:
- `[('wf_current_node_id', '=', 'Task_Submit')]`
- `[('wf_current_node_id', '=', 'Task_HOD')]`
- `[('wf_current_node_id', '=', 'Task_Doctor')]`
- `[('wf_action_key', 'ilike', 'submit')]`
- `[('request_owner_id', '=', wf_actor_uid)]`

Combine with `&` / `|` in Advanced mode for full business logic.

## 11. Runtime Assignment Resolution Order (Actual Engine Flow)

At runtime, assignee resolution is:

1. Collect candidates by `assignment_mode` strategy.
2. For group rules, apply rule **record domain** (`link.domain`) first.
3. Then apply rule **user domain** (`link.user_domain`) per matched group.
4. Apply category/ACL eligibility checks (active, internal user, company, category access depending on category flag, model read access).
5. Apply delegation rules (out-of-office/delegate substitution).
6. Apply share overrides when enabled.
7. If still empty, apply `fallback_policy`.

Result:
- final assignees
- delegation map
- blocked state when no fallback user can be resolved and policy blocks

## 12. Approval Group Dialog (Create/Configure)

Fields:
- **Group Name**
- **Parent Group**
- **Department**
- **Users** (multi-select with search by name/login/email/employee code)

Optional node rule block in dialog:
- **Sequence**
- **User Filter Domain**
- **Record Domain**
- **Note**

## 13. Defaults and Validation Rules

- `assignment_mode`: `mixed`
- `completion_mode`: `any`
- `fallback_policy`: `route_admin_queue`
- `join_policy`: `all_of`
- `parallel_reject_policy`: `strict`
- `confidentiality_level`: `public`
- `twofa_method`: `email_otp`
- `approval_require_number`: minimum 1
- `join_policy = min_n` requires `join_min_n > 0`

## 14. Practical Configuration Recipes

### 14.1 Request Owner Approves First

- Node: `userTask`
- Assignment Mode: `request_owner`
- Completion Mode: `any`

### 14.2 HOD by Dynamic Path

- Assignment Mode: `domain`
- Assignment User Domain:
`[('id', '=', request.request_owner_id.employee_id.parent_id.user_id.id)]`

### 14.3 Exclude Self-Approval

- Use preset/domain:
`[('id', '!=', request_owner_id)]`

### 14.4 Notify Submitter + All Decided Approvers

- Node: `sendTask` or notification-capable node
- Notification Domain:
`[('id', 'in', notification_submitter_and_decided_user_ids)]`

### 14.5 Parallel Join (Any 2 of 3)

- Gateway join node
- Join Policy: `min_n`
- Join Min N: `2`

## 15. Troubleshooting

- **No approver resolved**:
  - check assignment mode
  - check approval group record domain
  - check group user domain
  - check fallback policy/user
  - check category/record access rights

- **Button not visible**:
  - check action `invisible_domain`
  - check action `domain`

- **2FA not triggering**:
  - verify `require_2fa = true`
  - validate `twofa_condition_domain`

- **Rule edits not saved**:
  - link/unlink saves immediately
  - sequence/domain/note needs **Save Rule Details**

## 16. Governance Recommendations

- Prefer presets + builder over manual raw domain typing.
- Keep Approval Groups reusable and linked from catalog.
- Use `mixed` mode for most business flows; reserve `domain` mode for advanced routing.
- Keep fallback policy explicit on critical nodes.
- Add description/notes for every non-trivial rule for future maintainers.
