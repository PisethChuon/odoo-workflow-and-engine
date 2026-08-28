"""Remove metadata left by the retired dynamic import transient models."""

import logging


_logger = logging.getLogger(__name__)

STALE_MODEL_NAMES = (
    "dynamic.import.wizard",
    "dynamic.import.wizard.line",
)

# These optional metadata tables can retain field references without a
# database-level cascade on every supported database revision.
FIELD_REFERENCE_COLUMNS = (
    ("base_automation_on_change_field_rel", "field_id"),
    ("base_automation_trigger_field_rel", "field_id"),
    ("ir_actions_server_fields_lines", "col1"),
    ("ir_act_server_field_rel", "field_id"),
    ("ir_default", "field_id"),
    ("ir_filters", "field_id"),
    ("ir_model_constraint", "field_id"),
    ("ir_model_fields_group_rel", "field_id"),
    ("ir_model_fields_selection", "field_id"),
    ("ir_model_inherit", "parent_field_id"),
    ("ir_model_relation", "field_id"),
    ("ir_property", "fields_id"),
    ("mail_tracking_value", "field_id"),
)


def _table_column_exists(cr, table_name, column_name):
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = %s
           AND column_name = %s
        """,
        (table_name, column_name),
    )
    return bool(cr.fetchone())


def _delete_external_ids(cr, model_name, res_ids):
    if not res_ids:
        return
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE model = %s
           AND res_id = ANY(%s)
        """,
        (model_name, res_ids),
    )


def migrate(cr, version):
    if not version:
        return

    cr.execute(
        """
        SELECT id
          FROM ir_model_fields
         WHERE model = ANY(%s)
        """,
        (list(STALE_MODEL_NAMES),),
    )
    field_ids = [row[0] for row in cr.fetchall()]

    if field_ids:
        for table_name, column_name in FIELD_REFERENCE_COLUMNS:
            if not _table_column_exists(cr, table_name, column_name):
                continue
            cr.execute(
                f'DELETE FROM "{table_name}" WHERE "{column_name}" = ANY(%s)',
                (field_ids,),
            )
        _delete_external_ids(cr, "ir.model.fields", field_ids)
        cr.execute(
            "DELETE FROM ir_model_fields WHERE id = ANY(%s)",
            (field_ids,),
        )

    cr.execute(
        """
        SELECT id
          FROM ir_model
         WHERE model = ANY(%s)
        """,
        (list(STALE_MODEL_NAMES),),
    )
    model_ids = [row[0] for row in cr.fetchall()]
    if model_ids:
        _delete_external_ids(cr, "ir.model", model_ids)
        cr.execute(
            "DELETE FROM ir_model WHERE id = ANY(%s)",
            (model_ids,),
        )

    _logger.info(
        "Removed %s stale fields and %s stale models for retired workflow import models: %s",
        len(field_ids),
        len(model_ids),
        ", ".join(STALE_MODEL_NAMES),
    )
