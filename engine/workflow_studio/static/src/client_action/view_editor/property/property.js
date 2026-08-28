import { Component, useEffect, useRef } from "@odoo/owl";
import { CheckBox } from "@web/core/checkbox/checkbox";
import { SelectMenu } from "@web/core/select_menu/select_menu";
import { useService } from "@web/core/utils/hooks";
import { WorkflowStudioDomainDialog } from "@workflow_studio/client_action/components/workflow_domain_dialog/workflow_domain_dialog";

export class Property extends Component {
    static template = "workflow_studio.Property";
    static components = { CheckBox, SelectMenu, WorkflowStudioDomainDialog };
    static defaultProps = {
        childProps: {},
        class: "",
    };
    static props = {
        name: { type: String },
        type: { type: String },
        value: { optional: true },
        onChange: { type: Function, optional: true },
        childProps: { type: Object, optional: true },
        class: { type: String, optional: true },
        isReadonly: { type: Boolean, optional: true },
        slots: {
            type: Object,
            optional: true,
        },
        tooltip: { type: String, optional: true },
        inputAttributes: { type: Object, optional: true },
        autofocus: { type: Boolean, optional: true },
    };

    setup() {
        this.dialog = useService("dialog");
        this.rootRef = useRef("root");

        useEffect(
            (el) => {
                if (!this.props.autofocus || !el) {
                    return;
                }
                if (this.props.type === "selection") {
                    el.querySelector(".o_select_menu_toggler").click();
                } else {
                    el.querySelector("input").focus();
                }
            },
            () => [this.rootRef.el, this.env.viewEditorModel.activeNodeXpath]
        );
    }

    get className() {
        const propsClass = this.props.class ? this.props.class : "";
        return `o_web_studio_property_${this.props.name} ${propsClass}`;
    }

    onDomainClicked() {
        const workflowContext = this.env?.viewEditorModel?._studio?.editedAction?.context || {};
        const workflowVersionId = Number(workflowContext.workflow_version_id || 0) || 0;
        const workflowCategoryId = Number(workflowContext.workflow_category_id || 0) || 0;
        this.dialog.add(WorkflowStudioDomainDialog, {
            resModel: this.props.childProps.relation,
            workflowVersionId,
            workflowCategoryId,
            domain: this.props.value || "[]",
            contextType: this.props.childProps.domainContextType || "generic",
            isDebugMode: !!this.env.debug,
            onConfirm: (domain) => this.props.onChange(domain, this.props.name),
        });
    }

    onViewOptionChange(value) {
        this.props.onChange(value, this.props.name);
    }
}
