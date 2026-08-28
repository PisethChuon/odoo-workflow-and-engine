from odoo.tests.common import TransactionCase
from odoo import fields
from datetime import datetime


class TestItemRequestType(TransactionCase):
    """Test cases for the Item Request Type model."""

    @classmethod
    def setUpClass(cls):
        """Set up test data for all test methods."""
        super().setUpClass()

    def setUp(self):
        """Set up test fixtures before each test method."""
        super().setUp()
        
        # Clear any existing item request types
        self.env['x_item_request_type'].search([]).unlink()

    # ============== Test Item Request Type Creation ==============

    def test_create_item_request_type_basic(self):
        """Test creating a basic item request type."""
        item_type = self.env['x_item_request_type'].create({
            'x_name': 'Walkie Talkie',
        })
        self.assertEqual(item_type.x_name, 'Walkie Talkie')
        self.assertTrue(item_type.x_active)

    def test_create_item_request_type_with_description(self):
        """Test creating an item request type with description."""
        item_type = self.env['x_item_request_type'].create({
            'x_name': 'Phone Accessory',
            'x_description': 'Mobile phone accessories like chargers, cables, etc.',
        })
        self.assertEqual(item_type.x_name, 'Phone Accessory')
        self.assertEqual(item_type.x_description, 'Mobile phone accessories like chargers, cables, etc.')

    def test_item_request_type_active_by_default(self):
        """Test that item request types are active by default."""
        item_type = self.env['x_item_request_type'].create({
            'x_name': 'Test Device',
        })
        self.assertTrue(item_type.x_active)

    def test_item_request_type_unique_name(self):
        """Test that item request type names are unique."""
        self.env['x_item_request_type'].create({
            'x_name': 'Unique Item',
        })
        
        # Try to create duplicate - should raise an error
        with self.assertRaises(Exception):
            self.env['x_item_request_type'].create({
                'x_name': 'Unique Item',
            })

    # ============== Test Item Request Type Deactivation ==============

    def test_deactivate_item_request_type(self):
        """Test deactivating an item request type."""
        item_type = self.env['x_item_request_type'].create({
            'x_name': 'Test Device',
        })
        
        item_type.x_active = False
        self.assertFalse(item_type.x_active)

    def test_reactivate_item_request_type(self):
        """Test reactivating a deactivated item request type."""
        item_type = self.env['x_item_request_type'].create({
            'x_name': 'Test Device',
        })
        
        item_type.x_active = False
        self.assertFalse(item_type.x_active)
        
        item_type.x_active = True
        self.assertTrue(item_type.x_active)

    # ============== Test Item Request Type Listing ==============

    def test_list_active_item_types(self):
        """Test listing only active item request types."""
        self.env['x_item_request_type'].create({
            'x_name': 'Active Device 1',
            'x_active': True,
        })
        self.env['x_item_request_type'].create({
            'x_name': 'Active Device 2',
            'x_active': True,
        })
        self.env['x_item_request_type'].create({
            'x_name': 'Inactive Device',
            'x_active': False,
        })
        
        active_types = self.env['x_item_request_type'].search([('x_active', '=', True)])
        self.assertEqual(len(active_types), 2)

    def test_list_all_item_types_ordered(self):
        """Test that item types are ordered by name."""
        self.env['x_item_request_type'].create({'x_name': 'Zebra Device'})
        self.env['x_item_request_type'].create({'x_name': 'Alpha Device'})
        self.env['x_item_request_type'].create({'x_name': 'Beta Device'})
        
        all_types = self.env['x_item_request_type'].search([], order='x_name')
        names = [item.x_name for item in all_types]
        
        self.assertEqual(names, sorted(names))
