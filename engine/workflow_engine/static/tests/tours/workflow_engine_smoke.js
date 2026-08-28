/** @odoo-module **/

import { registry } from "@web/core/registry";

const WORKFLOW_VIEW_SELECTOR = ".o_kanban_view, .o_list_view, .o_form_view, .o_graph_view";
const SMOKE_CREATE_VISIBLE_CATEGORY = "Workflow Smoke Create Visible";
const SMOKE_READ_ONLY_VISIBLE_CATEGORY = "Workflow Smoke Read Only Visible";

function assertNoWorkflowError(label) {
    const errorDialog = document.querySelector(".o_error_dialog");
    const accessDialog = [...document.querySelectorAll(".modal, .o_dialog")].find((dialog) =>
        /Access Error|You are not allowed|top-secret records|Odoo Server Error|Traceback/i.test(
            dialog.textContent || ""
        )
    );
    const errorNode = errorDialog || accessDialog;
    if (errorNode) {
        throw new Error(`${label} opened with a blocking error: ${errorNode.textContent.trim()}`);
    }
}

function routeSmokeSteps(label, viewSelector = WORKFLOW_VIEW_SELECTOR) {
    return [
        {
            trigger: viewSelector,
            content: `${label} view is loaded.`,
            timeout: 60000,
        },
        {
            trigger: "body",
            content: `${label} has no access/server error dialog.`,
            run: () => assertNoWorkflowError(label),
        },
    ];
}

function findCategoryRow(namePrefix) {
    return [...document.querySelectorAll(".o_kanban_record, .o_data_row")].find((row) =>
        (row.textContent || "").includes(namePrefix)
    );
}

function hasNewRequestAction(row) {
    return [...row.querySelectorAll("button, a")].some((action) =>
        /New Request/i.test(action.textContent || "")
    );
}

registry.category("web_tour.tours").add("workflow_engine_smoke_tour", {
    url: "/odoo?debug=tests",
    steps: () => [
        {
            trigger: '.o_app[data-menu-xmlid="workflow_engine.workflow_approvals_menu_root"]',
            content: "Open the Workflow app.",
            run: "click",
        },
        {
            trigger: ".o_kanban_view",
            content: "Workflow dashboard is loaded.",
        },
    ],
});

registry.category("web_tour.tours").add("workflow_engine_predeploy_dashboard_tour", {
    url: "/odoo/my-workflow-dashboard?debug=tests",
    steps: () => routeSmokeSteps("My Workflow Dashboard"),
});

registry.category("web_tour.tours").add("workflow_engine_predeploy_work_list_tour", {
    url: "/odoo/my-work-list?debug=tests",
    steps: () => routeSmokeSteps("My Work List"),
});

registry.category("web_tour.tours").add("workflow_engine_predeploy_contribute_list_tour", {
    url: "/odoo/my-contribute-list?debug=tests",
    steps: () => routeSmokeSteps("My Contribute List"),
});

registry.category("web_tour.tours").add("workflow_engine_predeploy_request_list_tour", {
    url: "/odoo/my-request-list?debug=tests",
    steps: () => routeSmokeSteps("My Request List"),
});

registry.category("web_tour.tours").add("workflow_engine_predeploy_request_report_tour", {
    url: "/odoo/approval-request-report?debug=tests",
    steps: () => routeSmokeSteps("Request Report"),
});

registry.category("web_tour.tours").add("workflow_engine_predeploy_approval_report_tour", {
    url: "/odoo/approvals-report?debug=tests",
    steps: () => routeSmokeSteps("Approval Report"),
});

registry.category("web_tour.tours").add("workflow_engine_predeploy_model_report_tour", {
    url: "/odoo/approvals-report?debug=tests",
    steps: () => routeSmokeSteps("Approval Model Report"),
});

registry.category("web_tour.tours").add("workflow_engine_predeploy_creator_dashboard_tour", {
    url: "/odoo/my-workflow-dashboard?debug=tests",
    steps: () => [
        ...routeSmokeSteps("Workflow creator dashboard"),
        {
            trigger: `.o_kanban_record:contains("${SMOKE_CREATE_VISIBLE_CATEGORY}"), .o_data_row:contains("${SMOKE_CREATE_VISIBLE_CATEGORY}")`,
            content: "A workflow creator can see a category that grants create access to their group.",
        },
        {
            trigger: "body",
            content: "Create-only and read-only dashboard actions are separated.",
            run: () => {
                const creatorRow = findCategoryRow(SMOKE_CREATE_VISIBLE_CATEGORY);
                if (!creatorRow) {
                    throw new Error("Create-visible workflow category was not visible.");
                }
                if (!hasNewRequestAction(creatorRow)) {
                    throw new Error("Create-visible workflow category should show New Request.");
                }

                const readOnlyRow = findCategoryRow(SMOKE_READ_ONLY_VISIBLE_CATEGORY);
                if (!readOnlyRow) {
                    throw new Error("Read-only workflow category was not visible.");
                }
                if (hasNewRequestAction(readOnlyRow)) {
                    throw new Error("Read-only workflow category must not show New Request.");
                }
            },
        },
    ],
});
