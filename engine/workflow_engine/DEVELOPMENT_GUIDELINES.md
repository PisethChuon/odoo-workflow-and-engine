# Workflow Engine Development Guidelines (Odoo 19)

This guide is for contributors working on `engine/workflow_engine` and its integration with `engine/workflow_studio`.

Goal: make changes predictable so developers know exactly where to modify code for each feature.

## 1) Module Boundaries

- `workflow_engine` owns runtime execution, permissions, assignment, approval history, 2FA, field policies, and request UI widgets.
- `workflow_studio` owns BPMN editor UI, metadata design UX, and save/sync/import/export APIs for versions.
- Dependency direction must remain:
  - `workflow_engine -> workflow_studio` is not allowed as hard module dependency.
  - Keep runtime logic in `workflow_engine`.
  - Keep designer/editor logic in `workflow_studio`.

## 2) Code Map (Where Things Live)

### Runtime core (`workflow_engine/models`)

- Request header/state model:
  - `workflow_base_approval_request.py`
- Transition and assignment flow:
  - `approval_child_mixin.py`
- Approval rows, timeline labels, decision history:
  - `workflow_approval_approver.py`
- Runtime additive models and 2FA challenge:
  - `workflow_runtime_models.py`
- Runtime services:
  - `workflow_engine_services.py`
- Runtime integration bridge:
  - `workflow_runtime_integration.py`
- Category and version metadata:
  - `workflow_approval_category.py`
  - `approval_category_version.py`
  - `approval_category_version_meta.py`
- Zero-trust and runtime security extensions:
  - `workflow_security_and_meta_extensions.py`

### BPMN and parser (`workflow_engine/utils`)

- BPMN parsing and supported node/action extraction:
  - `bpmn_engine_parser.py`

### Views and XML (`workflow_engine/views`)

- Request form and approver tabs/lists:
  - `workflow_approval_base_request_views.xml`
- Category/version/meta forms:
  - `workflow_approval_category_views.xml`
- Runtime access/security tab extensions:
  - `workflow_runtime_security_views.xml`

### Frontend runtime widgets (`workflow_engine/static/src/web`)

- BPMN readonly widget and node popup:
  - `bpmn_button/bpmn_widget.js`, `.xml`, `.scss`
- Action buttons:
  - `approval_button/approval_button.js`
- Requestor import x2many bridge:
  - `import_button/requestor_import_o2m.js`, `.xml`
  - `import_button/requestor_excel_import.js`, `.xml`, `.scss`
- Runtime field-state patches:
  - `patches/wf_form_runtime_field_state.js`
  - `patches/wf_form_field_modifiers.js`
  - `patches/wf_form_fieldinfo_runtime_modifiers.js`

### Studio BPMN editor (`workflow_studio/static/src/client_action/bpmn_editor`)

- Sidebar component list and properties:
  - `bpmn_editor.js`
  - `bpmn_editor.xml`
  - `bpmn_editor.scss`

## 3) Feature-to-File Recipe

Use this mapping first before coding.

| Change type | Primary files | Secondary files |
|---|---|---|
| New category runtime toggle | `models/workflow_security_and_meta_extensions.py` | `views/workflow_runtime_security_views.xml`, tests |
| Request state/header behavior | `models/workflow_base_approval_request.py` | `views/workflow_approval_base_request_views.xml` |
| Rework/submission assignment correctness | `models/approval_child_mixin.py` | `models/workflow_approval_approver.py`, tests |
| From Activity / To Activity labels | `models/workflow_approval_approver.py` | `views/workflow_approval_base_request_views.xml` |
| Decision-only filtering in tabs/popup | `views/workflow_approval_base_request_views.xml` | `models/workflow_approval_approver.py` (`has_decision`) |
| Bus real-time mini refresh | `models/workflow_base_approval_request.py` | `models/workflow_approval_approver.py`, `static/src/web/bpmn_button/bpmn_widget.js` |
| Stage age calculation | `models/workflow_approval_approver.py` | `views/workflow_approval_base_request_views.xml` |
| New BPMN node support (engine) | `utils/bpmn_engine_parser.py` | `models/approval_category_version.py`, tests |
| New BPMN node in Studio panel | `workflow_studio/.../bpmn_editor.js` | `workflow_studio/.../bpmn_editor.xml`, parser sync |
| 2FA logic | `models/workflow_engine_services.py`, `models/workflow_runtime_models.py` | `static/src/web/confirm_wizard/*`, `static/src/web/twofa_dialog/*` |
| Access rule behavior | `models/workflow_security_and_meta_extensions.py` | `security/*.xml`, tests |
| Requestor/detail-line import wizard | `models/requestor_import_wizard.py`, form module wizard inherit | `views/requestor_import_wizard_views.xml`, x2many field XML, tests |

