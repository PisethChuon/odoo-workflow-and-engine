# Emergency Incident Module

This module provides a request workflow for logging, tracking, and reporting emergency incidents. 
It integrates dynamic configuration options, native employee lookup, and custom PDF report generation.

---

## Architecture & Module Structure

```text
emergency_incident/
├── __manifest__.py
├── models/
│   └── schema/
│       ├── emergency_incident_information_type.xml
│       ├── emergency_incident_property.xml
│       ├── emergency_incident_shift.xml
│       ├── emergency_incident_location.xml
│       ├── emergency_incident_call.xml
│       ├── emergency_incident_color_code.xml
│       └── emergency_incident_information.xml   # Main Model
├── data/
│   └── emergency_incident_type_data.xml         # Master Seed Data
├── automation/
│   └── emergency_incident_automation.xml        # Base Automation Rules
├── security/
│   └── ir.model.access.csv
├── views/
│   ├── emergency_incident_property_view.xml
│   ├── emergency_incident_shift_view.xml
│   ├── emergency_incident_location_view.xml
│   ├── emergency_incident_call_view.xml
│   ├── emergency_incident_information_type_view.xml
│   ├── emergency_incident_color_code_view.xml
│   └── emergency_incident_information_view.xml   # UX Form View
├── actions/
│   └── act_window.xml
├── menus/
│   └── emergency_incident_menu.xml
├── reports/
│   ├── emergency_incident_report.xml
│   └── emergency_incident_report_template.xml    # QWeb PDF Template
└── workflows/
    └── emergency_incident_workflow.xml
```

## Core Features
### Dynamic Admin Configurations
- Incident Types, Properties, Shifts, Locations, Calls of Incident, and Color Codes are managed via dynamic relational models (```many2one```).
- System Admins can add or archive entries directly through the UI via the Emergency Incidents configuration menu without modifying code.

### Auto-Populating Responder & Patient Details
- Linked directly to native Employee records (```hr.employee```).
- Standardized auto-lookup fields (```x_responder_id``` and ```x_patient_id```) automatically pull:
  - Position (```job_title```)
  - Department (```department_id.name```)
  - Phone Contact (```work_phone```)
### Isolated Field Naming
Uses clear, distinct field names for reusability across entity contexts (e.g., ```x_incident_remark``` vs. ```x_patient_remark```).

### Base Automations
UI Server Actions automatically clear out dependent fields (such as ```x_color_code_id```) when parent fields (```x_type_of_incidents_id```) change.

### CLI Upgrade Command
To apply code updates and reload dependencies:

```python odoo-bin -c debian/odoo.conf -d <your_database_name> -u emergency_incident```