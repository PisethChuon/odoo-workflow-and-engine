import logging

_logger = logging.getLogger(__name__)

def uninstall_hook(env):
    """Safely clean up Gate Pass module tables and related workflow categories."""
    _model_names = ['x_item_request']
    _module_name = 'item_request'  # Adjust this to your real module name

    _logger.info("🧹 Starting uninstall cleanup for models: %s", _model_names)
    
    _logger.info("🗑️ Dropping physical columns from dynamic_import_wizard")
    cr = env.cr

    
    try:
        cr.execute("""
            ALTER TABLE dynamic_import_wizard 
            DROP COLUMN IF EXISTS x_item_request_id,
            DROP COLUMN IF EXISTS x_item_line_id,
            DROP COLUMN IF EXISTS x_sub_itemline_id,
            DROP COLUMN IF EXISTS x_comment;
        """)
 
        cr.commit() 
        _logger.info("Successfully dropped columns and committed.")
    except Exception as e:
        cr.rollback()
        _logger.error("Failed to drop columns: %s", e)

    for model_name in _model_names:
        if model_name not in env:
            _logger.warning("⚠️ Model %s not found in environment, skipping.", model_name)
            continue

        model = env[model_name]
        # Check if the model actually belongs to our module
        ir_model = env['ir.model'].search([('model', '=', model._name)], limit=1)
              # Safely detect module source
        model_data = env['ir.model.data'].search([
            ('model', '=', 'ir.model'),
            ('res_id', '=', ir_model.id)
        ], limit=1)

        module_name = model_data.module or 'unknown'
        
        if ir_model and module_name == _module_name:
            _logger.info("✅ Model %s belongs to this module (%s). Proceeding with cleanup.", model_name, module_name)
        else:
            _logger.warning("⛔ Skipping model %s — belongs to another module or unknown source.", model_name)
            continue

        # Step 1: Delete related approval requests and categories
        categories = env['workflow.approval.category'].search([('res_model_name', '=', model._name)])
        if categories:
            approval_requests = env['workflow.base.approval.request'].search([('category_id', 'in', categories.ids)])
            if approval_requests:
                _logger.info("🗑️ Deleting %d approval requests for model %s", len(approval_requests), model_name)
              # FIX: Loop to avoid "Expected singleton" error in custom unlink logic
                for request in approval_requests:
                    request.unlink()
            else:
                _logger.info("ℹ️ No approval requests found for %s", model_name)

            _logger.info("🗑️ Deleting %d workflow categories for model %s", len(categories), model_name)
            categories.unlink()
        else:
            _logger.info("ℹ️ No workflow categories for %s", model_name)

    _logger.info("✅ Gate Pass uninstall cleanup completed safely.")
