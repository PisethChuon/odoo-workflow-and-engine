/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { useRecordObserver } from "@web/model/relational_model/utils";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import {
    applyWorkflowFieldStateMap,
    applyWorkflowNodeStateMap,
    applyWorkflowRuntimeFieldLists,
    serializeWorkflowSnapshot,
} from "@workflow_engine/web/utils/wf_field_state_utils";

export class DynamicTransitionButtons extends Component {
    static template = "workflow_engine.DynamicApprovalButtons";
    static components = { Dropdown, DropdownItem };
    static props = {
        ...standardWidgetProps,
    };

    setup() {
        super.setup();
        this.action = useService("action");
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.ui = useService("ui");
        this.resId = this.props.record.resId;
        this._dialogButtonGuard = {
            active: false,
            preservedButtons: [],
        };
        this.state = useState({
            buttons: this._parseButtons(this.props.record?.data?.visible_buttons),
        });
        useRecordObserver((record) => {
            this.resId = record?.resId;
            this.state.buttons = this._resolveButtonSnapshot(record?.data?.visible_buttons);
        });
        useBus(this.env.bus, "WF-APPROVAL-BUTTONS:UPDATE", (payload) => {
            const record = this.props.record;
            if (!record || !payload) {
                return;
            }
            if (payload.resModel !== record.resModel) {
                return;
            }
            if ((payload.resId || false) !== (record.resId || false)) {
                return;
            }
            this.state.buttons = this._resolveButtonSnapshot(payload.buttons);
        });
    }

    _parseButtons(buttons) {
        try {
            if (!buttons) return [];
            if (typeof buttons === 'string') {
                buttons = JSON.parse(buttons);
            }
            return Array.isArray(buttons) ? buttons : [];
        } catch (e) {
            console.warn('Failed to parse buttons:', e);
            return [];
        }
    }

    _cloneButtons(buttons) {
        return (buttons || []).map((button) => ({ ...button }));
    }

    _resolveButtonSnapshot(buttons) {
        const parsedButtons = this._parseButtons(buttons);
        if (
            this._dialogButtonGuard.active &&
            !parsedButtons.length &&
            this._dialogButtonGuard.preservedButtons.length
        ) {
            return this._cloneButtons(this._dialogButtonGuard.preservedButtons);
        }
        return parsedButtons;
    }

    _activateDialogButtonGuard(buttons = this.buttons) {
        this._dialogButtonGuard.active = true;
        this._dialogButtonGuard.preservedButtons = this._cloneButtons(buttons);
    }

    _releaseDialogButtonGuard() {
        this._dialogButtonGuard.active = false;
        this._dialogButtonGuard.preservedButtons = [];
    }

    _restorePreservedButtons(record = this.props.record) {
        if (!this._dialogButtonGuard.preservedButtons.length) {
            return;
        }
        const restoredButtons = this._cloneButtons(this._dialogButtonGuard.preservedButtons);
        this.state.buttons = restoredButtons;
        if (record?.data && "visible_buttons" in record.data) {
            record.data.visible_buttons = restoredButtons;
            if (typeof record._setEvalContext === "function") {
                record._setEvalContext();
            }
            if (typeof record.model?.notify === "function") {
                record.model.notify();
            }
        }
    }

    get buttons() {
        return this.state.buttons;
    }

    getButtonCssClass(button) {
        const custom = (button?.css_class || "").trim();
        const base = "o-navigable o_approval_decision_row wf-approval-action";
        const safeCustom = this._normalizeDynamicActionCssClass(custom);
        const tone = this._getDynamicActionToneClass(button);
        return [base, safeCustom, tone].filter(Boolean).join(" ");
    }

    getDesktopSingleButtonCssClass(button) {
        const tone = this._getDynamicActionToneClass(button);
        const configuredStyle = this._getConfiguredActionStyle(button);
        const toneClass =
            configuredStyle.buttonClass ||
            {
                "wf-approval-action--primary": "btn-primary",
                "wf-approval-action--secondary": "btn-secondary",
                "wf-approval-action--success": "btn-success",
                "wf-approval-action--info": "btn-info",
                "wf-approval-action--warning": "btn-warning",
                "wf-approval-action--danger": "btn-danger",
            }[tone] ||
            "btn-warning";
        return [
            "btn",
            toneClass,
            "o_approval_decision_trigger",
            "wf-approval-trigger",
            "wf-approval-trigger--single",
            this._normalizeDynamicActionCssClass(button?.css_class || ""),
            button?.disabled ? "disabled" : "",
        ]
            .filter(Boolean)
            .join(" ");
    }

