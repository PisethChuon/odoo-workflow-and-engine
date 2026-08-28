import {Component, EventBus, onWillDestroy, useState, useSubEnv, xml} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { makeActionManager } from "@web/webclient/actions/action_service";
import { useBus, useService } from "@web/core/utils/hooks";

import { StudioActionContainer } from "./studio_action_container";
import { EditorMenu } from "./editor_menu/editor_menu";
import { NewModelItem } from "./new_model_item/new_model_item";
import { EditionFlow } from "./edition_flow";
import { useStudioServiceAsReactive } from "@workflow_studio/studio_service";
import { useSubEnvAndServices, useServicesOverrides } from "@workflow_studio/client_action/utils";
import { omit } from "@web/core/utils/objects";

class DialogWithEnv extends Component {
    static template = xml`<t t-component="props.Component" t-props="componentProps" />`;
    static props = ["*"];

    setup() {
        useSubEnvAndServices(this.props.env);
    }

    get componentProps() {
        const additionalProps = omit(this.props, "Component", "env", "componentProps");
        return { ...this.props.componentProps, ...additionalProps };
    }
}
const dialogService = {
    dependencies: ["dialog"],
    start(env, { dialog }) {
        function addDialog(Component, _props, options) {
            const props = { env, Component, componentProps: _props };
            return dialog.add(DialogWithEnv, props, options);
        }
        return { ...dialog, add: addDialog };
    },
};

const actionServiceStudio = {
    dependencies: ["workflow_studio", "dialog"],
    start(env, { workflow_studio: studio }) {
        const router = {
            current: { hash: {} },
            pushState() {},
            stateToUrl() {},
            hideKeyFromUrl: () => {},
        };
        const action = makeActionManager(env, router);
        const _doAction = action.doAction;

        async function doAction(actionRequest, options) {
            if (actionRequest === "workflow_studio.action_edit_report") {
                return studio.setParams({
                    editedReport: options.report,
                });
            }
            return _doAction(...arguments);
        }

        return Object.assign(action, { doAction });
    },
};
const menuButtonsRegistry = registry.category("studio_navbar_menubuttons");
const WORKFLOW_STUDIO_ALLOWED_VIEW_TYPE = "form";
export class Editor extends Component {
    static template = "workflow_studio.Editor";
    static props = {};
    static components = {
        EditorMenu,
        StudioActionContainer,
    };

    setup() {
        const globalBus = this.env.bus;
        const newBus = new EventBus();
        useBus(globalBus, "CLEAR-UNCOMMITTED-CHANGES", (ev) =>
            newBus.trigger("CLEAR-UNCOMMITTED-CHANGES", ev.detail)
        );
        useBus(globalBus, "MENUS:APP-CHANGED", (ev) =>
            newBus.trigger("MENUS:APP-CHANGED", ev.detail)
        );

        useSubEnv({
            bus: newBus,
        });

        useServicesOverrides({
            dialog: dialogService,
            action: actionServiceStudio,
        });
        this.studio = useService("workflow_studio");

        const editionFlow = new EditionFlow(this.env, {
            dialog: useService("dialog"),
            studio: useStudioServiceAsReactive(),
            view: useService("view"),
        });
        useSubEnv({
            editionFlow,
        });

        this.actionService = useService("action");

        this.state = useState({ actionContainerId: 1 });
        useBus(this.studio.bus, "UPDATE", async () => {
            this.state.actionContainerId++;
        });


        menuButtonsRegistry.getEntries().forEach(([name]) => {
            if (name.startsWith("new_model_item_")) {
                menuButtonsRegistry.remove(name);
            }
        });
        const menuButtonsId = this.constructor.menuButtonsId++;

        menuButtonsRegistry.add(`new_model_item_${menuButtonsId}`, { Component: NewModelItem });
        onWillDestroy(() => {
            menuButtonsRegistry.remove(`new_model_item_${menuButtonsId}`);
        });
    }

    switchView({ viewType }) {
        this.studio.setParams({
            viewType:
                viewType === WORKFLOW_STUDIO_ALLOWED_VIEW_TYPE
                    ? viewType
                    : WORKFLOW_STUDIO_ALLOWED_VIEW_TYPE,
            editorTab: "views",
        });
    }
    switchViewLegacy(ev) {
        const requestedViewType = ev?.detail?.view_type;
        this.studio.setParams({
            viewType:
                requestedViewType === WORKFLOW_STUDIO_ALLOWED_VIEW_TYPE
                    ? requestedViewType
                    : WORKFLOW_STUDIO_ALLOWED_VIEW_TYPE,
        });
    }

    switchTab({ tab }) {
        this.studio.setParams({ editorTab: tab });
    }
}
