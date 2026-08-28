/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ControlPanel } from "@web/search/control_panel/control_panel";

patch(ControlPanel.prototype, {
    async switchView(viewType, newWindow) {
        const globalContext = this.env.searchModel?.globalContext || {};
        const isNodePopup =
            !newWindow &&
            Boolean(globalContext.wf_allow_dialog_view_switch) &&
            Boolean(globalContext.wf_node_popup_request_id) &&
            Boolean(globalContext.wf_node_popup_node_id);

        if (!isNodePopup) {
            return super.switchView(...arguments);
        }

        if (this.env.config?.viewType === viewType) {
            return;
        }

        try {
            const popupAction = await this.orm.call(
                "workflow.approval.approver",
                "action_open_node_approvers",
                [
                    globalContext.wf_node_popup_request_id,
                    globalContext.wf_node_popup_node_id,
                    globalContext.wf_node_popup_node_name || false,
                    Boolean(globalContext.wf_node_popup_is_current_node),
                    viewType,
                ]
            );
            if (popupAction) {
                await this.actionService.doAction(popupAction, { viewType });
            }
        } catch (error) {
            console.warn("Workflow node popup: dialog view switch failed.", error);
        }
    },
});
