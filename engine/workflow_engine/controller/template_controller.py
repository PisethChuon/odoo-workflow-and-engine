import os
import logging
from odoo import http
from odoo.http import request
from odoo.modules.module import get_module_path  # ✅ Odoo 19

_logger = logging.getLogger(__name__)

class TemplateDownloadController(http.Controller):

    @http.route(
        '/download/template/<string:module>/<string:filename>',
        type='http',
        auth='public',   # 🔓
        csrf=False
    )
    def download_template(self, module, filename, **kw):
        try:
            module_path = get_module_path(module)
            if not module_path:
                return request.not_found()

            file_path = os.path.join(
                module_path,
                'static', 'src', 'templates', filename
            )

            if not os.path.exists(file_path):
                _logger.error("File not found: %s", file_path)
                return request.not_found()

            with open(file_path, 'rb') as f:
                content = f.read()

            return request.make_response(
                content,
                headers=[
                    ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                    ('Content-Disposition', http.content_disposition(filename)),
                ],
            )

        except Exception:
            _logger.exception("Template download failed")
            return request.make_response(
                "<h2>Internal Server Error</h2>",
                headers=[('Content-Type', 'text/html')],
            )
