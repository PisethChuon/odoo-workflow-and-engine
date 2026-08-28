from enum import Enum
    
class RequestDataContext(Enum):
    MY_REQUESTS = 'MY_REQUESTS'
    MY_REVIEWS = 'MY_REVIEWS'
    MY_APPROVALS = 'MY_APPROVALS'
    ALL = 'ALL'

class EmployeeType(Enum):
    EMPLOYEE = 'EMPLOYEE'
    NON_EMPLOYEE = 'NON EMPLOYEE'

    @classmethod
    def selection(cls):
        return [
            (cls.EMPLOYEE.value, 'EMPLOYEE'),
            (cls.NON_EMPLOYEE.value, 'NON EMPLOYEE'),
        ]
