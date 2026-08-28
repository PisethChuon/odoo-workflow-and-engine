/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";

patch(ListRenderer.prototype, {
    async onCellClicked(record, column, ev) {
        const resModel = this.props?.list?.resModel || "";
        if (resModel !== "workflow.base.approval.request") {
            return super.onCellClicked(...arguments);
        }

        const ignoredClick = ev?.target?.closest(
            "button, a, input, textarea, select, .o_handle_cell, .o_list_record_selector"
        );
        if (ignoredClick || !record?.resId) {
            return super.onCellClicked(...arguments);
        }

        try {
            const orm = this.env?.services?.orm;
            const actionService = this.env?.services?.action;
            if (!orm || !actionService) {
                return super.onCellClicked(...arguments);
            }
            const action = await orm.call(
                "workflow.base.approval.request",
                "action_open_child",
                [[record.resId]],
                { context: { wf_open_target: "current" } }
            );
            if (action && action.type) {
                return actionService.doAction(action);
            }
        } catch (error) {
            console.warn("workflow request list open-child patch fallback", error);
        }

        return super.onCellClicked(...arguments);
    },
});

