import unittest


class MockDepartment:
    """Simple department mock with an identifier."""

    def __init__(self, dept_id):
        self.id = dept_id


class MockEmployee:
    """Employee mock with optional department."""

    def __init__(self, department=None):
        self.department_id = department


class MockUser:
    """User mock with optional employee."""

    def __init__(self, employee=None):
        self.employee_id = employee


class MockRequestDocument:
    """Request document mock with document type and personal information."""

    def __init__(self, document_type=None, personal_information=None, reason=None, requester=None):
        self.x_request_document_type = document_type
        self.x_request_document_personal_information = personal_information
        self.x_request_document_reason = reason
        self.x_requester_id = requester
        self.x_charge_to_department = None

    def validate_document_type(self):
        """Validate that document type is one of the allowed types."""
        allowed_types = ['income_statement', 'certificate_of_employment']
        return self.x_request_document_type in allowed_types if self.x_request_document_type else False

    def compute_requester_department(self):
        """Compute the department of the requester based on their employee info."""
        if self.x_requester_id and self.x_requester_id.employee_id:
            employee = self.x_requester_id.employee_id
            self.x_charge_to_department = employee.department_id if employee else None
        else:
            self.x_charge_to_department = None

    def is_valid_request(self):
        """Check if the request has all required information."""
        return (
            self.validate_document_type()
            and self.x_request_document_personal_information
            and self.x_request_document_reason
            and self.x_requester_id
        )


class TestRequestDocumentTypeValidation(unittest.TestCase):
    """Test document type validation for request documents."""

    def test_valid_income_statement_type(self):
        """Income statement is a valid document type."""
        request_doc = MockRequestDocument(document_type='income_statement')

        self.assertTrue(request_doc.validate_document_type())

    def test_valid_certificate_of_employment_type(self):
        """Certificate of employment is a valid document type."""
        request_doc = MockRequestDocument(document_type='certificate_of_employment')

        self.assertTrue(request_doc.validate_document_type())

    def test_invalid_document_type(self):
        """Invalid document type fails validation."""
        request_doc = MockRequestDocument(document_type='invalid_type')

        self.assertFalse(request_doc.validate_document_type())

    def test_none_document_type(self):
        """None document type fails validation."""
        request_doc = MockRequestDocument(document_type=None)

        self.assertFalse(request_doc.validate_document_type())

    def test_empty_string_document_type(self):
        """Empty string document type fails validation."""
        request_doc = MockRequestDocument(document_type='')

        self.assertFalse(request_doc.validate_document_type())


class TestRequestDocumentRequesterDepartment(unittest.TestCase):
    """Test requester department auto-fill logic for request documents."""

    def test_department_auto_fill_from_requester(self):
        """Department is taken from the requester's employee."""
        dept_hr = MockDepartment('dept_hr')
        employee = MockEmployee(dept_hr)
        user = MockUser(employee)
        request_doc = MockRequestDocument(requester=user)

        request_doc.compute_requester_department()

        self.assertEqual(request_doc.x_charge_to_department, dept_hr)

    def test_department_updates_when_requester_changes(self):
        """Department updates when the requester changes."""
        dept_hr = MockDepartment('dept_hr')
        dept_finance = MockDepartment('dept_finance')
        user_hr = MockUser(MockEmployee(dept_hr))
        user_finance = MockUser(MockEmployee(dept_finance))
        request_doc = MockRequestDocument(requester=user_hr)

        request_doc.compute_requester_department()
        self.assertEqual(request_doc.x_charge_to_department, dept_hr)

        request_doc.x_requester_id = user_finance
        request_doc.compute_requester_department()
        self.assertEqual(request_doc.x_charge_to_department, dept_finance)

    def test_department_none_when_no_requester(self):
        """Department is empty when no requester is set."""
        request_doc = MockRequestDocument(requester=None)

        request_doc.compute_requester_department()

        self.assertIsNone(request_doc.x_charge_to_department)

    def test_department_none_when_user_has_no_employee(self):
        """Department is empty if user has no employee linked."""
        user = MockUser(None)
        request_doc = MockRequestDocument(requester=user)

        request_doc.compute_requester_department()

        self.assertIsNone(request_doc.x_charge_to_department)

    def test_department_none_when_employee_has_no_department(self):
        """Department is empty if employee has no department."""
        user = MockUser(MockEmployee(None))
        request_doc = MockRequestDocument(requester=user)

        request_doc.compute_requester_department()

        self.assertIsNone(request_doc.x_charge_to_department)


class TestRequestDocumentValidation(unittest.TestCase):
    """Test overall validation of request documents."""

    def test_valid_request_document(self):
        """A request with all required fields is valid."""
        dept_hr = MockDepartment('dept_hr')
        employee = MockEmployee(dept_hr)
        user = MockUser(employee)
        request_doc = MockRequestDocument(
            document_type='income_statement',
            personal_information='Employee Name: John Doe',
            reason='Loan application',
            requester=user
        )

        self.assertTrue(request_doc.is_valid_request())

    def test_invalid_request_missing_document_type(self):
        """Request without document type is invalid."""
        dept_hr = MockDepartment('dept_hr')
        employee = MockEmployee(dept_hr)
        user = MockUser(employee)
        request_doc = MockRequestDocument(
            document_type=None,
            personal_information='Employee Name: John Doe',
            reason='Loan application',
            requester=user
        )

        self.assertFalse(request_doc.is_valid_request())

    def test_invalid_request_missing_personal_information(self):
        """Request without personal information is invalid."""
        dept_hr = MockDepartment('dept_hr')
        employee = MockEmployee(dept_hr)
        user = MockUser(employee)
        request_doc = MockRequestDocument(
            document_type='income_statement',
            personal_information=None,
            reason='Loan application',
            requester=user
        )

        self.assertFalse(request_doc.is_valid_request())

    def test_invalid_request_missing_reason(self):
        """Request without reason is invalid."""
        dept_hr = MockDepartment('dept_hr')
        employee = MockEmployee(dept_hr)
        user = MockUser(employee)
        request_doc = MockRequestDocument(
            document_type='income_statement',
            personal_information='Employee Name: John Doe',
            reason=None,
            requester=user
        )

        self.assertFalse(request_doc.is_valid_request())

    def test_invalid_request_missing_requester(self):
        """Request without requester is invalid."""
        request_doc = MockRequestDocument(
            document_type='income_statement',
            personal_information='Employee Name: John Doe',
            reason='Loan application',
            requester=None
        )

        self.assertFalse(request_doc.is_valid_request())

    def test_invalid_request_with_invalid_document_type(self):
        """Request with invalid document type is invalid."""
        dept_hr = MockDepartment('dept_hr')
        employee = MockEmployee(dept_hr)
        user = MockUser(employee)
        request_doc = MockRequestDocument(
            document_type='invalid_type',
            personal_information='Employee Name: John Doe',
            reason='Loan application',
            requester=user
        )

        self.assertFalse(request_doc.is_valid_request())


if __name__ == '__main__':
    unittest.main()