    getButtonIconClass(button) {
        const raw = (button?.icon_class || "").trim();
        if (!raw) {
            return "me-1 fa fa-gavel";
        }
        const tokens = raw.split(/\s+/).filter(Boolean);
        const hasFamilyClass = tokens.some((token) => /^(fa|fas|far|fal|fab|fad)$/.test(token));
        const hasIconClass = tokens.some((token) => token.startsWith("fa-"));
        if (hasIconClass) {
            return `me-1 ${hasFamilyClass ? raw : `fa ${raw}`}`;
        }
        if (hasFamilyClass) {
            return `me-1 ${raw} fa-gavel`;
        }
        return `me-1 fa fa-${raw}`;
    }

    _getConfiguredActionStyle(button) {
        const custom = (button?.css_class || "").trim();
        const tones = ["primary", "secondary", "success", "info", "warning", "danger"];
        for (const tone of tones) {
            if (new RegExp(`\\bbtn-outline-${tone}\\b`).test(custom)) {
                return {tone, buttonClass: `btn-outline-${tone}`};
            }
            if (new RegExp(`\\bbtn-${tone}\\b`).test(custom)) {
                return {tone, buttonClass: `btn-${tone}`};
            }
            if (new RegExp(`\\btext-${tone}\\b`).test(custom)) {
                return {tone, buttonClass: "btn-link"};
            }
        }
        return {tone: "", buttonClass: ""};
    }

    _normalizeDynamicActionCssClass(rawClass) {
        if (!rawClass) {
            return "";
        }
        const blocked = /^(btn|bg-|dropdown-item|o-dropdown-item|rounded|border|shadow|p-|px-|py-|m-|mx-|my-)/;
        return rawClass
            .split(/\s+/)
            .filter((token) => token && !blocked.test(token))
            .join(" ");
    }

    _getDynamicActionToneClass(button) {
        const configuredTone = this._getConfiguredActionStyle(button).tone;
        if (configuredTone) {
            return `wf-approval-action--${configuredTone}`;
        }
        const actionKey = String(button?.action_key || button?.name || button?.label || "").toLowerCase();
        if (/(reject|refuse|cancel|deny)/.test(actionKey)) {
            return "wf-approval-action--danger";
        }
        if (/(submit|approve|complete|done)/.test(actionKey)) {
            return "wf-approval-action--primary";
        }
        return "";
    }

    get showDesktopSaveFallback() {
        const record = this.props.record;
        return (
            !this.env.isSmall &&
            (record?.__wfActorUiSnapshotLoaded === true || !record?.resId) &&
            !this.buttons.length &&
            !this._dialogButtonGuard.preservedButtons.length &&
            Boolean(record?.data?.is_user_has_permission)
        );
    }

    _extractErrorMessage(error) {
        const rpcData = error?.data || error?.cause?.data || {};
        const detail = rpcData?.data || error?.cause?.data?.data || {};
        let message =
            detail?.message ||
            rpcData?.message ||
            error?.message ||
            _t("Operation failed. Please contact Workflow Admin.");

        if (typeof message !== "string") {
            message = String(message || "");
        }
        message = message.trim();
        if (!message) {
            message = _t("Operation failed. Please contact Workflow Admin.");
        }
        if (message.includes("\nTraceback")) {
            message = message.split("\nTraceback")[0].trim();
        }

        const accessSignature = "doesn't have 'write' access";
        if (message.includes(accessSignature) || String(detail?.name || "").includes("AccessError")) {
            const lines = message
                .split("\n")
                .map((line) => line.trim())
                .filter(Boolean);
            const accessLine = lines.find((line) => line.includes("doesn't have")) || "";
            const modelLine = lines.find((line) => line.startsWith("- ")) || "";
            const compactDetail = [accessLine, modelLine].filter(Boolean).join(" ");
            const suffix = compactDetail
                ? ` ${_t("Details:")} ${compactDetail}`
                : "";
            return _t(
                "You do not have permission to update one or more related records. Please contact Workflow Admin.%s",
                suffix
            );
        }
        return message;
    }

    _notifyActionError(error) {
        const message = this._extractErrorMessage(error);
        this.notification.add(message, {
            type: "danger",
            sticky: true,
        });
    }

