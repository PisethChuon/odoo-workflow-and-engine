/** @odoo-module **/

import { onWillStart, onWillUnmount, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formView } from "@web/views/form/form_view";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { markup } from "@odoo/owl";

export class CreateApprovalRequest extends formView.Controller {
    
    setup() {
        super.setup();
        this.action = useService("action");
        this.orm = useService("orm");
        this.bus = useService("bus_service");
        this._wfMiniBusRequestId = null;
        this._wfMiniBusChannel = null;
        this._wfMiniBusCallback = null;
        this._wfMiniBusEnsureSeq = 0;
        this._wfMiniReloadTimer = null;
        this._wfMiniReloadInFlight = false;
        this._wfMiniReloadQueued = false;
        this._wfPostSaveReloadInFlight = false;
        this._wfActionSaveNeedsReload = false;
        this._wfActionSaveWasNew = false;
        this._wfLastPostSaveReloadAt = 0;
        this._wfSkipNextDuplicateCheck = false;

        onWillStart(async () => {
            await this._wfRedirectBaseRequestToChildForm();
        });

        useEffect(
            () => {
                this._wfEnsureMiniBusChannel();
            },
            () => [
                this.model?.root?.resId || 0,
                this._wfReadM2OId(this.model?.root?.data?.x_approval_base_id) || 0,
                this.props?.resModel || "",
            ]
        );

        onWillUnmount(() => {
            this._wfMiniBusEnsureSeq += 1;
            this._wfUnregisterMiniBusChannel();
            if (this._wfMiniReloadTimer) {
                clearTimeout(this._wfMiniReloadTimer);
                this._wfMiniReloadTimer = null;
            }
        });
    }

    async _wfRedirectBaseRequestToChildForm() {
        const record = this.model?.root;
        if (!record?.resId) {
            return;
        }
        const modelName = this.props?.resModel || record.resModel || "";
        if (modelName !== "workflow.base.approval.request") {
            return;
        }
        const actionContext = this.props?.context || {};
        if (actionContext.wf_redirected_from_base) {
            return;
        }
        try {
            const rows = await this.orm.read(
                "workflow.base.approval.request",
                [record.resId],
                ["res_model_name"]
            );
            const targetModel = rows?.[0]?.res_model_name || "";
            if (!targetModel || targetModel === "workflow.base.approval.request") {
                return;
            }
            const childIds = await this.orm.call(
                targetModel,
                "search",
                [[["x_approval_base_id", "=", record.resId]]],
                { limit: 1 }
            );
            const childId = Array.isArray(childIds) ? childIds[0] : null;
            if (!childId) {
                return;
            }
            await this.action.doAction({
                type: "ir.actions.act_window",
                res_model: targetModel,
                res_id: childId,
                views: [[false, "form"]],
                view_mode: "form",
                target: "current",
                context: {
                    ...actionContext,
                    wf_redirected_from_base: true,
                },
            });
        } catch (error) {
            console.warn("workflow base->child redirect skipped", error);
        }
    }

    _wfIsDryRunMode() {
        return Boolean(
            this.props?.context?.wf_dryrun_mode ||
            this.model?.root?.context?.wf_dryrun_mode ||
            this.model?.root?.evalContext?.context?.wf_dryrun_mode
        );
    }

    _wfGetDuplicateRetryIntent(modelName) {
        if (typeof window === "undefined") {
            return null;
        }
        const intent = window.__wfDuplicateRetryIntent;
        if (!intent) {
            return null;
        }
        if (intent.resModel !== modelName) {
            return null;
        }
        if ((Date.now() - Number(intent.ts || 0)) > 15000) {
            delete window.__wfDuplicateRetryIntent;
            return null;
        }
        return intent;
    }

    _wfClearDuplicateRetryIntent() {
        if (typeof window === "undefined") {
            return;
        }
        delete window.__wfDuplicateRetryIntent;
    }

    _wfFindApprovalRetryButton(intent) {
        if (!intent?.actionKey || typeof document === "undefined") {
            return null;
        }
        const actionKey = String(intent.actionKey || "").trim();
        if (!actionKey) {
            return null;
        }
        const escaped = typeof CSS !== "undefined" && CSS.escape ? CSS.escape(actionKey) : actionKey;
        return document.querySelector(
            `.wf-approval-actions [data-action-key="${escaped}"]`
        );
    }

    _wfScheduleDuplicateRetry(intent) {
        const approvalButton = this._wfFindApprovalRetryButton(intent);
        const fallbackButton = typeof document !== "undefined"
            ? document.querySelector(".o_form_button_save")
            : null;
        const target = approvalButton || fallbackButton;
        if (!target) {
            this._wfClearDuplicateRetryIntent();
            return;
        }
        setTimeout(() => {
            target.click();
        }, 0);
    }