## 4) Runtime Flow Reference

Main execution path for approval actions:

1. UI button calls `action_do_transition` on child request model.
2. `approval_child_mixin.py` validates conditions and may open confirm/2FA dialog.
3. `_run_engine()` resolves current node and selected action.
4. `_approve()` writes decision row and status.
5. `_assign_dynamic_approvers_from_meta()` computes next assignees.
6. Request header fields and approver timeline recompute.
7. Optional bus notification pushes lightweight update for BPMN widget.

When fixing behavior, follow this chain in order. Do not patch only UI first.

## 5) Refactor Rules (Do and Do Not)

### Do

- Keep server as source of truth for transitions, permissions, and field rules.
- Add small, focused helper methods for repeated logic.
- Keep backward compatibility with existing `workflow.approval.approver` semantics unless migration is explicit.
- Update XML views and Python compute methods together when adding display fields.
- Add tests for every behavior change.

### Do not

- Do not trust client data for actor/node/action authorization.
- Do not put business transition logic into OWL components.
- Do not edit minified third-party libs under `static/lib` unless absolutely required.
- Do not bypass record rules/security checks using broad `sudo()` without reason.

## 6) Frontend Integration Rules

- If the change affects live request updates:
  - publish from Python (`bus.bus`),
  - subscribe in JS (`bus_service`),
  - keep payload minimal,
  - fetch authoritative snapshot via ORM RPC.
- For `wf_form` behavior:
  - server computes policy,
  - client only applies state map.
  - do not force `task_node_id=current_node_id` from JS in branch scenarios; let server resolve actor node.
  - never allow runtime map to downgrade static XML modifiers (`readonly="1"`, static `required`, static `invisible`).
  - preserve original arch modifiers in `record.activeFields` and layer runtime policy on top.

## 6.1) Sensitive Field Guardrails

- Sensitive field protection is zero-trust and must be server-side:
  - block writes to runtime `readonly` fields,
  - block writes to runtime `invisible` fields,
  - enforce runtime `required` fields.
- Client modifiers are UX only; server validation must be the final authority.
- For multi-branch approvals, evaluate field policy using the actor primary node (open approver row), not only request header `current_node_id`.

## 6.2) Studio UX Guardrails (Configuration)

- Prefer guided configuration over free-text input:
  - use domain builder dialogs for condition fields,
  - provide preset choices for common domains,
  - provide mapping templates for JSON fields.
- Keep selector-first UX for relational data:
  - many2one/many2many should default to dropdown/tag selectors,
  - avoid forcing users to type IDs/XMLIDs manually.
- Keep admin help visible in-place:
  - add short purpose/help blocks in property panels and key forms,
  - separate “effective runtime values” from “template/preset values” with clear labels.
- Do not change execution semantics when improving UX:
  - UI helpers must still save to the same metadata fields,
  - runtime behavior must remain driven by server models and services.

## 6.3) BPMN Preview Readability

- Flow preview must remain readable in both light and dark themes:
  - enforce robust text contrast for node labels and connection labels,
  - handle SVG text and foreignObject labels,
  - avoid relying on a single static color.
