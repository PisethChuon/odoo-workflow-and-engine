## Item Repair
Project type: Workflow Module

Tech stack: Odoo 19.0, Python, PostgreSQL

![Module Icon](static/description/icon.png)

## Project overview

This module manages item repair requests. It collects item details and stores repair data for review and approval.

## Features

- Create item repair requests
- Track request status
- Store item details and repair history

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
2. Create a new item repair request.
3. Fill in item details.
4. Submit and follow the request status.

## Run unit tests

Run this command:

```cd item_repair && python3 tests/test_item_repair_request_standalone.py -v```

## Folder structure

- models/ : business logic
- views/ : UI views
- security/ : access rules
- data/ : demo or setup data
- tests/ : test files