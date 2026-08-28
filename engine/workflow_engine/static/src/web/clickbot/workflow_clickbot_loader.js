/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { startClickEverywhere } from "@web/webclient/clickbot/clickbot_loader";

const WORKFLOW_MENU_XML_ID = "workflow_engine.workflow_approvals_menu_root";

function runWorkflowClickTestItem() {
    return {
        type: "item",
        description: _t("Run Workflow Click Everywhere"),
        callback: () => startClickEverywhere(WORKFLOW_MENU_XML_ID, false),
        sequence: 461,
        section: "testing",
    };
}

registry
    .category("debug")
    .category("default")
    .add("runWorkflowClickTestItem", runWorkflowClickTestItem);