- Mobile readability is mandatory:
  - keep minimum practical label size and visible state markers,
  - avoid low-contrast pills/badges on dark backgrounds.
- “Current state” visualization should be visible to any user who can read the request, not only active approvers.

## 6.4) Requestor Import Wizard Usage

Use `workflow.requestor.import.wizard` when a workflow form needs to add many requestor/detail rows from either a user picker or an Excel template. This pattern is for detail/line models only. Do not store imported employee/item values on the workflow master request unless the business field belongs to the master.

### Standard business contract

- The saved request line is the audit source of truth.
- Store final text on the detail line, for example `x_employee_code`, `x_employee_name`, `x_department_name`, `x_position_name`, `x_section_name`, `x_item_name`, `x_item_type_name`, `x_role_name`, and `x_comment`.
- Do not persist helper `Many2one` fields such as employee/user/item/type/role on the saved detail line unless the business explicitly needs a live relation.
- Keep helper `Many2one` fields on the transient wizard. Selecting a user, employee, item, type, or role must copy display text into preview/output values.
- Excel import must not create users, employees, departments, items, or roles.
- For employee requestor import, `EMP.NO` lookup has priority. If the employee code exists in the database, use database code/name/department/position and ignore those Excel text values for that row. If the employee code does not exist, keep the Excel text values exactly as imported.

### Master form x2many wiring

Use `widget="requestor_import_o2m"` on the detail one2many field. This widget opens the modal without forcing an unsaved parent form save, applies returned rows locally, then requests one authoritative workflow runtime field-state refresh.

```xml
<field name="x_own_item_line_ids"
    string="Requested Items"
    widget="requestor_import_o2m"
    mode="list,kanban"
    invisible="'x_own_item_line_ids' in (invisible_fields or '')"
    readonly="not x_item_line_id or 'x_own_item_line_ids' in (readonly_fields or '') or is_finished"
    required="'x_own_item_line_ids' in (required_fields or '')"
    options="{
        'action_xmlid': 'your_module.action_requestor_import_wizard',
        'section_field': 'x_item_line_id',
        'button_string': 'Add'
    }">
    <list editable="bottom" create="false" delete="true" no_open="True">
        <field name="x_employee_code" readonly="1" force_save="1"/>
        <field name="x_employee_name" readonly="1" force_save="1"/>
        <field name="x_department_name" readonly="1" force_save="1"/>
        <field name="x_position_name" readonly="1" force_save="1"/>
        <field name="x_item_name" readonly="1" force_save="1"/>
        <field name="x_item_type_name" readonly="1" force_save="1"/>
        <field name="x_comment"/>
    </list>
    <kanban class="o_kanban_mobile" create="false">
        <field name="x_employee_code" force_save="1"/>
        <field name="x_employee_name" force_save="1"/>
        <field name="x_department_name" force_save="1"/>
        <field name="x_position_name" force_save="1"/>
        <templates>
            <t t-name="card" class="flex-row">
                <!-- Use native Odoo kanban card structure for mobile. -->
            </t>
        </templates>
    </kanban>
</field>
```

Important guardrails:

- Keep the workflow expressions on `invisible`, `readonly`, and `required`; do not replace them with widget-only logic.
- Keep `force_save="1"` on readonly audit text fields in the list and kanban declarations, otherwise locally inserted rows can save blank values.
- Keep `create="false"` and `no_open="True"` when rows should only be added through the import modal and only editable inline for allowed fields such as `x_comment`.
- Keep `delete="true"` if the current workflow stage allows the x2many field to be editable. Delete availability is still controlled by the field readonly state.
- Do not add a normal object/action button outside the x2many field for this flow; that can force parent save/reload and close the modal on unsaved forms.

### Wizard extension in a business module

In the business module, inherit the base wizard and add form-specific selectors. Override `_prepare_output_line_vals()` to copy selector display text into the saved line values.

