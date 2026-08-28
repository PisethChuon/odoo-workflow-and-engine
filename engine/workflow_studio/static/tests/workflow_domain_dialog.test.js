import { describe, expect, test } from "@odoo/hoot";

import {
    buildWorkflowLineMatchExpression,
    buildWorkflowRuntimeClause,
    WorkflowStudioDomainDialog,
    WorkflowStudioRuntimeReferenceDialog,
} from "@workflow_studio/client_action/components/workflow_domain_dialog/workflow_domain_dialog";

describe("workflow line match expression builder", () => {
    test("builds runtime field presence clauses without a dynamic value", () => {
        expect(
            buildWorkflowRuntimeClause({
                fieldName: "x_leave_item_ids",
                operator: "is_set",
            })
        ).toBe('[("x_leave_item_ids", "!=", False)]');
        expect(
            buildWorkflowRuntimeClause({
                fieldName: "x_leave_item_ids",
                operator: "is_not_set",
            })
        ).toBe('[("x_leave_item_ids", "=", False)]');
    });

    test("keeps runtime comparison clauses unchanged", () => {
        expect(
            buildWorkflowRuntimeClause({
                fieldName: "request_owner_id",
                operator: "=",
                valueExpression: "uid",
            })
        ).toBe('[("request_owner_id", "=", uid)]');
    });

    test("combines explicit constant domains without producing invalid numeric leaves", () => {
        const dialog = Object.create(WorkflowStudioDomainDialog.prototype);
        const condition = "[('state', '=', 'waiting')]";

        expect(dialog._combineDomainExpressions(condition, "[(1, '=', 1)]", "and")).toBe(
            condition
        );
        expect(dialog._combineDomainExpressions(condition, "[(1, '=', 1)]", "or")).toBe(
            "[(1, '=', 1)]"
        );
        expect(dialog._combineDomainExpressions(condition, "[(0, '=', 1)]", "and")).toBe(
            "[(0, '=', 1)]"
        );
        expect(dialog._combineDomainExpressions(condition, "[(0, '=', 1)]", "or")).toBe(
            condition
        );
    });

    test("builds collection presence expressions", () => {
        expect(
            buildWorkflowLineMatchExpression({
                relation: "item_line_ids",
                mode: "has_lines",
            })
        ).toBe('wf_any("item_line_ids", True)');
        expect(
            buildWorkflowLineMatchExpression({
                relation: "item_line_ids",
                mode: "no_lines",
            })
        ).toBe('not wf_any("item_line_ids", True)');
    });

    test("builds field set and not-set expressions without a value", () => {
        expect(
            buildWorkflowLineMatchExpression({
                relation: "item_line_ids",
                mode: "any",
                path: "x_category_type_id",
                operator: "is_set",
            })
        ).toBe('wf_any("item_line_ids", [("x_category_type_id", "!=", False)])');
        expect(
            buildWorkflowLineMatchExpression({
                relation: "item_line_ids",
                mode: "all",
                path: "x_category_type_id",
                operator: "is_not_set",
            })
        ).toBe('wf_all("item_line_ids", [("x_category_type_id", "=", False)])');
    });

    test("keeps direct many2one and dotted related field paths valid", () => {
        expect(
            buildWorkflowLineMatchExpression({
                relation: "x_leave_item_ids",
                mode: "all",
                path: "x_clinic_id",
                operator: "=",
                valueLiteral: "1",
            })
        ).toBe('wf_all("x_leave_item_ids", [("x_clinic_id", "=", 1)])');
        expect(
            buildWorkflowLineMatchExpression({
                relation: "x_leave_item_ids",
                mode: "any",
                path: "x_clinic_id.name",
                operator: "ilike",
                valueLiteral: '"Main Clinic"',
            })
        ).toBe(
            'wf_any("x_leave_item_ids", [("x_clinic_id.name", "ilike", "Main Clinic")])'
        );
    });

    test("still requires a value for comparison operators", () => {
        expect(
            buildWorkflowLineMatchExpression({
                relation: "item_line_ids",
                mode: "any",
                path: "name",
                operator: "ilike",
            })
        ).toBe("");
    });

    test("runtime reference exposes verified approval and delegation symbols", () => {
        const dialog = Object.create(WorkflowStudioDomainDialog.prototype);
        dialog.props = {
            contextType: "assignment_users_routing",
            requestFields: [],
            resModel: "res.users",
            requestModel: "x_request",
        };
        dialog.requestFieldState = {rows: []};
        dialog.state = {
            runtimeReferenceCategory: "approvals",
            runtimeReferenceQuery: "",
            runtimeObject: "actual_user",
            runtimePath: "login",
        };

        const keys = dialog.runtimeVariableRows.map((row) => row.key);
        expect(keys).toInclude("all_approver_user_ids");
        expect(keys).toInclude("pending_approver_user_ids");
        expect(keys).toInclude("actual_user_id");
        expect(keys).toInclude("delegated_from_user_id");
        expect(dialog.runtimeReferenceRows.every((row) => row.category === "approvals")).toBe(true);
        expect(dialog.runtimeValueExpression).toBe("actual_user.login");
    });

    test("browse symbols opens the dedicated runtime reference dialog", () => {
        const dialog = Object.create(WorkflowStudioDomainDialog.prototype);
        const referenceState = {
            runtimeReferenceCategory: "recommended",
            runtimeReferenceQuery: "",
        };
        const rows = [{key: "uid", symbol: "uid", recommended: true}];
        const categoryOptions = [{value: "recommended", label: "Recommended"}];
        let dialogRequest = null;

        dialog.dialog = {
            add: (ComponentClass, props) => {
                dialogRequest = {ComponentClass, props};
            },
        };
        dialog.state = referenceState;
        Object.defineProperties(dialog, {
            runtimeVariableRows: {value: rows},
            runtimeReferenceCategoryOptions: {value: categoryOptions},
            showRuntimePathBuilder: {value: true},
        });

        dialog.onBrowseRuntimeReference();

        expect(dialogRequest.ComponentClass).toBe(
            WorkflowStudioRuntimeReferenceDialog
        );
        expect(dialogRequest.props.rows).toBe(rows);
        expect(dialogRequest.props.categoryOptions).toBe(categoryOptions);
        expect(dialogRequest.props.referenceState).toBe(referenceState);
        expect(dialogRequest.props.showRuntimePathBuilder).toBe(true);
    });

    test("dynamic value objects only offer fields supplied by runtime namespaces", () => {
        const dialog = Object.create(WorkflowStudioDomainDialog.prototype);
        dialog.props = {
            contextType: "request_scope_routing",
            requestFields: [],
            resModel: "x_request",
            requestModel: "x_request",
        };
        dialog.requestFieldState = {rows: []};
        dialog.state = {
            runtimeObject: "delegated_from_user",
            runtimePath: "",
        };

        expect(dialog.runtimeObjectOptions.map((option) => option.value)).toInclude("employee");
        expect(dialog.runtimeObjectOptions.map((option) => option.value)).toInclude("company");
        expect(dialog.runtimePathOptions.map((option) => option.value)).toInclude("approval_group_ids");
        expect(dialog.runtimePathOptions.map((option) => option.value)).not.toInclude("manager_id");
        expect(dialog.showRuntimeModelFieldSelector).toBe(false);
    });
});
