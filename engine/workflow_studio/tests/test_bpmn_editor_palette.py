from pathlib import Path

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("ws_patch")
class TestWorkflowStudioBpmnEditorPalette(TransactionCase):
    def test_unsupported_nodes_are_hidden_from_add_components_sidebar(self):
        editor_path = Path(__file__).resolve().parents[1] / "static" / "src" / "client_action" / "bpmn_editor" / "bpmn_editor.js"
        source = editor_path.read_text(encoding="utf-8")

        self.assertNotIn('key: "receive_task"', source)
        self.assertNotIn('key: "event_based_gateway"', source)
        self.assertNotIn('key: "complex_gateway"', source)
        self.assertNotIn('key: "business_rule_task"', source)

    def test_runtime_guard_configuration_is_scoped_to_interactive_actions(self):
        template_path = (
            Path(__file__).resolve().parents[1]
            / "static"
            / "src"
            / "client_action"
            / "bpmn_editor"
            / "bpmn_editor.xml"
        )
        source = template_path.read_text(encoding="utf-8")

        self.assertIn("Show Validation Dialog", source)
        self.assertIn("Validation Message", source)
        self.assertIn("Legacy route domain detected", source)
        self.assertNotIn("Optional runtime domain for this route", source)

    def test_custom_dialogs_follow_enterprise_control_contract(self):
        static_root = Path(__file__).resolve().parents[1] / "static" / "src" / "client_action"
        template_source = (static_root / "bpmn_editor" / "bpmn_editor.xml").read_text(
            encoding="utf-8"
        )
        script_source = (static_root / "bpmn_editor" / "bpmn_editor.js").read_text(
            encoding="utf-8"
        )
        style_source = (static_root / "zz_workflow_studio_ui.scss").read_text(
            encoding="utf-8"
        )
        dialog_start = template_source.index('<t t-name="workflow_studio.NewVersionDialog">')
        dialog_source = template_source[dialog_start:]

        self.assertNotIn("<select", dialog_source)
        self.assertNotIn("Quick Setup", dialog_source)
        self.assertIn('<SelectMenu t-props="actionTypeSelectProps"/>', dialog_source)
        self.assertIn("o_field_x2many o_wfs_email_recipient_o2m", dialog_source)
        self.assertIn(
            '<MultiRecordSelector t-props="getEmailRecipientUsersProps(line_index)"/>',
            dialog_source,
        )
        self.assertIn("o_wfs_email_recipient_source_col", dialog_source)
        self.assertIn("input-group input-group-sm", dialog_source)
        self.assertIn(
            'togglerClass: "form-select form-select-sm o_wfs_dialog_select_toggler"',
            script_source,
        )
        self.assertIn("--wfs-primary: #aa9b3c;", style_source)
        self.assertIn(".btn.btn-primary", style_source)

    def test_runtime_reference_uses_a_dialog_and_tracks_engine_symbols(self):
        static_root = Path(__file__).resolve().parents[1] / "static" / "src" / "client_action"
        domain_template = (
            static_root
            / "components"
            / "workflow_domain_dialog"
            / "workflow_domain_dialog.xml"
        ).read_text(encoding="utf-8")
        domain_script = (
            static_root
            / "components"
            / "workflow_domain_dialog"
            / "workflow_domain_dialog.js"
        ).read_text(encoding="utf-8")
        studio_style = (static_root / "zz_workflow_studio_ui.scss").read_text(
            encoding="utf-8"
        )

        main_dialog_start = domain_template.index(
            '<t t-name="workflow_studio.WorkflowStudioDomainDialog">'
        )
        main_dialog_source = domain_template[main_dialog_start:]

        self.assertIn(
            '<t t-name="workflow_studio.RuntimeReferenceDialog">',
            domain_template,
        )
        self.assertIn("runtimeReferenceCategorySelectProps", domain_template)
        self.assertNotIn('id="o_wfs_runtime_reference"', main_dialog_source)
        self.assertIn(
            "this.dialog.add(WorkflowStudioRuntimeReferenceDialog",
            domain_script,
        )
        self.assertNotIn("scrollIntoView", domain_script)
        self.assertIn(
            ".btn-group > .btn:not(:first-child)",
            studio_style,
        )
        self.assertIn(
            ".btn-group > .btn:not(:last-child)",
            studio_style,
        )
        for symbol in (
            "all_approver_user_ids",
            "pending_approver_user_ids",
            "actual_user_id",
            "delegated_from_user_id",
            "wf_action_key",
            "wf_actor_is_hod",
        ):
            self.assertIn(symbol, domain_script)

    def test_line_item_manual_path_uses_enterprise_form_control(self):
        static_root = Path(__file__).resolve().parents[1] / "static" / "src" / "client_action"
        component_root = static_root / "components" / "workflow_domain_dialog"
        template_source = (component_root / "workflow_domain_dialog.xml").read_text(
            encoding="utf-8"
        )
        style_source = (component_root / "workflow_domain_dialog.scss").read_text(
            encoding="utf-8"
        )
        path_style_start = style_source.index(".o_wfs_runtime_path_manual {")
        path_style_end = style_source.index("}", path_style_start)
        path_style = style_source[path_style_start:path_style_end]

        self.assertIn(
            'class="o_input form-control o_wfs_runtime_path_manual"',
            template_source,
        )
        self.assertIn("font-family:", path_style)
        self.assertNotIn("background:", path_style)
        self.assertNotIn("border-style:", path_style)
        self.assertNotIn("margin-top:", path_style)

    def test_dynamic_value_builder_supports_presence_operators(self):
        static_root = Path(__file__).resolve().parents[1] / "static" / "src" / "client_action"
        component_root = static_root / "components" / "workflow_domain_dialog"
        script_source = (component_root / "workflow_domain_dialog.js").read_text(
            encoding="utf-8"
        )
        template_source = (component_root / "workflow_domain_dialog.xml").read_text(
            encoding="utf-8"
        )

        self.assertIn('{value: "is_set", label: _t("is set")}', script_source)
        self.assertIn(
            '{value: "is_not_set", label: _t("is not set")}',
            script_source,
        )
        self.assertIn("export function buildWorkflowRuntimeClause", script_source)
        self.assertIn(
            'return `[(${JSON.stringify(normalizedFieldName)}, "!=", False)]`;',
            script_source,
        )
        self.assertIn(
            'return `[(${JSON.stringify(normalizedFieldName)}, "=", False)]`;',
            script_source,
        )
        self.assertIn('t-if="runtimeOperatorUsesValue"', template_source)
        self.assertIn(
            "Presence checks do not require a runtime value.",
            template_source,
        )

    def test_auto_action_schedule_uses_enterprise_sidebar_controls(self):
        static_root = Path(__file__).resolve().parents[1] / "static" / "src" / "client_action"
        template_source = (static_root / "bpmn_editor" / "bpmn_editor.xml").read_text(
            encoding="utf-8"
        )
        section_start = template_source.index('<t t-if="isAutoFlowAction">')
        section_end = template_source.index(
            '<t t-if="showInteractiveActionAppearanceSection">',
            section_start,
        )
        section_source = template_source[section_start:section_end]

        self.assertIn('class="o_wfs_automation_schedule"', section_source)
        self.assertNotIn("o_web_studio_bpmn_meta_row", section_source)
        self.assertGreaterEqual(section_source.count('class="form-select'), 5)
        self.assertGreaterEqual(section_source.count('class="o_input form-control'), 5)
        self.assertIn(
            'class="input-group o_wfs_automation_interval_control"',
            section_source,
        )
        self.assertRegex(
            section_source,
            r'id="o_wfs_action_automation_recurring"\s+'
            r'class="form-check-input"',
        )
        self.assertIn(
            'for="o_wfs_action_automation_recurring"',
            section_source,
        )
        self.assertIn("onActionAutomationTriggerModeChange", section_source)
        self.assertIn("onActionAutomationReminderPresetChange", section_source)
        self.assertNotIn("style=", section_source)

    def test_large_meta_field_sets_move_from_sidebar_to_manager_dialog(self):
        static_root = Path(__file__).resolve().parents[1] / "static" / "src" / "client_action"
        editor_script = (static_root / "bpmn_editor" / "bpmn_editor.js").read_text(
            encoding="utf-8"
        )
        editor_template = (static_root / "bpmn_editor" / "bpmn_editor.xml").read_text(
            encoding="utf-8"
        )

        self.assertIn("const META_FIELD_INLINE_LIMIT = 5;", editor_script)
        self.assertIn(
            "this.state.metaFieldRows || []).length > META_FIELD_INLINE_LIMIT",
            editor_script,
        )
        self.assertIn('t-if="usesMetaFieldManagerDialog"', editor_template)
        self.assertIn(
            '<t t-name="workflow_studio.MetaFieldManagerDialog">',
            editor_template,
        )
        self.assertIn("o_wfs_meta_manager_cards", editor_template)
        manager_start = editor_template.index(
            '<t t-name="workflow_studio.MetaFieldManagerDialog">'
        )
        manager_end = editor_template.index(
            '<t t-name="workflow_studio.CopyMetaFieldDialog">',
            manager_start,
        )
        manager_source = editor_template[manager_start:manager_end]
        footer_start = manager_source.index('<t t-set-slot="footer">')
        manager_toolbar = manager_source[:footer_start]
        manager_footer = manager_source[footer_start:]
        self.assertNotIn("addMetaFieldRow", manager_toolbar)
        self.assertNotIn("copyMetaFieldRows", manager_toolbar)
        self.assertIn("addMetaFieldRow", manager_footer)
        self.assertIn("copyMetaFieldRows", manager_footer)

    def test_task_notification_booleans_use_native_checkboxes(self):
        template_path = (
            Path(__file__).resolve().parents[1]
            / "static"
            / "src"
            / "client_action"
            / "bpmn_editor"
            / "bpmn_editor.xml"
        )
        source = template_path.read_text(encoding="utf-8")

        for checkbox_id in (
            "o_wfs_reset_request_to_submit",
            "o_wfs_push_notification_to_actor",
            "o_wfs_notify_request_owner_email",
            "o_wfs_notify_request_creator_email",
        ):
            self.assertIn(
                f'id="{checkbox_id}" class="form-check-input" type="checkbox"',
                source,
            )
            self.assertIn(f'for="{checkbox_id}"', source)
            input_offset = source.index(f'id="{checkbox_id}"')
            self.assertIn(
                '<div class="o_web_studio_sidebar_checkbox d-flex">',
                source[max(0, input_offset - 220) : input_offset],
            )
        self.assertNotIn('class="form-check form-switch"', source)
        self.assertNotIn('role="switch"', source)
        self.assertIn(
            "entering this task resets the request to To Submit instead of "
            "Waiting Approval",
            source,
        )

    def test_destructive_studio_actions_use_danger_confirmations(self):
        editor_path = (
            Path(__file__).resolve().parents[1]
            / "static"
            / "src"
            / "client_action"
            / "bpmn_editor"
            / "bpmn_editor.js"
        )
        source = editor_path.read_text(encoding="utf-8")

        for title in (
            "Remove Notification Channel?",
            "Remove Field Rule?",
            "Unlink Approval Group?",
            "Remove Approval Group Rule?",
            "Remove Workflow Mapping?",
        ):
            self.assertIn(f'title: _t("{title}")', source)
        self.assertGreaterEqual(source.count('confirmClass: "btn-danger"'), 6)
        self.assertIn("This cannot be undone.", source)

    def test_approval_group_members_use_native_avatar_selector_layout(self):
        static_root = Path(__file__).resolve().parents[1] / "static" / "src" / "client_action"
        template_source = (static_root / "bpmn_editor" / "bpmn_editor.xml").read_text(
            encoding="utf-8"
        )
        script_source = (static_root / "bpmn_editor" / "bpmn_editor.js").read_text(
            encoding="utf-8"
        )
        style_source = (static_root / "zz_workflow_studio_ui.scss").read_text(
            encoding="utf-8"
        )
        dialog_start = template_source.index(
            '<t t-name="workflow_studio.CreateApprovalGroupDialog">'
        )
        dialog_end = template_source.index(
            '<t t-name="workflow_studio.MetaFieldDialog">',
            dialog_start,
        )
        dialog_source = template_source[dialog_start:dialog_end]

        self.assertIn(
            'class="o_field_widget o_wfs_approval_group_user_picker"',
            dialog_source,
        )
        self.assertNotIn(
            "o_field_many2many_tags o_wfs_approval_group_user_picker",
            dialog_source,
        )
        self.assertIn('placeholder: _t("Select members...")', script_source)
        self.assertIn(
            ".o_multi_record_selector .o_record_autocomplete_with_caret",
            style_source,
        )
        self.assertIn(
            "&:has(.modal-content.o_wfs_approval_group_dialog) "
            ".o-autocomplete--dropdown-menu",
            style_source,
        )

    def test_service_executor_actions_use_native_many2many_tags(self):
        static_root = Path(__file__).resolve().parents[1] / "static" / "src" / "client_action"
        template_source = (static_root / "bpmn_editor" / "bpmn_editor.xml").read_text(
            encoding="utf-8"
        )
        script_source = (static_root / "bpmn_editor" / "bpmn_editor.js").read_text(
            encoding="utf-8"
        )
        style_source = (static_root / "zz_workflow_studio_ui.scss").read_text(
            encoding="utf-8"
        )

        self.assertNotIn(
            '<select multiple="multiple" t-on-change="onTaskWorkflowActionsChange">',
            template_source,
        )
        self.assertIn(
            '<MultiRecordSelector t-props="taskWorkflowActionsProps"/>',
            template_source,
        )
        self.assertIn(
            'return ["server_action"];',
            script_source,
        )
        self.assertIn(
            "Every selected action runs when this executor is reached.",
            script_source,
        )
        self.assertIn(
            ".o_wfs_workflow_action_picker",
            style_source,
        )

    def test_dark_bpmn_context_pad_keeps_action_icons_readable(self):
        style_path = (
            Path(__file__).resolve().parents[1]
            / "static"
            / "src"
            / "client_action"
            / "zz_workflow_studio_ui.scss"
        )
        style_source = style_path.read_text(encoding="utf-8")
        dark_theme_start = style_source.index("@mixin wfs-dark-theme")
        dark_theme_end = style_source.index(
            "// The Studio shell loads a dedicated dark asset bundle",
            dark_theme_start,
        )
        dark_theme_source = style_source[dark_theme_start:dark_theme_end]

        self.assertIn(".djs-context-pad .entry {", dark_theme_source)
        self.assertIn(
            "background-color: var(--wfs-surface-muted) !important;",
            dark_theme_source,
        )
        self.assertIn("color: var(--wfs-text) !important;", dark_theme_source)
        self.assertIn(".djs-context-pad .entry::before", dark_theme_source)
        self.assertIn("color: inherit !important;", dark_theme_source)
        self.assertIn(".djs-context-pad .entry:hover", dark_theme_source)
        self.assertIn("color: var(--wfs-accent-hover) !important;", dark_theme_source)

    def test_dark_studio_typography_uses_odoo_contrast_levels(self):
        style_path = (
            Path(__file__).resolve().parents[1]
            / "static"
            / "src"
            / "client_action"
            / "zz_workflow_studio_ui.scss"
        )
        style_source = style_path.read_text(encoding="utf-8")
        dark_theme_start = style_source.index("@mixin wfs-dark-theme")
        dark_theme_end = style_source.index(
            "// The Studio shell loads a dedicated dark asset bundle",
            dark_theme_start,
        )
        dark_theme_source = style_source[dark_theme_start:dark_theme_end]

        self.assertIn("--wfs-text: #dee2e6;", dark_theme_source)
        self.assertIn("--wfs-text-muted: #adb2ba;", dark_theme_source)
        self.assertIn("--wfs-text-faint: #858b93;", dark_theme_source)
        self.assertIn("--wfs-dialog-text: #dee2e6;", dark_theme_source)
        self.assertIn("--wfs-dialog-text-muted: #adb2ba;", dark_theme_source)
        self.assertNotIn("--wfs-text: #f0f1f3;", dark_theme_source)
        self.assertIn("fill: var(--wfs-text) !important;", dark_theme_source)

    def test_approval_group_link_dialog_uses_enterprise_form_controls(self):
        template_path = (
            Path(__file__).resolve().parents[1]
            / "static"
            / "src"
            / "client_action"
            / "bpmn_editor"
            / "bpmn_editor.xml"
        )
        source = template_path.read_text(encoding="utf-8")
        dialog_start = source.index(
            '<t t-name="workflow_studio.LinkApprovalGroupDialog">'
        )
        dialog_end = source.index(
            '<t t-name="workflow_studio.MetaFieldDialog">',
            dialog_start,
        )
        dialog_source = source[dialog_start:dialog_end]

        self.assertIn(
            'contentClass="\'o_wfs_approval_group_link_dialog\'"',
            dialog_source,
        )
        self.assertNotIn("o_wfs_approval_group_panel card", dialog_source)
        self.assertIn('class="o_input form-control"', dialog_source)
        self.assertIn('class="input-group"', dialog_source)
        self.assertIn("col-form-label", dialog_source)

    def test_notification_channel_create_action_stays_in_dialog_footer(self):
        static_root = Path(__file__).resolve().parents[1] / "static" / "src" / "client_action"
        template_source = (static_root / "bpmn_editor" / "bpmn_editor.xml").read_text(
            encoding="utf-8"
        )
        style_source = (static_root / "zz_workflow_studio_ui.scss").read_text(
            encoding="utf-8"
        )
        dialog_start = template_source.index(
            '<t t-name="workflow_studio.NotificationChannelBrowserDialog">'
        )
        dialog_end = template_source.index(
            '<t t-name="workflow_studio.ApprovalGroupBrowserDialog">',
            dialog_start,
        )
        dialog_source = template_source[dialog_start:dialog_end]
        footer_source = dialog_source[dialog_source.index('<t t-set-slot="footer">') :]

        self.assertEqual(
            dialog_source.count("o_wfs_notification_channel_create_btn"),
            1,
        )
        self.assertIn("o_wfs_notification_channel_create_btn", footer_source)
        self.assertIn(
            ".modal-content.o_wfs_notification_channel_browser_dialog",
            style_source,
        )
        self.assertIn(
            ".o_wfs_approval_group_browser_node",
            style_source,
        )
        self.assertIn("color: var(--wfs-text) !important;", style_source)

    def test_approval_group_create_action_and_dark_text_follow_dialog_contract(self):
        static_root = Path(__file__).resolve().parents[1] / "static" / "src" / "client_action"
        template_source = (static_root / "bpmn_editor" / "bpmn_editor.xml").read_text(
            encoding="utf-8"
        )
        style_source = (static_root / "zz_workflow_studio_ui.scss").read_text(
            encoding="utf-8"
        )
        dialog_start = template_source.index(
            '<t t-name="workflow_studio.ApprovalGroupBrowserDialog">'
        )
        dialog_end = template_source.index(
            '<t t-name="workflow_studio.CreateApprovalGroupDialog">',
            dialog_start,
        )
        dialog_source = template_source[dialog_start:dialog_end]
        footer_source = dialog_source[dialog_source.index('<t t-set-slot="footer">') :]
        toolbar_source = dialog_source[: dialog_source.index('<t t-set-slot="footer">')]

        self.assertEqual(
            dialog_source.count("o_wfs_approval_group_browser_create_btn"),
            1,
        )
        self.assertIn("o_wfs_approval_group_browser_create_btn", footer_source)
        self.assertNotIn("o_wfs_approval_group_browser_create_btn", toolbar_source)
        self.assertLess(
            footer_source.index("o_wfs_approval_group_browser_create_btn"),
            footer_source.index(">Close</button>"),
        )
        self.assertIn(
            ".modal-content.o_wfs_approval_group_browser_dialog",
            style_source,
        )
        self.assertIn(
            ".o_wfs_approval_group_browser_summary_eyebrow",
            style_source,
        )
        self.assertIn(
            ".o_wfs_approval_group_browser_summary_text",
            style_source,
        )