```python
from odoo import _, fields, models
from odoo.exceptions import UserError


class MyRequestorImportWizard(models.TransientModel):
    _inherit = "workflow.requestor.import.wizard"

    x_my_section_id = fields.Many2one("x_my_item", string="Section", required=True)
    x_my_item_id = fields.Many2one("x_my_item", string="Item", required=True)
    x_comment = fields.Text(string="Comment")

    def _prepare_output_line_vals(self, line):
        vals = super()._prepare_output_line_vals(line)
        self.ensure_one()
        if not self.x_my_item_id:
            raise UserError(_("Please select Item before confirming."))
        vals.update({
            "x_section_name": self.x_my_section_id.display_name or "",
            "x_item_name": self.x_my_item_id.display_name or "",
            "x_comment": self.x_comment or "",
        })
        return vals
```

The base wizard already provides:

- `request_user_id` picker that appends a preview row and clears itself.
- `excel_file` / `excel_filename` fields for the Excel widget.
- preview `line_ids`.
- Excel header parsing for `EMP.NO`, `EMP.NAME`, `POSITION`, `DEPT.NAME`.
- duplicate prevention by employee code within the preview.
- `action_confirm_import()` returning `requestor_import_lines` with `noReload=True`.

### Wizard action and inherited view

Create a form-module action that opens the inherited wizard view in a modal:

```xml
<record id="action_requestor_import_wizard" model="ir.actions.act_window">
    <field name="name">Import Requestors</field>
    <field name="res_model">workflow.requestor.import.wizard</field>
    <field name="view_mode">form</field>
    <field name="view_id" ref="your_module.view_requestor_import_wizard_form"/>
    <field name="target">new</field>
</record>
```

Inherit `workflow_engine.view_workflow_requestor_import_wizard_form` and add form-specific fields above the base requestor picker/preview. Use `requestor_excel_import` on `excel_file`; do not rename it to `x_file` or use generic custom field names. Add `options="{'hide_on_mobile': True}"` when the Excel upload action should be hidden in compact mobile modals.

### Template file

- Put the form-specific sample template under the business module `static/` folder.
- The standard employee requestor template headers are `EMP.NO`, `EMP.NAME`, `POSITION`, `DEPT.NAME`.
- Link the template from the wizard footer with a normal Odoo button/link.
- If another form needs different headers, override `_excel_headers()` and the value builder methods in the wizard inherit, and add tests for the new lookup priority.

### Runtime stability rules

- The x2many import widget triggers `WF-RUNTIME-FIELD-STATE:REFRESH` before and after applying rows. Do not remove this handshake.
- The form runtime patch remains the authority for field visibility/readonly/required state. Do not force edit mode from the import widget.
- If the field disappears or becomes readonly after import, check the workflow runtime payload for the x2many field before changing widget code.
- If a section change should clear existing lines, use an explicit confirmation widget or server-side guarded automation; do not silently clear one2many rows in an onchange.

### Tests to add for each form

- The wizard returns text values only and no master relations.
- Existing `EMP.NO` uses database values over Excel values.
- Unknown `EMP.NO` keeps Excel text values and creates no master records.
- The x2many view has `widget="requestor_import_o2m"`, `mode="list,kanban"`, readonly `force_save` audit fields, and editable allowed fields only.
- The runtime field-state payload keeps the detail one2many visible/editable/required in the expected stage.
- Confirming the modal returns `noReload=True` and appends rows without forcing a parent form reload.

## 7) Tests to Update

Backend tests folder:
- `workflow_engine/tests/`

Common existing suites:
- `test_workflow_transitions.py`
- `test_workflow_assignment.py`
- `test_runtime_services.py`
- `test_access_rules.py`
- `test_node_popup_filters.py`
- `test_bpmn_supported_components.py`
- `test_workflow_field_render_logic.py`

Frontend tests folder:
- `workflow_engine/static/tests/`

When adding/altering BPMN support also validate:
- `static/tests/bpmn/exit_clearance_full.bpmn`

## 8) Local Validation Commands

From repo root `naga_odoo19`:

