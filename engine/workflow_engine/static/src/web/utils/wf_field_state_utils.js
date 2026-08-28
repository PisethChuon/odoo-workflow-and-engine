/** @odoo-module **/

function toTrueFalseExpr(value) {
    return value ? "True" : "False";
}

function toBooleanExpr(value) {
    return value === true || value === "True" || value === "true" || value === 1 || value === "1";
}

const RUNTIME_FIELD_LIST_KEYS = ["required_fields", "readonly_fields", "invisible_fields"];
export const WORKFLOW_TECHNICAL_X2MANY_FIELDS = new Set([
    "approver_ids",
    "owner_user_ids",
    "to_approve_user_ids",
    "to_approve_res_user_ids",
    "already_approved_user_ids",
    "activity_history",
    "attachment_ids",
    "file_attachment_ids",
    "child_ids",
    "task_instance_ids",
    "visibility_scope_ids",
    "task_event_ids",
    "department_payload_ids",
    "automation_instance_ids",
    "approver_decisions_ids",
]);

export function isWorkflowTechnicalX2ManyField(fieldName) {
    return WORKFLOW_TECHNICAL_X2MANY_FIELDS.has(fieldName);
}

function isPlainObject(value) {
    if (!value || typeof value !== "object") {
        return false;
    }
    const proto = Object.getPrototypeOf(value);
    return proto === Object.prototype || proto === null;
}

export function isWorkflowManagedJsClass(jsClass) {
    if (typeof jsClass !== "string") {
        return false;
    }
    const tokens = jsClass
        .split(/\s+/)
        .map((token) => token.trim())
        .filter(Boolean);
    return tokens.includes("wf_form") || tokens.includes("create_approval_request");
}

export function isWorkflowStudioEditorActive() {
    if (typeof document === "undefined" || !document?.querySelector) {
        return false;
    }
    // Guard only when Studio editor is actually active.
    // Avoid broad selectors that can match non-editor containers and disable
    // wf_form runtime behavior for normal users.
    const bodyHasStudioFlag = document.body?.classList?.contains("o_studio");
    if (!bodyHasStudioFlag) {
        return false;
    }
    return Boolean(document.querySelector(".o_web_studio_editor, .o_web_studio_editor_manager"));
}

function normalizeSnapshotValue(value, depth = 0) {
    if (depth > 2) {
        return undefined;
    }
    if (value === undefined || typeof value === "function") {
        return undefined;
    }
    if (value === null || typeof value === "boolean" || typeof value === "number" || typeof value === "string") {
        return value;
    }
    if (Array.isArray(value)) {
        if (
            value.length === 2 &&
            typeof value[0] === "number" &&
            (typeof value[1] === "string" || value[1] === false || value[1] === null || value[1] === undefined)
        ) {
            return { id: value[0], display_name: value[1] || "" };
        }
        const normalizedItems = value
            .map((item) => normalizeSnapshotValue(item, depth + 1))
            .filter((item) => item !== undefined);
        return normalizedItems;
    }
    if (
        value &&
        typeof value === "object" &&
        "resId" in value &&
        typeof value.resId === "number"
    ) {
        const normalized = {
            id: value.resId,
            display_name: value.displayName || value.display_name || "",
        };
        if (isPlainObject(value.data)) {
            for (const [key, child] of Object.entries(value.data)) {
                const childValue = normalizeSnapshotValue(child, depth + 1);
                if (childValue !== undefined) {
                    normalized[key] = childValue;
                }
            }
        }
        return normalized;
    }
    if (value && typeof value === "object" && "id" in value && typeof value.id === "number") {
        const normalized = {
            id: value.id,
            display_name: value.display_name || value.displayName || "",
        };
        for (const [key, child] of Object.entries(value)) {
            if (key === "id" || key === "display_name" || key === "displayName") {
                continue;
            }
            const childValue = normalizeSnapshotValue(child, depth + 1);
            if (childValue !== undefined) {
                normalized[key] = childValue;
            }
        }
        return normalized;
    }
    if (!isPlainObject(value)) {
        return undefined;
    }
    const normalized = {};
    for (const [key, child] of Object.entries(value)) {
        const childValue = normalizeSnapshotValue(child, depth + 1);
        if (childValue !== undefined) {
            normalized[key] = childValue;
        }
    }
    return normalized;
}

export function serializeWorkflowSnapshot(record) {
    const snapshot = {};
    if (!record?.data) {
        return snapshot;
    }
    for (const [fieldName, value] of Object.entries(record.data)) {
        const normalized = normalizeSnapshotValue(value);
        if (normalized !== undefined) {
            snapshot[fieldName] = normalized;
        }
    }
    return snapshot;
}

export function normalizeRuntimeFieldList(value) {
    if (Array.isArray(value)) {
        return [...new Set(value.filter(Boolean).map((item) => String(item)))].sort();
    }
    if (typeof value === "string") {
        const text = value.trim();
        if (!text) {
            return [];
        }
        try {
            const parsed = JSON.parse(text);
            if (Array.isArray(parsed)) {
                return normalizeRuntimeFieldList(parsed);
            }
        } catch {
            // Keep compatibility with older comma-separated helper values.
        }
        return [...new Set(text.split(",").map((item) => item.trim()).filter(Boolean))].sort();
    }
    return [];
}