    async onWillSaveRecord(record, changes) {
        if (this._wfIsDryRunMode()) {
            return;
        }
        // we are only interested in creating new record
        if (record._config.resId) return;
        if (this._wfSkipNextDuplicateCheck) {
            this._wfSkipNextDuplicateCheck = false;
            return;
        }
        
        const modelName = this.props.resModel;
        const dialog = this.env.services.dialog;
        const data = this.model.root.data;
        const retryIntent = this._wfGetDuplicateRetryIntent(modelName);
        const category_id = data.category_id?.id;
        const request_owner_id = data.request_owner_id?.id;
        const request_owner_name = data.request_owner_id?.display_name || "";
        if (!category_id || !request_owner_id) {
            return;
        }
        
        const last_request_ids = await this.orm.call(modelName, "action_find_existing_requests_by_request_owner_id", [category_id, request_owner_id], {});
        
        let ul = '<ul>';
        
        if (last_request_ids && last_request_ids.length > 0) {
            for (const request of last_request_ids) {
                ul += `<li>${request['name']} created on ${request['create_date']} by ${request['create_uid']}</li>`;
            }
            ul += '</ul>';
            
            await dialog.add(ConfirmationDialog, {
                title: "Duplicate Found",
                confirmLabel: "Yes",
                confirm: async () => {
                    await this.orm.call(modelName, "action_complete_existing_request", [last_request_ids.map(request => request['id'])], {});
                    this._wfSkipNextDuplicateCheck = true;
                    if (retryIntent) {
                        retryIntent.skipWorkflowConfirmOnRetry = true;
                    }
                    this._wfScheduleDuplicateRetry(retryIntent);
                    return true;
                },
                cancelLabel: "No",
                cancel: () => {
                    this._wfClearDuplicateRetryIntent();
                },
                body: markup(`Employee: ${request_owner_name} already has the following requests: <br/>${ul}Do you want to cancel them and create a new one?`),
            });
            // await this.orm.call(modelName, "complete_existing_and_create_new", [data], {});
            // this.model.root.notify();
            // this.action.doAction("reload");
            //return;
            return false;
        }
        return;
    }

    _wfReadM2OId(value) {
        if (Array.isArray(value) && value[0]) {
            return Number(value[0]);
        }
        if (value && typeof value === "object" && value.id) {
            return Number(value.id);
        }
        if (typeof value === "number") {
            return Number(value);
        }
        return 0;
    }

    async _wfGetBaseRequestId() {
        const record = this.model?.root;
        if (!record) {
            return null;
        }
        const modelName = this.props?.resModel || record.resModel || "";
        if (modelName === "workflow.base.approval.request") {
            return Number(record.resId || 0) || null;
        }
        const localBaseId = this._wfReadM2OId(record?.data?.x_approval_base_id);
        if (localBaseId) {
            return localBaseId;
        }
        if (!record.resId || !modelName) {
            return null;
        }
        try {
            const rows = await this.orm.read(modelName, [record.resId], ["x_approval_base_id"]);
            return this._wfReadM2OId(rows?.[0]?.x_approval_base_id) || null;
        } catch {
            return null;
        }
    }

    async _wfEnsureMiniBusChannel() {
        const ensureSeq = ++this._wfMiniBusEnsureSeq;
        const requestId = await this._wfGetBaseRequestId();
        if (ensureSeq !== this._wfMiniBusEnsureSeq) {
            return;
        }
        const normalizedRequestId = Number(requestId || 0);
        if (!normalizedRequestId) {
            this._wfUnregisterMiniBusChannel();
            return;
        }
        if (
            this._wfMiniBusRequestId === normalizedRequestId &&
            this._wfMiniBusChannel
        ) {
            return;
        }
        this._wfUnregisterMiniBusChannel();
        this._wfMiniBusRequestId = normalizedRequestId;
        this._wfMiniBusChannel = `workflow_approval.request_${normalizedRequestId}`;
        this.bus.addChannel(this._wfMiniBusChannel);
        this.bus.start();
        this._wfMiniBusCallback = (payload) => {
            if (!payload || Number(payload.request_id) !== this._wfMiniBusRequestId) {
                return;
            }
            this._wfScheduleMiniReload();
        };
        this.bus.subscribe("workflow_approval.request_mini_update", this._wfMiniBusCallback);
    }

    _wfUnregisterMiniBusChannel() {
        if (this._wfMiniBusCallback) {
            this.bus.unsubscribe("workflow_approval.request_mini_update", this._wfMiniBusCallback);
            this._wfMiniBusCallback = null;
        }
        if (this._wfMiniBusChannel) {
            this.bus.deleteChannel(this._wfMiniBusChannel);
            this._wfMiniBusChannel = null;
        }
        this._wfMiniBusRequestId = null;
    }

    _wfScheduleMiniReload() {
        if (this._wfMiniReloadTimer) {
            return;
        }
        this._wfMiniReloadTimer = setTimeout(() => {
            this._wfMiniReloadTimer = null;
            this._wfReloadCurrentRecordFromBus();
        }, 120);
    }

