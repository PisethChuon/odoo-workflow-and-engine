/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListRenderer } from "@web/views/list/list_renderer";
import { useService } from "@web/core/utils/hooks";

export class WorkflowApprovalRequestListRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.action = useService("action");
        this.orm = useService("orm");
    }

    async onCellClicked(record, column, ev) {
        const resModel = this.props?.list?.resModel || "";
        if (resModel !== "workflow.base.approval.request") {
            return super.onCellClicked(record, column, ev);
        }

        const ignoredClick = ev.target.closest(
            "button, a, input, textarea, select, .o_handle_cell, .o_list_record_selector"
        );
        if (ignoredClick) {
            return super.onCellClicked(record, column, ev);
        }

        if (!record?.resId) {
            return super.onCellClicked(record, column, ev);
        }

        try {
            const action = await this.orm.call(
                "workflow.base.approval.request",
                "action_open_child",
                [[record.resId]],
                { context: { wf_open_target: "current" } }
            );
            if (action && action.type) {
                return this.action.doAction(action);
            }
        } catch (error) {
            console.warn("workflow request list open-child fallback", error);
        }

        return super.onCellClicked(record, column, ev);
    }
}

export const WorkflowApprovalRequestListView = {
    ...listView,
    Renderer: WorkflowApprovalRequestListRenderer,
};

registry.category("views").add("workflow_approval_request_list", WorkflowApprovalRequestListView);
