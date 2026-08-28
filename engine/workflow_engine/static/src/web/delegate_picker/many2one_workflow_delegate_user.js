/** @odoo-module **/

import { Many2XAvatarUserAutocomplete } from "@mail/views/web/fields/avatar_autocomplete/avatar_many2x_autocomplete";
import { Avatar } from "@mail/views/web/fields/avatar/avatar";
import {
    Many2ManyTagsAvatarUserField,
    many2ManyTagsAvatarUserField,
} from "@mail/views/web/fields/many2many_avatar_user_field/many2many_avatar_user_field";
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

const DELEGATE_PICKER_LIST_VIEW_REF = "workflow_engine.view_res_users_workflow_delegate_picker_list";
const DELEGATE_PICKER_KANBAN_VIEW_REF = "workflow_engine.view_res_users_workflow_delegate_picker_kanban";
const DELEGATE_PICKER_SEARCH_VIEW_REF = "workflow_engine.view_res_users_workflow_delegate_picker_search";

const DELEGATE_PICKER_SPECIFICATION = {
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

function formatDelegateLabel(record, fallback = "") {
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

class Many2XWorkflowDelegateAutocomplete extends Many2XAvatarUserAutocomplete {
    get actionSuggestions() {
        return [
            {
                enabled: this.addSearchMoreSuggestion.bind(this),
                build: this.buildSearchMoreSuggestion.bind(this),
            },
        ];
    }

    get searchSpecification() {
        return {
            ...DELEGATE_PICKER_SPECIFICATION,
            ...this.props.specification,
        };
    }

    addSearchMoreSuggestion() {
        return true;
    }

    buildRecordSuggestion(request, record) {
        const label = formatDelegateLabel(record, record.display_name);
        const selectionRecord = {...record, display_name: label};
        return {
            data: {record: selectionRecord, slotName: "autoCompleteItem"},
            label: label
                ? highlightText(request, odoomark(label), "text-primary fw-bold")
                : _t("Unnamed"),
            onSelect: () => this.props.update([selectionRecord]),
        };
    }
}

class Many2OneWorkflowDelegate extends Many2One {
    static components = {
        ...Many2One.components,
        Many2XAutocomplete: Many2XWorkflowDelegateAutocomplete,
    };
}

class Many2OneWorkflowDelegateField extends Component {
    static template = "mail.Many2OneAvatarUserField";
    static components = {Avatar, Many2OneAvatarUser: Many2OneWorkflowDelegate};
    static props = {
        ...Many2OneField.props,
    };

    get m2oProps() {
        const props = computeM2OProps(this.props);
        return {
            ...props,
            context: {
                ...props.context,
                workflow_request_owner_picker: true,
                workflow_delegate_picker: true,
                list_view_ref: DELEGATE_PICKER_LIST_VIEW_REF,
                kanban_view_ref: DELEGATE_PICKER_KANBAN_VIEW_REF,
                search_view_ref: DELEGATE_PICKER_SEARCH_VIEW_REF,
            },
            specification: DELEGATE_PICKER_SPECIFICATION,
        };
    }

    get relation() {
        return this.props.record.fields[this.props.name].relation;
    }

    get value() {
        return this.m2oProps.value || false;
    }
}

const many2OneWorkflowDelegateField = {
    ...buildM2OFieldDescription(Many2OneWorkflowDelegateField),
    additionalClasses: ["o_field_many2one_avatar", "o_field_many2one_workflow_delegate_user"],
    extractProps(staticInfo, dynamicInfo) {
        return {
            ...extractM2OFieldProps(staticInfo, dynamicInfo),
            canOpen: "no_open" in staticInfo.options
                ? !staticInfo.options.no_open
                : staticInfo.viewType === "form",
        };
    },
    listViewWidth: [160],
};

registry.category("fields").add("many2one_workflow_delegate_user", many2OneWorkflowDelegateField);

class Many2ManyWorkflowDelegateField extends Many2ManyTagsAvatarUserField {
    static components = {
        ...Many2ManyTagsAvatarUserField.components,
        Many2XAutocomplete: Many2XWorkflowDelegateAutocomplete,
    };

    get specification() {
        return DELEGATE_PICKER_SPECIFICATION;
    }

    getTagProps(record) {
        return {
            ...super.getTagProps(record),
            text: formatDelegateLabel(record.data, record.data.display_name),
        };
    }
}

const many2ManyWorkflowDelegateField = {
    ...many2ManyTagsAvatarUserField,
    component: Many2ManyWorkflowDelegateField,
    additionalClasses: [
        "o_field_many2many_tags_avatar",
        "o_field_many2many_workflow_delegate_user",
    ],
    relatedFields(fieldInfo) {
        const relatedFields = many2ManyTagsAvatarUserField.relatedFields?.(fieldInfo) || [];
        return [
            ...relatedFields,
            {name: "wf_request_owner_emp_code", type: "char"},
            {name: "wf_request_owner_employee_name", type: "char"},
        ];
    },
};

registry
    .category("fields")
    .add("many2many_workflow_delegate_user", many2ManyWorkflowDelegateField);
