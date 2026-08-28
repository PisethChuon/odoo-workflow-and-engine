# Approval User Configuration Guide (BCJ + Exit Clearance)

This guide is for configuring approval users/groups after BPMN import and Sync.

## 1. BCJ Approval Model

BCJ uses mixed assignment sources:
- Stage-specific fixed groups (mainly Finance and Purchasing)
- Dynamic HOD lookup by submitter department
- Dynamic Line Department / Department Executive lookup by BCJ list type

### 1.1 BCJ Stage Intent (from source workflow sheet)

- **Level 1 (Requestor)**: Log in and submit 
01) Requestor information
02) Input BCJ information   
03) Add Capital Requirement
04) Add Financial Analysis
05) Add attache file if any
- **Level 2 (HOD Approval)**: 01) Rout to Submitter's HOD for approval
02) Add attach file, Comment (optional)
03) Action (Approved, Reworked, Rejected)
04) If Reworked rout to Submitter
- **Level 3 (Line of Department)**: 01) Rout to Line of Department
02) Add attach file, Comment (optional)
03) Action (Reviewed, Reworked, Rejected)
04) If Reworked rout to Submitter's HOD
- **Level 4 (Department Executive)**: 01) Rout to Department Executive
02) Add attach file, Comment (optional)
03) Action (Reviewed, Reworked, Rejected)
04) If Reworked rout to Line of Department
- **Level 5 (Finance Approval)**: 01) A. If Total amount <=500, Rout to Finance Group:
           - if Branch of Co Name=Gaming, rout to Finance-Gaming
            - if Branch of Co Name=None Gaming, rout to Finance-Hotel
           - if Branch of Co Name=Others, rout to Group Finance
      B. If Total amount >500 and <=100K, Rout to CFO/DYCFO
     C. If Total amount >100K, Rout to CFO
02) Add attach file, Comment (optional)
03) Action (Reviewed, Reworked, Rejected)
04) If Reworked rout to Department Executive
- **Level 6 (Email Notification)**: 01) Send an email notification to Submitter for completed approved form
- **Level 7 (Purchasing)**: 01) Rout to Purchasing
02) Add PO number, PO date and Value
03) Action (Done)
- **Modification**: 01) Modification group users can update comment and attached file.
02) The Purchasing user can add/update PO number, PO date and Value of BCJ form done by them only.
03) Modify period is 1 month from last action taken by purchasing in level7.
03) No email notification send to Submitter

### 1.2 Fixed BCJ approval groups found in source

- `CFO`: 3 user(s)
- `CFO/DYCFO`: 3 user(s)
- `Finance - Gaming`: 2 user(s)
- `Finance - Hotel`: 2 user(s)
- `Group Finance`: 2 user(s)
- `Modification`: 3 user(s)
- `Purchasing`: 12 user(s)

### 1.3 Dynamic mappings to import into your approval groups

- `bcj_hod_mapping.csv`: HOD by department mapping.
- `bcj_line_dept_exec_mapping.csv`: list type -> line dept + dept executive mapping.
- `bcj_group_users.csv`: fixed group membership user list (emp no/name/email).

## 2. Exit Clearance Approval Model

Exit Clearance should configure approval groups per human stage:
- HOD Decision
- IT / Finance / Admin / Security / Facility / Purchase / Operations / HR Dept
- HOD Final Review
- Payroll Review
- HR Final Clearance

Do not configure approval groups on gateways/events/automation tasks.

### 2.1 Demo Users for quick UAT

All demo users use password: `12345`

- Requestor: `demo.exit.requestor@nagaworld.com`
- HOD: `demo.exit.hod@nagaworld.com`
- IT: `demo.exit.it@nagaworld.com`
- Finance: `demo.exit.finance@nagaworld.com`
- Admin: `demo.exit.admin@nagaworld.com`
- Security: `demo.exit.security@nagaworld.com`
- Facility: `demo.exit.facility@nagaworld.com`
- Purchase: `demo.exit.purchase@nagaworld.com`
- Operations: `demo.exit.operations@nagaworld.com`
- HR: `demo.exit.hr@nagaworld.com`
- Payroll: `demo.exit.payroll@nagaworld.com`

