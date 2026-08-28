# -*- coding: utf-8 -*-

from lxml import etree

from odoo.tests import common


class TestApprovalGroupConfig(common.TransactionCase):
    def setUp(self):
        super().setUp()
        self.ApprovalGroup = self.env["workflow.approval.group"]
        self.ApprovalGroupLine = self.env["workflow.approval.group.line"]
        self.ApprovalGroupTeam = self.env["workflow.approval.group.team"]
        self.ApprovalCategory = self.env["workflow.approval.category"]
        self.Department = self.env["hr.department"]
        self.base_request_model = self.env["ir.model"]._get("workflow.base.approval.request")

    def test_approval_group_hierarchy_fields_are_optional_and_writable(self):
        department = self.Department.create({"name": "Workflow Config Department"})
        category = self.ApprovalCategory.create(
            {
                "name": "Workflow Config Category",
                "res_model": self.base_request_model.id,
            }
        )
        line = self.ApprovalGroupLine.create(
            {
                "name": "Workflow Config Line",
                "department_id": department.id,
            }
        )
        team = self.ApprovalGroupTeam.create(
            {
                "name": "Workflow Config Team",
                "line_id": line.id,
            }
        )

        group = self.ApprovalGroup.create({"name": "Workflow Config Group"})
        self.assertFalse(group.category_id)
        self.assertFalse(group.line_id)
        self.assertFalse(group.team_id)

        group.write(
            {
                "category_id": category.id,
                "department_id": department.id,
                "line_id": line.id,
                "team_id": team.id,
            }
        )

        self.assertEqual(group.category_id, category)
        self.assertEqual(group.department_id, department)
        self.assertEqual(group.line_id, line)
        self.assertEqual(group.team_id, team)
        self.assertEqual(team.department_id, department)

    def test_approval_group_views_expose_hierarchy_fields_and_grouping(self):
        list_view = self.env.ref("workflow_engine.workflow_approval_category_approver_group_view_list")
        search_view = self.env.ref("workflow_engine.workflow_approval_group_view_search")
        action = self.env.ref("workflow_engine.approval_category_approver_group_action")

        list_arch = etree.fromstring(
            self.ApprovalGroup.get_view(view_id=list_view.id, view_type="list")["arch"].encode()
        )
        self.assertEqual(list_arch.tag, "list")
        self.assertEqual(list_arch.get("multi_edit"), "1")
        self.assertTrue(list_arch.xpath(".//field[@name='category_id']"))
        self.assertTrue(list_arch.xpath(".//field[@name='department_id']"))
        self.assertTrue(list_arch.xpath(".//field[@name='line_id']"))
        self.assertTrue(list_arch.xpath(".//field[@name='team_id']"))

        search_arch = etree.fromstring(
            self.ApprovalGroup.get_view(view_id=search_view.id, view_type="search")["arch"].encode()
        )
        self.assertTrue(search_arch.xpath(".//field[@name='category_id']"))
        self.assertTrue(search_arch.xpath(".//field[@name='department_id']"))
        self.assertTrue(search_arch.xpath(".//field[@name='line_id']"))
        self.assertTrue(search_arch.xpath(".//field[@name='team_id']"))
        self.assertTrue(
            search_arch.xpath(".//filter[@name='group_by_category' and contains(@context, \"category_id\")]")
        )
        self.assertTrue(
            search_arch.xpath(".//filter[@name='group_by_department' and contains(@context, \"department_id\")]")
        )
        self.assertTrue(search_arch.xpath(".//filter[@name='group_by_line' and contains(@context, \"line_id\")]"))
        self.assertTrue(search_arch.xpath(".//filter[@name='group_by_team' and contains(@context, \"team_id\")]"))
        self.assertEqual(action.search_view_id, search_view)

    def test_line_and_team_configuration_actions_are_available(self):
        line_action = self.env.ref("workflow_engine.workflow_approval_group_line_action")
        team_action = self.env.ref("workflow_engine.workflow_approval_group_team_action")
        line_search_view = self.env.ref("workflow_engine.workflow_approval_group_line_view_search")
        team_search_view = self.env.ref("workflow_engine.workflow_approval_group_team_view_search")

        line_form_arch = self.ApprovalGroupLine.get_view(
            view_id=self.env.ref("workflow_engine.workflow_approval_group_line_view_form").id,
            view_type="form",
        )["arch"]
        team_form_arch = self.ApprovalGroupTeam.get_view(
            view_id=self.env.ref("workflow_engine.workflow_approval_group_team_view_form").id,
            view_type="form",
        )["arch"]

        self.assertEqual(line_action.search_view_id, line_search_view)
        self.assertEqual(team_action.search_view_id, team_search_view)
        self.assertIn('field name="department_id"', line_form_arch)
        self.assertIn('field name="line_id"', team_form_arch)
        self.assertIn('field name="department_id"', team_form_arch)
