# Additional Time Work
Project type: Workflow Module

Tech stack: Odoo 19.0, Python, PostgreSQL

![Module Icon](static/description/icon.png)

## Project overview
This module manages Additional Time Work requests with a workflow-based approval lifecycle.
It captures additional working time details (for example Regular Day, Off Day, and Public Holiday entries), routes requests through approval and HR review, and supports report export.

## Features
- Create and submit additional time work requests
- Add multiple detail lines per request (employee, date, category, hours)
- Workflow approval process with rework, reject, and cancel paths
- HR review and closure step
- Request tracking through approval state transitions
- PDF report action for request output

## Requirements
- Odoo 19.0
- Python 3.x
- PostgreSQL
- `wkhtmltopdf` (for PDF reports)

## Installation steps
1. Copy this module to your Odoo addons path.
2. Update the apps list in Odoo.
3. Install the module from the Apps menu.
4. Ensure dependencies are installed: `workflow_engine` and `hr`.

## Configuration
No extra technical configuration is required after installation.

Business users should verify that:
- The approval category is available as **Additional Time Work Form**.
- Workflow version **V1** is active.
- Users have proper access rights for requesting and approving records.

## How to use
1. Open **Workflow** and navigate to **Additional Time Work**.
2. Create a new request.
3. Add line items with employee, date, category, and hour values.
4. Submit the request for approval.
5. Approver performs **Approve**, **Reject**, or **Rework**.
6. HR performs final review and closes the request.

For detailed user steps and screenshots, see:
- `docs/USERGUIDE.md`
- `docs/USER ACCEPTANCE.md`

## Workflow summary
Main process stages:
- Submission
- HOD Approval
- HR Review

Main outcomes:
- Reviewed (closed)
- Rework (resubmission loop)
- Rejected
- Cancelled

## Testing
Current tests are placeholders:
- `tests/test_additional_time_work_logic.py`
- `tests/test_additional_time_work_integration.py`

Add module-specific assertions before relying on automated test coverage.

## Folder structure
- `models/schema/` : `ir.model` and `ir.model.fields` definitions
- `security/` : access rules (`ir.model.access.csv`)
- `actions/` : window and category actions
- `automation/` : automation rules and server actions
- `views/` : list and form view definitions
- `menus/` : module menu items
- `workflows/` : workflow category and BPMN version
- `reports/` : report action and QWeb template
- `data/` : seed/demo support data
- `tests/` : test files
- `docs/` : user guide and user acceptance notes