The module file `demo/exit_clearance_demo_data.xml` wires these users to the matching approval groups.

### 2.2 Full Demo Setup (Ready for manual testing)

Use a fresh DB install (do not use `-u` only):

```bash
python odoo-core-19/odoo-bin -c config/naga-odoo-19.conf -d <your_demo_db> -i workflow_engine,workflow_studio --without-demo=False --stop-after-init
```

Demo category:
- Name: `Demo - Exit Clearance Enterprise`
- Type (`res_model`): `workflow.base.approval.request`
- Active version: `v1` / `Exit Clearance - Enterprise Parallel Flow`
- BPMN in demo data includes `BPMNDI` coordinates for full diagram rendering.

Stage to approval group mapping:

| Activity (node) | Group |
|---|---|
| Task_Submission | Request Owner |
| Task_HODDecision | Exit Clearance - HOD |
| Task_ITClearance | Exit Clearance - IT |
| Task_FinanceClearance | Exit Clearance - Finance |
| Task_AdminClearance | Exit Clearance - Admin |
| Task_SecurityClearance | Exit Clearance - Security |
| Task_FacilityClearance | Exit Clearance - Facility |
| Task_PurchaseClearance | Exit Clearance - Purchase |
| Task_OperationsClearance | Exit Clearance - Operations |
| Task_HRDeptClearance | Exit Clearance - HR |
| Task_HODFinalReview | Exit Clearance - HOD |
| Task_PayrollReview | Exit Clearance - Payroll |
| Task_HRFinalClearance | Exit Clearance - HR |

Submission action window:
- `Task_Submission` is preconfigured with action window `Exit Clearance - New Request`.
- This action opens the create form on model `workflow.base.approval.request`.

Main manual test path (happy path):

1. Login `demo.exit.requestor@nagaworld.com` and create request in category `Demo - Exit Clearance Enterprise`.
2. On `Task_Submission`, click `Submit Exit Clearance`.
3. Login `demo.exit.hod@nagaworld.com`, on `Task_HODDecision` click `Approve and Send to Departments`.
4. In parallel department stage, approve `Task_ITClearance` using `demo.exit.it@nagaworld.com`.
5. Approve `Task_FinanceClearance` using `demo.exit.finance@nagaworld.com`.
6. Approve `Task_AdminClearance` using `demo.exit.admin@nagaworld.com`.
7. Approve `Task_SecurityClearance` using `demo.exit.security@nagaworld.com`.
8. Approve `Task_FacilityClearance` using `demo.exit.facility@nagaworld.com`.
9. Approve `Task_PurchaseClearance` using `demo.exit.purchase@nagaworld.com`.
10. Approve `Task_OperationsClearance` using `demo.exit.operations@nagaworld.com`.
11. Approve `Task_HRDeptClearance` using `demo.exit.hr@nagaworld.com`.
12. After all parallel approvals complete, login HOD and approve `Task_HODFinalReview`.
13. Login `demo.exit.payroll@nagaworld.com` and approve `Task_PayrollReview` (configured with 2FA email OTP condition).
14. System executes automation tasks (`Task_DisableAccounts`, `Task_NotifyChannels`), then routes to HR final.
15. Login `demo.exit.hr@nagaworld.com` and click `Complete Exit Clearance` on `Task_HRFinalClearance`.
16. Verify request state becomes `completed`.

Rework/reject path checks:

1. At HOD stage, click `Reject to Requestor Rework`.
2. Login requestor and click `Resubmit for HOD Decision`.
3. At IT stage, click `Reject IT` and verify route returns to requestor rework.
4. At Finance stage, click `Reject Finance` and verify route returns to requestor rework.

## 3. Required Validation

1. Every human stage has at least one approver candidate.
2. Rework routes to the expected previous stage.
3. Reject routes to final rejected path.
4. Finance route conditions do not overlap.
5. Purchasing and modification permissions match business policy.
