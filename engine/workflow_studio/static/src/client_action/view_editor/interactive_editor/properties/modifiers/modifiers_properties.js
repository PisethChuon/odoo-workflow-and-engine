import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { CheckBox } from "@web/core/checkbox/checkbox";
import { useOwnedDialogs } from "@web/core/utils/hooks";
import { ExpressionEditorDialog } from "@web/core/expression_editor_dialog/expression_editor_dialog";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import {
    WorkflowStudioDomainDialog
} from "@workflow_studio/client_action/components/workflow_domain_dialog/workflow_domain_dialog";
import { evaluateExpr } from "@web/core/py_js/py";
import { computeXpath } from "@workflow_studio/client_action/view_editor/editors/xml_utils";

export function collectWorkflowFieldTargets(env) {
    const xmlDoc = env.viewEditorModel?.xmlDoc;
    if (!xmlDoc) {
        return [];
    }
    const modelFields = env.viewEditorModel?.fields || {};
    const grouped = new Map();
    const fieldNodes = Array.from(xmlDoc.querySelectorAll("field[name]"));

    const excluded = new Set(["tree", "list", "kanban", "search", "calendar", "graph", "pivot", "gantt", "activity", "cohort", "map"]);
    function isMainFormFieldNode(node) {
        if (!node || node.tagName !== "field") return false;
        let formCount = 0;
        let current = node.parentElement;
        while (current) {
            const tagName = (current.tagName || "").toLowerCase();
            if (tagName === "form") formCount += 1;
            if (excluded.has(tagName)) return false;
            current = current.parentElement;
        }
        return formCount === 1;
    }

    function snapshotNodeAttributes(node) {
        const attrs = {};
        for (const attrName of node?.getAttributeNames?.() || []) {
            attrs[attrName] = node.getAttribute(attrName);
        }
        return attrs;
    }

    for (const node of fieldNodes) {
        if (!isMainFormFieldNode(node)) {
            continue;
        }
        const fieldName = (node.getAttribute("name") || "").trim();
        if (!fieldName) {
            continue;
        }
        const fieldMeta = modelFields[fieldName] || {};
        if (!grouped.has(fieldName)) {
            grouped.set(fieldName, {
                name: fieldName,
                label: fieldMeta.string || fieldMeta.label || fieldName,
                type: fieldMeta.type || "",
                relation: fieldMeta.relation || "",
                selection: Array.isArray(fieldMeta.selection) ? fieldMeta.selection : [],
                occurrences: [],
            });
        }
        grouped.get(fieldName).occurrences.push({
            xpath: computeXpath(node, "form"),
            attrs: snapshotNodeAttributes(node),
        });
    }
    return Array.from(grouped.values()).sort((a, b) => {
        const left = `${a.label || ""} ${a.name || ""}`.toLowerCase();
        const right = `${b.label || ""} ${b.name || ""}`.toLowerCase();
        return left.localeCompare(right);
    });
}

export function buildWorkflowDomainOperationForFieldTarget(env, targetOccurrence, domainChangesByKind = {}) {
    return {
        new_attrs: {
            invisible: "False",
            readonly: "False",
            required: "False",
        },
        type: "attributes",
        position: "attributes",
        target: env.viewEditorModel.getFullTarget(targetOccurrence.xpath),
    };
}

export class WorkflowGlobalBulkPolicyDialog extends Component {
    static template = "workflow_studio.WorkflowGlobalBulkPolicyDialog";
    static components = { Dialog, CheckBox };
    static props = {
        close: Function,
        onConfirm: Function,
        fields: { type: Array },
        availableKinds: { type: Array },
        resModel: { type: String, optional: true },
        requestFields: { type: Array, optional: true },
    };

    setup() {
        this.addDialog = useOwnedDialogs();
        const selectedByName = {};
        for (const item of this.props.fields || []) {
            selectedByName[item.name] = false;
        }
        const selectedKinds = { visible: false, readonly: false, required: false };
        const domainsByKind = { visible: "[]", readonly: "[]", required: "[]" };
        this.state = useState({
            search: "",
            selectedByName,
            selectedKinds,
            domainsByKind,
            applying: false,
        });
        this.onSearchInput = this.onSearchInput.bind(this);
        this.onToggleField = this.onToggleField.bind(this);
        this.onToggleKind = this.onToggleKind.bind(this);
        this.selectFiltered = this.selectFiltered.bind(this);
        this.clearFiltered = this.clearFiltered.bind(this);
        this.onConfirmClicked = this.onConfirmClicked.bind(this);
    }

    openDomainBuilder(kind = "visible") {
        const domainKind = ["visible", "readonly", "required"].includes(kind) ? kind : "visible";
        const kindLabel = this.getKindLabel(domainKind);
        const resModel = `${this.props.resModel || this.env?.viewEditorModel?.resModel || ""}`.trim();
        if (!resModel) {
            this.env?.services?.notification?.add(
                _t("Cannot open Domain Builder because model context is missing."),
                { type: "warning" }
            );
            return;
        }
        const workflowContext = this.env?.viewEditorModel?._studio?.editedAction?.context || {};
        const workflowVersionId = Number(workflowContext.workflow_version_id || 0) || 0;
        const workflowCategoryId = Number(workflowContext.workflow_category_id || 0) || 0;
        this.addDialog(WorkflowStudioDomainDialog, {
            resModel,
            requestFields: this.props.requestFields || [],
            workflowVersionId,
            workflowCategoryId,
            domain: this.state.domainsByKind[domainKind] || "[]",
            domainKind,
            contextType: "field_modifiers",
            title: _t("%s Domain", kindLabel),
            helpText: _t("Define specific domain to be applied"),
            isDebugMode: !!this.env.debug,
            onConfirm: (domainExpression) => {
                this.onDomainInput(domainKind, domainExpression);
            },
        });
    }

