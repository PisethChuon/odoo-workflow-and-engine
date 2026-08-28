# Meal Allowance & Laundry Module

## Purpose
This module manages Meal Allowance and Laundry expense requests using the `workflow_engine` approval flow.

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

## Menu Management

### Administrator-Only Configuration Menus
These configuration submenus are maintained under the Odoo administrator configuration area:
- **Employee Titles** (`menu_x_meal_allowance_title`)
- **Employee Levels** (`menu_x_meal_allowance_level`)
- **Apparel Types** (`menu_x_meal_allowance_apparel_type`)
- **Staff Groups** (`menu_x_meal_allowance_staff_group`)

These menus are intentionally visible only to Odoo administrators (`base.group_system`) so Level, Entitlement, and Apparel values can be maintained from the UI without code deployment.
