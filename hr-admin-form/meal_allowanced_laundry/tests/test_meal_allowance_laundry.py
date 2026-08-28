from odoo.tests.common import TransactionCase


class TestMealAllowanceTitleConfiguration(TransactionCase):
    """Verify title records can drive request defaults from UI-managed data."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.level_4a = cls.env.ref('meal_allowanced_laundry.x_meal_allowance_level_4a')
        cls.level_5a = cls.env.ref('meal_allowanced_laundry.x_meal_allowance_level_5a')

    def setUp(self):
        super().setUp()
        self.env['x_meal_allowance_request'].search([]).unlink()

    def test_title_configuration_is_used_for_request_auto_fill(self):
        title = self.env['x_meal_allowance_title'].create({
            'x_name': 'Temporary Director',
            'x_level_id': self.level_4a.id,
            'x_entitlement_monthly': '180.0',
        })

        request = self.env['x_meal_allowance_request'].create({
            'x_title': title.id,
        })

        self.assertEqual(request.x_meal_allowance_level_id.id, self.level_4a.id)
        self.assertEqual(request.x_entitlement_monthly, '180.0')

        title.write({
            'x_level_id': self.level_5a.id,
            'x_entitlement_monthly': '250.0',
        })

        second_request = self.env['x_meal_allowance_request'].create({
            'x_title': title.id,
        })

        self.assertEqual(second_request.x_meal_allowance_level_id.id, self.level_5a.id)
        self.assertEqual(second_request.x_entitlement_monthly, '250.0')

    def test_meal_and_laundry_entitlements_are_independent(self):
        title = self.env['x_meal_allowance_title'].create({
            'x_name': 'Director',
            'x_level_id': self.level_4a.id,
            'x_entitlement_monthly': '180.0',
        })
        staff_group = self.env['x_meal_allowance_staff_group'].create({
            'x_name': 'Housekeeping',
            'x_entitlement_information_monthly': '150.0',
        })

        request = self.env['x_meal_allowance_request'].create({
            'x_title': title.id,
            'x_is_laundry': True,
            'x_staff_group_id': staff_group.id,
        })

        self.assertEqual(request.x_entitlement_monthly, '180.0')
        self.assertEqual(request.x_entitlement_information_monthly, '150.0')


class TestMealAllowanceStaffGroupConfiguration(TransactionCase):
    """Verify staff group apparel configuration flows into requests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.apparel_all = cls.env.ref('meal_allowanced_laundry.x_meal_allowance_apparel_type_all')

    def setUp(self):
        super().setUp()
        self.env['x_meal_allowance_request'].search([]).unlink()

    def test_staff_group_apparel_type_is_used_for_request_auto_fill(self):
        staff_group = self.env['x_meal_allowance_staff_group'].create({
            'x_name': 'Temporary Staff Group',
            'x_entitlement_information_monthly': '150.0',
            'x_apparel_type_id': self.apparel_all.id,
        })

        request = self.env['x_meal_allowance_request'].create({
            'x_staff_group_id': staff_group.id,
        })

        self.assertEqual(request.x_entitlement_information_monthly, '150.0')
        self.assertEqual(request.x_apparel_type, 'All')


class TestMealAllowanceEmployeeAutoFill(TransactionCase):
    """Verify employee number lookup drives employee name and position display."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.job = cls.env['hr.job'].create({
            'name': 'Operations Supervisor',
            'company_id': cls.env.company.id,
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Alex Employee',
            'barcode': 'EMP-001',
            'identification_id': 'EMP-ID-001',
            'job_id': cls.job.id,
            'company_id': cls.env.company.id,
        })

    def setUp(self):
        super().setUp()
        self.env['x_meal_allowance_request'].search([]).unlink()

    def test_employee_no_onchange_fills_employee_fields(self):
        request = self.env['x_meal_allowance_request'].new({
            'x_employee_no': self.employee.id,
        })

        self.assertEqual(request.x_employee_name, 'Alex Employee')
        self.assertEqual(request.x_position, 'Operations Supervisor')

    def test_employee_no_create_fills_employee_fields(self):
        request = self.env['x_meal_allowance_request'].create({
            'x_employee_no': self.employee.id,
        })

        self.assertEqual(request.x_employee_name, 'Alex Employee')
        self.assertEqual(request.x_position, 'Operations Supervisor')

    def test_employee_name_search_matches_employee_number(self):
        results = self.env['hr.employee'].name_search('EMP-001')

        self.assertTrue(any(result_id == self.employee.id for result_id, _display_name in results))
        self.assertTrue(any(display_name == 'EMP-001' for _result_id, display_name in results))

    def test_employee_name_get_returns_employee_number(self):
        self.employee.write({'x_emp_code': 'EMP-001'})

        display = dict(self.employee.with_context(meal_allowance_show_code=True).name_get())

        self.assertEqual(display[self.employee.id], 'EMP-001')

    def test_employee_name_search_keeps_employee_code_display(self):
        self.employee.write({'x_emp_code': 'EMP-001'})

        results = self.env['hr.employee'].with_context(meal_allowance_show_code=True).name_search('Alex')

        self.assertTrue(any(result_id == self.employee.id for result_id, _display_name in results))
        self.assertTrue(all(display_name == 'EMP-001' for _result_id, display_name in results if _result_id == self.employee.id))

    def test_employee_display_name_uses_employee_number_in_meal_allowance_context(self):
        self.employee.write({'x_emp_code': 'EMP-001'})

        employee = self.employee.with_context(meal_allowance_show_code=True)

        self.assertEqual(employee.display_name, 'EMP-001')
