# -*- coding: utf-8 -*-

from pathlib import Path

from odoo.tests import common


class TestBpmnDialogMobileUi(common.TransactionCase):
    def test_preview_flow_uses_mobile_bottom_sheet_without_runtime_changes(self):
        module_root = Path(__file__).resolve().parents[1]
        style_source = (
            module_root
            / "static"
            / "src"
            / "web"
            / "bpmn_button"
            / "bpmn_dialog.scss"
        ).read_text(encoding="utf-8")
        template_source = (
            module_root
            / "static"
            / "src"
            / "web"
            / "bpmn_button"
            / "bpmn_dialog.xml"
        ).read_text(encoding="utf-8")
        component_source = (
            module_root
            / "static"
            / "src"
            / "web"
            / "bpmn_button"
            / "bpmn_dialog.js"
        ).read_text(encoding="utf-8")

        self.assertIn("@media (max-width: 767px)", style_source)
        self.assertIn(
            ".modal.o_modal_full:has(> .modal-dialog > .ngflow-modal)",
            style_source,
        )
        self.assertIn("height: 82dvh;", style_source)
        self.assertIn("@keyframes ngflowSheetUp", style_source)
        self.assertIn(
            "animation: 420ms ngflowSheetUp "
            "cubic-bezier(0.22, 1, 0.36, 1) forwards;",
            style_source,
        )
        self.assertIn("transform: translate3d(0, 100%, 0);", style_source)
        self.assertIn("backface-visibility: hidden;", style_source)
        self.assertIn("contain: content;", style_source)
        self.assertIn("border-radius: 20px 20px 0 0;", style_source)
        self.assertIn("min-height: 58px;", style_source)
        self.assertIn("padding: 14px 10px 8px 16px;", style_source)
        self.assertIn("position: static;", style_source)
        self.assertIn("flex: 0 0 36px;", style_source)
        self.assertIn("env(safe-area-inset-bottom)", style_source)
        self.assertIn(
            ".ngflow-modal .ngflow-footer > .btn.btn-primary",
            style_source,
        )
        self.assertIn("width: 100% !important;", style_source)
        self.assertIn("state.isSheetReady", template_source)
        self.assertIn("ngflow-modal--ready", template_source)
        self.assertIn("onMounted", component_source)
        self.assertIn("isSheetReady: false", component_source)
        self.assertIn("isDiagramReady: !isMobileSheet", component_source)
        self.assertIn("MOBILE_DIAGRAM_MOUNT_DELAY_MS", component_source)
        self.assertGreaterEqual(component_source.count("browser.requestAnimationFrame"), 2)
        self.assertIn(
            '<BpmnWidget t-if="state.isDiagramReady" '
            't-props="{ data: props.data }"/>',
            template_source,
        )
        self.assertIn("ngflow-canvas-loading", template_source)
