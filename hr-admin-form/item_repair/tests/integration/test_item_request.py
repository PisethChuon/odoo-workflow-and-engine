from odoo.tests.common import TransactionCase
from odoo import fields


class TestItemRequest(TransactionCase):
    """Test cases for the Item Request model."""

    @classmethod
    def setUpClass(cls):
        """Set up test data for all test methods."""
        super().setUpClass()
        
        # Create item request types
        cls.item_type_walkie = cls.env['x_item_request_type'].create({
            'x_name': 'Walkie Talkie',
            'x_description': 'Two-way radio communication device',
        })
        
        cls.item_type_accessory = cls.env['x_item_request_type'].create({
            'x_name': 'Phone Accessory',
            'x_description': 'Mobile phone accessories',
        })
        
        # Create test departments
        cls.dept_it = cls.env['hr.department'].create({
            'name': 'IT Department',
        })
        
        cls.dept_sales = cls.env['hr.department'].create({
            'name': 'Sales Department',
        })
        
        # Create test employees
        cls.employee_1 = cls.env['hr.employee'].create({
            'name': 'John Doe',
            'department_id': cls.dept_it.id,
        })
        
        cls.employee_2 = cls.env['hr.employee'].create({
            'name': 'Jane Smith',
            'department_id': cls.dept_sales.id,
        })
        
        # Create test users linked to employees
        cls.user_1 = cls.env['res.users'].create({
            'name': 'John User',
            'login': 'john@example.com',
            'employee_id': cls.employee_1.id,
        })
        
        cls.user_2 = cls.env['res.users'].create({
            'name': 'Jane User',
            'login': 'jane@example.com',
            'employee_id': cls.employee_2.id,
        })

    def setUp(self):
        """Set up test fixtures before each test method."""
        super().setUp()
        
        # Clear any existing item repair requests and item requests
        self.env['x_item_request'].search([]).unlink()
        self.env['x_item_repair_request'].search([]).unlink()

    # ============== Test Item Request Creation ==============

    def test_create_item_request_basic(self):
        """Test creating a basic item request."""
        # Create an item repair request first
        repair_request = self.env['x_item_repair_request'].create({
            'category_id': self._create_test_category().id,
            'request_owner_id': self.user_1.id,
        })
        
        # Create an item request
        item_request = self.env['x_item_request'].create({
            'x_item_repair_request_id': repair_request.id,
            'x_item_request': self.item_type_walkie.id,
            'x_serial_number': 'SN12345',
        })
        
        self.assertEqual(item_request.x_serial_number, 'SN12345')
        self.assertEqual(item_request.x_item_request.id, self.item_type_walkie.id)

    def test_item_request_requires_item_type(self):
        """Test that item request requires an item type."""
        repair_request = self.env['x_item_repair_request'].create({
            'category_id': self._create_test_category().id,
            'request_owner_id': self.user_1.id,
        })
        
        # Try to create without item type - should raise an error
        with self.assertRaises(Exception):
            self.env['x_item_request'].create({
                'x_item_repair_request_id': repair_request.id,
                'x_serial_number': 'SN12345',
            })

    # ============== Test Automatic Department Assignment ==============

    def test_department_auto_fill_from_request_owner(self):
        """Test that department is automatically filled from request owner."""
        repair_request = self.env['x_item_repair_request'].create({
            'category_id': self._create_test_category().id,
            'request_owner_id': self.user_1.id,
        })
        
        item_request = self.env['x_item_request'].create({
            'x_item_repair_request_id': repair_request.id,
            'x_item_request': self.item_type_walkie.id,
            'x_serial_number': 'SN12345',
        })
        
        # Department should be automatically filled from user_1's employee department
        self.assertEqual(item_request.x_charge_to_depat.id, self.dept_it.id)

    def test_department_changes_with_request_owner(self):
        """Test that department updates when request owner changes."""
        repair_request = self.env['x_item_repair_request'].create({
            'category_id': self._create_test_category().id,
            'request_owner_id': self.user_1.id,
        })
        
        item_request = self.env['x_item_request'].create({
            'x_item_repair_request_id': repair_request.id,
            'x_item_request': self.item_type_walkie.id,
            'x_serial_number': 'SN12345',
        })
        
        # Initial department from user_1 (IT)
        self.assertEqual(item_request.x_charge_to_depat.id, self.dept_it.id)
        
        # Change request owner to user_2 (Sales)
        repair_request.request_owner_id = self.user_2
        
        # Department should update to sales
        self.assertEqual(item_request.x_charge_to_depat.id, self.dept_sales.id)

    def test_department_field_readonly(self):
        """Test that department field is read-only."""
        repair_request = self.env['x_item_repair_request'].create({
            'category_id': self._create_test_category().id,
            'request_owner_id': self.user_1.id,
        })
        
        item_request = self.env['x_item_request'].create({
            'x_item_repair_request_id': repair_request.id,
            'x_item_request': self.item_type_walkie.id,
            'x_serial_number': 'SN12345',
        })
        
        # Verify field is readonly
        field_def = self.env['x_item_request']._fields['x_charge_to_depat']
        self.assertTrue(field_def.readonly)

    # ============== Test Item Request with Serial Number ==============

    def test_create_item_request_with_serial(self):
        """Test creating item request with serial number."""
        repair_request = self.env['x_item_repair_request'].create({
            'category_id': self._create_test_category().id,
            'request_owner_id': self.user_1.id,
        })
        
        item_request = self.env['x_item_request'].create({
            'x_item_repair_request_id': repair_request.id,
            'x_item_request': self.item_type_accessory.id,
            'x_serial_number': 'ACC-2024-001',
        })
        
        self.assertEqual(item_request.x_serial_number, 'ACC-2024-001')

    def test_create_item_request_without_serial(self):
        """Test creating item request without serial number."""
        repair_request = self.env['x_item_repair_request'].create({
            'category_id': self._create_test_category().id,
            'request_owner_id': self.user_1.id,
        })
        
        item_request = self.env['x_item_request'].create({
            'x_item_repair_request_id': repair_request.id,
            'x_item_request': self.item_type_walkie.id,
        })
        
        self.assertFalse(item_request.x_serial_number)

    # ============== Test Submitter Remarks ==============

    def test_add_submitter_remark(self):
        """Test adding submitter remarks to item request."""
        repair_request = self.env['x_item_repair_request'].create({
            'category_id': self._create_test_category().id,
            'request_owner_id': self.user_1.id,
        })
        
        remark = "Device has screen damage on the right side"
        item_request = self.env['x_item_request'].create({
            'x_item_repair_request_id': repair_request.id,
            'x_item_request': self.item_type_walkie.id,
            'x_serial_number': 'SN12345',
            'x_submitter_remark': remark,
        })
        
        self.assertEqual(item_request.x_submitter_remark, remark)

    # ============== Helper Methods ==============

    def _create_test_category(self):
        """Create a test approval category for item repair requests."""
        return self.env['workflow.approval.category'].create({
            'name': 'Test Item Repair Category',
            'res_model_id': self.env['ir.model'].search([('model', '=', 'x_item_repair_request')]).id,
        })