    get dialogTitle() {
        return _t("Global Bulk Apply Workflow Rules");
    }

    get searchValue() {
        return (this.state.search || "").trim().toLowerCase();
    }

    get filteredFields() {
        const search = this.searchValue;
        const rows = this.props.fields || [];
        if (!search) {
            return rows;
        }
        return rows.filter((row) => {
            const haystack = [row.label || "", row.name || "", row.type || ""].join(" ").toLowerCase();
            return haystack.includes(search);
        });
    }

    get selectedFieldNames() {
        return (this.props.fields || [])
            .filter((row) => !!this.state.selectedByName[row.name])
            .map((row) => row.name);
    }

    get selectedKinds() {
        return (this.props.availableKinds || []).filter((kind) => !!this.state.selectedKinds[kind]);
    }

    get selectedCount() {
        return this.selectedFieldNames.length;
    }

    get selectedKindsCount() {
        return this.selectedKinds.length;
    }

    get canConfirm() {
        return !this.state.applying && this.selectedCount > 0 && this.selectedKindsCount > 0;
    }

    getKindLabel(kind) {
        if (kind === "readonly") return _t("Readonly rule");
        if (kind === "required") return _t("Required rule");
        return _t("Visible rule");
    }

    onSearchInput(event) {
        this.state.search = event?.target?.value || "";
    }

    getDomainByKind(kind) {
        return this.state.domainsByKind[kind] || "[]";
    }

    onDomainInput(kind, eventOrValue) {
        if (!this.state?.domainsByKind || !kind || !(kind in this.state.domainsByKind)) {
            return;
        }
        const value = typeof eventOrValue === "string"
            ? eventOrValue
            : eventOrValue?.target?.value;
        this.state.domainsByKind[kind] = `${value || "[]"}`.trim() || "[]";
    }

    onToggleField(fieldName, value) {
        if (!this.state?.selectedByName || !fieldName) {
            return;
        }
        if (!(fieldName in this.state.selectedByName)) {
            this.state.selectedByName[fieldName] = false;
        }
        this.state.selectedByName[fieldName] = !!value;
    }

    onToggleKind(kind, value) {
        if (!this.state?.selectedKinds || !kind) {
            return;
        }
        if (!(kind in this.state.selectedKinds)) {
            this.state.selectedKinds[kind] = false;
        }
        this.state.selectedKinds[kind] = !!value;
    }

    selectFiltered() {
        for (const row of this.filteredFields) {
            this.state.selectedByName[row.name] = true;
        }
    }

    clearFiltered() {
        for (const row of this.filteredFields) {
            this.state.selectedByName[row.name] = false;
        }
    }

    async onConfirmClicked() {
        if (!this.canConfirm) {
            return;
        }
        this.state.applying = true;
        try {
            await this.props.onConfirm({
                fieldNames: this.selectedFieldNames,
                kinds: this.selectedKinds,
                domainsByKind: { ...this.state.domainsByKind },
            });
            this.props.close();
        } finally {
            this.state.applying = false;
        }
    }
}

export class WorkflowFieldPolicyBulkApplyDialog extends Component {
    static template = "workflow_studio.WorkflowFieldPolicyBulkApplyDialog";
    static components = { Dialog, CheckBox };
    static props = {
        close: Function,
        onConfirm: Function,
        fields: { type: Array },
        availableKinds: { type: Array },
        initialSelected: { type: Array, optional: true },
        initialKinds: { type: Array, optional: true },
        sourceFieldLabel: { type: String, optional: true },
    };

    setup() {
        const selectedSeed = new Set(this.props.initialSelected || []);
        const kindsSeed = new Set(
            (this.props.initialKinds && this.props.initialKinds.length
                ? this.props.initialKinds
                : this.props.availableKinds) || []
        );
        const selectedByName = {};
        for (const item of this.props.fields || []) {
            selectedByName[item.name] = selectedSeed.has(item.name);
        }
        const selectedKinds = {};
        for (const kind of this.props.availableKinds || []) {
            selectedKinds[kind] = kindsSeed.has(kind);
        }
        this.state = useState({
            search: "",
            selectedByName,
            selectedKinds,
            applying: false,
        });
        this.onSearchInput = this.onSearchInput.bind(this);
        this.onToggleField = this.onToggleField.bind(this);
        this.onToggleKind = this.onToggleKind.bind(this);
        this.selectFiltered = this.selectFiltered.bind(this);
        this.clearFiltered = this.clearFiltered.bind(this);
        this.onConfirmClicked = this.onConfirmClicked.bind(this);
    }

