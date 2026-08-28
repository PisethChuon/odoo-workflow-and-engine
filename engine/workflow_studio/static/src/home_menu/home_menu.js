/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { onMounted, onWillUnmount } from "@odoo/owl";
import { HomeMenu } from "@web_theme/webclient/home_menu/home_menu";

patch(HomeMenu.prototype, {
    setup() {
        super.setup(...arguments);
        const hasCustomBackground = Boolean(this.menus.getMenu("root")?.backgroundImage);

        onMounted(() => {
            document.body.classList.add("o_home_menu_background");
            document.body.classList.toggle("o_home_menu_background_custom", hasCustomBackground);
        });

        onWillUnmount(() => {
            document.body.classList.remove("o_home_menu_background_custom");
        });
    },
});
