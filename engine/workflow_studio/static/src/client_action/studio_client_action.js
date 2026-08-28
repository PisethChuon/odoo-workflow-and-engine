import { registry } from "@web/core/registry";
import { user as originalUser } from "@web/core/user";
import { useBus, useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { computeAppsAndMenuItems, reorderApps } from "@web/webclient/menus/menu_helpers";

import { Editor } from "./editor/editor";
import { StudioNavbar } from "./navbar/navbar";
import { StudioHomeMenu } from "./studio_home_menu/studio_home_menu";

import { Component, onWillStart, onMounted, onPatched, onWillUnmount } from "@odoo/owl";

export class StudioClientAction extends Component {
    static template = "workflow_studio.StudioClientAction";
    static target = "fullscreen";
    static props = { ...standardActionServiceProps };
    static components = {
        StudioNavbar,
        StudioHomeMenu,
        Editor,
    };

    setup() {
        const homemenuConfig = JSON.parse(originalUser.settings?.homemenu_config || "null");
        this.studio = useService("workflow_studio");
        useBus(this.studio.bus, "UPDATE", () => {
            this.render();
        });

        this.menus = useService("menu");
        let apps = computeAppsAndMenuItems(this.menus.getMenuAsTree("root")).apps;
        if (homemenuConfig) {
            reorderApps(apps, homemenuConfig);
        }
        this.homeMenuProps = {
            apps: apps,
        };
        useBus(this.env.bus, "MENUS:APP-CHANGED", () => {
            apps = computeAppsAndMenuItems(this.menus.getMenuAsTree("root")).apps;
            if (homemenuConfig) {
                reorderApps(apps, homemenuConfig);
            }
            this.homeMenuProps = {
                apps: apps,
            };
            this.render();
        });

        onWillStart(() => this.studio.ready);
        onMounted(() => {
            document.body.classList.add("o_in_workflow_studio");
            this.studio.pushState();
        });
        onPatched(() => this.studio.pushState());
        onWillUnmount(() => document.body.classList.remove("o_in_workflow_studio"));
    }
}

registry.category("lazy_components").add("StudioClientAction", StudioClientAction);
// force: true to bypass the studio lazy loading action next time and just use this one directly
registry.category("actions").add("workflow_studio", StudioClientAction, { force: true });
