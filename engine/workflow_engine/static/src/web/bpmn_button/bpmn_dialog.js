/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { Dialog } from "@web/core/dialog/dialog";
import { BpmnWidget } from "./bpmn_widget";

const MOBILE_SHEET_DURATION_MS = 420;
const MOBILE_DIAGRAM_MOUNT_DELAY_MS = MOBILE_SHEET_DURATION_MS + 40;

const STATUS_CLASS_BY_VALUE = {
    blocked: "is-blocked",
    approved: "is-approved",
    done: "is-approved",
    rejected: "is-rejected",
    refused: "is-rejected",
    cancelled: "is-rejected",
    cancel: "is-rejected",
    waiting: "is-waiting",
    pending: "is-waiting",
    review: "is-waiting",
    progress: "is-waiting",
    draft: "is-draft",
    submitted: "is-draft",
    new: "is-draft",
};

function normalizeValue(value) {
    if (value === undefined || value === null || value === false) {
        return "";
    }
    if (Array.isArray(value)) {
        return normalizeValue(value[1] ?? value[0]);
    }
    if (typeof value === "object") {
        if (typeof value.display_name === "string" && value.display_name.trim()) {
            return value.display_name.trim();
        }
        if (typeof value.name === "string" && value.name.trim()) {
            return value.name.trim();
        }
        return "";
    }
    return String(value).trim();
}

function toLabel(value) {
    return normalizeValue(value)
        .replace(/[_-]+/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .replace(/\b\w/g, (char) => char.toUpperCase());
}

function isTechnicalNodeId(value) {
    const raw = normalizeValue(value).toLowerCase();
    if (!raw) {
        return false;
    }
    return /^activity[_\s-]?[a-z0-9]{5,}$/.test(raw)
        || /^node[_\s-]?[a-z0-9]{5,}$/.test(raw)
        || /^task[_\s-]?[a-z0-9]{5,}$/.test(raw);
}

function isTerminalWorkflowState(value) {
    const state = normalizeValue(value).toLowerCase();
    return ["completed", "cancelled", "auto_cancelled", "refused", "auto_approved"].includes(state);
}

export class BpmnDialog extends Component {
    static template = "workflow_engine.BpmnDialog";
    static components = { Dialog, BpmnWidget };
    static props = {
        data: { type: Object, optional: true },
        title: { type: String, optional: true },
        close: { type: Function, optional: true },
    };

    setup() {
        const isMobileSheet = Boolean(this.env.isSmall);
        this.state = useState({
            isSheetReady: false,
            isDiagramReady: !isMobileSheet,
        });
        this.sheetFrame = null;
        this.diagramTimer = null;

        onMounted(() => {
            if (!isMobileSheet) {
                this.state.isSheetReady = true;
                return;
            }

            // Paint the off-screen sheet first, then start its compositor animation.
            this.sheetFrame = browser.requestAnimationFrame(() => {
                this.sheetFrame = browser.requestAnimationFrame(() => {
                    this.sheetFrame = null;
                    this.state.isSheetReady = true;

                    const reducedMotion = browser.matchMedia(
                        "(prefers-reduced-motion: reduce)"
                    );
                    if (reducedMotion === true || reducedMotion.matches === true) {
                        this.state.isDiagramReady = true;
                        return;
                    }
                    this.diagramTimer = browser.setTimeout(() => {
                        this.diagramTimer = null;
                        this.state.isDiagramReady = true;
                    }, MOBILE_DIAGRAM_MOUNT_DELAY_MS);
                });
            });
        });

        onWillUnmount(() => {
            if (this.sheetFrame !== null) {
                browser.cancelAnimationFrame(this.sheetFrame);
            }
            if (this.diagramTimer !== null) {
                browser.clearTimeout(this.diagramTimer);
            }
        });
    }

    get titleText() {
        return normalizeValue(this.props.title) || "Preview Flow";
    }

    get requestLabel() {
        const data = this.props.data || {};
        return normalizeValue(data.display_name || data.name || data.request_name || data.reference);
    }

    get categoryLabel() {
        const data = this.props.data || {};
        return normalizeValue(data.category_id || data.approval_type || data.approval_category_id);
    }

    get stageLabel() {
        const data = this.props.data || {};
        const stageRaw = normalizeValue(data.current_activity || data.current_stage || data.workflow_stage || data.current_node_name);
        if (!stageRaw || isTechnicalNodeId(stageRaw)) {
            return "";
        }
        return toLabel(stageRaw);
    }

    get statusLabel() {
        if (this.isBlocked) {
            return "Blocked";
        }
        const data = this.props.data || {};
        return toLabel(data.request_status || data.state || data.activity_state || data.status);
    }

    get statusClass() {
        const key = normalizeValue(this.statusLabel).toLowerCase();
        return STATUS_CLASS_BY_VALUE[key] || "is-neutral";
    }

    get isBlocked() {
        const raw = this.props.data?.wf_is_blocked;
        return raw === true || raw === 1 || raw === "1" || raw === "true";
    }

    get blockedReason() {
        return normalizeValue(this.props.data?.wf_block_reason);
    }

    get subWorkflowCount() {
        const subFlows = this.props.data?.sub_workflows;
        return Array.isArray(subFlows) ? subFlows.length : 0;
    }

    get requestOwnerLabel() {
        const data = this.props.data || {};
        return normalizeValue(data.request_owner_id || data.owner_id || data.requester_id || data.create_uid);
    }

    get openApproverCount() {
        if (
            isTerminalWorkflowState(this.props.data?.state)
            || isTerminalWorkflowState(this.props.data?.request_status)
        ) {
            return 0;
        }
        const approvers = this.props.data?.approver_ids?.records || [];
        if (!Array.isArray(approvers) || !approvers.length) {
            return 0;
        }
        const actionableStatuses = new Set(["new", "pending", "waiting", "view"]);
        return approvers.filter((approver) => actionableStatuses.has(approver?.data?.status)).length;
    }
}
