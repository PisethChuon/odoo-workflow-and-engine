## Honestly Award

Project type: Workflow Module
Tech stack: Odoo 19.0, Python, PostgreSQL

![Module Icon](static/description/icon.png)

## Project overview

This module manages Honestly Award requests. It collects founder details and stores award data for review and approval.

## Features

- Create Honestly Award requests
- Track request status
- Store founder details

## Folder structure

- `models/schema/`: `ir.model` and `ir.model.fields` definitions
- `actions/`: window actions
- `views/`: list/form view definitions
- `menus/`: menu items
- `workflows/`: workflow category and BPMN version
- `reports/`: report action and QWeb template
- `security/`: access control rules
- `tests/`: Odoo integration and standalone logic tests

## Requirements

- Odoo 19.0
- Python 3.x
- PostgreSQL

## Installation steps

1. Copy this module to your Odoo addons path.
2. Update the apps list in Odoo.
3. Install the module from the Apps menu.
4. Verify `wkhtmltopdf` is installed (for PDF reports)

## Configuration

No extra configuration is required.

## How to use

1. Open the module in Odoo.
2. Create a new Honestly Award request.
3. Fill in founder details.
4. Submit and follow the request status.

## Run unit tests

Run this command:

```bash
python -m pytest modules/workflow/admin_forms/honestly_award/tests/test_honestly_award_logic.py -v
```
