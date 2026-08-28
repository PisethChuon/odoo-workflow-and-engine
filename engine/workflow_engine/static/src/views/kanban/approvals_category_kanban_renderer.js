import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";

export class ApprovalCategoryKanbanRenderer extends KanbanRenderer {
    static template = "workflow_engine.ApprovalCategoryKanbanRenderer";
    static components = Object.assign({}, KanbanRenderer.components);
}

export const ApprovalCategoryKanbanView = {
    ...kanbanView,
    Renderer: ApprovalCategoryKanbanRenderer
};

registry.category("views").add("approvals_category_kanban", ApprovalCategoryKanbanView);