export function applyWorkflowRuntimeFieldLists(record, payload) {
    if (!record?.data || !payload || typeof payload !== "object") {
        return false;
    }
    let hasChanges = false;
    const hadAppliedLists = Boolean(record.__wfRuntimeAppliedFieldLists);
    const appliedLists = {};
    for (const key of RUNTIME_FIELD_LIST_KEYS) {
        if (!(key in payload) && !(key in record.data)) {
            continue;
        }
        const nextValue = normalizeRuntimeFieldList(payload[key]);
        appliedLists[key] = nextValue;
        const currentValue = normalizeRuntimeFieldList(record.data[key]);
        const isCurrentArray = Array.isArray(record.data[key]);
        if (JSON.stringify(currentValue) === JSON.stringify(nextValue) && isCurrentArray) {
            continue;
        }
        record.data[key] = nextValue;
        hasChanges = true;
    }
    record.__wfRuntimeAppliedFieldLists = {
        ...(record.__wfRuntimeAppliedFieldLists || {}),
        ...appliedLists,
    };
    // First runtime application must still notify, even when values match the reloaded record.
    if (!hadAppliedLists && Object.keys(appliedLists).length) {
        hasChanges = true;
    }
    if (hasChanges && typeof record._setEvalContext === "function") {
        record._setEvalContext();
    }
    if (hasChanges && typeof record.model?.notify === "function") {
        record.model.notify();
    }
    return hasChanges;
}

export function applyWorkflowFieldStateMap(record, fieldStateMap) {
    if (!record?.activeFields || !fieldStateMap || typeof fieldStateMap !== "object") {
        return false;
    }
    let hasChanges = false;
    const archDefaults = record.__wfArchFieldDefaults || {};
    record.__wfArchFieldDefaults = archDefaults;
    const previousManagedFields = new Set(record.__wfRuntimeManagedFields || []);
    const nextManagedFields = new Set();
    const nextAppliedFieldStates = {};

    for (const [fieldName, state] of Object.entries(fieldStateMap)) {
        if (isWorkflowTechnicalX2ManyField(fieldName)) {
            continue;
        }
        const activeField = record.activeFields[fieldName];
        if (!activeField) {
            continue;
        }
        if (!archDefaults[fieldName]) {
            archDefaults[fieldName] = {
                invisible: activeField.invisible,
                readonly: activeField.readonly,
                required: activeField.required,
            };
        }
        nextManagedFields.add(fieldName);
        // Meta Field runtime state is the single workflow authority.
        const nextInvisibleBool = Boolean(state?.invisible);
        const nextReadonlyBool = Boolean(state?.readonly) || nextInvisibleBool;
        const nextRequiredBool = Boolean(state?.required) && !nextInvisibleBool && !nextReadonlyBool;
        const nextInvisible = toTrueFalseExpr(nextInvisibleBool);
        const nextReadonly = toTrueFalseExpr(nextReadonlyBool);
        const nextRequired = toTrueFalseExpr(nextRequiredBool);
        if (
            activeField.invisible !== nextInvisible ||
            activeField.readonly !== nextReadonly ||
            activeField.required !== nextRequired
        ) {
            hasChanges = true;
        }
        activeField.invisible = nextInvisible;
        activeField.readonly = nextReadonly;
        activeField.required = nextRequired;
        activeField.__wf_runtime_applied = true;
        nextAppliedFieldStates[fieldName] = {
            invisible: nextInvisible,
            readonly: nextReadonly,
            required: nextRequired,
        };
    }

    // Fields no longer present in runtime payload should fall back to arch defaults.
    // We do this by clearing the runtime-applied marker; field compilation then uses
    // static fieldInfo again for those fields.
    for (const fieldName of previousManagedFields) {
        if (nextManagedFields.has(fieldName)) {
            continue;
        }
        const activeField = record.activeFields[fieldName];
        if (activeField && activeField.__wf_runtime_applied) {
            const baseModifiers = archDefaults[fieldName];
            if (baseModifiers) {
                if (
                    activeField.invisible !== baseModifiers.invisible ||
                    activeField.readonly !== baseModifiers.readonly ||
                    activeField.required !== baseModifiers.required
                ) {
                    hasChanges = true;
                }
                activeField.invisible = baseModifiers.invisible;
                activeField.readonly = baseModifiers.readonly;
                activeField.required = baseModifiers.required;
            }
            delete activeField.__wf_runtime_applied;
        }
    }
    record.__wfRuntimeManagedFields = Array.from(nextManagedFields);
    record.__wfRuntimeAppliedFieldStates = nextAppliedFieldStates;

    if (hasChanges && typeof record.model?.notify === "function") {
        record.model.notify();
    }
    return hasChanges;
}

function normalizeNodeStateValue(value) {
    return toTrueFalseExpr(Boolean(value));
}

export function applyWorkflowNodeStateMap(record, nodeStateMap) {
    if (!record || !nodeStateMap || typeof nodeStateMap !== "object") {
        return false;
    }
    const nextNodeStates = {};
    for (const [nodeKey, state] of Object.entries(nodeStateMap)) {
        if (!nodeKey) {
            continue;
        }
        nextNodeStates[nodeKey] = {
            invisible: normalizeNodeStateValue(state?.invisible),
        };
    }

    const previous = record.__wfNodeStates || {};
    const nextSerialized = JSON.stringify(nextNodeStates);
    const prevSerialized = JSON.stringify(previous || {});
    if (nextSerialized === prevSerialized) {
        return false;
    }
    record.__wfNodeStates = nextNodeStates;
    if (typeof record.model?.notify === "function") {
        record.model.notify();
    }
    return true;
}
