/** @odoo-module **/

import { Many2XAvatarUserAutocomplete } from "@mail/views/web/fields/avatar_autocomplete/avatar_many2x_autocomplete";
import { Avatar } from "@mail/views/web/fields/avatar/avatar";
import { AvatarCardPopover } from "@mail/discuss/web/avatar_card/avatar_card_popover";
import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { highlightText, odoomark } from "@web/core/utils/html";
import { computeM2OProps, Many2One } from "@web/views/fields/many2one/many2one";
import {
    buildM2OFieldDescription,
    extractM2OFieldProps,
    Many2OneField,
} from "@web/views/fields/many2one/many2one_field";

const REQUEST_OWNER_LIST_VIEW_REF = "workflow_engine.view_res_users_request_owner_picker_list";
const REQUEST_OWNER_KANBAN_VIEW_REF = "workflow_engine.view_res_users_request_owner_picker_kanban";
const REQUEST_OWNER_SEARCH_VIEW_REF = "workflow_engine.view_res_users_request_owner_picker_search";

const REQUEST_OWNER_SPECIFICATION = {
    display_name: {},
    name: {},
    login: {},
    email: {},
    partner_id: {
        fields: {
            display_name: {},
            name: {},
            email: {},
        },
    },
    wf_request_owner_emp_code: {},
    wf_request_owner_employee_name: {},
    wf_request_owner_department: {},
    wf_request_owner_position: {},
    wf_request_owner_extension: {},
    wf_request_owner_work_mobile: {},
    wf_request_owner_phone: {},
    wf_request_owner_email: {},
    wf_request_owner_job_position: {},
};

function displayName(value) {
    if (!value) {
        return "";
    }
    if (typeof value === "string") {
        return value;
    }
    if (Array.isArray(value)) {
        return value[1] || "";
    }
    return value.display_name || value.name || "";
}

function formatRequestOwnerLabel(record, fallback = "") {
    if (!record) {
        return fallback || _t("Unnamed");
    }

    const employeeCode = record.wf_request_owner_emp_code || "";
    const employeeName = record.wf_request_owner_employee_name || "";
    if (employeeCode && employeeName) {
        return `${employeeCode} - ${employeeName}`;
    }

    return (
        employeeName ||
        displayName(record.partner_id) ||
        record.name ||
        fallback ||
        record.display_name ||
        _t("Unnamed")
    );
}

export class RequestOwnerAvatarCardPopover extends AvatarCardPopover {
    static template = "workflow_engine.RequestOwnerAvatarCardPopover";
}

export class RequestOwnerAvatar extends Avatar {
    static components = {
        ...Avatar.components,
        Popover: RequestOwnerAvatarCardPopover,
    };
}

export class Many2XRequestOwnerAutocomplete extends Many2XAvatarUserAutocomplete {
    get actionSuggestions() {
        if (this.props.context.show_invite_by_email) {
            return super.actionSuggestions;
        }
        return [
            {
                enabled: this.addSearchMoreSuggestion.bind(this),
                build: this.buildSearchMoreSuggestion.bind(this),
            },
        ];
    }

    get searchSpecification() {
        return {
            ...REQUEST_OWNER_SPECIFICATION,
            ...this.props.specification,
        };
    }

    addSearchMoreSuggestion() {
        return true;
    }

    buildRecordSuggestion(request, record) {
        const label = formatRequestOwnerLabel(record, record.display_name);
        const selectionRecord = { ...record, display_name: label };
        return {
            data: { record: selectionRecord, slotName: "autoCompleteItem" },
            label: label
                ? highlightText(request, odoomark(label), "text-primary fw-bold")
                : _t("Unnamed"),
            onSelect: () => this.props.update([selectionRecord]),
        };
    }
}

export class Many2OneRequestOwner extends Many2One {
    static components = {
        ...Many2One.components,
        Many2XAutocomplete: Many2XRequestOwnerAutocomplete,
    };
}

export class Many2OneRequestOwnerField extends Component {
    static template = "mail.Many2OneAvatarUserField";
    static components = { Avatar: RequestOwnerAvatar, Many2OneAvatarUser: Many2OneRequestOwner };
    static props = {
        ...Many2OneField.props,
        showInviteByEmail: { type: Boolean, optional: true },
    };

    get m2oProps() {
        const props = computeM2OProps(this.props);
        const context = {
            ...props.context,
            workflow_request_owner_picker: true,
            list_view_ref: REQUEST_OWNER_LIST_VIEW_REF,
            kanban_view_ref: REQUEST_OWNER_KANBAN_VIEW_REF,
            search_view_ref: REQUEST_OWNER_SEARCH_VIEW_REF,
            show_invite_by_email: !!this.props.showInviteByEmail,
        };
        const value = this.requestOwnerValue(props.value);
        return {
            ...props,
            canCreate: !!this.props.showInviteByEmail && props.canCreate,
            canCreateEdit: !!this.props.showInviteByEmail && props.canCreateEdit,
            canQuickCreate: !!this.props.showInviteByEmail && props.canQuickCreate,
            context,
            specification: REQUEST_OWNER_SPECIFICATION,
            value,
        };
    }

    requestOwnerValue(value) {
        if (!value) {
            return value;
        }
        const data = this.props.record.data;
        const employeeCode = data.request_owner_emp_code || "";
        const employeeName = data.request_owner_emp_name || "";
        if (!employeeCode && !employeeName) {
            return value;
        }

        const display_name =
            employeeCode && employeeName ? `${employeeCode} - ${employeeName}` : employeeName;
        return {
            ...value,
            display_name,
        };
    }

    get relation() {
        return this.props.record.fields[this.props.name].relation;
    }

    get value() {
        return this.props.record.data[this.props.name];
    }
}

export const many2OneRequestOwnerField = {
    ...buildM2OFieldDescription(Many2OneRequestOwnerField),
    additionalClasses: ["o_field_many2one_avatar", "o_field_many2one_request_owner"],
    extractProps(staticInfo, dynamicInfo) {
        return {
            ...extractM2OFieldProps(staticInfo, dynamicInfo),
            canOpen: "no_open" in staticInfo.options
                ? !staticInfo.options.no_open
                : staticInfo.viewType === "form",
            showInviteByEmail: !!staticInfo.options.show_invite_by_email,
        };
    },
    listViewWidth: [160],
};

registry.category("fields").add("many2one_request_owner", many2OneRequestOwnerField);
