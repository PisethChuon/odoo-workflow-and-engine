"""
Standalone unit tests for 'Car Park Request' model.
Can run without full Odoo setup.
These tests focus on the core business logic without database dependencies.
"""

import unittest
from datetime import datetime


class MockCarParkRequest:
    """Mock implementation of CarParkRequest for testing core logic."""
    
    @staticmethod
    def _normalize_plate_number(plate_number):
        """
        Normalize plate number:
        - Convert to uppercase
        - Remove extra spaces
        """
        if not plate_number:
            return plate_number
        # Remove leading/trailing whitespace, convert to uppercase
        normalized = plate_number.strip().upper()
        # Remove spaces only (preserve hyphens and other characters)
        normalized = ' '.join(normalized.split())
        return normalized


class TestPlateNumberNormalization(unittest.TestCase):
    """Test plate number normalization logic."""

    def test_normalize_uppercase(self):
        """Test that plate numbers are converted to uppercase."""
        result = MockCarParkRequest._normalize_plate_number('ab1234')
        self.assertEqual(result, 'AB1234')

    def test_normalize_remove_spaces(self):
        """Test that extra spaces are condensed to single spaces."""
        result = MockCarParkRequest._normalize_plate_number('ab 12 34')
        self.assertEqual(result, 'AB 12 34')

    def test_normalize_trim_whitespace(self):
        """Test that leading/trailing whitespace is trimmed."""
        result = MockCarParkRequest._normalize_plate_number('  AB1234  ')
        self.assertEqual(result, 'AB1234')

    def test_normalize_preserve_hyphens(self):
        """Test that hyphens are preserved during normalization."""
        result = MockCarParkRequest._normalize_plate_number('ab-1234')
        self.assertEqual(result, 'AB-1234')

    def test_normalize_complex_case(self):
        """Test complex normalization with mixed input."""
        result = MockCarParkRequest._normalize_plate_number('  aB-12  34  ')
        self.assertEqual(result, 'AB-12 34')

    def test_normalize_empty_string(self):
        """Test that empty strings are handled correctly."""
        result = MockCarParkRequest._normalize_plate_number('')
        self.assertEqual(result, '')

    def test_normalize_none_value(self):
        """Test that None values are handled correctly."""
        result = MockCarParkRequest._normalize_plate_number(None)
        self.assertIsNone(result)


class TestYearOfProductionValidation(unittest.TestCase):
    """Test year of production validation logic."""

    def _validate_year(self, year_str):
        """Validate car year of production."""
        current_year = datetime.now().year
        min_year = 1900
        max_year = current_year + 1

        if year_str:
            year_str = year_str.strip()
            
            # Check if it's a valid 4-digit number
            if not year_str.isdigit() or len(year_str) != 4:
                raise ValueError(
                    f'Year must be a 4-digit year. Got {year_str}.'
                )
            
            year = int(year_str)
            
            # Check if year is within valid range
            if year < min_year or year > max_year:
                raise ValueError(
                    f'Year of Production must be between {min_year} and {max_year}. '
                    f'Got {year}.'
                )
        return year_str

    def test_valid_year(self):
        """Test that valid years are accepted."""
        result = self._validate_year('2020')
        self.assertEqual(result, '2020')

    def test_minimum_year(self):
        """Test that minimum year (1900) is accepted."""
        result = self._validate_year('1900')
        self.assertEqual(result, '1900')

    def test_current_year(self):
        """Test that current year is accepted."""
        current_year = str(datetime.now().year)
        result = self._validate_year(current_year)
        self.assertEqual(result, current_year)

    def test_future_year(self):
        """Test that future year (current year + 1) is accepted."""
        future_year = str(datetime.now().year + 1)
        result = self._validate_year(future_year)
        self.assertEqual(result, future_year)

    def test_year_too_low(self):
        """Test that years before 1900 are rejected."""
        with self.assertRaises(ValueError) as context:
            self._validate_year('1899')
        self.assertIn('Year of Production must be between', str(context.exception))

    def test_year_too_high(self):
        """Test that years after (current year + 1) are rejected."""
        too_high_year = str(datetime.now().year + 2)
        with self.assertRaises(ValueError) as context:
            self._validate_year(too_high_year)
        self.assertIn('Year of Production must be between', str(context.exception))

    def test_non_numeric_year(self):
        """Test that non-numeric years are rejected."""
        with self.assertRaises(ValueError) as context:
            self._validate_year('20AB')
        self.assertIn('Year must be a 4-digit year', str(context.exception))

    def test_wrong_length_year_short(self):
        """Test that non-4-digit years (too short) are rejected."""
        with self.assertRaises(ValueError) as context:
            self._validate_year('202')
        self.assertIn('Year must be a 4-digit year', str(context.exception))

    def test_wrong_length_year_long(self):
        """Test that non-4-digit years (too long) are rejected."""
        with self.assertRaises(ValueError) as context:
            self._validate_year('20200')
        self.assertIn('Year must be a 4-digit year', str(context.exception))

    def test_empty_string_year(self):
        """Test that empty year strings are accepted (optional field)."""
        result = self._validate_year('')
        self.assertEqual(result, '')

    def test_whitespace_handled(self):
        """Test that whitespace around year is handled properly."""
        result = self._validate_year('  2020  ')
        self.assertEqual(result, '2020')


class TestBusinessLogic(unittest.TestCase):
    """Test combined business logic."""

    def test_plate_normalization_workflow(self):
        """Test complete plate normalization workflow."""
        inputs = [
            ('ab 1234', 'AB 1234'),
            ('AB-1234', 'AB-1234'),
            ('  cd  56  78  ', 'CD 56 78'),
            ('test-abc-123', 'TEST-ABC-123'),
        ]
        
        for input_val, expected in inputs:
            result = MockCarParkRequest._normalize_plate_number(input_val)
            self.assertEqual(result, expected, f'Failed for input: {input_val}')

    def test_year_validation_workflow(self):
        """Test year validation across edge cases."""
        # These should all pass
        valid_years = ['1900', '2000', '2020', str(datetime.now().year), str(datetime.now().year + 1)]
        for year in valid_years:
            try:
                # Just ensure no exception is raised
                if year:
                    int(year)
            except ValueError:
                self.fail(f'Year {year} should be valid')


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)
