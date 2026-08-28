import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("workflow_studio_form_editor_tour", {
    steps: () => [
        {
            trigger:
                ".o_web_studio_action_editor .o_web_studio_thumbnail_item.o_web_studio_thumbnail_form",
            run: "click",
        },
        {
            trigger:
                ".o_web_studio_editor_manager:has(.o_web_studio_form_view_editor) .o_web_studio_sidebar",
        },
        {
            trigger: ".o_web_studio_sidebar .o_web_studio_component",
            run() {
                const bodyStyle = getComputedStyle(document.body);
                const sidebarColor = bodyStyle.getPropertyValue("--wfs-studio-sidebar-bg").trim();
                const controlColor = bodyStyle.getPropertyValue("--wfs-studio-control-bg").trim();
                const controlText = bodyStyle.getPropertyValue("--wfs-studio-control-text").trim();
                const focusColor = bodyStyle.getPropertyValue("--wfs-studio-control-focus").trim();
                const sidebar = document.querySelector(".o_web_studio_sidebar");
                const component = document.querySelector(".o_web_studio_sidebar .o_web_studio_component");
                const textComponent = document.querySelector(
                    ".o_web_studio_sidebar .o_web_studio_field_char"
                );
                const selectionComponent = document.querySelector(
                    ".o_web_studio_sidebar .o_web_studio_field_selection"
                );
                const many2manyComponent = document.querySelector(
                    ".o_web_studio_sidebar .o_web_studio_field_many2many"
                );
                const one2manyComponent = document.querySelector(
                    ".o_web_studio_sidebar .o_web_studio_field_one2many"
                );
                const workspace = document.querySelector(".o_web_studio_view_renderer");

                const resolveColor = (value) => {
                    const probe = document.createElement("span");
                    probe.style.color = value;
                    probe.style.position = "fixed";
                    probe.style.visibility = "hidden";
                    document.body.appendChild(probe);
                    const resolved = getComputedStyle(probe).color;
                    probe.remove();
                    return resolved;
                };
                const resolveRadius = (value) => {
                    const probe = document.createElement("span");
                    probe.style.borderRadius = value;
                    probe.style.position = "fixed";
                    probe.style.visibility = "hidden";
                    document.body.appendChild(probe);
                    const resolved = getComputedStyle(probe).borderTopLeftRadius;
                    probe.remove();
                    return resolved;
                };

                if (!sidebarColor || !controlColor || !controlText || !focusColor) {
                    throw new Error("Enterprise Studio control tokens are not loaded in Workflow Studio.");
                }
                if (
                    !sidebar ||
                    getComputedStyle(sidebar).backgroundColor !== resolveColor(sidebarColor)
                ) {
                    throw new Error("Workflow Studio does not use the Enterprise Studio sidebar surface.");
                }
                if (!sidebar || sidebar.getBoundingClientRect().width < 280) {
                    throw new Error("Workflow Studio form sidebar did not mount at desktop width.");
                }
                const nativeComponentRadius = resolveRadius("var(--border-radius-sm)");
                if (
                    !component ||
                    getComputedStyle(component).borderTopLeftRadius !== nativeComponentRadius ||
                    !getComputedStyle(component).backgroundImage.includes("linear-gradient")
                ) {
                    throw new Error("Workflow Studio field tiles do not match Enterprise Studio.");
                }
                if (!textComponent || !selectionComponent || !many2manyComponent || !one2manyComponent) {
                    throw new Error(
                        "Workflow Studio is missing Enterprise text, selection, many2many, or one2many controls."
                    );
                }
                if (!workspace || workspace.getBoundingClientRect().width < 400) {
                    throw new Error("Workflow Studio form workspace is too narrow.");
                }
                if (document.documentElement.scrollWidth > window.innerWidth + 1) {
                    throw new Error("Workflow Studio form editor overflows the browser viewport.");
                }
            },
        },
        {
            trigger: ".o_web_studio_form_view_editor .o_inner_group .o_field_widget",
            run: "click",
        },
        {
            trigger: ".o_web_studio_sidebar .o_web_studio_property .o_select_menu_toggler",
            run() {
                const bodyStyle = getComputedStyle(document.body);
                const controlColor = bodyStyle.getPropertyValue("--wfs-studio-control-bg").trim();
                const controlText = bodyStyle.getPropertyValue("--wfs-studio-control-text").trim();
                const focusColor = bodyStyle.getPropertyValue("--wfs-studio-control-focus").trim();
                const toggler = document.querySelector(
                    ".o_web_studio_sidebar .o_web_studio_property .o_select_menu_toggler"
                );
                const textControl = document.querySelector(
                    '.o_web_studio_sidebar .o_web_studio_property .o_web_studio_sidebar_text > input:not([type="checkbox"]):not([type="radio"])'
                );
                const resolveColor = (value) => {
                    const probe = document.createElement("span");
                    probe.style.color = value;
                    probe.style.position = "fixed";
                    probe.style.visibility = "hidden";
                    document.body.appendChild(probe);
                    const resolved = getComputedStyle(probe).color;
                    probe.remove();
                    return resolved;
                };

                if (!toggler?.closest(".o_select_menu")) {
                    throw new Error("Workflow Studio property dropdown is not the native Odoo SelectMenu.");
                }
                const isNativeButton = toggler.matches("button.btn.btn-light.bg-light");
                const isNativeSearchInput = toggler.matches("input.o_input");
                if (!isNativeButton && !isNativeSearchInput) {
                    throw new Error("Workflow Studio property dropdown is missing native SelectMenu classes.");
                }
                if (!textControl) {
                    throw new Error("Workflow Studio property textbox is missing.");
                }
                const textControlStyle = getComputedStyle(textControl);
                if (
                    textControlStyle.backgroundColor !== resolveColor(controlColor) ||
                    textControlStyle.color !== resolveColor(controlText) ||
                    textControlStyle.borderTopLeftRadius !== "0px"
                ) {
                    throw new Error("Workflow Studio property textbox does not match Enterprise Studio.");
                }
                const inlineTransition = textControl.style.transition;
                textControl.style.transition = "none";
                textControl.focus();
                if (getComputedStyle(textControl).borderTopColor !== resolveColor(focusColor)) {
                    throw new Error("Workflow Studio property textbox focus does not match Enterprise Studio.");
                }
                textControl.blur();
                textControl.style.transition = inlineTransition;
            },
        },
        {
            trigger: "body.o_in_workflow_studio",
            run() {
                const forbiddenTitles = [
                    "List",
                    "Kanban",
                    "Map",
                    "Calendar",
                    "Grid",
                    "Gantt",
                    "Pivot",
                    "Graph",
                    "Cohort",
                    "Activity",
                ];
                const visibleForbidden = forbiddenTitles.flatMap((title) =>
                    [...document.querySelectorAll(`.o_web_studio_views_icons a[title='${title}']`)].filter(
                        (el) => el.offsetParent !== null
                    )
                );
                if (visibleForbidden.length) {
                    throw new Error(`Forbidden non-form view shortcuts are visible: ${visibleForbidden.length}`);
                }
            },
        },
    ],
});
