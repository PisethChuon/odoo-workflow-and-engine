import { Component } from "@odoo/owl";
import { Property } from "@workflow_studio/client_action/view_editor/property/property";
import { ClassAttribute } from "@workflow_studio/client_action/view_editor/interactive_editor/properties/class_attribute/class_attribute";
import { ViewStructureProperties } from "@workflow_studio/client_action/view_editor/interactive_editor/properties/view_structure_properties/view_structure_properties";
import { useEditNodeAttributes } from "@workflow_studio/client_action/view_editor/view_editor_model";

export class FooterProperties extends Component {
    static template = "workflow_studio.ViewEditor.InteractiveEditorProperties.Footer";
    static components = {
        ClassAttribute,
        Property,
        ViewStructureProperties,
    };
    static props = {
        node: { type: Object },
    };

    setup() {
        this.editNodeAttributes = useEditNodeAttributes();
    }

    onChangeAttribute(value, name) {
        return this.editNodeAttributes({ [name]: value });
    }
}
