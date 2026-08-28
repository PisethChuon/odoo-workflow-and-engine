# Car Park Permit Module

## Purpose
This module manages Car Park Permit requests using the `workflow_engine` approval flow.

## Folder Structure
- `models/schema/`: `ir.model` and `ir.model.fields` definitions
- `security/`: access control (`ir.model.access.csv`)
- `actions/`: window actions
- `menus/`: menu items
- `views/`: form/list view definitions
- `automation/`: base automation rules and server actions
- `workflows/`: workflow category and BPMN version
- `reports/`: report action and QWeb template
- `data/demo/`: demo records
- `tests/`: Odoo integration tests and pure logic tests

## Conventions
- Keep one source of truth for model access rules in `security/ir.model.access.csv`.
- Group XML files by concern to simplify maintenance and reviews.
- Use clear, domain-based filenames to make intent obvious for new developers.
