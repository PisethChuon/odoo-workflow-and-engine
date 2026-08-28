/** @odoo-module **/

import { evaluateExpr } from "@web/core/py_js/py";
import { patch } from "@web/core/utils/patch";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import { ListRenderer } from "@web/views/list/list_renderer";
import { ViewButton } from "@web/views/view_button/view_button";

function isWorkflowHistoryContext(context) {
    return Boolean(context?.workflow_history_mode && context?.workflow_history_source_base_id);
}

function openWorkflowHistoryDialog(env, { resModel, resId, context, title, viewId = false }) {
    if (!resModel || !resId || !isWorkflowHistoryContext(context)) {
        return false;
    }
    const dialogService = env?.services?.dialog;
    if (!dialogService) {
        return false;
    }
    dialogService.add(FormViewDialog, {
        resModel,
        resId,
        context,
        title,
        viewId,
        readonly: true,
        preventCreate: true,
        preventEdit: true,
        canExpand: false,
    });
    return true;
}

function getWorkflowHistoryTitle(record) {
    return record?.data?.display_name || record?.data?.name || undefined;
}

function getWorkflowHistoryButtonContext(button) {
    const rawContext = button.clickParams?.context;
    if (!rawContext) {
        return {};
    }
    if (typeof rawContext === "string") {
        try {
            return evaluateExpr(rawContext, button.props.record?.evalContext || {});
        } catch {
            return {};
        }
    }
    return rawContext;
}

function isWorkflowHistoryDialogButton(button) {
    const buttonContext = getWorkflowHistoryButtonContext(button);
    return Boolean(buttonContext.workflow_history_dialog);
}

patch(ListRenderer.prototype, {
    async onCellClicked(record, column, ev, newWindow) {
        const ignoredClick = ev?.target?.closest(
            "button, a, input, textarea, select, .o_handle_cell, .o_list_record_selector"
        );
        if (!ignoredClick && !newWindow && record?.resId && isWorkflowHistoryContext(record.context)) {
            const opened = openWorkflowHistoryDialog(this.env, {
                resModel: record.resModel,
                resId: record.resId,
                context: record.context,
                title: getWorkflowHistoryTitle(record),
            });
            if (opened) {
                return;
            }
        }
        return super.onCellClicked(...arguments);
    },
});

patch(ViewButton.prototype, {
    onClick(ev, newWindow) {
        if (isWorkflowHistoryDialogButton(this)) {
            if (this.props.tag === "a") {
                ev.preventDefault();
            }
            if (this.props.onClick) {
                return this.props.onClick();
            }
            this.dropdownControl.close();
            const record = this.props.record || {};
            const buttonContext = getWorkflowHistoryButtonContext(this);
            const context = {
                ...(record.context || {}),
                ...buttonContext,
            };
            const opened = openWorkflowHistoryDialog(this.env, {
                resModel: record.resModel,
                resId: record.resId,
                context,
                title: getWorkflowHistoryTitle(record),
                viewId: context.workflow_history_form_view_id || false,
            });
            if (opened) {
                return;
            }
        }
        return super.onClick(...arguments);
    },
});
