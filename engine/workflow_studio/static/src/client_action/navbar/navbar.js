import { _t } from "@web/core/l10n/translation";
import { onWillUnmount } from "@odoo/owl";

import { registry } from "@web/core/registry";
import { router } from "@web/core/browser/router";
import { useService } from "@web/core/utils/hooks";
import { NavBar } from "@web/webclient/navbar/navbar";
import { HomeMenuCustomizer } from "./home_menu_customizer/home_menu_customizer";
import { useStudioServiceAsReactive, NotEditableActionError } from "@workflow_studio/studio_service";

const menuButtonsRegistry = registry.category("studio_navbar_menubuttons");
export class StudioNavbar extends NavBar {
    static template = "workflow_studio.StudioNavbar";
    static components = {
        ...NavBar.components,
        HomeMenuCustomizer,
    };
    setup() {
        super.setup();
        this.studio = useStudioServiceAsReactive();
        this.actionManager = useService("action");
        this.dialogManager = useService("dialog");
        this.notification = useService("notification");
        const onMenuButtonsUpdate = () => this.render();
        menuButtonsRegistry.addEventListener("UPDATE", onMenuButtonsUpdate);
        onWillUnmount(() => menuButtonsRegistry.removeEventListener("UPDATE", onMenuButtonsUpdate));
    }
    onMenuToggle() {
        this.studio.toggleHomeMenu();
    }
    _getWorkflowCategoryId() {
        const context = this.studio.editedAction?.context || {};
        const routeState = router.current || {};
        const fromWorkflowContext =
            context.workflow_category_id ||
            (context.active_model === "workflow.approval.category" ? context.active_id : false) ||
            routeState.workflow_category_id ||
            (routeState.active_model === "workflow.approval.category" ? routeState.active_id : false);
        const categoryId = Number(fromWorkflowContext);
        return Number.isFinite(categoryId) && categoryId > 0 ? categoryId : false;
    }
    closeStudio() {
        const workflowCategoryId = this._getWorkflowCategoryId();
        if (workflowCategoryId) {
            this.studio.leave({
                type: "ir.actions.act_window",
                name: _t("Approval Category"),
                res_model: "workflow.approval.category",
                views: [[false, "form"]],
                view_mode: "form",
                res_id: workflowCategoryId,
                target: "current",
            });
            return;
        }
        this.studio.leave();
    }
    async onNavBarDropdownItemSelection(menu) {
        if (menu.actionID) {
            try {
                await this.studio.open(this.studio.MODES.EDITOR, menu.actionID);
            } catch (e) {
                if (e instanceof NotEditableActionError) {
                    const options = { type: "danger" };
                    this.notification.add(_t("This action is not editable by Workflow Studio"), options);
                    return;
                }
                throw e;
            }
        }
    }
    get hasBackgroundAction() {
        return this.studio.editedAction || this.studio.MODES.APP_CREATOR === this.studio.mode;
    }
    get isInApp() {
        return this.studio.mode === this.studio.MODES.EDITOR;
    }
    get menuButtons() {
        return Object.fromEntries(menuButtonsRegistry.getEntries());
    }
}
