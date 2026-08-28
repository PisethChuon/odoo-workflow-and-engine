# -*- coding: utf-8 -*-

import csv
from pathlib import Path

from odoo.tests import common

from odoo.addons.workflow_engine.utils.bpmn_engine_parser import BpmnEngine


class TestFlowBundleBpmn(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.flow_root = Path(__file__).resolve().parents[1] / "demo" / "flow"
        cls.all_flows_dir = cls.flow_root / "all_flows_bpmn"
        cls.index_path = cls.flow_root / "ALL_FLOWS_BPMN_INDEX.csv"

    def _iter_all_flow_bpmn_files(self):
        return sorted(self.all_flows_dir.glob("*.bpmn"))

    def test_all_flow_bpmn_files_parse_into_engine_metadata(self):
        bpmn_files = self._iter_all_flow_bpmn_files()
        self.assertTrue(
            bpmn_files,
            "Expected generated BPMN files under demo/flow/all_flows_bpmn.",
        )

        for bpmn_file in bpmn_files:
            xml = bpmn_file.read_text(encoding="utf-8")
            parser = BpmnEngine(xml)
            meta_tasks, meta_actions = parser.get_meta_tasks_and_actions()

            self.assertTrue(
                meta_tasks,
                "BPMN file %s should produce metadata tasks." % bpmn_file.name,
            )
            self.assertTrue(
                meta_actions,
                "BPMN file %s should produce metadata actions." % bpmn_file.name,
            )

    def test_flow_index_matches_all_flow_bpmn_files(self):
        self.assertTrue(self.index_path.exists(), "Flow index CSV must exist.")

        indexed_paths = set()
        with self.index_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                rel_path = (row.get("bpmn_file") or "").strip()
                self.assertTrue(rel_path, "Each index row must define bpmn_file.")

                bpmn_path = (self.flow_root / rel_path).resolve()
                self.assertTrue(
                    bpmn_path.exists(),
                    "Indexed BPMN file does not exist: %s" % rel_path,
                )
                indexed_paths.add(bpmn_path)

        actual_paths = {path.resolve() for path in self._iter_all_flow_bpmn_files()}
        self.assertEqual(
            indexed_paths,
            actual_paths,
            "Flow index CSV should map exactly to all generated BPMN files.",
        )
