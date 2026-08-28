# -*- coding: utf-8 -*-

CUSTOM_MODULE = "workflow_studio_customization"


def migrate(cr, version):
    cr.execute(
        "SELECT id FROM ir_module_module WHERE name = %s",
        (CUSTOM_MODULE,),
    )
    row = cr.fetchone()
    if not row:
        return

    module_id = row[0]
    cr.execute(
        """
        UPDATE ir_module_module
           SET state = 'installed',
               imported = TRUE,
               application = FALSE
         WHERE id = %s
        """,
        (module_id,),
    )
    cr.execute(
        """
        DELETE FROM ir_module_module_dependency
         WHERE module_id = %s
           AND name = 'workflow_studio'
        """,
        (module_id,),
    )
