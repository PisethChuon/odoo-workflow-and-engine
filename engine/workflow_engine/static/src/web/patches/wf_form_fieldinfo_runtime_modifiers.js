/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormCompiler } from "@web/views/form/form_compiler";
import {
    isWorkflowStudioEditorActive,
    isWorkflowTechnicalX2ManyField,
} from "@workflow_engine/web/utils/wf_field_state_utils";

function isWorkflowManagedFormNode(fieldNode) {
    if (isWorkflowStudioEditorActive()) {
        return false;
    }
    const formNode = fieldNode?.closest?.("form");
    const jsClass = (formNode?.getAttribute?.("js_class") || "").trim();
    if (!jsClass) {
        return false;
    }
    const tokens = jsClass
        .split(/\s+/)
        .map((token) => token.trim())
        .filter(Boolean);
    return tokens.includes("wf_form") || tokens.includes("create_approval_request");
}

function runtimeInvisibleExpr(fieldName) {
    const fieldLiteral = JSON.stringify(fieldName || "");
    if (isWorkflowTechnicalX2ManyField(fieldName)) {
        return `(__comp__.props.record.activeFields[${fieldLiteral}] && __comp__.evaluateBooleanExpr((__comp__.props.record.activeFields[${fieldLiteral}].invisible || 'False'), __comp__.props.record.evalContextWithVirtualIds))`;
    }
    return `((Array.isArray(__comp__.props.record.data.invisible_fields) && __comp__.props.record.data.invisible_fields.includes(${fieldLiteral}))
        || (__comp__.props.record.activeFields[${fieldLiteral}] && __comp__.evaluateBooleanExpr((__comp__.props.record.activeFields[${fieldLiteral}].invisible || 'False'), __comp__.props.record.evalContextWithVirtualIds)))`;
}

function runtimeModifierExpr(fieldName, modifierName) {
    const fieldLiteral = JSON.stringify(fieldName || "");
    const listName = JSON.stringify(`${modifierName}_fields`);
    const activeModifier = JSON.stringify(modifierName);
    if (isWorkflowTechnicalX2ManyField(fieldName)) {
        return `(__comp__.props.record.activeFields[${fieldLiteral}] && __comp__.evaluateBooleanExpr((__comp__.props.record.activeFields[${fieldLiteral}][${activeModifier}] || 'False'), __comp__.props.record.evalContextWithVirtualIds))`;
    }
    return `((Array.isArray(__comp__.props.record.data[${listName}]) && __comp__.props.record.data[${listName}].includes(${fieldLiteral}))
        || (__comp__.props.record.activeFields[${fieldLiteral}] && __comp__.evaluateBooleanExpr((__comp__.props.record.activeFields[${fieldLiteral}][${activeModifier}] || 'False'), __comp__.props.record.evalContextWithVirtualIds)))`;
}

function mergeSlotVisibilityExpr(existingExpr, workflowInvisibleExpr) {
    const current = (existingExpr || "true").trim();
    if (!workflowInvisibleExpr) {
        return current || "true";
    }
    if (current === "false") {
        return "false";
    }
    if (current === "true") {
        return `!(${workflowInvisibleExpr})`;
    }
    return `(${current}) && !(${workflowInvisibleExpr})`;
}

patch(FormCompiler.prototype, {
    compileField(el, params) {
        const compiled = super.compileField(...arguments);
        if (!isWorkflowManagedFormNode(el)) {
            return compiled;
        }

        const fieldName = (el.getAttribute("name") || "").trim();
        const fieldId = (el.getAttribute("field_id") || fieldName).trim();
        if (!fieldName || !fieldId) {
            return compiled;
        }

        // Runtime workflow policy mutates record.activeFields. Merge those live
        // modifiers into fieldInfo so Field components use current readonly/required/
        // invisible instead of static arch-only values.
        // Important:
        // Only overlay runtime modifiers when wf runtime explicitly applied
        // a state for this field. Otherwise keep static arch modifiers (e.g. readonly="1")
        // to avoid turning readonly fields editable.
        compiled.setAttribute(
            "fieldInfo",
            `(((__comp__.props.record.activeFields['${fieldName}'] || {}).__wf_runtime_applied || ${runtimeInvisibleExpr(fieldName)} || ${runtimeModifierExpr(fieldName, "readonly")} || ${runtimeModifierExpr(fieldName, "required")})
                ? Object.assign({}, (__comp__.props.archInfo.fieldNodes['${fieldId}'] || {}), {
                    invisible: (${runtimeInvisibleExpr(fieldName)}) ? 'True' : ((__comp__.props.record.activeFields['${fieldName}'] || {}).invisible || 'False'),
                    readonly: (${runtimeModifierExpr(fieldName, "readonly")} || ${runtimeInvisibleExpr(fieldName)}) ? 'True' : 'False',
                    required: (${runtimeModifierExpr(fieldName, "required")} && !(${runtimeModifierExpr(fieldName, "readonly")}) && !(${runtimeInvisibleExpr(fieldName)})) ? 'True' : 'False',
                })
                : (__comp__.props.archInfo.fieldNodes['${fieldId}'] || {}))`
        );

        // Keep label+field slot visibility in sync with Meta Field runtime state.
        const currentSlot = params?.currentSlot;
        if (currentSlot) {
            currentSlot.setAttribute(
                "isVisible",
                mergeSlotVisibilityExpr(
                    currentSlot.getAttribute("isVisible"),
                    runtimeInvisibleExpr(fieldName)
                )
            );
        }
        return compiled;
    },
});
