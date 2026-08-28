/** @odoo-module **/

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("workflow_engine_runtime_v2_nurse_done_to_on_going", {
    steps: () => [
        {
            trigger: ".o_form_view",
            content: "The workflow request form is loaded.",
            timeout: 30000,
        },
        {
            trigger: 'button.wf-approval-trigger:contains("Done")',
            content: "Move Nurse Verify to the runtime_v2 parallel split.",
            run: "click",
        },
        {
            trigger: '.o_form_view .badge:contains("On Going")',
            content: "The request should project to the On Going branch.",
            timeout: 30000,
        },
    ],
});

registry.category("web_tour.tours").add("workflow_engine_runtime_v2_doctor_sees_on_going_actions", {
    steps: () => [
        {
            trigger: '.o_form_view .badge:contains("On Going")',
            content: "Doctor is on the On Going stage.",
            timeout: 30000,
        },
        {
            trigger: "button.wf-approval-trigger",
            content: "Open the doctor action menu.",
            run: "click",
        },
        {
            trigger: 'button.o_approval_decision_row:contains("Go to Nurse")',
            content: "The On Going branch exposes the expected user actions.",
        },
    ],
});

registry.category("web_tour.tours").add("workflow_engine_runtime_v2_auto_approved_after_timer", {
    steps: () => [
        {
            trigger: '.o_form_view .badge:contains("Approved")',
            content: "The timer should auto-complete the request to Approved.",
            timeout: 30000,
        },
        {
            trigger: ".o_form_view",
            content: "Approved requests should not expose workflow action buttons.",
            run: () => {
                if (document.querySelector("button.wf-approval-trigger")) {
                    throw new Error("Workflow action trigger should be hidden after timer auto-approval.");
                }
            },
        },
    ],
});
