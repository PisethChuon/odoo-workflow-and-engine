# Workflow Studio

Workflow Studio is the Odoo 19 graphical editor for configuring workflow
versions, BPMN nodes, actions, assignment, routing, notifications, field rules,
and runtime conditions.

This document records the July 2026 UI/UX revision so later changes can reuse
the same design and behavior contracts without relying on screenshots or
conversation history.

## Scope and behavior contract

The revision modernizes presentation and interaction only unless a functional
change is explicitly listed in this document.

- Preserve all existing models, field names, RPC methods, payload shapes,
  callbacks, save behavior, and BPMN runtime behavior.
- Prefer Odoo 19 Enterprise controls and OWL components over custom controls.
- Keep desktop, mobile, light-theme, and dark-theme behavior consistent.
- Keep destructive operations behind an Odoo `ConfirmationDialog` when they
  cannot be restored with Studio Undo/Redo.
- Do not move validation exclusively to the client. Runtime and action-time
  validation remain authoritative in `workflow_engine`.

## Visual system

The Studio presentation layer is centralized in:

`static/src/client_action/zz_workflow_studio_ui.scss`

The stylesheet intentionally contains presentation only. Component behavior
stays in the owning JavaScript and XML files.

### Theme tokens

- Primary Studio action color: `#aa9b3c`
- Light primary hover: `#918431`
- Dark primary hover: `#c0b252`
- Odoo accent color is retained for secondary selection and Studio identity.
- Semantic success, warning, information, and danger colors have separate
  light and dark tokens.
- Text uses primary, muted, and faint levels instead of pure white in dark
  mode. The dark primary text is `#dee2e6`.
- Surfaces, borders, shadows, focus rings, and radii use `--wfs-*` variables.

All `.btn-primary` controls inside `body.o_in_workflow_studio` inherit the
Studio primary color. Danger actions continue to use Odoo danger styling.

### Odoo 19 control rules

- Use `SelectMenu` for dialog dropdowns that need Odoo menu spacing, keyboard
  behavior, and dark-mode support.
- Use `MultiRecordSelector` inside `o_field_many2many_tags` for multi-record
  fields, including avatars and tags.
- Use `AutoComplete` for searchable node references.
- Use `ModelFieldSelector` for model-aware technical field paths.
- Use `form-control`, `form-select`, `input-group`, `form-check`, and Odoo
  button variants for standard form controls.
- Native checkboxes use `form-check-input` and `form-check-label`; boolean
  settings are not presented as custom toggle switches.
- Related controls use consistent vertical gaps. Button groups remove the
  radius between adjacent buttons while keeping the outer group radius.
- Dialog actions belong in the Odoo modal footer, not in a floating header
  toolbar.

## Implemented editor UI

### Studio shell and node editor

- Added a clear Workflow Studio navbar identity while preserving Odoo navbar
  layout and menu behavior.
- Standardized the top toolbar, sidebar width, property spacing, section
  hierarchy, canvas surface, node selection, and contextual BPMN action
  palette.
- Corrected selected-node contextual action colors in dark mode.
- Reduced excessive dark-mode text brightness and introduced muted/faint text
  levels for labels, hints, paths, and metadata.
- Kept compact controls responsive as the sidebar narrows.
- Styled Outgoing Actions as a connected button group with spacing from
  surrounding sections.

### Task properties

- Assignment and routing controls use consistent Odoo field spacing.
- User, group, approval-group, and notification-recipient multi-selection use
  many2many tag controls instead of visually ambiguous list boxes.
- Service tasks label their multi-selection as `Server Actions`.
  `MultiRecordSelector` is intentional because a service task can reference
  multiple actions.
- Notification tasks show a compact configured-channel summary instead of
  rendering every channel in the property sidebar.
- Approval tasks show a compact linked-group summary instead of rendering the
  complete group catalog in the property sidebar.
- Meta field rules stay inline up to five rows. More than five rows switch to
  the searchable Meta Field Rules manager.
- Automation Schedule fields use consistent select/input sizing and explanatory
  text for trigger mode, frequency, interval, recurrence, and conditions.
- `Reset Request To Submit On Entry` includes help explaining that entering the
  task returns the request to `To Submit` for rework or resubmission.
- Push and email notification booleans use the same native checkbox pattern and
  retain their existing default/value semantics.

## Implemented dialogs

All dialogs use Odoo `Dialog`, standard header/body/footer structure, Odoo
button ordering, responsive sizes, and theme-aware surfaces.

### Notification channels

`Manage Notification Channels` provides:

- Current-node summary and configured/total counts.
- Searchable configured-channel cards.
- Configure and Remove from Node actions.
- Searchable reusable Channel Catalog.
- Add an existing channel to the selected node.
- `New Channel` in the modal footer.
- Channel configuration in a dedicated dialog, including channel type, name,
  email template, recipients, server action, webhook/message settings, and
  optional request domain.
