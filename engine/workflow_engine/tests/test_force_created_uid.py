# -*- coding: utf-8 -*-

from uuid import uuid4

from odoo.tests import common


FORCED_CREATOR_BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_ForceCreator">
  <bpmn:process id="Process_ForceCreator" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1" name="Start">
      <bpmn:outgoing>Flow_Start_Submission</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:userTask id="Task_Submission" name="Submission">
      <bpmn:incoming>Flow_Start_Submission</bpmn:incoming>
    </bpmn:userTask>
    <bpmn:sequenceFlow id="Flow_Start_Submission" sourceRef="StartEvent_1" targetRef="Task_Submission"/>
  </bpmn:process>
</bpmn:definitions>"""


class TestWorkflowForceCreatedUid(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.User = cls.env["res.users"]
        cls.Category = cls.env["workflow.approval.category"]
        cls.Version = cls.env["workflow.approval.category.version"]
        cls.Request = cls.env["workflow.base.approval.request"]

        unique = uuid4().hex[:8]
        workflow_group = cls.env.ref("workflow_engine.group_workflow_approval_user")
        internal_group = cls.env.ref("base.group_user")
        cls.admin_user = cls.env.ref("base.user_admin")

        def _new_user(role):
            login = f"wf_force_{role}_{unique}"
            return cls.User.with_context(no_reset_password=True, active_test=False).create(
                {
                    "name": f"Workflow Force {role.title()} {unique}",
                    "login": login,
                    "email": f"{login}@example.com",
                    "group_ids": [(6, 0, [internal_group.id, workflow_group.id])],
                }
            )

        cls.normal_user = _new_user("normal")
        cls.inactive_user = _new_user("inactive")
        cls.inactive_user.sudo().write({"active": False})

        base_request_model = cls.env["ir.model"]._get("workflow.base.approval.request")
        cls.base_category = cls.Category.sudo().create(
            {
                "name": f"Force Creator Base {unique}",
                "res_model": base_request_model.id,
                "zero_trust_enforced": False,
            }
        )
        cls.base_version = cls.Version.sudo().create(
            {
                "name": f"v_force_base_{unique}",
                "category_id": cls.base_category.id,
                "is_active": True,
            }
        )
        cls.base_category.sudo().write({"active_version_id": cls.base_version.id})

        cls.child_model_record = cls.env["ir.model"].sudo().create(
            {
                "name": f"Workflow Force Creator Request {unique}",
                "model": f"x_wf_force_creator_{unique}",
                "state": "manual",
            }
        )
        cls.child_model_record.sudo().write({"is_approval": True})
        cls.child_model_name = cls.child_model_record.model

        cls.child_category = cls.Category.sudo().create(
            {
                "name": f"Force Creator Child {unique}",
                "res_model": cls.child_model_record.id,
                "zero_trust_enforced": False,
            }
        )
        cls.child_version = cls.Version.sudo().create(
            {
                "name": f"v_force_child_{unique}",
                "category_id": cls.child_category.id,
                "is_active": True,
                "bpmn_xml": FORCED_CREATOR_BPMN,
            }
        )
        cls.child_category.sudo().write({"active_version_id": cls.child_version.id})
        cls.child_version.action_sync_bpmn_metadata()

    def _base_request_vals(self, name):
        return {
            "name": f"{name}_{uuid4().hex[:8]}",
            "category_id": self.base_category.id,
            "request_owner_id": self.normal_user.id,
        }

    def test_normal_create_without_force_context_uses_current_user(self):
        request = self.Request.with_user(self.normal_user).create(
            self._base_request_vals("REQ_FORCE_NORMAL")
        )

        self.assertEqual(request.create_uid, self.normal_user)

    def test_admin_force_created_uid_accepts_inactive_existing_user(self):
        request = self.Request.with_user(self.admin_user).with_context(
            force_created_uid=self.inactive_user.id
        ).create(self._base_request_vals("REQ_FORCE_INACTIVE"))

        self.assertEqual(request.create_uid, self.inactive_user)
        self.assertEqual(request.owner_user_id, self.inactive_user)

    def test_missing_force_created_uid_falls_back_to_current_user(self):
        request = self.Request.with_user(self.admin_user).with_context(
            force_created_uid=999999999
        ).create(self._base_request_vals("REQ_FORCE_MISSING"))

        self.assertEqual(request.create_uid, self.admin_user)

    def test_non_admin_force_created_uid_is_ignored(self):
        request = self.Request.with_user(self.normal_user).with_context(
            force_created_uid=self.inactive_user.id
        ).create(self._base_request_vals("REQ_FORCE_UNTRUSTED"))

        self.assertEqual(request.create_uid, self.normal_user)

    def test_child_create_first_submission_assignee_uses_forced_creator(self):
        child_request = self.env[self.child_model_name].sudo().with_context(
            force_created_uid=self.inactive_user.id,
            tracking_disable=True,
            mail_create_nolog=True,
            mail_create_nosubscribe=True,
            workflow_activity_no_email=True,
        ).create(
            {
                "name": f"REQ_FORCE_CHILD_{uuid4().hex[:8]}",
                "category_id": self.child_category.id,
                "request_owner_id": self.normal_user.id,
            }
        )

        base_request = child_request.x_approval_base_id
        submission_rows = base_request.approver_ids.filtered(
            lambda row: row.current_meta_id.node_id == "Task_Submission"
            and row.status == "new"
        )
        self.assertEqual(base_request.create_uid, self.inactive_user)
        self.assertEqual(base_request.current_node_id, "Task_Submission")
        self.assertEqual(submission_rows[:1].user_id, self.inactive_user)

    def test_child_model_without_search_view_gets_engine_default_search_filters(self):
        arch, view = self.env[self.child_model_name]._get_view(view_type="search")

        self.assertFalse(view)
        self.assertTrue(arch.xpath("//field[@name='request_owner_id']"))
        self.assertTrue(arch.xpath("//field[@name='request_owner_department']"))
        self.assertTrue(arch.xpath("//filter[@name='filter_create_date' and @date='create_date']"))
        self.assertTrue(arch.xpath("//filter[@name='filter_my_request_owner']"))
        self.assertTrue(arch.xpath("//group/filter[@name='groupby_request_owner_department']"))
        self.assertTrue(arch.xpath("//group/filter[@name='groupby_create_date']"))
        self.assertTrue(arch.xpath("//filter[@name='activities_overdue' and @invisible='1']"))

    def test_child_model_custom_search_view_keeps_own_filters(self):
        custom_view = self.env["ir.ui.view"].sudo().create(
            {
                "name": "Workflow Force Creator Custom Search",
                "model": self.child_model_name,
                "type": "search",
                "arch": """
                    <search>
                        <field name="name"/>
                        <filter name="custom_only" string="Custom Only" domain="[]"/>
                    </search>
                """,
            }
        )

        arch, view = self.env[self.child_model_name]._get_view(view_type="search")

        self.assertEqual(view, custom_view)
        self.assertTrue(arch.xpath("//filter[@name='custom_only']"))
        self.assertFalse(arch.xpath("//filter[@name='filter_create_date']"))
        self.assertFalse(arch.xpath("//group/filter[@name='groupby_request_owner_department']"))
        self.assertTrue(arch.xpath("//filter[@name='activities_overdue' and @invisible='1']"))
