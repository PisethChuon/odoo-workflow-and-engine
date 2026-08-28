# -*- coding: utf-8 -*-
import ast
import base64
import contextlib
import io
import json
import logging
import pprint
import re
import time
import zipfile

from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

DISALLOWED_DYNAMIC_FIELD_PARAMS = {"tracking", "auto_join"}  # warning-only, but better removed


class WorkflowStudioImportZipWizard(models.TransientModel):
    _name = "workflow.studio.import.zip.wizard"
    _description = "Workflow Studio ZIP Import Wizard"

    bundle_file = fields.Binary(string="Workflow ZIP", required=True)
    bundle_filename = fields.Char(string="Filename")

    detected_category_name = fields.Char(string="Detected Category", readonly=True)
    detected_version_name = fields.Char(string="Detected Version", readonly=True)
    detected_model_name = fields.Char(string="Detected Model", readonly=True)

    target_category_id = fields.Many2one(
        "workflow.approval.category",
        string="Import Into Category",
        help="Leave empty to create a category from the package manifest.",
    )
    existing_model_mode = fields.Selection(
        [
            ("sync", "Sync existing model"),
            ("duplicate", "Create duplicate category"),
            ("error", "Abort if model already exists"),
        ],
        string="Existing Model Handling",
        required=True,
        default="sync",
    )
    create_category_if_missing = fields.Boolean(default=True)
    deploy_after_import = fields.Boolean(default=True)
    run_dry_run_before_import = fields.Boolean(
        default=True,
        help="Run isolated dry-run validation before applying any changes.",
    )
    force_init_customizations = fields.Boolean(
        default=True,
        help="Force update when importing the embedded customizations module.",
    )
    import_warnings = fields.Text(readonly=True)

    # ------------------------------------------------------------
    # Security
    # ------------------------------------------------------------
    def _ensure_workflow_studio_admin(self):
        if not (
            self.env.user.has_group("workflow_engine.group_workflow_approval_admin")
            or self.env.user.has_group("base.group_system")
        ):
            raise AccessError(_("Only Workflow Approval Admin users can import workflow packages."))

    # ------------------------------------------------------------
    # ZIP helpers
    # ------------------------------------------------------------
    def _decode_bundle_content(self):
        self.ensure_one()
        if not self.bundle_file:
            raise UserError(_("Please upload a workflow ZIP file."))
        try:
            return base64.b64decode(self.bundle_file)
        except Exception as e:
            raise UserError(_("Invalid uploaded file content: %s") % e) from e

    def _read_bundle_manifest(self, raw_content):
        try:
            with zipfile.ZipFile(io.BytesIO(raw_content), "r") as z:
                mf = next((n for n in z.namelist() if n.endswith("manifest.json")), False)
                return json.loads(z.read(mf).decode("utf-8")) if mf else {}
        except zipfile.BadZipFile as e:
            raise UserError(_("Invalid ZIP file: %s") % e) from e
        except Exception as e:
            raise UserError(_("Cannot read package manifest: %s") % e) from e

    def _extract_customizations_zip(self, raw_content):
        with zipfile.ZipFile(io.BytesIO(raw_content), "r") as z:
            path = next(
                (
                    n for n in z.namelist()
                    if n.endswith("workflow_studio/workflow_customizations.zip")
                    or n.endswith("studio/workflow_customizations.zip")
                    or n.endswith("workflow_customizations.zip")
                ),
                False,
            )
            if path:
                return z.read(path)

            entries_by_relative = {}
            for n in z.namelist():
                if not n or n.endswith("/"):
                    continue
                normalized_name = n.lstrip("/").replace("\\", "/")
                if not normalized_name:
                    continue
                relative_name = normalized_name.split("/", 1)[1] if "/" in normalized_name else normalized_name
                entries_by_relative.setdefault(relative_name, n)

            payload_manifest_path = next(
                (
                    n for n in z.namelist()
                    if n.endswith("studio_customizations_manifest.json")
                    or n.endswith("data/studio_payload_manifest.json")
                    or n.endswith("studio_payload_manifest.json")
                ),
                False,
            )
            payload_entries = []
            payload_module_root = False
            if payload_manifest_path:
                try:
                    payload_meta = json.loads(z.read(payload_manifest_path).decode("utf-8"))
                except Exception:
                    payload_meta = {}
                requested_root = (payload_meta.get("module_root") or "").strip()
                if requested_root:
                    payload_module_root = requested_root
                for relative_name in payload_meta.get("files") or []:
                    normalized_relative = (relative_name or "").lstrip("/").replace("\\", "/")
                    if (
                        not normalized_relative
                        or normalized_relative.startswith("../")
                        or "/../" in normalized_relative
                    ):
                        continue
                    entry_name = entries_by_relative.get(normalized_relative)
                    if entry_name:
                        payload_entries.append((entry_name, normalized_relative))

            if not payload_entries:
                for n in z.namelist():
                    if not n or n.endswith("/"):
                        continue
                    normalized_name = n.lstrip("/").replace("\\", "/")
                    relative_name = False
                    if "/data/studio_payload/" in normalized_name:
                        relative_name = normalized_name.split("/data/studio_payload/", 1)[1].lstrip("/")
                    elif normalized_name.startswith("data/studio_payload/"):
                        relative_name = normalized_name[len("data/studio_payload/") :].lstrip("/")
                    if relative_name:
                        payload_entries.append((n, relative_name))

            if payload_entries:
                customizations_entries = []
                for entry_name, relative_name in payload_entries:
                    normalized_relative = relative_name.lstrip("/").replace("\\", "/")
                    if (
                        not normalized_relative
                        or normalized_relative.startswith("../")
                        or "/../" in normalized_relative
                    ):
                        continue
                    customizations_entries.append((entry_name, normalized_relative))
                if customizations_entries:
                    customizations_module_root = payload_module_root or "workflow_studio_customization"
                    with io.BytesIO() as out:
                        data_files = []
                        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as dst:
                            dst.writestr(f"{customizations_module_root}/__init__.py", b"")
                            for entry_name, relative_name in customizations_entries:
                                archive_name = f"{customizations_module_root}/{relative_name}"
                                dst.writestr(archive_name, z.read(entry_name))
                                if relative_name.endswith(".xml") or relative_name.endswith(".csv"):
                                    data_files.append(relative_name)
                            customizations_manifest = {
                                "name": "Workflow Studio customizations",
                                "version": "1.0",
                                "depends": ["workflow_studio"],
                                "data": sorted(set(data_files)),
                                "installable": True,
                                "application": False,
                                "license": "OPL-1",
                            }
                            dst.writestr(
                                f"{customizations_module_root}/__manifest__.py",
                                (
                                    pprint.pformat(customizations_manifest, sort_dicts=False)
                                    + "\n"
                                ).encode("utf-8"),
                            )
                        return out.getvalue()

            dir_entries = []
            for n in z.namelist():
                if not n or n.endswith("/"):
                    continue
                normalized_name = n.lstrip("/").replace("\\", "/")
                relative_name = False
                if "/customizations/" in normalized_name:
                    relative_name = normalized_name.split("/customizations/", 1)[1].lstrip("/")
                elif normalized_name.startswith("customizations/"):
                    relative_name = normalized_name[len("customizations/") :].lstrip("/")
                elif "/workflow_studio/customizations/" in normalized_name:
                    relative_name = normalized_name.split(
                        "/workflow_studio/customizations/", 1
                    )[1].lstrip("/")
                elif normalized_name.startswith("workflow_studio/customizations/"):
                    relative_name = normalized_name[len("workflow_studio/customizations/") :].lstrip("/")
                if relative_name:
                    dir_entries.append((n, relative_name))
            if not dir_entries:
                return False

            customizations_module_root = False
            customizations_entries = []
            for entry_name, relative_name in dir_entries:
                normalized_relative = relative_name.lstrip("/").replace("\\", "/")
                if not normalized_relative or normalized_relative.startswith("../") or "/../" in normalized_relative:
                    continue
                if normalized_relative == ".module_root":
                    try:
                        marker = z.read(entry_name).decode("utf-8", errors="ignore").strip()
                    except Exception:
                        marker = ""
                    if marker:
                        customizations_module_root = marker
                    continue
                customizations_entries.append((entry_name, normalized_relative))
            if not customizations_entries:
                return False

            with io.BytesIO() as out:
                with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as dst:
                    for entry_name, relative_name in customizations_entries:
                        if customizations_module_root and not relative_name.startswith(
                            f"{customizations_module_root}/"
                        ):
                            archive_name = f"{customizations_module_root}/{relative_name}"
                        else:
                            archive_name = relative_name
                        dst.writestr(archive_name, z.read(entry_name))
                return out.getvalue()

    def _detect_module_root(self, zf):
        # prefer root/__manifest__.py
        for n in zf.namelist():
            if n.endswith("__manifest__.py") and "/" in n:
                return n.split("/", 1)[0]
        roots = sorted({n.split("/", 1)[0] for n in zf.namelist() if "/" in n})
        return roots[0] if roots else "workflow_studio_customization"

    def _pre_import_customizations_zip_content(self, customizations_zip, *, dry_run=False, **kwargs):
        """
        Backward compatible hook (some code paths still call it).
        Returns: (notes, sanitized_zip_bytes)
        """
        notes = []
        sanitized, info = self._sanitize_customization_zip(
            customizations_zip,
            persist_xmlids=not bool(dry_run),
        )
        notes.append(_("Sanitized embedded module '%s'.") % info.get("module_root"))
        if info.get("remapped_model_refs"):
            notes.append(_("Remapped %s binding model ref(s).") % info["remapped_model_refs"])
        if info.get("removed_params"):
            notes.append(_("Removed %s unsupported ir.model.fields param(s).") % info["removed_params"])
        if dry_run:
            notes.append(_("Dry-run: module install skipped."))
        return notes, sanitized

    # ------------------------------------------------------------
    # XML helpers
    # ------------------------------------------------------------
    def _safe_xml_fromstring(self, xml_bytes):
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False, huge_tree=False)
        return etree.fromstring(xml_bytes, parser=parser)

    def _read_record_field(self, record_node, field_name):
        for f in record_node.findall("field"):
            if f.get("name") != field_name:
                continue
            refv = (f.get("ref") or "").strip()
            if refv:
                return {"ref": refv}
            return {"text": (f.text or "").strip()}
        return {}

    def _ensure_xmlid_binding(self, module, name, model, res_id):
        """Ensure ir.model.data row exists for module.name -> model,res_id.

        Use Odoo's upsert path to avoid search/create races under concurrent imports.
        """
        if not (module and name and model and res_id):
            return False
        record = self.env[model].sudo().browse(int(res_id)).exists()
        if not record:
            return False
        IrModelData = self.env["ir.model.data"].sudo().with_context(workflow_studio=True)
        existing = IrModelData.search([("module", "=", module), ("name", "=", name)], limit=1)
        # Fast path: identical binding already present, avoid any write/lock.
        if existing and existing.model == model and int(existing.res_id or 0) == int(record.id):
            return existing
        IrModelData._update_xmlids(
            [{"xml_id": f"{module}.{name}", "record": record, "noupdate": True}],
            update=False,
        )
        return IrModelData.search([("module", "=", module), ("name", "=", name)], limit=1)

    def _acquire_module_import_lock(self, cr, module_root):
        # Serialize customization imports per module root to prevent lock contention
        # on ir.model_data unique(module,name) during concurrent import requests.
        lock_key = f"workflow_studio_import:{module_root or 'workflow_studio_customization'}"
        cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (lock_key,))

    # ------------------------------------------------------------
    # CRITICAL: bind missing ir_model_XXXX refs (fixes ir_model_3707)
    # ------------------------------------------------------------
    def _bind_missing_ir_model_refs(self, zf, module_root):
        """
        If some XML references ref="ir_model_XXXX" but that id is not defined as <record model="ir.model">,
        create ir.model.data mapping to the correct ir.model row by inferring model name from the same record.
        """
        IrModelData = self.env["ir.model.data"].sudo()
        IrModel = self.env["ir.model"].sudo()

        # collect ir.model ids defined in zip
        defined_ir_model_ids = set()
        # collect referenced ir_model_XXXX with inferred technical model name
        needed = {}  # xmlid_name -> model_technical

        for n in zf.namelist():
            if not (n.startswith(f"{module_root}/") and n.endswith(".xml") and "/i18n/" not in n):
                continue
            try:
                root = self._safe_xml_fromstring(zf.read(n))
            except Exception:
                continue

            for rec in root.findall(".//record[@model='ir.model']"):
                rid = (rec.get("id") or "").strip()
                if rid:
                    defined_ir_model_ids.add(rid)

            # infer from report/actions where binding_model_id points to ir.model
            for rec in root.findall(".//record"):
                # case A: ir.actions.report has <field name="model">x_xxx</field> and binding_model_id ref="ir_model_####"
                if rec.get("model") == "ir.actions.report":
                    b = self._read_record_field(rec, "binding_model_id").get("ref", "")
                    m = self._read_record_field(rec, "model").get("text", "")
                    if b and re.fullmatch(r"ir_model_\d+", b) and m:
                        needed[b] = m

                # case B: ir.actions.act_window has <field name="res_model">x_xxx</field> and binding_model_id ref="ir_model_####"
                if rec.get("model") == "ir.actions.act_window":
                    b = self._read_record_field(rec, "binding_model_id").get("ref", "")
                    m = self._read_record_field(rec, "res_model").get("text", "")
                    if b and re.fullmatch(r"ir_model_\d+", b) and m:
                        needed[b] = m

        for xmlid_name, model_technical in needed.items():
            if xmlid_name in defined_ir_model_ids:
                continue
            # already exists in DB?
            if IrModelData.search([("module", "=", module_root), ("name", "=", xmlid_name)], limit=1):
                continue
            model_row = IrModel.search([("model", "=", model_technical)], limit=1)
            if model_row:
                self._ensure_xmlid_binding(module_root, xmlid_name, "ir.model", model_row.id)

    # ------------------------------------------------------------
    # Sanitize + strip duplicates in embedded module XML
    # ------------------------------------------------------------
    def _sanitize_customization_zip(self, custom_zip_bytes, *, persist_xmlids=True):
        stripped_models = stripped_fields = 0
        removed_params = 0
        remapped_model_refs = 0

        with zipfile.ZipFile(io.BytesIO(custom_zip_bytes), "r") as src:
            module_root = self._detect_module_root(src)
            IrModel = self.env["ir.model"].sudo()
            IrFields = self.env["ir.model.fields"].sudo()

            # -------------------------
            # PASS 1: model -> xmlid in ZIP
            # -------------------------
            model_to_xmlid_in_zip = {}  # x_it_request -> ir_model_751
            defined_ir_model_xmlids = set()

            for n in src.namelist():
                if not (n.startswith(f"{module_root}/") and n.endswith(".xml") and "/i18n/" not in n):
                    continue
                try:
                    root = self._safe_xml_fromstring(src.read(n))
                except Exception:
                    continue

                for rec in root.findall(".//record[@model='ir.model']"):
                    xmlid = (rec.get("id") or "").strip()
                    model_name = self._read_record_field(rec, "model").get("text", "")
                    if xmlid and model_name:
                        model_to_xmlid_in_zip[model_name] = xmlid
                        defined_ir_model_xmlids.add(xmlid)

            # -------------------------
            # PASS 2: rewrite + strip
            # -------------------------
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as dst:
                for n in src.namelist():
                    data = src.read(n)

                    if not (n.startswith(f"{module_root}/") and n.endswith(".xml") and "/i18n/" not in n):
                        dst.writestr(n, data)
                        continue

                    try:
                        root = self._safe_xml_fromstring(data)
                    except Exception:
                        dst.writestr(n, data)
                        continue

                    changed = False

                    # ---- REWRITE binding_model_id refs (fix ir_model_1128, ir_model_3707, etc.)
                    for rec in root.findall(".//record[@model='ir.actions.report']"):
                        binding = None
                        model_name = self._read_record_field(rec, "model").get("text", "")
                        for f in rec.findall("field"):
                            if f.get("name") == "binding_model_id":
                                binding = f
                                break
                        if binding is not None:
                            refv = (binding.get("ref") or "").strip()
                            # only rewrite the numeric style ones
                            if refv and re.fullmatch(r"ir_model_\d+", refv):
                                target_xmlid = model_to_xmlid_in_zip.get(model_name)
                                if target_xmlid and target_xmlid != refv:
                                    binding.set("ref", target_xmlid)
                                    remapped_model_refs += 1
                                    changed = True

                    for rec in root.findall(".//record[@model='ir.actions.act_window']"):
                        binding = None
                        model_name = self._read_record_field(rec, "res_model").get("text", "")
                        for f in rec.findall("field"):
                            if f.get("name") == "binding_model_id":
                                binding = f
                                break
                        if binding is not None:
                            refv = (binding.get("ref") or "").strip()
                            if refv and re.fullmatch(r"ir_model_\d+", refv):
                                target_xmlid = model_to_xmlid_in_zip.get(model_name)
                                if target_xmlid and target_xmlid != refv:
                                    binding.set("ref", target_xmlid)
                                    remapped_model_refs += 1
                                    changed = True

                    # ---- strip duplicated ir.model (reuse existing DB schema)
                    for rec in list(root.findall(".//record[@model='ir.model']")):
                        xmlid = (rec.get("id") or "").strip()
                        model_name = self._read_record_field(rec, "model").get("text", "")
                        if not xmlid or not model_name:
                            continue
                        existing = IrModel.search([("model", "=", model_name)], limit=1)
                        if existing:
                            if persist_xmlids:
                                self._ensure_xmlid_binding(module_root, xmlid, "ir.model", existing.id)
                            rec.getparent().remove(rec)
                            stripped_models += 1
                            changed = True

                    # ---- strip duplicated ir.model.fields + remove unsupported params
                    for rec in list(root.findall(".//record[@model='ir.model.fields']")):
                        xmlid = (rec.get("id") or "").strip()
                        field_name = self._read_record_field(rec, "name").get("text", "")
                        model_name = self._read_record_field(rec, "model").get("text", "")
                        if not (xmlid and field_name and model_name):
                            continue

                        for f in list(rec.findall("field")):
                            if (f.get("name") or "").strip() in DISALLOWED_DYNAMIC_FIELD_PARAMS:
                                rec.remove(f)
                                removed_params += 1
                                changed = True

                        existing = IrFields.search([("model", "=", model_name), ("name", "=", field_name)], limit=1)
                        if existing:
                            if persist_xmlids:
                                self._ensure_xmlid_binding(module_root, xmlid, "ir.model.fields", existing.id)
                            rec.getparent().remove(rec)
                            stripped_fields += 1
                            changed = True

                    if changed:
                        data = etree.tostring(root, pretty_print=True, encoding="UTF-8", xml_declaration=True)

                    dst.writestr(n, data)

        return out.getvalue(), {
            "module_root": module_root,
            "stripped_models": stripped_models,
            "stripped_fields": stripped_fields,
            "removed_params": removed_params,
            "remapped_model_refs": remapped_model_refs,
        }

    # ------------------------------------------------------------
    # Install embedded module in dedicated cursor (prevents lock timeout)
    # ------------------------------------------------------------
    def _install_customizations_in_new_cursor(
        self,
        customizations_zip_bytes,
        *,
        force_init=True,
        lock_timeout_ms=30000,
        retries=2,
    ):
        """
        Do sanitize+bindings+install in one cursor and COMMIT there, so we don't contend with locks held by current request.
        """
        module_root = "workflow_studio_customization"
        try:
            with zipfile.ZipFile(io.BytesIO(customizations_zip_bytes), "r") as source_zip:
                module_root = self._detect_module_root(source_zip)
        except Exception:
            pass

        last = None
        for attempt in range(retries + 1):
            try:
                with self.env.registry.cursor() as cr:
                    cr.execute("SET LOCAL lock_timeout = %s", (int(lock_timeout_ms),))
                    env2 = api.Environment(cr, self.env.uid, dict(self.env.context or {}))
                    wiz2 = self.with_env(env2)
                    wiz2._acquire_module_import_lock(cr, module_root)
                    sanitized_zip_bytes, sanitize_info = wiz2._sanitize_customization_zip(
                        customizations_zip_bytes,
                        persist_xmlids=True,
                    )

                    module_file = io.BytesIO(sanitized_zip_bytes)
                    module_file.seek(0)
                    env2["ir.module.module"].sudo()._import_zipfile(
                        module_file,
                        force=bool(force_init),
                        with_demo=False,
                    )

                    cr.commit()
                return sanitize_info
            except Exception as e:
                last = e
                _logger.warning("Customization module install attempt %s failed: %s", attempt + 1, e, exc_info=True)
                if attempt < retries:
                    time.sleep(min(2, attempt + 1))
        raise UserError(_("Failed installing embedded customizations module after retries: %s") % last)

    def _dry_run_manifest_import(
        self,
        manifest,
        *,
        customizations_zip=False,
        force_init_customizations=True,
    ):
        with self._isolated_env() as wiz:
            if customizations_zip:
                # Validate customizations structure quickly without DB bindings/module install
                # to keep UI dry-run responsive and avoid lock contention.
                wiz._sanitize_customization_zip(customizations_zip, persist_xmlids=False)

            category = wiz._prepare_target_category(manifest)
            vdata = manifest.get("version") or {}
            vname = wiz._next_version_name(category, vdata.get("name"))
            version = wiz.env["workflow.approval.category.version"].sudo().create(
                {
                    "category_id": category.id,
                    "name": vname,
                    "title": (vdata.get("title") or "").strip(),
                    "sequence": (max(category.version_ids.mapped("sequence") or [0]) + 10) or 10,
                    "is_active": False,
                    "is_locked": False,
                    "is_published": False,
                }
            )
            version.with_context(
                workflow_studio_dry_run=True,
                workflow_studio_skip_customization_import=True,
            ).workflow_studio_import_bundle(wiz.bundle_file)

    # ------------------------------------------------------------
    # Category/version helpers
    # ------------------------------------------------------------
    def _build_category_name(self, manifest):
        return (((manifest.get("category") or {}).get("name") or "").strip() or _("Imported Workflow"))

    def _next_available_category_name(self, base_name):
        Category = self.env["workflow.approval.category"].sudo()
        name = (base_name or "").strip() or _("Imported Workflow")
        if not Category.search_count([("name", "=", name)]):
            return name
        i = 2
        while Category.search_count([("name", "=", f"{name} ({i})")]):
            i += 1
        return f"{name} ({i})"

    def _resolve_model_from_manifest(self, manifest):
        model_name = (manifest.get("res_model_name") or "").strip()
        if not model_name:
            return False, ""
        model = self.env["ir.model"].sudo()._get(model_name)
        return model, model_name

    def _prepare_target_category(self, manifest):
        Category = self.env["workflow.approval.category"].sudo()

        category = Category.browse(self.target_category_id.id).exists() if self.target_category_id else Category.browse()
        category_name = self._build_category_name(manifest)
        model, model_name = self._resolve_model_from_manifest(manifest)

        if not category:
            if self.create_category_if_missing:
                if self.existing_model_mode == "duplicate":
                    vals = {"name": self._next_available_category_name(category_name)}
                    if model:
                        vals["res_model"] = model.id
                    category = Category.create(vals)
                else:
                    category = Category.search([("name", "=", category_name)], limit=1)
                    if not category:
                        vals = {"name": category_name}
                        if model:
                            vals["res_model"] = model.id
                        category = Category.create(vals)
            else:
                category = Category.search([("name", "=", category_name)], limit=1)
                if not category:
                    raise UserError(_("Category '%s' was not found.") % category_name)

        if model_name and not model:
            raise UserError(_("Target model '%s' from package is missing in this database.") % model_name)

        if model and self.existing_model_mode == "error":
            if self.target_category_id and self.target_category_id.res_model.id == model.id:
                pass
            else:
                raise UserError(
                    _(
                        "Model '%s' already exists. Switch 'Existing Model Handling' to 'Sync existing model' to continue."
                    )
                    % model.model
                )

        if model:
            if category.res_model and category.res_model.id != model.id:
                raise UserError(
                    _("Category model mismatch: selected category uses '%(c)s' but package requires '%(r)s'.")
                    % {"c": category.res_model.model, "r": model.model}
                )
            if not category.res_model:
                category.write({"res_model": model.id})

        if not category.res_model:
            raise UserError(_("Cannot import package because target category has no model and package does not provide one."))

        return category

    def _next_version_name(self, category, requested_name):
        base = (requested_name or "").strip() or "New"
        existing = set(category.version_ids.mapped("name"))
        if base not in existing:
            return base
        i = 2
        while f"{base}_{i}" in existing:
            i += 1
        return f"{base}_{i}"

    # ------------------------------------------------------------
    # Onchange
    # ------------------------------------------------------------
    @api.onchange("bundle_file")
    def _onchange_bundle_file(self):
        for w in self:
            w.detected_category_name = False
            w.detected_version_name = False
            w.detected_model_name = False
            w.import_warnings = False
            if not w.bundle_file:
                continue
            try:
                raw = w._decode_bundle_content()
                mf = w._read_bundle_manifest(raw)
                w.detected_category_name = ((mf.get("category") or {}).get("name") or "").strip()
                w.detected_version_name = ((mf.get("version") or {}).get("name") or "").strip()
                w.detected_model_name = (mf.get("res_model_name") or "").strip()
            except Exception as e:
                w.import_warnings = str(e)

    # ------------------------------------------------------------
    # Dry-run isolated env
    # ------------------------------------------------------------
    @contextlib.contextmanager
    def _isolated_env(self):
        self.ensure_one()
        ctx = dict(self.env.context or {})
        ctx.update({"workflow_studio_dry_run": True, "tracking_disable": True, "mail_create_nosubscribe": True})
        with self.env.registry.cursor() as cr:
            env2 = api.Environment(cr, self.env.uid, ctx)
            target_category = (
                env2["workflow.approval.category"].sudo().browse(self.target_category_id.id).exists()
                if self.target_category_id
                else env2["workflow.approval.category"]
            )
            clone_vals = {
                "bundle_file": self.bundle_file,
                "bundle_filename": self.bundle_filename,
                "target_category_id": target_category.id or False,
                "existing_model_mode": self.existing_model_mode,
                "create_category_if_missing": self.create_category_if_missing,
                "deploy_after_import": self.deploy_after_import,
                "run_dry_run_before_import": self.run_dry_run_before_import,
                "force_init_customizations": self.force_init_customizations,
            }
            wiz2 = env2[self._name].sudo().create(clone_vals)
            try:
                yield wiz2
            finally:
                try:
                    cr.rollback()
                except Exception:
                    pass

    # ------------------------------------------------------------
    # UI actions
    # ------------------------------------------------------------
    def action_validate_bundle(self):
        self.ensure_one()
        self._ensure_workflow_studio_admin()

        raw = self._decode_bundle_content()
        manifest = self._read_bundle_manifest(raw)

        notes = []
        # Validate embedded module structure (sanitize only, no install)
        custom_zip = self._extract_customizations_zip(raw)
        if custom_zip:
            _sanitized_zip, info = self._sanitize_customization_zip(custom_zip, persist_xmlids=False)
            notes.append(_("Embedded module detected (%s).") % info["module_root"])
            if info["stripped_models"] or info["stripped_fields"]:
                notes.append(_("Will reuse existing schema: %s model(s), %s field(s).") % (info["stripped_models"], info["stripped_fields"]))
            if info["removed_params"]:
                notes.append(_("Will drop %s unsupported field params (tracking/auto_join).") % info["removed_params"])

        self._dry_run_manifest_import(
            manifest,
            customizations_zip=custom_zip or False,
            force_init_customizations=self.force_init_customizations,
        )

        msg = _("Package structure and dry-run import are valid.")
        if notes:
            msg = msg + " " + " ".join(notes)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("Workflow ZIP Validation"), "message": msg, "type": "success", "sticky": False},
        }

    def action_import_bundle(self):
        self.ensure_one()
        self._ensure_workflow_studio_admin()

        raw = self._decode_bundle_content()
        manifest = self._read_bundle_manifest(raw)

        warnings = []
        custom_zip = self._extract_customizations_zip(raw)

        if self.run_dry_run_before_import:
            self._dry_run_manifest_import(
                manifest,
                customizations_zip=custom_zip or False,
                force_init_customizations=self.force_init_customizations,
            )
            warnings.append(_("Pre-import dry-run validation passed."))

        # 1) Install embedded customizations module (if any) in dedicated cursor (prevents lock timeout)
        if custom_zip:
            try:
                info = self._install_customizations_in_new_cursor(
                    custom_zip,
                    force_init=self.force_init_customizations,
                )
                warnings.append(_("Installed embedded customizations module '%s'.") % info["module_root"])
            except UserError as install_error:
                raise UserError(
                    _(
                        "Import aborted to avoid configuration loss because embedded customizations "
                        "could not be installed. Resolve the issue and retry. Details: %s"
                    )
                    % (str(install_error or ""))
                ) from install_error

        # 2) Import workflow bundle into category/version
        category = self._prepare_target_category(manifest)
        vdata = manifest.get("version") or {}
        vname = self._next_version_name(category, vdata.get("name"))
        version = self.env["workflow.approval.category.version"].sudo().create({
            "category_id": category.id,
            "name": vname,
            "title": (vdata.get("title") or "").strip(),
            "sequence": (max(category.version_ids.mapped("sequence") or [0]) + 10) or 10,
            "is_active": False,
            "is_locked": False,
            "is_published": False,
        })

        import_result = version.with_context(workflow_studio_skip_customization_import=True).workflow_studio_import_bundle(self.bundle_file)
        warnings += import_result.get("warnings") or []

        deployed = False
        if self.deploy_after_import:
            version.workflow_studio_deploy_version()
            deployed = True

        self.import_warnings = "\n".join([w for w in warnings if w]) if warnings else False

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Workflow ZIP Imported"),
                "message": _("Imported into '%(cat)s' as version '%(ver)s' (%(state)s).")
                           % {"cat": category.display_name, "ver": version.display_name, "state": _("deployed") if deployed else _("draft")},
                "type": "warning" if warnings else "success",
                "sticky": bool(warnings),
                "next": {
                    "type": "ir.actions.act_window",
                    "name": _("Approval Category"),
                    "res_model": "workflow.approval.category",
                    "res_id": category.id,
                    "views": [[False, "form"]],
                    "view_mode": "form",
                    "target": "current",
                },
            },
        }
