# -*- coding: utf-8 -*-
from contextlib import ExitStack
from unittest.mock import patch
from urllib.parse import urljoin
from uuid import uuid4

from odoo import fields
from odoo.tests.common import HttpCase, tagged


@tagged("-at_install", "post_install")
class TestWorkflowTwoFactorMobileApi(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unique = uuid4().hex[:8]

        workflow_group = cls.env.ref("workflow_engine.group_workflow_approval_user")
        cls.user_password = "workflow_2fa_%s" % cls.unique
        cls.user = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "2FA Mobile User %s" % cls.unique,
                "login": "workflow_2fa_%s@example.com" % cls.unique,
                "email": "workflow_2fa_%s@example.com" % cls.unique,
                "password": cls.user_password,
                "group_ids": [(6, 0, [workflow_group.id])],
            }
        )
        base_request_model = cls.env["ir.model"]._get("workflow.base.approval.request")

        cls.category = cls.env["workflow.approval.category"].sudo().create(
            {
                "name": "2FA Category %s" % cls.unique,
                "res_model": base_request_model.id,
                "allowed_user_ids": [(6, 0, [cls.user.id])],
            }
        )
        cls.version = cls.env["workflow.approval.category.version"].sudo().create(
            {
                "name": "v2fa_%s" % cls.unique,
                "category_id": cls.category.id,
                "is_active": True,
            }
        )
        cls.category.sudo().write({"active_version_id": cls.version.id})

        cls.meta_task = cls.env["workflow.category.version.meta.task"].sudo().create(
            {
                "version_id": cls.version.id,
                "name": "Approve %s" % cls.unique,
                "node_id": "Task_%s" % cls.unique,
                "node_type": "userTask",
                "assignment_mode": "request_owner",
            }
        )
        cls.meta_end = cls.env["workflow.category.version.meta.task"].sudo().create(
            {
                "version_id": cls.version.id,
                "name": "Done %s" % cls.unique,
                "node_id": "End_%s" % cls.unique,
                "node_type": "endEvent",
            }
        )
        cls.meta_action = cls.env[
            "workflow.category.version.meta.task.action"
        ].sudo().create(
            {
                "name": "Approve",
                "meta_task_id": cls.meta_task.id,
                "source_id": cls.meta_task.node_id,
                "source_name": cls.meta_task.name,
                "source_node_type": cls.meta_task.node_type,
                "target_id": cls.meta_end.node_id,
                "target_name": cls.meta_end.name,
                "target_node_type": cls.meta_end.node_type,
                "node_id": "Flow_%s" % cls.unique,
                "version_id": cls.version.id,
                "approval_require_number": 1,
            }
        )
        cls.request_record = cls.env["workflow.base.approval.request"].sudo().create(
            {
                "name": "REQ_2FA_%s" % cls.unique,
                "category_id": cls.category.id,
                "request_owner_id": cls.user.id,
                "current_node_id": cls.meta_task.node_id,
                "previous_node_id": cls.meta_task.node_id,
                "current_iteration_no": 1,
            }
        )
        cls.env["workflow.approval.approver"].sudo().create(
            {
                "user_id": cls.user.id,
                "request_id": cls.request_record.id,
                "current_meta_id": cls.meta_task.id,
                "previous_meta_id": cls.meta_task.id,
                "status": "new",
                "required": True,
                "sequence": 1,
                "iteration_no": cls.request_record.current_iteration_no or 1,
            }
        )

    def _post_json_route(self, route, payload=None, patches=None):
        self.env.flush_all()
        self.env.invalidate_all()
        self.authenticate(self.user.login, self.user_password)

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "odoo.addons.workflow_engine.controller.twofactor_controller.WorkflowTwoFactorController._audit_twofactor_event",
                    return_value=None,
                )
            )
            for ctx in patches or []:
                stack.enter_context(ctx)

            response = self.opener.post(
                urljoin(self.base_url(), route),
                json={
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": payload if payload is not None else {},
                },
                headers={"Content-Type": "application/json"},
                timeout=20,
            )

        body = response.json()
        self.assertNotIn(
            "error",
            body,
            "JSON-RPC route %s returned HTTP %s: %s"
            % (route, response.status_code, body.get("error")),
        )
        return response, body.get("result", body)

    def test_mobile_scanned_endpoint_marks_qr_challenge_scanned(self):
        challenge = self.env["workflow.approval.action.challenge"].sudo().issue_qr_challenge(
            request_record=self.request_record,
            action_key="Approve",
            user=self.user,
        )
        payload = challenge.build_qr_payload()

        _response, result = self._post_json_route(
            "/workflow_2fa/mobile/scanned",
            payload={
                "challenge_id": challenge.id,
                "qr_payload": payload,
                "scanner_user_id": self.user.id,
                "scanner_login": self.user.login,
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "scanned")

    def test_mobile_confirm_endpoint_approves_scanned_challenge(self):
        challenge = self.env["workflow.approval.action.challenge"].sudo().issue_qr_challenge(
            request_record=self.request_record,
            action_key="Approve",
            user=self.user,
        )
        challenge.mark_scanned(actor_user=self.user)
        payload = challenge.build_qr_payload()

        _response, result = self._post_json_route(
            "/workflow_2fa/mobile/confirm",
            payload={
                "challenge_id": challenge.id,
                "decision": "approve",
                "signed_token": payload["signature"],
                "qr_payload": payload,
                "scanner_user_id": self.user.id,
                "scanner_login": self.user.login,
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "approved")

    def test_request_otp_and_verify_otp_endpoints_cover_email_flow(self):
        challenge = self.env["workflow.approval.action.challenge"].sudo().issue_qr_challenge(
            request_record=self.request_record,
            action_key="Approve",
            user=self.user,
        )

        _response, requested = self._post_json_route(
            "/workflow_2fa/challenge/request_otp",
            payload={"challenge_id": challenge.id},
            patches=[
                patch(
                    "odoo.addons.workflow_engine.models.workflow_runtime_models.WorkflowApprovalActionChallenge._send_email_otp",
                    return_value=None,
                )
            ],
        )

        self.assertTrue(requested["ok"])
        self.assertEqual(requested["state"], "pending")
        self.assertTrue(requested["otp_expires_at"])
        self.assertEqual(requested["otp_length"], int(challenge.otp_length or 6))

        otp_code = "123456"
        challenge.sudo().write({"code_hash": challenge._hash_code(challenge.token, otp_code)})

        _response, verified = self._post_json_route(
            "/workflow_2fa/challenge/verify_otp",
            payload={"challenge_id": challenge.id, "otp_code": otp_code},
        )

        self.assertTrue(verified["ok"])
        self.assertEqual(verified["state"], "approved")

    def test_request_otp_resets_failed_challenge_for_retry(self):
        challenge = self.env["workflow.approval.action.challenge"].sudo().issue_qr_challenge(
            request_record=self.request_record,
            action_key="Approve",
            user=self.user,
        )
        challenge.sudo().write({"state": "failed", "otp_attempts": 5, "last_error": "Invalid code"})

        _response, requested = self._post_json_route(
            "/workflow_2fa/challenge/request_otp",
            payload={"challenge_id": challenge.id},
            patches=[
                patch(
                    "odoo.addons.workflow_engine.models.workflow_runtime_models.WorkflowApprovalActionChallenge._send_email_otp",
                    return_value=None,
                )
            ],
        )

        challenge.invalidate_recordset()
        self.assertTrue(requested["ok"])
        self.assertEqual(challenge.state, "pending")
        self.assertEqual(challenge.otp_attempts, 0)
        self.assertFalse(challenge.last_error)

    def test_status_endpoint_returns_mobile_polling_payload(self):
        challenge = self.env["workflow.approval.action.challenge"].sudo().issue_qr_challenge(
            request_record=self.request_record,
            action_key="Approve",
            user=self.user,
        )

        _response, result = self._post_json_route(
            "/workflow_2fa/challenge/status",
            payload={"challenge_id": challenge.id},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "pending")
        self.assertEqual(result["token"], challenge.token)
        self.assertEqual(result["signature"], challenge.qr_signature)
        self.assertTrue(result["qr_payload"])
        self.assertIn("masked_email", result)

    def test_finalize_action_endpoint_returns_next_action(self):
        challenge = self.env["workflow.approval.action.challenge"].sudo().issue_qr_challenge(
            request_record=self.request_record,
            action_key="Approve",
            user=self.user,
        )
        challenge.mark_decision("approve", actor_user=self.user)

        _response, result = self._post_json_route(
            "/workflow_2fa/finalize_action",
            payload={
                "challenge_id": challenge.id,
                "meta_action_id": self.meta_action.id,
                "res_model": self.request_record._name,
                "res_id": self.request_record.id,
                "idempotency_key": "2fa-finalize-%s" % self.unique,
            },
            patches=[
                patch.object(type(self.request_record), "_get_form_data", return_value={}),
                patch.object(
                    type(self.request_record),
                    "_run_engine",
                    return_value={"type": "ir.actions.client", "tag": "reload"},
                ),
            ],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "approved")
        self.assertEqual(result["next_action"]["tag"], "reload")

    def test_mobile_endpoints_reject_invalid_challenge(self):
        for route in (
            "/workflow_2fa/mobile/scanned",
            "/workflow_2fa/mobile/confirm",
            "/workflow_2fa/challenge/request_otp",
            "/workflow_2fa/challenge/status",
            "/workflow_2fa/finalize_action",
        ):
            _response, result = self._post_json_route(route, payload={"challenge_id": 99999999})
            self.assertFalse(result["ok"], "Route %s must reject invalid challenge ids." % route)