    async _wfReloadCurrentRecordFromBus() {
        if (this._wfMiniReloadInFlight) {
            this._wfMiniReloadQueued = true;
            return;
        }
        const record = this.model?.root;
        if (!record?.resId) {
            return;
        }
        let isDirty = false;
        if (typeof record.isDirty === "function") {
            try {
                isDirty = await record.isDirty();
            } catch {
                isDirty = Boolean(record.dirty);
            }
        } else {
            isDirty = Boolean(record.dirty);
        }
        if (isDirty) {
            return;
        }
        this._wfMiniReloadInFlight = true;
        try {
            if (typeof record.model?.load === "function") {
                await record.model.load({
                    resId: record.resId,
                    resIds: Array.isArray(record.resIds) ? record.resIds : undefined,
                });
                if (typeof record.model?.notify === "function") {
                    record.model.notify();
                }
            } else {
                await record.load();
            }
        } catch (error) {
            console.warn("Workflow realtime mini update refresh failed.", error);
        } finally {
            this._wfMiniReloadInFlight = false;
            if (this._wfMiniReloadQueued) {
                this._wfMiniReloadQueued = false;
                this._wfScheduleMiniReload();
            }
        }
    }

    _wfIsWorkflowRuntimeForm(record = this.model?.root) {
        const data = record?.data || {};
        const activeFields = record?.activeFields || {};
        const workflowKeys = [
            "x_approval_base_id",
            "approver_ids",
            "visible_buttons",
            "current_node_id",
            "is_user_has_permission",
        ];
        return workflowKeys.some((key) => key in data || key in activeFields);
    }

    async _wfReloadAfterDraftSave(wasNew, params = {}) {
        if (this._wfPostSaveReloadInFlight || (!params?.force && params?.reload === false)) {
            return;
        }
        const now = Date.now();
        if (now - (this._wfLastPostSaveReloadAt || 0) < 600) {
            return;
        }
        const record = this.model?.root;
        if (!record?.resId || !this._wfIsWorkflowRuntimeForm(record)) {
            return;
        }
        this._wfPostSaveReloadInFlight = true;
        try {
            this._wfLastPostSaveReloadAt = now;
            await record.model.load({
                resId: record.resId,
                resIds: record.resIds,
            });
            if (typeof record.model?.notify === "function") {
                record.model.notify();
            }
            if (typeof this.render === "function") {
                this.render();
            }
            if (wasNew) {
                await this._wfEnsureMiniBusChannel();
            }
            if (wasNew || params?.forceActionReload) {
                await this.action.doAction("soft_reload");
            }
        } catch (error) {
            console.warn("Workflow post-save reload failed.", error);
        } finally {
            this._wfPostSaveReloadInFlight = false;
        }
    }

    async save(params = {}) {
        const record = this.model?.root;
        const wasNew = Boolean(record && !record.resId);
        const saved = await super.save(...arguments);
        if (saved) {
            await this._wfReloadAfterDraftSave(wasNew, params);
        }
        return saved;
    }

    async beforeExecuteActionButton(clickParams) {
        const record = this.model?.root;
        const wasNew = Boolean(record && !record.resId);
        const saved = await super.beforeExecuteActionButton(...arguments);
        if (saved && clickParams?.special !== "cancel" && wasNew) {
            this._wfActionSaveNeedsReload = true;
            this._wfActionSaveWasNew = wasNew;
        }
        return saved;
    }

    async afterExecuteActionButton(clickParams) {
        const needsReload = this._wfActionSaveNeedsReload;
        const wasNew = this._wfActionSaveWasNew;
        this._wfActionSaveNeedsReload = false;
        this._wfActionSaveWasNew = false;
        await super.afterExecuteActionButton(...arguments);
        if (needsReload && clickParams?.special !== "cancel") {
            await this._wfReloadAfterDraftSave(wasNew, { force: true });
        }
    }

    async saveButtonClicked(params = {}) {
        const record = this.model?.root;
        const wasNew = Boolean(record && !record.resId);
        const saved = await super.saveButtonClicked(...arguments);
        if (saved !== false) {
            await this._wfReloadAfterDraftSave(wasNew, {
                ...params,
                force: true,
                forceActionReload: wasNew,
            });
        }
        return saved;
    }
}

const workflowFormView = {
    ...formView,
    Controller: CreateApprovalRequest,
    props: (genericProps, view) => {
        const props = formView.props(genericProps, view);
        const jsClass = props?.archInfo?.xmlDoc?.getAttribute?.("js_class") || "";
        const tokens = jsClass
            .split(/\s+/)
            .map((token) => token.trim())
            .filter(Boolean);
        const isWorkflowManagedForm =
            tokens.includes("wf_form") || tokens.includes("create_approval_request");
        const canEditFromArch = props?.archInfo?.activeActions?.edit !== false;

        // Keep persisted workflow forms opening in readonly first, then wf_form runtime
        // permission logic promotes active actors to edit mode. Unsaved request forms
        // must open editable so requesters can fill bootstrap data before first save.
        if (isWorkflowManagedForm && canEditFromArch && props.resId) {
            props.readonly = true;
        }

        return props;
    },
};

registry.category("views").add("create_approval_request", workflowFormView);
if (!registry.category("views").contains("wf_form")) {
    registry.category("views").add("wf_form", workflowFormView);
}
