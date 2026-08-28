/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { getTag } from "@web/core/utils/xml";
import { FormCompiler } from "@web/views/form/form_compiler";
import { getModifier } from "@web/views/view_compiler";
import {
    isWorkflowStudioEditorActive,
    isWorkflowTechnicalX2ManyField,
} from "@workflow_engine/web/utils/wf_field_state_utils";

function isWorkflowManagedFormNode(groupNode) {
    if (isWorkflowStudioEditorActive()) {
        return false;
    }
    const formNode = groupNode?.closest?.("form");
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

function isAlwaysInvisible(modifier) {
    return modifier === "True" || modifier === "1";
}

function isAlwaysVisible(modifier) {
    return !modifier || modifier === "False" || modifier === "0";
}

function normalizeText(value) {
    return typeof value === "string" ? value.trim() : "";
}

function isFormFieldNode(node) {
    return Boolean(node && getTag(node, true) === "field" && normalizeText(node.getAttribute("name")));
}

function collectRenderedSlotSourceChildren(groupNode, compileInvisibleNodes) {
    const children = [];
    for (const child of groupNode.children || []) {
        if (getTag(child, true) === "newline") {
            continue;
        }
        const invisible = getModifier(child, "invisible");
        if (!compileInvisibleNodes && isAlwaysInvisible(invisible)) {
            continue;
        }
        children.push(child);
    }
    return children;
}

function collectItemSlots(compiledGroupNode) {
    const slots = [];
    for (const child of compiledGroupNode?.children || []) {
        const slotName = child?.getAttribute?.("t-set-slot") || "";
        if (slotName.startsWith("item_")) {
            slots.push(child);
        }
    }
    return slots;
}

function buildRuntimeInvisibleExpr(fieldName) {
    const fieldLiteral = JSON.stringify(fieldName || "");
    if (isWorkflowTechnicalX2ManyField(fieldName)) {
        return `(__comp__.props.record.activeFields[${fieldLiteral}] && __comp__.evaluateBooleanExpr((__comp__.props.record.activeFields[${fieldLiteral}].invisible || 'False'), __comp__.props.record.evalContextWithVirtualIds))`;
    }
    return `((Array.isArray(__comp__.props.record.data.invisible_fields) && __comp__.props.record.data.invisible_fields.includes(${fieldLiteral}))
        || (__comp__.props.record.activeFields[${fieldLiteral}] && __comp__.evaluateBooleanExpr((__comp__.props.record.activeFields[${fieldLiteral}].invisible || 'False'), __comp__.props.record.evalContextWithVirtualIds)))`;
}

function buildModifierVisibleExpr(modifier) {
    if (isAlwaysVisible(modifier)) {
        return "true";
    }
    if (isAlwaysInvisible(modifier)) {
        return "false";
    }
    return `!__comp__.evaluateBooleanExpr(${JSON.stringify(
        modifier
    )}, __comp__.props.record.evalContextWithVirtualIds)`;
}

function mergeVisibilityExpr(existingExpr, runtimeInvisibleExpr) {
    const current = (existingExpr || "true").trim();
    if (!runtimeInvisibleExpr) {
        return current;
    }
    if (current === "false") {
        return "false";
    }
    if (current === "true") {
        return `!(${runtimeInvisibleExpr})`;
    }
    return `(${current}) && !(${runtimeInvisibleExpr})`;
}

function mergeRequiredVisibilityExpr(existingExpr, requiredVisibleExpr) {
    const current = (existingExpr || "true").trim();
    const required = (requiredVisibleExpr || "").trim();
    if (!required || required === "true") {
        return current;
    }
    if (current === "false" || required === "false") {
        return "false";
    }
    if (current === "true") {
        return `(${required})`;
    }
    return `(${current}) && (${required})`;
}

function andVisibilityExpr(...expressions) {
    const parts = expressions
        .map((expr) => (expr || "").trim())
        .filter((expr) => expr && expr !== "true");
    if (expressions.some((expr) => (expr || "").trim() === "false")) {
        return "false";
    }
    if (!parts.length) {
        return "true";
    }
    return parts.map((expr) => `(${expr})`).join(" && ");
}

function extractInvisibleFieldListChecks(modifier) {
    const expression = normalizeText(modifier);
    if (!expression || !expression.includes("invisible_fields")) {
        return [];
    }
    const fieldNames = new Set();
    const pattern = /['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s+in\s+\(?\s*invisible_fields\b/g;
    let match;
    while ((match = pattern.exec(expression))) {
        if (!isWorkflowTechnicalX2ManyField(match[1])) {
            fieldNames.add(match[1]);
        }
    }
    return [...fieldNames];
}

function buildInvisibleFieldListVisibleExpr(modifier) {
    const fieldNames = extractInvisibleFieldListChecks(modifier);
    if (!fieldNames.length) {
        return "";
    }
    const listExpr = "__comp__.props.record.data.invisible_fields";
    const runtimeReadyExpr = `(Array.isArray(${listExpr}) || typeof ${listExpr} === 'string')`;
    const hiddenChecks = fieldNames.map((fieldName) => {
        const fieldLiteral = JSON.stringify(fieldName);
        return `((Array.isArray(${listExpr}) && ${listExpr}.includes(${fieldLiteral}))
            || (typeof ${listExpr} === 'string' && ${listExpr}.split(',').map((item) => item.trim()).includes(${fieldLiteral})))`;
    });
    // Once the helper field is loaded, trust it directly. Non-record runtime
    // markers can be lost across Odoo save/reload cycles.
    return `(${runtimeReadyExpr}) && !(${hiddenChecks.join(" || ")})`;
}

function orVisibilityExpr(expressions) {
    const parts = expressions
        .map((expr) => (expr || "").trim())
        .filter((expr) => expr && expr !== "false");
    if (parts.includes("true")) {
        return "true";
    }
    if (!parts.length) {
        return "";
    }
    return parts.map((expr) => `(${expr})`).join(" || ");
}

function isDecorativeGroupChild(node) {
    const tag = getTag(node, true);
    if (tag === "newline" || tag === "separator" || tag === "label") {
        return true;
    }
    return Boolean(node?.matches?.("div[class='clearfix']:empty"));
}

function buildRenderedGroupHasVisibleExpr(groupNode, compileInvisibleNodes) {
    const visibleExpressions = [];
    for (const child of groupNode.children || []) {
        if (isDecorativeGroupChild(child)) {
            continue;
        }
        const invisible = getModifier(child, "invisible");
        if (!compileInvisibleNodes && isAlwaysInvisible(invisible)) {
            continue;
        }
        const ownVisibleExpr = andVisibilityExpr(
            buildModifierVisibleExpr(invisible),
            buildInvisibleFieldListVisibleExpr(invisible)
        );
        const tag = getTag(child, true);
        if (tag === "field") {
            const fieldName = normalizeText(child.getAttribute("name"));
            if (!fieldName) {
                continue;
            }
            visibleExpressions.push(
                andVisibilityExpr(ownVisibleExpr, `!(${buildRuntimeInvisibleExpr(fieldName)})`)
            );
            continue;
        }
        if (tag === "group") {
            const childVisibleExpr = buildRenderedGroupHasVisibleExpr(child, compileInvisibleNodes);
            if (childVisibleExpr) {
                visibleExpressions.push(andVisibilityExpr(ownVisibleExpr, childVisibleExpr));
            }
            continue;
        }
        visibleExpressions.push(ownVisibleExpr);
    }
    return orVisibilityExpr(visibleExpressions);
}

patch(FormCompiler.prototype, {
    compileGroup(el, params) {
        const compiled = super.compileGroup(...arguments);
        if (!isWorkflowManagedFormNode(el)) {
            return compiled;
        }

        const groupHasVisibleExpr = buildRenderedGroupHasVisibleExpr(
            el,
            Boolean(params?.compileInvisibleNodes)
        );
        if (groupHasVisibleExpr) {
            compiled.setAttribute(
                "t-if",
                mergeRequiredVisibilityExpr(compiled.getAttribute("t-if"), groupHasVisibleExpr)
            );
        }

        const sourceChildren = collectRenderedSlotSourceChildren(el, Boolean(params?.compileInvisibleNodes));
        const itemSlots = collectItemSlots(compiled);
        if (!sourceChildren.length || !itemSlots.length) {
            return compiled;
        }

        const limit = Math.min(sourceChildren.length, itemSlots.length);
        for (let index = 0; index < limit; index++) {
            const sourceChild = sourceChildren[index];
            if (!isFormFieldNode(sourceChild)) {
                continue;
            }
            const fieldName = (sourceChild.getAttribute("name") || "").trim();
            if (!fieldName) {
                continue;
            }
            // Visible-allowlist rules can hide fields that do not carry their own
            // workflow policy marker in the XML. Attach runtime invisibility to
            // every field slot so the label/wrapper follows activeFields state.
            const runtimeInvisibleExpr = buildRuntimeInvisibleExpr(fieldName);
            const slotNode = itemSlots[index];
            slotNode.setAttribute(
                "isVisible",
                mergeVisibilityExpr(slotNode.getAttribute("isVisible"), runtimeInvisibleExpr)
            );
        }

        return compiled;
    },

    compileButton(el, params) {
        const compiled = super.compileButton(...arguments);
        if (!isWorkflowManagedFormNode(el)) {
            return compiled;
        }
        const invisible = getModifier(el, "invisible");
        const helperVisibleExpr = buildInvisibleFieldListVisibleExpr(invisible);
        if (!helperVisibleExpr || !compiled?.setAttribute) {
            return compiled;
        }
        compiled.setAttribute(
            "t-if",
            andVisibilityExpr(compiled.getAttribute("t-if") || "true", helperVisibleExpr)
        );
        return compiled;
    },
});
