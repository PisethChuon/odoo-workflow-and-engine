# -*- coding: utf-8 -*-
import json
import logging

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WorkflowTwoFactorController(http.Controller):
    _APPROVAL_QR_KIND = "workflow.approval.twofa"

    def _find_challenge(self, challenge_id=None, token=None):
        Challenge = request.env["workflow.approval.action.challenge"].sudo()
        domain = []
        if challenge_id:
            try:
                domain = [("id", "=", int(challenge_id))]
            except Exception:
                return None
        elif token:
            domain = [("token", "=", token)]
        if not domain:
            return None
        return Challenge.search(domain, limit=1)

    def _parse_qr_payload(self, qr_payload):
        if isinstance(qr_payload, dict):
            return dict(qr_payload)
        if not qr_payload or not isinstance(qr_payload, str):
            return {}
        try:
            parsed = json.loads(qr_payload)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _request_network_metadata(self):
        ip_address = False
        request_host = False
        user_agent = False
        try:
            http_request = request.httprequest
            headers = http_request.headers
            forwarded_for = (headers.get("X-Forwarded-For") or "").strip()
            if forwarded_for:
                ip_address = forwarded_for.split(",")[0].strip()
            ip_address = ip_address or http_request.remote_addr
            request_host = (headers.get("X-Forwarded-Host") or headers.get("Host") or "").strip() or False
            user_agent = headers.get("User-Agent") or False
        except Exception:
            pass
        return ip_address, request_host, user_agent

    def _audit_twofactor_event(
        self,
        challenge,
        *,
        decision=False,
        comment=False,
        payload=False,
        actor_user=False,
    ):
        if not challenge or not challenge.request_id:
            return
        audit_service = request.env["workflow.engine.audit.service"].sudo()
        source_id = challenge.meta_action_id.source_id if challenge.meta_action_id else False
        target_id = challenge.meta_action_id.target_id if challenge.meta_action_id else False
        try:
            audit_service.log_event(
                request_record=challenge.request_id,
                task_instance=challenge.task_instance_id if challenge.task_instance_id else False,
                event_type="twofactor",
                action_key=challenge.action_key or False,
                decision=decision or False,
                from_node_id=source_id,
                to_node_id=target_id,
                actor_user=actor_user or request.env.user,
                comment=comment or False,
                payload=payload or {},
                challenge=challenge,
            )
        except Exception:
            _logger.exception(
                "Failed to audit twofactor event for challenge %s",
                challenge.id,
            )

    def _enforce_scanner_user_match(self, challenge, scanner_user_id=False, scanner_login=False):
        actor_user = request.env.user.sudo()
        ok, error = challenge.validate_scanner_identity(
            actor_user=actor_user,
            scanner_user_id=scanner_user_id,
            scanner_login=scanner_login,
        )
        return ok, error, actor_user

    def _resolve_challenge_and_payload(self, challenge_id=False, token=False, qr_payload=False):
        payload = self._parse_qr_payload(qr_payload)
        resolved_challenge_id = challenge_id or payload.get("challenge_id")
        resolved_token = token or payload.get("token")
        challenge = self._find_challenge(resolved_challenge_id, resolved_token)
        return challenge, payload

    @http.route("/workflow_2fa/mobile/scanned", type="jsonrpc", auth="user", csrf=False)
    def mobile_scanned(
        self,
        challenge_id=None,
        token=None,
        qr_payload=None,
        scanner_user_id=None,
        scanner_login=None,
    ):
        ch, payload = self._resolve_challenge_and_payload(
            challenge_id=challenge_id,
            token=token,
            qr_payload=qr_payload,
        )
        if not ch:
            return {"ok": False, "error": "invalid_challenge"}

        qr_kind = payload.get("qr_kind")
        if qr_kind and qr_kind != self._APPROVAL_QR_KIND:
            self._audit_twofactor_event(
                ch,
                decision="scan_invalid_qr_kind",
                payload={"qr_kind": qr_kind},
            )
            return {"ok": False, "error": "invalid_qr_kind"}

        ok, identity_error, actor_user = self._enforce_scanner_user_match(
            ch,
            scanner_user_id=scanner_user_id or payload.get("scanner_user_id"),
            scanner_login=scanner_login or payload.get("scanner_login"),
        )
        if not ok:
            self._audit_twofactor_event(
                ch,
                decision="scan_denied_user_mismatch",
                actor_user=actor_user,
                payload={
                    "error": identity_error,
                    "expected_user_id": ch.user_id.id,
                    "actor_user_id": actor_user.id if actor_user else False,
                },
            )
            return {"ok": False, "error": identity_error}

        if ch.state not in ("pending", "scanned"):
            self._audit_twofactor_event(
                ch,
                decision="scan_invalid_state",
                actor_user=actor_user,
                payload={"state": ch.state},
            )
            return {"ok": False, "error": "invalid_state"}

        request_ip, request_host, user_agent = self._request_network_metadata()
        ch.mark_scanned(
            actor_user=actor_user,
            request_ip=request_ip,
            request_host=request_host,
            user_agent=user_agent,
        )
        self._audit_twofactor_event(
            ch,
            decision="scanned",
            actor_user=actor_user,
            payload={"state": ch.state},
        )
        return {"ok": True, "state": ch.state}

    @http.route("/workflow_2fa/mobile/confirm", type="jsonrpc", auth="user", csrf=False)
    def mobile_confirm(
        self,
        challenge_id=None,
        decision="approve",
        signed_token=None,
        qr_payload=None,
        scanner_user_id=None,
        scanner_login=None,
    ):
        ch, payload = self._resolve_challenge_and_payload(
            challenge_id=challenge_id,
            token=False,
            qr_payload=qr_payload,
        )
        if not ch:
            return {"ok": False, "error": "invalid_challenge"}

        actor_user = request.env.user.sudo()
        qr_kind = payload.get("qr_kind")
        if qr_kind and qr_kind != self._APPROVAL_QR_KIND:
            self._audit_twofactor_event(
                ch,
                decision="confirm_invalid_qr_kind",
                actor_user=actor_user,
                payload={"qr_kind": qr_kind},
            )
            return {"ok": False, "error": "invalid_qr_kind"}

        ok, identity_error, actor_user = self._enforce_scanner_user_match(
            ch,
            scanner_user_id=scanner_user_id or payload.get("scanner_user_id"),
            scanner_login=scanner_login or payload.get("scanner_login"),
        )
        if not ok:
            self._audit_twofactor_event(
                ch,
                decision="confirm_denied_user_mismatch",
                actor_user=actor_user,
                payload={
                    "error": identity_error,
                    "expected_user_id": ch.user_id.id,
                    "actor_user_id": actor_user.id if actor_user else False,
                },
            )
            return {"ok": False, "error": identity_error}

        if ch.state in ("approved", "denied", "expired", "failed"):
            self._audit_twofactor_event(
                ch,
                decision="confirm_final_state",
                actor_user=actor_user,
                payload={"state": ch.state},
            )
            return {"ok": False, "error": "final_state"}

        payload_token = (payload.get("token") or "").strip()
        if payload_token and payload_token != (ch.token or ""):
            self._audit_twofactor_event(
                ch,
                decision="confirm_invalid_token",
                actor_user=actor_user,
                payload={"payload_token_prefix": payload_token[:6]},
            )
            return {"ok": False, "error": "invalid_token"}

        signature = signed_token or payload.get("signature") or ""
        if not ch.verify_qr_signature(signature):
            self._audit_twofactor_event(
                ch,
                decision="confirm_invalid_signature",
                actor_user=actor_user,
            )
            return {"ok": False, "error": "invalid_signature"}

        request_ip, request_host, user_agent = self._request_network_metadata()
        normalized_decision = "approve" if decision == "approve" else "deny"
        ok = ch.mark_decision(
            normalized_decision,
            actor_user=actor_user,
            request_ip=request_ip,
            request_host=request_host,
            user_agent=user_agent,
        )
        self._audit_twofactor_event(
            ch,
            decision="approved" if ok and normalized_decision == "approve" else "denied",
            actor_user=actor_user,
            payload={
                "requested_decision": normalized_decision,
                "state": ch.state,
            },
        )
        return {"ok": ok, "state": ch.state}

    @http.route("/workflow_2fa/challenge/request_otp", type="jsonrpc", auth="user", csrf=False)
    def request_otp(self, challenge_id=None):
        ch = self._find_challenge(challenge_id)
        if not ch:
            return {"ok": False, "error": "invalid_challenge"}
        if ch.user_id.id != request.env.user.id:
            self._audit_twofactor_event(
                ch,
                decision="otp_request_denied_user_mismatch",
                payload={
                    "expected_user_id": ch.user_id.id,
                    "actor_user_id": request.env.user.id,
                },
            )
            return {"ok": False, "error": "forbidden"}
        try:
            ch.request_otp()
        except Exception as exc:
            self._audit_twofactor_event(
                ch,
                decision="otp_request_failed",
                payload={"error": str(exc)},
            )
            return {"ok": False, "error": str(exc)}

        self._audit_twofactor_event(ch, decision="otp_requested")
        return {
            "ok": True,
            "state": ch.state,
            "otp_expires_at": ch.otp_expires_at,
            "otp_length": int(ch.otp_length or 6),
        }

    @http.route("/workflow_2fa/challenge/verify_otp", type="jsonrpc", auth="user", csrf=False)
    def verify_otp(self, challenge_id=None, otp_code=None):
        otp_code = "".join(ch for ch in str(otp_code or "") if ch.isdigit())
        ch = self._find_challenge(challenge_id)
        if not ch or not otp_code:
            return {"ok": False, "error": "invalid_request"}
        if ch.user_id.id != request.env.user.id:
            self._audit_twofactor_event(
                ch,
                decision="otp_verify_denied_user_mismatch",
                payload={
                    "expected_user_id": ch.user_id.id,
                    "actor_user_id": request.env.user.id,
                },
            )
            return {"ok": False, "error": "forbidden"}
        request_ip, request_host, user_agent = self._request_network_metadata()
        ok = ch.verify_email_otp(
            otp_code,
            actor_user=request.env.user,
            request_ip=request_ip,
            request_host=request_host,
            user_agent=user_agent,
        )
        self._audit_twofactor_event(
            ch,
            decision="otp_verified" if ok else "otp_verify_failed",
            payload={"state": ch.state},
        )
        return {"ok": ok, "state": ch.state}

    @http.route("/workflow_2fa/challenge/status", type="jsonrpc", auth="user", csrf=False)
    def status(self, challenge_id=None):
        ch = self._find_challenge(challenge_id)
        if not ch:
            return {"ok": False, "error": "invalid_challenge"}
        if ch.user_id.id != request.env.user.id:
            return {"ok": False, "error": "forbidden"}
        email = ch.user_id.email or ""
        masked = "******"
        if email and "@" in email:
            local, dom = email.split("@", 1)
            masked = f"{local[:1]}*****{local[-1:] if len(local) > 1 else ''}@{dom}"
        return {
            "ok": True,
            "state": ch.state,
            "expires_at": ch.expires_at,
            "otp_expires_at": ch.otp_expires_at,
            "qr_image": ch.qr_image,
            "token": ch.token,
            "signature": ch.qr_signature,
            "qr_payload": ch.build_qr_payload(),
            "masked_email": masked,
            "otp_length": int(ch.otp_length or 6),
        }

    @http.route("/workflow_2fa/finalize_action", type="jsonrpc", auth="user", csrf=False)
    def finalize_action(
        self,
        challenge_id=None,
        meta_action_id=None,
        res_model=None,
        res_id=None,
        view_id=None,
        idempotency_key=None,
    ):
        ch = self._find_challenge(challenge_id)
        if not ch:
            return {"ok": False, "error": "invalid_challenge"}
        if ch.user_id.id != request.env.user.id:
            self._audit_twofactor_event(
                ch,
                decision="finalize_denied_user_mismatch",
                payload={
                    "expected_user_id": ch.user_id.id,
                    "actor_user_id": request.env.user.id,
                },
            )
            return {"ok": False, "error": "forbidden"}
        if ch.state not in ("approved", "verified"):
            self._audit_twofactor_event(
                ch,
                decision="finalize_not_approved",
                payload={"state": ch.state},
            )
            return {"ok": False, "error": "not_approved"}
        if not (res_model and res_id and meta_action_id):
            return {"ok": False, "error": "missing_params"}

        record = request.env[res_model].browse(int(res_id))
        if not record.exists():
            return {"ok": False, "error": "missing_record"}
        meta_action = request.env["workflow.category.version.meta.task.action"].sudo().browse(
            int(meta_action_id)
        )
        if not meta_action.exists():
            return {"ok": False, "error": "missing_meta_action"}
        request_record = record
        if "x_approval_base_id" in record._fields and record.x_approval_base_id:
            request_record = record.x_approval_base_id
        permission_service = request.env["workflow.engine.permission.service"]
        permission = permission_service.assert_can_execute_action(
            child_record=record,
            request_record=request_record,
            meta_action=meta_action,
            user=request.env.user,
        )
        action_context = {}
        if hasattr(record, "_workflow_build_action_execution_context"):
            action_context = record._workflow_build_action_execution_context(
                permission=permission,
                actor_user=request.env.user,
                task_node_id=meta_action.source_id,
            )
        workflow_record = record._workflow_elevated_action_record()

        try:
            next_action = workflow_record.with_context(
                **action_context,
                workflow_challenge_id=ch.id,
                workflow_idempotency_key=idempotency_key or f"2fa:{ch.id}:{record._name}:{record.id}",
                view_id=int(view_id or 0) or False,
                meta_action_id=meta_action.id,
                workflow_action_key=meta_action.name or meta_action.attr_label,
                workflow_task_node_id=meta_action.source_id or False,
                workflow_skip_config_confirm=True,
                workflow_notification_actor_user_id=request.env.user.id,
            )._run_engine(
                form_data=workflow_record._get_form_data(),
                meta_action_id=meta_action.id,
            )
            if not ch.used_at:
                ch.sudo().write({"used_at": fields.Datetime.now()})
        except Exception as exc:
            self._audit_twofactor_event(
                ch,
                decision="finalize_failed",
                payload={"error": str(exc)},
            )
            raise

        self._audit_twofactor_event(
            ch,
            decision="finalized",
            payload={
                "res_model": record._name,
                "res_id": record.id,
                "meta_action_id": meta_action.id,
                "next_action_type": (next_action or {}).get("type")
                if isinstance(next_action, dict)
                else False,
            },
        )
        return {
            "ok": True,
            "state": ch.state,
            "next_action": next_action if isinstance(next_action, dict) else False,
        }
