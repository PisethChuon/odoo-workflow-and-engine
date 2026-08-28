# Workflow Flow Configuration Guide (BCJ + Exit Clearance)

This guide explains how to configure the two full flows in Workflow Studio with business logic that should be followed.

For full per-condition configuration (all gateway domains, action routing, group/user domain conditions, and runtime values), use:
- `WORKFLOW_STUDIO_FULL_CONDITION_CONFIGURATION.md`

## 1. BPMN Files To Import

- BCJ (aligned): `engine/workflow_engine/demo/bcj_flow_full_aligned.bpmn`
- Exit Clearance (aligned): `engine/workflow_engine/demo/exit_clearance_demo_full_flow_aligned.bpmn`

Use aligned files for readability. They include BPMNDI coordinates, so the diagram opens in a clean layout.

## 2. Quick Start Sequence (Recommended)

1. Open category/version in Workflow Studio.
2. Import aligned BPMN.
3. Click `Sync` once.
4. Configure task-level metadata.
5. Configure action/transition behavior.
6. Configure approval groups by stage.
7. Save and deploy.
8. Run scenario tests (approve/rework/reject paths).

## 3. Approval Configuration Strategy

Short answer: configure approval on each **human decision stage** only.

Configure approval groups on:
- `userTask` stages where a person must approve/review/reject/rework.

Do not configure approval groups on:
- `startEvent`
- `endEvent`
- `intermediateCatchEvent` / `intermediateThrowEvent`
- `exclusiveGateway` / `parallelGateway` / `inclusiveGateway`
- `sendTask` / `scriptTask` (unless your business explicitly requires manual approval before them)

## 4. BCJ Stage Configuration (Business Logic)

### 4.1 Human approval stages (must configure)

- `Task_HODApproval`
- `Task_LineDepartment`
- `Task_DepartmentExecutive`
- Finance stage tasks:
  - `Task_FinanceGaming`
  - `Task_FinanceHotel`
  - `Task_GroupFinance`
  - `Task_CFO_DYCFO`
  - `Task_CFO`
- `Task_Purchasing` (Done action owner)
- `Task_Modification` (only if modification window enabled)

### 4.2 Finance routing rules (must match source logic)

From `Gateway_FinanceRoute`:
- `total_amount <= 500` and branch=`gaming` -> `Task_FinanceGaming`
- `total_amount <= 500` and branch=`hotel` -> `Task_FinanceHotel`
- `total_amount <= 500` and branch=`others` -> `Task_GroupFinance`
- `500 < total_amount <= 100000` -> `Task_CFO_DYCFO`
- `total_amount > 100000` -> `Task_CFO`

### 4.3 Rework loops (must keep)

- HOD rework -> back to `Task_Submitter`
- Line Dept rework -> back to `Task_HODApproval`
- Dept Exec rework -> back to `Task_LineDepartment`
- Finance rework -> back to `Task_DepartmentExecutive`

### 4.4 Notification and completion

- After finance approved join -> send submitter notification (`Task_EmailNotification`)
- Then purchasing done -> modification window decision
- Modification allowed: `Task_Modification` -> complete
- Otherwise complete directly

## 5. Exit Clearance Stage Configuration (Business Logic)

### 5.1 Human approval stages (must configure)

- `Task_Submission` (request owner)
- `Task_HODDecision`
- Parallel department tasks:
  - `Task_ITClearance`
  - `Task_FinanceClearance`
  - `Task_AdminClearance`
  - `Task_SecurityClearance`
  - `Task_FacilityClearance`
  - `Task_PurchaseClearance`
  - `Task_OperationsClearance`
  - `Task_HRDeptClearance`
- `Task_HODFinalReview`
- `Task_PayrollReview`
- `Task_HRFinalClearance`

### 5.2 Parallel branch rules

- Split at `Gateway_DeptSplit`
- Join at `Gateway_DeptJoin`
- Join policy should be `all_of` (all department branches complete)
- Reject from IT/Finance branch should route to rework as designed

### 5.3 Automation section

- `Gateway_OffboardRoute` routes to:
  - `Task_DisableAccounts` (script/server behavior)
  - `Task_NotifyChannels` (notification behavior)
- Both join at `Gateway_OffboardJoin` before HR final clearance

## 6. Task-Level Settings Template (Per Human Stage)

For each human decision stage, configure:
- Assignment mode (`groups` / `request_owner` as needed)
- Completion mode (`any` or `all`)
- Fallback policy (`route_admin_queue` recommended)
- Approval groups + sequence
- User/group domain filters
- Button actions: approve, rework, reject (label + behavior + optional reason/comment required)

## 7. Transition Design Rules

- `Approve` must go forward only.
- `Rework` must go to previous correction stage.
- `Reject` should go to final rejected end (or explicit reject branch).
- Keep each action key unique and explicit for auditability.

## 8. Validation Checklist Before Deploy

1. Approve path reaches final completed end.
2. Every rework path returns to intended previous stage.
3. Every reject path reaches rejected end.
4. Finance gateway conditions are mutually exclusive and complete.
5. No stage is left without assignees (groups/users/domains).
6. Notification and server actions execute at intended nodes.

## 9. Common Issue: “Approve looks like Rework”

If diagram visually looks wrong:
- Check sequence flow source/target IDs (logic is authoritative).
- Re-import aligned BPMN file.
- Use `Fit` only for zoom; `Fit` does not re-layout logic.
- `Sync` updates metadata from BPMN; it does not auto-arrange diagram paths.
