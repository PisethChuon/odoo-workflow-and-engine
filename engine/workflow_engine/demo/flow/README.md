# Flow Package

This folder contains aligned BPMN files and configuration guides for Workflow Studio migration and testing.

## Files

- `bcj_full_aligned.bpmn`
- `exit_clearance_full_aligned.bpmn`
- `FLOW_CONFIGURATION_GUIDE.md`
- `APPROVAL_USER_CONFIGURATION_GUIDE.md`
- `WORKFLOW_STUDIO_FULL_CONDITION_CONFIGURATION.md`
- `ALL_FLOWS_FROM_ZIP_CATALOG.md`
- `ALL_FLOWS_BPMN_INDEX.csv`
- `ALL_FLOWS_MASTER_CONFIGURATION_GUIDE.md`
- `all_flows_bpmn/` (71 import-ready BPMN files from catalog)
- `bcj_group_users.csv`
- `bcj_hod_mapping.csv`
- `bcj_line_dept_exec_mapping.csv`

## Import Order

1. Pick target flow from `ALL_FLOWS_BPMN_INDEX.csv`.
2. Import BPMN file to a draft version.
3. Click Sync.
4. Apply approval assignment from guides/CSV mapping.
5. Configure all action/gateway/group conditions from `WORKFLOW_STUDIO_FULL_CONDITION_CONFIGURATION.md` and `ALL_FLOWS_MASTER_CONFIGURATION_GUIDE.md`.
6. Validate approve/rework/reject scenarios.
7. Deploy after UAT.
