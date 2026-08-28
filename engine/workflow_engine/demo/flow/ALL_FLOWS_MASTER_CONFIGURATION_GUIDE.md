# All Flows Master Configuration Guide (71 Available Flows)

This package contains import-ready BPMN files for all flows currently discoverable from the uploaded source catalog.

## Scope

- Source inventory in this workspace currently yields **71** normalized flow entries.
- All BPMN files are placed under `all_flows_bpmn/` and indexed in `ALL_FLOWS_BPMN_INDEX.csv`.
- `FULL_REFERENCE_BCJ` and `FULL_REFERENCE_EXIT` files reuse validated aligned full-flow BPMN logic.
- `DEMO_TEMPLATE` files are clean import templates with standard approval/rework/reject + one conditional route.

## Files

1. `ALL_FLOWS_BPMN_INDEX.csv`
2. `all_flows_bpmn/*.bpmn`
3. `WORKFLOW_STUDIO_FULL_CONDITION_CONFIGURATION.md` (detailed BCJ + Exit condition guide)

## Runtime Assignment + Approval Group Rule (Must Follow)

1. For actionable human stages, configure **User Groups** on every userTask stage.
2. Keep `Runtime Assignment` aligned with the same intent; do not rely on runtime domain alone for button actionability.
3. If `assignment_mode=domain`, also keep at least one group link and use group `user_domain` for matching users.
4. Set `fallback_policy=route_admin_queue` at stage level and define category admin queue user.
5. Validate pending approver rows exist after each transition; otherwise stage will be blocked.

## Studio Configuration Baseline (All Flows)

For each imported flow, configure per human approval stage:

1. Runtime tab
   - `assignment_mode`: `groups` (recommended baseline)
   - `completion_mode`: `any` (or `all` for strict parallel approvals)
   - `fallback_policy`: `route_admin_queue`
2. User Groups tab
   - add `approval_group_id` link rows
   - add request filter `domain` if stage is conditional by request data
   - add assignee filter `user_domain` if stage needs dynamic user selection
3. Actions tab
   - configure action keys: `submit`, `approve/review`, `rework`, `reject`
   - configure `dialog_type`, `require_reason`, `comment_required`, and optional 2FA
4. Gateway conditions
   - set sequence action `Domain` values for each branch

## Standard Condition Patterns

Use these domain patterns in Studio condition fields:

1. Boolean flag: `[('allow_modification', '=', True)]`
2. Amount band: `[('total_amount', '>', 500), ('total_amount', '<=', 100000)]`
3. Branch value: `[('branch_company', '=', 'gaming')]`
4. Employee type: `[('request_owner_emp_type', '=', 'employee')]`
5. Active internal user filter: `[('share', '=', False), ('active', '=', True)]`

## Per-Flow Index