    _isWorkflowSaveAccessError(error) {
        const rpcData = error?.data || error?.cause?.data || {};
        const detail = rpcData?.data || error?.cause?.data?.data || {};
        const errorName = String(detail?.name || rpcData?.name || error?.name || "");
        const rawMessage = [
            detail?.message,
            rpcData?.message,
            error?.message,
        ]
            .filter(Boolean)
            .join("\n");
        const compactMessage = String(rawMessage || "").trim();
        if (!compactMessage && !errorName) {
            return false;
        }
        if (errorName.includes("AccessError")) {
            return true;
        }
        return [
            "doesn't have 'write' access",
            "You are not allowed to access one or more workflow requests",
            "You do not have permission to update one or more related records",
            "Access Denied by ACLs for operation: write",
        ].some((needle) => compactMessage.includes(needle));
    }

    async _resetRecordAfterSaveAccessError(record) {
        if (!record) {
            return;
        }
        try {
            if (typeof record.discard === "function") {
                await record.discard();
                return;
            }
        } catch (discardError) {
            console.warn(
                "Workflow action could not discard dirty form state after save access error; reloading instead.",
                discardError
            );
        }
        await this._reloadRecordModel(record);
    }

    _storeDuplicateRetryIntent(record, button) {
        if (typeof window === "undefined") {
            return;
        }
        window.__wfDuplicateRetryIntent = {
            resModel: record?.resModel || "",
            actionKey: button?.action_key || button?.name || button?.action_button_label || "",
            metaActionId: button?.meta_action_id || false,
            ts: Date.now(),
        };
    }

    _consumeDuplicateRetryConfirmBypass(record, button) {
        if (typeof window === "undefined") {
            return false;
        }
        const intent = window.__wfDuplicateRetryIntent;
        if (!intent) {
            return false;
        }
        const actionKey = button?.action_key || button?.name || button?.action_button_label || "";
        const matches =
            intent.resModel === (record?.resModel || "")
            && String(intent.actionKey || "") === String(actionKey || "")
            && (!intent.metaActionId || intent.metaActionId === (button?.meta_action_id || false));
        if (!matches || !intent.skipWorkflowConfirmOnRetry) {
            return false;
        }
        delete window.__wfDuplicateRetryIntent;
        return true;
    }

    _clearDuplicateRetryIntent() {
        if (typeof window === "undefined") {
            return;
        }
        delete window.__wfDuplicateRetryIntent;
    }

    _validateRecordBeforeSave(record) {
        if (!record?._checkValidity) {
            return true;
        }
        return record._checkValidity({ displayNotification: true });
    }

    _isDialogAction(action) {
        return Boolean(action && action.type && action.target === "new");
    }

    async _reloadRecordModel(record) {
        if (typeof record?.model?.load === "function") {
            const params = record.resId
                ? {
                      resId: record.resId,
                      resIds: Array.isArray(record.resIds) ? record.resIds : undefined,
                  }
                : {};
            await record.model.load(params);
            if (typeof record.model.notify === "function") {
                record.model.notify();
            }
            return;
        }
        if (record?.resId && this.action?.doAction) {
            try {
                await this.action.doAction("soft_reload");
                return;
            } catch (error) {
                console.warn("Workflow soft reload failed after model load was unavailable.", error);
            }
        }
    }

    async _readRecordWriteDate(record) {
        if (!record?.resModel || !record?.resId) {
            return "";
        }
        try {
            const rows = await this.orm.read(record.resModel, [record.resId], ["write_date"]);
            return rows?.[0]?.write_date || "";
        } catch {
            // If write_date cannot be checked, fall back to reloading after close.
            return "";
        }
    }

    _queueDialogCloseFollowUp(record, beforeDialogWriteDate) {
        Promise.resolve()
            .then(async () => {
                const afterDialogWriteDate = await this._readRecordWriteDate(record);
                if (
                    !beforeDialogWriteDate ||
                    !afterDialogWriteDate ||
                    beforeDialogWriteDate !== afterDialogWriteDate
                ) {
                    await this._reloadRecordModel(record);
                }
            })
            .catch((error) => {
                console.warn(
                    "Workflow dialog close follow-up failed; leaving current button state in place.",
                    error
                );
            });
    }

    async onSaveFallbackClick() {
        this.ui.block();
        try {
            const record = this.props.record;
            if (!this._validateRecordBeforeSave(record)) {
                return;
            }
            const isValid = await record.save();
            if (!isValid) {
                return;
            }
            await this._reloadRecordModel(record);
        } catch (error) {
            console.error(error);
            this._notifyActionError(error);
        } finally {
            this.ui.unblock();
        }
    }

