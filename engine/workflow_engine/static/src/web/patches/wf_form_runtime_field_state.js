/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { useBus } from "@web/core/utils/hooks";
import { FormController } from "@web/views/form/form_controller";
import { onMounted, onWillStart, onWillUnmount, useEffect } from "@odoo/owl";

import {
    applyWorkflowFieldStateMap,
    applyWorkflowNodeStateMap,
    applyWorkflowRuntimeFieldLists,
    isWorkflowStudioEditorActive,
    normalizeRuntimeFieldList,
    serializeWorkflowSnapshot,
} from "@workflow_engine/web/utils/wf_field_state_utils";

function fieldSelectorByName(fieldName) {
    const escaped = typeof CSS !== "undefined" && CSS.escape ? CSS.escape(fieldName) : fieldName;
    return `.o_field_widget[name="${escaped}"], [name="${escaped}"].o_field_widget`;
}

function isWorkflowRuntimeRecord(record) {
    if (!record) {
        return false;
    }
    const data = record.data || {};
    const activeFields = record.activeFields || {};
    const workflowKeys = [
        "x_approval_base_id",
        "visible_buttons",
        "current_node_id",
        "wf_current_node_id",
        "wf_action_key",
        "is_user_has_permission",
        "required_fields",
        "readonly_fields",
        "invisible_fields",
    ];
    return workflowKeys.some((key) => key in data || key in activeFields);
}

function getWorkflowSnapshotFingerprint(record) {
    if (!record || !isWorkflowRuntimeRecord(record)) {
        return "";
    }
    const snapshot = { ...(serializeWorkflowSnapshot(record) || {}) };
    const ignoredKeys = [
        "visible_buttons",
        "required_fields",
        "readonly_fields",
        "invisible_fields",
        "wf_action_key",
        "wf_current_node_id",
        "wf_actor_uid",
        "wf_actor_name",
        "wf_actor_login",
        "wf_actor_department_name",
        "wf_actor_position_name",
        "wf_actor_group_xmlids",
        "wf_actor_is_manager",
        "wf_actor_is_hod",
    ];
    for (const key of ignoredKeys) {
        delete snapshot[key];
    }
    return JSON.stringify(snapshot);
}

function hasAppliedWorkflowFieldState(record, fingerprint) {
    if (!record || record.__wfRuntimeAppliedFingerprint !== fingerprint) {
        return false;
    }
    const appliedLists = record.__wfRuntimeAppliedFieldLists || {};
    for (const key of ["required_fields", "readonly_fields", "invisible_fields"]) {
        if (!(key in appliedLists)) {
            return false;
        }
        const currentList = normalizeRuntimeFieldList(record.data?.[key]);
        const appliedList = normalizeRuntimeFieldList(appliedLists[key]);
        if (JSON.stringify(currentList) !== JSON.stringify(appliedList)) {
            return false;
        }
    }
    const managedFields = Array.isArray(record.__wfRuntimeManagedFields)
        ? record.__wfRuntimeManagedFields
        : [];
    if (!managedFields.length) {
        return Boolean(record.__wfRuntimeAppliedEmptyState);
    }
    return managedFields.every((fieldName) => {
        const activeField = record.activeFields?.[fieldName];
        const appliedState = record.__wfRuntimeAppliedFieldStates?.[fieldName] || {};
        return Boolean(activeField?.__wf_runtime_applied) &&
            activeField.invisible === appliedState.invisible &&
            activeField.readonly === appliedState.readonly &&
            activeField.required === appliedState.required;
    });
}

