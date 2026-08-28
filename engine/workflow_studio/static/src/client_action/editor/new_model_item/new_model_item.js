import {Component, useState} from "@odoo/owl";
import {_t} from "@web/core/l10n/translation";
import {rpc} from "@web/core/network/rpc";
import {user} from "@web/core/user";
import {useBus, useService, useOwnedDialogs} from "@web/core/utils/hooks";
import {Dialog} from "@web/core/dialog/dialog";
import {ModelConfiguratorDialog} from "../../model_configurator/model_configurator";
import {useDialogConfirmation} from "../../utils";

class SimpleNewModelDialog extends Component {
    static template = "workflow_studio.SimpleNewModelDialog";
    static components = {Dialog};
    static props = {close: {type: Function}};

    setup() {
        this.addDialog = useOwnedDialogs();
        this.menus = useService("menu");
        this.action = useService("action");
        this.studio = useService("workflow_studio");
        this.notification = useService("notification");
        this.state = useState({modelName: "", showValidation: false});
        const { confirm, cancel } = useDialogConfirmation({
            confirm: async (data) => {
                try {
                    const modelName = (this.state.modelName || "").trim();

                    if (!modelName) {
                        this.state.showValidation = true;
                        return;
                    }

                    const res = await rpc(
                        "/workflow_studio/create_model_and_open_editor",
                        {
                            model_name: modelName,
                            model_choice: "new",
                            model_options: data?.modelOptions || [],
                            context: user.context,
                        }
                    );

                    // 🔥 ALWAYS check transient first
                    if (res?.is_transient) {
                        this.notification.add(
                            _t("Wizard model created successfully."),
                            { type: "success" }
                        );
                        return;
                    }

                    if (!res?.action) {
                        this.notification.add(
                            _t("Failed to open Workflow Studio."),
                            { type: "danger" }
                        );
                        return;
                    }

                    await this.action.doAction(res.action, {
                        clearBreadcrumbs: true,
                    });

                } catch (error) {
                    console.error("Create model error:", error);
                    this.notification.add(
                        _t("An unexpected error occurred while creating the model."),
                        { type: "danger" }
                    );
                }
            },
        });

        this._confirm = confirm;
        this._cancel = cancel;
    }

    confirm(data = {}) {
        this.props.close();
        return this._confirm(data);
    }

    onConfigureModel() {
        if (!this.state.modelName) {
            this.state.showValidation = true;
            return;
        }

        this.addDialog(ModelConfiguratorDialog, {
            confirmLabel: _t("Create Model"), confirm: (data) => {
                this.confirm({modelOptions: data});
            },
        });
    }
}

export class NewModelItem extends Component {
    static props = {};
    static template = "workflow_studio.NewModelItem";

    setup() {
        this.addDialog = useOwnedDialogs();
        this.menus = useService("menu");
        this.studio = useService("workflow_studio");
        this.action = useService("action");

        useBus(this.env.bus, "MENUS:APP-CHANGED", () => this.render());
    }

    onClick(ev) {
        ev.preventDefault();
        this.addDialog(SimpleNewModelDialog);
    }
}
