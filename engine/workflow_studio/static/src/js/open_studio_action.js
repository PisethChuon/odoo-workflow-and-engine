/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

async function openWorkflowStudioFromCategory(env, action) {
    const params = action.params || {};
    if (!params.model) {
        throw new Error("workflow_studio.open_workflow_studio requires params.model");
    }

    const targetAction = {
        type: "ir.actions.act_window",
        name: params.name || _t("Workflow Studio"),
        res_model: params.model,
        view_mode: "form",
        views: [[params.view_id || false, "form"]],
        context: params.context || {},
    };

    if (params.res_id) {
        targetAction.res_id = params.res_id;
    }

    await env.services.workflow_studio.open(env.services.workflow_studio.MODES.EDITOR, targetAction);
    if (params.editor_tab) {
        env.services.workflow_studio.setParams({ editorTab: params.editor_tab });
    }
}

registry
    .category("actions")
    .add("workflow_studio.open_workflow_studio", openWorkflowStudioFromCategory, {
        force: true,
    });