patch(FormController.prototype, {
    _wfMarkActorUiSnapshotStale(record = this.model?.root) {
        if (!record || !isWorkflowRuntimeRecord(record)) {
            return;
        }
        record.__wfActorUiSnapshotLoaded = false;
    },

    _wfApplyActorUiSnapshot(record, snapshot) {
        if (!record || !snapshot || typeof snapshot !== "object") {
            return false;
        }
        const data = record.data || {};
        const nextButtons = Array.isArray(snapshot.visible_buttons) ? snapshot.visible_buttons : [];
        const nextPermission = Boolean(snapshot.is_user_has_permission);
        const nextCanDelegate = Boolean(snapshot.is_user_can_delegate);
        const previousButtons = JSON.stringify(data.visible_buttons || []);
        const previousPermission = Boolean(data.is_user_has_permission);
        const previousCanDelegate = Boolean(data.is_user_can_delegate);
        const wasLoaded = record.__wfActorUiSnapshotLoaded === true;

        let changed = false;
        if (previousButtons !== JSON.stringify(nextButtons)) {
            data.visible_buttons = nextButtons;
            changed = true;
            this.env.bus.trigger("WF-APPROVAL-BUTTONS:UPDATE", {
                resModel: record.resModel,
                resId: record.resId || false,
                buttons: nextButtons,
            });
        }
        if (previousPermission !== nextPermission) {
            data.is_user_has_permission = nextPermission;
            changed = true;
        }
        if (previousCanDelegate !== nextCanDelegate) {
            data.is_user_can_delegate = nextCanDelegate;
            changed = true;
        }

        record.__wfActorUiSnapshotLoaded = true;
        const loadedChanged = !wasLoaded;
        if ((changed || loadedChanged) && typeof record._setEvalContext === "function") {
            record._setEvalContext();
        }
        if ((changed || loadedChanged) && typeof record.model?.notify === "function") {
            record.model.notify();
        }
        return changed || loadedChanged;
    },

    async _wfReadActorUiSnapshot(record, { snapshotValues = {}, taskNodeId = false } = {}) {
        if (!record || !isWorkflowRuntimeRecord(record)) {
            return null;
        }
        const isVirtual = !record.resId;
        const method = isVirtual
            ? "workflow_get_actor_ui_snapshot_virtual"
            : "workflow_get_actor_ui_snapshot";
        const args = isVirtual ? [] : [[record.resId]];
        return this.orm.call(record.resModel, method, args, {
            snapshot_values: snapshotValues,
            task_node_id: taskNodeId || false,
        });
    },

    _wfIsDryRunMode() {
        return Boolean(
            this.props?.context?.wf_dryrun_mode ||
                this.model?.config?.context?.wf_dryrun_mode ||
                this.model?.root?.context?.wf_dryrun_mode
        );
    },

    _wfHandleFormReentry(reason = "reentry") {
        if (!this.__wfState?.enabled) {
            return;
        }
        const record = this.model?.root;
        if (!record || !isWorkflowRuntimeRecord(record)) {
            return;
        }
        const now = Date.now();
        if (now - (this.__wfState.lastReentryAt || 0) < 500) {
            return;
        }
        this.__wfState.lastReentryAt = now;
        this.__wfState.autoEditTried = false;
        this.__wfState.suppressRecordChangedUntil = Math.max(
            this.__wfState.suppressRecordChangedUntil || 0,
            now + 300
        );
        this._wfMarkActorUiSnapshotStale(record);
        this._wfScheduleRefresh(reason);
    },

    _wfDryRunWizardId() {
        return (
            this.props?.context?.wf_dryrun_wizard_id ||
            this.model?.config?.context?.wf_dryrun_wizard_id ||
            this.model?.root?.context?.wf_dryrun_wizard_id ||
            false
        );
    },

    _wfNotify(message, type = "warning") {
        this.env.services?.notification?.add(message, { type });
    },

    _wfHandleRuntimeRefreshRequest(event) {
        if (!this.__wfState?.enabled) {
            return;
        }
        const detail = event?.detail || event || {};
        const record = this.model?.root;
        if (!record || !isWorkflowRuntimeRecord(record)) {
            return;
        }
        if (detail.resModel && detail.resModel !== record.resModel) {
            return;
        }
        if ("resId" in detail && (detail.resId || false) !== (record.resId || false)) {
            return;
        }
        const now = Date.now();
        const suppressMs = Number(detail.suppressMs) || 500;
        this.__wfState.suppressRecordChangedUntil = Math.max(
            this.__wfState.suppressRecordChangedUntil || 0,
            now + suppressMs
        );
        if (detail.phase === "before") {
            return;
        }
        if (this.__wfState.timer) {
            clearTimeout(this.__wfState.timer);
            this.__wfState.timer = null;
        }
        this.__wfState.lastFingerprint = "";
        this.__wfState.autoEditTried = false;
        void this._wfRefreshFieldStates({
            reason: detail.reason || "external_refresh",
            force: detail.force !== false,
            skipActorSnapshot: Boolean(detail.skipActorSnapshot),
        });
    },

    setup() {
        super.setup(...arguments);

        this.__wfState = {
            enabled: !isWorkflowStudioEditorActive(),
            timer: null,
            seq: 0,
            postSaveSeq: 0,
            postSaveTimer: null,
            autoEditTried: false,
            inFlight: false,
            queuedReason: "",
            queuedForce: false,
            suppressRecordChangedUntil: 0,
            lastFingerprint: "",
            lastReentryAt: 0,
        };
        if (!this.__wfState.enabled) {
            return;
        }
        this._wfMarkActorUiSnapshotStale(this.model?.root);

        useBus(this.env.bus, "WF-RUNTIME-FIELD-STATE:REFRESH", (event) => {
            this._wfHandleRuntimeRefreshRequest(event);
        });

        const previousOnRecordChanged = this.model.hooks.onRecordChanged;
        this.model.hooks.onRecordChanged = async (record, changes) => {
            if (previousOnRecordChanged) {
                await previousOnRecordChanged(record, changes);
            }
            if (Date.now() < (this.__wfState?.suppressRecordChangedUntil || 0)) {
                return;
            }
            if (
                record === this.model.root &&
                changes &&
                Object.keys(changes).length &&
                isWorkflowRuntimeRecord(record)
            ) {
                this._wfScheduleRefresh("record_change");
            }
        };

        onWillStart(async () => {
            // Preload workflow field states before first render to avoid
            // delayed/flicker appearance of wf_field slots.
            await this._wfRefreshFieldStates({ reason: "open" });
        });

        onMounted(() => {
            if (typeof window !== "undefined") {
                this.__wfWindowFocusHandler = () => this._wfHandleFormReentry("window_focus");
                this.__wfPageShowHandler = () => this._wfHandleFormReentry("pageshow");
                window.addEventListener("focus", this.__wfWindowFocusHandler);
                window.addEventListener("pageshow", this.__wfPageShowHandler);
            }
            if (typeof document !== "undefined") {
                this.__wfVisibilityHandler = () => {
                    if (document.visibilityState === "visible") {
                        this._wfHandleFormReentry("visibility_visible");
                    }
                };
                document.addEventListener("visibilitychange", this.__wfVisibilityHandler);
            }
            this._wfEnsureEditMode();
            this._wfScheduleEnsureEditMode("mounted");
        });

        onWillUnmount(() => {
            if (this.__wfState?.timer) {
                clearTimeout(this.__wfState.timer);
                this.__wfState.timer = null;
            }
            if (this.__wfState?.postSaveTimer) {
                clearTimeout(this.__wfState.postSaveTimer);
                this.__wfState.postSaveTimer = null;
            }
            if (typeof window !== "undefined") {
                if (this.__wfWindowFocusHandler) {
                    window.removeEventListener("focus", this.__wfWindowFocusHandler);
                }
                if (this.__wfPageShowHandler) {
                    window.removeEventListener("pageshow", this.__wfPageShowHandler);
                }
            }
            if (typeof document !== "undefined" && this.__wfVisibilityHandler) {
                document.removeEventListener("visibilitychange", this.__wfVisibilityHandler);
            }
        });

        useEffect(
            () => {
                this._wfMarkActorUiSnapshotStale(this.model?.root);
                this._wfScheduleRefresh("node_change");
            },
            () => [this.model.root?.resId, this.model.root?.data?.current_node_id]
        );

        useEffect(
            () => {
                this._wfScheduleRefresh("snapshot_change");
            },
            () => [getWorkflowSnapshotFingerprint(this.model.root)]
        );

        // Re-check edit mode when runtime permission indicators change.
        useEffect(
            () => {
                this._wfEnsureEditMode();
            },
            () => [
                this.model.root?.resId,
                this.model.root?.data?.is_user_has_permission,
                this.model.root?.data?.is_admin,
                this.model.root?.data?.is_workflow_admin,
                JSON.stringify(this.model.root?.data?.visible_buttons || []),
            ]
        );

        useEffect(
            () => {
                const record = this.model?.root;
                if (!record || !isWorkflowRuntimeRecord(record)) {
                    return;
                }
                const data = record.data || {};
                const rawButtons = data.visible_buttons;
                const buttonCount = Array.isArray(rawButtons)
                    ? rawButtons.length
                    : typeof rawButtons === "string"
                        ? (() => {
                              try {
                                  const parsed = JSON.parse(rawButtons);
                                  return Array.isArray(parsed) ? parsed.length : 0;
                              } catch {
                                  return 0;
                              }
                          })()
                        : 0;
                if (buttonCount > 0) {
                    return;
                }
                if (!data.is_user_has_permission && !data.is_user_can_delegate) {
                    return;
                }
                this._wfHandleFormReentry("actor_ui_guard");
            },
            () => [
                this.model.root?.resId,
                this.model.root?.data?.is_user_has_permission,
                this.model.root?.data?.is_user_can_delegate,
                JSON.stringify(this.model.root?.data?.visible_buttons || []),
            ]
        );
    },

    async wfBackToDryRun() {
        if (!this._wfIsDryRunMode()) {
            return;
        }
        const wizardId = this._wfDryRunWizardId();
        if (!wizardId) {
            this._wfNotify(_t("Dry-run session not found. Please reopen the wizard."), "danger");
            return;
        }
        const action = await this.orm.call("workflow.dryrun.wizard", "action_reopen_session", [[wizardId]]);
        if (action) {
            await this.actionService.doAction(this._wfNormalizeAction(action));
        }
    },

    _wfNormalizeAction(action) {
        if (!action || typeof action !== "object") {
            return action;
        }
        if (action.type !== "ir.actions.act_window" || Array.isArray(action.views)) {
            return action;
        }
        const normalized = { ...action };
        const modeTokens = String(normalized.view_mode || "form")
            .split(",")
            .map((token) => token.trim())
            .filter(Boolean);
        const primaryMode = modeTokens[0] || "form";
        const rawViewId = Array.isArray(normalized.view_id) ? normalized.view_id[0] : normalized.view_id;
        normalized.views = [[rawViewId || false, primaryMode]];
        return normalized;
    },

    async wfRunDryRunClick() {
        return this._wfRunDryRunVirtual();
    },

    async _wfRunDryRunVirtual() {
        const record = this.model?.root;
        if (!record) {
            return false;
        }
        const wizardId = this._wfDryRunWizardId();
        if (!wizardId) {
            this._wfNotify(_t("Dry-run session not found. Please reopen the wizard."), "danger");
            return false;
        }
        const isValid = await this._wfValidateBeforePersist();
        if (!isValid) {
            return false;
        }
        const action = await this.orm.call(record.resModel, "workflow_run_dryrun_virtual", [], {
            wizard_id: wizardId,
            snapshot_values: serializeWorkflowSnapshot(record),
            view_id: this.env.config?.viewId || false,
        });
        if (action) {
            await this.actionService.doAction(this._wfNormalizeAction(action));
        }
        return false;
    },

    _wfScheduleEnsureEditMode(reason = "scheduled") {
        if (!this.__wfState?.enabled) {
            return;
        }
        const delays = reason === "mounted" ? [0, 120, 500] : [0];
        for (const delay of delays) {
            setTimeout(() => {
                const record = this.model?.root;
                if (record && !record.resId && isWorkflowRuntimeRecord(record)) {
                    this._wfEnsureEditMode();
                }
            }, delay);
        }
    },

    _wfSchedulePostSaveReentry(reason = "save_after") {
        if (!this.__wfState?.enabled) {
            return;
        }
        const runSeq = ++this.__wfState.postSaveSeq;
        if (this.__wfState.postSaveTimer) {
            clearTimeout(this.__wfState.postSaveTimer);
            this.__wfState.postSaveTimer = null;
        }
        const refreshOnce = async (attempt = 0) => {
            if (!this.__wfState?.enabled || runSeq !== this.__wfState.postSaveSeq) {
                return;
            }
            const record = this.model?.root;
            if (!record || !isWorkflowRuntimeRecord(record)) {
                return;
            }
            this.__wfState.lastFingerprint = "";
            this.__wfState.autoEditTried = false;
            this.__wfState.suppressRecordChangedUntil = Date.now() + 400;
            this._wfMarkActorUiSnapshotStale(record);
            await this._wfRefreshFieldStates({ reason, force: true });
            if (!this.__wfState?.enabled || runSeq !== this.__wfState.postSaveSeq) {
                return;
            }
            const refreshedRecord = this.model?.root;
            if (!refreshedRecord || !isWorkflowRuntimeRecord(refreshedRecord)) {
                return;
            }
            const needsRetry =
                attempt === 0 &&
                !refreshedRecord.isInEdition &&
                (
                    refreshedRecord.__wfActorUiSnapshotLoaded !== true ||
                    this._wfCanAutoEdit(refreshedRecord)
                );
            if (needsRetry) {
                this.__wfState.postSaveTimer = setTimeout(() => {
                    this.__wfState.postSaveTimer = null;
                    void refreshOnce(1);
                }, 250);
            }
        };
        void refreshOnce(0);
    },

    _wfScheduleRefresh(reason = "debounced", { force = false } = {}) {
        if (!this.__wfState?.enabled) {
            return;
        }
        if (!isWorkflowRuntimeRecord(this.model?.root)) {
            return;
        }
        if (this.__wfState.timer) {
            clearTimeout(this.__wfState.timer);
        }
        this.__wfState.timer = setTimeout(() => {
            this._wfRefreshFieldStates({ reason, force });
        }, reason === "record_change" ? 220 : 80);
    },

    async _wfRefreshFieldStates({
        reason = "manual",
        actionKey = "",
        metaActionId = false,
        force = false,
        skipActorSnapshot = false,
    } = {}) {
        if (!this.__wfState?.enabled) {
            return;
        }
        if (this.__wfState.inFlight) {
            this.__wfState.queuedReason = reason || "queued";
            this.__wfState.queuedForce = this.__wfState.queuedForce || Boolean(force);
            return;
        }
        const record = this.model.root;
        if (!record) {
            return;
        }
        if (!isWorkflowRuntimeRecord(record)) {
            return;
        }
        if (typeof this.model?._askChanges === "function") {
            await this.model._askChanges();
        }
        // Zero-trust: let server resolve effective actor node (especially branch mode).
        // Keep optional explicit override only when caller intentionally sets it.
        const taskNodeId =
            record?.data?.workflow_task_node_id ||
            record?.data?.current_node_id ||
            record?.data?.wf_current_node_id ||
            "";
        const snapshotValues = serializeWorkflowSnapshot(record);
        const isVirtual = !record.resId;
        const method = isVirtual
            ? "workflow_get_runtime_field_state_map_virtual"
            : "workflow_get_runtime_field_state_map";
        const args = isVirtual ? [] : [[record.resId]];
        const fingerprint = JSON.stringify({
            model: record.resModel,
            id: record.resId || 0,
            node: taskNodeId || "",
            action: actionKey || "",
            meta: metaActionId || false,
            view: this.env.config?.viewId || false,
            snapshot: snapshotValues,
        });
        const skipHeavyPayload =
            !force &&
            fingerprint === this.__wfState.lastFingerprint &&
            hasAppliedWorkflowFieldState(record, fingerprint);
        if (!skipHeavyPayload) {
            this.__wfState.lastFingerprint = fingerprint;
        }
        const callSeq = ++this.__wfState.seq;
        this.__wfState.inFlight = true;
        try {
            const [payload, actorUiSnapshot] = await Promise.all([
                skipHeavyPayload
                    ? Promise.resolve(null)
                    : this.orm.call(
                          record.resModel,
                          method,
                          args,
                          {
                              action_key: actionKey || "",
                              task_node_id: taskNodeId || false,
                              meta_action_id: metaActionId || false,
                              view_id: this.env.config?.viewId || false,
                              snapshot_values: snapshotValues,
                          }
                      ),
                skipActorSnapshot
                    ? Promise.resolve(null)
                    : this._wfReadActorUiSnapshot(record, {
                          snapshotValues,
                          taskNodeId,
                      }).catch((err) => {
                          console.warn("Workflow actor UI snapshot refresh failed", err);
                          return null;
                      }),
            ]);
            if (callSeq !== this.__wfState.seq) {
                return;
            }
            this.__wfState.suppressRecordChangedUntil = Date.now() + 300;
            let hasRuntimeListChanges = false;
            let hasFieldChanges = false;
            let hasNodeChanges = false;
            if (!skipHeavyPayload) {
                hasRuntimeListChanges = applyWorkflowRuntimeFieldLists(record, payload || {});
                hasFieldChanges = applyWorkflowFieldStateMap(record, payload?.field_state_map || {});
                hasNodeChanges = applyWorkflowNodeStateMap(record, payload?.node_state_map || {});
                record.__wfRuntimeAppliedFingerprint = fingerprint;
                record.__wfRuntimeAppliedEmptyState = !Object.keys(payload?.field_state_map || {}).length;
            }
            const actorUiChanged = skipActorSnapshot
                ? false
                : this._wfApplyActorUiSnapshot(record, actorUiSnapshot);
            await this._wfEnsureEditMode();
            const hasChanges =
                hasRuntimeListChanges ||
                hasFieldChanges ||
                hasNodeChanges ||
                actorUiChanged;
            if (!record.resId) {
                this._wfScheduleEnsureEditMode("virtual_refresh");
            }
            if ((hasChanges || force) && typeof this.render === "function") {
                // Ensure group slot visibility expressions re-evaluate immediately,
                // avoiding UI updates that only appear after user scroll/repaint.
                if (force || actorUiChanged || reason !== "record_change") {
                    this.render();
                }
            }
        } catch (error) {
            // Allow immediate retry after a failed call.
            this.__wfState.lastFingerprint = "";
            // Keep wf_form resilient: ignore policy refresh failures and preserve form usability.
            console.warn("Workflow runtime field-state refresh failed", error);
        } finally {
            this.__wfState.inFlight = false;
            if (this.__wfState.queuedReason) {
                const queuedReason = this.__wfState.queuedReason;
                const queuedForce = this.__wfState.queuedForce;
                this.__wfState.queuedReason = "";
                this.__wfState.queuedForce = false;
                this._wfScheduleRefresh(queuedReason, { force: queuedForce });
            }
        }
    },

    _wfCanAutoEdit(record) {
        const data = record?.data || {};
        if (!record?.resId) {
            return true;
        }
        if (record.__wfActorUiSnapshotLoaded !== true && !record.isInEdition) {
            return false;
        }
        // While a post-save or local x2many refresh is reloading the actor snapshot,
        // preserve an already editable form from flickering readonly.
        const rawPermission = data.is_user_has_permission;
        if (
            rawPermission === true ||
            rawPermission === 1 ||
            rawPermission === "1" ||
            (typeof rawPermission === "string" && /^(true|1)$/i.test(rawPermission.trim()))
        ) {
            return true;
        }
        // A business-action actor may have a visible button without general edit rights.
        // Auto-edit is therefore controlled only by the server permission snapshot.
        return false;
    },

    async _wfEnsureEditMode() {
        if (!this.__wfState?.enabled) {
            return;
        }
        const record = this.model?.root;
        if (!record) {
            return;
        }
        if (!isWorkflowRuntimeRecord(record)) {
            return;
        }
        const canAutoEdit = this._wfCanAutoEdit(record);
        if (record.isInEdition && !canAutoEdit) {
            try {
                await record.switchMode("readonly");
                if (typeof this.model?.notify === "function") {
                    this.model.notify();
                }
                if (typeof this.render === "function") {
                    this.render();
                }
            } catch {
                // Keep form usable if readonly switch cannot be applied.
            }
            this.__wfState.autoEditTried = false;
            return;
        }
        if (record.isInEdition) {
            this.__wfState.autoEditTried = true;
            return;
        }
        if (!canAutoEdit) {
            this.__wfState.autoEditTried = false;
            return;
        }
        if (this.__wfState.autoEditTried) {
            return;
        }
        try {
            await record.switchMode("edit");
            this.__wfState.autoEditTried = true;
            if (typeof this.model?.notify === "function") {
                this.model.notify();
            }
            if (typeof this.render === "function") {
                this.render();
            }
        } catch {
            // If mode switch fails (for example rights), keep form usable in readonly.
            // Allow later retries (for example after first mount/render timing settles).
            this.__wfState.autoEditTried = false;
            if (!record.resId) {
                setTimeout(() => {
                    this._wfEnsureEditMode();
                }, 250);
            }
        }
    },

    async _wfValidateBeforePersist() {
        if (!this.__wfState?.enabled) {
            return true;
        }
        const record = this.model?.root;
        if (!record || !record.isInEdition) {
            return true;
        }
        await this._wfRefreshFieldStates({ reason: "before_submit", skipActorSnapshot: true });
        try {
            const isValid = await record.checkValidity({ displayNotification: true });
            this._wfSyncInvalidFieldStyles(record);
            if (!isValid) {
                this._wfFocusFirstInvalidField(record);
            }
            return isValid;
        } catch {
            this._wfSyncInvalidFieldStyles(record);
            return false;
        }
    },

    _wfSyncInvalidFieldStyles(record) {
        if (typeof document === "undefined") {
            return;
        }
        const root = this.root?.el || this.el || document;
        if (!root?.querySelectorAll) {
            return;
        }
        for (const element of root.querySelectorAll(".wf_runtime_required_invalid")) {
            element.classList.remove("wf_runtime_required_invalid");
        }
        const invalidFields = record?._invalidFields ? Array.from(record._invalidFields) : [];
        for (const fieldName of invalidFields) {
            const element = root.querySelector(fieldSelectorByName(fieldName));
            if (element) {
                element.classList.add("wf_runtime_required_invalid");
            }
        }
    },

    _wfFocusFirstInvalidField(record) {
        if (typeof document === "undefined") {
            return;
        }
        const invalidFields = record?._invalidFields ? Array.from(record._invalidFields) : [];
        if (!invalidFields.length) {
            return;
        }
        const root = this.root?.el || this.el || document;
        const firstField = invalidFields[0];
        const element = root?.querySelector?.(fieldSelectorByName(firstField));
        if (!element) {
            return;
        }
        element.scrollIntoView({ behavior: "smooth", block: "center" });
        const focusable = element.querySelector("input, textarea, select, button, [tabindex]");
        if (focusable && typeof focusable.focus === "function") {
            focusable.focus({ preventScroll: true });
        }
    },

    async beforeExecuteActionButton(clickParams) {
        if (this._wfIsDryRunMode() && clickParams?.special !== "cancel") {
            this._wfNotify(_t("Form action buttons are disabled in dry-run mode. Use Run Dry Run instead."));
            return false;
        }
        if (this.__wfState?.enabled && clickParams?.special !== "cancel") {
            const isValid = await this._wfValidateBeforePersist();
            if (!isValid) {
                return false;
            }
        }
        return super.beforeExecuteActionButton(...arguments);
    },

    async afterExecuteActionButton(clickParams) {
        const result = await super.afterExecuteActionButton(...arguments);
        if (this.__wfState?.enabled && clickParams?.special !== "cancel") {
            for (const delay of [0, 150, 500, 1000]) {
                setTimeout(() => {
                    this._wfScheduleRefresh("action_button_after");
                }, delay);
            }
        }
        return result;
    },

    async shouldExecuteAction(item) {
        if (this._wfIsDryRunMode() && !item?.skipSave) {
            this._wfNotify(_t("Form actions are disabled in dry-run mode. Use Run Dry Run instead."));
            return false;
        }
        if (this.__wfState?.enabled && !item?.skipSave) {
            const isValid = await this._wfValidateBeforePersist();
            if (!isValid) {
                return false;
            }
        }
        return super.shouldExecuteAction(...arguments);
    },

    async saveButtonClicked(params = {}) {
        if (this._wfIsDryRunMode()) {
            return this._wfRunDryRunVirtual();
        }
        return super.saveButtonClicked(...arguments);
    },

    async save(params = {}) {
        if (this._wfIsDryRunMode()) {
            this._wfNotify(_t("Saving is disabled in dry-run mode. Use Run Dry Run instead."));
            return false;
        }
        if (this.__wfState?.enabled) {
            const isValid = await this._wfValidateBeforePersist();
            if (!isValid) {
                return false;
            }
        }
        if (this.__wfState?.enabled) {
            this.__wfState.suppressRecordChangedUntil = Date.now() + 400;
        }
        const result = await super.save(...arguments);
        if (this.__wfState?.enabled && result !== false) {
            this._wfSchedulePostSaveReentry("save_after");
        }
        return result;
    },
});
