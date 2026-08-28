/** @odoo-module **/
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { CharField, charField } from "@web/views/fields/char/char_field";
import { useService } from "@web/core/utils/hooks";
import { evaluateExpr } from "@web/core/py_js/py";
import { status } from "@odoo/owl";

export class InputSuffixButton extends CharField {
    static template = "workflow_engine.InputSuffixButton";
    static props = {
        ...CharField.props,
        label: { type: String, optional: false },
        title: { type: String, optional: false },
        wizard_model: { type: String, optional: false },
        context: { type: String, optional: true }
    };

    setup() {
        super.setup();
        this.action = useService("action");
    }

    async onClick() {
        const record = this.props.record;
        let evalContext = {};
        try {
            if (this.props.context) {
                evalContext = evaluateExpr(this.props.context, record.evalContext);
            }
        } catch (e) {
            console.error("Context evaluation failed:", e);
        }
        
        await this.action.doAction(
            {
                type: "ir.actions.act_window",
                target: "new",
                name: this.props.title,
                res_model: this.props.wizard_model,
                views: [[false, "form"]],
                context: evalContext
            },
            {
                onClose: async () => {
                    if (status(this) === "destroyed") {
                        return;
                    }
                    const record = this.props.record;
                    if (record?.model?.load && record.resId) {
                        await record.model.load({
                            resId: record.resId,
                            resIds: Array.isArray(record.resIds) ? record.resIds : undefined,
                        });
                    } else if (record?.load) {
                        await record.load();
                    }
                },
            }
        );
    }
}

export const inputSuffixButton = {
    ...charField,
    component: InputSuffixButton,
    extractProps: ({ attrs, options, context }) => {
        const { title, label, wizard_model } = options;
        return {
            ...charField.extractProps({ attrs, options, context }),
            title: title || '',
            label: label || '',
            wizard_model: wizard_model || '',
            context: context || ''
        }
    },
};

registry.category("fields").add("input_suffix_button", inputSuffixButton);
