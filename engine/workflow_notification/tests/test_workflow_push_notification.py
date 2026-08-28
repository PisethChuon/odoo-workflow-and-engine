# -*- coding: utf-8 -*-
"""
Tests for workflow_notification push notification integration.

Verifies that when a workflow.approval.approver record is created or transitions
to an actionable status, notification.post and notification.live.post records
are queued so that:

  1. The workflow transaction does not wait on FCM delivery.
  2. A notification.inbox record is created for the user's MyPortal inbox.

Firebase is mocked at _firebase_send_message_from_configuration to guard against
accidental inline HTTP calls. All tests run inside a single transaction and are
rolled back.
"""
from contextlib import contextmanager
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestWorkflowPushNotification(TransactionCase):
    """Integration tests for workflow push-notification → inbox pipeline."""

    # ------------------------------------------------------------------
    # Class-level fixtures (created once per test class)
    # ------------------------------------------------------------------

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Push-notifications channel (defined by notification_push_channel module data)
        cls.push_channel = cls.env.ref(
            'notification_push_channel.notification_push_channel'
        )

        # Notification account that the engine will discover via the config param.
        # company_id=False makes it a global account; this is needed because the
        # test approver has no request_id → company_id=False, and
        # _workflow_get_push_account filters for company_id=False when the approver
        # has no company.
        cls.push_account = cls.env['notification.account'].sudo().create({
            'name': 'Test Push Account',
            'code': 'wf_test_push_app',
            'channel_id': cls.push_channel.id,
            'firebase_enable_push_notifications': True,
            'active': True,
            'company_id': False,
        })

        # Point the engine's config param to our test account code
        cls.env['ir.config_parameter'].sudo().set_param(
            'notification.push_account', 'wf_test_push_app'
        )
        cls.env['ir.config_parameter'].sudo().set_param(
            'workflow_notification.myportal_app_code', 'noc'
        )
        cls.env['ir.config_parameter'].sudo().set_param(
            'workflow_notification.push_enabled', '1'
        )

        # Internal user that will act as the approver
        cls.approver_user = cls.env['res.users'].sudo().create({
            'name': 'WF Push Test Approver',
            'login': 'wf_push_test_approver@naga.test',
            'username': '11541',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.reassigned_user = cls.env['res.users'].sudo().create({
            'name': 'WF Push Reassigned Approver',
            'login': 'wf_push_reassigned_approver@naga.test',
            'username': '11542',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.delegator_user = cls.env['res.users'].sudo().create({
            'name': 'WF Push Delegator',
            'login': 'wf_push_delegator@naga.test',
            'username': '11543',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

        # Minimal meta-task stubs — no required fields on this model
        cls.meta_task = cls.env['workflow.category.version.meta.task'].sudo().create({
            'name': 'Approval Step',
            'node_id': 'node_test_wf_push_01',
        })
        cls.muted_meta_task = cls.env['workflow.category.version.meta.task'].sudo().create({
            'name': 'Muted Approval Step',
            'node_id': 'node_test_wf_push_02',
            'push_notification_to_actor': False,
        })
        cls.notification_category = cls.env['workflow.approval.category'].sudo().create({
            'name': 'Workflow Notification Test Category',
            'res_model': cls.env['ir.model']._get('workflow.base.approval.request').id,
        })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_push_device(self, user=None, token_suffix='default'):
        """Register an active push device for *user* under the test account."""
        user = user or self.approver_user
        return self.env['notification.device'].sudo().create({
            'user_id': user.id,
            'notification_account_id': self.push_account.id,
            'platform': 'android',
            'push_token': 'fake_fcm_token_%s_%d' % (token_suffix, user.id),
            'is_active': True,
        })

    def _create_approver(self, status='new', user=None, skip_notify=True, meta_task=None, **extra_vals):
        """Create a workflow.approval.approver.

        skip_notify=True uses PUSH_CTX_SKIP context to keep both create() and
        write()-driven push notifications silent.
        """
        user = user or self.approver_user
        meta_task = meta_task or self.meta_task
        ctx = {'workflow_skip_push_notify': True} if skip_notify else {}
        vals = {
            'current_meta_id': meta_task.id,
            'previous_meta_id': meta_task.id,
            'user_id': user.id,
            'status': status,
        }
        vals.update(extra_vals)
        return self.env['workflow.approval.approver'].sudo().with_context(**ctx).create(vals)

    @contextmanager
    def _firebase_mock(self):
        """Return a context manager that mocks FCM HTTP calls to a no-op."""
        AccountModel = type(self.push_account)
        with patch.object(
            AccountModel,
            '_prepare_fcm_session',
            return_value=('test_fcm_token', 'https://firebase.test/send'),
        ), patch.object(
            AccountModel,
            '_firebase_send_message_from_configuration',
            return_value=[],
        ) as firebase_mock:
            yield firebase_mock

    def _inbox_count(self, user=None):
        user = user or self.approver_user
        return self.env['notification.inbox'].sudo().search_count([
            ('user_id', '=', user.id),
        ])

    def _latest_post_after(self, post_id):
        return self.env['notification.post'].sudo().search([
            ('id', '>', post_id),
            ('account_ids', 'in', [self.push_account.id]),
        ], order='id desc', limit=1)

    def _create_message_request(self, creator, owner, name):
        return self.env['workflow.base.approval.request'].with_user(creator).sudo().create({
            'name': name,
            'category_id': self.notification_category.id,
            'request_owner_id': owner.id,
        })

    # ------------------------------------------------------------------
    # 1. Happy path — inbox created on approver create()
    # ------------------------------------------------------------------

    def test_message_names_creator_and_different_request_owner(self):
        request = self._create_message_request(
            self.delegator_user,
            self.reassigned_user,
            'REQ_PUSH_CREATED_ON_BEHALF',
        )
        approver = self._create_approver(request_id=request.id)

        _title, body = approver._workflow_build_message()

        self.assertEqual(
            body,
            'REQ_PUSH_CREATED_ON_BEHALF needs your action at Approval Step. '
            'Requested by WF Push Delegator for WF Push Reassigned Approver.',
        )

    def test_message_names_creator_once_when_creator_is_request_owner(self):
        request = self._create_message_request(
            self.delegator_user,
            self.delegator_user,
            'REQ_PUSH_SAME_OWNER',
        )
        approver = self._create_approver(request_id=request.id)

        _title, body = approver._workflow_build_message()

        self.assertEqual(
            body,
            'REQ_PUSH_SAME_OWNER needs your action at Approval Step. '
            'Requested by WF Push Delegator.',
        )

    def test_inbox_created_on_approver_create(self):
        """Creating an approver with status='new' + push device → inbox record."""
        device = self._create_push_device(token_suffix='create')
        try:
            count_before = self._inbox_count()
            with self._firebase_mock():
                approver = self.env['workflow.approval.approver'].sudo().create({
                    'current_meta_id': self.meta_task.id,
                    'previous_meta_id': self.meta_task.id,
                    'user_id': self.approver_user.id,
                    'status': 'new',
                })

            inbox = self.env['notification.inbox'].sudo().search([
                ('user_id', '=', self.approver_user.id),
            ], limit=1)
            self.assertTrue(
                inbox,
                "notification.inbox record must be created for an actionable approver.",
            )
            self.assertEqual(inbox.state, 'delivered',
                             "New inbox items must start in 'delivered' state.")
            self.assertTrue(inbox.unread_badge,
                            "New inbox items must have unread_badge=True.")
            self.assertEqual(
                self._inbox_count() - count_before, 1,
                "Exactly one inbox record should be added.",
            )
        finally:
            device.sudo().unlink()

    def test_no_email_send_does_not_suppress_push_notification_on_approver_create(self):
        """Email-only suppression must not suppress workflow push/inbox notifications."""
        device = self._create_push_device(token_suffix='silent_create')
        try:
            count_before = self._inbox_count()
            with self._firebase_mock() as firebase_mock:
                self.env['workflow.approval.approver'].sudo().with_context(
                    no_email_send=True,
                ).create({
                    'current_meta_id': self.meta_task.id,
                    'previous_meta_id': self.meta_task.id,
                    'user_id': self.approver_user.id,
                    'status': 'new',
                })

            self.assertEqual(self._inbox_count() - count_before, 1)
            firebase_mock.assert_not_called()
        finally:
            device.sudo().unlink()

    def test_user_push_preference_suppresses_push_notification_on_approver_create(self):
        """Workflow-specific user preference must opt out of push/inbox notifications."""
        device = self._create_push_device(token_suffix='preference_disabled')
        self.approver_user.sudo().write({'wf_approval_push_enabled': False})
        try:
            count_before = self._inbox_count()
            with self._firebase_mock() as firebase_mock:
                self.env['workflow.approval.approver'].sudo().create({
                    'current_meta_id': self.meta_task.id,
                    'previous_meta_id': self.meta_task.id,
                    'user_id': self.approver_user.id,
                    'status': 'new',
                })

            self.assertEqual(self._inbox_count(), count_before)
            firebase_mock.assert_not_called()
        finally:
            self.approver_user.sudo().write({'wf_approval_push_enabled': True})
            device.sudo().unlink()

    def test_node_push_toggle_suppresses_direct_stage_entry_notification(self):
        """Node-level push toggle must suppress push/inbox for direct stage-entry assignment rows."""
        device = self._create_push_device(token_suffix='node_muted_direct')
        try:
            count_before = self._inbox_count()
            with self._firebase_mock() as firebase_mock:
                approver = self._create_approver(
                    status='new',
                    skip_notify=False,
                    meta_task=self.muted_meta_task,
                )

            self.assertEqual(self._inbox_count(), count_before)
            self.assertFalse(approver.push_notified_at)
            firebase_mock.assert_not_called()
        finally:
            device.sudo().unlink()

    def test_node_push_toggle_keeps_shared_assignment_notification(self):
        """Manual shared rows must still notify even when the node disables direct stage-entry push."""
        device = self._create_push_device(token_suffix='node_muted_shared')
        try:
            count_before = self._inbox_count()
            with self._firebase_mock():
                approver = self._create_approver(
                    status='new',
                    skip_notify=False,
                    meta_task=self.muted_meta_task,
                    delegation_mode='shared',
                    delegated_from_user_id=self.delegator_user.id,
                    delegated_to_user_id=self.approver_user.id,
                    delegated_by_user_id=self.delegator_user.id,
                )

            self.assertEqual(self._inbox_count(), count_before + 1)
            self.assertTrue(approver.push_notified_at)
        finally:
            device.sudo().unlink()

    def test_node_push_toggle_keeps_ooo_delegate_notification(self):
        """OOO delegation rows must still notify even when the node disables direct stage-entry push."""
        device = self._create_push_device(token_suffix='node_muted_ooo')
        try:
            count_before = self._inbox_count()
            with self._firebase_mock():
                approver = self._create_approver(
                    status='new',
                    skip_notify=False,
                    meta_task=self.muted_meta_task,
                    delegated_from_user_id=self.delegator_user.id,
                )

            self.assertEqual(self._inbox_count(), count_before + 1)
            self.assertTrue(approver.push_notified_at)
        finally:
            device.sudo().unlink()

    def test_no_notification_suppresses_push_notification_on_approver_create(self):
        """Short migration context must suppress push/inbox notifications."""
        device = self._create_push_device(token_suffix='silent_no_notification_create')
        try:
            count_before = self._inbox_count()
            with self._firebase_mock() as firebase_mock:
                self.env['workflow.approval.approver'].sudo().with_context(
                    no_notification=True,
                    tracking_disable=True,
                ).create({
                    'current_meta_id': self.meta_task.id,
                    'previous_meta_id': self.meta_task.id,
                    'user_id': self.approver_user.id,
                    'status': 'new',
                })

            self.assertEqual(self._inbox_count(), count_before)
            firebase_mock.assert_not_called()
        finally:
            device.sudo().unlink()

    def test_skip_push_context_suppresses_push_notification_on_approver_create(self):
        """Explicit push-skip context must keep internal create flows silent."""
        device = self._create_push_device(token_suffix='skip_ctx_create')
        try:
            count_before = self._inbox_count()
            with self._firebase_mock() as firebase_mock:
                approver = self._create_approver(status='new', skip_notify=True)

            self.assertEqual(self._inbox_count(), count_before)
            self.assertFalse(approver.push_notified_at)
            firebase_mock.assert_not_called()
        finally:
            device.sudo().unlink()

    def test_notification_failure_does_not_block_approver_create(self):
        """Push errors must never block workflow assignment creation."""
        ApproverModel = type(self.env['workflow.approval.approver'])
        with patch.object(
            ApproverModel,
            '_workflow_push_notify',
            side_effect=RuntimeError('push channel unavailable'),
        ):
            approver = self.env['workflow.approval.approver'].sudo().create({
                'current_meta_id': self.meta_task.id,
                'previous_meta_id': self.meta_task.id,
                'user_id': self.approver_user.id,
                'status': 'new',
            })

        self.assertTrue(approver.exists())
        self.assertEqual(approver.status, 'new')

    # ------------------------------------------------------------------
    # 2. push_notified_at is set after successful notification
    # ------------------------------------------------------------------

    def test_push_notified_at_set_after_notify(self):
        """push_notified_at must be stamped on the approver after notification."""
        device = self._create_push_device(token_suffix='notified_at')
        try:
            with self._firebase_mock():
                approver = self.env['workflow.approval.approver'].sudo().create({
                    'current_meta_id': self.meta_task.id,
                    'previous_meta_id': self.meta_task.id,
                    'user_id': self.approver_user.id,
                    'status': 'new',
                })
            self.assertTrue(
                approver.push_notified_at,
                "push_notified_at must be set after a successful push notification.",
            )
        finally:
            device.sudo().unlink()

    # ------------------------------------------------------------------
    # 3. notification.post + notification.live.post records are created
    # ------------------------------------------------------------------

    def test_notification_post_and_live_post_created(self):
        """One notification.post and one notification.live.post per notify."""
        device = self._create_push_device(token_suffix='post_lp')
        try:
            post_before = self.env['notification.post'].sudo().search_count([])
            live_before = self.env['notification.live.post'].sudo().search_count([])

            with self._firebase_mock():
                self.env['workflow.approval.approver'].sudo().create({
                    'current_meta_id': self.meta_task.id,
                    'previous_meta_id': self.meta_task.id,
                    'user_id': self.approver_user.id,
                    'status': 'new',
                })

            self.assertEqual(
                self.env['notification.post'].sudo().search_count([]),
                post_before + 1,
                "Exactly one notification.post must be created per approver notification.",
            )
            self.assertEqual(
                self.env['notification.live.post'].sudo().search_count([]),
                live_before + 1,
                "Exactly one notification.live.post must be created per approver notification.",
            )
        finally:
            device.sudo().unlink()

    def test_create_multi_groups_workflow_approvers_into_single_post(self):
        """One workflow step with four approvers must create one post targeting four users."""
        users = self.env['res.users'].sudo().create([
            {
                'name': 'WF Push Batch Approver 1',
                'login': 'wf_push_batch_1@naga.test',
                'username': '11551',
                'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
            },
            {
                'name': 'WF Push Batch Approver 2',
                'login': 'wf_push_batch_2@naga.test',
                'username': '11552',
                'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
            },
            {
                'name': 'WF Push Batch Approver 3',
                'login': 'wf_push_batch_3@naga.test',
                'username': '11553',
                'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
            },
            {
                'name': 'WF Push Batch Approver 4',
                'login': 'wf_push_batch_4@naga.test',
                'username': '11554',
                'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
            },
        ])
        devices = self.env['notification.device'].sudo().create([
            {
                'user_id': user.id,
                'notification_account_id': self.push_account.id,
                'platform': 'android',
                'push_token': 'fake_fcm_token_group_%d' % user.id,
                'is_active': True,
            }
            for user in users
        ])
        try:
            post_before = self.env['notification.post'].sudo().search_count([])
            live_before = self.env['notification.live.post'].sudo().search_count([])
            last_post_id = self.env['notification.post'].sudo().search([], order='id desc', limit=1).id or 0

            with self._firebase_mock() as firebase_mock:
                approvers = self.env['workflow.approval.approver'].sudo().create([
                    {
                        'current_meta_id': self.meta_task.id,
                        'previous_meta_id': self.meta_task.id,
                        'user_id': user.id,
                        'status': 'new',
                    }
                    for user in users
                ])
                firebase_mock.assert_not_called()

            post = self._latest_post_after(last_post_id)
            self.assertTrue(post, "Grouped workflow notification must create a notification.post.")
            self.assertEqual(
                self.env['notification.post'].sudo().search_count([]),
                post_before + 1,
                "Four approver rows on the same step must share one notification.post.",
            )
            self.assertEqual(
                self.env['notification.live.post'].sudo().search_count([]),
                live_before + 1,
                "Four approver rows on the same step must share one notification.live.post.",
            )
            self.assertEqual(
                post.user_domain,
                repr([('emp_code', 'in', users.sorted('id').mapped('emp_code'))]),
                "The posted workflow audience must be stored as employee codes when available.",
            )
            self.assertEqual(
                set(post.audience_ids.mapped('user_id').ids),
                set(users.ids),
                "The workflow post audience must contain all target approvers.",
            )
            self.assertEqual(
                set(post.audience_ids.mapped('state')),
                {'queued'},
                "Push-capable approvers should be visible immediately as queued audience rows.",
            )
            inbox_rows = self.env['notification.inbox'].sudo().search([
                ('post_id', '=', post.id),
            ])
            self.assertEqual(
                set(inbox_rows.mapped('user_id').ids),
                set(users.ids),
                "Inline inbox creation must cover every grouped workflow approver.",
            )
            self.assertTrue(
                all(approvers.mapped('push_notified_at')),
                "All grouped approver rows must be marked as notified after the shared post is queued.",
            )
        finally:
            devices.sudo().unlink()

    def test_employee_code_domain_is_stable_when_database_has_duplicate_codes(self):
        """Preprod data with an old duplicate code must not force workflow posts back to IDs."""
        self.env['res.users'].sudo().create({
            'name': 'WF Push Existing Duplicate Code',
            'login': 'wf_push_existing_duplicate_code@naga.test',
            'username': self.approver_user.emp_code,
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        approver = self._create_approver(status='new', skip_notify=True)

        self.assertEqual(
            approver._workflow_build_target_user_domain(self.approver_user),
            repr([('emp_code', 'in', [self.approver_user.emp_code])]),
            "Workflow notification domains must remain employee-code based when the target user has a code.",
        )

    def test_workflow_notifications_are_tagged_for_my_alerts(self):
        """Workflow inbox items must carry the WORKFLOW tag used by MyPortal My Alerts."""
        device = self._create_push_device(token_suffix='workflow_tag')
        try:
            last_post_id = self.env['notification.post'].sudo().search([], order='id desc', limit=1).id or 0

            with self._firebase_mock():
                approver = self.env['workflow.approval.approver'].sudo().create({
                    'current_meta_id': self.meta_task.id,
                    'previous_meta_id': self.meta_task.id,
                    'user_id': self.approver_user.id,
                    'status': 'new',
                })

            workflow_tag = self.env.ref('notification_app.notification_post_tag_workflow')
            post = self._latest_post_after(last_post_id)
            self.assertTrue(post, "Workflow notification must create a notification.post.")
            self.assertIn(
                workflow_tag,
                post.tag_ids,
                "Workflow notification.post must be tagged WORKFLOW.",
            )

            inbox = self.env['notification.inbox'].sudo().search([
                ('post_id', '=', post.id),
                ('user_id', '=', self.approver_user.id),
            ], limit=1)
            self.assertTrue(inbox, "Workflow notification must create an inbox item.")
            self.assertIn(
                'workflow',
                inbox.tag_ids.mapped('code'),
                "Inbox tag codes must include 'workflow' for the My Alerts tab.",
            )
        finally:
            device.sudo().unlink()

    def test_workflow_deeplink_targets_myportal_workflow_mini_app(self):
        """Workflow notifications must not emit legacy /web# links for MyPortal taps."""
        device = self._create_push_device(token_suffix='deeplink')
        try:
            last_post_id = self.env['notification.post'].sudo().search([], order='id desc', limit=1).id or 0

            with self._firebase_mock():
                approver = self.env['workflow.approval.approver'].sudo().create({
                    'current_meta_id': self.meta_task.id,
                    'previous_meta_id': self.meta_task.id,
                    'user_id': self.approver_user.id,
                    'status': 'new',
                })

            post = self._latest_post_after(last_post_id)
            self.assertTrue(post, "Workflow notification must create a notification.post.")
            deeplink = post.push_notification_target_url or ''
            parsed = urlparse(deeplink)
            query = parse_qs(parsed.query)

            self.assertEqual(parsed.scheme, 'app')
            self.assertEqual(parsed.netloc, 'myportal')
            self.assertEqual(parsed.path, '/mini')
            self.assertEqual(query.get('app'), ['noc'])
            self.assertEqual(query.get('session'), ['1'])
            self.assertNotIn('/web#', deeplink)
            self.assertIn('needs your action at Approval Step', post.push_notification_message)

            inbox = self.env['notification.inbox'].sudo().search([
                ('post_id', '=', post.id),
                ('user_id', '=', self.approver_user.id),
            ], limit=1)
            self.assertEqual(inbox.target_url, deeplink)

            report_path = approver._workflow_build_odoo_action_path(
                221, model='x_medical_request', res_id=14
            )
            report_deeplink = approver._workflow_build_myportal_deeplink(
                report_path,
                request_id=221,
                approver_id=approver.id,
                model='x_medical_request',
                res_id=14,
            )
            self.assertEqual(
                report_deeplink,
                'app://myportal/mini?app=noc&path=/odoo/approval-request-report/'
                'm-x_medical_request/14&session=1&request_id=221&approver_id=%s'
                '&module=workflow_approval&model=x_medical_request&res_id=14' % approver.id,
            )
        finally:
            device.sudo().unlink()

    def test_workflow_deeplink_app_code_is_configurable(self):
        """The MyPortal mini-app app= value must be configurable without code changes."""
        params = self.env['ir.config_parameter'].sudo()
        old_code = params.get_param('workflow_notification.myportal_app_code', '')
        approver = self._create_approver(status='new', skip_notify=True)
        try:
            params.set_param('workflow_notification.myportal_app_code', 'k2_v2')
            report_path = approver._workflow_build_odoo_action_path(
                221, model='x_medical_request', res_id=14
            )
            deeplink = approver._workflow_build_myportal_deeplink(
                report_path,
                request_id=221,
                approver_id=approver.id,
                model='x_medical_request',
                res_id=14,
            )
            parsed = urlparse(deeplink)
            query = parse_qs(parsed.query)
            self.assertEqual(query.get('app'), ['k2_v2'])
            self.assertEqual(
                query.get('path'),
                ['/odoo/approval-request-report/m-x_medical_request/14'],
            )
        finally:
            params.set_param('workflow_notification.myportal_app_code', old_code)

    # ------------------------------------------------------------------
    # 4. Inbox still records workflow item when push delivery cannot run
    # ------------------------------------------------------------------

    def test_inbox_created_without_push_device(self):
        """Missing push devices must not block the MyPortal inbox record."""
        # Ensure no device exists for the approver user on this account
        self.env['notification.device'].sudo().search([
            ('user_id', '=', self.approver_user.id),
            ('notification_account_id', '=', self.push_account.id),
        ]).unlink()

        count_before = self._inbox_count()

        with self._firebase_mock() as firebase_mock:
            self.env['workflow.approval.approver'].sudo().create({
                'current_meta_id': self.meta_task.id,
                'previous_meta_id': self.meta_task.id,
                'user_id': self.approver_user.id,
                'status': 'new',
            })
            firebase_mock.assert_not_called()

        self.assertEqual(
            self._inbox_count(),
            count_before + 1,
            "Inbox record should be created even when push delivery cannot run.",
        )

    # ------------------------------------------------------------------
    # 5. Idempotency — push_notified_at prevents re-notification
    # ------------------------------------------------------------------

    def test_system_parameter_can_disable_workflow_push_notifications(self):
        """workflow_notification.push_enabled=0 disables workflow notification queuing."""
        params = self.env['ir.config_parameter'].sudo()
        old_value = params.get_param('workflow_notification.push_enabled', '1')
        device = self._create_push_device(token_suffix='disabled_by_param')
        try:
            params.set_param('workflow_notification.push_enabled', '0')
            count_before = self._inbox_count()
            last_post_id = self.env['notification.post'].sudo().search([], order='id desc', limit=1).id or 0

            with self._firebase_mock() as firebase_mock:
                approver = self.env['workflow.approval.approver'].sudo().create({
                    'current_meta_id': self.meta_task.id,
                    'previous_meta_id': self.meta_task.id,
                    'user_id': self.approver_user.id,
                    'status': 'new',
                })
                firebase_mock.assert_not_called()

            self.assertFalse(approver.push_notified_at)
            self.assertEqual(self._inbox_count(), count_before)
            self.assertFalse(self._latest_post_after(last_post_id))
        finally:
            device.sudo().unlink()
            params.set_param('workflow_notification.push_enabled', old_value)

    def test_system_parameter_reenables_workflow_push_notifications(self):
        """workflow_notification.push_enabled=1 enables queued workflow notifications."""
        params = self.env['ir.config_parameter'].sudo()
        old_value = params.get_param('workflow_notification.push_enabled', '1')
        device = self._create_push_device(token_suffix='enabled_by_param')
        try:
            params.set_param('workflow_notification.push_enabled', '1')
            count_before = self._inbox_count()

            with self._firebase_mock() as firebase_mock:
                approver = self.env['workflow.approval.approver'].sudo().create({
                    'current_meta_id': self.meta_task.id,
                    'previous_meta_id': self.meta_task.id,
                    'user_id': self.approver_user.id,
                    'status': 'new',
                })
                firebase_mock.assert_not_called()

            self.assertTrue(approver.push_notified_at)
            self.assertEqual(self._inbox_count(), count_before + 1)
        finally:
            device.sudo().unlink()
            params.set_param('workflow_notification.push_enabled', old_value)

    def test_idempotency_push_notified_at(self):
        """An approver that already has push_notified_at set must NOT be re-notified."""
        device = self._create_push_device(token_suffix='idempotency')
        try:
            approver = self._create_approver(status='new')
            # Simulate previously notified
            approver.sudo().with_context(workflow_skip_push_notify=True).write({
                'push_notified_at': '2025-01-01 00:00:00',
            })

            count_before = self._inbox_count()

            with self._firebase_mock() as mock_send:
                approver._workflow_push_notify()
                mock_send.assert_not_called()

            self.assertEqual(
                self._inbox_count(),
                count_before,
                "push_notified_at guard: no additional inbox record must be created.",
            )
        finally:
            device.sudo().unlink()

    # ------------------------------------------------------------------
    # 6. Non-actionable status is skipped
    # ------------------------------------------------------------------

    def test_non_actionable_status_skipped(self):
        """Approvers in non-actionable statuses must not trigger notifications."""
        device = self._create_push_device(token_suffix='non_actionable')
        try:
            count_before = self._inbox_count()

            with self._firebase_mock() as mock_send:
                approver = self._create_approver(status='approved')
                # Manually invoke just to be explicit
                approver._workflow_push_notify()
                mock_send.assert_not_called()

            self.assertEqual(
                self._inbox_count(),
                count_before,
                "No inbox record should be created for a non-actionable status.",
            )
            self.assertFalse(
                approver.push_notified_at,
                "push_notified_at must remain unset for non-actionable status.",
            )
        finally:
            device.sudo().unlink()

    # ------------------------------------------------------------------
    # 7. Inactive user is skipped
    # ------------------------------------------------------------------

    def test_inactive_user_skipped(self):
        """Inactive users must not receive push notifications."""
        inactive_user = self.env['res.users'].sudo().with_context(no_reset_password=True).create({
            'name': 'Inactive WF Push User',
            'login': 'inactive_wf_push@naga.test',
            'active': False,
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        device = self.env['notification.device'].sudo().create({
            'user_id': inactive_user.id,
            'notification_account_id': self.push_account.id,
            'platform': 'ios',
            'push_token': 'fake_fcm_token_inactive_user',
            'is_active': True,
        })
        try:
            approver = self.env['workflow.approval.approver'].sudo().with_context(
                workflow_skip_push_notify=True
            ).create({
                'current_meta_id': self.meta_task.id,
                'previous_meta_id': self.meta_task.id,
                'user_id': inactive_user.id,
                'status': 'new',
            })

            with self._firebase_mock() as mock_send:
                approver._workflow_push_notify()
                mock_send.assert_not_called()

            self.assertFalse(
                approver.push_notified_at,
                "push_notified_at must not be set for inactive users.",
            )
        finally:
            device.sudo().unlink()
            inactive_user.sudo().unlink()

    # ------------------------------------------------------------------
    # 8. Non-actionable → actionable status transition triggers notify
    # ------------------------------------------------------------------

    def test_status_transition_triggers_notify(self):
        """Transitioning from non-actionable to actionable status sends notification."""
        device = self._create_push_device(token_suffix='transition')
        try:
            # Create in 'waiting' (non-actionable); no notification at create time
            with self._firebase_mock() as mock_send:
                approver = self._create_approver(status='waiting')
                mock_send.assert_not_called()

            # Now transition to 'pending' (actionable).
            # Strip workflow_skip_push_notify so the write() hook fires
            # (the approver recordset inherited that context from _create_approver).
            with self._firebase_mock():
                approver.sudo().with_context(workflow_skip_push_notify=False).write({'status': 'pending'})

            self.assertTrue(
                approver.push_notified_at,
                "push_notified_at must be set after a non-actionable → actionable transition.",
            )
            inbox = self.env['notification.inbox'].sudo().search([
                ('user_id', '=', self.approver_user.id),
            ], limit=1)
            self.assertTrue(
                inbox,
                "notification.inbox must be created after a non-actionable → actionable transition.",
            )
        finally:
            device.sudo().unlink()

    def test_muted_node_status_transition_does_not_notify(self):
        """Muted nodes must remain silent when a direct stage-entry row becomes actionable later."""
        device = self._create_push_device(token_suffix='node_muted_transition')
        try:
            with self._firebase_mock() as mock_send:
                approver = self._create_approver(
                    status='waiting',
                    meta_task=self.muted_meta_task,
                )
                mock_send.assert_not_called()

            count_before = self._inbox_count()
            with self._firebase_mock() as mock_send:
                approver.sudo().with_context(workflow_skip_push_notify=False).write({'status': 'pending'})
                mock_send.assert_not_called()

            self.assertEqual(self._inbox_count(), count_before)
            self.assertFalse(approver.push_notified_at)
        finally:
            device.sudo().unlink()

    # ------------------------------------------------------------------
    # 9. Already-actionable → actionable transition does NOT re-notify
    # ------------------------------------------------------------------

    def test_already_actionable_no_double_notify(self):
        """Transitioning from 'new' to 'pending' (both actionable) must not re-notify."""
        device = self._create_push_device(token_suffix='double_notify')
        try:
            with self._firebase_mock():
                approver = self.env['workflow.approval.approver'].sudo().create({
                    'current_meta_id': self.meta_task.id,
                    'previous_meta_id': self.meta_task.id,
                    'user_id': self.approver_user.id,
                    'status': 'new',
                })

            first_notified_at = approver.push_notified_at
            self.assertTrue(first_notified_at, "Should have been notified on create.")

            count_after_create = self._inbox_count()

            # Transition from 'new' → 'pending' (both actionable); old status was
            # already actionable, so write() hook must NOT fire again.
            with self._firebase_mock() as mock_send:
                approver.sudo().write({'status': 'pending'})
                mock_send.assert_not_called()

            self.assertEqual(
                approver.push_notified_at,
                first_notified_at,
                "push_notified_at must not change on an actionable → actionable transition.",
            )
            self.assertEqual(
                self._inbox_count(),
                count_after_create,
                "No additional inbox record on an actionable → actionable transition.",
            )
        finally:
            device.sudo().unlink()

    def test_reopened_actionable_row_re_notifies(self):
        """A reused approver row must notify again when reopened as actionable."""
        device = self._create_push_device(token_suffix='reopen')
        try:
            with self._firebase_mock():
                approver = self.env['workflow.approval.approver'].sudo().create({
                    'current_meta_id': self.meta_task.id,
                    'previous_meta_id': self.meta_task.id,
                    'user_id': self.approver_user.id,
                    'status': 'new',
                })

            approver.sudo().with_context(workflow_skip_push_notify=True).write({
                'status': 'closed',
                'push_notified_at': '2025-01-01 00:00:00',
            })
            old_notified_at = approver.push_notified_at
            count_before = self._inbox_count()

            with self._firebase_mock() as firebase_mock:
                approver.sudo().write({'status': 'new'})
                firebase_mock.assert_not_called()

            approver.invalidate_recordset(['push_notified_at'])
            self.assertEqual(
                self._inbox_count(),
                count_before + 1,
                "Reopened actionable rows must create a fresh inbox item.",
            )
            self.assertNotEqual(
                approver.push_notified_at,
                old_notified_at,
                "Reopened actionable rows must refresh push_notified_at.",
            )
        finally:
            device.sudo().unlink()

    def test_notification_failure_does_not_block_status_transition(self):
        """Push errors must never block workflow status transitions."""
        approver = self._create_approver(status='closed', skip_notify=True)
        ApproverModel = type(self.env['workflow.approval.approver'])

        with patch.object(
            ApproverModel,
            '_workflow_push_notify',
            side_effect=RuntimeError('push channel unavailable'),
        ):
            result = approver.sudo().with_context(
                workflow_skip_push_notify=False,
            ).write({'status': 'new'})

        self.assertTrue(result)
        self.assertEqual(approver.status, 'new')

    def test_reassigned_actionable_row_notifies_new_user(self):
        """Changing the assignee on an open row must notify the new user."""
        device_old = self._create_push_device(token_suffix='reassign_old')
        device_new = self._create_push_device(
            user=self.reassigned_user,
            token_suffix='reassign_new',
        )
        try:
            with self._firebase_mock():
                approver = self.env['workflow.approval.approver'].sudo().create({
                    'current_meta_id': self.meta_task.id,
                    'previous_meta_id': self.meta_task.id,
                    'user_id': self.approver_user.id,
                    'status': 'new',
                })

            approver.sudo().with_context(workflow_skip_push_notify=True).write({
                'push_notified_at': '2025-01-01 00:00:00',
            })
            old_user_count = self._inbox_count(self.approver_user)
            new_user_count = self._inbox_count(self.reassigned_user)

            with self._firebase_mock() as firebase_mock:
                approver.sudo().write({'user_id': self.reassigned_user.id})
                firebase_mock.assert_not_called()

            self.assertEqual(
                self._inbox_count(self.approver_user),
                old_user_count,
                "Reassignment must not send another inbox item to the old user.",
            )
            self.assertEqual(
                self._inbox_count(self.reassigned_user),
                new_user_count + 1,
                "Reassignment must send an inbox item to the new user.",
            )
        finally:
            device_old.sudo().unlink()
            device_new.sudo().unlink()

    # ------------------------------------------------------------------
    # 12. Missing push account — silently skipped
    # ------------------------------------------------------------------

    def test_missing_push_account_skipped(self):
        """When no push account matches the config param, notify silently skips."""
        # Override the config param to point at a non-existent code
        old_code = self.env['ir.config_parameter'].sudo().get_param(
            'notification.push_account', ''
        )
        self.env['ir.config_parameter'].sudo().set_param(
            'notification.push_account', 'nonexistent_account_xyz'
        )
        device = self._create_push_device(token_suffix='missing_account')
        try:
            count_before = self._inbox_count()

            # create() fires _workflow_push_notify() → no account found → silently skips
            approver = self._create_approver(status='new', skip_notify=False)
            # Manual call to confirm no error raised
            approver._workflow_push_notify()

            self.assertEqual(
                self._inbox_count(),
                count_before,
                "No inbox record must be created when the push account is not found.",
            )
        finally:
            device.sudo().unlink()
            self.env['ir.config_parameter'].sudo().set_param(
                'notification.push_account', old_code
            )

    def test_push_notify_uses_sudo_for_notification_post_creation(self):
        """Approvers without notification access must still queue workflow posts."""
        device = self._create_push_device(token_suffix='sudo_notify')
        try:
            approver = self._create_approver(status='new', skip_notify=True)
            last_post_id = self.env['notification.post'].sudo().search([], order='id desc', limit=1).id or 0

            with self._firebase_mock() as firebase_mock:
                approver.with_user(self.approver_user).with_context(
                    workflow_skip_push_notify=False,
                )._workflow_push_notify()
                firebase_mock.assert_not_called()

            approver.invalidate_recordset(['push_notified_at'])
            post = self._latest_post_after(last_post_id)
            self.assertTrue(
                post,
                "Workflow push notification must create a post even for a basic internal approver user.",
            )
            self.assertTrue(
                approver.push_notified_at,
                "push_notified_at must still be written when the caller lacks notification access.",
            )
            self.assertEqual(
                post.user_domain,
                repr([('emp_code', 'in', [self.approver_user.emp_code])]),
                "Single-approver workflow posts should keep a readable employee-code audience filter.",
            )
        finally:
            device.sudo().unlink()

    def test_actor_assigned_to_next_stage_is_excluded_from_notification_targets(self):
        """The user who triggered the stage move may stay assigned but must not be notified."""
        device_actor = self._create_push_device(
            user=self.approver_user,
            token_suffix='actor_skip_actor',
        )
        device_other = self._create_push_device(
            user=self.reassigned_user,
            token_suffix='actor_skip_other',
        )
        try:
            last_post_id = self.env['notification.post'].sudo().search([], order='id desc', limit=1).id or 0

            with self._firebase_mock() as firebase_mock:
                approvers = self.env['workflow.approval.approver'].sudo().with_context(
                    workflow_notification_actor_user_id=self.approver_user.id,
                ).create([
                    {
                        'current_meta_id': self.meta_task.id,
                        'previous_meta_id': self.meta_task.id,
                        'user_id': self.approver_user.id,
                        'status': 'new',
                    },
                    {
                        'current_meta_id': self.meta_task.id,
                        'previous_meta_id': self.meta_task.id,
                        'user_id': self.reassigned_user.id,
                        'status': 'new',
                    },
                ])
                firebase_mock.assert_not_called()

            post = self._latest_post_after(last_post_id)
            self.assertTrue(post, "The next-stage workflow post must still be created for the remaining approvers.")
            self.assertEqual(
                post.user_domain,
                repr([('emp_code', 'in', [self.reassigned_user.emp_code])]),
                "The actor must be removed from the push notification audience filter.",
            )
            self.assertEqual(
                post.audience_ids.mapped('user_id').ids,
                [self.reassigned_user.id],
                "Only the non-actor assignee should appear in the notification audience.",
            )
            actor_inbox = self.env['notification.inbox'].sudo().search([
                ('post_id', '=', post.id),
                ('user_id', '=', self.approver_user.id),
            ])
            other_inbox = self.env['notification.inbox'].sudo().search([
                ('post_id', '=', post.id),
                ('user_id', '=', self.reassigned_user.id),
            ])
            self.assertFalse(
                actor_inbox,
                "The actor must remain assigned but must not receive the next-stage inbox notification.",
            )
            self.assertTrue(
                other_inbox,
                "Other assignees on the same stage must still receive the notification.",
            )
            self.assertTrue(
                all(approvers.mapped('push_notified_at')),
                "All stage assignee rows should be marked handled once notification suppression is applied.",
            )
        finally:
            device_actor.sudo().unlink()
            device_other.sudo().unlink()
