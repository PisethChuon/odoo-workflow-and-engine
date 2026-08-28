# -*- coding: utf-8 -*-

ALWAYS_TRUE_DOMAIN = "[(1, '=', 1)]"


def migrate(cr, version):
    # Keep this migration mirrored in workflow_studio so `-u workflow_studio`
    # backfills routing data even when the dependency update path is selective.
    cr.execute(
        """
        UPDATE workflow_category_task_approval_group
           SET user_domain = %s
         WHERE user_domain IS NULL
            OR btrim(user_domain) = ''
            OR btrim(user_domain) = '[]'
        """,
        (ALWAYS_TRUE_DOMAIN,),
    )
    cr.execute(
        """
        UPDATE workflow_category_task_approval_group
           SET domain = %s
         WHERE domain IS NULL
            OR btrim(domain) = ''
            OR btrim(domain) = '[]'
        """,
        (ALWAYS_TRUE_DOMAIN,),
    )
    cr.execute(
        """
        UPDATE workflow_category_version_meta_task
           SET assignment_user_domain = %s
         WHERE btrim(coalesce(assignment_user_domain, '')) = '[]'
        """,
        (ALWAYS_TRUE_DOMAIN,),
    )
    cr.execute(
        """
        UPDATE workflow_category_version_meta_task
           SET approval_group_domain = %s
         WHERE btrim(coalesce(approval_group_domain, '')) = '[]'
        """,
        (ALWAYS_TRUE_DOMAIN,),
    )
    cr.execute(
        """
        UPDATE workflow_category_version_meta_task
           SET notification_recipient_domain = %s
         WHERE (
                notification_recipient_source = 'domain'
                OR (
                    coalesce(notification_recipient_source, '') = ''
                    AND coalesce(notification_recipient_mode, '') IN ('domain', 'both')
                )
            )
           AND btrim(coalesce(notification_recipient_domain, '')) = '[]'
        """,
        (ALWAYS_TRUE_DOMAIN,),
    )
    cr.execute(
        """
        UPDATE workflow_category_version_meta_task
           SET notification_recipient_domain = %s
         WHERE (
                notification_recipient_source = 'domain'
                OR (
                    coalesce(notification_recipient_source, '') = ''
                    AND coalesce(notification_recipient_mode, '') IN ('domain', 'both')
                )
            )
           AND btrim(coalesce(notification_recipient_domain, '')) = ''
           AND btrim(coalesce(notification_recipient_filter_domain, '')) = '[]'
        """,
        (ALWAYS_TRUE_DOMAIN,),
    )
    cr.execute(
        """
        UPDATE workflow_category_version_meta_task
           SET notification_recipient_filter_domain = %s
         WHERE notification_recipient_source IN ('approval_group_users', 'group_users', 'node_users')
           AND btrim(coalesce(notification_recipient_filter_domain, '')) = '[]'
        """,
        (ALWAYS_TRUE_DOMAIN,),
    )
    cr.execute(
        """
        UPDATE workflow_category_version_meta_task
           SET notification_recipient_filter_domain = %s
         WHERE notification_recipient_source IN ('approval_group_users', 'group_users', 'node_users')
           AND btrim(coalesce(notification_recipient_filter_domain, '')) = ''
           AND btrim(coalesce(notification_recipient_domain, '')) IN ('', '[]')
        """,
        (ALWAYS_TRUE_DOMAIN,),
    )
    cr.execute(
        """
        UPDATE workflow_approval_action_email_recipient
           SET domain = %s
         WHERE source = 'domain'
           AND btrim(coalesce(domain, '')) = '[]'
        """,
        (ALWAYS_TRUE_DOMAIN,),
    )
    cr.execute(
        """
        UPDATE workflow_approval_action_email_recipient
           SET domain = %s
         WHERE source IN ('approval_group_users', 'group_users', 'node_users')
           AND btrim(coalesce(domain, '')) IN ('', '[]')
        """,
        (ALWAYS_TRUE_DOMAIN,),
    )