| # | Category | Flow Name | BPMN File | Type |
|---|---|---|---|---|
| 1 | EGM | EGM-Attendance Form | `all_flows_bpmn/egm__egm_attendance_form.bpmn` | DEMO_TEMPLATE |
| 2 | EGM | EGM-Incident Form | `all_flows_bpmn/egm__egm_incident_form.bpmn` | DEMO_TEMPLATE |
| 3 | EGM | EGM-PM | `all_flows_bpmn/egm__egm_pm.bpmn` | DEMO_TEMPLATE |
| 4 | EGM | EGM-PM Form | `all_flows_bpmn/egm__egm_pm_form.bpmn` | DEMO_TEMPLATE |
| 5 | EGM | GMU RAM CLEAR FORM | `all_flows_bpmn/egm__gmu_ram_clear_form.bpmn` | DEMO_TEMPLATE |
| 6 | EGM | Machine Form | `all_flows_bpmn/egm__machine_form.bpmn` | DEMO_TEMPLATE |
| 7 | EGM | RAM CLEAR FORM | `all_flows_bpmn/egm__ram_clear_form.bpmn` | DEMO_TEMPLATE |
| 8 | Events | Complimentary Vouchers & Discount Vouchers | `all_flows_bpmn/events__complimentary_vouchers_and_discount_vouchers.bpmn` | DEMO_TEMPLATE |
| 9 | Events | Hotel Gift Voucher Request Form | `all_flows_bpmn/events__hotel_gift_voucher_request_form.bpmn` | DEMO_TEMPLATE |
| 10 | Exit Clearance Form | Book2 | `all_flows_bpmn/exit_clearance_form__book2.bpmn` | FULL_REFERENCE_EXIT |
| 11 | Exit Clearance Form | Exit Clearance Form - 25July2024 | `all_flows_bpmn/exit_clearance_form__exit_clearance_form_25july2024.bpmn` | FULL_REFERENCE_EXIT |
| 12 | Exit Clearance Form | Exit Clearance Form - Feb2018f | `all_flows_bpmn/exit_clearance_form__exit_clearance_form_feb2018f.bpmn` | FULL_REFERENCE_EXIT |
| 13 | Exit Clearance Form | Exit Clearance Form - Feb2018f-v4 (003) | `all_flows_bpmn/exit_clearance_form__exit_clearance_form_feb2018f_v4_003.bpmn` | FULL_REFERENCE_EXIT |
| 14 | Exit Clearance Form | Exit Clearance Form Drafe workflow and report | `all_flows_bpmn/exit_clearance_form__exit_clearance_form_drafe_workflow_and_report.bpmn` | FULL_REFERENCE_EXIT |
| 15 | Exit Clearance Form | Exit Clearance Form Testing DOC | `all_flows_bpmn/exit_clearance_form__exit_clearance_form_testing_doc.bpmn` | FULL_REFERENCE_EXIT |
| 16 | Exit Clearance Form | Exit Clearance Form Testing Doc 28-Nov-2024 | `all_flows_bpmn/exit_clearance_form__exit_clearance_form_testing_doc_28_nov_2024.bpmn` | FULL_REFERENCE_EXIT |
| 17 | Exit Clearance Form | Testing Doc 03-Sep-2024(New) | `all_flows_bpmn/exit_clearance_form__testing_doc_03_sep_2024_new.bpmn` | FULL_REFERENCE_EXIT |
| 18 | Exit Clearance Form | Testing Doc 22-Aug-2024 | `all_flows_bpmn/exit_clearance_form__testing_doc_22_aug_2024.bpmn` | FULL_REFERENCE_EXIT |
| 19 | Exit Clearance Form | Testing Feedback | `all_flows_bpmn/exit_clearance_form__testing_feedback.bpmn` | FULL_REFERENCE_EXIT |
| 20 | Finance | BCJ | `all_flows_bpmn/finance__bcj.bpmn` | FULL_REFERENCE_BCJ |
| 21 | Finance | BCJ Routing | `all_flows_bpmn/finance__bcj_routing.bpmn` | FULL_REFERENCE_BCJ |
| 22 | Finance | Fixed Asset Disposal | `all_flows_bpmn/finance__fixed_asset_disposal.bpmn` | DEMO_TEMPLATE |
| 23 | Finance | Fixed Asset Transfer | `all_flows_bpmn/finance__fixed_asset_transfer.bpmn` | DEMO_TEMPLATE |
| 24 | Finance | Gaming IA-Variance Approval | `all_flows_bpmn/finance__gaming_ia_variance_approval.bpmn` | DEMO_TEMPLATE |
| 25 | Finance | UAT For Finance | `all_flows_bpmn/finance__uat_for_finance.bpmn` | DEMO_TEMPLATE |
| 26 | Fire Safey | Emergency Incident Form | `all_flows_bpmn/fire_safey__emergency_incident_form.bpmn` | DEMO_TEMPLATE |
| 27 | HR | Additional Time Work Claim Form | `all_flows_bpmn/hr__additional_time_work_claim_form.bpmn` | DEMO_TEMPLATE |
| 28 | HR | Admin - Item Repair Form | `all_flows_bpmn/hr__admin_item_repair_form.bpmn` | DEMO_TEMPLATE |
| 29 | HR | Admin - Item Request Form | `all_flows_bpmn/hr__admin_item_request_form.bpmn` | DEMO_TEMPLATE |
| 30 | HR | Admin - Phone&Allowance Request Form | `all_flows_bpmn/hr__admin_phone_and_allowance_request_form.bpmn` | DEMO_TEMPLATE |
| 31 | HR | Admin - Purchase Request Form | `all_flows_bpmn/hr__admin_purchase_request_form.bpmn` | DEMO_TEMPLATE |
| 32 | HR | Authorisation to Travel Form | `all_flows_bpmn/hr__authorisation_to_travel_form.bpmn` | DEMO_TEMPLATE |
| 33 | HR | Car Park | `all_flows_bpmn/hr__car_park.bpmn` | DEMO_TEMPLATE |
| 34 | HR | Home Leave Ticket | `all_flows_bpmn/hr__home_leave_ticket.bpmn` | DEMO_TEMPLATE |
| 35 | HR | Honesty Award Request Form | `all_flows_bpmn/hr__honesty_award_request_form.bpmn` | DEMO_TEMPLATE |
| 36 | HR | HR Course Registration Form | `all_flows_bpmn/hr__hr_course_registration_form.bpmn` | DEMO_TEMPLATE |
| 37 | HR | HR Employee Of the month | `all_flows_bpmn/hr__hr_employee_of_the_month.bpmn` | DEMO_TEMPLATE |
| 38 | HR | HR Medical Treatment | `all_flows_bpmn/hr__hr_medical_treatment.bpmn` | DEMO_TEMPLATE |
| 39 | HR | HR Request For Document | `all_flows_bpmn/hr__hr_request_for_document.bpmn` | DEMO_TEMPLATE |
| 40 | HR | Meal Allowance & Laundry Form | `all_flows_bpmn/hr__meal_allowance_and_laundry_form.bpmn` | DEMO_TEMPLATE |
| 41 | HR | Onboarding Ticket Request Form | `all_flows_bpmn/hr__onboarding_ticket_request_form.bpmn` | DEMO_TEMPLATE |
| 42 | HR | Request User Access Form Detail | `all_flows_bpmn/hr__request_user_access_form_detail.bpmn` | DEMO_TEMPLATE |
| 43 | Hygiene | Foreign Object Complaint Form Detail | `all_flows_bpmn/hygiene__foreign_object_complaint_form_detail.bpmn` | DEMO_TEMPLATE |
| 44 | IT | Internet Bandwidth | `all_flows_bpmn/it__internet_bandwidth.bpmn` | DEMO_TEMPLATE |
| 45 | IT | IT Change Request | `all_flows_bpmn/it__it_change_request.bpmn` | DEMO_TEMPLATE |
| 46 | IT | IT Generic AD Login Request Form-2019Jul03 | `all_flows_bpmn/it__it_generic_ad_login_request_form_2019jul03.bpmn` | DEMO_TEMPLATE |
| 47 | IT | IT Item Record Form | `all_flows_bpmn/it__it_item_record_form.bpmn` | DEMO_TEMPLATE |
| 48 | IT | IT Item Repair | `all_flows_bpmn/it__it_item_repair.bpmn` | DEMO_TEMPLATE |
| 49 | IT | IT Project Responsitory | `all_flows_bpmn/it__it_project_responsitory.bpmn` | DEMO_TEMPLATE |
| 50 | IT | IT Request Form | `all_flows_bpmn/it__it_request_form.bpmn` | DEMO_TEMPLATE |
| 51 | IT | IT Simphony Meny Item Request Form | `all_flows_bpmn/it__it_simphony_meny_item_request_form.bpmn` | DEMO_TEMPLATE |
| 52 | IT | IT Software Development Form | `all_flows_bpmn/it__it_software_development_form.bpmn` | DEMO_TEMPLATE |
| 53 | IT | IT Software Review Form | `all_flows_bpmn/it__it_software_review_form.bpmn` | DEMO_TEMPLATE |
| 54 | IT | IT Training Feedback Form | `all_flows_bpmn/it__it_training_feedback_form.bpmn` | DEMO_TEMPLATE |
| 55 | IT | IT VPN Form | `all_flows_bpmn/it__it_vpn_form.bpmn` | DEMO_TEMPLATE |
| 56 | IT | Review-IT Incident SLA | `all_flows_bpmn/it__review_it_incident_sla.bpmn` | DEMO_TEMPLATE |
| 57 | Legal | Contract Draft-Review Request | `all_flows_bpmn/legal__contract_draft_review_request.bpmn` | DEMO_TEMPLATE |
| 58 | Maintenance | Maintenance Work Order Request Form | `all_flows_bpmn/maintenance__maintenance_work_order_request_form.bpmn` | DEMO_TEMPLATE |
| 59 | Maintenance | Maintenance Work Order Request Form-V5(23-Nov-2020) | `all_flows_bpmn/maintenance__maintenance_work_order_request_form_v5_23_nov_2020.bpmn` | DEMO_TEMPLATE |
| 60 | Maintenance | Maintenance Work Order Request Form-V6 2022No | `all_flows_bpmn/maintenance__maintenance_work_order_request_form_v6_2022no.bpmn` | DEMO_TEMPLATE |
| 61 | Maintenance | Maintenance Work Order Request Form-V7 2023May18 | `all_flows_bpmn/maintenance__maintenance_work_order_request_form_v7_2023may18.bpmn` | DEMO_TEMPLATE |
| 62 | Maintenance | Preventive Maintenance Form | `all_flows_bpmn/maintenance__preventive_maintenance_form.bpmn` | DEMO_TEMPLATE |
| 63 | Poker | Poker Keys and Card Inventory | `all_flows_bpmn/poker__poker_keys_and_card_inventory.bpmn` | DEMO_TEMPLATE |
| 64 | QA Test | K2 - Complimentary Vouchers & Discount Vouchers testing by Chaly | `all_flows_bpmn/qa_test__k2_complimentary_vouchers_and_discount_vouchers_testing_by_chaly.bpmn` | DEMO_TEMPLATE |
| 65 | Reservation | 1st November - Change of Friends and Family Rates and T&C in K2 | `all_flows_bpmn/reservation__1st_november_change_of_friends_and_family_rates_and_t_and_c_in_k2.bpmn` | DEMO_TEMPLATE |
| 66 | Reservation | Complimentary Room Request | `all_flows_bpmn/reservation__complimentary_room_request.bpmn` | DEMO_TEMPLATE |
| 67 | Reservation | Complimentary Room Request - R3 old | `all_flows_bpmn/reservation__complimentary_room_request_r3_old.bpmn` | DEMO_TEMPLATE |
| 68 | Reservation | Friends and Family Booking Request | `all_flows_bpmn/reservation__friends_and_family_booking_request.bpmn` | DEMO_TEMPLATE |
| 69 | Risk Management Matric | Self Assessment Form | `all_flows_bpmn/risk_management_matric__self_assessment_form.bpmn` | DEMO_TEMPLATE |
| 70 | Risk Management Matric | Self Assessment Form up1 | `all_flows_bpmn/risk_management_matric__self_assessment_form_up1.bpmn` | DEMO_TEMPLATE |
| 71 | Surveillance | Request For Access Card | `all_flows_bpmn/surveillance__request_for_access_card.bpmn` | DEMO_TEMPLATE |

## Import Order

1. Pick flow from `ALL_FLOWS_BPMN_INDEX.csv`.
2. Import corresponding file from `all_flows_bpmn/`.
3. Click Sync.
4. Configure Runtime + User Groups + Actions + Conditions.
5. Run approve/rework/reject test cycle before deploy.
