/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { x2ManyCommands } from "@web/core/orm_service";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";

export class RequestorImportX2ManyField extends X2ManyField {
    static template = "workflow_engine.RequestorImportX2ManyField";
    static components = X2ManyField.components;
    static props = {
        ...X2ManyField.props,
        importOptions: { type: Object, optional: true },
    };

    get importOptions() {
        return this.props.importOptions || {};
    }

    get importButtonString() {
        return this.importOptions.button_string || _t("Import Requestors");
    }

    get importButtonInvisible() {
        return this.props.readonly || !this.importOptions.action_xmlid || !this._sectionId();
    }

    _many2oneId(value) {
        if (!value) {
            return false;
        }
        if (Array.isArray(value)) {
            return value[0] || false;
        }
        if (typeof value === "object") {
            return value.resId || value.id || false;
        }
        return value;
    }

    _sectionId() {
        const fieldName = this.importOptions.section_field;
        if (!fieldName) {
            return false;
        }
        return this._many2oneId(this.props.record.data[fieldName]);
    }

    async onOpenRequestorImport() {
        const sectionId = this._sectionId();
        if (!sectionId) {
            this.notificationService.add(_t("Please select a section first."), { type: "warning" });
            return;
        }

        await this.action.doAction(this.importOptions.action_xmlid, {
            additionalContext: {
                default_x_itrq_section_id: sectionId,
            },
            onClose: async (info) => {
                const lines = info?.requestor_import_lines || [];
                if (!lines.length) {
                    return;
                }
                const refreshPayload = {
                    resModel: this.props.record.resModel,
                    resId: this.props.record.resId || false,
                    fieldName: this.props.name,
                    reason: "requestor_import_x2many_update",
                };
                this.env.bus.trigger("WF-RUNTIME-FIELD-STATE:REFRESH", {
                    ...refreshPayload,
                    phase: "before",
                    suppressMs: 1200,
                    skipActorSnapshot: true,
                });
                await this.props.record.update({
                    [this.props.name]: lines.map((vals) => x2ManyCommands.create(false, vals)),
                });
                this.env.bus.trigger("WF-RUNTIME-FIELD-STATE:REFRESH", {
                    ...refreshPayload,
                    phase: "after",
                    force: true,
                    skipActorSnapshot: true,
                });
            },
        });
    }
}

export const requestorImportX2ManyField = {
    ...x2ManyField,
    component: RequestorImportX2ManyField,
    extractProps(staticInfo, dynamicInfo) {
        const props = x2ManyField.extractProps(staticInfo, dynamicInfo);
        props.importOptions = staticInfo.options || {};
        return props;
    },
};

registry.category("fields").add("requestor_import_o2m", requestorImportX2ManyField);
