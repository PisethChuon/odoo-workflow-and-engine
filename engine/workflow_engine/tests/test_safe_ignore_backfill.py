# -*- coding: utf-8 -*-

from odoo.tests import common

from odoo.addons.workflow_engine.models.approval_category_version_meta import (
    ROUTING_ALWAYS_TRUE,
    _backfill_safe_ignore_routing_domains,
)


class TestSafeIgnoreRoutingBackfill(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.target_model = cls.env["ir.model"]._get("res.partner")
        cls.category = cls.env["workflow.approval.category"].create(
            {
                "name": "Safe Ignore Backfill Category",
                "res_model": cls.target_model.id,
            }
        )
        cls.version = cls.env["workflow.approval.category.version"].create(
            {
                "category_id": cls.category.id,
                "name": "v_backfill",
                "is_active": False,
            }
        )
        cls.action = cls.env["workflow.approval.action"].create(
            {
                "name": "Backfill Notification Channel",
                "action_type": "email",
                "version_id": cls.version.id,
            }
        )

    def test_backfill_updates_channel_email_recipient_routing_domains(self):
        recipient_model = self.env["workflow.approval.action.email.recipient"]
        approval_group_line = recipient_model.create(
            {
                "action_id": self.action.id,
                "header": "to",
                "source": "approval_group_users",
                "domain": "",
            }
        )
        group_line = recipient_model.create(
            {
                "action_id": self.action.id,
                "header": "cc",
                "source": "group_users",
                "domain": "[]",
            }
        )
        domain_line = recipient_model.create(
            {
                "action_id": self.action.id,
                "header": "bcc",
                "source": "domain",
                "domain": "[]",
            }
        )
        direct_line = recipient_model.create(
            {
                "action_id": self.action.id,
                "header": "to",
                "source": "direct",
                "raw_emails": "noreply@example.com",
                "domain": "",
            }
        )

        _backfill_safe_ignore_routing_domains(self.env.cr)
        _backfill_safe_ignore_routing_domains(self.env.cr)
        (
            approval_group_line
            | group_line
            | domain_line
            | direct_line
        ).invalidate_recordset(["domain"])

        self.assertEqual(approval_group_line.domain, ROUTING_ALWAYS_TRUE)
        self.assertEqual(group_line.domain, ROUTING_ALWAYS_TRUE)
        self.assertEqual(domain_line.domain, ROUTING_ALWAYS_TRUE)
        self.assertFalse(direct_line.domain)
