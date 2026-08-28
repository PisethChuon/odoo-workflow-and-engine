import { Component } from "@odoo/owl";

export class ViewEditorSnackbar extends Component {
    static template = "workflow_studio.ViewEditor.Snackbar";
    static props = {
        operations: Object,
        saveIndicator: Object,
    };
}
