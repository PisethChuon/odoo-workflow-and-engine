from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError
from datetime import datetime


class TestCarParkRequest(TransactionCase):
    """Test cases for the Car Park Permit Request model."""

    @classmethod
    def setUpClass(cls):
        """Set up test data for all test methods."""
        super().setUpClass()
        
        # Create test car models
        cls.car_model_1 = cls.env['x_car_model'].create({
            'x_name': 'Toyota Camry',
        })
        cls.car_model_2 = cls.env['x_car_model'].create({
            'x_name': 'Honda Civic',
        })
        
        # Create test car colors
        cls.car_color_1 = cls.env['x_car_color'].create({
            'x_name': 'Red',
        })
        cls.car_color_2 = cls.env['x_car_color'].create({
            'x_name': 'Blue',
        })

    def setUp(self):
        """Set up test fixtures before each test method."""
        super().setUp()
        
        # Clear any existing car park requests
        self.env['x_car_park_request'].search([]).unlink()

    # ============== Test Plate Number Normalization ==============

    def test_normalize_plate_number_uppercase(self):
        """Test that plate numbers are converted to uppercase."""
        record = self.env['x_car_park_request'].create({
            'x_plate_number': 'ab1234',
            'x_car_model': self.car_model_1.id,
            'x_car_color': self.car_color_1.id,
            'x_car_year_of_production': '2020',
        })
        self.assertEqual(record.x_plate_number, 'AB1234')

    def test_normalize_plate_number_remove_spaces(self):
        """Test that spaces are removed from plate numbers."""
        record = self.env['x_car_park_request'].create({
            'x_plate_number': 'ab 12 34',
            'x_car_model': self.car_model_1.id,
            'x_car_color': self.car_color_1.id,
            'x_car_year_of_production': '2020',
        })
        self.assertEqual(record.x_plate_number, 'AB1234')

    def test_normalize_plate_number_trim_whitespace(self):
        """Test that leading/trailing whitespace is trimmed."""
        record = self.env['x_car_park_request'].create({
            'x_plate_number': '  AB1234  ',
            'x_car_model': self.car_model_1.id,
            'x_car_color': self.car_color_1.id,
            'x_car_year_of_production': '2020',
        })
        self.assertEqual(record.x_plate_number, 'AB1234')

    def test_normalize_plate_number_preserve_hyphens(self):
        """Test that hyphens are preserved during normalization."""
        record = self.env['x_car_park_request'].create({
            'x_plate_number': 'ab-1234',
            'x_car_model': self.car_model_1.id,
            'x_car_color': self.car_color_1.id,
            'x_car_year_of_production': '2020',
        })
        self.assertEqual(record.x_plate_number, 'AB-1234')

    def test_normalize_plate_number_on_write(self):
        """Test that plate numbers are normalized when updated."""
        record = self.env['x_car_park_request'].create({
            'x_plate_number': 'xy9999',
            'x_car_model': self.car_model_1.id,
            'x_car_color': self.car_color_1.id,
            'x_car_year_of_production': '2020',
        })
        
        record.write({'x_plate_number': 'ab cd 12'})
        self.assertEqual(record.x_plate_number, 'ABCD12')

    # ============== Test Year of Production Validation ==============

    def test_year_validation_valid_year(self):
        """Test that valid years are accepted."""
        record = self.env['x_car_park_request'].create({
            'x_plate_number': 'TEST1234',
            'x_car_model': self.car_model_1.id,
            'x_car_color': self.car_color_1.id,
            'x_car_year_of_production': '2020',
        })
        self.assertEqual(record.x_car_year_of_production, '2020')

    def test_year_validation_min_year(self):
        """Test that minimum year (1900) is accepted."""
        record = self.env['x_car_park_request'].create({
            'x_plate_number': 'MIN1900',
            'x_car_model': self.car_model_1.id,
            'x_car_color': self.car_color_1.id,
            'x_car_year_of_production': '1900',
        })
        self.assertEqual(record.x_car_year_of_production, '1900')

    def test_year_validation_current_year(self):
        """Test that current year is accepted."""
        current_year = str(datetime.now().year)
        record = self.env['x_car_park_request'].create({
            'x_plate_number': 'CURR2024',
            'x_car_model': self.car_model_1.id,
            'x_car_color': self.car_color_1.id,
            'x_car_year_of_production': current_year,
        })
        self.assertEqual(record.x_car_year_of_production, current_year)

    def test_year_validation_future_year(self):
        """Test that future year (current year + 1) is accepted."""
        future_year = str(datetime.now().year + 1)
        record = self.env['x_car_park_request'].create({
            'x_plate_number': 'FUTR2025',
            'x_car_model': self.car_model_1.id,
            'x_car_color': self.car_color_1.id,
            'x_car_year_of_production': future_year,
        })
        self.assertEqual(record.x_car_year_of_production, future_year)

    def test_year_validation_too_low(self):
        """Test that years before 1900 are rejected."""
        with self.assertRaises(ValidationError) as context:
            self.env['x_car_park_request'].create({
                'x_plate_number': 'LOW1800',
                'x_car_model': self.car_model_1.id,
                'x_car_color': self.car_color_1.id,
                'x_car_year_of_production': '1899',
            })
        self.assertIn('Year of Production must be between', str(context.exception))

    def test_year_validation_too_high(self):
        """Test that years after (current year + 1) are rejected."""
        too_high_year = str(datetime.now().year + 2)
        with self.assertRaises(ValidationError) as context:
            self.env['x_car_park_request'].create({
                'x_plate_number': 'HIGH2027',
                'x_car_model': self.car_model_1.id,
                'x_car_color': self.car_color_1.id,
                'x_car_year_of_production': too_high_year,
            })
        self.assertIn('Year of Production must be between', str(context.exception))

    def test_year_validation_non_numeric(self):
        """Test that non-numeric years are rejected."""
        with self.assertRaises(ValidationError) as context:
            self.env['x_car_park_request'].create({
                'x_plate_number': 'NNUM2ABC',
                'x_car_model': self.car_model_1.id,
                'x_car_color': self.car_color_1.id,
                'x_car_year_of_production': '20AB',
            })
        self.assertIn('Year must be a 4-digit year', str(context.exception))

    def test_year_validation_wrong_length(self):
        """Test that non-4-digit years are rejected."""
        with self.assertRaises(ValidationError) as context:
            self.env['x_car_park_request'].create({
                'x_plate_number': 'WRNG202',
                'x_car_model': self.car_model_1.id,
                'x_car_color': self.car_color_1.id,
                'x_car_year_of_production': '202',
            })
        self.assertIn('Year must be a 4-digit year', str(context.exception))

    def test_year_validation_empty_string(self):
        """Test that empty year strings are accepted (optional field)."""
        record = self.env['x_car_park_request'].create({
            'x_plate_number': 'EMPT0000',
            'x_car_model': self.car_model_1.id,
            'x_car_color': self.car_color_1.id,
            'x_car_year_of_production': '',
        })
        self.assertEqual(record.x_car_year_of_production, '')

    def test_year_validation_whitespace_handled(self):
        """Test that whitespace around year is handled properly."""
        record = self.env['x_car_park_request'].create({
            'x_plate_number': 'WHTSP2020',
            'x_car_model': self.car_model_1.id,
            'x_car_color': self.car_color_1.id,
            'x_car_year_of_production': '  2020  ',
        })
        self.assertEqual(record.x_car_year_of_production, '2020')

    # ============== Test Plate Number Uniqueness ==============

    def test_plate_number_unique_active(self):
        """Test that plate numbers must be unique for active records."""
        # Create first record
        record1 = self.env['x_car_park_request'].create({
            'x_plate_number': 'UNIQ0001',
            'x_car_model': self.car_model_1.id,
            'x_car_color': self.car_color_1.id,
            'x_car_year_of_production': '2020',
        })
        
        # Try to create second record with same plate number
        with self.assertRaises(Exception):  # IntegrityError from unique index
            self.env['x_car_park_request'].create({
                'x_plate_number': 'UNIQ0001',
                'x_car_model': self.car_model_2.id,
                'x_car_color': self.car_color_2.id,
                'x_car_year_of_production': '2021',
            })

    # ============== Test Create and Write Methods ==============

    def test_create_multi_plate_normalization(self):
        """Test that multiple records are created with normalized plate numbers."""
        records = self.env['x_car_park_request'].create([
            {
                'x_plate_number': 'ab 12 34',
                'x_car_model': self.car_model_1.id,
                'x_car_color': self.car_color_1.id,
                'x_car_year_of_production': '2020',
            },
            {
                'x_plate_number': 'cd-56-78',
                'x_car_model': self.car_model_2.id,
                'x_car_color': self.car_color_2.id,
                'x_car_year_of_production': '2021',
            },
        ])
        
        self.assertEqual(records[0].x_plate_number, 'AB1234')
        self.assertEqual(records[1].x_plate_number, 'CD-5678')

    # ============== Test Basic Record Creation ==============

    def test_create_basic_record(self):
        """Test creating a basic car park request record."""
        record = self.env['x_car_park_request'].create({
            'x_plate_number': 'BASIC001',
            'x_car_model': self.car_model_1.id,
            'x_car_color': self.car_color_1.id,
            'x_car_year_of_production': '2020',
        })
        
        self.assertIsNotNone(record.id)
        self.assertEqual(record.x_plate_number, 'BASIC001')
        self.assertEqual(record.x_car_model.id, self.car_model_1.id)
        self.assertEqual(record.x_car_color.id, self.car_color_1.id)

    def test_create_with_all_fields(self):
        """Test creating a record with all available fields."""
        record = self.env['x_car_park_request'].create({
            'x_plate_number': 'FULL0001',
            'x_car_model': self.car_model_1.id,
            'x_car_color': self.car_color_1.id,
            'x_car_year_of_production': '2020',
            'x_car_remark': 'Test remark',
            'x_has_company_id': True,
            'x_has_driving_license': True,
            'x_has_car_registration': True,
            'x_car_park_permit_area': 'Area-A1',
        })
        
        self.assertEqual(record.x_car_remark, 'Test remark')
        self.assertTrue(record.x_has_company_id)
        self.assertTrue(record.x_has_driving_license)
        self.assertTrue(record.x_has_car_registration)
        self.assertEqual(record.x_car_park_permit_area, 'Area-A1')

    # ============== Test Record Updates ==============

    def test_update_plate_number_normalization(self):
        """Test that plate numbers are normalized on update."""
        record = self.env['x_car_park_request'].create({
            'x_plate_number': 'ORIG0001',
            'x_car_model': self.car_model_1.id,
            'x_car_color': self.car_color_1.id,
            'x_car_year_of_production': '2020',
        })
        
        record.write({'x_plate_number': 'new 12 34'})
        self.assertEqual(record.x_plate_number, 'NEW1234')

    def test_update_year_validation(self):
        """Test that year validation works on updates."""
        record = self.env['x_car_park_request'].create({
            'x_plate_number': 'UPDT0001',
            'x_car_model': self.car_model_1.id,
            'x_car_color': self.car_color_1.id,
            'x_car_year_of_production': '2020',
        })
        
        with self.assertRaises(ValidationError):
            record.write({'x_car_year_of_production': '1800'})

    # ============== Test Field Tracking ==============

    def test_field_tracking_enabled(self):
        """Test that tracking is enabled for important fields."""
        record = self.env['x_car_park_request'].create({
            'x_plate_number': 'TRCK0001',
            'x_car_model': self.car_model_1.id,
            'x_car_color': self.car_color_1.id,
            'x_car_year_of_production': '2020',
        })
        
        # Update a tracked field
        record.write({'x_plate_number': 'TRCK0002'})
        
        # Record should have messages in message thread
        self.assertIsNotNone(record.message_ids)