- Email recipients rendered as an Odoo one2many-style table with Header,
  Source, Recipient Configuration, row removal, and `Add a line`.
- Recipient source controls for direct addresses, users, approval groups, Odoo
  groups, workflow-node users, and domains.

Removing a channel from a node requires confirmation. It unlinks the channel
from that node but does not delete the reusable channel.

### Approval groups

`Manage Approval Groups` provides:

- Current-node summary and linked/total counts.
- Search by hierarchy path, department, or member.
- All, Linked, and Remaining views.
- Routing-focus filters for blank and `[]` user/record domains.
- Linked-first catalog cards with department, members, routing warnings, and
  status.
- Link & Configure, Rule Settings, Edit Group, and Unlink actions.
- `Add Approval Group` in the modal footer.
- Dedicated add/edit dialogs with Odoo form controls and many2many member tags.
- Dedicated routing-rule configuration for sequence, user filter domain,
  record domain, presets, and note.

Unlinking a group or removing its routing rule requires confirmation because
the node-specific sequence, domains, and note cannot be restored automatically.

### Meta field rules

`Meta Field Rules` provides:

- Search by field label, technical name, type, or rule.
- Responsive field cards showing visibility, required, readonly, action, and
  condition metadata.
- Card selection to edit a rule.
- Confirmed removal for irreversible rule deletion.
- `Add Field Rule`, `Copy`, and `Close` actions in the modal footer.
- A step-based rule editor for fields, rule types, conditions, and optional
  action limits.
- A copy dialog for selecting a source node and choosing field rules.

The manager is used automatically when more than five field rules are
configured. Five or fewer rules retain the compact inline property display.

### Workflow/server action configuration

The action dialog uses Odoo controls for action type, name, templates, server
actions, message/webhook settings, recipient rows, code, and request domain.
Single-choice values use `SelectMenu`; multi-record values use tag selectors.

### Destructive action confirmations

Odoo `ConfirmationDialog` is used for:

- Delete Workflow Version
- Remove Notification Channel
- Remove Field Rule
- Unlink Approval Group
- Remove Approval Group Rule
- Remove Workflow Mapping

Confirmation copy identifies what will be discarded and whether the operation
cannot be undone.

## Domain builder

The shared domain dialog supports request, assignment, routing, 2FA, action
visibility, field modifier, recipient, and automation contexts.

### UI structure

- Target model and context help.
- Quick presets with connected Add AND, Add OR, and Replace modes.
- Odoo simple `DomainSelector` and advanced expression modes.
- Runtime-value callout with `Browse Symbols` and `Build Dynamic Value`.
- Runtime symbols in a separate searchable dialog to avoid making the main
  domain dialog excessively tall.
- Workflow activity/action clause builder.
- Line Item Conditions.
- Actor and business-scenario helpers where supported.
- Technical details and generated expressions.
- Confirm/Cancel actions in the Odoo footer.

### Preset semantics

- Generic Odoo domains use `[]` for an unconditional match.
- Routing presets use explicit leaf domains:
  - Always: `[(1, '=', 1)]`
  - Never: `[(0, '=', 1)]`
- The explicit routing values distinguish intentional Always/Never routing
  from blank or legacy `[]` routing that the approval-group audit filters flag
  for review.
- Presets can replace the current expression or combine with AND/OR.
- Presets containing example fields must be adapted to the target request
  model before deployment.

### Dynamic values

The Dynamic Value Builder supports standard comparison operators plus:

- `is set`
- `is not set`

Presence operators do not require a comparison value. The builder emits the
corresponding false/non-false domain clause.

### Line Item Conditions

Line Item Conditions provide model-aware controls for:

- One2many/many2many line relation.
- At least one line matches.
- Every existing line matches.
- Line list is not empty.
- Line list is empty.
- Field on each line.
- Comparison operator and optional comparison value.

Generated expressions use:

- `wf_any(relation_path, line_domain)`
- `wf_all(relation_path, line_domain)`

The backend implementations are in
`workflow_engine/models/workflow_engine_services.py`.

Technical path rules:

- Prefer `ModelFieldSelector` over manual entry.
- Dotted paths are valid for traversing related fields.
- For a many2one record ID comparison, use the field itself, such as
  `x_clinic_id`; do not append `.id`.
- Manual technical paths are normalized before expression generation.

## Mobile Preview Flow

The runtime `Preview Flow` dialog is owned by `workflow_engine`, not
`workflow_studio`.

On screens up to 767 px:

