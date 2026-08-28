/** @odoo-module */
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";


export class ApprovalCategoryDashboard extends Component {
    static template = "workflow_engine.ApprovalCategoryDashboard";
    static props = {
        all_count: Number,
        tosubmit_count: Number,
        waiting_count: Number,
        reviewed_count: Number,
        completed_count: Number,
        all_count_display: { type: String, optional: true },
        tosubmit_count_display: { type: String, optional: true },
        waiting_count_display: { type: String, optional: true },
        reviewed_count_display: { type: String, optional: true },
        completed_count_display: { type: String, optional: true },
        category_count: { type: Number, optional: true },
        department_count: { type: Number, optional: true },
        waiting_category_count: { type: Number, optional: true },
        category_count_display: { type: String, optional: true },
        department_count_display: { type: String, optional: true },
        waiting_category_count_display: { type: String, optional: true },
        top_departments: { type: Array, optional: true },
    };

    setup() {
        this.data = this.props;
        this.action = useService("action");
        this.orm = useService("orm");
    }

    async onClick(e) {
        e.preventDefault();
        e.stopPropagation();
        const state = e.currentTarget.dataset.state || false;
        const action = await this.orm.call(
            this.env.searchModel.resModel,
            "action_open_dashboard_requests",
            [state || false],
            { context: this.env.searchModel.context }
        );
        await this.action.doAction(action);
    }
}
