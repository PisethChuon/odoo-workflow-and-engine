import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { afterEach, describe, expect, test } from "@odoo/hoot";
import { edit, queryAllTexts, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { contains, mountWithCleanup } from "@web/../tests/web_test_helpers";
import {
    ensureBpmnDiagramXml,
    extractImportableBpmnXml,
    resolveWorkflowContextIds,
    WorkflowStudioApprovalGroupBrowserDialog,
    WorkflowStudioApprovalGroupDialog,
    WorkflowStudioApprovalGroupLinkDialog,
    WorkflowStudioBpmnEditor,
    WorkflowStudioCreateActionWindowDialog,
    WorkflowStudioNotificationChannelBrowserDialog,
    WorkflowStudioWorkflowActionDialog,
} from "@workflow_studio/client_action/bpmn_editor/bpmn_editor";

describe.current.tags("desktop");

defineMailModels();

afterEach(() => document.body.classList.remove("o_in_workflow_studio"));

function makeApprovalGroupEditor({
    approvalGroups = [],
    approvalLinkRows = [],
    query = "",
    mode = "all",
    routingFilter = "all",
    versionId = 99,
    selectedTask = {node_id: "Task_Review", name: "Review Request"},
} = {}) {
    const editor = Object.create(WorkflowStudioBpmnEditor.prototype);
    const linkedGroupIds = new Set(
        (approvalLinkRows || [])
            .map((row) => Number(row?.approval_group_ref?.id || row?.approval_group_id || 0))
            .filter(Boolean)
    );
    editor.state = {
        payload: {
            options: {
                approval_groups: approvalGroups,
            },
        },
        approvalLinkRows,
        approvalGroupCatalogQuery: query,
        approvalGroupCatalogRows: [],
        approvalGroupCatalogTotal: 0,
        approvalGroupCatalogTotalGroups: approvalGroups.length,
        approvalGroupCatalogLinkedCount: linkedGroupIds.size,
        approvalGroupCatalogHasMore: false,
        approvalGroupCatalogPending: false,
        approvalGroupCatalogMode: mode,
        approvalGroupCatalogRoutingFilter: routingFilter,
        selectedTask,
        versionId,
    };
    editor._approvalGroupCatalogSearchTimer = null;
    editor._approvalGroupCatalogScheduledResolver = null;
    editor._approvalGroupCatalogSearchSequence = 0;
    return editor;
}

test("bpmn create action dialog keeps model-aware backend defaults", async () => {
    expect.assertions(2);

    await mountWithCleanup(WorkflowStudioCreateActionWindowDialog, {
        props: {
            close: () => {},
            confirm: (values) => {
                expect(values).toEqual({
                    name: "Open Request",
                    view_mode: "",
                    target: "",
                });
                return true;
            },
        },
    });
    await animationFrame();

    expect("select.o_input").toHaveValue("");
    await contains("input[placeholder='e.g. Open Request Form']").click();
    await edit("Open Request");
    await contains(".modal-footer .btn-primary").click();
});

test("bpmn create action dialog supports explicit overrides", async () => {
    expect.assertions(1);

    await mountWithCleanup(WorkflowStudioCreateActionWindowDialog, {
        props: {
            close: () => {},
            confirm: (values) => {
                expect(values).toEqual({
                    name: "Open Wizard",
                    view_mode: "form",
                    target: "new",
                });
                return true;
            },
        },
    });
    await animationFrame();

    await contains("input[placeholder='e.g. Open Request Form']").click();
    await edit("Open Wizard");
    await contains("input[placeholder='e.g. list,form']").click();
    await edit("form");
    await contains("select.o_input").select("new");
    await contains(".modal-footer .btn-primary").click();
});

test("workflow context resolution uses explicit workflow ids first", () => {
    const ids = resolveWorkflowContextIds({
        context: {
            workflow_category_id: 42,
            workflow_version_id: 84,
        },
        actionResModel: "workflow.approval.category",
        actionResId: 9,
    });
    expect(ids).toEqual({ categoryId: 42, versionId: 84 });
});

test("workflow context resolution falls back to current category record", () => {
    const ids = resolveWorkflowContextIds({
        context: {},
        routeState: {},
        actionResModel: "workflow.approval.category",
        controllerResId: 73,
    });
    expect(ids).toEqual({ categoryId: 73, versionId: null });
});

test("workflow context resolution falls back to current version record", () => {
    const ids = resolveWorkflowContextIds({
        context: {},
        routeState: {},
        actionResModel: "workflow.approval.category.version",
        actionResId: 65,
    });
    expect(ids).toEqual({ categoryId: null, versionId: 65 });
});

test("extractImportableBpmnXml extracts BPMN payload from Odoo data XML", () => {
    const odooXml = `<?xml version="1.0" encoding="utf-8"?>
<odoo>
  <data>
    <record id="x_demo" model="workflow.approval.category.version">
      <field name="bpmn_xml"><![CDATA[
        <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_Test">
          <bpmn:process id="Process_Test" />
        </bpmn:definitions>
      ]]></field>
    </record>
  </data>
</odoo>`;

    const extracted = extractImportableBpmnXml(odooXml);
    expect(extracted).toContain("<bpmn:definitions");
    expect(extracted).toContain("Process_Test");
});

test("ensureBpmnDiagramXml adds bpmndi layout when diagram section is missing", () => {
    const xmlWithoutDiagram = `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_Auto">
  <bpmn:process id="Process_Auto">
    <bpmn:startEvent id="Start_1"/>
    <bpmn:userTask id="Task_1"/>
    <bpmn:endEvent id="End_1"/>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_1"/>
    <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="End_1"/>
  </bpmn:process>
</bpmn:definitions>`;

    const normalized = ensureBpmnDiagramXml(xmlWithoutDiagram);
    expect(normalized).toContain("bpmndi:BPMNDiagram");
    expect(normalized).toContain("bpmndi:BPMNShape");
    expect(normalized).toContain("bpmndi:BPMNEdge");
});

test("end node shows meta fields but keeps human-task-only sections hidden", () => {
    const endNodeEditor = {
        state: {
            selectedTask: {
                is_end_node: true,
            },
        },
        isHumanTaskNode: false,
        _isTaskType: () => false,
    };

    const metaFieldsGetter = Object.getOwnPropertyDescriptor(
        WorkflowStudioBpmnEditor.prototype,
        "showTaskMetaFieldsSection"
    ).get;
    const approvalGroupsGetter = Object.getOwnPropertyDescriptor(
        WorkflowStudioBpmnEditor.prototype,
        "showTaskApprovalGroupsSection"
    ).get;

    expect(metaFieldsGetter.call(endNodeEditor)).toBe(true);
    expect(approvalGroupsGetter.call(endNodeEditor)).toBe(false);
});

test("user task keeps existing meta field and approval group sections", () => {
    const humanTaskEditor = {
        state: {
            selectedTask: {
                is_end_node: false,
            },
        },
        isHumanTaskNode: true,
        _isTaskType: () => true,
    };

    const metaFieldsGetter = Object.getOwnPropertyDescriptor(
        WorkflowStudioBpmnEditor.prototype,
        "showTaskMetaFieldsSection"
    ).get;
    const approvalGroupsGetter = Object.getOwnPropertyDescriptor(
        WorkflowStudioBpmnEditor.prototype,
        "showTaskApprovalGroupsSection"
    ).get;

    expect(metaFieldsGetter.call(humanTaskEditor)).toBe(true);
    expect(approvalGroupsGetter.call(humanTaskEditor)).toBe(true);
});

test("conditional event sequence flow hides runtime domain guard", () => {
    const editor = Object.create(WorkflowStudioBpmnEditor.prototype);
    editor.state = {
        selectedAction: {
            source_id: "Event_Check",
            flow_type: "noEmailAction",
            target_node_type: "userTask",
        },
        selectedElement: {
            id: "Flow_Matched",
            type: "bpmn:SequenceFlow",
        },
    };
    editor.modeler = {
        get: () => ({
            get: (id) => ({id, type: id === "Flow_Matched" ? "bpmn:SequenceFlow" : "bpmn:IntermediateCatchEvent"}),
        }),
    };
    editor._getEngineNodeType = (element) => (
        element?.id === "Event_Check" ? "conditionalEventDefinition" : "userTask"
    );

    const routeDomainGetter = Object.getOwnPropertyDescriptor(
        WorkflowStudioBpmnEditor.prototype,
        "showSequenceFlowRouteDomainSection"
    ).get;
    const defaultFlowGetter = Object.getOwnPropertyDescriptor(
        WorkflowStudioBpmnEditor.prototype,
        "showConditionalDefaultFlowSection"
    ).get;

    expect(defaultFlowGetter.call(editor)).toBe(true);
    expect(routeDomainGetter.call(editor)).toBe(false);
});

test("meta field row serialization preserves per-rule domains", () => {
    const editor = Object.create(WorkflowStudioBpmnEditor.prototype);
    const [row] = editor._serializeMetaFieldRows([
        {
            field_key: "x.it.request::x_item_line_id",
            field_types: ["visible", "required"],
            activity_action_keys: ["Task_Submit|Event_Submit"],
            domains_by_type: {
                visible: "[('x_item_line_id', '!=', False)]",
                required: "[('x_amount_total', '>=', 1000)]",
            },
        },
    ]);

    expect(row.domains_by_type).toEqual({
        visible: "[('x_item_line_id', '!=', False)]",
        required: "[('x_amount_total', '>=', 1000)]",
    });
    expect(row.visible_domain).toBe("[('x_item_line_id', '!=', False)]");
    expect(row.required_domain).toBe("[('x_amount_total', '>=', 1000)]");
});

test("persisted single meta field rows merge without clearing visible domain", () => {
    const editor = Object.create(WorkflowStudioBpmnEditor.prototype);
    const [row] = editor._mergeMetaFieldRows([
        {
            id: 9,
            task_node_id: "Task_Submit",
            field_type: "visible",
            field_ref: {
                model: "x.it.request",
                name: "x_item_line_id",
            },
            domain: "[('x_item_line_id', '!=', False)]",
            visible_domain: "[('x_item_line_id', '!=', False)]",
            required_domain: "[]",
            domains_by_type: {
                visible: "[('x_item_line_id', '!=', False)]",
            },
        },
        {
            id: 10,
            task_node_id: "Task_Submit",
            field_type: "required",
            field_ref: {
                model: "x.it.request",
                name: "x_item_line_id",
            },
            domain: "[]",
            visible_domain: "[]",
            required_domain: "[]",
            domains_by_type: {
                required: "[]",
            },
        },
    ]);

    expect(row.field_types).toEqual(["visible", "required"]);
    expect(row.domains_by_type.visible).toBe("[('x_item_line_id', '!=', False)]");
    expect(row.domains_by_type.required).toBe("[]");
});

test("approval group send-email source shows advanced filter domain", () => {
    const editor = Object.create(WorkflowStudioBpmnEditor.prototype);
    editor.state = {
        selectedTask: {
            notification_delivery_mode: "email",
            notification_recipient_source: "approval_group_users",
        },
    };
    editor._isTaskType = () => true;

    const domainSectionGetter = Object.getOwnPropertyDescriptor(
        WorkflowStudioBpmnEditor.prototype,
        "showTaskNotificationDomainSection"
    ).get;
    const filterLabelGetter = Object.getOwnPropertyDescriptor(
        WorkflowStudioBpmnEditor.prototype,
        "taskNotificationFilterLabel"
    ).get;

    expect(domainSectionGetter.call(editor)).toBe(true);
    expect(filterLabelGetter.call(editor)).toBe("Advanced Filter Domain");
});

test("selected notification channel search filters linked channels by template text", () => {
    const editor = Object.create(WorkflowStudioBpmnEditor.prototype);
    editor.state = {
        selectedTask: {
            activity_type_ids: [1, 2],
        },
        selectedNotificationChannelQuery: "template b",
    };
    editor.workflowActionOptions = [
        { id: 1, name: "Notify Workforce", action_type: "email", email_template_name: "Template A" },
        { id: 2, name: "Notify Requester", action_type: "email", email_template_name: "Template B" },
        { id: 3, name: "Log Only", action_type: "log" },
    ];

    const selectedGetter = Object.getOwnPropertyDescriptor(
        WorkflowStudioBpmnEditor.prototype,
        "selectedNotificationChannels"
    ).get;

    expect(selectedGetter.call(editor).map((option) => option.id)).toEqual([2]);
});

test("available notification channel search filters existing channels and keeps notification-safe types", () => {
    const editor = Object.create(WorkflowStudioBpmnEditor.prototype);
    editor.state = {
        selectedTask: {
            activity_type_ids: [2],
        },
        notificationChannelQuery: "surveillance",
    };
    editor.workflowActionOptions = [
        { id: 1, name: "Notify Surveillance", action_type: "email", email_template_name: "MTF Complete" },
        { id: 2, name: "Selected Channel", action_type: "email", email_template_name: "Already Used" },
        { id: 3, name: "Surveillance Server Action", action_type: "server_action", server_action_name: "Do Work" },
    ];
    editor._isTaskType = () => true;

    const availableGetter = Object.getOwnPropertyDescriptor(
        WorkflowStudioBpmnEditor.prototype,
        "availableChannelOptions"
    ).get;

    expect(availableGetter.call(editor).map((option) => option.id)).toEqual([1]);
});

test("service executor uses a multi-action tag selector limited to server actions", async () => {
    const editor = Object.create(WorkflowStudioBpmnEditor.prototype);
    editor.state = {
        selectedTask: {
            service_behavior: "executor",
            activity_type_ids: [11, 12],
        },
        payload: {
            options: {
                workflow_actions: [
                    {id: 11, name: "Stockout Medicine", action_type: "server_action"},
                    {id: 12, name: "Sync Medicine", action_type: "server_action"},
                    {id: 13, name: "Notify HOD", action_type: "email"},
                ],
            },
        },
    };
    Object.defineProperty(editor, "isServiceTaskNode", {value: true});
    Object.defineProperty(editor, "isScriptTaskNode", {value: false});
    const updates = [];
    editor.onTaskFieldChange = async (fieldName, value) => {
        updates.push({fieldName, value});
    };

    expect(editor.taskWorkflowActionAllowedTypes).toEqual(["server_action"]);
    expect(editor.selectableTaskWorkflowActionOptions.map((action) => action.id)).toEqual([11, 12]);
    const {update, ...selectorProps} = editor.taskWorkflowActionsProps;
    expect(selectorProps).toEqual({
        resModel: "workflow.approval.action",
        resIds: [11, 12],
        domain: [["id", "in", [11, 12]]],
        fieldString: "Server Actions",
        placeholder: "Select server actions...",
    });
    expect(editor.taskWorkflowActionsHelpText).toContain("Every selected action runs");
    expect(editor.taskServiceBehaviorHelpText).toContain(
        "Executor runs every selected server action"
    );

    await update([12]);
    expect(updates).toEqual([
        {fieldName: "activity_type_ids", value: [12]},
    ]);
});

test("notification channel browser opener resets searches and preserves channel callbacks", async () => {
    const editor = Object.create(WorkflowStudioBpmnEditor.prototype);
    editor.state = {
        selectedTask: {
            node_id: "SendTask_Notify",
            name: "Notify Requester",
            activity_type_ids: [2],
        },
        notificationChannelQuery: "old available search",
        selectedNotificationChannelQuery: "old configured search",
    };
    editor.workflowActionOptions = [
        {id: 1, name: "SMS Alert", action_type: "sms", message_body: "Request updated"},
        {id: 2, name: "Email Requester", action_type: "email", email_template_name: "Request Update"},
        {id: 3, name: "Internal Server Action", action_type: "server_action", server_action_name: "Sync"},
    ];
    Object.defineProperty(editor, "showTaskNotificationSection", {value: true});
    const callbackLog = {create: 0, configure: [], add: [], remove: []};
    editor.createWorkflowActionOnTheFly = (afterConfirm) => {
        callbackLog.create += 1;
        afterConfirm?.();
    };
    editor.configureWorkflowActionOnTheFly = (channelId, afterConfirm) => {
        callbackLog.configure.push(channelId);
        afterConfirm?.();
    };
    editor.addChannelById = async (channelId) => callbackLog.add.push(channelId);
    editor.removeWorkflowActionFromTask = async (channelId) => callbackLog.remove.push(channelId);
    let addedDialog = null;
    editor.dialog = {
        add: (Component, props) => {
            addedDialog = {Component, props};
        },
    };

    editor.openNotificationChannelBrowserDialog();

    expect(editor.state.notificationChannelQuery).toBe("");
    expect(editor.state.selectedNotificationChannelQuery).toBe("");
    expect(addedDialog.Component).toBe(WorkflowStudioNotificationChannelBrowserDialog);
    expect(addedDialog.props.getNodeLabel()).toBe("Notify Requester (SendTask_Notify)");
    expect(addedDialog.props.getConfiguredCount()).toBe(1);
    expect(addedDialog.props.getTotalCount()).toBe(2);
    expect(addedDialog.props.getConfiguredRows().map((row) => row.id)).toEqual([2]);
    expect(addedDialog.props.getAvailableRows().map((row) => row.id)).toEqual([1]);

    addedDialog.props.createChannel(() => {});
    addedDialog.props.configureChannel(2, () => {});
    await addedDialog.props.addChannel(1);
    await addedDialog.props.removeChannel(2);

    expect(callbackLog).toEqual({create: 1, configure: [2], add: [1], remove: [2]});
});

test("destructive node configuration removals require danger confirmation", async () => {
    const editor = Object.create(WorkflowStudioBpmnEditor.prototype);
    editor.state = {
        selectedTask: {
            activity_type_ids: [7],
        },
        payload: {
            options: {
                workflow_actions: [
                    {id: 7, name: "Notify Requester", action_type: "email"},
                ],
            },
        },
        metaFieldRows: [
            {field_key: "x.medical.request::x_accident_venue"},
        ],
        workflowMapRows: [
            {
                called_workflow_ref: {
                    name: "Stock Request",
                    display_name: "Stock Request / V2",
                },
                execution_mode: "sync",
                field_mapping: "{}",
                domain: "[]",
            },
        ],
    };
    const prompts = [];
    let allowRemoval = false;
    let stagedMetaFields = 0;
    let metaRefreshes = 0;
    editor._confirmWithDialog = async (prompt) => {
        prompts.push(prompt);
        return allowRemoval;
    };
    editor._metaFieldShortLabel = () => "Accident Venue";
    editor._stageSelectedMetaFieldRows = () => {
        stagedMetaFields += 1;
    };
    editor.onTaskFieldChange = async (fieldName, value) => {
        editor.state.selectedTask[fieldName] = value;
    };

    expect(await editor.removeWorkflowActionFromTask(7)).toBe(false);
    expect(await editor.removeMetaFieldRow(0, () => {
        metaRefreshes += 1;
    })).toBe(false);
    expect(await editor.removeWorkflowMapRow(0)).toBe(false);
    expect(editor.state.selectedTask.activity_type_ids).toEqual([7]);
    expect(editor.state.metaFieldRows).toHaveLength(1);
    expect(editor.state.workflowMapRows).toHaveLength(1);
    expect(stagedMetaFields).toBe(0);
    expect(metaRefreshes).toBe(0);

    allowRemoval = true;
    expect(await editor.removeWorkflowActionFromTask(7)).toBe(true);
    expect(await editor.removeMetaFieldRow(0, () => {
        metaRefreshes += 1;
    })).toBe(true);
    expect(await editor.removeWorkflowMapRow(0)).toBe(true);
    expect(editor.state.selectedTask.activity_type_ids).toEqual([]);
    expect(editor.state.metaFieldRows).toHaveLength(0);
    expect(editor.state.workflowMapRows).toHaveLength(0);
    expect(stagedMetaFields).toBe(1);
    expect(metaRefreshes).toBe(1);
    expect(prompts.map((prompt) => prompt.title)).toEqual([
        "Remove Notification Channel?",
        "Remove Field Rule?",
        "Remove Workflow Mapping?",
        "Remove Notification Channel?",
        "Remove Field Rule?",
        "Remove Workflow Mapping?",
    ]);
    expect(prompts.every((prompt) => prompt.confirmClass === "btn-danger")).toBe(true);
});

test("notification channel browser renders spaced rows and keeps every management action", async () => {
    document.body.classList.add("o_in_workflow_studio");
    let configuredQuery = "";
    let availableQuery = "";
    const configuredRows = [
        {id: 1, name: "Email Daily Digest", action_type: "email", email_template_name: "Daily Digest"},
        {id: 2, name: "Telegram Duty Team", action_type: "telegram", telegram_webhook_url: "https://example.test/hook"},
    ];
    const availableRows = [
        {id: 3, name: "SMS Escalation", action_type: "sms", message_body: "Escalation required"},
    ];
    const callbackLog = {create: 0, configure: [], add: [], remove: []};

    await mountWithCleanup(WorkflowStudioNotificationChannelBrowserDialog, {
        props: {
            close: () => {},
            getNodeLabel: () => "Notify Requester (SendTask_Notify)",
            getTotalCount: () => 3,
            getConfiguredCount: () => 2,
            getConfiguredQuery: () => configuredQuery,
            setConfiguredQuery: (value) => {
                configuredQuery = value;
            },
            getAvailableQuery: () => availableQuery,
            setAvailableQuery: (value) => {
                availableQuery = value;
            },
            getConfiguredRows: () => configuredRows.filter((row) =>
                row.name.toLowerCase().includes(configuredQuery.toLowerCase())
            ),
            getAvailableRows: () => availableRows.filter((row) =>
                row.name.toLowerCase().includes(availableQuery.toLowerCase())
            ),
            createChannel: (afterConfirm) => {
                callbackLog.create += 1;
                afterConfirm?.();
            },
            configureChannel: (channelId, afterConfirm) => {
                callbackLog.configure.push(channelId);
                afterConfirm?.();
            },
            addChannel: async (channelId) => callbackLog.add.push(channelId),
            removeChannel: async (channelId) => callbackLog.remove.push(channelId),
        },
    });
    await animationFrame();

    expect(queryAllTexts(".o_wfs_notification_channel_browser_dialog .o_wfs_approval_group_browser_summary_card .o_wfs_approval_group_browser_status")).toEqual([
        "2 configured",
        "3 total",
    ]);
    expect(queryAllTexts(".o_wfs_notification_channel_browser_row .o_wfs_approval_group_browser_name")).toEqual([
        "Email Daily Digest",
        "Telegram Duty Team",
        "SMS Escalation",
    ]);
    expect(".o_wfs_notification_channel_browser_dialog .modal-footer .o_wfs_notification_channel_create_btn").toHaveCount(1);
    expect(getComputedStyle(queryOne(".o_wfs_notification_channel_browser_configured_rows")).rowGap).toBe("16px");

    await contains(".o_wfs_notification_channel_configured_search").edit("digest");
    await contains(".o_wfs_notification_channel_available_search").edit("sms");
    await contains(".o_wfs_notification_channel_create_btn").click();
    await contains(".o_wfs_notification_channel_browser_row[data-channel-id='1'] .o_wfs_notification_channel_configure_btn").click();
    await contains(".o_wfs_notification_channel_browser_row[data-channel-id='1'] .o_wfs_notification_channel_remove_btn").click();
    await contains(".o_wfs_notification_channel_browser_row[data-channel-id='3'] .o_wfs_notification_channel_add_btn").click();

    expect(configuredQuery).toBe("digest");
    expect(availableQuery).toBe("sms");
    expect(callbackLog).toEqual({create: 1, configure: [1], add: [3], remove: [1]});
});

test("notification channel request domain dialog uses routing-safe validation and preserves blank domain", () => {
    const dialog = Object.create(WorkflowStudioWorkflowActionDialog.prototype);
    dialog.props = {
        requestModel: "x_medical_request",
        requestFields: [],
        workflowVersionId: 99,
        workflowCategoryId: 42,
        workflowMetaTaskOptions: [],
        workflowTaskNodeOptions: [],
        domainPresetsByKey: {
            routing_request_scope: [
                {key: "always", label: "Always", domain: "[(1, '=', 1)]"},
                {key: "never", label: "Never", domain: "[(0, '=', 1)]"},
            ],
        },
    };
    dialog.state = {
        domain: "",
    };
    let addedDialog = null;
    dialog.dialog = {
        add: (Component, props) => {
            addedDialog = {Component, props};
        },
    };

    dialog.openRequestDomainDialog();

    expect(addedDialog.Component.name).toBe("WorkflowStudioDomainDialog");
    expect(addedDialog.props.domain).toBe("");
    expect(addedDialog.props.contextType).toBe("request_scope_routing");
    expect(addedDialog.props.allowBlankDomain).toBe(true);

    addedDialog.props.onConfirm("");
    expect(dialog.state.domain).toBe("");

    addedDialog.props.onConfirm("[(1, '=', 1)]");
    expect(dialog.state.domain).toBe("[(1, '=', 1)]");
});

test("email recipient line keeps approval-group filter domain when source changes", () => {
    const editor = Object.create(WorkflowStudioWorkflowActionDialog.prototype);
    editor.state = {
        emailRecipientLines: [
            {
                source: "domain",
                domain: "[('id', '=', 7)]",
                raw_emails: "workforce@example.com",
                user_ids: [11],
                approval_group_ids: [22],
                group_ids: [33],
                node_ref: "Task_HOD",
            },
        ],
    };

    editor.updateEmailRecipientLine(0, "source", "approval_group_users");

    expect(editor.state.emailRecipientLines[0].domain).toBe("[('id', '=', 7)]");
    expect(editor.state.emailRecipientLines[0].raw_emails).toBe("");
    expect(editor.state.emailRecipientLines[0].user_ids).toEqual([]);
    expect(editor.state.emailRecipientLines[0].approval_group_ids).toEqual([]);
    expect(editor.state.emailRecipientLines[0].group_ids).toEqual([]);
    expect(editor.state.emailRecipientLines[0].node_ref).toBe("");
});

test("approval group catalog rows sort linked groups first and keep readable member overflow text", () => {
    const editor = makeApprovalGroupEditor({
        approvalGroups: [
            {
                id: 2,
                name: "Front Office",
                display_path: "MTF: Approval Group: Food & Beverage > Front Office",
                department_name: "Operations",
                user_names: ["Sophea"],
            },
            {
                id: 1,
                name: "Food & Beverage",
                display_path: "MTF: Approval Group: Food & Beverage > Beverage",
                department_name: "Food & Beverage",
                user_names: ["Alice", "Bob", "Chan", "Dara"],
            },
            {
                id: 3,
                name: "Spa",
                display_path: "MTF: Approval Group: Spa > Spa > N2 Spa",
                department_name: "Spa",
                user_names: ["Malis", "Nita"],
            },
        ],
        approvalLinkRows: [
            {approval_group_ref: {id: 3, name: "Spa"}},
            {approval_group_ref: {id: 1, name: "Food & Beverage"}},
        ],
    });

    const rows = editor.buildApprovalGroupCatalogRowsFromOptions(editor.approvalGroupOptions);
    expect(rows.map((row) => row.id)).toEqual([1, 3, 2]);
    expect(rows[0].memberPreview).toBe("Alice, Bob, Chan +1 more");
    expect(rows[0].membersSummary).toBe("Alice, Bob, Chan, Dara");
});

test("approval group catalog rows surface blank and empty routing warnings for linked groups", () => {
    const editor = makeApprovalGroupEditor({
        approvalGroups: [
            {
                id: 1,
                name: "Finance",
                display_path: "MTF: Approval Group: Finance > Cost Control",
                department_name: "Finance",
                user_names: ["Dara", "Sokha"],
            },
        ],
        approvalLinkRows: [
            {
                approval_group_ref: {id: 1, name: "Finance"},
                user_domain: "",
                domain: "[]",
            },
        ],
    });

    const [row] = editor.buildApprovalGroupCatalogRowsFromOptions(editor.approvalGroupOptions);
    expect(row.routingWarnings.map((warning) => warning.label)).toEqual([
        "User Filter Blank",
        "Record Domain []",
    ]);
});

test("approval group catalog search matches display path department and member names", () => {
    const editor = makeApprovalGroupEditor({
        approvalGroups: [
            {
                id: 1,
                name: "Front Office",
                display_path: "MTF: Approval Group: Food & Beverage > Front Office",
                department_name: "Operations",
                user_names: ["Mey", "Sokha"],
            },
            {
                id: 2,
                name: "Spa",
                display_path: "MTF: Approval Group: Spa > Spa > N2 Spa",
                department_name: "Wellness",
                user_names: ["Vanna", "Dalin"],
            },
        ],
    });

    const rows = editor.buildApprovalGroupCatalogRowsFromOptions(editor.approvalGroupOptions);

    expect(editor.filterApprovalGroupCatalogRows(rows, {query: "front office"}).map((row) => row.id)).toEqual([1]);

    expect(editor.filterApprovalGroupCatalogRows(rows, {query: "wellness"}).map((row) => row.id)).toEqual([2]);

    expect(editor.filterApprovalGroupCatalogRows(rows, {query: "sokha"}).map((row) => row.id)).toEqual([1]);
});

test("approval group routing filter narrows linked groups that need configuration", () => {
    const editor = makeApprovalGroupEditor({
        approvalGroups: [
            {
                id: 1,
                name: "Finance",
                display_path: "MTF: Approval Group: Finance > Cost Control",
                department_name: "Finance",
                user_names: ["Dara"],
            },
            {
                id: 2,
                name: "Front Office",
                display_path: "MTF: Approval Group: Food & Beverage > Front Office",
                department_name: "Operations",
                user_names: ["Sokha"],
            },
        ],
        approvalLinkRows: [
            {
                approval_group_ref: {id: 1, name: "Finance"},
                user_domain: "",
                domain: "[]",
            },
            {
                approval_group_ref: {id: 2, name: "Front Office"},
                user_domain: "[(1, '=', 1)]",
                domain: "[(1, '=', 1)]",
            },
        ],
    });

    const rows = editor.buildApprovalGroupCatalogRowsFromOptions(editor.approvalGroupOptions);

    expect(editor.filterApprovalGroupCatalogRows(rows, {routingFilter: "needs_config"}).map((row) => row.id)).toEqual([1]);

    expect(editor.filterApprovalGroupCatalogRows(rows, {routingFilter: "domain:ignored_empty"}).map((row) => row.id)).toEqual([1]);

    expect(editor.filterApprovalGroupCatalogRows(rows, {routingFilter: "user_domain:ignored_blank"}).map((row) => row.id)).toEqual([1]);
});

test("approval group catalog browser refresh calls the server with query filter and paging", async () => {
    const editor = makeApprovalGroupEditor({
        approvalGroups: [
            {
                id: 1,
                name: "Front Office",
                display_path: "MTF: Approval Group: Food & Beverage > Front Office",
                department_name: "Operations",
                user_names: ["Mey"],
            },
            {
                id: 2,
                name: "Spa",
                display_path: "MTF: Approval Group: Spa > Spa > N2 Spa",
                department_name: "Wellness",
                user_names: ["Vanna"],
            },
        ],
        query: "finance",
        mode: "linked",
        routingFilter: "needs_config",
    });
    editor.state.approvalLinkRows = [
        {
            approval_group_ref: {id: 9, name: "Finance"},
            user_domain: "",
            domain: "[]",
        },
    ];
    const rpcCalls = [];
    editor.orm = {
        call: async (...args) => {
            rpcCalls.push(args);
            return {
                rows: [
                    {
                        id: 9,
                        name: "Finance",
                        display_path: "MTF: Approval Group: Finance > Cost Control",
                        department_name: "Finance",
                        user_names: ["Dara"],
                        is_linked: true,
                        linked_count: 1,
                        member_preview: "Dara",
                        members_summary: "Dara",
                        routing_warnings: [{key: "user_domain:ignored_blank", label: "User Filter Blank"}],
                    },
                ],
                total: 1,
                total_groups: 22,
                linked_count: 1,
                has_more: false,
            };
        },
    };

    await editor.refreshApprovalGroupCatalogBrowser({immediate: true});

    expect(rpcCalls).toHaveLength(1);
    expect(rpcCalls[0][0]).toBe("workflow.approval.category.version");
    expect(rpcCalls[0][1]).toBe("workflow_studio_browse_approval_groups");
    expect(rpcCalls[0][2]).toEqual([[
        99,
    ], {
        query: "finance",
        mode: "linked",
        routing_filter: "needs_config",
        offset: 0,
        limit: 20,
        approval_link_rows: [
            {
                approval_group_id: 9,
                user_domain: "",
                domain: "[]",
            },
        ],
    }]);
    expect(editor.approvalGroupCatalogRows.map((row) => row.id)).toEqual([9]);
    expect(editor.approvalGroupCatalogRows[0].displayPath).toBe("MTF: Approval Group: Finance > Cost Control");
    expect(editor.state.approvalGroupCatalogTotalGroups).toBe(22);
    expect(editor.hasMoreApprovalGroupCatalogRows).toBe(false);
});

test("approval group unlink and rule removal require explicit confirmation", async () => {
    const approvalGroup = {
        id: 9,
        name: "Finance",
        display_path: "MTF: Approval Group: Finance > Cost Control",
    };
    const approvalLink = {
        approval_group_ref: {id: 9, name: "Finance"},
        sequence: 20,
        user_domain: "[('active', '=', True)]",
        domain: "[('amount_total', '>', 1000)]",
        note: "Finance review",
    };
    const editor = makeApprovalGroupEditor({
        approvalGroups: [approvalGroup],
        approvalLinkRows: [{...approvalLink}],
    });
    const prompts = [];
    let allowRemoval = false;
    editor._confirmWithDialog = async (prompt) => {
        prompts.push(prompt);
        return allowRemoval;
    };
    editor._mutateApprovalLinksAndPersist = async (mutator) => {
        mutator();
        return true;
    };

    expect(await editor.unlinkApprovalGroupFromCatalog(9)).toBe(false);
    expect(editor.state.approvalLinkRows).toHaveLength(1);
    allowRemoval = true;
    expect(await editor.unlinkApprovalGroupFromCatalog(9)).toBe(true);
    expect(editor.state.approvalLinkRows).toHaveLength(0);

    editor.state.approvalLinkRows = [{...approvalLink}];
    allowRemoval = false;
    expect(await editor.removeApprovalLinkRow(0)).toBe(false);
    expect(editor.state.approvalLinkRows).toHaveLength(1);
    allowRemoval = true;
    expect(await editor.removeApprovalLinkRow(0)).toBe(true);
    expect(editor.state.approvalLinkRows).toHaveLength(0);
    expect(prompts.map((prompt) => prompt.title)).toEqual([
        "Unlink Approval Group?",
        "Unlink Approval Group?",
        "Remove Approval Group Rule?",
        "Remove Approval Group Rule?",
    ]);
    expect(prompts.every((prompt) => prompt.confirmClass === "btn-danger")).toBe(true);
    expect(prompts[0].body).toContain("routing sequence, domains, and note");
});

test("approval group catalog load more appends the next server page", async () => {
    const editor = makeApprovalGroupEditor({
        approvalGroups: [],
    });
    editor.orm = {
        call: async (model, method, args) => {
            const options = args[1];
            if (options.offset === 0) {
                return {
                    rows: Array.from({length: 20}, (_, index) => ({
                        id: index + 1,
                        name: `Group ${index + 1}`,
                        display_path: `Department > Group ${index + 1}`,
                        user_names: [],
                        is_linked: false,
                        linked_count: 0,
                        member_preview: "No users assigned",
                        members_summary: "No users assigned",
                        routing_warnings: [],
                    })),
                    total: 45,
                    total_groups: 45,
                    linked_count: 0,
                    has_more: true,
                };
            }
            return {
                rows: Array.from({length: 20}, (_, index) => ({
                    id: 21 + index,
                    name: `Group ${21 + index}`,
                    display_path: `Department > Group ${21 + index}`,
                    user_names: [],
                    is_linked: false,
                    linked_count: 0,
                    member_preview: "No users assigned",
                    members_summary: "No users assigned",
                    routing_warnings: [],
                })),
                total: 45,
                total_groups: 45,
                linked_count: 0,
                has_more: false,
            };
        },
    };

    await editor.refreshApprovalGroupCatalogBrowser({immediate: true});
    expect(editor.approvalGroupCatalogRows).toHaveLength(20);
    expect(editor.hasMoreApprovalGroupCatalogRows).toBe(true);

    await editor.loadMoreApprovalGroupCatalogRows();
    expect(editor.approvalGroupCatalogRows).toHaveLength(40);
    expect(editor.approvalGroupCatalogRows[39].id).toBe(40);
    expect(editor.hasMoreApprovalGroupCatalogRows).toBe(true);
});

test("approval group browser dialog opener resets catalog state and passes node-aware callbacks", () => {
    const editor = makeApprovalGroupEditor({
        approvalGroups: [
            {id: 1, name: "Front Office", display_path: "Front Office", user_names: []},
            {id: 2, name: "Spa", display_path: "Spa", user_names: []},
        ],
        approvalLinkRows: [{approval_group_ref: {id: 2, name: "Spa"}}],
        query: "spa",
        mode: "linked",
        selectedTask: {node_id: "Task_HOD", name: "Head Of Department"},
    });
    let addedDialog = null;
    let refreshCalls = 0;
    editor.dialog = {
        add: (Component, props) => {
            addedDialog = {Component, props};
        },
    };
    editor.refreshApprovalGroupCatalogBrowser = async () => {
        refreshCalls += 1;
        return true;
    };

    editor.openApprovalGroupBrowserDialog();

    expect(editor.state.approvalGroupCatalogQuery).toBe("");
    expect(editor.state.approvalGroupCatalogMode).toBe("all");
    expect(editor.state.approvalGroupCatalogRoutingFilter).toBe("all");
    expect(refreshCalls).toBe(1);
    expect(editor.state.approvalGroupCatalogRows).toHaveLength(2);
    expect(addedDialog.props.getRows()).toHaveLength(2);
    expect(addedDialog.Component).toBe(WorkflowStudioApprovalGroupBrowserDialog);
    expect(addedDialog.props.getNodeLabel()).toBe("Head Of Department (Task_HOD)");
    expect(addedDialog.props.getTotalCount()).toBe(2);
    expect(addedDialog.props.getLinkedCount()).toBe(1);
    expect(addedDialog.props.getRoutingFilter()).toBe("all");
});

test("approval group link and configure flow links first and opens rule settings", async () => {
    const editor = makeApprovalGroupEditor({
        approvalGroups: [{id: 9, name: "Finance", display_path: "Finance", user_names: []}],
        approvalLinkRows: [],
    });
    const openedRowIndexes = [];
    editor.notification = { add: () => {} };
    editor._assertEditableVersion = () => true;
    editor._mutateApprovalLinksAndPersist = async (mutator) => {
        mutator();
        return true;
    };
    editor.openApprovalGroupConfigDialog = (rowIndex) => {
        openedRowIndexes.push(rowIndex);
    };

    const linked = await editor.linkApprovalGroupAndConfigureFromCatalog(9);

    expect(linked).toBe(true);
    expect(editor.state.approvalLinkRows).toHaveLength(1);
    expect(editor.state.approvalLinkRows[0].approval_group_ref).toEqual({id: 9, name: "Finance"});
    expect(openedRowIndexes).toEqual([0]);
});

test("approval group rule settings dialog keeps group selection enabled for linked rows", () => {
    const editor = makeApprovalGroupEditor({
        approvalGroups: [{id: 9, name: "Finance", display_path: "Finance", user_names: []}],
        approvalLinkRows: [{approval_group_ref: {id: 9, name: "Finance"}, sequence: 20}],
    });
    let addedDialog = null;
    editor.notification = { add: () => {} };
    editor._assertEditableVersion = () => true;
    editor.dialog = {
        add: (Component, props) => {
            addedDialog = {Component, props};
        },
    };

    editor.openApprovalGroupConfigDialog(0);

    expect(addedDialog.Component).toBe(WorkflowStudioApprovalGroupLinkDialog);
    expect(addedDialog.props.selectedGroupId).toBe(9);
    expect(addedDialog.props.originGroupId).toBe(9);
    expect(addedDialog.props.allowGroupSelection).toBe(true);
});

test("approval group rule settings can replace the current linked group", async () => {
    const editor = makeApprovalGroupEditor({
        approvalGroups: [
            {id: 9, name: "Finance", display_path: "Finance", user_names: []},
            {id: 12, name: "Spa", display_path: "Spa", user_names: []},
        ],
        approvalLinkRows: [
            {
                approval_group_ref: {id: 9, name: "Finance"},
                sequence: 20,
                user_domain: "[(1, '=', 1)]",
                domain: "",
                note: "Current",
            },
        ],
    });
    const notifications = [];
    editor.notification = {
        add: (message, options = {}) => notifications.push({message, type: options.type}),
    };
    editor._assertEditableVersion = () => true;
    editor._mutateApprovalLinksAndPersist = async (mutator) => {
        mutator();
        return true;
    };

    const saved = await editor.saveApprovalGroupLinkFromDialog(
        12,
        {
            sequence: 35,
            user_domain: "[(0, '=', 1)]",
            domain: "[(1, '=', 1)]",
            note: "Replacement",
        },
        {originGroupId: 9}
    );

    expect(saved).toBe(true);
    expect(notifications).toEqual([]);
    expect(editor.state.approvalLinkRows).toEqual([
        {
            approval_group_ref: {id: 12, name: "Spa"},
            sequence: 35,
            user_domain: "[(0, '=', 1)]",
            domain: "[(1, '=', 1)]",
            note: "Replacement",
        },
    ]);
});

test("approval group rule settings blocks replacing the current link with another already-linked group", async () => {
    const editor = makeApprovalGroupEditor({
        approvalGroups: [
            {id: 9, name: "Finance", display_path: "Finance", user_names: []},
            {id: 12, name: "Spa", display_path: "Spa", user_names: []},
        ],
        approvalLinkRows: [
            {approval_group_ref: {id: 9, name: "Finance"}, sequence: 20},
            {approval_group_ref: {id: 12, name: "Spa"}, sequence: 30},
        ],
    });
    const notifications = [];
    editor.notification = {
        add: (message, options = {}) => notifications.push({message, type: options.type}),
    };
    editor._assertEditableVersion = () => true;
    editor._mutateApprovalLinksAndPersist = async () => true;

    const saved = await editor.saveApprovalGroupLinkFromDialog(
        12,
        {sequence: 30},
        {originGroupId: 9}
    );

    expect(saved).toBe(false);
    expect(notifications).toEqual([
        {
            message: "This approval group is already linked to the selected node. Open its Rule Settings directly or choose another available group.",
            type: "warning",
        },
    ]);
    expect(editor.state.approvalLinkRows).toEqual([
        {approval_group_ref: {id: 9, name: "Finance"}, sequence: 20},
        {approval_group_ref: {id: 12, name: "Spa"}, sequence: 30},
    ]);
});

test("approval group browser dialog renders row actions for large catalogs", async () => {
    document.body.classList.add("o_in_workflow_studio");
    const callbackLog = {
        create: 0,
        edit: [],
        rules: [],
        linkConfigure: [],
        link: [],
        unlink: [],
        loadMore: 0,
    };
    const rows = [
        {
            id: 11,
            key: 11,
            name: "Front Office",
            displayPath: "MTF: Approval Group: Food & Beverage > Front Office",
            department_name: "Operations",
            memberPreview: "Alice, Bob, Chan +1 more",
            membersSummary: "Alice, Bob, Chan, Dara",
            linkedCount: 2,
            isLinked: true,
            routingWarnings: [
                {
                    key: "user_domain:ignored_blank",
                    label: "User Filter Blank",
                    title: "Blank routing domains are ignored.",
                },
                {
                    key: "domain:ignored_empty",
                    label: "Record Domain []",
                    title: "Empty [] routing domains are ignored.",
                },
            ],
        },
        {
            id: 22,
            key: 22,
            name: "Spa",
            displayPath: "MTF: Approval Group: Spa > Spa > N2 Spa",
            department_name: "Wellness",
            memberPreview: "Vanna, Dalin",
            membersSummary: "Vanna, Dalin",
            linkedCount: 0,
            isLinked: false,
        },
    ];

    await mountWithCleanup(WorkflowStudioApprovalGroupBrowserDialog, {
        props: {
            close: () => {},
            getNodeLabel: () => "Head Of Department (Task_HOD)",
            getTotalCount: () => 125,
            getLinkedCount: () => 14,
            getQuery: () => "",
            setQuery: () => {},
            getMode: () => "all",
            setMode: () => {},
            modeOptions: [
                {value: "all", label: "All"},
                {value: "linked", label: "Linked"},
                {value: "available", label: "Not Linked"},
            ],
            getRoutingFilter: () => "needs_config",
            setRoutingFilter: () => {},
            routingFilterOptions: [
                {value: "all", label: "All Routing"},
                {value: "needs_config", label: "Needs Configuration"},
                {value: "user_domain:ignored_blank", label: "User Filter Blank"},
                {value: "domain:ignored_empty", label: "Record Domain []"},
            ],
            getRows: () => rows,
            hasMore: () => true,
            loadMore: () => {
                callbackLog.loadMore += 1;
            },
            createGroup: (afterConfirm) => {
                callbackLog.create += 1;
                afterConfirm?.();
            },
            editGroup: (groupId, afterConfirm) => {
                callbackLog.edit.push(groupId);
                afterConfirm?.();
            },
            editRuleSettings: (groupId, afterConfirm) => {
                callbackLog.rules.push(groupId);
                afterConfirm?.();
            },
            linkGroup: async (groupId) => {
                callbackLog.link.push(groupId);
            },
            linkAndConfigureGroup: async (groupId) => {
                callbackLog.linkConfigure.push(groupId);
            },
            unlinkGroup: async (groupId) => {
                callbackLog.unlink.push(groupId);
            },
        },
    });
    await animationFrame();

    expect(getComputedStyle(queryOne(".modal-content")).borderRadius).toBe("14px");
    expect(getComputedStyle(queryOne(".modal-body")).backgroundColor).toBe(
        "rgb(248, 249, 251)"
    );
    expect(".o_wfs_approval_group_browser_node").toHaveText("Head Of Department (Task_HOD)");
    expect(queryAllTexts(".o_wfs_approval_group_browser_summary_card .o_wfs_approval_group_browser_status")).toEqual([
        "14 linked",
        "125 total",
    ]);
    expect(queryAllTexts(".o_wfs_approval_group_browser_name")).toEqual([
        "MTF: Approval Group: Food & Beverage > Front Office",
        "MTF: Approval Group: Spa > Spa > N2 Spa",
    ]);
    expect(".o_wfs_approval_group_browser_row[data-group-id='11'] .o_wfs_approval_group_browser_meta_line:eq(1)").toHaveText(
        "Members Alice, Bob, Chan +1 more"
    );
    expect(queryAllTexts(".o_wfs_approval_group_browser_warning_badge")).toEqual([
        "User Filter Blank",
        "Record Domain []",
    ]);

    await contains(".o_wfs_approval_group_browser_create_btn").click();
    await contains(".o_wfs_approval_group_browser_load_more_btn").click();
    await contains(".o_wfs_approval_group_browser_row[data-group-id='22'] .o_wfs_approval_group_browser_link_configure_btn").click();
    await contains(".o_wfs_approval_group_browser_row[data-group-id='11'] .o_wfs_approval_group_browser_rule_btn").click();
    await contains(".o_wfs_approval_group_browser_row[data-group-id='11'] .o_wfs_approval_group_browser_edit_btn").click();
    await contains(".o_wfs_approval_group_browser_row[data-group-id='11'] .o_wfs_approval_group_browser_unlink_btn").click();

    expect(callbackLog).toEqual({
        create: 1,
        edit: [11],
        rules: [11],
        linkConfigure: [22],
        link: [],
        unlink: [11],
        loadMore: 1,
    });
});

test("approval group browser dialog normalizes invalid count labels", async () => {
    await mountWithCleanup(WorkflowStudioApprovalGroupBrowserDialog, {
        props: {
            close: () => {},
            getNodeLabel: () => "Head Of Department (Task_HOD)",
            getTotalCount: () => "abc",
            getLinkedCount: () => Number.NaN,
            getQuery: () => "",
            setQuery: () => {},
            getMode: () => "all",
            setMode: () => {},
            modeOptions: [
                {value: "all", label: "All"},
                {value: "linked", label: "Linked"},
                {value: "available", label: "Remaining"},
            ],
            getRoutingFilter: () => "all",
            setRoutingFilter: () => {},
            routingFilterOptions: [{value: "all", label: "All Routing"}],
            getRows: () => [],
            hasMore: () => false,
            loadMore: () => {},
            createGroup: () => {},
            editGroup: () => {},
            editRuleSettings: () => {},
            linkGroup: async () => {},
            linkAndConfigureGroup: async () => {},
            unlinkGroup: async () => {},
        },
    });
    await animationFrame();

    expect(queryAllTexts(".o_wfs_approval_group_browser_summary_card .o_wfs_approval_group_browser_status")).toEqual([
        "0 linked",
        "0 total",
    ]);
    expect(".o_wfs_approval_group_browser_shown_badge").toHaveText("0 shown");
});

test("approval group member summary filters nan placeholders from catalog rows", () => {
    const editor = makeApprovalGroupEditor({
        approvalGroups: [{
            id: 1,
            name: "Finance",
            display_path: "MTF: Approval Group: Finance",
            user_names: ["Alice", "NaN", "", null, "Bob"],
        }],
    });

    const rowsGetter = Object.getOwnPropertyDescriptor(
        WorkflowStudioBpmnEditor.prototype,
        "approvalGroupCatalogRows"
    ).get;
    const [row] = rowsGetter.call(editor);

    expect(editor.getApprovalGroupMemberSummary(editor.approvalGroupOptions[0])).toBe("Alice, Bob");
    expect(row.memberPreview).toBe("Alice, Bob");
    expect(row.userCount).toBe(2);
});

test("approval group create dialog exposes quick routing presets for create-and-link flow", async () => {
    await mountWithCleanup(WorkflowStudioApprovalGroupDialog, {
        props: {
            close: () => {},
            confirm: () => true,
            mode: "create",
            approvalGroups: [],
            approvalLinkRows: [],
            usersOptions: [],
            departmentOptions: [],
            linkConfig: {
                sequence: 10,
                user_domain: "",
                domain: "",
                note: "",
            },
            domainPresetsByKey: {
                routing_user_assignment: [
                    {key: "always", label: "Always", domain: "[(1, '=', 1)]"},
                    {key: "never", label: "Never", domain: "[(0, '=', 1)]"},
                ],
                routing_request_scope: [
                    {key: "always", label: "Always", domain: "[(1, '=', 1)]"},
                    {key: "never", label: "Never", domain: "[(0, '=', 1)]"},
                ],
            },
        },
    });
    await animationFrame();

    expect(queryAllTexts(".o_wfs_approval_group_rule_preset_btn")).toEqual([]);
    expect(queryAllTexts("select.form-select option")).toContain("Apply preset...");
    expect(".o_wfs_approval_group_rule_notice").toHaveText(
        "Blank or [] routing domains are ignored. Choose Always, Never, or build a custom rule before saving if this link should actively route."
    );
});

test("approval group link dialog offers create actions for unmatched search text", async () => {
    const dialog = Object.create(WorkflowStudioApprovalGroupLinkDialog.prototype);
    dialog.props = {
        approvalGroups: [
            {
                id: 1,
                name: "Finance",
                display_path: "MTF: Approval Group: Finance",
                department_name: "Finance",
                user_names: ["Dara"],
            },
        ],
        approvalLinkRows: [],
        linkConfig: {sequence: 10, user_domain: "", domain: "", note: ""},
    };
    dialog.state = {
        selectedGroupId: 0,
        selectedGroupOption: null,
        selectorSearchText: "",
        linkSequence: 10,
        linkUserDomain: "",
        linkDomain: "",
        linkNote: "",
    };

    const options = await dialog.getApprovalGroupSelectorOptions("Front Office");

    expect(options.map((option) => option.label)).toEqual([
        'Create "Front Office"',
        "Create and edit...",
    ]);
});

test("approval group link dialog loads existing node rule when a linked group is selected", () => {
    const dialog = Object.create(WorkflowStudioApprovalGroupLinkDialog.prototype);
    const financeGroup = {
        id: 7,
        name: "Finance",
        display_path: "MTF: Approval Group: Finance > Cost Control",
        department_name: "Finance",
        user_names: ["Dara", "Sokha"],
    };
    dialog.props = {
        approvalGroups: [financeGroup],
        approvalLinkRows: [
            {
                approval_group_ref: {id: 7, name: "Finance"},
                sequence: 35,
                user_domain: "[(1, '=', 1)]",
                domain: "[(0, '=', 1)]",
                note: "Only escalate finance exceptions",
            },
        ],
        linkConfig: {sequence: 10, user_domain: "", domain: "", note: ""},
    };
    dialog.state = {
        selectedGroupId: 0,
        selectedGroupOption: null,
        selectorSearchText: "",
        linkSequence: 10,
        linkUserDomain: "",
        linkDomain: "",
        linkNote: "",
    };

    dialog.selectApprovalGroup(financeGroup);

    expect(dialog.state.selectedGroupId).toBe(7);
    expect(dialog.state.linkSequence).toBe(35);
    expect(dialog.state.linkUserDomain).toBe("[(1, '=', 1)]");
    expect(dialog.state.linkDomain).toBe("[(0, '=', 1)]");
    expect(dialog.state.linkNote).toBe("Only escalate finance exceptions");
});

test("approval group link dialog hides other already-linked groups when replacing a rule group", async () => {
    const dialog = Object.create(WorkflowStudioApprovalGroupLinkDialog.prototype);
    const financeGroup = {
        id: 7,
        name: "Finance",
        display_path: "Finance",
        department_name: "Finance",
        user_names: ["Dara"],
    };
    const spaGroup = {
        id: 9,
        name: "Spa",
        display_path: "Spa",
        department_name: "Wellness",
        user_names: ["Vanna"],
    };
    const frontOfficeGroup = {
        id: 11,
        name: "Front Office",
        display_path: "Front Office",
        department_name: "Operations",
        user_names: ["Alice"],
    };
    dialog.props = {
        approvalGroups: [financeGroup, spaGroup, frontOfficeGroup],
        approvalLinkRows: [
            {approval_group_ref: {id: 7, name: "Finance"}},
            {approval_group_ref: {id: 11, name: "Front Office"}},
        ],
        originGroupId: 7,
        linkConfig: {sequence: 20, user_domain: "", domain: "", note: ""},
    };
    dialog.state = {
        selectedGroupId: 7,
        selectedGroupOption: financeGroup,
        selectorSearchText: "",
        linkSequence: 20,
        linkUserDomain: "",
        linkDomain: "",
        linkNote: "",
    };

    const options = await dialog.getApprovalGroupSelectorOptions("");

    expect(options.map((option) => option.label)).toEqual(["Finance", "Spa"]);
});

test("approval group link dialog renders selected group summary and node-specific save label", async () => {
    await mountWithCleanup(WorkflowStudioApprovalGroupLinkDialog, {
        props: {
            close: () => {},
            confirm: () => true,
            approvalGroups: [
                {
                    id: 11,
                    name: "Front Office",
                    display_path: "MTF: Approval Group: Food & Beverage > Front Office",
                    department_name: "Operations",
                    user_names: ["Alice", "Bob", "Chan"],
                },
            ],
            approvalLinkRows: [
                {
                    approval_group_ref: {id: 11, name: "Front Office"},
                    sequence: 14,
                    user_domain: "[(1, '=', 1)]",
                    domain: "",
                    note: "",
                },
            ],
            usersOptions: [
                {value: 4, label: "Alice"},
                {value: 5, label: "Bob"},
            ],
            departmentOptions: [
                {value: 8, label: "Operations"},
            ],
            selectedGroupId: 11,
            allowGroupSelection: true,
            linkConfig: {sequence: 10, user_domain: "", domain: "", note: ""},
            linkContextLabel: "HOD Decision (Activity_1lacool)",
            domainPresetsByKey: {
                routing_user_assignment: [
                    {key: "always", label: "Always", domain: "[(1, '=', 1)]"},
                    {key: "never", label: "Never", domain: "[(0, '=', 1)]"},
                ],
                routing_request_scope: [
                    {key: "always", label: "Always", domain: "[(1, '=', 1)]"},
                    {key: "never", label: "Never", domain: "[(0, '=', 1)]"},
                ],
            },
        },
    });
    await animationFrame();

    expect(".o_wfs_approval_group_selector_field .o-autocomplete--input").toHaveValue(
        "MTF: Approval Group: Food & Beverage > Front Office"
    );
    expect(".o_wfs_approval_group_selector_summary_path").toHaveText(
        "MTF: Approval Group: Food & Beverage > Front Office"
    );
    expect(queryAllTexts(".o_wfs_approval_group_selector_summary_key")).toEqual([
        "Department",
        "Members",
        "Status",
    ]);
    expect(".o_wfs_approval_group_selector_change_btn").toHaveText("Change Group");
    expect(".o_wfs_approval_group_selector_field_hint").toHaveText(
        "Need a different group? Click Change Group or type in the field to replace the current selection."
    );
    expect(".o_wfs_approval_group_selector_member_count").toHaveText("3 members");
    expect(".o_wfs_approval_group_selector_member_list").toHaveText("Alice, Bob, Chan");
    expect(".modal-footer .btn-primary").toHaveText("Save Rule Settings");
});

test("approval group link dialog explains replacement flow when editing a linked group", () => {
    const dialog = Object.create(WorkflowStudioApprovalGroupLinkDialog.prototype);
    const financeGroup = {
        id: 7,
        name: "Finance",
        display_path: "MTF: Approval Group: Finance",
        department_name: "Finance",
        user_names: ["Dara"],
    };
    const spaGroup = {
        id: 9,
        name: "Spa",
        display_path: "MTF: Approval Group: Spa",
        department_name: "Wellness",
        user_names: ["Vanna"],
    };
    dialog.props = {
        approvalGroups: [financeGroup, spaGroup],
        approvalLinkRows: [
            {
                approval_group_ref: {id: 7, name: "Finance"},
                sequence: 14,
                user_domain: "[(1, '=', 1)]",
                domain: "",
                note: "",
            },
        ],
        selectedGroupId: 7,
        originGroupId: 7,
        allowGroupSelection: true,
        linkConfig: {sequence: 14, user_domain: "[(1, '=', 1)]", domain: "", note: ""},
    };
    dialog.state = {
        selectedGroupId: 7,
        selectedGroupOption: financeGroup,
        selectorSearchText: "",
        linkSequence: 14,
        linkUserDomain: "[(1, '=', 1)]",
        linkDomain: "",
        linkNote: "",
    };

    expect(dialog.dialogTitle).toBe("Approval Group Rule Settings");
    expect(dialog.groupSelectorFieldHint).toBe(
        "This rule currently edits MTF: Approval Group: Finance. Type or click Change Group to replace it with another available group."
    );

    dialog.selectApprovalGroup(spaGroup);

    expect(dialog.selectedGroupStatusLabel).toBe("Will replace current linked group");
    expect(dialog.submitButtonLabel).toBe("Replace Group & Save");
    expect(dialog.selectedGroupSummaryHint).toBe(
        "Saving will replace MTF: Approval Group: Finance on this node and apply the routing rule below."
    );
});
