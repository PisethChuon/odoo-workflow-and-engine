# Home Leave Ticket Form
Project type: Workflow Module
Tech stack: Odoo 19.0, Python, PostgreSQL

![Module Icon](static/description/icon.png)
## Project overview
This module manages home leave ticket forms. It collects leave details and stores data for review and approval

## Features
- Create home leave ticket forms
- Track leave request status
- Store leave request details and history

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
2. Create a new home leave ticket form.
3. Fill in leave details.
4. Submit and follow the request status.

## Run unit tests
Run this command:

## Folder structure
- models/schema/: model and field schema definitions (ir.model, ir.model.fields)
- models/: Python business logic
- security/: access control rules
- actions/: window actions
- views/: list and form views
- menus/: menu hierarchy
- workflows/: approval workflow category/version
- reports/: report templates and report actions
- data/: default and master setup data
- tests/: test files