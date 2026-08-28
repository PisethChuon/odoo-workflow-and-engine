/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { X2ManyFieldDialog } from "@web/views/fields/relational_utils";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";

const APPROVER_MODEL = "workflow.approval.approver";

function isApproverDialog(recordOrProps) {
    return recordOrProps?.resModel === APPROVER_MODEL;
}

patch(X2ManyFieldDialog.prototype, {
    get dialogProps() {
        const props = super.dialogProps;
        if (isApproverDialog(this.props.record)) {
            delete props.onExpand;
        }
        return props;
    },
});

patch(FormViewDialog.prototype, {
    setup() {
        super.setup(...arguments);
        if (isApproverDialog(this.props)) {
            this.onExpandCallback = undefined;
        }
    },
});