    async _refreshRuntimeFieldStatesForAction(record, button) {
        if (!record) {
            return;
        }
        const isVirtual = !record.resId;
        const method = isVirtual
            ? "workflow_get_runtime_field_state_map_virtual"
            : "workflow_get_runtime_field_state_map";
        const args = isVirtual ? [] : [[record.resId]];
        const payload = await this.orm.call(
            record.resModel,
            method,
            args,
            {
                action_key: button?.action_key || button?.name || button?.action_button_label || "",
                task_node_id: record?.data?.current_node_id || "",
                meta_action_id: button?.meta_action_id || false,
                view_id: this.env.config?.viewId || false,
                snapshot_values: serializeWorkflowSnapshot(record),
            }
        );
        applyWorkflowRuntimeFieldLists(record, payload || {});
        applyWorkflowFieldStateMap(record, payload?.field_state_map || {});
        applyWorkflowNodeStateMap(record, payload?.node_state_map || {});
    }

    _applyButtonRequiredFieldsForValidation(record, button) {
        if (!record?.activeFields || !button) {
            return false;
        }
        if (button.has_conditional_required_fields) {
            return false;
        }
        const requiredFields = Array.isArray(button.required_fields) ? button.required_fields : [];
        const allActionFields = Array.isArray(button.all_require_fields) ? button.all_require_fields : [];
        if (!requiredFields.length && !allActionFields.length) {
            return false;
        }
        const requiredSet = new Set(requiredFields);
        for (const fieldName of allActionFields) {
            if (!requiredSet.has(fieldName)) {
                return false;
            }
        }
        let changed = false;
        for (const fieldName of requiredFields) {
            const activeField = record.activeFields[fieldName];
            if (!activeField) {
                continue;
            }
            if (activeField.required !== true) {
                activeField.required = true;
                changed = true;
            }
            if (activeField.invisible === true) {
                activeField.invisible = false;
                changed = true;
            }
        }
        if (changed && typeof record._setEvalContext === "function") {
            record._setEvalContext();
        }
        if (changed && typeof record.model?.notify === "function") {
            record.model.notify();
        }
        return true;
    }

    async onClick(button) {
        const selectedButton = {
            ...(button || {}),
            required_fields: Array.isArray(button?.required_fields) ? [...button.required_fields] : [],
            all_require_fields: Array.isArray(button?.all_require_fields) ? [...button.all_require_fields] : [],
        };
        const buttonSnapshotBeforeAction = this._cloneButtons(this.buttons);
        if (selectedButton?.disabled) {
            this.notification.add(
                selectedButton?.disabled_reason || "You do not have permission to execute this workflow action.",
                { type: "warning" }
            );
            return;
        }

        this.ui.block();

        try {
            const record = this.props.record;
            const suppressWorkflowConfirm = this._consumeDuplicateRetryConfirmBypass(record, selectedButton);
            const workflowContext = {
                view_id: this.env.config?.viewId || false,
                meta_action_id: selectedButton?.meta_action_id || false,
                workflow_action_key: selectedButton?.action_key || selectedButton?.name || selectedButton?.action_button_label || "",
                workflow_task_node_id: record?.data?.current_node_id || "",
                workflow_duplicate_confirmed: suppressWorkflowConfirm,
                workflow_skip_config_confirm: suppressWorkflowConfirm,
            };
            console.log("Clicked button:", selectedButton);

            const usedButtonRequiredSnapshot = this._applyButtonRequiredFieldsForValidation(
                record,
                selectedButton
            );
            if (!usedButtonRequiredSnapshot) {
                await this._refreshRuntimeFieldStatesForAction(record, selectedButton);
            }

            if (!this._validateRecordBeforeSave(record)) {
                this._clearDuplicateRetryIntent();
                return;
            }

            this._storeDuplicateRetryIntent(record, selectedButton);
            try {
                // .save() returns true if validation passes and data is written
                const isValid = await record.save();
                if (!isValid) {
                    // Validation failed: Odoo UI will show red fields automatically
                    return;
                }
            } catch (error) {
                if (!this._isWorkflowSaveAccessError(error)) {
                    throw error;
                }
                if (!record?.resId) {
                    this._clearDuplicateRetryIntent();
                    this.notification.add(
                        _t("The request was not saved because you do not have permission to create this workflow request. Please contact Workflow Admin."),
                        { type: "danger", sticky: true }
                    );
                    console.warn(
                        "Workflow action stopped because the new request could not be saved with the current user's access rights.",
                        error
                    );
                    return;
                }
                await this._resetRecordAfterSaveAccessError(record);
                console.warn(
                    "Workflow action save bypass activated after access-denied form save.",
                    error
                );
            }
            const resId = record?.resId || this.props.record?.resId || this.resId;
            if (!resId) {
                this.notification.add(
                    _t("The request was saved, but the workflow action could not find the saved record. Please reload and try again."),
                    { type: "danger", sticky: true }
                );
                return;
            }
            this.resId = resId;

            // Call the server method
            const result = await this.orm.call(record.resModel, "action_do_transition", [[resId]], {
                button: selectedButton,
                show_dialog: true,
                context: workflowContext,
            });
            const opensDialog = this._isDialogAction(result);
            if (opensDialog) {
                this._activateDialogButtonGuard(buttonSnapshotBeforeAction);
            }
            const beforeDialogWriteDate = opensDialog ? await this._readRecordWriteDate(record) : "";
            if (result && result.type) {
                await this.action.doAction(
                    result,
                    opensDialog
                        ? {
                              onClose: () => {
                                  this._restorePreservedButtons(record);
                                  this._releaseDialogButtonGuard();
                                  this._queueDialogCloseFollowUp(record, beforeDialogWriteDate);
                              },
                          }
                        : {}
                );
            }
            if (!opensDialog) {
                await this._reloadRecordModel(record);
            }
            this._clearDuplicateRetryIntent();
        } catch (error) {
            console.error(error);
            this._releaseDialogButtonGuard();
            this._clearDuplicateRetryIntent();
            this._notifyActionError(error);
        } finally {
            this.ui.unblock();
        }
    }

