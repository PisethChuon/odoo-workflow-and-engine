import { registry } from "@web/core/registry";
import { LazyComponent } from "@web/core/assets";
import { cookie } from "@web/core/browser/cookie";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { _t } from "@web/core/l10n/translation";

import { Component, xml } from "@odoo/owl";

class StudioActionLoader extends Component {
    static components = { LazyComponent };
    static template = xml`
        <LazyComponent bundle="bundle" Component="'StudioClientAction'" props="props"/>
    `;
    static props = {
        ...standardActionServiceProps,
        props: { type: Object, optional: true },
        Component: { type: Function, optional: true },
    };
    setup() {
        this.bundle =
            cookie.get("color_scheme") === "dark"
                ? "workflow_studio.studio_assets_dark"
                : "workflow_studio.studio_assets";
    }
}
registry.category("actions").add("workflow_studio", StudioActionLoader);

/**
 * Keep a resilient client action entrypoint for server actions that open
 * workflow studio from category/version forms.
 * This fallback is intentionally registered in the same module as the
 * "studio" client action loader so the key is available as soon as studio
 * assets are loaded.
 */
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
