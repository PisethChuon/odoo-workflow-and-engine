from uuid import uuid4

from lxml import etree

from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("-at_install", "post_install")
class TestWorkflowCategorySequence(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        internal_group = cls.env.ref("base.group_user")
        workflow_user_group = cls.env.ref("workflow_engine.group_workflow_approval_user")
        technical_group = cls.env.ref("workflow_engine.group_workflow_technical_admin")
        unique = uuid4().hex[:8]
        cls.technical_user = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Workflow Category Sequence Technical User",
                "login": f"workflow_category_sequence_technical_user_{unique}",
                "group_ids": [
                    Command.set(
                        [
                            internal_group.id,
                            workflow_user_group.id,
                            technical_group.id,
                        ]
                    )
                ],
            }
        )

    def test_technical_category_list_exposes_native_sequence_handle(self):
        view = self.env.ref(
            "workflow_studio.workflow_studio_workflow_approval_category_list_view"
        )
        view_arch = self.env["workflow.approval.category"].with_user(
            self.technical_user
        ).get_view(view_id=view.id, view_type="list")["arch"]
        root = etree.fromstring(view_arch.encode())
        sequence_fields = root.xpath("//field[@name='sequence']")

        self.assertEqual(root.get("default_order"), "sequence, create_date, id")
        self.assertEqual(len(sequence_fields), 1)
        self.assertEqual(sequence_fields[0].get("widget"), "handle")
