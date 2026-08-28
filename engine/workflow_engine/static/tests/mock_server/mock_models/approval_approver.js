import { models } from "@web/../tests/web_test_helpers";

export class ApprovalApprover extends models.ServerModel {
    _name = "workflow.approval.approver";

    action_approve() {
        return true;
    }

    action_refuse() {
        return true;
    }
}
