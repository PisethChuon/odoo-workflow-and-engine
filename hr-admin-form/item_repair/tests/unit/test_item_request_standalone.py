"""
Standalone unit tests for 'Item Request' model.
Can run without full Odoo setup.
These tests focus on the core business logic without database dependencies.
"""

import unittest


class MockItemRequest:
    """Mock implementation of ItemRequest for testing core logic."""
    
    @staticmethod
    def validate_serial_number(serial_number):
        """
        Validate serial number format.
        Serial number should not be empty if provided.
        """
        if serial_number:
            serial_number = serial_number.strip()
            if not serial_number:
                raise ValueError('Serial number cannot be empty or whitespace only.')
        return serial_number

    @staticmethod
    def validate_remark(remark):
        """
        Validate submitter remark.
        Remark should not be empty if provided.
        """
        if remark:
            remark = remark.strip()
            if not remark:
                raise ValueError('Remark cannot be empty or whitespace only.')
        return remark


class MockItemRequestType:
    """Mock implementation of ItemRequestType for testing core logic."""
    
    @staticmethod
    def validate_name(name):
        """
        Validate item type name.
        Name is required and cannot be empty.
        """
        if not name:
            raise ValueError('Item type name is required.')
        
        name = name.strip()
        if not name:
            raise ValueError('Item type name cannot be empty or whitespace only.')
        
        return name

    @staticmethod
    def validate_unique_name(name, existing_names):
        """
        Validate that item type name is unique.
        """
        name = name.strip().lower()
        existing_names_lower = [n.strip().lower() for n in existing_names]
        
        if name in existing_names_lower:
            raise ValueError(f'Item type with name "{name}" already exists.')
        
        return name


class TestSerialNumberValidation(unittest.TestCase):
    """Test serial number validation logic."""

    def test_valid_serial_number(self):
        """Test that valid serial numbers are accepted."""
        result = MockItemRequest.validate_serial_number('SN12345')
        self.assertEqual(result, 'SN12345')

    def test_serial_number_with_special_chars(self):
        """Test serial numbers with special characters."""
        result = MockItemRequest.validate_serial_number('SN-2024-001')
        self.assertEqual(result, 'SN-2024-001')

    def test_serial_number_trimmed(self):
        """Test that serial numbers are trimmed."""
        result = MockItemRequest.validate_serial_number('  SN12345  ')
        self.assertEqual(result, 'SN12345')

    def test_empty_serial_number_allowed(self):
        """Test that empty serial numbers are allowed (optional field)."""
        result = MockItemRequest.validate_serial_number('')
        self.assertEqual(result, '')

    def test_none_serial_number_allowed(self):
        """Test that None serial numbers are allowed (optional field)."""
        result = MockItemRequest.validate_serial_number(None)
        self.assertIsNone(result)

    def test_whitespace_only_serial_invalid(self):
        """Test that whitespace-only serial numbers are invalid."""
        with self.assertRaises(ValueError):
            MockItemRequest.validate_serial_number('   ')


class TestSubmitterRemarkValidation(unittest.TestCase):
    """Test submitter remark validation logic."""

    def test_valid_remark(self):
        """Test that valid remarks are accepted."""
        remark = "Device has screen damage on the right side"
        result = MockItemRequest.validate_remark(remark)
        self.assertEqual(result, remark)

    def test_remark_with_newlines(self):
        """Test remarks with newlines."""
        remark = "Line 1\nLine 2\nLine 3"
        result = MockItemRequest.validate_remark(remark)
        self.assertEqual(result, remark)

    def test_remark_trimmed(self):
        """Test that remarks are trimmed."""
        result = MockItemRequest.validate_remark('  Device damaged  ')
        self.assertEqual(result, 'Device damaged')

    def test_empty_remark_allowed(self):
        """Test that empty remarks are allowed (optional field)."""
        result = MockItemRequest.validate_remark('')
        self.assertEqual(result, '')

    def test_none_remark_allowed(self):
        """Test that None remarks are allowed (optional field)."""
        result = MockItemRequest.validate_remark(None)
        self.assertIsNone(result)

    def test_whitespace_only_remark_invalid(self):
        """Test that whitespace-only remarks are invalid."""
        with self.assertRaises(ValueError):
            MockItemRequest.validate_remark('   ')


