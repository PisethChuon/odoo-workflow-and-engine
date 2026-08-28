/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

const actionRegistry = registry.category("actions");
const OTP_RESEND_COOLDOWN_SECONDS = 60;

export class TwoFADialog extends Component {
    static template = "workflow_engine.TwoFADialog";
    static props = ["*"];

    setup() {
        this.bus = useService("bus_service");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.dialogService = useService("dialog");
        const params = this.props.action.params || {};
        this.challengeId = params.challenge_id;
        this.metaActionId = params.meta_action_id;
        this.resModel = params.res_model;
        this.resId = params.res_id;
        this.viewId = params.view_id || false;
        this.state = useState({
            stage: "qr",
            retry_stage: "qr",
            qr_image: null,
            countdown: null,
            otp_length: 6,
            otp_digits: ["", "", "", "", "", ""],
            masked_email: "******",
            resend_cooldown: 0,
        });
        this.busChannel = null;
        this.busType = "workflow_2fa.challenge_state";
        this.busCallback = null;
        this.resendTimer = null;

        this._fetchStatus();
        this._subscribeBus();
        onWillUnmount(() => {
            this._unsubscribeBus();
            this._clearResendCooldown();
        });
    }

    _maskEmail(email) {
        if (!email || email.indexOf("@") === -1) return "******";
        const [local, domain] = email.split("@");
        if (local.length <= 2) return "***@" + domain;
        return local[0] + "*****" + local.slice(-1) + "@" + domain;
    }

    _subscribeBus() {
        if (!this.challengeId) return;
        this.busChannel = `workflow_2fa.challenge_${this.challengeId}`;
        this.bus.addChannel(this.busChannel);
        this.bus.start();
        this.busCallback = (payload) => {
            if (!payload || Number(payload.challenge_id) !== Number(this.challengeId)) {
                return;
            }
            this._handleState(payload.state || "");
        };
        this.bus.subscribe(this.busType, this.busCallback);
    }

    _unsubscribeBus() {
        if (this.busCallback) {
            this.bus.unsubscribe(this.busType, this.busCallback);
            this.busCallback = null;
        }
        if (this.busChannel) {
            this.bus.deleteChannel(this.busChannel);
            this.busChannel = null;
        }
    }

    async _fetchStatus() {
        const data = await rpc("/workflow_2fa/challenge/status", { challenge_id: this.challengeId });
        if (!data.ok) return;
        this.state.qr_image = data.qr_image;
        if (data.masked_email) this.state.masked_email = data.masked_email;
        this._setOtpLength(data.otp_length);
        this._handleState(data.state);
    }

    _normalizeOtpLength(value) {
        const parsed = Number.parseInt(value, 10);
        if (!Number.isFinite(parsed)) {
            return 6;
        }
        return Math.min(8, Math.max(4, parsed));
    }

    _setOtpLength(lengthValue) {
        const length = this._normalizeOtpLength(lengthValue);
        const current = Array.isArray(this.state.otp_digits) ? this.state.otp_digits : [];
        const nextDigits = Array.from({ length }, (_, index) => {
            const char = String(current[index] || "").replace(/\D/g, "");
            return char ? char.slice(-1) : "";
        });
        this.state.otp_length = length;
        this.state.otp_digits = nextDigits;
    }

    _resetOtpDigits() {
        this.state.otp_digits = Array(this.state.otp_length).fill("");
        setTimeout(() => this._focusOtpInput(0), 0);
    }

    _focusOtpInput(index) {
        setTimeout(() => {
            const root = this.el || document.querySelector(".wf2fa-root");
            if (!root) {
                return;
            }
            const next = root.querySelector(`.wf2fa-otp-digit[data-index="${index}"]`);
            if (next) {
                next.focus();
                if (typeof next.select === "function") {
                    next.select();
                }
            }
        }, 0);
    }

    _otpCode() {
        return (this.state.otp_digits || []).join("");
    }

    otpSlots() {
        return (this.state.otp_digits || []).map((digit, index) => ({ digit, index }));
    }

    isOtpComplete() {
        return this._otpCode().length === this.state.otp_length;
    }

    canResendOtp() {
        return !this.state.resend_cooldown;
    }

