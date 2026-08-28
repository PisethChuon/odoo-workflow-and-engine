import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { listView } from "@web/views/list/list_view";
import { ListRenderer } from "@web/views/list/list_renderer";
import { useService } from "@web/core/utils/hooks";

export class ApprovalReportListRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.action = useService("action");
    }

    async onCellClicked(record, column, ev) {
        // debugger;
        // ev.preventDefault();
        // ev.stopPropagation();
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: record.data.res_model_name,
            res_id: record.evalContext.id,
            view_mode: "form",
            views: [[false, "form"]],
            target: "current", // or "new" for popup
        });
    }

}

export const ApprovalReportListView = {
    ...listView,
    Renderer: ApprovalReportListRenderer,
};

registry.category("views").add("approval_report_request_list", ApprovalReportListView);

