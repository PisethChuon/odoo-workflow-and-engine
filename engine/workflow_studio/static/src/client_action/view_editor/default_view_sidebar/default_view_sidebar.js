import { Component, useState } from "@odoo/owl";
import { InteractiveEditorSidebar } from "@workflow_studio/client_action/view_editor/interactive_editor/interactive_editor_sidebar";
import { SidebarViewToolbox } from "@workflow_studio/client_action/view_editor/interactive_editor/sidebar_view_toolbox/sidebar_view_toolbox";

export class DefaultViewSidebar extends Component {
    static template = "workflow_studio.ViewEditor.DefaultViewSidebar";
    static props = {
        openViewInForm: { type: Function, optional: true },
        openDefaultValues: { type: Function, optional: true },
    };
    static components = {
        InteractiveEditorSidebar,
        SidebarViewToolbox,
    };

    setup() {
        this.viewEditorModel = useState(this.env.viewEditorModel);
    }
}
