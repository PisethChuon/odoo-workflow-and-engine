import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { NotEditableActionError } from "../../studio_service";

import { Component, onMounted, onWillUnmount, useRef } from "@odoo/owl";

/**
 * Studio home menu
 *
 * Studio home screen for environments without web_enterprise HomeMenu.
 */
export class StudioHomeMenu extends Component {
    static props = { apps: { type: Array, optional: true } };
    static template = "workflow_studio.StudioHomeMenu";

    /**
     * @param {Object} props
     * @param {Object[]} props.apps application icons
     * @param {string} props.apps[].action
     * @param {number} props.apps[].id
     * @param {string} props.apps[].label
     * @param {string} props.apps[].parents
     * @param {(boolean|string|Object)} props.apps[].webIcon either:
     *      - boolean: false (no webIcon)
     *      - string: path to Odoo icon file
     *      - Object: customized icon (background, class and color)
     * @param {string} [props.apps[].webIconData]
     * @param {string} props.apps[].xmlid
     */
    setup() {
        this.studio = useService("workflow_studio");
        this.menus = useService("menu");
        this.notifications = useService("notification");
        this.root = useRef("root");
        const hasCustomBackground = Boolean(this.menus.getMenu("root")?.backgroundImage);

        onMounted(() => {
            document.body.classList.add("o_home_menu_background");
            document.body.classList.toggle("o_home_menu_background_custom", hasCustomBackground);
        });
        onWillUnmount(() => {
            document.body.classList.remove("o_home_menu_background", "o_home_menu_background_custom");
        });
    }

    //--------------------------------------------------------------------------
    // Getters
    //--------------------------------------------------------------------------

    get displayedApps() {
        return this.props.apps || [];
    }

    //--------------------------------------------------------------------------
    // Protected
    //--------------------------------------------------------------------------

    async _openMenu(menu) {
        try {
            await this.studio.open(this.studio.MODES.EDITOR, menu.actionID);
            this.menus.setCurrentMenu(menu);
        } catch (e) {
            if (e instanceof NotEditableActionError) {
                const options = { type: "danger" };
                this.notifications.add(_t("This action is not editable by Workflow Studio"), options);
                return;
            }
            throw e;
        }
    }

    _enableAppsSorting() {
        return false;
    }
}
