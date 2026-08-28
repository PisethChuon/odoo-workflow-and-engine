/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Component } from "@odoo/owl";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class DelegateButton extends Component {
    static template = "workflow_engine.DelegateButton";
    static props = { ...standardWidgetProps };

    setup() {
        this.dialog = useService("dialog");
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
    }

    async onClick() {
        const resId = this.props?.record?.resId;
        const resModel = this.props?.record?.resModel;
        if (!resId || !resModel) {
            this.notification.add(_t("Please save the record first."), { type: "warning" });
            return;
        }
        await this.action.doAction("workflow_engine.action_delegate_wizard", {
            additionalContext: {
                default_res_id: resId,
                default_res_model: resModel,
                default_delegate_type: "redirected",
            },
        });
    }
}

registry.category("view_widgets").add("delegate_button", { component: DelegateButton });
