from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError
from datetime import datetime, timedelta


class TestHonestlyAwardRequest(TransactionCase):
    """Test cases for the Honestly Award Request model."""

    @classmethod
    def setUpClass(cls):
        """Set up test data for all test methods."""
        super().setUpClass()
        
        # Create test items
        cls.item_1 = cls.env['x_item'].create({
            'x_name': 'Medal',
        })
        cls.item_2 = cls.env['x_item'].create({
            'x_name': 'Certificate',
        })
        
        # Create test locations
        cls.location_1 = cls.env['x_location'].create({
            'x_name': 'Head Office',
        })
        cls.location_2 = cls.env['x_location'].create({
            'x_name': 'Branch Office',
        })
        
        # Create test employees
        cls.employee_1 = cls.env['hr.employee'].create({
            'name': 'John Doe',
        })
        cls.employee_2 = cls.env['hr.employee'].create({
            'name': 'Jane Smith',
        })

    def setUp(self):
        """Set up test fixtures before each test method."""
        super().setUp()
        
        # Clear any existing honestly award requests
        self.env['x_honestly_award'].search([]).unlink()

    # ============== Test Honestly Award Creation ==============

    def test_create_honestly_award_basic(self):
        """Test basic creation of an honestly award request."""
        award = self.env['x_honestly_award'].create({
            'x_description': 'Test Award Request',
        })
        self.assertIsNotNone(award)
        self.assertEqual(award.x_description, 'Test Award Request')

    def test_create_honestly_award_with_details(self):
        """Test creation of honestly award with detail lines."""
        award = self.env['x_honestly_award'].create({
            'x_description': 'Award with Details',
            'x_honestly_award_detail_ids': [
                (0, 0, {
                    'x_employee_id': self.employee_1.id,
                    'x_item_id': self.item_1.id,
                    'x_location_id': self.location_1.id,
                    'x_date': datetime.now().date(),
                    'x_estimate_value': 100.0,
                    'x_remark': 'Test remark',
                })
            ],
        })
        self.assertEqual(len(award.x_honestly_award_detail_ids), 1)
        detail = award.x_honestly_award_detail_ids[0]
        self.assertEqual(detail.x_employee_id.id, self.employee_1.id)
        self.assertEqual(detail.x_item_id.id, self.item_1.id)
        self.assertEqual(detail.x_estimate_value, 100.0)

    def test_create_honestly_award_multiple_details(self):
        """Test creation of honestly award with multiple detail lines."""
        award = self.env['x_honestly_award'].create({
            'x_description': 'Multiple Recipients Award',
            'x_honestly_award_detail_ids': [
                (0, 0, {
                    'x_employee_id': self.employee_1.id,
                    'x_item_id': self.item_1.id,
                    'x_location_id': self.location_1.id,
                    'x_date': datetime.now().date(),
                    'x_estimate_value': 100.0,
                    'x_remark': 'Recipient 1',
                }),
                (0, 0, {
                    'x_employee_id': self.employee_2.id,
                    'x_item_id': self.item_2.id,
                    'x_location_id': self.location_2.id,
                    'x_date': datetime.now().date(),
                    'x_estimate_value': 75.0,
                    'x_remark': 'Recipient 2',
                })
            ],
        })
        self.assertEqual(len(award.x_honestly_award_detail_ids), 2)

    # ============== Test Honestly Award Detail ==============

    def test_create_award_detail_basic(self):
        """Test basic creation of award detail."""
        award = self.env['x_honestly_award'].create({
            'x_description': 'Test Award',
        })
        detail = self.env['x_honestly_award_detail'].create({
            'x_honestly_award_id': award.id,
            'x_employee_id': self.employee_1.id,
            'x_item_id': self.item_1.id,
            'x_location_id': self.location_1.id,
            'x_date': datetime.now().date(),
            'x_estimate_value': 150.0,
            'x_remark': 'Outstanding performance',
        })
        self.assertEqual(detail.x_estimate_value, 150.0)
        self.assertEqual(detail.x_remark, 'Outstanding performance')

    def test_award_detail_employee_required(self):
        """Test that employee is required in award detail."""
        award = self.env['x_honestly_award'].create({
            'x_description': 'Test Award',
        })
        
        with self.assertRaises(ValidationError):
            self.env['x_honestly_award_detail'].create({
                'x_honestly_award_id': award.id,
                'x_item_id': self.item_1.id,
                'x_location_id': self.location_1.id,
                'x_date': datetime.now().date(),
                'x_estimate_value': 100.0,
            })

    def test_award_detail_item_required(self):
        """Test that item is required in award detail."""
        award = self.env['x_honestly_award'].create({
            'x_description': 'Test Award',
        })
        
        with self.assertRaises(ValidationError):
            self.env['x_honestly_award_detail'].create({
                'x_honestly_award_id': award.id,
                'x_employee_id': self.employee_1.id,
                'x_location_id': self.location_1.id,
                'x_date': datetime.now().date(),
                'x_estimate_value': 100.0,
            })

    # ============== Test Estimate Value ==============

    def test_estimate_value_positive(self):
        """Test that positive estimate values are accepted."""
        detail = self.env['x_honestly_award_detail'].create({
            'x_employee_id': self.employee_1.id,
            'x_item_id': self.item_1.id,
            'x_location_id': self.location_1.id,
            'x_date': datetime.now().date(),
            'x_estimate_value': 999.99,
        })
        self.assertEqual(detail.x_estimate_value, 999.99)

    def test_estimate_value_zero(self):
        """Test that zero estimate value is accepted."""
        detail = self.env['x_honestly_award_detail'].create({
            'x_employee_id': self.employee_1.id,
            'x_item_id': self.item_1.id,
            'x_location_id': self.location_1.id,
            'x_date': datetime.now().date(),
            'x_estimate_value': 0.0,
        })
        self.assertEqual(detail.x_estimate_value, 0.0)

    def test_estimate_value_decimal(self):
        """Test that decimal estimate values are handled correctly."""
        detail = self.env['x_honestly_award_detail'].create({
            'x_employee_id': self.employee_1.id,
            'x_item_id': self.item_1.id,
            'x_location_id': self.location_1.id,
            'x_date': datetime.now().date(),
            'x_estimate_value': 123.45,
        })
        self.assertEqual(detail.x_estimate_value, 123.45)

    # ============== Test Date Handling ==============

    def test_award_detail_date_today(self):
        """Test award detail with today's date."""
        today = datetime.now().date()
        detail = self.env['x_honestly_award_detail'].create({
            'x_employee_id': self.employee_1.id,
            'x_item_id': self.item_1.id,
            'x_location_id': self.location_1.id,
            'x_date': today,
            'x_estimate_value': 100.0,
        })
        self.assertEqual(detail.x_date, today)

    def test_award_detail_date_future(self):
        """Test award detail with future date."""
        future_date = datetime.now().date() + timedelta(days=30)
        detail = self.env['x_honestly_award_detail'].create({
            'x_employee_id': self.employee_1.id,
            'x_item_id': self.item_1.id,
            'x_location_id': self.location_1.id,
            'x_date': future_date,
            'x_estimate_value': 100.0,
        })
        self.assertEqual(detail.x_date, future_date)

    def test_award_detail_date_past(self):
        """Test award detail with past date."""
        past_date = datetime.now().date() - timedelta(days=30)
        detail = self.env['x_honestly_award_detail'].create({
            'x_employee_id': self.employee_1.id,
            'x_item_id': self.item_1.id,
            'x_location_id': self.location_1.id,
            'x_date': past_date,
            'x_estimate_value': 100.0,
        })
        self.assertEqual(detail.x_date, past_date)

    # ============== Test Description Field ==============

    def test_award_description_empty(self):
        """Test award with empty description."""
        award = self.env['x_honestly_award'].create({
            'x_description': '',
        })
        self.assertEqual(award.x_description, '')

    def test_award_description_text(self):
        """Test award with text description."""
        description = 'This is a comprehensive description of the award criteria.'
        award = self.env['x_honestly_award'].create({
            'x_description': description,
        })
        self.assertEqual(award.x_description, description)

    def test_award_description_multiline(self):
        """Test award with multiline description."""
        description = '''Line 1
Line 2
Line 3'''
        award = self.env['x_honestly_award'].create({
            'x_description': description,
        })
        self.assertEqual(award.x_description, description)

    # ============== Test Remark Field ==============

    def test_award_detail_remark_empty(self):
        """Test award detail with empty remark."""
        detail = self.env['x_honestly_award_detail'].create({
            'x_employee_id': self.employee_1.id,
            'x_item_id': self.item_1.id,
            'x_location_id': self.location_1.id,
            'x_date': datetime.now().date(),
            'x_estimate_value': 100.0,
            'x_remark': '',
        })
        self.assertEqual(detail.x_remark, '')

    def test_award_detail_remark_text(self):
        """Test award detail with text remark."""
        remark = 'Exceptional contribution to team success'
        detail = self.env['x_honestly_award_detail'].create({
            'x_employee_id': self.employee_1.id,
            'x_item_id': self.item_1.id,
            'x_location_id': self.location_1.id,
            'x_date': datetime.now().date(),
            'x_estimate_value': 100.0,
            'x_remark': remark,
        })
        self.assertEqual(detail.x_remark, remark)

    # ============== Test Related Records ==============

    def test_award_detail_cascade_delete(self):
        """Test that award details are deleted when award is deleted."""
        award = self.env['x_honestly_award'].create({
            'x_description': 'Award for deletion test',
            'x_honestly_award_detail_ids': [
                (0, 0, {
                    'x_employee_id': self.employee_1.id,
                    'x_item_id': self.item_1.id,
                    'x_location_id': self.location_1.id,
                    'x_date': datetime.now().date(),
                    'x_estimate_value': 100.0,
                })
            ],
        })
        detail_id = award.x_honestly_award_detail_ids[0].id
        award.unlink()
        
        # Verify detail is also deleted
        deleted_detail = self.env['x_honestly_award_detail'].search([('id', '=', detail_id)])
        self.assertEqual(len(deleted_detail), 0)

    def test_award_detail_employee_relationship(self):
        """Test that award detail maintains proper employee relationship."""
        detail = self.env['x_honestly_award_detail'].create({
            'x_employee_id': self.employee_1.id,
            'x_item_id': self.item_1.id,
            'x_location_id': self.location_1.id,
            'x_date': datetime.now().date(),
            'x_estimate_value': 100.0,
        })
        self.assertEqual(detail.x_employee_id.name, 'John Doe')

    def test_award_detail_item_relationship(self):
        """Test that award detail maintains proper item relationship."""
        detail = self.env['x_honestly_award_detail'].create({
            'x_employee_id': self.employee_1.id,
            'x_item_id': self.item_1.id,
            'x_location_id': self.location_1.id,
            'x_date': datetime.now().date(),
            'x_estimate_value': 100.0,
        })
        self.assertEqual(detail.x_item_id.x_name, 'Medal')

    def test_award_detail_location_relationship(self):
        """Test that award detail maintains proper location relationship."""
        detail = self.env['x_honestly_award_detail'].create({
            'x_employee_id': self.employee_1.id,
            'x_item_id': self.item_1.id,
            'x_location_id': self.location_1.id,
            'x_date': datetime.now().date(),
            'x_estimate_value': 100.0,
        })
        self.assertEqual(detail.x_location_id.x_name, 'Head Office')

    # ============== Test Read/Write Operations ==============

    def test_award_update_description(self):
        """Test updating award description."""
        award = self.env['x_honestly_award'].create({
            'x_description': 'Initial description',
        })
        award.write({'x_description': 'Updated description'})
        self.assertEqual(award.x_description, 'Updated description')

    def test_award_detail_update_estimate_value(self):
        """Test updating award detail estimate value."""
        detail = self.env['x_honestly_award_detail'].create({
            'x_employee_id': self.employee_1.id,
            'x_item_id': self.item_1.id,
            'x_location_id': self.location_1.id,
            'x_date': datetime.now().date(),
            'x_estimate_value': 100.0,
        })
        detail.write({'x_estimate_value': 200.0})
        self.assertEqual(detail.x_estimate_value, 200.0)

    def test_award_detail_update_date(self):
        """Test updating award detail date."""
        old_date = datetime.now().date()
        new_date = old_date + timedelta(days=10)
        detail = self.env['x_honestly_award_detail'].create({
            'x_employee_id': self.employee_1.id,
            'x_item_id': self.item_1.id,
            'x_location_id': self.location_1.id,
            'x_date': old_date,
            'x_estimate_value': 100.0,
        })
        detail.write({'x_date': new_date})
        self.assertEqual(detail.x_date, new_date)

    # ============== Test Search Operations ==============

    def test_search_award_by_description(self):
        """Test searching awards by description."""
        award = self.env['x_honestly_award'].create({
            'x_description': 'Unique Award Description XYZ',
        })
        found = self.env['x_honestly_award'].search([
            ('x_description', 'ilike', 'Unique Award Description XYZ')
        ])
        self.assertIn(award.id, found.ids)

    def test_search_award_detail_by_employee(self):
        """Test searching award details by employee."""
        detail = self.env['x_honestly_award_detail'].create({
            'x_employee_id': self.employee_1.id,
            'x_item_id': self.item_1.id,
            'x_location_id': self.location_1.id,
            'x_date': datetime.now().date(),
            'x_estimate_value': 100.0,
        })
        found = self.env['x_honestly_award_detail'].search([
            ('x_employee_id', '=', self.employee_1.id)
        ])
        self.assertIn(detail.id, found.ids)

    def test_search_award_detail_by_estimate_value(self):
        """Test searching award details by estimate value."""
        detail = self.env['x_honestly_award_detail'].create({
            'x_employee_id': self.employee_1.id,
            'x_item_id': self.item_1.id,
            'x_location_id': self.location_1.id,
            'x_date': datetime.now().date(),
            'x_estimate_value': 500.0,
        })
        found = self.env['x_honestly_award_detail'].search([
            ('x_estimate_value', '>=', 400.0)
        ])
        self.assertIn(detail.id, found.ids)

    def test_search_award_detail_by_date_range(self):
        """Test searching award details by date range."""
        today = datetime.now().date()
        detail = self.env['x_honestly_award_detail'].create({
            'x_employee_id': self.employee_1.id,
            'x_item_id': self.item_1.id,
            'x_location_id': self.location_1.id,
            'x_date': today,
            'x_estimate_value': 100.0,
        })
        found = self.env['x_honestly_award_detail'].search([
            ('x_date', '>=', today - timedelta(days=1)),
            ('x_date', '<=', today + timedelta(days=1)),
        ])
        self.assertIn(detail.id, found.ids)
