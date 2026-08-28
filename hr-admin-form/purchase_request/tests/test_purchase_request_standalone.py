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


class MockPurchaseRequest:
    """Purchase request mock with a request owner."""

    def __init__(self, request_owner=None):
        self.request_owner_id = request_owner


class MockPurchaseItem:
    """Purchase item mock that computes charge-to department."""

    def __init__(self, purchase_request=None):
        self.x_purchase_request_id = purchase_request
        self.x_charge_to_depat = None

    def compute_charge_to_department(self):
        """Compute charge-to department based on request owner."""
        if self.x_purchase_request_id and self.x_purchase_request_id.request_owner_id:
            employee = self.x_purchase_request_id.request_owner_id.employee_id
            self.x_charge_to_depat = employee.department_id if employee else None
        else:
            self.x_charge_to_depat = None


class TestPurchaseItemDepartmentAutoFill(unittest.TestCase):
    """Test department auto-fill logic for purchase items."""

    def test_department_auto_fill_from_request_owner(self):
        """Department is taken from the request owner's employee."""
        dept_it = MockDepartment('dept_it')
        employee = MockEmployee(dept_it)
        user = MockUser(employee)
        request = MockPurchaseRequest(user)
        item = MockPurchaseItem(request)

        item.compute_charge_to_department()

        self.assertEqual(item.x_charge_to_depat, dept_it)

    def test_department_updates_when_request_owner_changes(self):
        """Department updates when the request owner changes."""
        dept_it = MockDepartment('dept_it')
        dept_sales = MockDepartment('dept_sales')
        user_it = MockUser(MockEmployee(dept_it))
        user_sales = MockUser(MockEmployee(dept_sales))
        request = MockPurchaseRequest(user_it)
        item = MockPurchaseItem(request)

        item.compute_charge_to_department()
        self.assertEqual(item.x_charge_to_depat, dept_it)

        request.request_owner_id = user_sales
        item.compute_charge_to_department()
        self.assertEqual(item.x_charge_to_depat, dept_sales)

    def test_department_none_when_no_request_owner(self):
        """Department is empty when no request owner is set."""
        request = MockPurchaseRequest(None)
        item = MockPurchaseItem(request)

        item.compute_charge_to_department()

        self.assertIsNone(item.x_charge_to_depat)

    def test_department_none_when_no_request(self):
        """Department is empty when no purchase request exists."""
        item = MockPurchaseItem(None)

        item.compute_charge_to_department()

        self.assertIsNone(item.x_charge_to_depat)

    def test_department_none_when_user_has_no_employee(self):
        """Department is empty if user has no employee linked."""
        user = MockUser(None)
        request = MockPurchaseRequest(user)
        item = MockPurchaseItem(request)

        item.compute_charge_to_department()

        self.assertIsNone(item.x_charge_to_depat)

    def test_department_none_when_employee_has_no_department(self):
        """Department is empty if employee has no department."""
        user = MockUser(MockEmployee(None))
        request = MockPurchaseRequest(user)
        item = MockPurchaseItem(request)

        item.compute_charge_to_department()

        self.assertIsNone(item.x_charge_to_depat)


if __name__ == '__main__':
    unittest.main()
