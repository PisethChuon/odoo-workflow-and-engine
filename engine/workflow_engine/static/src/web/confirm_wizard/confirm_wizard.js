/** @odoo-module **/

import { Component, useEffect, useRef, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";

const fieldRegistry = registry.category("fields");

const STAGES = ["qr", "wait", "success", "error", "otp"];

export class TwoFAChallengeWidget extends Component {
    static template = "workflow_engine.TwoFAChallenge";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.bus = useService("bus_service");
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.state = useState({
            stage: this._defaultStage(),
            countdown: this._computeCountdown(),
        });
        this.trackRef = useRef("track");

        onWillStart(() => {
            this._subscribeBus();
        });
        onWillUnmount(() => {
            this._unsubscribeBus();
            if (this._countdownTimer) clearInterval(this._countdownTimer);
        });

        useEffect(() => {
            if (this.state.stage === "qr" || this.state.stage === "wait") {
                this._ensureCountdown();
            } else if (this._countdownTimer) {
                clearInterval(this._countdownTimer);
            }
        }, () => [this.props.record.data.challenge_expires_at, this.state.stage]);
    }

    _defaultStage() {
        const method = this.props.record.data.challenge_method || "email_otp";
        if (method === "qr") return "qr";
        return "otp";
    }

    _computeCountdown() {
        const expires = this.props.record.data.challenge_expires_at;
        if (!expires) return null;
        const now = Date.now();
        const target = new Date(expires).getTime();
        const diff = Math.max(0, Math.floor((target - now) / 1000));
        return diff;
    }

    _ensureCountdown() {
        if (this._countdownTimer) clearInterval(this._countdownTimer);
        this._countdownTimer = setInterval(() => {
            this.state.countdown = this._computeCountdown();
            if (this.state.countdown !== null && this.state.countdown <= 0) {
                clearInterval(this._countdownTimer);
                if (this.state.stage === "wait") {
                    this.state.stage = "error";
                }
            }
        }, 1000);
    }

    _channelName() {
        const challengeId = this.props.record.data.challenge_id;
        if (!challengeId) return null;
        return `workflow_2fa.challenge_${challengeId}`;
    }

    _subscribeBus() {
        const channel = this._channelName();
        if (!channel) return;
        this.bus.addChannel(channel);
        this.bus.start();
        this._notifHandler = (payload) => {
            if (!payload || Number(payload.challenge_id) !== Number(this.props.record.data.challenge_id)) {
                return;
            }
            if (payload.state === "scanned" || payload.state === "waiting") {
                this.state.stage = "wait";
            } else if (payload.state === "approved" || payload.state === "verified") {
                this.state.stage = "success";
            } else if (payload.state === "failed" || payload.state === "expired" || payload.state === "denied") {
                this.state.stage = "error";
            }
        };
        this.bus.subscribe("workflow_2fa.challenge_state", this._notifHandler);
    }

    _unsubscribeBus() {
        if (this._notifHandler) {
            this.bus.unsubscribe("workflow_2fa.challenge_state", this._notifHandler);
            this._notifHandler = null;
        }
        const channel = this._channelName();
        if (channel) {
            this.bus.deleteChannel(channel);
        }
    }

    get trackStyle() {
        const idx = STAGES.indexOf(this.state.stage);
        const offset = idx >= 0 ? idx : 0;
        return { "--stage-index": offset };
    }

    onRequestOtp(ev) {
        ev.preventDefault();
        this.state.stage = "otp";
    }

    onBackToQr(ev) {
        ev.preventDefault();
        if ((this.props.record.data.challenge_method || "email_otp") === "qr") {
            this.state.stage = "qr";
        }
    }

    onInputOtp(ev) {
        this.props.update(ev.target.value || "");
    }
}

fieldRegistry.add("twofa_challenge", { component: TwoFAChallengeWidget });