    resendCooldownLabel() {
        const seconds = Number.parseInt(this.state.resend_cooldown || 0, 10);
        if (!seconds) {
            return "";
        }
        return `Resend in ${seconds}s`;
    }

    _handleState(newState) {
        if (newState === "approved" || newState === "verified") {
            this.state.stage = "success";
        } else if (newState === "scanned") {
            this.state.retry_stage = "qr";
            this.state.stage = "waiting";
        } else if (newState === "expired" || newState === "failed" || newState === "denied") {
            this.state.stage = "error";
        }
    }

    async switchToOtp() {
        this.state.stage = "otp";
        this.state.retry_stage = "otp";
        this._resetOtpDigits();
        await this.requestOtp();
    }

    backToQr() {
        this.state.stage = "qr";
        this.state.retry_stage = "qr";
    }

    onOtpDigitInput(ev) {
        const index = Number.parseInt(ev.target.dataset.index || "", 10);
        if (!Number.isFinite(index)) {
            return;
        }
        const digits = String(ev.target.value || "").replace(/\D/g, "");
        const next = [...(this.state.otp_digits || [])];
        if (digits.length > 1) {
            let cursor = index;
            for (const char of digits) {
                if (cursor >= next.length) {
                    break;
                }
                next[cursor] = char;
                cursor += 1;
            }
            this.state.otp_digits = next;
            ev.target.value = next[index] || "";
            this._focusOtpInput(Math.min(cursor, next.length - 1));
            return;
        }
        const normalized = digits ? digits.slice(-1) : "";
        next[index] = normalized;
        this.state.otp_digits = next;
        ev.target.value = normalized;
        if (normalized && index < next.length - 1) {
            this._focusOtpInput(index + 1);
        }
    }

    onOtpKeydown(ev) {
        const index = Number.parseInt(ev.target.dataset.index || "", 10);
        if (!Number.isFinite(index)) {
            return;
        }
        if (ev.ctrlKey || ev.metaKey) {
            return;
        }
        if (ev.key === "Backspace") {
            const next = [...(this.state.otp_digits || [])];
            if (next[index]) {
                next[index] = "";
                this.state.otp_digits = next;
                ev.preventDefault();
                return;
            }
            if (index > 0) {
                next[index - 1] = "";
                this.state.otp_digits = next;
                this._focusOtpInput(index - 1);
                ev.preventDefault();
            }
            return;
        }
        if (ev.key === "ArrowLeft" && index > 0) {
            this._focusOtpInput(index - 1);
            ev.preventDefault();
            return;
        }
        if (ev.key === "ArrowRight" && index < this.state.otp_digits.length - 1) {
            this._focusOtpInput(index + 1);
            ev.preventDefault();
            return;
        }
        if (ev.key.length === 1 && !/\d/.test(ev.key)) {
            ev.preventDefault();
        }
    }

    onOtpPaste(ev) {
        ev.preventDefault();
        const pasted = String((ev.clipboardData && ev.clipboardData.getData("text")) || "").replace(
            /\D/g,
            ""
        );
        if (!pasted) {
            return;
        }
        const start = Number.parseInt(ev.target.dataset.index || "0", 10) || 0;
        if (start === 0) {
            this._applyOtpCode(pasted, 0);
            return;
        }
        const next = [...(this.state.otp_digits || [])];
        let cursor = Math.max(0, Math.min(start, next.length - 1));
        for (const char of pasted) {
            if (cursor >= next.length) {
                break;
            }
            next[cursor] = char;
            cursor += 1;
        }
        this.state.otp_digits = next;
        this._focusOtpInput(Math.min(cursor, next.length - 1));
    }

    onOtpBoxPaste(ev) {
        const target = ev.target;
        if (target && target.classList && target.classList.contains("wf2fa-otp-digit")) {
            return;
        }
        ev.preventDefault();
        this._applyOtpCode(
            (ev.clipboardData && ev.clipboardData.getData("text")) || "",
            0
        );
    }

