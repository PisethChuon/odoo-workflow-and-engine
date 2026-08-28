import { SidebarDraggableItem } from "@workflow_studio/client_action/components/sidebar_draggable_item/sidebar_draggable_item";
import { Component } from "@odoo/owl";

export class ViewStructures extends Component {
    static components = { SidebarDraggableItem };
    static template = "workflow_studio.ViewStructures";
    static props = {
        structures: { type: Object },
    };
    get isVisible() {
        return Object.values(this.props.structures).filter(
            (e) => !e.isVisible || e.isVisible(this.env.viewEditorModel)
        ).length;
    }
}
