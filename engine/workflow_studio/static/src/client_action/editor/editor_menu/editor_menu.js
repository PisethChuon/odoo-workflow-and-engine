import { _t } from "@web/core/l10n/translation";
import { localization } from "@web/core/l10n/localization";
import { registry } from "@web/core/registry";

import { Component, useState } from "@odoo/owl";
import { useStudioServiceAsReactive } from "@workflow_studio/studio_service";
const editorTabRegistry = registry.category("workflow_studio.editor_tabs");

class Breadcrumbs extends Component {
    static template = "workflow_studio.EditorMenu.Breadcrumbs";
    static props = {
        currentTab: { type: Object },
        switchTab: Function,
    };
    setup() {
        this.editionFlow = useState(this.env.editionFlow);
        this.nextCrumbId = 1;
    }
    get breadcrumbs() {
        const currentTab = this.props.currentTab;
        const crumbs = [
            {
                data: {
                    name: currentTab.name,
                },
                handler: () => this.props.switchTab({ tab: currentTab.id }),
            },
        ];
        const breadcrumbs = this.editionFlow.breadcrumbs;
        breadcrumbs.forEach((crumb) => {
            crumbs.push(crumb);
        });
        for (const crumb of crumbs) {
            crumb.id = this.nextCrumbId++;
        }
        return crumbs;
    }
}

export class EditorMenu extends Component {
    static props = {
        switchTab: Function,
        switchView: Function,
    };
    static template = "workflow_studio.EditorMenu";
    static viewTypes = [
        {
            title: _t("Form"),
            type: "form",
            iconClasses: "fa fa-address-card",
        },
    ];
    static bpmnShortcut = {
        title: _t("BPMN Diagram"),
        iconClasses: "fa fa-sitemap",
    };

    static components = { Breadcrumbs };
    setup() {
        this.l10n = localization;
        this.studio = useStudioServiceAsReactive();
        this.editionFlow = useState(this.env.editionFlow);
    }

    get activeViews() {
        const availableEditors = registry.category("studio_editors");
        return this.constructor.viewTypes.filter((vt) => availableEditors.contains(vt.type));
    }

    get editorTabs() {
        return this.allEditorTabs.filter(
            (tab) => tab.id !== "views" && (this.supportsBpmnTab || tab.id !== "bpmn")
        );
    }

    get allEditorTabs() {
        const entries = editorTabRegistry.getEntries();
        return entries.map((entry) => Object.assign({}, entry[1], { id: entry[0] }));
    }

    get currentTab() {
        const fallbackTabId = this.supportsBpmnTab ? "bpmn" : "views";
        return (
            this.allEditorTabs.find((tab) => tab.id === this.studio.editorTab)
            || this.allEditorTabs.find((tab) => tab.id === fallbackTabId)
            || this.allEditorTabs[0]
        );
    }

    get supportsBpmnTab() {
        const action = this.studio.editedAction || {};
        const context = action.context || {};
        return Boolean(
            context.workflow_category_id
            || context.workflow_version_id
            || action.res_model === "workflow.approval.category"
            || action.res_model === "workflow.approval.category.version"
        );
    }

    get hasBpmnTab() {
        return this.supportsBpmnTab && this.allEditorTabs.some((tab) => tab.id === "bpmn");
    }

    get bpmnShortcut() {
        return this.constructor.bpmnShortcut;
    }

    openTab(tab) {
        this.props.switchTab({ tab });
    }
}

editorTabRegistry
    .add("views", { name: _t("Views"), action: "workflow_studio.action_editor" }, { sequence: 10 })
    .add("bpmn", { name: _t("Diagram"), action: "workflow_studio.bpmn_editor" }, { sequence: 15 })
    .add("automations", { name: _t("Automations") }, { sequence: 20 })
    .add("actions_server", { name: _t("Actions") }, { sequence: 30 })
    .add("automation_webhooks", { name: _t("Webhooks") }, { sequence: 40 })
    .add("acl", { name: _t("Access Control") }, { sequence: 50 })
    .add("filters", { name: _t("Filter Rules") }, { sequence: 60 });