    get dialogTitle() {
        return _t("Bulk Apply Workflow Field Rules");
    }

    get searchValue() {
        return (this.state.search || "").trim().toLowerCase();
    }

    get filteredFields() {
        const search = this.searchValue;
        const rows = this.props.fields || [];
        if (!search) {
            return rows;
        }
        return rows.filter((row) => {
            const haystack = [
                row.label || "",
                row.name || "",
                row.type || "",
            ]
                .join(" ")
                .toLowerCase();
            return haystack.includes(search);
        });
    }

    get selectedFieldNames() {
        return (this.props.fields || [])
            .filter((row) => !!this.state.selectedByName[row.name])
            .map((row) => row.name);
    }

    get selectedKinds() {
        return (this.props.availableKinds || []).filter((kind) => !!this.state.selectedKinds[kind]);
    }

    get selectedCount() {
        return this.selectedFieldNames.length;
    }

    get selectedKindsCount() {
        return this.selectedKinds.length;
    }

    get canConfirm() {
        return !this.state.applying && this.selectedCount > 0 && this.selectedKindsCount > 0;
    }

    getKindLabel(kind) {
        if (kind === "readonly") {
            return _t("Readonly rule");
        }
        if (kind === "required") {
            return _t("Required rule");
        }
        return _t("Visible rule");
    }

    onSearchInput(event) {
        this.state.search = event?.target?.value || "";
    }

    onToggleField(fieldName, value) {
        if (!this.state?.selectedByName || !fieldName) {
            return;
        }
        if (!(fieldName in this.state.selectedByName)) {
            this.state.selectedByName[fieldName] = false;
        }
        this.state.selectedByName[fieldName] = !!value;
    }

    onToggleKind(kind, value) {
        if (!this.state?.selectedKinds || !kind) {
            return;
        }
        if (!(kind in this.state.selectedKinds)) {
            this.state.selectedKinds[kind] = false;
        }
        this.state.selectedKinds[kind] = !!value;
    }

    selectFiltered() {
        for (const row of this.filteredFields) {
            this.state.selectedByName[row.name] = true;
        }
    }

    clearFiltered() {
        for (const row of this.filteredFields) {
            this.state.selectedByName[row.name] = false;
        }
    }

    async onConfirmClicked() {
        if (!this.canConfirm) {
            return;
        }
        this.state.applying = true;
        try {
            await this.props.onConfirm({
                fieldNames: this.selectedFieldNames,
                kinds: this.selectedKinds,
            });
            this.props.close();
        } finally {
            this.state.applying = false;
        }
    }
}

export class ModifiersProperties extends Component {
    static template = "workflow_studio.ViewEditor.InteractiveEditorProperties.Modifiers";
    static components = { CheckBox };
    static props = {
        node: { type: Object }, availableOptions: { type: Array },
    };

    setup() {
        this.addDialog = useOwnedDialogs();
        this.notification = this.env.services.notification;
        this.orm = this.env.services.orm;
        this.workflowPolicyCache = useState({});
        this.workflowPresetState = useState({
            submitNodeId: "Task_Submit", hodNodeId: "Task_HOD", approveActionKey: "approve",
        });
        this.simpleBuilderState = useState({
            actorType: "request_owner",
            actorLogin: "",
            actorGroupXmlid: "",
            nodeId: "",
            actionKey: "approve",
            requireOnAction: false,
        });

        onWillStart(async () => {
            await this._prefetchWorkflowPolicyDomains(this.props.node);
        });
        onWillUpdateProps(async (nextProps) => {
            await this._prefetchWorkflowPolicyDomains(nextProps.node);
        });
    }

    /**
     * @param {string} name of the attribute
     * @returns if this attribute supported in the current view
     */
    isAttributeSupported(name) {
        return this.props.availableOptions?.includes(name);
    }

    isWorkflowManagedForm() {
        if (this.env.viewEditorModel.viewType !== "form") {
            return false;
        }
        const workflowContext = this.env?.viewEditorModel?._studio?.editedAction?.context || {};
        if (workflowContext.workflow_version_id || workflowContext.workflow_category_id) {
            return true;
        }
        const formNode = this.env?.viewEditorModel?.xmlDoc?.querySelector?.("form");
        const jsClass = formNode?.getAttribute?.("js_class") || "";
        const tokens = jsClass.split(/\s+/).map((token) => token.trim()).filter(Boolean);
        return tokens.includes("wf_form") || tokens.includes("create_approval_request");
    }

    hasNativeModifierOptions() {
        return ["invisible", "required", "readonly"].some((name) => this.isAttributeSupported(name));
    }

    isWorkflowFieldNode() {
        return (this.env.viewEditorModel.viewType === "form" && this.props.node?.arch?.tagName === "field");
    }

    isWorkflowVisibleContainerNode(node = this.props.node) {
        return (
            this.env.viewEditorModel.viewType === "form" &&
            node?.arch?.tagName === "group" &&
            !!(node?.attrs?.name || "").trim()
        );
    }

    isWorkflowPolicyTargetNode() {
        return this.isWorkflowManagedForm() && (this.isWorkflowFieldNode() || this.isWorkflowVisibleContainerNode());
    }

    supportsWorkflowPolicyKind(kind) {
        return this._workflowPolicyDomainKinds().includes(kind);
    }