    _applyOtpCode(value, start = 0) {
        const digits = String(value || "").replace(/\D/g, "");
        const next = [...(this.state.otp_digits || [])];
        let cursor = Math.max(0, Math.min(Number.parseInt(start, 10) || 0, next.length - 1));
        if (start <= 0) {
            next.fill("");
        }
        for (const char of digits) {
            if (cursor >= next.length) {
                break;
            }
            next[cursor] = char;
            cursor += 1;
        }
        this.state.otp_digits = next;
        this._focusOtpInput(Math.min(cursor, next.length - 1));
    }

    _clearResendCooldown() {
        if (this.resendTimer) {
            clearInterval(this.resendTimer);
            this.resendTimer = null;
        }
        this.state.resend_cooldown = 0;
    }

    _startResendCooldown(seconds = OTP_RESEND_COOLDOWN_SECONDS) {
        this._clearResendCooldown();
        this.state.resend_cooldown = Math.max(1, Number.parseInt(seconds, 10) || OTP_RESEND_COOLDOWN_SECONDS);
        this.resendTimer = setInterval(() => {
            const next = Math.max(0, (this.state.resend_cooldown || 0) - 1);
            this.state.resend_cooldown = next;
            if (!next) {
                this._clearResendCooldown();
            }
        }, 1000);
    }

    async requestOtp() {
        if (!this.canResendOtp()) {
            return;
        }
        const res = await rpc("/workflow_2fa/challenge/request_otp", { challenge_id: this.challengeId });
        if (!res.ok) {
            this.notification.add(res.error || "Cannot send OTP", { type: "warning" });
            return;
        }
        this._setOtpLength(res.otp_length);
        this._resetOtpDigits();
        this._startResendCooldown(res.resend_cooldown || OTP_RESEND_COOLDOWN_SECONDS);
    }

    async verifyOtp() {
        const otpCode = this._otpCode();
        if (otpCode.length !== this.state.otp_length) {
            this.notification.add("Please complete the OTP code.", { type: "warning" });
            return;
        }
        const res = await rpc("/workflow_2fa/challenge/verify_otp", {
            challenge_id: this.challengeId,
            otp_code: otpCode,
        });
        if (res.ok) {
            this.state.stage = "success";
        } else {
            this.state.retry_stage = "otp";
            this.state.stage = "error";
            this.notification.add(res.error || "Invalid code", { type: "danger" });
        }
    }

    async finalize() {
        const res = await rpc("/workflow_2fa/finalize_action", {
            challenge_id: this.challengeId,
            meta_action_id: this.metaActionId,
            res_model: this.resModel,
            res_id: this.resId,
            view_id: this.viewId,
        });
        if (!res.ok) {
            this.notification.add(res.error || "Finalize failed", { type: "danger" });
            this.state.stage = "error";
            return;
        }
        const actionToOpen = this._normalizePostAction(res.next_action);
        await this.actionService.doAction(actionToOpen);
    }

    async retry() {
        await this._fetchStatus();
        if (this.state.retry_stage === "otp") {
            this.state.stage = "otp";
            await this.requestOtp();
            return;
        }
        this.state.stage = "qr";
        this.state.retry_stage = "qr";
        this._resetOtpDigits();
    }

    _normalizePostAction(action) {
        const closeAction = { type: "ir.actions.act_window_close" };
        const reloadAction = { type: "ir.actions.client", tag: "reload" };
        if (!action || typeof action !== "object") {
            return reloadAction;
        }
        if (action.type === "ir.actions.client" && action.tag === "display_notification") {
            const normalized = {
                ...action,
                params: { ...(action.params || {}) },
            };
            normalized.params.next = normalized.params.next || reloadAction;
            return normalized;
        }
        return this._normalizeWindowAction(action);
    }

    _normalizeWindowAction(action) {
        if (!action || typeof action !== "object") {
            return { type: "ir.actions.act_window_close" };
        }
        if (action.type !== "ir.actions.act_window") {
            return action;
        }
        const normalized = { ...action };
        if (!Array.isArray(normalized.views) || !normalized.views.length) {
            const mode = (normalized.view_mode || "form").split(",")[0] || "form";
            normalized.views = [[normalized.view_id || false, mode]];
        }
        normalized.target = normalized.target || "current";
        return normalized;
    }
}

actionRegistry.add("workflow_engine_twofa_dialog", TwoFADialog);