```bash
python odoo-core-19/odoo-bin -c config/naga-odoo-19.conf -d tmp-workflow-engine-dev -i workflow_engine --without-demo=True --stop-after-init --http-port=8170
python odoo-core-19/odoo-bin -c config/naga-odoo-19.conf -d tmp-workflow-engine-dev -u workflow_engine --stop-after-init --http-port=8170
```

If updating an existing shared DB and unrelated module errors appear, validate on a fresh temp DB as above.

## 9) Pull Request Checklist

- Feature mapped to correct files using Section 3.
- Python model changes include view updates where needed.
- Security and access implications reviewed.
- Backend tests added or updated.
- XML loads successfully and module upgrades cleanly.
- No unrelated refactor mixed in same PR.
- Changelog note added to `README.md` release notes when behavior changes.

## 10) Related Docs

- Architecture: `workflow_engine/README_ARCHITECTURE.md`
- Runtime + user operations: `workflow_engine/USER_MANUAL.md`
- Module overview and release notes: `workflow_engine/README.md`

## 11) BPMN Node Contract (Recommended Usage)

Use this table as the single source of truth when configuring BPMN nodes and metadata.

| BPMN node type | Primary purpose | Metadata fields to configure | Runtime behavior |
|---|---|---|---|
| `userTask` | Human approval/decision | `approval_group_link_ids`, `assignment_mode`, `meta_action_ids`, `field_ids` | Creates assignees and decision buttons |
| `intermediateEventMessage` | Approval button event (email/no-email action semantics) | `meta_action_ids`, `notification_recipient_ids` | Used as action transition step |
| `sendTask` | Notification node (CC/Broadcast) | `notification_recipient_ids`, `notification_recipient_domain`, `activity_type_ids` | Executes configured notification actions |
| `scriptTask` | Server-side automation | `activity_type_ids` | Executes workflow actions and server actions |
| `serviceTask` | Conditional router (single-path) | `meta_action_ids.domain` | Evaluates domains and selects next route |
| `inclusiveGateway` | Conditional multi-branch router | `meta_action_ids.domain` | Evaluates outgoing conditions (one or more true branches) |
| `parallelGateway` | Parallel split/join | `join_key`, `join_policy`, `parallel_reject_policy` | Coordinates join policies |

### Node picks for current business requirements

- Notification (email/SMS/Telegram): **use `sendTask`**.
  - Configure recipients in `notification_recipient_ids` (+ optional domain).
  - Configure channels in linked `workflow.approval.action` records via `activity_type_ids`.
- Server action execution: **use `scriptTask`**.
  - Add `workflow.approval.action` with `action_type = server_action`.
- Domain-based conditional routing with potential multiple true paths: **use `inclusiveGateway`**.
  - Put route domains on outgoing transitions (`meta_action.domain`).

## 12) Parser Refactor Rules (SOLID)

`utils/bpmn_engine_parser.py` must stay structured around the following responsibilities:

- **Single Responsibility**
  - classification helpers: `_classify_*`
  - flow extraction: `_map_sequence_flows`
  - metadata builders: `_build_meta_task`, `_build_meta_action`
- **Open/Closed**
  - add new BPMN variants by extending mapping dictionaries:
    - `TASK_NODE_TYPE_BY_TAG_SUFFIX`
    - `GATEWAY_NODE_TYPE_BY_TAG_SUFFIX`
    - `*_DEFINITION_TO_NODE_TYPE`
  - avoid rewriting core extraction loops for each new element.
- **Liskov/Interface**
  - keep public parser API stable:
    - `get_element_type`
    - `get_next_elements`
    - `get_meta_tasks_and_actions`
    - `get_action_type`
- **Dependency Inversion**
  - keep parser pure (XML in -> metadata out); runtime execution belongs in `models/`.

When adding a new node type, update in one PR:

1. Parser mapping dictionaries and tests.
2. Studio add-panel entry + label/purpose text.
3. Metadata sync (`sync_meta_from_bpmn`) if new fields are emitted.
4. Runtime handler (`approval_child_mixin.py`) only if node has execution side effects.
