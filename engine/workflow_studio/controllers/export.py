# -*- coding: utf-8 -*-
import io
import logging
import zipfile

from odoo.http import Controller, content_disposition, request, route, serialize_exception
from werkzeug.exceptions import Forbidden, InternalServerError, NotFound

from .export_utils import StudioExportSerializer

_logger = logging.getLogger(__name__)


class StudioExporter(Controller):

    @route('/workflow_studio/export', type='http', auth='user', csrf=False)
    def export(self, token=None, active_id=None, **kw):
        env = request.env
        if not env.is_admin():
            raise Forbidden()
        if not active_id:
            raise NotFound()

        wizard = env['workflow.studio.export.wizard'].browse(int(active_id)).exists()
        if not wizard:
            raise NotFound()

        try:
            module = env['ir.module.module'].get_studio_module()
            export_info = wizard.get_export_info()

            content = self._generate_archive(env, module, export_info)
            return request.make_response(content, headers=[
                ('Content-Disposition', content_disposition('workflow_customizations.zip')),
                ('Content-Type', 'application/zip'),
                ('Content-Length', str(len(content))),
            ])
        except Exception as e:
            _logger.warning("Error while generating studio export", exc_info=True)
            se = serialize_exception(e)
            res = request.make_json_response({'code': 0, 'message': "Odoo Server Error", 'data': se}, status=500)
            raise InternalServerError(response=res) from e

    def _generate_archive(self, env, module, export_info):
        with io.BytesIO() as f:
            with zipfile.ZipFile(f, 'w', zipfile.ZIP_STORED) as archive:
                for filename, content in self.generate_module_files(module, export_info, env=env):
                    archive.writestr(f"{module.name}/{filename}", content)
            return f.getvalue()

    # Kept for backward compatibility with legacy tests/helpers that still call this API.
    def generate_module_files(self, module, export_info, env=None):
        def _iter_files():
            effective_env = env or getattr(request, "env", None)
            if not effective_env:
                raise RuntimeError("No Odoo env available to export module files.")
            yield from StudioExportSerializer(effective_env, module, export_info).serialize()

        return _iter_files()
