/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { actionService } from "@web/webclient/actions/action_service";
import { ActionDialog } from "@web/webclient/actions/action_dialog";

function shouldUseFullscreenDialog(actionRequest) {
    return Boolean(
        actionRequest &&
            typeof actionRequest === "object" &&
            actionRequest.type === "ir.actions.act_window" &&
            actionRequest.target === "new" &&
            actionRequest.context?.wf_fullscreen_dialog
    );
}

patch(actionService, {
    start(env) {
        const manager = super.start(env);
        const originalDoAction = manager.doAction.bind(manager);

        manager.doAction = async (actionRequest, options = {}) => {
            if (!shouldUseFullscreenDialog(actionRequest)) {
                return originalDoAction(actionRequest, options);
            }

            const dialogService = env.services.dialog;
            const originalAdd = dialogService.add.bind(dialogService);
            let restored = false;

            const restore = () => {
                if (restored) {
                    return;
                }
                dialogService.add = originalAdd;
                restored = true;
            };

            dialogService.add = (Component, props = {}, dialogOptions = {}) => {
                try {
                    if (Component === ActionDialog) {
                        return originalAdd(
                            Component,
                            {
                                ...props,
                                fullscreen: true,
                                size: "fs",
                            },
                            dialogOptions
                        );
                    }
                    return originalAdd(Component, props, dialogOptions);
                } finally {
                    restore();
                }
            };

            try {
                return await originalDoAction(actionRequest, options);
            } finally {
                restore();
            }
        };

        return manager;
    },
});