    async onClick_bk(button) {

        this.ui.block();

        try {
            const record = this.props.record;
            const workflowContext = {
                view_id: this.env.config?.viewId || false,
                meta_action_id: button?.meta_action_id || false,
                workflow_action_key: button?.action_key || button?.name || button?.action_button_label || "",
                workflow_task_node_id: record?.data?.current_node_id || "",
            };
            console.log("Clicked button:", button);

            // the required fields for that specific button
            const requiredFields = button.required_fields || [];

            // all required fields for all available buttons
            const allRequiredFields = button.all_require_fields || []; 

            // clear the validtion for all fields
            record._unsetRequiredFields.clear();
            record._invalidFields.clear();

            for (var fieldName of allRequiredFields) {
                // this means that field is excluded from validation
                if (record.activeFields[fieldName]) {
                    record.activeFields[fieldName].invisible = true; 
                }
            }

            // if that button has required fields
            if (requiredFields.length > 0) {
                // now we put that field back to validation
                for (var fieldName of requiredFields) {
                    if (record.activeFields[fieldName]) {
                        record.activeFields[fieldName].invisible = false; 
                    }
                }

                // save() is to validate
                // if validate failed, just exit
                if (! await record._save()) {
                    return
                }

                // call to server to update the data
                // await this.orm.call(record.resModel, "action_do_transition", [[this.resId]], {button: button}, {});
                try {
                    // Call the server method
                    const result = await this.orm.call(record.resModel, "action_do_transition", [[this.resId]], {
                        button: button,
                        context: workflowContext,
                    });
                    if (result && result.type) {
                        await this.action.doAction(result);
                        await record.load();
                    } else {
                        await record.load();
                        console.log("No action returned, transition completed directly.");
                    }
                } catch (error) {
                    console.error("RPC Error:", error);
                    alert(error.message || "Server Error");  // simple popup for errors
                }

             } else {
                // if that button has no required field
                // unused code
                // we force all a
                // await allRequiredFields.forEach(element => {
                //     record.activeFields[element].invisible = true; 
                // }); 

                // validate
                await record._save();

                // restore all active fields
                await record._restoreActiveFields();

                // call to server to update the data
                // await this.orm.call(record.resModel, "action_do_transition", [[this.resId]], {button: button}, {});
                const result = await this.orm.call(record.resModel, "action_do_transition", [[this.resId]], {
                    button: button,
                    context: workflowContext,
                });
                if (result && result.type) {
                    await this.action.doAction(result);
                    await record.load();
                } else {
                    await record.load();
                    console.log("No action returned, transition completed directly.");
                }
            }

        } catch (error) {
            console.error(error);
        } finally {
            this.ui.unblock();
        }
    }
}

export const DynamicActionButton = {
    component: DynamicTransitionButtons,
}

registry.category("view_widgets").add("approval_buttons", DynamicActionButton);
