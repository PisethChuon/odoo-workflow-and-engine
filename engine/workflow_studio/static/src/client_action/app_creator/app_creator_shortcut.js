import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

const actionRegistry = registry.category("actions");

actionRegistry.add("action_web_studio_app_creator",
    (env) => {
        env.services.notification.add(
            _t("Creating new apps is disabled. Use workflow categories and models instead."),
            { type: "warning" }
        );
        return env.services.workflow_studio.open(env.services.workflow_studio.MODES.HOME_MENU);
    }
);
