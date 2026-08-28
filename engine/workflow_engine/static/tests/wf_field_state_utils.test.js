import { describe, expect, test } from "@odoo/hoot";

import {
    applyWorkflowFieldStateMap,
    applyWorkflowRuntimeFieldLists,
    serializeWorkflowSnapshot,
} from "@workflow_engine/web/utils/wf_field_state_utils";

describe.current.tags("desktop");

test("serializeWorkflowSnapshot normalizes unsaved many2one resId values", () => {
    const snapshot = serializeWorkflowSnapshot({
        data: {
            x_it_session_id: {
                resId: 2,
                displayName: "INFRASTRUCTURE",
            },
        },
    });

    expect(snapshot).toEqual({
        x_it_session_id: {
            id: 2,
            display_name: "INFRASTRUCTURE",
        },
    });
});

test("applyWorkflowRuntimeFieldLists updates legacy helper fields for wrapper modifiers", () => {
    let evalContextReset = false;
    let notified = false;
    const record = {
        data: {
            required_fields: [],
            readonly_fields: ["x_old"],
            invisible_fields: [],
        },
        _setEvalContext() {
            evalContextReset = true;
        },
        model: {
            notify() {
                notified = true;
            },
        },
    };

    const changed = applyWorkflowRuntimeFieldLists(record, {
        required_fields: ["x_blood_pressure"],
        readonly_fields: ["x_weight"],
        invisible_fields: ["x_weight"],
    });

    expect(changed).toBe(true);
    expect(record.data.required_fields).toEqual(["x_blood_pressure"]);
    expect(record.data.readonly_fields).toEqual(["x_weight"]);
    expect(record.data.invisible_fields).toEqual(["x_weight"]);
    expect(evalContextReset).toBe(true);
    expect(notified).toBe(true);
});

test("applyWorkflowRuntimeFieldLists marks unchanged lists as applied after form reload", () => {
    let evalContextReset = false;
    let notified = false;
    const record = {
        data: {
            required_fields: ["x_work_shift_id"],
            readonly_fields: [],
            invisible_fields: [],
        },
        _setEvalContext() {
            evalContextReset = true;
        },
        model: {
            notify() {
                notified = true;
            },
        },
    };

    const changed = applyWorkflowRuntimeFieldLists(record, {
        required_fields: ["x_work_shift_id"],
        readonly_fields: [],
        invisible_fields: [],
    });

    expect(changed).toBe(true);
    expect(record.__wfRuntimeAppliedFieldLists.invisible_fields).toEqual([]);
    expect(record.data.invisible_fields).toEqual([]);
    expect(evalContextReset).toBe(true);
    expect(notified).toBe(true);
});

test("applyWorkflowRuntimeFieldLists normalizes string helper lists to arrays", () => {
    const record = {
        data: {
            required_fields: "x_work_shift_id",
            readonly_fields: "",
            invisible_fields: "",
        },
    };

    const changed = applyWorkflowRuntimeFieldLists(record, {
        required_fields: ["x_work_shift_id"],
        readonly_fields: [],
        invisible_fields: [],
    });

    expect(changed).toBe(true);
    expect(record.data.required_fields).toEqual(["x_work_shift_id"]);
    expect(record.data.readonly_fields).toEqual([]);
    expect(record.data.invisible_fields).toEqual([]);
});

test("applyWorkflowRuntimeFieldLists keeps already applied equal lists as no-op", () => {
    let notified = false;
    const record = {
        __wfRuntimeAppliedFieldLists: {
            required_fields: ["x_work_shift_id"],
            readonly_fields: [],
            invisible_fields: [],
        },
        data: {
            required_fields: ["x_work_shift_id"],
            readonly_fields: [],
            invisible_fields: [],
        },
        model: {
            notify() {
                notified = true;
            },
        },
    };

    const changed = applyWorkflowRuntimeFieldLists(record, {
        required_fields: ["x_work_shift_id"],
        readonly_fields: [],
        invisible_fields: [],
    });

    expect(changed).toBe(false);
    expect(notified).toBe(false);
});

test("applyWorkflowFieldStateMap normalizes required readonly invisible active field modifiers", () => {
    let notifications = 0;
    const record = {
        activeFields: {
            x_name: { invisible: "False", readonly: "False", required: "False" },
            x_hidden: { invisible: "False", readonly: "False", required: "False" },
            x_readonly: { invisible: "False", readonly: "False", required: "False" },
        },
        model: {
            notify() {
                notifications += 1;
            },
        },
    };

    const changed = applyWorkflowFieldStateMap(record, {
        x_name: { invisible: false, readonly: false, required: true },
        x_hidden: { invisible: true, readonly: false, required: true },
        x_readonly: { invisible: false, readonly: true, required: true },
    });

    expect(changed).toBe(true);
    expect(record.activeFields.x_name).toEqual({
        invisible: "False",
        readonly: "False",
        required: "True",
        __wf_runtime_applied: true,
    });
    expect(record.activeFields.x_hidden).toEqual({
        invisible: "True",
        readonly: "True",
        required: "False",
        __wf_runtime_applied: true,
    });
    expect(record.activeFields.x_readonly).toEqual({
        invisible: "False",
        readonly: "True",
        required: "False",
        __wf_runtime_applied: true,
    });
    expect(notifications).toBe(1);
});

test("applyWorkflowFieldStateMap restores arch defaults when runtime stops managing a field", () => {
    let notifications = 0;
    const record = {
        activeFields: {
            x_dynamic: { invisible: "False", readonly: "False", required: "False" },
        },
        model: {
            notify() {
                notifications += 1;
            },
        },
    };

    expect(
        applyWorkflowFieldStateMap(record, {
            x_dynamic: { invisible: true, readonly: false, required: true },
        })
    ).toBe(true);
    expect(record.activeFields.x_dynamic.invisible).toBe("True");
    expect(record.activeFields.x_dynamic.readonly).toBe("True");
    expect(record.activeFields.x_dynamic.required).toBe("False");

    expect(applyWorkflowFieldStateMap(record, {})).toBe(true);
    expect(record.activeFields.x_dynamic).toEqual({
        invisible: "False",
        readonly: "False",
        required: "False",
    });
    expect(record.__wfRuntimeManagedFields).toEqual([]);
    expect(notifications).toBe(2);
});