    isManagedWorkflowModifier(name) {
        return ["invisible", "readonly", "required"].includes(name);
    }

    // <tag invisible="EXPRESSION"  />
    onChangeModifier(name, value) {
        const isTypeBoolean = typeof value === "boolean";
        const encodesBoolean = isTypeBoolean || this.isBooleanExpression(value);
        const isTruthy = encodesBoolean ? this.isBoolTrue(value) : !!value;
        const newAttrs = {};
        const oldAttrs = { ...this.props.node.attrs };

        const changingInvisible = name === "invisible";
        const isInList = this.env.viewEditorModel.viewType === "list";

        if (encodesBoolean) {
            if (changingInvisible && isInList) {
                if (isTruthy) {
                    newAttrs["column_invisible"] = "True";
                } else {
                    newAttrs["column_invisible"] = "False";
                    newAttrs["invisible"] = "False";
                }
            } else {
                newAttrs[name] = isTruthy ? "True" : "False";
            }
        } else {
            newAttrs[name] = value;
            if (changingInvisible && isInList && "column_invisible" in oldAttrs) {
                newAttrs["column_invisible"] = "False";
            }
        }

        if (this.env.viewEditorModel.viewType === "form" && name === "readonly") {
            newAttrs.force_save = isTruthy ? "1" : "0";
        }

        const operation = {
            new_attrs: newAttrs,
            type: "attributes",
            position: "attributes",
            target: this.env.viewEditorModel.getFullTarget(this.env.viewEditorModel.activeNodeXpath),
        };
        this.env.viewEditorModel.doOperation(operation);
    }

    onChangeWorkflowFieldDomain(domainExpression) {
        const normalizedDomain = (domainExpression || "[]").trim() || "[]";
        this.onChangeWorkflowDomain("visible", normalizedDomain);
    }

    parseOptionsExpression(optionsExpression) {
        if (!optionsExpression) {
            return {};
        }
        if (typeof optionsExpression === "object" && !Array.isArray(optionsExpression)) {
            return { ...optionsExpression };
        }
        if (typeof optionsExpression !== "string") {
            return {};
        }
        const rawExpression = optionsExpression.trim();
        if (!rawExpression) {
            return {};
        }
        try {
            const options = evaluateExpr(rawExpression) || {};
            return typeof options === "object" && !Array.isArray(options) ? options : {};
        } catch {
            try {
                const options = JSON.parse(rawExpression) || {};
                return typeof options === "object" && !Array.isArray(options) ? options : {};
            } catch {
                return {};
            }
        }
    }

    _coerceWorkflowPolicyId(policyIdValue) {
        const parsed = parseInt(policyIdValue, 10);
        return Number.isFinite(parsed) && parsed > 0 ? parsed : false;
    }

    _workflowPolicyCacheKey(policyId) {
        return `policy_${policyId}`;
    }

    _getWorkflowPolicyReference(node = this.props.node) {
        const policyId = this._getNodePolicyId(node);
        return { options: {}, policyId };
    }

    _workflowPolicyDomainKinds(node = this.props.node) {
        if (this.isWorkflowVisibleContainerNode(node)) {
            return ["visible"];
        }
        return ["visible", "readonly", "required"];
    }

    _workflowPolicyDomainFieldName(kind) {
        if (kind === "readonly") {
            return "readonlyDomain";
        }
        if (kind === "required") {
            return "requiredDomain";
        }
        return "visibleDomain";
    }

    _workflowPolicyFlagAttr(kind) {
        if (kind === "readonly") return "wf_has_readonly";
        if (kind === "required") return "wf_has_required";
        return "wf_has_visible";
    }

    _isTruthyFlag(value) {
        if (typeof value === "boolean") return value;
        if (typeof value === "number") return value !== 0;
        if (typeof value === "string") {
            return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
        }
        return false;
    }


    _workflowPolicyHasFlagFromAttrs(attrs, kind) {
        const key = this._workflowPolicyFlagAttr(kind);
        return this._isTruthyFlag(attrs?.[key]);
    }

    _workflowPolicyHasAnyFlagFromAttrs(attrs, node = this.props.node) {
        return this._workflowPolicyDomainKinds(node).some((kind) => this._workflowPolicyHasFlagFromAttrs(attrs, kind));
    }


    _workflowPolicyReferenceDomainFromCache(policyId, kind) {
        if (!policyId) {
            return "";
        }
        const cached = this.workflowPolicyCache[this._workflowPolicyCacheKey(policyId)];
        if (!cached) {
            return "";
        }
        return this.normalizeWorkflowDomainValue(cached[this._workflowPolicyDomainFieldName(kind)] || "");
    }

    async _prefetchWorkflowPolicyDomains(node = this.props.node, force = false) {
        return;
    }

    getWorkflowPolicyDefaultDomain() {
        return "[('id', '=', 0)]";
    }

    getWorkflowPolicyEnabledDomain() {
        // Use runtime actor helper so policy can evaluate True even on unsaved records.
        return "[('wf_actor_uid', '!=', 0)]";
    }