- Only Preview Flow changes from a regular Odoo dialog to a bottom sheet.
- The sheet height is `82dvh`, with `92dvh` for very short screens.
- The sheet has rounded top corners, a drag-handle indicator, compact aligned
  header, horizontally scrollable context/legend rows, and safe-area padding.
- Opening uses a GPU-friendly bottom-to-top transform animation:
  `420ms cubic-bezier(0.22, 1, 0.36, 1)`.
- `prefers-reduced-motion` disables the animation.
- The footer Close button is full width.
- The BPMN canvas keeps pan, zoom, fit, node inspection, and runtime status
  behavior unchanged.
- Light and dark themes have dedicated canvas, panel, border, text, status, and
  button colors.

The implementation is in:

- `workflow_engine/static/src/web/bpmn_button/bpmn_dialog.js`
- `workflow_engine/static/src/web/bpmn_button/bpmn_dialog.xml`
- `workflow_engine/static/src/web/bpmn_button/bpmn_dialog.scss`

## Main source map

- Editor state and dialog behavior:
  `static/src/client_action/bpmn_editor/bpmn_editor.js`
- Editor templates and property controls:
  `static/src/client_action/bpmn_editor/bpmn_editor.xml`
- Editor-specific component styles:
  `static/src/client_action/bpmn_editor/bpmn_editor.scss`
- Shared Studio visual system:
  `static/src/client_action/zz_workflow_studio_ui.scss`
- Domain builder behavior:
  `static/src/client_action/components/workflow_domain_dialog/workflow_domain_dialog.js`
- Domain builder templates:
  `static/src/client_action/components/workflow_domain_dialog/workflow_domain_dialog.xml`
- Domain builder styles:
  `static/src/client_action/components/workflow_domain_dialog/workflow_domain_dialog.scss`
- Python UI contract tests:
  `tests/test_bpmn_editor_palette.py`
- OWL domain-dialog tests:
  `static/tests/workflow_domain_dialog.test.js`

## Regression commands

Run module suites sequentially to avoid PostgreSQL lock conflicts. These
commands upgrade the named module in the selected database, so use a local or
cloned preproduction database rather than a live shared database. Use a free
HTTP port and do not pass `--no-http`: `workflow_engine` and `workflow_studio`
contain `HttpCase` tests that must be served by the test process itself.

From `odoo-develop/core-odoo`:

```powershell
uv run python odoo-bin -c ../config/noc-prod.conf -d <database> -u workflow_engine --http-port=<free_port> --test-enable --test-tags /workflow_engine --stop-after-init

uv run python odoo-bin -c ../config/noc-prod.conf -d <database> -u workflow_studio --http-port=<free_port> --test-enable --test-tags /workflow_studio --stop-after-init

uv run python odoo-bin -c ../config/noc-prod.conf -d <database> -u dashboard_ng --http-port=<free_port> --test-enable --test-tags /dashboard_ng --stop-after-init

uv run python odoo-bin -c ../config/noc-prod.conf -d <database> -u medical_request --no-http --test-enable --test-tags /medical_request --stop-after-init
```

For the focused Workflow Studio BPMN backend suite:

```powershell
uv run python odoo-bin -c ../config/workflow-v19.conf -d workflow-v19 -u workflow_studio --http-port=<free_port> --test-enable --test-tags /workflow_studio:TestWorkflowStudioBpmn --stop-after-init
```

## Validation baseline

Database: `preprod-local-3`  
Date: 2026-07-23

- `workflow_engine`: 0 failures, 0 errors of 537 loaded tests.
- `workflow_studio`: 0 failures, 0 errors of 414 loaded tests.
- `dashboard_ng`: 0 failures, 0 errors of 49 loaded tests.
- `medical_request`: 0 failures, 0 errors of 23 loaded tests.
- MTF/workflow deploy gate: 0 failures, 0 errors of 11 focused tests.

The suites ran sequentially on isolated HTTP port `8073`. An earlier run used
`--no-http` while another Odoo server owned port `8069`; the 2FA `HttpCase`
requests were served by that external process and incorrectly reported
`SessionExpiredException`. The isolated rerun passed all seven mobile 2FA
endpoint tests. The deploy gate now enforces its expected test count so stale
selectors cannot produce a misleading green result.

## Review checklist

Before merging later UI changes:

- Confirm no model, field, RPC, payload, callback, or BPMN behavior changed
  unintentionally.
- Check standard, hover, focus, disabled, validation, and destructive states.
- Check desktop and mobile layouts.
- Check light and dark themes.
- Check keyboard navigation and visible focus.
- Check long labels, many records, empty states, and large catalogs.
- Verify modal actions remain in the footer.
- Verify irreversible actions require confirmation.
- Run `workflow_engine`, `workflow_studio`, and affected integration suites.
