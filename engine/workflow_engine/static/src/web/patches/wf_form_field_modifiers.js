/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Field } from "@web/views/fields/field";
import { Domain } from "@web/core/domain";
import { evaluateBooleanExpr, evaluateExpr } from "@web/core/py_js/py";
import { getFieldContext } from "@web/model/relational_model/utils";
import { isWorkflowStudioEditorActive } from "@workflow_engine/web/utils/wf_field_state_utils";

const FALSE_VALUES = new Set([undefined, null, "", "False", "false", "0", false, 0]);
const TRUE_VALUES = new Set(["True", "true", "1", true, 1]);

function normalizeDomain(domainValue) {
    if (typeof domainValue === "string") {
        return domainValue.replace(/[\u200B-\u200D\uFEFF]/g, "").trim();
    }
    if (Array.isArray(domainValue)) {
        try {
            return JSON.stringify(domainValue);
        } catch {
            return "";
        }
    }
    return "";
}

function normalizeLegacyAlwaysVisibleDomain(domainExpression) {
    const expression = normalizeDomain(domainExpression);
    if (!expression) {
        return expression;
    }
    // Backward compatibility:
    // previous studio "enabled" default used id != 0, which is false on unsaved records.
    const isLegacyAlwaysVisible =
        /^\[\(\s*['"]id['"]\s*,\s*['"]!=['"]\s*,\s*0\s*\)\]$/.test(expression);
    if (isLegacyAlwaysVisible) {
        return "[('wf_actor_uid', '!=', 0)]";
    }
    return expression;
}

function combineWithOr(baseExpr, extraExpr) {
    if (FALSE_VALUES.has(baseExpr)) {
        return extraExpr;
    }
    if (TRUE_VALUES.has(baseExpr)) {
        return "True";
    }
    return `(${baseExpr}) or (${extraExpr})`;
}

function toPyLiteral(value) {
    if (value === true) {
        return "True";
    }
    if (value === false || value === null || value === undefined) {
        return "False";
    }
    if (typeof value === "number") {
        return Number.isFinite(value) ? `${value}` : "False";
    }
    if (typeof value === "string") {
        const escaped = value.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
        return `'${escaped}'`;
    }
    if (Array.isArray(value)) {
        // many2one value can arrive as [id, display_name]
        if (value.length === 2 && typeof value[0] === "number" && typeof value[1] === "string") {
            return `${value[0]}`;
        }
        return `[${value.map((v) => toPyLiteral(v)).join(", ")}]`;
    }
    return "False";
}

function lowerStringValue(value) {
    return typeof value === "string" ? value.toLowerCase() : value;
}

function toPyFieldRef(fieldName) {
    if (typeof fieldName !== "string") {
        return null;
    }
    const cleaned = fieldName.trim();
    if (!cleaned) {
        return null;
    }
    if (!/^[_A-Za-z][_A-Za-z0-9.]*$/.test(cleaned)) {
        return null;
    }
    return cleaned;
}

function toWorkflowRuntimeFieldExpr(fieldName, baseRef) {
    const cleaned = typeof fieldName === "string" ? fieldName.trim() : "";
    switch (cleaned) {
        case "wf_actor_name":
            return "(wf_actor_name or '')";
        case "wf_actor_login":
            return "(wf_actor_login or '')";
        case "wf_actor_department_name":
            return "(wf_actor_department_name or '')";
        case "wf_actor_position_name":
            return "(wf_actor_position_name or '')";
        case "wf_actor_group_xmlids":
            return "(wf_actor_group_xmlids or '')";
        case "wf_actor_is_manager":
            return "(wf_actor_is_manager or False)";
        case "wf_actor_is_hod":
            return "(wf_actor_is_hod or False)";
        case "wf_action_key":
            return "(wf_action_key or '')";
        case "wf_current_node_id":
            return "(wf_current_node_id or '')";
        default:
            return baseRef;
    }
}

function compileLeafCondition(cond) {
    if (!Array.isArray(cond) || cond.length < 3) {
        return null;
    }
    const [fieldName, operator, value] = cond;
    const baseFieldRef = toPyFieldRef(fieldName);
    if (!baseFieldRef) {
        return null;
    }
    const fieldRef = toWorkflowRuntimeFieldExpr(fieldName, baseFieldRef);
    const op = `${operator || ""}`.trim();
    const valueExpr = toPyLiteral(value);
    const valueLowerExpr = toPyLiteral(lowerStringValue(value));
    const isLoweredValueDifferent = valueLowerExpr !== valueExpr;
    switch (op) {
        case "=":
            return `(${fieldRef} == ${valueExpr})`;
        case "!=":
            return `(${fieldRef} != ${valueExpr})`;
        case ">":
        case ">=":
        case "<":
        case "<=":
            return `(${fieldRef} ${op} ${valueExpr})`;
        case "in":
            return `(${fieldRef} in ${valueExpr})`;
        case "not in":
            return `(${fieldRef} not in ${valueExpr})`;
        case "like":
        case "=like":
        case "contains":
            return `(${valueExpr} in (${fieldRef} or ''))`;
        case "ilike":
        case "=ilike":
        case "icontains":
            // No function calls allowed in py evaluator. For ilike/icontains,
            // use lowercase literal variant for runtime workflow keys.
            if (isLoweredValueDifferent) {
                return `((${valueExpr} in (${fieldRef} or '')) or (${valueLowerExpr} in (${fieldRef} or '')))`;
            }
            return `(${valueExpr} in (${fieldRef} or ''))`;
        case "not like":
        case "not contains":
            return `not (${valueExpr} in (${fieldRef} or ''))`;
        case "not ilike":
        case "not icontains":
            if (isLoweredValueDifferent) {
                return `not ((${valueExpr} in (${fieldRef} or '')) or (${valueLowerExpr} in (${fieldRef} or '')))`;
            }
            return `not (${valueExpr} in (${fieldRef} or ''))`;
        default:
            return null;
    }
}

function compileDomainNode(node) {
    if (!Array.isArray(node)) {
        return null;
    }
    if (!node.length) {
        return "True";
    }
    const head = node[0];
    if (head === "!") {
        const compiled = compileDomainNode(node[1]);
        return compiled ? `not (${compiled})` : null;
    }
    if (head === "&" || head === "|") {
        const left = compileDomainNode(node[1]);
        const right = compileDomainNode(node[2]);
        if (!left || !right) {
            return null;
        }
        return `(${left}) ${head === "&" ? "and" : "or"} (${right})`;
    }
    if (
        node.length >= 3 &&
        typeof node[0] === "string" &&
        !["&", "|", "!"].includes(node[0])
    ) {
        return compileLeafCondition(node);
    }
    const compiledItems = node.map((item) => compileDomainNode(item)).filter(Boolean);
    if (!compiledItems.length) {
        return null;
    }
    return compiledItems.map((item) => `(${item})`).join(" and ");
}

function buildMatchExpressionFromDomain(domainExpression) {
    const expression = normalizeDomain(domainExpression);
    if (!expression || expression === "[]") {
        return "True";
    }
    try {
        const parsed = new Domain(expression);
        const domainList = parsed.toList({});
        const compiled = compileDomainNode(domainList);
        return compiled || "False";
    } catch {
        return "False";
    }
}

function decodeDomainLiteral(rawLiteral, quote) {
    if (!rawLiteral) {
        return "";
    }
    let decoded = rawLiteral.replace(/\\\\/g, "\\");
    if (quote === "'") {
        decoded = decoded.replace(/\\'/g, "'");
    } else {
        decoded = decoded.replace(/\\"/g, '"');
    }
    return decoded;
}

function convertLegacyWfMatchExpression(expression) {
    if (typeof expression !== "string" || !expression.includes("wf_match_domain(")) {
        return expression;
    }
    let replaced = false;
    const converted = expression.replace(
        /wf_match_domain\(\s*(['"])((?:\\.|(?!\1).)*)\1(?:\s*,[^)]*)?\)/g,
        (_match, quote, literal) => {
            const domainExpression = decodeDomainLiteral(literal || "", quote);
            replaced = true;
            return `(${buildMatchExpressionFromDomain(domainExpression)})`;
        }
    );
    if (replaced) {
        return converted;
    }
    // Safety fallback for malformed legacy expressions.
    return "False";
}

function convertLegacyExpressionsInObject(value, seen = new WeakMap()) {
    if (typeof value === "string" || value instanceof String) {
        return convertLegacyWfMatchExpression(value);
    }
    if (!value || typeof value !== "object") {
        return value;
    }

    if (seen.has(value)) {
        return seen.get(value);
    }

    if (Array.isArray(value)) {
        const cloned = value.map((item) => convertLegacyExpressionsInObject(item, seen));
        seen.set(value, cloned);
        return cloned;
    }

    // Only traverse plain objects; keep specialized objects/proxies untouched.
    const proto = Object.getPrototypeOf(value);
    const isPlainObject = proto === Object.prototype || proto === null;
    if (!isPlainObject) {
        return value;
    }

    const cloned = {};
    seen.set(value, cloned);
    for (const key of Object.keys(value)) {
        cloned[key] = convertLegacyExpressionsInObject(value[key], seen);
    }
    return cloned;
}

function resolveWorkflowDomains(node, fieldInfo) {
    return null;
}

function isWorkflowManagedForm(jsClass) {
    if (typeof jsClass !== "string") {
        return false;
    }
    if (isWorkflowStudioEditorActive()) {
        return false;
    }
    const tokens = jsClass
        .split(/\s+/)
        .map((token) => token.trim())
        .filter(Boolean);
    return tokens.includes("wf_form") || tokens.includes("create_approval_request");
}

function isWorkflowManagedFieldComponent(component) {
    if (isWorkflowStudioEditorActive()) {
        return false;
    }
    const jsClass =
        component?.env?.config?.viewSubType ||
        component?.env?.config?.viewArch?.getAttribute?.("js_class") ||
        "";
    return isWorkflowManagedForm(jsClass);
}

function resolveJsClass(node, jsClass) {
    if (typeof jsClass === "string" && jsClass.trim()) {
        return jsClass;
    }
    try {
        const root = node?.ownerDocument?.documentElement;
        if (root?.getAttribute) {
            return root.getAttribute("js_class") || "";
        }
    } catch {
        // no-op
    }
    return "";
}

function hasWorkflowModifierConfig(node, fieldInfo) {
    return false;
}

function parseNodeOptions(node) {
    if (!node?.getAttribute) {
        return {};
    }
    const raw = (node.getAttribute("options") || "").trim();
    if (!raw) {
        return {};
    }
    try {
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch {
        return {};
    }
}

function isLegacyWfFieldWidget(node) {
    // Backward compatibility: old XML may still have widget="wf_field".
    return (node?.getAttribute?.("widget") || "").trim() === "wf_field";
}

patch(Field, {
    parseFieldNode(node, models, modelName, viewType, jsClass) {
        const resolvedJsClass = resolveJsClass(node, jsClass);
        let parseNode = node;
        if (isLegacyWfFieldWidget(node)) {
            // Backward compat: old arch stored widget="wf_field" as a policy marker.
            // Strip it so the field renders with its default widget and avoids
            // "Missing widget: wf_field" errors. The wf_original_widget option is
            // no longer written by the studio, but may exist in older arch.
            const options = parseNodeOptions(node);
            const originalWidget =
                typeof options.wf_original_widget === "string" ? options.wf_original_widget.trim() : "";
            parseNode = node.cloneNode(true);
            if (originalWidget) {
                parseNode.setAttribute("widget", originalWidget);
            } else {
                parseNode.removeAttribute("widget");
            }
        }
        const baseFieldInfo = super.parseFieldNode(parseNode, models, modelName, viewType, jsClass);

        if (viewType !== "form") {
            const fieldInfo = convertLegacyExpressionsInObject(baseFieldInfo);
            fieldInfo.invisible = convertLegacyWfMatchExpression(fieldInfo.invisible);
            fieldInfo.readonly = convertLegacyWfMatchExpression(fieldInfo.readonly);
            fieldInfo.required = convertLegacyWfMatchExpression(fieldInfo.required);
            return fieldInfo;
        }

        // wf_form is server-driven: avoid client-side domain compilation because
        // missing JS eval symbols (for example owner_user_id not loaded in view)
        // can raise EvalError and conflict with runtime server policies.
        if (isWorkflowManagedForm(resolvedJsClass)) {
            const fieldInfo = convertLegacyExpressionsInObject(baseFieldInfo);
            return fieldInfo;
        }

        const fieldInfo = convertLegacyExpressionsInObject(baseFieldInfo);
        fieldInfo.invisible = convertLegacyWfMatchExpression(fieldInfo.invisible);
        fieldInfo.readonly = convertLegacyWfMatchExpression(fieldInfo.readonly);
        fieldInfo.required = convertLegacyWfMatchExpression(fieldInfo.required);

        if (!isWorkflowManagedForm(resolvedJsClass) && !hasWorkflowModifierConfig(node, fieldInfo)) {
            return fieldInfo;
        }

        const domains = resolveWorkflowDomains(node, fieldInfo);
        if (!domains) {
            return fieldInfo;
        }

        const explicitVisibleExpr = domains.visibleDomain
            ? buildMatchExpressionFromDomain(domains.visibleDomain)
            : "";
        const requiredExpr = "False";
        const readonlyFromDomain = domains.readonlyDomain
            ? buildMatchExpressionFromDomain(domains.readonlyDomain)
            : "False";
        const readonlyFromLegacyEdit = domains.legacyEditDomain
            ? `not (${buildMatchExpressionFromDomain(domains.legacyEditDomain)})`
            : "False";
        const readonlyExpr =
            readonlyFromDomain !== "False" && readonlyFromLegacyEdit !== "False"
                ? `(${readonlyFromDomain}) or (${readonlyFromLegacyEdit})`
                : readonlyFromDomain !== "False"
                    ? readonlyFromDomain
                    : readonlyFromLegacyEdit;
        const autoVisibleExprParts = [];
        if (!domains.visibleDomain && readonlyExpr && readonlyExpr !== "False") {
            autoVisibleExprParts.push(`(${readonlyExpr})`);
        }
        const autoVisibleExpr = autoVisibleExprParts.length
            ? autoVisibleExprParts.join(" or ")
            : "";
        const visibleMatchExpr = explicitVisibleExpr || autoVisibleExpr || "True";
        const readonlyActiveExpr = readonlyExpr && readonlyExpr !== "False" ? `(${readonlyExpr})` : "False";
        const requiredWithVisibilityAndEditable =
            `(${requiredExpr}) and (${visibleMatchExpr}) and (not (${readonlyActiveExpr}))`;

        if (domains.visibleDomain || autoVisibleExpr) {
            // Workflow visibility policy owns field visibility; ignore stale native invisible.
            fieldInfo.invisible = "False";
            fieldInfo.invisible = combineWithOr(fieldInfo.invisible, `not (${visibleMatchExpr})`);
        }
        if (readonlyExpr && readonlyExpr !== "False") {
            fieldInfo.readonly = combineWithOr(fieldInfo.readonly, readonlyExpr);
        }
        // Merge with native Odoo required rule, do not overwrite it.
        fieldInfo.required = combineWithOr(fieldInfo.required, requiredWithVisibilityAndEditable);
        fieldInfo.wfModifierDomain =
            domains.readonlyDomain || domains.legacyEditDomain || domains.visibleDomain;

        return fieldInfo;
    },
});

patch(Field.prototype, {
    get fieldComponentProps() {
        if (!isWorkflowManagedFieldComponent(this)) {
            return super.fieldComponentProps;
        }

        const record = this.props.record;
        let readonly = false;
        let propsFromNode = {};

        if (this.props.fieldInfo) {
            let fieldInfo = this.props.fieldInfo;
            readonly = evaluateBooleanExpr(fieldInfo.readonly, record.evalContextWithVirtualIds);

            if (this.field.extractProps) {
                if (this.props.attrs) {
                    fieldInfo = {
                        ...fieldInfo,
                        attrs: { ...fieldInfo.attrs, ...this.props.attrs },
                    };
                }
                if (fieldInfo.attrs.placeholder || fieldInfo.options.placeholder_field) {
                    fieldInfo.placeholder =
                        record.data[fieldInfo.options.placeholder_field] ||
                        fieldInfo.attrs.placeholder;
                }

                const dynamicInfo = {
                    get context() {
                        return getFieldContext(record, fieldInfo.name, fieldInfo.context);
                    },
                    domain() {
                        const evalContext = record.evalContext;
                        if (fieldInfo.domain) {
                            return new Domain(evaluateExpr(fieldInfo.domain, evalContext)).toList();
                        }
                    },
                    required: evaluateBooleanExpr(
                        fieldInfo.required,
                        record.evalContextWithVirtualIds
                    ),
                    readonly,
                };
                propsFromNode = this.field.extractProps(fieldInfo, dynamicInfo);
            }
        }

        const props = { ...this.props };
        delete props.style;
        delete props.class;
        delete props.showTooltip;
        delete props.fieldInfo;
        delete props.attrs;
        delete props.type;
        delete props.readonly;

        return {
            readonly: readonly || !record.isInEdition || false,
            ...propsFromNode,
            ...props,
        };
    },
});