    normalizeWorkflowDomainValue(domainExpression) {
        if (typeof domainExpression === "string") {
            return domainExpression.trim();
        }
        if (Array.isArray(domainExpression)) {
            try {
                return JSON.stringify(domainExpression);
            } catch {
                return "";
            }
        }
        return "";
    }

    isWorkflowPolicyDefaultDomain(domainExpression) {
        const normalized = this.normalizeWorkflowDomainValue(domainExpression);
        if (!normalized) {
            return false;
        }
        if (normalized === this.getWorkflowPolicyDefaultDomain()) {
            return true;
        }
        return /^\[\(\s*['"]id['"]\s*,\s*['"]=['"]\s*,\s*0\s*\)\]$/.test(normalized);
    }

    isWorkflowPolicyDomainConfigured(domainExpression) {
        const normalized = this.normalizeWorkflowDomainValue(domainExpression);
        if (!normalized) {
            return false;
        }
        return !this.isWorkflowPolicyDefaultDomain(normalized);
    }

    hasAnyWorkflowPolicyDomainConfigured(attrs = this.props.node?.attrs || {}) {
        if (this._workflowPolicyHasAnyFlagFromAttrs(attrs, this.props.node)) {
            return true;
        }
        const policyId = this._getNodePolicyId({ attrs });
        if (!policyId) {
            return false;
        }
        return this._workflowPolicyDomainKinds().some((kind) =>
            this.isWorkflowPolicyDomainConfigured(this._workflowPolicyReferenceDomainFromCache(policyId, kind))
        );
    }

    getWorkflowDomainDialogTitle(kind) {
        const isGroupTarget = this.isWorkflowVisibleContainerNode();
        if (kind === "readonly") {
            return _t("Workflow Readonly Condition");
        }
        if (kind === "required") {
            return _t("Workflow Required Condition");
        }
        return isGroupTarget ? _t("Workflow Section Visible Condition") : _t("Workflow Visible Condition");
    }

    getWorkflowDomainHelpText(kind) {
        const isGroupTarget = this.isWorkflowVisibleContainerNode();
        if (kind === "readonly") {
            return _t("When this domain matches, the field is locked from editing. This rule does not depend on Approve/Rework/Reject/Submit actions. If the field is hidden, hidden still wins.");
        }
        if (kind === "required") {
            return _t("When this domain matches, the field must be filled. This rule may depend on Approve/Rework/Reject/Submit through wf_action_key, unless workflow visibility or readonly rules make the field hidden or locked.");
        }
        if (isGroupTarget) {
            return _t("When this domain matches, this section/column is shown. This rule does not depend on workflow actions. When it does not match, the full section/column is hidden.");
        }
        return _t("When this domain matches, the field is shown on the workflow request form. This rule does not depend on Approve/Rework/Reject/Submit actions.");
    }

    getWorkflowVisibleLabel() {
        return this.isWorkflowVisibleContainerNode()
            ? _t("Visible when (Section/Column)")
            : _t("Visible when");
    }

    onWorkflowPresetInputChange(fieldName, event) {
        const value = event?.target?.value || "";
        this.workflowPresetState[fieldName] = value;
    }

    _normalizedPresetToken(value) {
        return (value || "").trim();
    }

    _quotedPresetToken(value) {
        return JSON.stringify(this._normalizedPresetToken(value));
    }

    _buildAndDomain(tupleClauses = []) {
        const clauses = (tupleClauses || []).filter(Boolean);
        if (!clauses.length) {
            return "";
        }
        if (clauses.length === 1) {
            return `[${clauses[0]}]`;
        }
        let expr = `['&', ${clauses[0]}, ${clauses[1]}]`;
        for (let index = 2; index < clauses.length; index++) {
            expr = `['&', ${expr}, ${clauses[index]}]`;
        }
        return expr;
    }

    onSimpleBuilderInputChange(fieldName, event) {
        const value = event?.target?.value || "";
        this.simpleBuilderState[fieldName] = value;
    }

    onSimpleBuilderToggleRequireOnAction(value) {
        this.simpleBuilderState.requireOnAction = !!value;
    }

    _getSimpleActorClause() {
        const actorType = (this.simpleBuilderState.actorType || "").trim();
        if (actorType === "request_owner") {
            return "('request_owner_id', '=', wf_actor_uid)";
        }
        if (actorType === "hod") {
            return "('wf_actor_is_hod', '=', True)";
        }
        if (actorType === "manager") {
            return "('wf_actor_is_manager', '=', True)";
        }
        if (actorType === "login") {
            const login = this._normalizedPresetToken(this.simpleBuilderState.actorLogin).toLowerCase();
            if (!login) {
                return "";
            }
            return `('wf_actor_login', '=', ${JSON.stringify(login)})`;
        }
        if (actorType === "group") {
            const groupXmlid = this._normalizedPresetToken(this.simpleBuilderState.actorGroupXmlid);
            if (!groupXmlid) {
                return "";
            }
            return `('wf_actor_group_xmlids', 'ilike', ${JSON.stringify(`,${groupXmlid},`)})`;
        }
        return "";
    }

    _getSimpleBaseDomain() {
        const actorClause = this._getSimpleActorClause();
        if (!actorClause) {
            return "";
        }
        const clauses = [actorClause];
        const nodeId = this._normalizedPresetToken(this.simpleBuilderState.nodeId);
        if (nodeId) {
            clauses.push(`('wf_current_node_id', '=', ${JSON.stringify(nodeId)})`);
        }
        return this._buildAndDomain(clauses);
    }

    _getSimpleRequiredDomain() {
        const base = this._getSimpleBaseDomain();
        if (!base) {
            return "";
        }
        if (!this.simpleBuilderState.requireOnAction) {
            return base;
        }
        const actionKey = this._normalizedPresetToken(this.simpleBuilderState.actionKey).toLowerCase();
        if (!actionKey) {
            return "";
        }
        const actionClause = `('wf_action_key', 'ilike', ${JSON.stringify(actionKey)})`;
        const baseNoBrackets = base.trim();
        // base is always a list literal like "[...]", so convert back into clause list by wrapping.
        return `['&', ${baseNoBrackets}, ${actionClause}]`;
    }

    hasSimpleBuilderRequiredInput() {
        const actorType = (this.simpleBuilderState.actorType || "").trim();
        if (actorType === "login") {
            return !!this._normalizedPresetToken(this.simpleBuilderState.actorLogin);
        }
        if (actorType === "group") {
            return !!this._normalizedPresetToken(this.simpleBuilderState.actorGroupXmlid);
        }
        return ["request_owner", "hod", "manager"].includes(actorType);
    }

    applySimpleBuilderEditRule() {
        if (!this.hasSimpleBuilderRequiredInput()) {
            this.notification?.add(_t("Please complete the actor input in Simple Rule Builder."), {
                type: "warning",
            });
            return;
        }
        const baseDomain = this._getSimpleBaseDomain();
        if (!baseDomain) {
            this.notification?.add(_t("Simple rule could not be generated. Please check inputs."), {
                type: "warning",
            });
            return;
        }
        this._applyWorkflowDomainChanges({
            visible: baseDomain, readonly: baseDomain,
        });
    }

    applySimpleBuilderRequiredRule() {
        if (!this.hasSimpleBuilderRequiredInput()) {
            this.notification?.add(_t("Please complete the actor input in Simple Rule Builder."), {
                type: "warning",
            });
            return;
        }
        const requiredDomain = this._getSimpleRequiredDomain();
        if (!requiredDomain) {
            this.notification?.add(_t("Simple required rule could not be generated. Please check inputs."), {
                type: "warning",
            });
            return;
        }
        this._applyWorkflowDomainChanges({
            required: requiredDomain,
        });
    }

    applySimpleBuilderAll() {
        if (!this.hasSimpleBuilderRequiredInput()) {
            this.notification?.add(_t("Please complete the actor input in Simple Rule Builder."), {
                type: "warning",
            });
            return;
        }
        const baseDomain = this._getSimpleBaseDomain();
        if (!baseDomain) {
            this.notification?.add(_t("Simple rule could not be generated. Please check inputs."), {
                type: "warning",
            });
            return;
        }
        this._applyWorkflowDomainChanges({
            visible: baseDomain,
            readonly: baseDomain,
            required: this._getSimpleRequiredDomain() || baseDomain,
        });
    }

    getConfiguredVisibleWorkflowDomain() {
        const visibleDomain = this.extractWorkflowDomain("visible");
        if (!this.isWorkflowPolicyDomainConfigured(visibleDomain)) {
            return "";
        }
        return this.normalizeWorkflowDomainValue(visibleDomain);
    }

    hasConfiguredVisiblePolicyDomain() {
        return !!this.getConfiguredVisibleWorkflowDomain();
    }

    _getNodePolicyId(node = this.props.node) {
        return false;
    }

    _snapshotNodeAttributes(node) {
        const attrs = {};
        for (const attrName of node?.getAttributeNames?.() || []) {
            attrs[attrName] = node.getAttribute(attrName);
        }
        return attrs;
    }

    _collectWorkflowFieldTargets() {
        return collectWorkflowFieldTargets(this.env);
    }

    _configuredDomainChangesByKind(kinds = []) {
        const changes = {};
        for (const kind of kinds || []) {
            if (!this.supportsWorkflowPolicyKind(kind)) {
                continue;
            }
            const domainValue = this.normalizeWorkflowDomainValue(this.extractWorkflowDomain(kind));
            if (!this.isWorkflowPolicyDomainConfigured(domainValue)) {
                continue;
            }
            changes[kind] = domainValue;
        }
        return changes;
    }

    _clearWorkflowPolicyCache() {
        for (const key of Object.keys(this.workflowPolicyCache)) {
            delete this.workflowPolicyCache[key];
        }
    }

    _buildWorkflowDomainOperation(domainChangesByKind = {}) {
        const operationAttrs = this.isWorkflowVisibleContainerNode()
            ? { invisible: "False" }
            : { invisible: "False", readonly: "False", required: "False" };
        return {
            new_attrs: operationAttrs,
            type: "attributes",
            position: "attributes",
            target: this.env.viewEditorModel.getFullTarget(this.props.node.xpath),
        };
    }

    _applyWorkflowDomainChanges(domainChangesByKind = {}) {
        const policyId = this._getNodePolicyId();
        if (policyId) {
            delete this.workflowPolicyCache[this._workflowPolicyCacheKey(policyId)];
        }
        const operation = this._buildWorkflowDomainOperation(domainChangesByKind);
        this.env.viewEditorModel.doOperation(operation);
    }

    onChangeWorkflowDomain(kind, domainExpression) {
        if (!this.supportsWorkflowPolicyKind(kind)) {
            return;
        }
        this._applyWorkflowDomainChanges({ [kind]: domainExpression });
    }

    copyVisibleDomainToPolicy(kind) {
        const visibleDomain = this.getConfiguredVisibleWorkflowDomain();
        if (!visibleDomain) {
            this.notification?.add(_t("Configure Workflow Visible first, then copy it."), {
                type: "warning",
            });
            return;
        }
        this._applyWorkflowDomainChanges({ [kind]: visibleDomain });
    }

    applyVisibleDomainToAllPolicies() {
        const visibleDomain = this.getConfiguredVisibleWorkflowDomain();
        if (!visibleDomain) {
            this.notification?.add(_t("Configure Workflow Visible first, then apply to all."), {
                type: "warning",
            });
            return;
        }
        this._applyWorkflowDomainChanges({
            visible: visibleDomain,
            readonly: visibleDomain,
            required: visibleDomain,
        });
    }

    applyPresetSubmitActorEditable() {
        const submitNodeId = this._normalizedPresetToken(this.workflowPresetState.submitNodeId);
        if (!submitNodeId) {
            this.notification?.add(_t("Please enter Submit Node ID."), { type: "warning" });
            return;
        }
        const domain = `['&', ('wf_current_node_id', '=', ${this._quotedPresetToken(submitNodeId)}), ('request_owner_id', '=', wf_actor_uid)]`;
        this._applyWorkflowDomainChanges({
            visible: domain, readonly: domain,
        });
    }

    applyPresetHodEditable() {
        const hodNodeId = this._normalizedPresetToken(this.workflowPresetState.hodNodeId);
        if (!hodNodeId) {
            this.notification?.add(_t("Please enter HOD Node ID."), { type: "warning" });
            return;
        }
        const domain = `['&', ('wf_current_node_id', '=', ${this._quotedPresetToken(hodNodeId)}), ('wf_actor_is_hod', '=', True)]`;
        this._applyWorkflowDomainChanges({
            visible: domain, readonly: domain,
        });
    }

    applyPresetHodApproveRequired() {
        const hodNodeId = this._normalizedPresetToken(this.workflowPresetState.hodNodeId);
        const approveActionKey = this._normalizedPresetToken(this.workflowPresetState.approveActionKey);
        if (!hodNodeId) {
            this.notification?.add(_t("Please enter HOD Node ID."), { type: "warning" });
            return;
        }
        if (!approveActionKey) {
            this.notification?.add(_t("Please enter Approve Action Key."), {
                type: "warning",
            });
            return;
        }
        const requiredDomain = `['&','&', ('wf_current_node_id', '=', ${this._quotedPresetToken(hodNodeId)}), ('wf_actor_is_hod', '=', True), ('wf_action_key', 'ilike', ${this._quotedPresetToken(approveActionKey.toLowerCase())})]`;
        this._applyWorkflowDomainChanges({ required: requiredDomain });
    }

    applyPresetHodFull() {
        const hodNodeId = this._normalizedPresetToken(this.workflowPresetState.hodNodeId);
        const approveActionKey = this._normalizedPresetToken(this.workflowPresetState.approveActionKey);
        if (!hodNodeId) {
            this.notification?.add(_t("Please enter HOD Node ID."), { type: "warning" });
            return;
        }
        if (!approveActionKey) {
            this.notification?.add(_t("Please enter Approve Action Key."), {
                type: "warning",
            });
            return;
        }
        const visibleReadonlyDomain = `['&', ('wf_current_node_id', '=', ${this._quotedPresetToken(hodNodeId)}), ('wf_actor_is_hod', '=', True)]`;
        const requiredDomain = `['&','&', ('wf_current_node_id', '=', ${this._quotedPresetToken(hodNodeId)}), ('wf_actor_is_hod', '=', True), ('wf_action_key', 'ilike', ${this._quotedPresetToken(approveActionKey.toLowerCase())})]`;
        this._applyWorkflowDomainChanges({
            visible: visibleReadonlyDomain, readonly: visibleReadonlyDomain, required: requiredDomain,
        });
    }

    isWorkflowPolicyEnabled(kind) {
        if (!this.supportsWorkflowPolicyKind(kind)) {
            return false;
        }
        return this.hasWorkflowPolicyDomain(kind);
    }

    onWorkflowPolicyToggle(kind, enabled) {
        if (!this.supportsWorkflowPolicyKind(kind)) {
            return;
        }
        if (!enabled) {
            this.onChangeWorkflowDomain(kind, "");
            return;
        }

        const current = this.extractWorkflowDomain(kind);
        if (current && current !== this.getWorkflowPolicyDefaultDomain()) {
            this.onChangeWorkflowDomain(kind, current);
            return;
        }

        const policyId = this._getNodePolicyId();
        if (policyId) {
            const referenceDomain = this._workflowPolicyReferenceDomainFromCache(policyId, kind);
            if (referenceDomain && referenceDomain !== this.getWorkflowPolicyDefaultDomain()) {
                this.onChangeWorkflowDomain(kind, referenceDomain);
                return;
            }
        }

        this.onChangeWorkflowDomain(kind, this.getWorkflowPolicyEnabledDomain());
    }

    extractWorkflowFieldDomain() {
        return this.extractWorkflowDomain("visible");
    }

    extractWorkflowDomain(kind) {
        if (!this.supportsWorkflowPolicyKind(kind)) {
            return this.getWorkflowPolicyDefaultDomain();
        }
        const policyId = this._getNodePolicyId();
        if (policyId) {
            const cached = this._workflowPolicyReferenceDomainFromCache(policyId, kind);
            if (cached) {
                return cached;
            }
        }
        return this.getWorkflowPolicyDefaultDomain();
    }

    hasWorkflowPolicyDomain(kind) {
        if (!this.supportsWorkflowPolicyKind(kind)) {
            return false;
        }
        const attrs = this.props.node?.attrs || {};
        // If checkbox flag says "configured", treat as configured even before cache loads
        if (this._workflowPolicyHasFlagFromAttrs(attrs, kind)) {
            return true;
        }
        const domain = this.extractWorkflowDomain(kind);
        return this.isWorkflowPolicyDomainConfigured(domain);
    }

    getWorkflowPolicyStatusLabel(kind) {
        return this.hasWorkflowPolicyDomain(kind) ? _t("Configured") : "";
    }

    _getWorkflowRequestFieldHints() {
        const fields = this.env?.viewEditorModel?.fields || {};
        const hintsByName = new Map();
        for (const [name, field] of Object.entries(fields)) {
            if (!name) {
                continue;
            }
            hintsByName.set(name, {
                name,
                field_description: field?.string || field?.label || name,
                ttype: field?.type || field?.ttype || "char",
                relation: field?.relation || "",
                selection: Array.isArray(field?.selection) ? field.selection : [],
            });
        }
        for (const item of this._collectWorkflowFieldTargets()) {
            if (!item?.name) {
                continue;
            }
            const existing = hintsByName.get(item.name) || {};
            hintsByName.set(item.name, {
                ...existing,
                name: item.name,
                field_description: existing.field_description || item.label || item.name,
                ttype: existing.ttype || item.type || "char",
                relation: existing.relation || item.relation || "",
                selection: Array.isArray(existing.selection) && existing.selection.length
                    ? existing.selection
                    : (Array.isArray(item.selection) ? item.selection : []),
            });
        }
        return Array.from(hintsByName.values()).sort((left, right) => {
            const l = `${left.field_description || left.name || ""}`.toLowerCase();
            const r = `${right.field_description || right.name || ""}`.toLowerCase();
            return l.localeCompare(r);
        });
    }

    async onWorkflowPolicyButtonClicked(kind) {
        if (!this.supportsWorkflowPolicyKind(kind)) {
            return;
        }
        const resModel = `${this.env?.viewEditorModel?.resModel || ""}`.trim();
        if (!resModel) {
            this.notification?.add(
                _t("Cannot open Domain Builder because model context is missing."),
                { type: "warning" }
            );
            return;
        }
        await this._prefetchWorkflowPolicyDomains(this.props.node, true);
        const requestFields = this._getWorkflowRequestFieldHints();
        const workflowContext = this.env?.viewEditorModel?._studio?.editedAction?.context || {};
        const workflowVersionId = Number(workflowContext.workflow_version_id || 0) || 0;
        const workflowCategoryId = Number(workflowContext.workflow_category_id || 0) || 0;
        this.addDialog(WorkflowStudioDomainDialog, {
            resModel,
            requestModel: resModel,
            requestFields,
            workflowVersionId,
            workflowCategoryId,
            domain: this.extractWorkflowDomain(kind),
            domainKind: kind,
            contextType: "field_modifiers",
            title: this.getWorkflowDomainDialogTitle(kind),
            helpText: this.getWorkflowDomainHelpText(kind),
            isDebugMode: !!this.env.debug,
            onConfirm: (domainExpression) => this.onChangeWorkflowDomain(kind, domainExpression),
            onApplyWorkflowScenario: (domainsByKind = {}) => this._applyWorkflowDomainChanges(domainsByKind),
        });
    }

    isIndeterminate(value) {
        return value && !this.isBooleanExpression(value);
    }

    isBooleanExpression(expression) {
        return ["1", "0", "True", "true", "False", "false"].includes(expression);
    }

    isBoolTrue(value) {
        if (typeof value === "boolean") {
            return value;
        }
        return ["1", "True", "true"].includes(value);
    }

    valueAsBoolean(expression) {
        if (!expression) {
            return false;
        }
        if (this.isBooleanExpression(expression)) {
            return this.isBoolTrue(expression);
        }
        return true;
    }

    onConditionalButtonClicked(name, value) {
        if (typeof value !== "string" || value === "") {
            value = "False"; // See py.js:evaluateBooleanExpr default value is False
        }
        const { fields, resModel } = this.env.viewEditorModel;
        this.addDialog(ExpressionEditorDialog, {
            resModel, fields, expression: value, onConfirm: (expression) => this.onChangeModifier(name, expression),
        });
    }
}
