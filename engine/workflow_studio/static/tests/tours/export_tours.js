import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("can_export_new_module", {
    url: "/odoo",
    steps: () => [
        {
            trigger: ".o_home_menu .o_app, .o_app",
            run() {
                const app = [...document.querySelectorAll(".o_app")].find((el) =>
                    (el.textContent || "").trim() === "Workflow"
                );
                if (!app) {
                    throw new Error("Workflow app tile is not available");
                }
                app.click();
            },
        },
        {
            trigger: ".o_main_navbar .o_web_studio_navbar_item",
            run: "click",
        },
        {
            trigger: "a.o_web_studio_export, .o_web_studio_export",
        },
        {
            trigger: ".o_web_studio_export",
            run: "click",
        },
        {
            content: "check that export feature is blazing fast",
            trigger: ".modal .modal-footer button:contains(Export), .modal .modal-footer button:contains(export)",
            run: "click",
        },
        {
            content: "modal is closed",
            trigger: ":not(.modal)",
        },
    ],
});