class TestItemRequestTypeValidation(unittest.TestCase):
    """Test item request type validation logic."""

    def test_valid_item_type_name(self):
        """Test that valid item type names are accepted."""
        result = MockItemRequestType.validate_name('Walkie Talkie')
        self.assertEqual(result, 'Walkie Talkie')

    def test_item_type_name_trimmed(self):
        """Test that item type names are trimmed."""
        result = MockItemRequestType.validate_name('  Phone Accessory  ')
        self.assertEqual(result, 'Phone Accessory')

    def test_empty_item_type_name_invalid(self):
        """Test that empty item type names are invalid."""
        with self.assertRaises(ValueError):
            MockItemRequestType.validate_name('')

    def test_whitespace_only_name_invalid(self):
        """Test that whitespace-only names are invalid."""
        with self.assertRaises(ValueError):
            MockItemRequestType.validate_name('   ')

    def test_none_name_invalid(self):
        """Test that None names are invalid."""
        with self.assertRaises(ValueError):
            MockItemRequestType.validate_name(None)

    def test_unique_name_validation_pass(self):
        """Test that unique names pass validation."""
        existing_names = ['Walkie Talkie', 'Phone Accessory']
        result = MockItemRequestType.validate_unique_name('Laptop', existing_names)
        self.assertEqual(result, 'laptop')

    def test_unique_name_validation_fail(self):
        """Test that duplicate names fail validation."""
        existing_names = ['Walkie Talkie', 'Phone Accessory']
        with self.assertRaises(ValueError):
            MockItemRequestType.validate_unique_name('Walkie Talkie', existing_names)

    def test_unique_name_case_insensitive(self):
        """Test that name uniqueness is case-insensitive."""
        existing_names = ['Walkie Talkie', 'Phone Accessory']
        with self.assertRaises(ValueError):
            MockItemRequestType.validate_unique_name('walkie talkie', existing_names)

    def test_unique_name_with_whitespace(self):
        """Test that name uniqueness checks trimmed names."""
        existing_names = ['Walkie Talkie', 'Phone Accessory']
        with self.assertRaises(ValueError):
            MockItemRequestType.validate_unique_name('  Walkie Talkie  ', existing_names)


class TestDepartmentAutoAssignment(unittest.TestCase):
    """Test department auto-assignment logic."""

    def test_get_department_from_employee(self):
        """Test getting department from employee."""
        # Mock employee with department
        class MockEmployee:
            def __init__(self, dept_id):
                self.department_id = dept_id

        class MockUser:
            def __init__(self, employee):
                self.employee_id = employee

        employee = MockEmployee('dept_it')
        user = MockUser(employee)

        # Simulate getting department
        if user.employee_id:
            result = user.employee_id.department_id
            self.assertEqual(result, 'dept_it')

    def test_get_department_no_employee(self):
        """Test getting department when user has no employee."""
        class MockUser:
            def __init__(self):
                self.employee_id = None

        user = MockUser()

        # Simulate getting department
        result = None
        if user.employee_id:
            result = user.employee_id.department_id

        self.assertIsNone(result)

    def test_get_department_employee_no_dept(self):
        """Test getting department when employee has no department."""
        class MockEmployee:
            def __init__(self):
                self.department_id = None

        class MockUser:
            def __init__(self, employee):
                self.employee_id = employee

        employee = MockEmployee()
        user = MockUser(employee)

        # Simulate getting department
        result = None
        if user.employee_id:
            result = user.employee_id.department_id

        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
