/** @odoo-module **/

import {_t} from "@web/core/l10n/translation";
import {registry} from "@web/core/registry";
import {useService} from "@web/core/utils/hooks";
import {sprintf} from "@web/core/utils/strings";
import {loadJS, AssetsLoadingError} from "@web/core/assets";
import {router} from "@web/core/browser/router";
import {Dialog} from "@web/core/dialog/dialog";
import {ConfirmationDialog} from "@web/core/confirmation_dialog/confirmation_dialog";
import {standardActionServiceProps} from "@web/webclient/actions/action_service";
import {Component, onMounted, onPatched, onWillStart, onWillUnmount, useRef, useState} from "@odoo/owl";
import {useStudioServiceAsReactive} from "@workflow_studio/studio_service";
import {WorkflowStudioDomainDialog} from "@workflow_studio/client_action/components/workflow_domain_dialog/workflow_domain_dialog";
import {MultiRecordSelector} from "@web/core/record_selectors/multi_record_selector";
import {AutoComplete} from "@web/core/autocomplete/autocomplete";
import {SelectMenu} from "@web/core/select_menu/select_menu";

const DEFAULT_BPMN_XML = `<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
    xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
    xmlns:di="http://www.omg.org/spec/DD/20100524/DI"
    id="Definitions_WorkflowStudio"
    targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_WorkflowStudio" isExecutable="false">
    <bpmn:startEvent id="StartEvent_1" name="Start">
      <bpmn:outgoing>Flow_1</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:userTask id="Task_1" name="Task">
      <bpmn:incoming>Flow_1</bpmn:incoming>
      <bpmn:outgoing>Flow_2</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:endEvent id="EndEvent_1" name="End">
      <bpmn:incoming>Flow_2</bpmn:incoming>
    </bpmn:endEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="Task_1" />
    <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="EndEvent_1" />
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Process_WorkflowStudio">
      <bpmndi:BPMNShape id="StartEvent_1_di" bpmnElement="StartEvent_1">
        <dc:Bounds x="173" y="102" width="36" height="36" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="Task_1_di" bpmnElement="Task_1">
        <dc:Bounds x="260" y="80" width="100" height="80" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="EndEvent_1_di" bpmnElement="EndEvent_1">
        <dc:Bounds x="412" y="102" width="36" height="36" />
      </bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id="Flow_1_di" bpmnElement="Flow_1">
        <di:waypoint x="209" y="120" />
        <di:waypoint x="260" y="120" />
      </bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="Flow_2_di" bpmnElement="Flow_2">
        <di:waypoint x="360" y="120" />
        <di:waypoint x="412" y="120" />
      </bpmndi:BPMNEdge>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>`;
const BPMN_MODEL_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL";
const BPMN_DI_NS = "http://www.omg.org/spec/BPMN/20100524/DI";
const BPMN_DC_NS = "http://www.omg.org/spec/DD/20100524/DC";
const BPMN_DI_WAYPOINT_NS = "http://www.omg.org/spec/DD/20100524/DI";
const BPMN_AUTO_LAYOUT_NODE_NAMES = new Set([
    "startEvent",
    "endEvent",
    "userTask",
    "manualTask",
    "task",
    "serviceTask",
    "sendTask",
    "receiveTask",
    "scriptTask",
    "businessRuleTask",
    "callActivity",
    "subProcess",
    "exclusiveGateway",
    "parallelGateway",
    "inclusiveGateway",
    "eventBasedGateway",
    "complexGateway",
    "intermediateCatchEvent",
    "intermediateThrowEvent",
    "boundaryEvent",
]);
const BPMN_AUTO_LAYOUT_EVENT_NAMES = new Set([
    "startEvent",
    "endEvent",
    "intermediateCatchEvent",
    "intermediateThrowEvent",
    "boundaryEvent",
]);
const BPMN_AUTO_LAYOUT_GATEWAY_NAMES = new Set([
    "exclusiveGateway",
    "parallelGateway",
    "inclusiveGateway",
    "eventBasedGateway",
    "complexGateway",
]);

const SUPPORTED_ENGINE_TASK_NODE_TYPES = new Set([
    "startEvent",
    "startEventMessage",
    "startEventTimer",
    "startEventSignal",
    "startEventConditional",
    "userTask",
    "manualTask",
    "task",
    "serviceTask",
    "sendTask",
    "receiveTask",
    "scriptTask",
    "businessRuleTask",
    "callActivity",
    "subProcess",
    "endEvent",
    "endEventMessage",
    "endEventSignal",
    "endEventTerminate",
    "intermediateCatchEvent",
    "conditionalEventDefinition",
    "intermediateEventSignal",
    "exclusiveGateway",
    "parallelGateway",
    "inclusiveGateway",
    "eventBasedGateway",
    "complexGateway",
]);

const SUPPORTED_ENGINE_ACTION_NODE_TYPES = new Set([
    "intermediateEventMessage",
    "timerEvent",
    "intermediateThrowEvent",
    "intermediateThrowEventMessage",
    "intermediateThrowEventSignal",
]);

const INTERACTIVE_ACTION_NODE_TYPES = new Set([
    "intermediateEventMessage",
    "intermediateThrowEvent",
    "intermediateThrowEventMessage",
    "intermediateThrowEventSignal",
]);

const START_EVENT_NODE_TYPES = new Set([
    "startEvent",
    "startEventMessage",
    "startEventTimer",
    "startEventSignal",
    "startEventConditional",
]);

const END_EVENT_NODE_TYPES = new Set([
    "endEvent",
    "endEventMessage",
    "endEventSignal",
    "endEventTerminate",
]);

const GATEWAY_NODE_TYPES = new Set([
    "exclusiveGateway",
    "parallelGateway",
    "inclusiveGateway",
]);

const HUMAN_TASK_NODE_TYPES = new Set([
    "userTask",
    "manualTask",
    "task",
]);

const COLLABORATION_TASK_NODE_TYPES = new Set([
    "callActivity",
    "subProcess",
    "receiveTask",
]);

const NOTIFICATION_NODE_TYPES = new Set([
    "sendTask",
    "intermediateEventMessage",
    "intermediateThrowEventMessage",
    "intermediateThrowEventSignal",
    "endEventMessage",
    "endEventSignal",
    "startEventMessage",
]);

const MESSAGE_NOTIFICATION_NODE_TYPES = new Set([
    "sendTask",
    "intermediateThrowEventMessage",
    "endEventMessage",
]);

const AUTOMATION_NODE_TYPES = new Set([
    "serviceTask",
    "scriptTask",
    "businessRuleTask",
]);

const ASSIGNMENT_CONFIG_NODE_TYPES = new Set([
    ...HUMAN_TASK_NODE_TYPES,
    ...COLLABORATION_TASK_NODE_TYPES,
]);

const APPROVAL_GROUP_CONFIG_NODE_TYPES = new Set([
    ...HUMAN_TASK_NODE_TYPES,
    "callActivity",
    "subProcess",
]);

const FIELD_RULE_CONFIG_NODE_TYPES = new Set([
    ...HUMAN_TASK_NODE_TYPES,
    ...COLLABORATION_TASK_NODE_TYPES,
    "scriptTask",
    "businessRuleTask",
    ...END_EVENT_NODE_TYPES,
]);

const CONFIDENTIALITY_CONFIG_NODE_TYPES = new Set([
    ...HUMAN_TASK_NODE_TYPES,
    ...COLLABORATION_TASK_NODE_TYPES,
]);

const ALLOWED_PALETTE_ACTIONS = new Set([
    "create.start-event",
    "create.end-event",
    "create.task",
    "create.user-task",
    "create.service-task",
    "create.script-task",
    "create.send-task",
    "create.call-activity",
    "create.intermediate-event",
    "lasso-tool",
    "space-tool",
    "global-connect-tool",
    "hand-tool",
    "tool-separator",
]);

const BLOCKED_CONTEXT_PAD_ACTIONS = new Set([
    "replace",
    "append.text-annotation",
]);

const FIELD_TYPE_OPTIONS = ["visible", "required", "readonly", "invisible"];
const EDITABLE_FIELD_TYPE_OPTIONS = ["visible", "required", "readonly"];
const FIELD_TYPE_PRIORITY = ["visible", "required", "readonly", "invisible"];
const META_FIELD_INLINE_LIMIT = 5;
const AUXILIARY_SHAPE_TYPES = new Set(["label", "bpmn:TextAnnotation"]);
const BPMN_DRAG_MIME = "application/x-workflow-bpmn-shape";
const BPMN_MODELER_LIB_URL = "/workflow_engine/static/lib/bpmn-js/bpmn-modeler.production.min.js";
const APPROVAL_GROUP_PROPERTY_HELP = {
    configured_rules: _t("Total rule rows configured on this selected node."),
    linked_groups: _t("Unique approval groups currently attached to this node."),
    available_groups: _t("Groups available in this category but not linked to this node."),
    existing_groups: _t("Reusable approval groups already defined for this workflow category."),
    auto_save: _t("Link and unlink actions are saved immediately."),
    catalog_link: _t("Attach this group to the selected node and save immediately."),
    catalog_unlink: _t("Detach this group from the selected node and save immediately."),
    configure_group: _t("Open approval group settings (members, department, parent group)."),
    unlink_rule: _t("Remove this linked rule from the selected node and save immediately."),
    rule_group: _t("Approval group used by this rule."),
    rule_sequence: _t("Lower number runs first when evaluating assignment rules."),
    rule_user_domain: _t("Optional filter on users (res.users) to narrow assignees."),
    rule_record_domain: _t("Optional filter on request data to control when this rule applies. Use this for business routing such as Hotel App -> Group A and Casino App -> Group B."),
    rule_user_domain_examples: _t("Examples: [('id', '=', request_owner_id)] or [('id', '=', request_owner_line_manager_user_id)]."),
    rule_record_domain_examples: _t("Examples: [('x_item_line_id', '=', 1)] for Hotel App, [('x_item_line_id', '=', 2)] for Casino App, [('request_owner_id', '=', uid)] or [('state', '=', 'waiting')]."),
    rule_note: _t("Internal note for administrators. Not shown to approvers."),
    save_rules: _t("Save sequence/domain/note edits made in the rule editor below."),
};
const PROPERTY_LABEL_HELP = {
    "node id": _t("Technical BPMN node identifier used by runtime and metadata mapping."),
    "node type": _t("BPMN element type recognized by the workflow engine."),
    name: _t("Display name shown on diagram and in workflow tracking UI."),
    description: _t("Internal description for administrators and maintainers."),
    sequence: _t("Execution order priority. Lower values are evaluated first."),
    label: _t("Short label used by UI and metadata display."),
    "css class": _t("Custom CSS class for this action or node display."),
    "element type": _t("Technical element classification from BPMN metadata."),
    "activity type": _t("Type of activity executed by this node at runtime."),
    "is end node": _t("Marks this node as terminal and completes the workflow path."),
    "workflow actions": _t("Actions that run when this node executes (email, SMS, webhook, server action)."),
    "approval group domain": _t("Request-level filter to decide when group-based assignment is active."),
    "notification domain": _t("Domain filter that controls when notification recipients are selected."),
    "assignment mode": _t("Primary strategy for resolving assignees (groups, domain, explicit users, owner, or users from a workflow node)."),
    "explicit users": _t("Fixed users included as assignment candidates for this node."),
    "assignment user domain": _t("User-domain filter applied after assignment candidates are collected."),
    "completion mode": _t("Controls whether any assignee or all assignees must complete this step."),
    "fallback policy": _t("Policy used when no approver matches configured assignment rules."),
    "fallback user": _t("Specific fallback user used by fallback policy when configured."),
    "automation run mode": _t("Immediate runs when the workflow reaches this node. Scheduled creates a request-scoped runtime job."),
    "automation condition": _t("Optional request domain that must still match each time the scheduled automation runs."),
    "schedule mode": _t("Interval repeats after a duration. Fixed Time runs daily at a chosen time. Cron uses the configured expression."),
    "recurring reminder": _t("When enabled, the scheduled send task re-arms after each successful run."),
    "stop condition": _t("Control whether the recurring reminder runs forever, a fixed number of times, or until a date."),
    "total runs": _t("Maximum number of successful executions for recurring automation."),
    "repeat until": _t("Stop scheduling the reminder after this date and time."),
    "join key": _t("Group key used to correlate parallel branches before join processing."),
    "gateway node id": _t("Reference gateway node ID for branch join tracking."),
    "join policy": _t("How parallel branches are joined (all branches, minimum N, etc.)."),
    "join min n": _t("Minimum completed branches required when join policy is Min-N."),
    "parallel reject policy": _t("Behavior when one parallel branch rejects while others are running."),
    "assign to previous actor": _t("Add users resolved from another workflow node to the assignment candidates."),
    "previous actor node ref": _t("Workflow node used as the source for assigned, pending, or decided users."),
    "assign to request owner": _t("Include original request owner as assignee for this node."),
    "confidentiality level": _t("Confidentiality classification used by runtime access and visibility policies."),
    department: _t("Department context used by confidentiality and assignment logic."),
    "requires department payload": _t("Requires request data to include department context before processing."),
    "enable share override": _t("Allow controlled sharing override for this task when policy permits."),
    field: _t("Request field affected by workflow meta field rule."),
    type: _t("Rule type for selected field: visible, required, or readonly."),
    "limit to actions": _t("Apply this field rule only for selected action buttons."),
    "called workflow": _t("Child workflow version launched by Call Activity node."),
    "execution mode": _t("Required waits for child completion; Optional continues asynchronously."),
    "field mapping (json)": _t("Maps parent request fields to child workflow fields."),
    domain: _t("Domain condition controlling when this configuration applies."),
    transition: _t("Source and target nodes of this action transition."),
    "flow name": _t("Internal sequence flow name from BPMN."),
    "flow type": _t("Action classification used by runtime behavior."),
    "button label": _t("Label shown to end users on action button."),
    "button css preset (recommended)": _t("Quick visual style presets for action button appearance."),
    "custom button css classes": _t("Additional custom CSS classes for button styling."),
    "font awesome icon preset (recommended)": _t("Quick icon presets for action button."),
    "custom font awesome icon": _t("Custom icon class (e.g. fa-check, fa-paper-plane)."),
    "icon class": _t("Icon class used for action visual rendering."),
    "show confirmation dialog": _t("Show a confirmation dialog before executing this action."),
    "require reason": _t("Require user reason input before action can proceed."),
    "comment required": _t("Require a comment value when executing this action."),
    "idempotency required": _t("Prevent duplicate execution of the same action intent."),
    "require 2fa": _t("Require 2FA verification before action execution."),
    "2fa method": _t("Verification method used when 2FA is required."),
    "2fa condition domain": _t("Optional condition deciding when 2FA is required."),
    "action rule set": _t("Rule set evaluated before allowing this action."),
    "dialog type": _t("Dialog UX mode shown to user for this action."),
    "required approvals": _t("Minimum number of approvals needed for this action outcome."),
    "auto action condition": _t("Advanced auto-action condition expression."),
    "button visibility domain": _t("Show this button only when condition matches request + actor context."),
    "action execution domain": _t("Advanced server-side guard checked during action execution."),
    "confirm message": _t("Message shown in confirmation dialog before action runs."),
};
const APPROVAL_GROUP_CATALOG_DEFAULT_LIMIT = 20;
const APPROVAL_GROUP_CATALOG_PAGE_SIZE = 20;
const ADD_COMPONENT_ITEMS = [
    {
        key: "start_event",
        label: "Start Event",
        purpose: "Entry point of the workflow.",
        serverPurpose: "Initializes runtime and opens the first route.",
        iconClasses: "fa fa-play-circle-o",
        shapeSpec: {type: "bpmn:StartEvent"},
    },
    {
        key: "start_event_message",
        label: "Start Event (Message)",
        purpose: "Start when an external message triggers the process.",
        serverPurpose: "Tracked as start-event with message semantics.",
        iconClasses: "fa fa-envelope-o",
        shapeSpec: {
            type: "bpmn:StartEvent",
            eventDefinitionType: "bpmn:MessageEventDefinition",
        },
    },
    {
        key: "start_event_timer",
        label: "Start Event (Timer)",
        purpose: "Start workflow on a timer-based trigger.",
        serverPurpose: "Parsed as timer-driven start event.",
        iconClasses: "fa fa-clock-o",
        shapeSpec: {
            type: "bpmn:StartEvent",
            eventDefinitionType: "bpmn:TimerEventDefinition",
        },
    },
    {
        key: "start_event_signal",
        label: "Start Event (Signal)",
        purpose: "Start workflow from a broadcast signal.",
        serverPurpose: "Parsed as signal-driven start event.",
        iconClasses: "fa fa-bullhorn",
        shapeSpec: {
            type: "bpmn:StartEvent",
            eventDefinitionType: "bpmn:SignalEventDefinition",
        },
    },
    {
        key: "start_event_conditional",
        label: "Start Event (Conditional)",
        purpose: "Start when a condition is satisfied.",
        serverPurpose: "Parsed as conditional start event.",
        iconClasses: "fa fa-code-fork",
        shapeSpec: {
            type: "bpmn:StartEvent",
            eventDefinitionType: "bpmn:ConditionalEventDefinition",
        },
    },
    {
        key: "user_task",
        label: "User Task",
        purpose: "Human approval or input step.",
        serverPurpose: "Creates task metadata and approval assignments.",
        iconClasses: "fa fa-user",
        shapeSpec: {type: "bpmn:UserTask"},
    },
    {
        key: "manual_task",
        label: "Manual Task",
        purpose: "Manual offline activity before next step.",
        serverPurpose: "Tracked as a manual activity node.",
        iconClasses: "fa fa-hand-paper-o",
        shapeSpec: {type: "bpmn:ManualTask"},
    },
    {
        key: "task",
        label: "Generic Task",
        purpose: "Neutral task when specialization is not required.",
        serverPurpose: "Tracked as generic task node.",
        iconClasses: "fa fa-square-o",
        shapeSpec: {type: "bpmn:Task"},
    },
    {
        key: "service_task",
        label: "Service Task",
        purpose: "Run server-side logic automatically.",
        serverPurpose: "Executes system routing/domain logic at runtime.",
        iconClasses: "fa fa-cogs",
        shapeSpec: {type: "bpmn:ServiceTask"},
    },
    {
        key: "send_task",
        label: "Send Task",
        purpose: "Send outbound notifications or integrations.",
        serverPurpose: "Used for messaging/notification flow steps.",
        iconClasses: "fa fa-paper-plane-o",
        shapeSpec: {type: "bpmn:SendTask"},
    },
    {
        key: "script_task",
        label: "Script Task",
        purpose: "Execute scripted business logic.",
        serverPurpose: "Runs configured workflow script actions.",
        iconClasses: "fa fa-file-code-o",
        shapeSpec: {type: "bpmn:ScriptTask"},
    },
    {
        key: "call_activity",
        label: "Call Activity",
        purpose: "Invoke another workflow/sub-process version.",
        serverPurpose: "Creates linked subprocess runtime instances.",
        iconClasses: "fa fa-external-link",
        shapeSpec: {type: "bpmn:CallActivity"}
    },
    {
        key: "sub_process",
        label: "Sub Process",
        purpose: "Group steps into a reusable block.",
        serverPurpose: "Tracked as nested subprocess segment.",
        iconClasses: "fa fa-clone",
        shapeSpec: {type: "bpmn:SubProcess"}
    },
    {
        key: "exclusive_gateway",
        label: "Exclusive Gateway",
        purpose: "Route to exactly one branch.",
        serverPurpose: "Server evaluates outgoing conditions for one path.",
        iconClasses: "fa fa-random",
        shapeSpec: {type: "bpmn:ExclusiveGateway"},
    },
    {
        key: "parallel_gateway",
        label: "Parallel Gateway",
        purpose: "Split or merge parallel branches.",
        serverPurpose: "Server tracks parallel routing semantics.",
        iconClasses: "fa fa-code-fork",
        shapeSpec: {type: "bpmn:ParallelGateway"},
    },
    {
        key: "inclusive_gateway",
        label: "Inclusive Gateway",
        purpose: "Route to one or more matching branches.",
        serverPurpose: "Server can evaluate multi-branch conditions.",
        iconClasses: "fa fa-random",
        shapeSpec: {type: "bpmn:InclusiveGateway"},
    },
    {
        key: "conditional_event",
        label: "Conditional Event",
        purpose: "Pause and continue when condition is met.",
        serverPurpose: "Evaluated as conditional routing event.",
        iconClasses: "fa fa-code-fork",
        shapeSpec: {
            type: "bpmn:IntermediateCatchEvent",
            eventDefinitionType: "bpmn:ConditionalEventDefinition",
        },
    },
    {
        key: "intermediate_event_message",
        label: "Intermediate Event (Message)",
        purpose: "Wait for or represent a message event.",
        serverPurpose: "Mapped as message transition/event node.",
        iconClasses: "fa fa-comments-o",
        shapeSpec: {
            type: "bpmn:IntermediateCatchEvent",
            eventDefinitionType: "bpmn:MessageEventDefinition",
        },
    },
    {
        key: "intermediate_event_timer",
        label: "Intermediate Event (Timer)",
        purpose: "Continue after timer duration/date.",
        serverPurpose: "Mapped as automatic timer transition.",
        iconClasses: "fa fa-clock-o",
        shapeSpec: {
            type: "bpmn:IntermediateCatchEvent",
            eventDefinitionType: "bpmn:TimerEventDefinition",
        },
    },
    {
        key: "intermediate_event_signal",
        label: "Intermediate Event (Signal)",
        purpose: "Catch broadcast signal in mid-flow.",
        serverPurpose: "Mapped as signal catch event.",
        iconClasses: "fa fa-bullhorn",
        shapeSpec: {
            type: "bpmn:IntermediateCatchEvent",
            eventDefinitionType: "bpmn:SignalEventDefinition",
        },
    },
    {
        key: "intermediate_throw_event",
        label: "Intermediate Throw Event",
        purpose: "Emit event before continuing to next node.",
        serverPurpose: "Mapped as throw-event transition node.",
        iconClasses: "fa fa-reply",
        shapeSpec: {type: "bpmn:IntermediateThrowEvent"},
    },
    {
        key: "intermediate_throw_event_message",
        label: "Intermediate Throw Event (Message)",
        purpose: "Emit message event mid-flow.",
        serverPurpose: "Mapped as message throw transition.",
        iconClasses: "fa fa-envelope-o",
        shapeSpec: {
            type: "bpmn:IntermediateThrowEvent",
            eventDefinitionType: "bpmn:MessageEventDefinition",
        },
    },
    {
        key: "intermediate_throw_event_signal",
        label: "Intermediate Throw Event (Signal)",
        purpose: "Broadcast signal mid-flow.",
        serverPurpose: "Mapped as signal throw transition.",
        iconClasses: "fa fa-bullhorn",
        shapeSpec: {
            type: "bpmn:IntermediateThrowEvent",
            eventDefinitionType: "bpmn:SignalEventDefinition",
        },
    },
    {
        key: "end_event",
        label: "End Event",
        purpose: "Close workflow branch/process.",
        serverPurpose: "Marks workflow completion/end state.",
        iconClasses: "fa fa-stop-circle-o",
        shapeSpec: {type: "bpmn:EndEvent"},
    },
    {
        key: "end_event_message",
        label: "End Event (Message)",
        purpose: "End and emit message semantics.",
        serverPurpose: "Captured as message end event.",
        iconClasses: "fa fa-envelope-o",
        shapeSpec: {
            type: "bpmn:EndEvent",
            eventDefinitionType: "bpmn:MessageEventDefinition",
        },
    },
    {
        key: "end_event_signal",
        label: "End Event (Signal)",
        purpose: "End and broadcast signal semantics.",
        serverPurpose: "Captured as signal end event.",
        iconClasses: "fa fa-bullhorn",
        shapeSpec: {
            type: "bpmn:EndEvent",
            eventDefinitionType: "bpmn:SignalEventDefinition",
        },
    },
    {
        key: "end_event_terminate",
        label: "End Event (Terminate)",
        purpose: "Immediately terminate the process instance.",
        serverPurpose: "Captured as terminate end event.",
        iconClasses: "fa fa-times-circle-o",
        shapeSpec: {
            type: "bpmn:EndEvent",
            eventDefinitionType: "bpmn:TerminateEventDefinition",
        },
    },
];
const ADD_COMPONENT_ITEMS_BY_KEY = new Map(ADD_COMPONENT_ITEMS.map((item) => [item.key, item]));
const ALLOWED_DRAG_COMPONENT_KEYS = new Set(ADD_COMPONENT_ITEMS.map((item) => item.key));

function getEventDefinitionTypeFromBusinessObject(businessObject) {
    const eventDefinitions = businessObject?.eventDefinitions;
    if (!eventDefinitions || !eventDefinitions.length) {
        return "";
    }
    return eventDefinitions[0]?.$type || "";
}

function getEngineNodeTypeFromBpmnType(type, eventDefinitionType = "") {
    if (type === "bpmn:StartEvent") {
        if (eventDefinitionType === "bpmn:MessageEventDefinition") {
            return "startEventMessage";
        }
        if (eventDefinitionType === "bpmn:TimerEventDefinition") {
            return "startEventTimer";
        }
        if (eventDefinitionType === "bpmn:SignalEventDefinition") {
            return "startEventSignal";
        }
        if (eventDefinitionType === "bpmn:ConditionalEventDefinition") {
            return "startEventConditional";
        }
        return "startEvent";
    }
    if (type === "bpmn:Task") {
        return "task";
    }
    if (type === "bpmn:UserTask") {
        return "userTask";
    }
    if (type === "bpmn:ManualTask") {
        return "manualTask";
    }
    if (type === "bpmn:ServiceTask") {
        return "serviceTask";
    }
    if (type === "bpmn:SendTask") {
        return "sendTask";
    }
    if (type === "bpmn:ReceiveTask") {
        return "receiveTask";
    }
    if (type === "bpmn:ScriptTask") {
        return "scriptTask";
    }
    if (type === "bpmn:BusinessRuleTask") {
        return "businessRuleTask";
    }
    if (type === "bpmn:CallActivity") {
        return "callActivity";
    }
    if (type === "bpmn:SubProcess") {
        return "subProcess";
    }
    if (type === "bpmn:ExclusiveGateway") {
        return "exclusiveGateway";
    }
    if (type === "bpmn:ParallelGateway") {
        return "parallelGateway";
    }
    if (type === "bpmn:InclusiveGateway") {
        return "inclusiveGateway";
    }
    if (type === "bpmn:EventBasedGateway") {
        return "eventBasedGateway";
    }
    if (type === "bpmn:ComplexGateway") {
        return "complexGateway";
    }
    if (type === "bpmn:EndEvent") {
        if (eventDefinitionType === "bpmn:MessageEventDefinition") {
            return "endEventMessage";
        }
        if (eventDefinitionType === "bpmn:SignalEventDefinition") {
            return "endEventSignal";
        }
        if (eventDefinitionType === "bpmn:TerminateEventDefinition") {
            return "endEventTerminate";
        }
        return "endEvent";
    }
    if (type === "bpmn:IntermediateCatchEvent") {
        if (eventDefinitionType === "bpmn:MessageEventDefinition") {
            return "intermediateEventMessage";
        }
        if (eventDefinitionType === "bpmn:TimerEventDefinition") {
            return "timerEvent";
        }
        if (eventDefinitionType === "bpmn:ConditionalEventDefinition") {
            return "conditionalEventDefinition";
        }
        if (eventDefinitionType === "bpmn:SignalEventDefinition") {
            return "intermediateEventSignal";
        }
        return "intermediateCatchEvent";
    }
    if (type === "bpmn:IntermediateThrowEvent") {
        if (eventDefinitionType === "bpmn:MessageEventDefinition") {
            return "intermediateThrowEventMessage";
        }
        if (eventDefinitionType === "bpmn:SignalEventDefinition") {
            return "intermediateThrowEventSignal";
        }
        return "intermediateThrowEvent";
    }
    return "";
}

function getLocalName(node) {
    if (!node) {
        return "";
    }
    if (node.localName) {
        return node.localName;
    }
    const nodeName = String(node.nodeName || "");
    const parts = nodeName.split(":");
    return parts.length > 1 ? parts[1] : parts[0];
}

function parseXmlDocument(xml) {
    if (typeof xml !== "string" || !xml.trim()) {
        return null;
    }
    try {
        return new DOMParser().parseFromString(xml, "text/xml");
    } catch {
        return null;
    }
}

function hasXmlParserError(doc) {
    if (!doc) {
        return true;
    }
    return !!doc.getElementsByTagName("parsererror")?.length;
}

function findBpmnDefinitionsNode(doc) {
    if (!doc || hasXmlParserError(doc)) {
        return null;
    }
    const root = doc.documentElement;
    if (root && getLocalName(root) === "definitions" && root.namespaceURI === BPMN_MODEL_NS) {
        return root;
    }
    return Array.from(doc.getElementsByTagName("*")).find(
        (node) => getLocalName(node) === "definitions" && node.namespaceURI === BPMN_MODEL_NS
    ) || null;
}

function ensureXmlNamespace(definitionsNode, prefix, uri) {
    if (!definitionsNode || !prefix || !uri) {
        return;
    }
    const attrName = `xmlns:${prefix}`;
    if (!definitionsNode.getAttribute(attrName)) {
        definitionsNode.setAttribute(attrName, uri);
    }
}

function getAutoLayoutNodeSize(nodeName) {
    if (BPMN_AUTO_LAYOUT_EVENT_NAMES.has(nodeName)) {
        return {width: 36, height: 36};
    }
    if (BPMN_AUTO_LAYOUT_GATEWAY_NAMES.has(nodeName)) {
        return {width: 50, height: 50};
    }
    if (nodeName === "subProcess") {
        return {width: 180, height: 120};
    }
    return {width: 130, height: 80};
}

function getCenterY(bounds) {
    return bounds.y + (bounds.height / 2);
}

function buildAutoLayoutData(processNode) {
    const children = Array.from(processNode?.children || []);
    const nodes = children.filter(
        (node) => node.namespaceURI === BPMN_MODEL_NS && BPMN_AUTO_LAYOUT_NODE_NAMES.has(getLocalName(node))
    );
    const sequenceFlows = children.filter(
        (node) => node.namespaceURI === BPMN_MODEL_NS && getLocalName(node) === "sequenceFlow"
    );

    const adjacency = new Map();
    for (const flow of sequenceFlows) {
        const sourceId = flow.getAttribute("sourceRef");
        const targetId = flow.getAttribute("targetRef");
        if (!sourceId || !targetId) {
            continue;
        }
        const targets = adjacency.get(sourceId) || [];
        targets.push(targetId);
        adjacency.set(sourceId, targets);
    }

    const depthByNodeId = new Map();
    const startNodeIds = nodes
        .filter((node) => getLocalName(node) === "startEvent")
        .map((node) => node.getAttribute("id"))
        .filter((nodeId) => !!nodeId);
    const queue = [];
    for (const nodeId of startNodeIds) {
        if (!depthByNodeId.has(nodeId)) {
            depthByNodeId.set(nodeId, 0);
            queue.push(nodeId);
        }
    }

    while (queue.length) {
        const currentNodeId = queue.shift();
        const currentDepth = depthByNodeId.get(currentNodeId) || 0;
        for (const targetNodeId of adjacency.get(currentNodeId) || []) {
            if (!depthByNodeId.has(targetNodeId)) {
                depthByNodeId.set(targetNodeId, currentDepth + 1);
                queue.push(targetNodeId);
            }
        }
    }

    const depthBuckets = new Map();
    let maxDepth = 0;
    for (const node of nodes) {
        const nodeId = node.getAttribute("id");
        if (!nodeId) {
            continue;
        }
        const depth = depthByNodeId.has(nodeId) ? depthByNodeId.get(nodeId) : (maxDepth + 1);
        maxDepth = Math.max(maxDepth, depth);
        const bucket = depthBuckets.get(depth) || [];
        bucket.push(nodeId);
        depthBuckets.set(depth, bucket);
    }

    const boundsByNodeId = new Map();
    const sortedDepths = Array.from(depthBuckets.keys()).sort((left, right) => left - right);
    for (const depth of sortedDepths) {
        const nodeIds = depthBuckets.get(depth) || [];
        nodeIds.forEach((nodeId, rowIndex) => {
            const node = nodes.find((candidate) => candidate.getAttribute("id") === nodeId);
            const nodeName = getLocalName(node);
            const size = getAutoLayoutNodeSize(nodeName);
            boundsByNodeId.set(nodeId, {
                x: 120 + (depth * 220),
                y: 120 + (rowIndex * 140),
                width: size.width,
                height: size.height,
            });
        });
    }

    return {nodes, sequenceFlows, boundsByNodeId};
}

function appendAutoBpmndiLayout(definitionsNode) {
    const documentRef = definitionsNode?.ownerDocument;
    if (!definitionsNode || !documentRef) {
        return false;
    }
    const processNode = Array.from(definitionsNode.children || []).find(
        (child) => getLocalName(child) === "process" && child.namespaceURI === BPMN_MODEL_NS
    );
    if (!processNode) {
        return false;
    }

    ensureXmlNamespace(definitionsNode, "bpmndi", BPMN_DI_NS);
    ensureXmlNamespace(definitionsNode, "dc", BPMN_DC_NS);
    ensureXmlNamespace(definitionsNode, "di", BPMN_DI_WAYPOINT_NS);

    const processId = processNode.getAttribute("id") || "Process_Auto";
    const diagramNode = documentRef.createElementNS(BPMN_DI_NS, "bpmndi:BPMNDiagram");
    diagramNode.setAttribute("id", `BPMNDiagram_${processId}`);
    const planeNode = documentRef.createElementNS(BPMN_DI_NS, "bpmndi:BPMNPlane");
    planeNode.setAttribute("id", `BPMNPlane_${processId}`);
    planeNode.setAttribute("bpmnElement", processId);
    diagramNode.appendChild(planeNode);

    const {nodes, sequenceFlows, boundsByNodeId} = buildAutoLayoutData(processNode);
    for (const node of nodes) {
        const nodeId = node.getAttribute("id");
        const bounds = boundsByNodeId.get(nodeId);
        if (!nodeId || !bounds) {
            continue;
        }
        const shapeNode = documentRef.createElementNS(BPMN_DI_NS, "bpmndi:BPMNShape");
        shapeNode.setAttribute("id", `${nodeId}_di`);
        shapeNode.setAttribute("bpmnElement", nodeId);
        const boundsNode = documentRef.createElementNS(BPMN_DC_NS, "dc:Bounds");
        boundsNode.setAttribute("x", String(bounds.x));
        boundsNode.setAttribute("y", String(bounds.y));
        boundsNode.setAttribute("width", String(bounds.width));
        boundsNode.setAttribute("height", String(bounds.height));
        shapeNode.appendChild(boundsNode);
        planeNode.appendChild(shapeNode);
    }

    for (const flow of sequenceFlows) {
        const flowId = flow.getAttribute("id");
        const sourceId = flow.getAttribute("sourceRef");
        const targetId = flow.getAttribute("targetRef");
        if (!flowId || !sourceId || !targetId) {
            continue;
        }
        const sourceBounds = boundsByNodeId.get(sourceId);
        const targetBounds = boundsByNodeId.get(targetId);
        if (!sourceBounds || !targetBounds) {
            continue;
        }

        const edgeNode = documentRef.createElementNS(BPMN_DI_NS, "bpmndi:BPMNEdge");
        edgeNode.setAttribute("id", `${flowId}_di`);
        edgeNode.setAttribute("bpmnElement", flowId);

        const firstPoint = documentRef.createElementNS(BPMN_DI_WAYPOINT_NS, "di:waypoint");
        firstPoint.setAttribute("x", String(sourceBounds.x + sourceBounds.width));
        firstPoint.setAttribute("y", String(getCenterY(sourceBounds)));
        edgeNode.appendChild(firstPoint);

        const secondPoint = documentRef.createElementNS(BPMN_DI_WAYPOINT_NS, "di:waypoint");
        secondPoint.setAttribute("x", String(targetBounds.x));
        secondPoint.setAttribute("y", String(getCenterY(targetBounds)));
        edgeNode.appendChild(secondPoint);

        planeNode.appendChild(edgeNode);
    }

    definitionsNode.appendChild(diagramNode);
    return true;
}

export function extractImportableBpmnXml(rawText) {
    if (typeof rawText !== "string" || !rawText.trim()) {
        return "";
    }
    const trimmed = rawText.trim();
    if (/<(?:\w+:)?definitions\b/i.test(trimmed) && /BPMN\/20100524\/MODEL/i.test(trimmed)) {
        return trimmed;
    }

    const doc = parseXmlDocument(trimmed);
    if (!doc || hasXmlParserError(doc)) {
        return "";
    }

    const fieldNode = doc.querySelector("field[name='bpmn_xml']");
    const bpmnFieldValue = String(fieldNode?.textContent || "").trim();
    if (bpmnFieldValue && /<(?:\w+:)?definitions\b/i.test(bpmnFieldValue)) {
        return bpmnFieldValue;
    }

    const definitionsNode = findBpmnDefinitionsNode(doc);
    if (!definitionsNode) {
        return "";
    }
    return new XMLSerializer().serializeToString(definitionsNode);
}

export function ensureBpmnDiagramXml(rawBpmnXml) {
    if (typeof rawBpmnXml !== "string" || !rawBpmnXml.trim()) {
        return rawBpmnXml;
    }

    const doc = parseXmlDocument(rawBpmnXml.trim());
    if (!doc || hasXmlParserError(doc)) {
        return rawBpmnXml;
    }

    const definitionsNode = findBpmnDefinitionsNode(doc);
    if (!definitionsNode) {
        return rawBpmnXml;
    }

    const hasDiagram = Array.from(definitionsNode.getElementsByTagName("*")).some(
        (node) => getLocalName(node) === "BPMNDiagram" && node.namespaceURI === BPMN_DI_NS
    );
    if (!hasDiagram) {
        appendAutoBpmndiLayout(definitionsNode);
    }
    return new XMLSerializer().serializeToString(definitionsNode);
}

function isConditionalIntermediateCatchEvent(node) {
    if (!node || node.namespaceURI !== BPMN_MODEL_NS || getLocalName(node) !== "intermediateCatchEvent") {
        return false;
    }
    return Array.from(node.children || []).some(
        (child) => child.namespaceURI === BPMN_MODEL_NS && getLocalName(child) === "conditionalEventDefinition"
    );
}

function mergeConditionalEventDefaultAttrs(baseXml, overlayXml) {
    if (!baseXml || !overlayXml) {
        return baseXml || overlayXml || "";
    }

    const baseDoc = parseXmlDocument(baseXml);
    const overlayDoc = parseXmlDocument(overlayXml);
    if (!baseDoc || !overlayDoc || hasXmlParserError(baseDoc) || hasXmlParserError(overlayDoc)) {
        return baseXml;
    }

    const baseDefinitions = findBpmnDefinitionsNode(baseDoc);
    const overlayDefinitions = findBpmnDefinitionsNode(overlayDoc);
    if (!baseDefinitions || !overlayDefinitions) {
        return baseXml;
    }

    const overlayDefaultsById = new Map();
    for (const node of Array.from(overlayDefinitions.getElementsByTagName("*"))) {
        if (!isConditionalIntermediateCatchEvent(node)) {
            continue;
        }
        const nodeId = node.getAttribute("id");
        if (!nodeId) {
            continue;
        }
        overlayDefaultsById.set(nodeId, node.getAttribute("default") || "");
    }

    for (const node of Array.from(baseDefinitions.getElementsByTagName("*"))) {
        if (!isConditionalIntermediateCatchEvent(node)) {
            continue;
        }
        const nodeId = node.getAttribute("id");
        if (!nodeId || !overlayDefaultsById.has(nodeId)) {
            continue;
        }
        const defaultFlowId = overlayDefaultsById.get(nodeId);
        if (defaultFlowId) {
            node.setAttribute("default", defaultFlowId);
        } else {
            node.removeAttribute("default");
        }
    }

    return new XMLSerializer().serializeToString(baseDefinitions);
}

function getConditionalEventOutgoingLimitViolationsFromXml(xml) {
    if (!xml) {
        return [];
    }
    const documentNode = parseXmlDocument(xml);
    if (!documentNode || hasXmlParserError(documentNode)) {
        return [];
    }
    const definitionsNode = findBpmnDefinitionsNode(documentNode);
    if (!definitionsNode) {
        return [];
    }

    const outgoingCountBySourceId = new Map();
    for (const node of Array.from(definitionsNode.getElementsByTagName("*"))) {
        if (node.namespaceURI !== BPMN_MODEL_NS || getLocalName(node) !== "sequenceFlow") {
            continue;
        }
        const sourceRef = node.getAttribute("sourceRef") || "";
        if (!sourceRef) {
            continue;
        }
        outgoingCountBySourceId.set(sourceRef, (outgoingCountBySourceId.get(sourceRef) || 0) + 1);
    }

    return Array.from(definitionsNode.getElementsByTagName("*"))
        .filter((node) => isConditionalIntermediateCatchEvent(node))
        .map((node) => {
            const id = node.getAttribute("id") || "";
            return {
                id,
                name: node.getAttribute("name") || id || _t("Conditional Event"),
                outgoingCount: outgoingCountBySourceId.get(id) || 0,
            };
        })
        .filter((entry) => entry.outgoingCount > 2);
}

function toPositiveInt(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

export function resolveWorkflowContextIds({
                                              context = {},
                                              routeState = {},
                                              actionResModel = "",
                                              actionResId = null,
                                              controllerResId = null,
                                          } = {}) {
    let categoryId =
        toPositiveInt(context.workflow_category_id)
        || toPositiveInt(routeState.workflow_category_id)
        || null;

    let versionId =
        toPositiveInt(context.workflow_version_id)
        || toPositiveInt(routeState.workflow_version_id)
        || null;
    const contextActiveId = toPositiveInt(context.active_id);
    const routeActiveId = toPositiveInt(routeState.active_id);

    if (!versionId && context.active_model === "workflow.approval.category.version" && contextActiveId) {
        versionId = contextActiveId;
    } else if (
        !versionId
        && routeState.active_model === "workflow.approval.category.version"
        && routeActiveId
    ) {
        versionId = routeActiveId;
    }

    if (!categoryId && context.active_model === "workflow.approval.category" && contextActiveId) {
        categoryId = contextActiveId;
    } else if (
        !categoryId
        && routeState.active_model === "workflow.approval.category"
        && routeActiveId
    ) {
        categoryId = routeActiveId;
    }

    const fallbackResId = toPositiveInt(actionResId) || toPositiveInt(controllerResId) || null;
    if (!categoryId && actionResModel === "workflow.approval.category" && fallbackResId) {
        categoryId = fallbackResId;
    }
    if (!versionId && actionResModel === "workflow.approval.category.version" && fallbackResId) {
        versionId = fallbackResId;
    }

    return {categoryId, versionId};
}

function elementDisplayName(element) {
    const businessObject = element?.businessObject || {};
    return businessObject.name || businessObject.id || element?.id || "";
}

function toBase64(arrayBuffer) {
    let binary = "";
    const bytes = new Uint8Array(arrayBuffer);
    const chunkSize = 0x8000;
    for (let i = 0; i < bytes.length; i += chunkSize) {
        const chunk = bytes.subarray(i, i + chunkSize);
        binary += String.fromCharCode.apply(null, chunk);
    }
    return btoa(binary);
}

function fromBase64(base64) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
}

export class WorkflowStudioNewVersionDialog extends Component {
    static template = "workflow_studio.NewVersionDialog";
    static components = {Dialog, SelectMenu};
    static props = {
        close: Function,
        confirm: Function,
        versions: {type: Array, optional: true},
        currentVersionId: {type: Number, optional: true},
    };

    setup() {
        this.state = useState({
            title: "",
            copyFromVersionId: this.props.currentVersionId || 0,
            isSubmitting: false,
        });
    }

    get versionOptions() {
        return this.props.versions || [];
    }

    get copyFromVersionSelectProps() {
        return {
            choices: [
                {value: 0, label: _t("Empty BPMN template")},
                ...this.versionOptions.map((version) => ({
                    value: Number(version.id),
                    label: version.lifecycle_label
                        ? `${version.display_name} - ${version.lifecycle_label}`
                        : version.display_name,
                })),
            ],
            value: Number(this.state.copyFromVersionId || 0),
            onSelect: (value) => {
                this.state.copyFromVersionId = Number(value || 0);
            },
            searchable: true,
            autoSort: false,
            class: "o_wfs_dialog_select",
            togglerClass: "o_wfs_dialog_select_toggler",
        };
    }

    async onConfirm() {
        if (this.state.isSubmitting) {
            return;
        }
        this.state.isSubmitting = true;
        try {
            const created = await this.props.confirm({
                title: (this.state.title || "").trim(),
                copy_from_version_id: Number(this.state.copyFromVersionId || 0) || false,
            });
            if (created) {
                this.props.close();
            }
        } finally {
            this.state.isSubmitting = false;
        }
    }
}

export class WorkflowStudioCopyVersionDialog extends Component {
    static template = "workflow_studio.CopyVersionDialog";
    static components = {Dialog, SelectMenu};
    static props = {
        close: Function,
        confirm: Function,
        versions: {type: Array, optional: true},
    };

    setup() {
        const defaultTargetVersionId = this.props.versions?.[0]?.id || 0;
        this.state = useState({
            targetVersionId: defaultTargetVersionId,
            isSubmitting: false,
        });
    }

    get versionOptions() {
        return this.props.versions || [];
    }

    get targetVersionSelectProps() {
        return {
            choices: this.versionOptions.map((version) => ({
                value: Number(version.id),
                label: version.lifecycle_label
                    ? `${version.display_name} - ${version.lifecycle_label}`
                    : version.display_name,
            })),
            value: Number(this.state.targetVersionId || 0),
            onSelect: (value) => {
                this.state.targetVersionId = Number(value || 0);
            },
            searchable: true,
            autoSort: false,
            class: "o_wfs_dialog_select",
            togglerClass: "o_wfs_dialog_select_toggler",
        };
    }

    async onConfirm() {
        if (this.state.isSubmitting) {
            return;
        }
        this.state.isSubmitting = true;
        try {
            const done = await this.props.confirm({
                target_version_id: Number(this.state.targetVersionId || 0) || false,
            });
            if (done) {
                this.props.close();
            }
        } finally {
            this.state.isSubmitting = false;
        }
    }
}

export class WorkflowStudioCreateActivityTemplateDialog extends Component {
    static template = "workflow_studio.CreateActivityTemplateDialog";
    static components = {Dialog};
    static props = {
        close: Function,
        confirm: Function,
    };

    setup() {
        this.state = useState({
            name: "",
            subject: "",
            bodyHtml: "<div/>",
            isSubmitting: false,
        });
    }

    async onConfirm() {
        if (this.state.isSubmitting) {
            return;
        }
        this.state.isSubmitting = true;
        try {
            const done = await this.props.confirm({
                name: (this.state.name || "").trim(),
                subject: (this.state.subject || "").trim(),
                body_html: (this.state.bodyHtml || "").trim(),
            });
            if (done) {
                this.props.close();
            }
        } finally {
            this.state.isSubmitting = false;
        }
    }
}

export class WorkflowStudioCreateActionWindowDialog extends Component {
    static template = "workflow_studio.CreateActionWindowDialog";
    static components = {Dialog, SelectMenu};
    static props = {
        close: Function,
        confirm: Function,
        defaultViewMode: {type: String, optional: true},
        defaultTarget: {type: String, optional: true},
    };

    setup() {
        this.state = useState({
            name: "",
            // Leave values empty by default to let backend pick model-aware defaults.
            viewMode: this.props.defaultViewMode || "",
            target: this.props.defaultTarget || "",
            isSubmitting: false,
        });
    }

    get targetSelectProps() {
        return {
            choices: [
                {value: "", label: _t("Auto (Based on Model)")},
                {value: "current", label: _t("Current")},
                {value: "new", label: _t("New (Dialog)")},
            ],
            value: this.state.target || "",
            onSelect: (value) => {
                this.state.target = value || "";
            },
            searchable: false,
            autoSort: false,
            class: "o_wfs_dialog_select",
            togglerClass: "form-select o_wfs_dialog_select_toggler",
        };
    }

    async onConfirm() {
        if (this.state.isSubmitting) {
            return;
        }
        this.state.isSubmitting = true;
        try {
            const done = await this.props.confirm({
                name: (this.state.name || "").trim(),
                view_mode: (this.state.viewMode || "").trim(),
                target: (this.state.target || "").trim(),
            });
            if (done) {
                this.props.close();
            }
        } finally {
            this.state.isSubmitting = false;
        }
    }
}

export class WorkflowStudioCreateEmailTemplateDialog extends Component {
    static template = "workflow_studio.CreateEmailTemplateDialog";
    static components = {Dialog};
    static props = {
        close: Function,
        confirm: Function,
    };

    setup() {
        this.state = useState({
            name: "",
            subject: "",
            bodyHtml: "<div/>",
            isSubmitting: false,
        });
    }

    async onConfirm() {
        if (this.state.isSubmitting) {
            return;
        }
        this.state.isSubmitting = true;
        try {
            const done = await this.props.confirm({
                name: (this.state.name || "").trim(),
                subject: (this.state.subject || "").trim(),
                body_html: (this.state.bodyHtml || "").trim(),
            });
            if (done) {
                this.props.close();
            }
        } finally {
            this.state.isSubmitting = false;
        }
    }
}

export class WorkflowStudioCreateRecipientDialog extends Component {
    static template = "workflow_studio.CreateRecipientDialog";
    static components = {Dialog};
    static props = {
        close: Function,
        confirm: Function,
    };

    setup() {
        this.state = useState({
            name: "",
            email: "",
            login: "",
            isSubmitting: false,
        });
    }

    async onConfirm() {
        if (this.state.isSubmitting) {
            return;
        }
        this.state.isSubmitting = true;
        try {
            const done = await this.props.confirm({
                name: (this.state.name || "").trim(),
                email: (this.state.email || "").trim(),
                login: (this.state.login || "").trim(),
            });
            if (done) {
                this.props.close();
            }
        } finally {
            this.state.isSubmitting = false;
        }
    }
}

export class WorkflowStudioWorkflowActionDialog extends Component {
    static template = "workflow_studio.WorkflowActionDialog";
    static components = {Dialog, MultiRecordSelector, AutoComplete, SelectMenu};
    static props = {
        close: Function,
        confirm: Function,
        title: {type: String, optional: true},
        initialAction: {type: Object, optional: true},
        templateOptions: {type: Array, optional: true},
        serverActionOptions: {type: Array, optional: true},
        workflowActionTypeOptions: {type: Array, optional: true},
        allowedActionTypes: {type: Array, optional: true},
        isNotificationChannel: {type: Boolean, optional: true},
        requestModel: {type: String, optional: true},
        requestFields: {type: Array, optional: true},
        workflowVersionId: {type: Number, optional: true},
        workflowCategoryId: {type: Number, optional: true},
        workflowMetaTaskOptions: {type: Array, optional: true},
        domainPresetsByKey: {type: Object, optional: true},
        isDebugMode: {type: Boolean, optional: true},
        usersOptions: {type: Array, optional: true},
        approvalGroupOptions: {type: Array, optional: true},
        groupOptions: {type: Array, optional: true},
        workflowTaskNodeOptions: {type: Array, optional: true},
        nodeUserTypeOptions: {type: Array, optional: true},
        emailRecipientHeaderOptions: {type: Array, optional: true},
        emailRecipientSourceOptions: {type: Array, optional: true},
    };

    setup() {
        this.dialog = useService("dialog");
        const action = this.props.initialAction || {};
        const recipientLines = Array.isArray(action.email_recipient_lines)
            ? action.email_recipient_lines
            : [];
        this.state = useState({
            name: action.name || "",
            actionType: action.action_type || "workflow",
            messageBody: action.message_body || "",
            emailTemplateId: Number(action.email_template_id || 0) || 0,
            serverActionId: Number(action.server_action_id || 0) || 0,
            webhookUrl: action.webhook_url || "",
            telegramWebhookUrl: action.telegram_webhook_url || "",
            domain: action.domain || "",
            code: action.code || "",
            emailRecipientLines: recipientLines.map((line, index) => this._normalizeEmailRecipientLine(line, index)),
            isSubmitting: false,
        });
    }

    get dialogTitle() {
        return this.props.title || _t("Configure Workflow Action");
    }

    get actionTypeLabel() {
        return this.props.isNotificationChannel ? _t("Channel Type") : _t("Action Type");
    }

    get actionTypeHelp() {
        return this.props.isNotificationChannel
            ? _t("Actual notification channel executed at runtime.")
            : _t("Actual workflow action executed at runtime.");
    }

    get actionTypeOptions() {
        const options = (this.props.workflowActionTypeOptions || []).length
            ? this.props.workflowActionTypeOptions
            : [
                {value: "log", label: _t("Log Message")},
                {value: "email", label: _t("Send Email")},
                {value: "sms", label: _t("Send SMS")},
                {value: "telegram", label: _t("Send Telegram")},
                {value: "webhook", label: _t("Webhook")},
                {value: "server_action", label: _t("Run Server Action")},
                {value: "workflow", label: _t("Workflow Action")},
            ];
        const allowed = this.props.allowedActionTypes;
        if (allowed && allowed.length) {
            return options.filter((opt) => allowed.includes(opt.value));
        }
        return options;
    }

    get actionTypeSelectProps() {
        return {
            choices: this.actionTypeOptions,
            value: this.state.actionType || "workflow",
            onSelect: (value) => {
                this.state.actionType = value || "workflow";
            },
            searchable: false,
            autoSort: false,
            class: "o_wfs_dialog_select",
            togglerClass: "o_wfs_dialog_select_toggler",
        };
    }

    get templateOptions() {
        return this.props.templateOptions || [];
    }

    get emailTemplateSelectProps() {
        return {
            choices: [
                {value: 0, label: _t("None")},
                ...this.templateOptions.map((template) => ({
                    value: Number(template.id),
                    label: template.name,
                })),
            ],
            value: Number(this.state.emailTemplateId || 0),
            onSelect: (value) => {
                this.state.emailTemplateId = Number(value || 0);
            },
            searchable: true,
            autoSort: false,
            class: "o_wfs_dialog_select",
            togglerClass: "form-select o_wfs_dialog_select_toggler",
        };
    }

    get requestDomainModel() {
        return this.props.requestModel || "workflow.base.approval.request";
    }

    get userDomainPresets() {
        const presets = this.props.domainPresetsByKey || {};
        return Array.isArray(presets.routing_user_assignment)
            ? presets.routing_user_assignment
            : Array.isArray(presets.user_assignment)
                ? presets.user_assignment
                : [];
    }

    get requestDomainPresets() {
        const presets = this.props.domainPresetsByKey || {};
        return Array.isArray(presets.routing_request_scope)
            ? presets.routing_request_scope
            : Array.isArray(presets.request_scope)
                ? presets.request_scope
                : [];
    }

    get serverActionOptions() {
        return this.props.serverActionOptions || [];
    }

    get serverActionSelectProps() {
        return {
            choices: [
                {value: 0, label: _t("None")},
                ...this.serverActionOptions.map((action) => ({
                    value: Number(action.id),
                    label: action.model_name
                        ? `${action.name} (${action.model_name})`
                        : action.name,
                })),
            ],
            value: Number(this.state.serverActionId || 0),
            onSelect: (value) => {
                this.state.serverActionId = Number(value || 0);
            },
            searchable: true,
            autoSort: false,
            class: "o_wfs_dialog_select",
            togglerClass: "form-select o_wfs_dialog_select_toggler",
        };
    }

    get emailRecipientHeaderOptions() {
        return this.props.emailRecipientHeaderOptions || [
            {value: "to", label: _t("To")},
            {value: "cc", label: _t("CC")},
            {value: "bcc", label: _t("BCC")},
        ];
    }

    get emailRecipientSourceOptions() {
        return this.props.emailRecipientSourceOptions || [
            {value: "direct", label: _t("Raw Emails")},
            {value: "send_task", label: _t("Send Task Recipients")},
            {value: "specific_users", label: _t("Specific Users")},
            {value: "approval_group_users", label: _t("Workflow Approval Group Users")},
            {value: "group_users", label: _t("Odoo Group Users")},
            {value: "node_users", label: _t("Users From Workflow Node")},
            {value: "domain", label: _t("Domain Over Users")},
        ];
    }

    get workflowTaskNodeOptions() {
        return this.props.workflowTaskNodeOptions || [];
    }

    get nodeUserTypeOptions() {
        return this.props.nodeUserTypeOptions || [
            {value: "assigned", label: _t("Assigned Users")},
            {value: "pending", label: _t("Pending Users")},
            {value: "decided", label: _t("Decided Users")},
        ];
    }

    getEmailRecipientHeaderSelectProps(index) {
        const line = this.state.emailRecipientLines[index] || {};
        return {
            choices: this.emailRecipientHeaderOptions,
            value: line.header || "to",
            onSelect: (value) => this.updateEmailRecipientLine(index, "header", value || "to"),
            searchable: false,
            autoSort: false,
            class: "o_wfs_dialog_select o_wfs_email_recipient_header_select",
            togglerClass: "form-select form-select-sm o_wfs_dialog_select_toggler",
        };
    }

    getEmailRecipientSourceSelectProps(index) {
        const line = this.state.emailRecipientLines[index] || {};
        return {
            choices: this.emailRecipientSourceOptions,
            value: line.source || "send_task",
            onSelect: (value) => this.updateEmailRecipientLine(index, "source", value || "send_task"),
            searchable: true,
            autoSort: false,
            class: "o_wfs_dialog_select o_wfs_email_recipient_source_select",
            togglerClass: "form-select form-select-sm o_wfs_dialog_select_toggler",
        };
    }

    getEmailRecipientNodeUserTypeSelectProps(index) {
        const line = this.state.emailRecipientLines[index] || {};
        return {
            choices: this.nodeUserTypeOptions,
            value: line.node_user_type || "assigned",
            onSelect: (value) => this.updateEmailRecipientLine(index, "node_user_type", value || "assigned"),
            searchable: false,
            autoSort: false,
            class: "o_wfs_dialog_select mt-2",
            togglerClass: "form-select form-select-sm o_wfs_dialog_select_toggler",
        };
    }

    get showMessageBody() {
        return ["log", "sms", "telegram", "webhook", "workflow"].includes(this.state.actionType);
    }

    get showEmailTemplate() {
        return this.state.actionType === "email";
    }

    get showEmailRecipients() {
        return this.state.actionType === "email";
    }

    get showTelegramWebhook() {
        return this.state.actionType === "telegram";
    }

    get showWebhookUrl() {
        return ["webhook", "telegram"].includes(this.state.actionType);
    }

    get showServerAction() {
        return this.state.actionType === "server_action";
    }

    get showCode() {
        return this.state.actionType === "workflow";
    }

    _normalizeEmailRecipientLine(line = {}, index = 0) {
        return {
            sequence: Number(line.sequence || ((index + 1) * 10)),
            header: line.header || "to",
            source: line.source || "send_task",
            raw_emails: line.raw_emails || "",
            user_ids: [...(line.user_ids || [])],
            approval_group_ids: [...(line.approval_group_ids || [])],
            group_ids: [...(line.group_ids || [])],
            node_ref: line.node_ref || "",
            node_user_type: line.node_user_type || "assigned",
            domain: line.domain || "",
        };
    }

    addEmailRecipientLine() {
        this.state.emailRecipientLines.push(this._normalizeEmailRecipientLine({}, this.state.emailRecipientLines.length));
    }

    removeEmailRecipientLine(index) {
        this.state.emailRecipientLines.splice(index, 1);
    }

    updateEmailRecipientLine(index, fieldName, value) {
        const line = this.state.emailRecipientLines[index];
        if (!line) {
            return;
        }
        line[fieldName] = value;
        if (fieldName === "source") {
            line.raw_emails = "";
            line.user_ids = [];
            line.approval_group_ids = [];
            line.group_ids = [];
            line.node_ref = "";
            if (!["domain", "approval_group_users", "group_users", "node_users"].includes(value)) {
                line.domain = "";
            }
        }
    }

    openEmailRecipientDomainDialog(index) {
        const line = this.state.emailRecipientLines[index];
        if (!line || !["domain", "approval_group_users", "group_users", "node_users"].includes(line.source)) {
            return;
        }
        const isApprovalGroupFilter = line.source === "approval_group_users";
        this.dialog.add(WorkflowStudioDomainDialog, {
            resModel: "res.users",
            requestModel: this.requestDomainModel,
            requestFields: this.props.requestFields || [],
            workflowVersionId: Number(this.props.workflowVersionId || 0) || 0,
            workflowCategoryId: Number(this.props.workflowCategoryId || 0) || 0,
            workflowMetaTaskOptions: this.props.workflowMetaTaskOptions || this.props.workflowTaskNodeOptions || [],
            domain: line.domain || "",
            title: isApprovalGroupFilter
                ? _t("Approval Group User Filter")
                : _t("Email Recipient User Domain"),
            helpText: isApprovalGroupFilter
                ? _t("Filter the users inside the selected workflow approval groups. The domain is evaluated on res.users with request and actor symbols available.")
                : _t("Select users for this To/CC/BCC row. The domain is evaluated on res.users with request and actor symbols available."),
            contextType: "assignment_users_routing",
            presets: this.userDomainPresets,
            isDebugMode: !!this.props.isDebugMode,
            allowBlankDomain: true,
            onConfirm: (domain) => this.updateEmailRecipientLine(index, "domain", domain),
        });
    }

    openRequestDomainDialog() {
        this.dialog.add(WorkflowStudioDomainDialog, {
            resModel: this.requestDomainModel,
            requestModel: this.requestDomainModel,
            requestFields: this.props.requestFields || [],
            workflowVersionId: Number(this.props.workflowVersionId || 0) || 0,
            workflowCategoryId: Number(this.props.workflowCategoryId || 0) || 0,
            workflowMetaTaskOptions: this.props.workflowMetaTaskOptions || this.props.workflowTaskNodeOptions || [],
            domain: this.state.domain || "",
            title: _t("Notification Channel Request Domain"),
            helpText: _t("Optional guard for this channel. The channel executes only when this domain matches the current request record."),
            contextType: "request_scope_routing",
            presets: this.requestDomainPresets,
            isDebugMode: !!this.props.isDebugMode,
            allowBlankDomain: true,
            onConfirm: (domain) => {
                this.state.domain = domain || "";
            },
        });
    }

    getEmailRecipientUsersProps(index) {
        const line = this.state.emailRecipientLines[index] || {};
        return {
            resModel: "res.users",
            resIds: [...(line.user_ids || [])],
            update: (resIds) => this.updateEmailRecipientLine(index, "user_ids", resIds),
        };
    }

    getEmailRecipientApprovalGroupProps(index) {
        const line = this.state.emailRecipientLines[index] || {};
        return {
            resModel: "workflow.approval.group",
            resIds: [...(line.approval_group_ids || [])],
            update: (resIds) => this.updateEmailRecipientLine(index, "approval_group_ids", resIds),
        };
    }

    getEmailRecipientGroupProps(index) {
        const line = this.state.emailRecipientLines[index] || {};
        return {
            resModel: "res.groups",
            resIds: [...(line.group_ids || [])],
            update: (resIds) => this.updateEmailRecipientLine(index, "group_ids", resIds),
        };
    }

    getEmailRecipientNodeAutocompleteProps(index) {
        const line = this.state.emailRecipientLines[index] || {};
        const value = line.node_ref || "";
        const selected = this.workflowTaskNodeOptions.find((node) => node.value === value);
        return {
            value: selected ? selected.label : value,
            class: "o_wfs_meta_field_autocomplete",
            placeholder: _t("Search workflow node..."),
            searchOnInputClick: true,
            resetOnSelect: false,
            sources: [
                {
                    options: (searchTerm) => {
                        const term = (searchTerm || "").trim().toLowerCase();
                        return this.workflowTaskNodeOptions
                            .filter((node) => {
                                const haystack = `${node.label || ""} ${node.value || ""}`.toLowerCase();
                                return !term || haystack.includes(term);
                            })
                            .map((node) => ({
                                label: node.label,
                                onSelect: () => this.updateEmailRecipientLine(index, "node_ref", node.value),
                            }));
                    },
                },
            ],
            onChange: ({inputValue, isOptionSelected}) => {
                if (!isOptionSelected && !(inputValue || "").trim()) {
                    this.updateEmailRecipientLine(index, "node_ref", "");
                }
            },
        };
    }

    async onConfirm() {
        if (this.state.isSubmitting) {
            return;
        }
        this.state.isSubmitting = true;
        try {
            const done = await this.props.confirm({
                name: (this.state.name || "").trim(),
                action_type: this.state.actionType || "workflow",
                message_body: this.state.messageBody || "",
                email_template_id: Number(this.state.emailTemplateId || 0) || false,
                email_recipient_lines: this.state.emailRecipientLines.map((line, index) => ({
                    sequence: Number(line.sequence || ((index + 1) * 10)),
                    header: line.header || "to",
                    source: line.source || "send_task",
                    raw_emails: line.raw_emails || "",
                    user_ids: [...(line.user_ids || [])],
                    approval_group_ids: [...(line.approval_group_ids || [])],
                    group_ids: [...(line.group_ids || [])],
                    node_ref: line.node_ref || "",
                    node_user_type: line.node_user_type || "assigned",
                    domain: line.domain || "",
                })),
                server_action_id: Number(this.state.serverActionId || 0) || false,
                webhook_url: (this.state.webhookUrl || "").trim(),
                telegram_webhook_url: (this.state.telegramWebhookUrl || "").trim(),
                domain: (this.state.domain || "").trim(),
                code: this.state.code || "",
            });
            if (done) {
                this.props.close();
            }
        } finally {
            this.state.isSubmitting = false;
        }
    }
}

export class WorkflowStudioNotificationChannelBrowserDialog extends Component {
    static template = "workflow_studio.NotificationChannelBrowserDialog";
    static components = {Dialog};
    static props = {
        close: Function,
        getNodeLabel: Function,
        getTotalCount: Function,
        getConfiguredCount: Function,
        getConfiguredQuery: Function,
        setConfiguredQuery: Function,
        getAvailableQuery: Function,
        setAvailableQuery: Function,
        getConfiguredRows: Function,
        getAvailableRows: Function,
        createChannel: Function,
        configureChannel: Function,
        addChannel: Function,
        removeChannel: Function,
    };

    setup() {
        this.state = useState({refreshNonce: 0});
    }

    _refresh() {
        this.state.refreshNonce += 1;
    }

    _safeCount(value) {
        const parsed = Number(value);
        return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 0;
    }

    get dialogTitle() {
        return _t("Manage Notification Channels");
    }

    get nodeLabel() {
        this.state.refreshNonce;
        return this.props.getNodeLabel?.() || _t("Selected node");
    }

    get totalCount() {
        this.state.refreshNonce;
        return this._safeCount(this.props.getTotalCount?.());
    }

    get configuredCount() {
        this.state.refreshNonce;
        return this._safeCount(this.props.getConfiguredCount?.());
    }

    get totalBadgeLabel() {
        return sprintf(_t("%s total"), this.totalCount);
    }

    get configuredBadgeLabel() {
        return sprintf(_t("%s configured"), this.configuredCount);
    }

    get configuredQuery() {
        this.state.refreshNonce;
        return this.props.getConfiguredQuery?.() || "";
    }

    get availableQuery() {
        this.state.refreshNonce;
        return this.props.getAvailableQuery?.() || "";
    }

    get configuredRows() {
        this.state.refreshNonce;
        return this.props.getConfiguredRows?.() || [];
    }

    get availableRows() {
        this.state.refreshNonce;
        return this.props.getAvailableRows?.() || [];
    }

    get configuredEmptyMessage() {
        if (this.configuredQuery.trim()) {
            return _t("No configured channels match the current search.");
        }
        return _t("No notification channels are configured on this node yet.");
    }

    get availableEmptyMessage() {
        if (this.availableQuery.trim()) {
            return _t("No available channels match the current search.");
        }
        return _t("No additional channels are available. Create a new channel if needed.");
    }

    getChannelTypeLabel(channel = {}) {
        const labels = {
            email: _t("Email"),
            sms: _t("SMS"),
            telegram: _t("Telegram"),
            webhook: _t("Webhook"),
            server_action: _t("Server Action"),
            log: _t("Log Message"),
            workflow: _t("Workflow Action"),
        };
        return labels[channel.action_type] || channel.action_type || _t("Channel");
    }

    getChannelDetail(channel = {}) {
        if (channel.action_type === "email") {
            return channel.email_template_name || "";
        }
        if (channel.action_type === "server_action") {
            return channel.server_action_name || "";
        }
        if (channel.action_type === "webhook") {
            return channel.webhook_url || "";
        }
        if (channel.action_type === "telegram") {
            return channel.telegram_webhook_url || channel.message_body || "";
        }
        if (channel.action_type === "sms" || channel.action_type === "log") {
            return channel.message_body || "";
        }
        return "";
    }

    onConfiguredSearchInput(event) {
        this.props.setConfiguredQuery?.(event?.target?.value || "");
        this._refresh();
    }

    onAvailableSearchInput(event) {
        this.props.setAvailableQuery?.(event?.target?.value || "");
        this._refresh();
    }

    onCreateChannel() {
        this.props.createChannel?.(() => this._refresh());
    }

    onConfigureChannel(channelId) {
        this.props.configureChannel?.(channelId, () => this._refresh());
    }

    async onAddChannel(channelId) {
        await this.props.addChannel?.(channelId);
        this._refresh();
    }

    async onRemoveChannel(channelId) {
        const removed = await this.props.removeChannel?.(channelId);
        if (removed !== false) {
            this._refresh();
        }
    }
}

export class WorkflowStudioMetaFieldDialog extends Component {
    static template = "workflow_studio.MetaFieldDialog";
    static components = {Dialog, MultiRecordSelector, WorkflowStudioDomainDialog};
    static props = {
        close: Function,
        confirm: Function,
        mode: {type: String, optional: true},
        initialRow: {type: Object, optional: true},
        fieldsOptions: {type: Array, optional: true},
        requestModel: {type: String, optional: true},
        requestFields: {type: Array, optional: true},
        workflowVersionId: {type: Number, optional: true},
        workflowCategoryId: {type: Number, optional: true},
        workflowMetaTaskOptions: {type: Array, optional: true},
        isDebugMode: {type: Boolean, optional: true},
        outgoingActions: {type: Array, optional: true},
    };

    setup() {
        const row = this.props.initialRow || {};
        this.dialog = useService("dialog");
        const fieldKeys = Array.isArray(row.field_keys)
            ? row.field_keys
            : row.field_key
                ? [row.field_key]
                : [];
        this.state = useState({
            field_keys: [...new Set(fieldKeys.filter(Boolean))],
            field_types: this._normalizeFieldTypes(row),
            activity_action_keys: Array.isArray(row.activity_action_keys) ? [...row.activity_action_keys] : [],
            domains_by_type: this._normalizeDomainsByType(row),
        });
        this._tagTooltipFrame = null;
        onMounted(() => this._scheduleSelectedFieldTagTooltips());
        onPatched(() => this._scheduleSelectedFieldTagTooltips());
        onWillUnmount(() => {
            if (this._tagTooltipFrame && typeof window !== "undefined" && window.cancelAnimationFrame) {
                window.cancelAnimationFrame(this._tagTooltipFrame);
            }
            this._tagTooltipFrame = null;
        });
    }

    _normalizeFieldTypes(row = {}) {
        const rawTypes = Array.isArray(row.field_types)
            ? row.field_types
            : row.field_type
                ? [row.field_type]
                : ["visible"];
        const types = new Set(rawTypes.filter((type) => FIELD_TYPE_OPTIONS.includes(type)));
        if (types.has("required") || types.has("readonly")) {
            types.add("visible");
        }
        if (types.has("readonly")) {
            types.delete("required");
        }
        if (!types.size) {
            types.add("visible");
        }
        return FIELD_TYPE_PRIORITY.filter((type) => types.has(type));
    }

    _normalizeDomainsByType(row = {}) {
        const domainsByType = {};
        if (row.domains_by_type && typeof row.domains_by_type === "object") {
            for (const [fieldType, domain] of Object.entries(row.domains_by_type)) {
                if (FIELD_TYPE_OPTIONS.includes(fieldType)) {
                    domainsByType[fieldType] = `${domain || "[]"}`.trim() || "[]";
                }
            }
        }
        for (const [fieldType, fieldName] of Object.entries({
            visible: "visible_domain",
            required: "required_domain",
            readonly: "readonly_domain",
            invisible: "invisible_domain",
        })) {
            const domain = `${row[fieldName] || ""}`.trim();
            if (domain && domain !== "[]") {
                domainsByType[fieldType] = domainsByType[fieldType] || domain;
            }
        }
        const rowDomain = `${row.condition_domain || row.domain || ""}`.trim();
        if (rowDomain) {
            for (const fieldType of this._normalizeFieldTypes(row)) {
                domainsByType[fieldType] = domainsByType[fieldType] || rowDomain;
            }
        }
        return domainsByType;
    }

    get isEditMode() {
        return (this.props.mode || "create") === "edit";
    }

    get dialogTitle() {
        return this.isEditMode ? _t("Edit Field Rule") : _t("Add Field Rule");
    }

    get fieldsOptions() {
        return this.props.fieldsOptions || [];
    }

    get requestModel() {
        return this.props.requestModel || "";
    }

    get outgoingActions() {
        return this.props.outgoingActions || [];
    }

    get hasVisibleRule() {
        return (this.state.field_types || []).includes("visible");
    }

    get hasRequiredRule() {
        return (this.state.field_types || []).includes("required");
    }

    get hasReadonlyRule() {
        return (this.state.field_types || []).includes("readonly");
    }

    get selectedDomainTypes() {
        return FIELD_TYPE_PRIORITY.filter(
            (type) => ["visible", "required", "readonly"].includes(type)
                && (this.state.field_types || []).includes(type)
        );
    }

    _fieldOptionData(field = {}) {
        const [model = "", name = ""] = String(field.key || "").split("::");
        const technical = model && name ? `${model}.${name}` : field.key || "";
        const displayName = field.display_name || field.field_description || name || field.key || "";
        const label = displayName.replace(/\s*\([^()]*\)\s*$/, "").trim() || displayName || technical;
        const nameWords = name
            .replace(/^x_/, "")
            .replace(/_/g, " ")
            .trim();
        const searchLabel = [
            label,
            technical,
            name,
            nameWords,
            field.field_description || "",
            field.relation || "",
        ].filter(Boolean).join(" ");
        return {
            key: field.key || "",
            label,
            displayLabel: label,
            searchLabel,
            technical,
            model,
            name,
            type: field.ttype || "",
            isCurrentModel: !!model && model === this.requestModel,
        };
    }

    get fieldOptionsById() {
        const optionsById = new Map();
        for (const field of this.fieldsOptions) {
            const fieldId = Number(field?.id || 0);
            if (fieldId && field?.key) {
                optionsById.set(fieldId, field);
            }
        }
        return optionsById;
    }

    get fieldOptionsByKey() {
        return new Map((this.fieldsOptions || []).map((field) => [field.key, field]));
    }

    get selectedFieldIds() {
        const ids = [];
        const seenIds = new Set();
        const optionsByKey = this.fieldOptionsByKey;
        for (const fieldKey of this.state.field_keys || []) {
            const fieldId = Number(optionsByKey.get(fieldKey)?.id || 0);
            if (fieldId && !seenIds.has(fieldId)) {
                ids.push(fieldId);
                seenIds.add(fieldId);
            }
        }
        return ids;
    }

    get fieldRecordSelectorProps() {
        return {
            resModel: "ir.model.fields",
            resIds: this.selectedFieldIds,
            domain: this.fieldRecordSelectorDomain,
            context: this.fieldRecordSelectorContext,
            fieldString: _t("Field"),
            placeholder: _t("Search and select fields..."),
            update: (resIds) => this.updateSelectedFieldIds(resIds),
        };
    }

    get fieldRecordSelectorDomain() {
        const fieldIds = [
            ...new Set(
                (this.fieldsOptions || [])
                    .map((field) => Number(field?.id || 0))
                    .filter(Boolean)
            ),
        ];
        return fieldIds.length ? [["id", "in", fieldIds]] : [["id", "=", 0]];
    }

    get fieldRecordSelectorContext() {
        return {
            workflow_studio: true,
            workflow_request_model: this.requestModel,
            list_view_ref: "workflow_studio.view_ir_model_fields_workflow_meta_picker_list",
            search_view_ref: "workflow_studio.view_ir_model_fields_workflow_meta_picker_search",
        };
    }

    updateSelectedFieldIds(resIds = []) {
        const optionsById = this.fieldOptionsById;
        const selectedKeys = [];
        const seenKeys = new Set();
        for (const rawId of resIds || []) {
            const field = optionsById.get(Number(rawId || 0));
            if (field?.key && !seenKeys.has(field.key)) {
                selectedKeys.push(field.key);
                seenKeys.add(field.key);
            }
        }
        this.state.field_keys = selectedKeys;
    }

    get canApply() {
        return this.hasVisibleRule && (this.state.field_keys || []).length > 0;
    }

    get selectedFieldTags() {
        return this._selectedFieldTooltipData();
    }

    _selectedFieldTooltipData() {
        const optionsByKey = new Map((this.fieldsOptions || []).map((field) => [field.key, field]));
        return (this.state.field_keys || [])
            .filter(Boolean)
            .map((fieldKey) => {
                const data = this._fieldOptionData(optionsByKey.get(fieldKey) || {key: fieldKey});
                return {
                    key: fieldKey,
                    label: data.label || fieldKey,
                    technical: data.technical || fieldKey,
                };
            });
    }

    removeSelectedField(fieldKey) {
        this.state.field_keys = (this.state.field_keys || []).filter((key) => key !== fieldKey);
    }

    _scheduleSelectedFieldTagTooltips() {
        const applyTooltips = () => {
            this._tagTooltipFrame = null;
            this._syncSelectedFieldTagTooltips();
        };
        if (typeof window !== "undefined" && window.requestAnimationFrame) {
            if (this._tagTooltipFrame) {
                window.cancelAnimationFrame(this._tagTooltipFrame);
            }
            this._tagTooltipFrame = window.requestAnimationFrame(applyTooltips);
        } else {
            applyTooltips();
        }
    }

    _syncSelectedFieldTagTooltips() {
        if (typeof document === "undefined") {
            return;
        }
        const selector = document.querySelector(".o_wfs_meta_field_dialog .o_wfs_meta_field_selector");
        if (!selector) {
            return;
        }
        const tooltipData = this._selectedFieldTooltipData();
        const tags = selector.querySelectorAll(".o_tag");
        tags.forEach((tag, index) => {
            const field = tooltipData[index];
            if (!field) {
                return;
            }
            const title = field.technical || field.label;
            tag.setAttribute("title", title);
            tag.setAttribute("data-tooltip", title);
            tag.setAttribute("aria-label", `${field.label} (${title})`);
            const textNode = tag.querySelector(".o_tag_badge_text");
            if (textNode) {
                textNode.textContent = field.label;
            }
        });
    }

    domainForType(fieldType) {
        return `${this.state.domains_by_type?.[fieldType] || "[]"}`.trim() || "[]";
    }

    domainSummaryForType(fieldType) {
        const domain = this.domainForType(fieldType);
        if (!domain || domain === "[]") {
            return _t("Always");
        }
        if (domain.length > 96) {
            return `${domain.slice(0, 93)}...`;
        }
        return domain;
    }

    domainLabelForType(fieldType) {
        const labels = {
            visible: _t("Visible when"),
            required: _t("Required when"),
            readonly: _t("Readonly when"),
        };
        return labels[fieldType] || _t("Condition");
    }

    domainButtonLabelForType(fieldType) {
        const domain = this.domainForType(fieldType);
        return domain && domain !== "[]" ? _t("Edit") : _t("Add");
    }

    setDomainForType(fieldType, domainExpression) {
        if (!FIELD_TYPE_OPTIONS.includes(fieldType)) {
            return;
        }
        this.state.domains_by_type = {
            ...(this.state.domains_by_type || {}),
            [fieldType]: `${domainExpression || "[]"}`.trim() || "[]",
        };
    }

    openDomainDialog(fieldType) {
        if (!["visible", "required", "readonly"].includes(fieldType)) {
            return;
        }
        const titleByType = {
            visible: _t("Visible Field Domain"),
            required: _t("Required Field Domain"),
            readonly: _t("Readonly Field Domain"),
        };
        const helpTextByType = {
            visible: _t("Show the selected field only when this domain matches current form values and actor context."),
            required: _t("Require the selected field only when this domain matches. Required rules may use the clicked workflow action."),
            readonly: _t("Lock the selected field only when this domain matches current form values and actor context."),
        };
        const requestModel = this.requestModel;
        this.dialog.add(WorkflowStudioDomainDialog, {
            resModel: requestModel,
            requestModel,
            requestFields: this.props.requestFields || [],
            workflowVersionId: Number(this.props.workflowVersionId || 0) || 0,
            workflowCategoryId: Number(this.props.workflowCategoryId || 0) || 0,
            workflowMetaTaskOptions: this.props.workflowMetaTaskOptions || [],
            domain: this.domainForType(fieldType),
            domainKind: fieldType,
            contextType: "field_modifiers",
            title: titleByType[fieldType],
            helpText: helpTextByType[fieldType],
            isDebugMode: !!this.props.isDebugMode,
            onConfirm: (domainExpression) => this.setDomainForType(fieldType, domainExpression),
        });
    }

    toggleFieldType(fieldType) {
        if (!EDITABLE_FIELD_TYPE_OPTIONS.includes(fieldType)) {
            return;
        }
        const types = new Set(this.state.field_types || []);
        if (fieldType === "visible") {
            types.add("visible");
        } else {
            if (!types.has("visible")) {
                types.add("visible");
            }
            if (types.has(fieldType)) {
                types.delete(fieldType);
            } else {
                types.add(fieldType);
                if (fieldType === "required") {
                    types.delete("readonly");
                } else if (fieldType === "readonly") {
                    types.delete("required");
                }
            }
        }
        this.state.field_types = FIELD_TYPE_PRIORITY.filter((type) => types.has(type));
        if (!types.has("required")) {
            this.state.activity_action_keys = [];
        }
    }

    toggleAction(actionKey) {
        const current = this.state.activity_action_keys;
        if (current.includes(actionKey)) {
            this.state.activity_action_keys = current.filter((k) => k !== actionKey);
        } else {
            this.state.activity_action_keys = [...current, actionKey];
        }
    }

    onApply() {
        if (!this.state.field_keys.length || !this.hasVisibleRule) {
            return;
        }
        const fieldTypes = FIELD_TYPE_PRIORITY.filter(
            (type) => (this.state.field_types || []).includes(type)
                && EDITABLE_FIELD_TYPE_OPTIONS.includes(type)
        );
        this.props.confirm({
            field_keys: [...this.state.field_keys],
            field_types: fieldTypes.length ? fieldTypes : ["visible"],
            activity_action_keys: fieldTypes.includes("required")
                ? [...this.state.activity_action_keys]
                : [],
            domains_by_type: Object.fromEntries(
                (fieldTypes.length ? fieldTypes : ["visible"])
                    .map((fieldType) => [fieldType, this.domainForType(fieldType)])
            ),
        });
        this.props.close();
    }
}

export class WorkflowStudioMetaFieldManagerDialog extends Component {
    static template = "workflow_studio.MetaFieldManagerDialog";
    static components = {Dialog};
    static props = {
        close: Function,
        getRows: Function,
        addRow: Function,
        copyRows: Function,
        editRow: Function,
        removeRow: Function,
        canCopy: Boolean,
    };

    setup() {
        this.state = useState({
            query: "",
            revision: 0,
        });
    }

    get rows() {
        return this.props.getRows(this.state.revision) || [];
    }

    get filteredRows() {
        const query = `${this.state.query || ""}`.trim().toLowerCase();
        return this.rows.filter((row) => !query || row.searchText.includes(query));
    }

    refresh() {
        this.state.revision += 1;
    }

    onSearchInput(event) {
        this.state.query = event.target.value || "";
    }

    clearSearch() {
        this.state.query = "";
    }

    addMetaFieldRow() {
        this.props.addRow(() => this.refresh());
    }

    copyMetaFieldRows() {
        this.props.copyRows(() => this.refresh());
    }

    editMetaFieldRow(index) {
        this.props.editRow(index, () => this.refresh());
    }

    removeMetaFieldRow(index) {
        this.props.removeRow(index, () => this.refresh());
    }
}

export class WorkflowStudioCopyMetaFieldDialog extends Component {
    static template = "workflow_studio.CopyMetaFieldDialog";
    static components = {Dialog, SelectMenu};
    static props = {
        close: Function,
        confirm: Function,
        sourceOptions: {type: Array, optional: true},
        fieldsOptions: {type: Array, optional: true},
    };

    setup() {
        const sourceNodeId = this.sourceOptions[0]?.nodeId || "";
        this.state = useState({
            sourceNodeId,
            selectedKeys: sourceNodeId ? this._sourceRowKeys(sourceNodeId) : [],
        });
    }

    get sourceOptions() {
        return this.props.sourceOptions || [];
    }

    get sourceSelectProps() {
        return {
            choices: this.sourceOptions.map((source) => ({
                value: source.nodeId,
                label: `${source.label} - ${source.rows.length} ${_t("rule(s)")}`,
            })),
            value: this.state.sourceNodeId || "",
            onSelect: (sourceNodeId) => {
                this.state.sourceNodeId = sourceNodeId || "";
                this.state.selectedKeys = this._sourceRowKeys(this.state.sourceNodeId);
            },
            searchable: true,
            autoSort: false,
            class: "o_wfs_dialog_select",
            togglerClass: "o_wfs_dialog_select_toggler",
        };
    }

    get fieldsOptions() {
        return this.props.fieldsOptions || [];
    }

    get selectedSource() {
        return this.sourceOptions.find((source) => source.nodeId === this.state.sourceNodeId) || null;
    }

    get sourceRows() {
        return this.selectedSource?.rows || [];
    }

    get selectedKeySet() {
        return new Set(this.state.selectedKeys || []);
    }

    get canCopy() {
        return !!this.selectedSource && this.selectedKeySet.size > 0;
    }

    get allRowsSelected() {
        return this.sourceRows.length > 0 && this.sourceRows.every((row, index) => {
            return this.selectedKeySet.has(this._rowKey(row, index));
        });
    }

    _rowKey(row, index = 0) {
        return row?.field_key || row?.key || `row_${index}`;
    }

    _sourceRowKeys(sourceNodeId) {
        const source = this.sourceOptions.find((item) => item.nodeId === sourceNodeId);
        return (source?.rows || []).map((row, index) => this._rowKey(row, index));
    }

    onSourceChange(ev) {
        const sourceNodeId = ev.target.value || "";
        this.state.sourceNodeId = sourceNodeId;
        this.state.selectedKeys = this._sourceRowKeys(sourceNodeId);
    }

    toggleAll(ev) {
        this.state.selectedKeys = ev.target.checked
            ? this.sourceRows.map((row, index) => this._rowKey(row, index))
            : [];
    }

    toggleRow(row, index) {
        const rowKey = this._rowKey(row, index);
        const selected = new Set(this.state.selectedKeys || []);
        if (selected.has(rowKey)) {
            selected.delete(rowKey);
        } else {
            selected.add(rowKey);
        }
        this.state.selectedKeys = [...selected];
    }

    isRowSelected(row, index) {
        return this.selectedKeySet.has(this._rowKey(row, index));
    }

    _fieldOption(fieldKey) {
        return this.fieldsOptions.find((field) => field.key === fieldKey) || null;
    }

    fieldLabel(fieldKey) {
        const option = this._fieldOption(fieldKey);
        if (!option) {
            return fieldKey || _t("Unknown Field");
        }
        const displayName = option.display_name || option.field_description || option.name || fieldKey;
        const paren = displayName.indexOf("(");
        return paren > 0 ? displayName.slice(0, paren).trim() : displayName;
    }

    fieldTitle(fieldKey) {
        const option = this._fieldOption(fieldKey);
        return option?.display_name || fieldKey || _t("Unknown Field");
    }

    metaFieldTypes(row = {}) {
        const rawTypes = Array.isArray(row.field_types)
            ? row.field_types
            : row.field_type
                ? [row.field_type]
                : ["visible"];
        const types = new Set(rawTypes.filter((type) => FIELD_TYPE_OPTIONS.includes(type)));
        if ((types.has("required") || types.has("readonly")) && !types.has("invisible")) {
            types.add("visible");
        }
        if (types.has("readonly")) {
            types.delete("required");
        }
        if (!types.size) {
            types.add("visible");
        }
        return FIELD_TYPE_PRIORITY.filter((type) => types.has(type));
    }

    metaFieldTypeLabel(type) {
        const labels = {
            visible: _t("visible"),
            required: _t("required"),
            readonly: _t("readonly"),
            invisible: _t("hidden"),
        };
        return labels[type] || type;
    }

    metaFieldHasDomain(row = {}) {
        const domainsByType = row.domains_by_type || {};
        const domainValues = Object.values(domainsByType);
        if (row.domain || row.condition_domain) {
            domainValues.push(row.domain || row.condition_domain);
        }
        return domainValues.some((domain) => {
            const value = `${domain || ""}`.trim();
            return value && value !== "[]";
        });
    }

    onCopy() {
        if (!this.canCopy) {
            return;
        }
        const selectedKeys = this.selectedKeySet;
        const rows = this.sourceRows.filter((row, index) => selectedKeys.has(this._rowKey(row, index)));
        this.props.confirm({
            sourceNodeId: this.state.sourceNodeId,
            rows,
        });
        this.props.close();
    }
}

export class WorkflowStudioApprovalGroupBrowserDialog extends Component {
    static template = "workflow_studio.ApprovalGroupBrowserDialog";
    static components = {Dialog};
    static props = {
        close: Function,
        getNodeLabel: {type: Function, optional: true},
        getTotalCount: Function,
        getLinkedCount: Function,
        getIsLoading: {type: Function, optional: true},
        getQuery: Function,
        setQuery: Function,
        resetFilters: {type: Function, optional: true},
        getMode: Function,
        setMode: Function,
        modeOptions: {type: Array, optional: true},
        getRoutingFilter: {type: Function, optional: true},
        setRoutingFilter: {type: Function, optional: true},
        routingFilterOptions: {type: Array, optional: true},
        getRows: Function,
        hasMore: Function,
        loadMore: Function,
        reloadRows: {type: Function, optional: true},
        createGroup: Function,
        editGroup: Function,
        editRuleSettings: Function,
        linkGroup: Function,
        linkAndConfigureGroup: {type: Function, optional: true},
        unlinkGroup: Function,
    };

    setup() {
        this.state = useState({
            refreshNonce: 0,
        });
    }

    _refresh() {
        this.state.refreshNonce += 1;
    }

    get dialogTitle() {
        this.state.refreshNonce;
        return _t("Manage Approval Groups");
    }

    toSafeCount(value) {
        const parsed = Number(value);
        if (!Number.isFinite(parsed) || parsed <= 0) {
            return 0;
        }
        return Math.floor(parsed);
    }

    get nodeLabel() {
        this.state.refreshNonce;
        return this.props.getNodeLabel?.() || _t("Selected node");
    }

    get totalCount() {
        this.state.refreshNonce;
        return this.toSafeCount(this.props.getTotalCount?.());
    }

    get linkedCount() {
        this.state.refreshNonce;
        return this.toSafeCount(this.props.getLinkedCount?.());
    }

    get summaryText() {
        return sprintf(_t("%(linked)s linked of %(total)s approval groups"), {
            linked: this.linkedCount,
            total: this.totalCount,
        });
    }

    get isLoading() {
        this.state.refreshNonce;
        return Boolean(this.props.getIsLoading?.());
    }

    get emptyMessage() {
        if (this.isLoading) {
            return _t("Loading approval groups...");
        }
        if (!this.totalCount) {
            return _t("No approval groups are available yet. Create one to start linking groups to this node.");
        }
        return _t("No approval groups match the current search or filter.");
    }

    get query() {
        this.state.refreshNonce;
        return this.props.getQuery?.() || "";
    }

    get mode() {
        this.state.refreshNonce;
        return this.props.getMode?.() || "all";
    }

    get rows() {
        this.state.refreshNonce;
        return this.props.getRows?.() || [];
    }

    get hasMoreRows() {
        this.state.refreshNonce;
        return Boolean(this.props.hasMore?.());
    }

    get modeOptions() {
        return this.props.modeOptions || [];
    }

    get routingFilter() {
        this.state.refreshNonce;
        return this.props.getRoutingFilter?.() || "all";
    }

    get routingFilterOptions() {
        return this.props.routingFilterOptions || [];
    }

    get hasActiveFilters() {
        return Boolean(
            this.query.trim()
            || this.mode !== "all"
            || this.routingFilter !== "all"
        );
    }

    getLinkedBadgeLabel() {
        return sprintf(_t("%(count)s linked"), {
            count: this.linkedCount,
        });
    }

    getTotalBadgeLabel() {
        return sprintf(_t("%(count)s total"), {
            count: this.totalCount,
        });
    }

    getShownCountLabel() {
        return sprintf(_t("%(count)s shown"), {
            count: this.toSafeCount(this.rows.length),
        });
    }

    get createButtonLabel() {
        return _t("Add Approval Group");
    }

    get createButtonHint() {
        return _t("Choose an existing group or create a new one, then configure its routing for this node.");
    }

    get activeRoutingFilterLabel() {
        return (
            this.routingFilterOptions.find((option) => option?.value === this.routingFilter)?.label
            || _t("All Routing")
        );
    }

    get filterSummaryText() {
        const fragments = [];
        if (this.mode === "linked") {
            fragments.push(_t("linked groups only"));
        } else if (this.mode === "available") {
            fragments.push(_t("not linked yet"));
        } else {
            fragments.push(_t("all groups"));
        }
        if (this.routingFilter !== "all") {
            fragments.push(sprintf(_t("routing focus: %s"), this.activeRoutingFilterLabel));
        }
        if (this.query.trim()) {
            fragments.push(_t("matching the current search"));
        }
        return sprintf(_t("Showing %s."), fragments.join(", "));
    }

    getGroupDepartmentLabel(groupRow = {}) {
        return groupRow.department_name || _t("No department");
    }

    getGroupMemberPreview(groupRow = {}) {
        return groupRow.memberPreview || _t("No users assigned");
    }

    getModeDisplayLabel(modeOption = {}) {
        if (modeOption?.value === "available") {
            return _t("Remaining");
        }
        return modeOption?.label || "";
    }

    getGroupLinkedRulesLabel(groupRow = {}) {
        return sprintf(_t("%(count)s rules linked on this node"), {
            count: this.toSafeCount(groupRow.linkedCount),
        });
    }

    getGroupStatusLabel(groupRow = {}) {
        return groupRow.isLinked ? _t("Linked") : _t("Available");
    }

    async onSearchInput(event) {
        const refreshPromise = this.props.setQuery?.(event?.target?.value || "");
        this._refresh();
        await refreshPromise;
        this._refresh();
    }

    async onModeChange(event) {
        const refreshPromise = this.props.setMode?.(event?.target?.value || "all");
        this._refresh();
        await refreshPromise;
        this._refresh();
    }

    async onModeShortcut(modeValue) {
        const refreshPromise = this.props.setMode?.(modeValue || "all");
        this._refresh();
        await refreshPromise;
        this._refresh();
    }

    async onRoutingFilterChange(event) {
        const refreshPromise = this.props.setRoutingFilter?.(event?.target?.value || "all");
        this._refresh();
        await refreshPromise;
        this._refresh();
    }

    async onRoutingFilterShortcut(filterValue) {
        const refreshPromise = this.props.setRoutingFilter?.(filterValue || "all");
        this._refresh();
        await refreshPromise;
        this._refresh();
    }

    async onResetFilters() {
        const refreshPromise = this.props.resetFilters?.();
        this._refresh();
        await refreshPromise;
        this._refresh();
    }

    async onLoadMore() {
        const refreshPromise = this.props.loadMore?.();
        this._refresh();
        await refreshPromise;
        this._refresh();
    }

    async refreshBrowserRows() {
        const refreshPromise = this.props.reloadRows?.({immediate: true});
        this._refresh();
        await refreshPromise;
        this._refresh();
    }

    onCreateGroup() {
        this.props.createGroup?.(() => {
            void this.refreshBrowserRows();
        });
    }

    onEditGroup(groupId) {
        this.props.editGroup?.(groupId, () => {
            void this.refreshBrowserRows();
        });
    }

    onRuleSettings(groupId) {
        this.props.editRuleSettings?.(groupId, () => {
            void this.refreshBrowserRows();
        });
    }

    async onLinkGroup(groupId) {
        await this.props.linkGroup?.(groupId);
        await this.refreshBrowserRows();
    }

    async onLinkAndConfigureGroup(groupId) {
        await this.props.linkAndConfigureGroup?.(groupId, () => {
            void this.refreshBrowserRows();
        });
        this._refresh();
    }

    async onUnlinkGroup(groupId) {
        const unlinked = await this.props.unlinkGroup?.(groupId);
        if (unlinked !== false) {
            await this.refreshBrowserRows();
        }
    }
}

export class WorkflowStudioApprovalGroupLinkDialog extends Component {
    static template = "workflow_studio.LinkApprovalGroupDialog";
    static components = {Dialog, AutoComplete, SelectMenu};
    static props = {
        close: Function,
        confirm: Function,
        approvalGroups: {type: Array, optional: true},
        approvalLinkRows: {type: Array, optional: true},
        usersOptions: {type: Array, optional: true},
        departmentOptions: {type: Array, optional: true},
        selectedGroupId: {type: Number, optional: true},
        originGroupId: {type: Number, optional: true},
        allowGroupSelection: {type: Boolean, optional: true},
        linkConfig: {type: Object, optional: true},
        linkContextLabel: {type: String, optional: true},
        requestModel: {type: String, optional: true},
        requestFields: {type: Array, optional: true},
        domainPresetsByKey: {type: Object, optional: true},
        isDebugMode: {type: Boolean, optional: true},
        workflowVersionId: {type: Number, optional: true},
        workflowCategoryId: {type: Number, optional: true},
        searchApprovalGroups: {type: Function, optional: true},
        requestCreateGroup: {type: Function, optional: true},
        requestEditGroup: {type: Function, optional: true},
    };

    setup() {
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.selectorFieldRef = useRef("approvalGroupSelectorField");
        const initialLink = this.props.linkConfig || {};
        const initialGroupId = Number(this.props.selectedGroupId || 0) || 0;
        const initialGroup = this._resolveApprovalGroupOption(initialGroupId);
        this.state = useState({
            selectedGroupId: initialGroupId,
            selectedGroupOption: initialGroup || null,
            selectorSearchText: "",
            linkSequence: Number(initialLink.sequence || 10) || 10,
            linkUserDomain: initialLink.user_domain || "",
            linkDomain: initialLink.domain || "",
            linkNote: initialLink.note || "",
            isSubmitting: false,
        });
        if (initialGroupId) {
            this._applyLinkValuesForGroup(initialGroupId, {preserveCurrent: false});
        }
    }

    get dialogTitle() {
        return this.isEditingExistingLink || this.isSelectedGroupAlreadyLinked
            ? _t("Approval Group Rule Settings")
            : _t("Add Approval Group");
    }

    get allowGroupSelection() {
        return this.props.allowGroupSelection !== false;
    }

    get originGroupId() {
        return Number(this.props.originGroupId || 0) || 0;
    }

    get isEditingExistingLink() {
        return !!this.originGroupId;
    }

    get isReplacingCurrentLinkedGroup() {
        return this.isEditingExistingLink
            && !!Number(this.state.selectedGroupId || 0)
            && Number(this.state.selectedGroupId || 0) !== this.originGroupId;
    }

    get linkContextLabel() {
        return (this.props.linkContextLabel || "").trim();
    }

    get linkConfigurationTitle() {
        if (!this.linkContextLabel) {
            return _t("Routing Rule");
        }
        return sprintf(_t("Routing Rule (%s)"), this.linkContextLabel);
    }

    get linkConfigurationHint() {
        return _t("Configure how this approval group should match records and which users from the group can receive the assignment on this node.");
    }

    get routingSafetyHint() {
        return _t("Blank or [] routing domains are ignored. Choose Always, Never, or build a custom rule before saving if this link should actively route.");
    }

    get requestModelName() {
        return (this.props.requestModel || "").trim();
    }

    get requestFields() {
        return this.props.requestFields || [];
    }

    get domainPresetsByKey() {
        return this.props.domainPresetsByKey || {};
    }

    get userDomainPresets() {
        return this.domainPresetsByKey.routing_user_assignment
            || this.domainPresetsByKey.user_assignment
            || [];
    }

    get recordDomainPresets() {
        return this.domainPresetsByKey.routing_request_scope
            || this.domainPresetsByKey.request_scope
            || [];
    }

    get selectedGroup() {
        return this.state.selectedGroupOption
            || this._resolveApprovalGroupOption(this.state.selectedGroupId)
            || null;
    }

    get originGroup() {
        return this._resolveApprovalGroupOption(this.originGroupId)
            || this.getLinkedApprovalRowByGroupId(this.originGroupId)?.approval_group_ref
            || null;
    }

    get originGroupDisplayLabel() {
        const group = this.originGroup;
        return group ? this.getApprovalGroupDisplayPath(group) : "";
    }

    get selectedGroupDisplayLabel() {
        const group = this.selectedGroup;
        return group ? this.getApprovalGroupDisplayPath(group) : "";
    }

    get selectedGroupDepartmentLabel() {
        return this.selectedGroup?.department_name || _t("No department");
    }

    get selectedGroupMemberSummary() {
        const members = this.getApprovalGroupUserNames(this.selectedGroup);
        if (!members.length) {
            return _t("No members assigned");
        }
        return members.join(", ");
    }

    get selectedGroupMemberCountLabel() {
        const members = this.getApprovalGroupUserNames(this.selectedGroup);
        if (!members.length) {
            return _t("No members");
        }
        return sprintf(_t("%s members"), members.length);
    }

    get selectedGroupStatusLabel() {
        if (this.isReplacingCurrentLinkedGroup) {
            return _t("Will replace current linked group");
        }
        return this.isSelectedGroupAlreadyLinked
            ? _t("Already linked to this node")
            : _t("Not linked to this node yet");
    }

    get isSelectedGroupAlreadyLinked() {
        return Boolean(this.getLinkedApprovalRowByGroupId(this.state.selectedGroupId));
    }

    get submitButtonLabel() {
        if (this.isReplacingCurrentLinkedGroup) {
            return _t("Replace Group & Save");
        }
        return this.isSelectedGroupAlreadyLinked ? _t("Save Rule Settings") : _t("Link & Save");
    }

    get submitBusyLabel() {
        if (this.isReplacingCurrentLinkedGroup) {
            return _t("Replacing...");
        }
        return this.isSelectedGroupAlreadyLinked ? _t("Saving...") : _t("Linking...");
    }

    get groupSelectorHint() {
        return _t("Search by group path, department, or member name. If the group does not exist yet, create it without leaving this flow.");
    }

    get groupSelectorActionLabel() {
        return this.selectedGroup ? _t("Change Group") : _t("Find Group");
    }

    get groupSelectorFieldLabel() {
        return this.allowGroupSelection ? _t("Approval Group") : _t("Linked Approval Group");
    }

    get groupSelectorFieldHint() {
        if (!this.allowGroupSelection) {
            return _t("This rule is editing the current linked group. To use a different group, return to Manage Approval Groups and choose Add Approval Group.");
        }
        if (this.isEditingExistingLink) {
            if (this.isReplacingCurrentLinkedGroup) {
                return this.originGroupDisplayLabel
                    ? sprintf(
                        _t("Saving will replace %s on this node with the selected group."),
                        this.originGroupDisplayLabel
                    )
                    : _t("Saving will replace the current linked group on this node with the selected group.");
            }
            return this.originGroupDisplayLabel
                ? sprintf(
                    _t("This rule currently edits %s. Type or click Change Group to replace it with another available group."),
                    this.originGroupDisplayLabel
                )
                : _t("Type or click Change Group to replace the current linked group with another available group.");
        }
        if (this.selectedGroup) {
            return _t("Need a different group? Click Change Group or type in the field to replace the current selection.");
        }
        return _t("Start typing to search an existing group, or create one if it does not exist yet.");
    }

    get selectedGroupSummaryHint() {
        if (this.isReplacingCurrentLinkedGroup) {
            return this.originGroupDisplayLabel
                ? sprintf(
                    _t("Saving will replace %s on this node and apply the routing rule below."),
                    this.originGroupDisplayLabel
                )
                : _t("Saving will replace the current linked group on this node with the routing rule below.");
        }
        return this.isSelectedGroupAlreadyLinked
            ? _t("This node already uses this group. Saving updates the existing rule.")
            : _t("Saving will link this group to the current node with the routing rule below.");
    }

    get approvalGroupSelectorAutocompleteProps() {
        return {
            value: this.selectedGroupDisplayLabel,
            title: this.selectedGroupDisplayLabel,
            class: "o_wfs_approval_group_selector_autocomplete",
            menuCssClass: "o_wfs_approval_group_selector_menu",
            placeholder: _t("Search approval groups..."),
            searchOnInputClick: true,
            resetOnSelect: false,
            sources: [
                {
                    placeholder: _t("Loading..."),
                    optionSlot: "approvalGroupOption",
                    options: (searchTerm) => this.getApprovalGroupSelectorOptions(searchTerm),
                },
            ],
            onInput: ({inputValue}) => {
                this.state.selectorSearchText = inputValue || "";
            },
            onChange: ({inputValue, isOptionSelected}) => {
                this.state.selectorSearchText = inputValue || "";
                if (!isOptionSelected && !(inputValue || "").trim()) {
                    this.state.selectedGroupId = 0;
                    this.state.selectedGroupOption = null;
                }
            },
        };
    }

    _normalizeApprovalGroupSearch(value) {
        return `${value || ""}`.trim().toLowerCase().replace(/\s+/g, " ");
    }

    _resolveApprovalGroupOption(groupId) {
        const normalizedGroupId = Number(groupId || 0);
        if (!normalizedGroupId) {
            return null;
        }
        return (this.props.approvalGroups || []).find(
            (group) => Number(group?.id || 0) === normalizedGroupId
        ) || null;
    }

    isSelectableApprovalGroup(groupOption) {
        const groupId = Number(groupOption?.id || 0);
        if (!groupId) {
            return false;
        }
        if (!this.isEditingExistingLink) {
            return true;
        }
        const linkedRow = this.getLinkedApprovalRowByGroupId(groupId);
        if (!linkedRow) {
            return true;
        }
        return groupId === this.originGroupId;
    }

    getApprovalGroupDisplayPath(groupOption) {
        if (!groupOption) {
            return "";
        }
        return groupOption.display_path || groupOption.name || "";
    }

    getApprovalGroupUserNames(groupOption) {
        return (groupOption?.user_names || [])
            .map((name) => `${name || ""}`.trim())
            .filter((name) => name && name.toLowerCase() !== "nan");
    }

    getApprovalGroupMemberSummary(groupOption, limit = 3) {
        const userNames = this.getApprovalGroupUserNames(groupOption);
        if (!userNames.length) {
            return _t("No members assigned");
        }
        if (!limit || userNames.length <= limit) {
            return userNames.join(", ");
        }
        const preview = userNames.slice(0, limit).join(", ");
        return sprintf(_t("%(names)s +%(count)s more"), {
            names: preview,
            count: userNames.length - limit,
        });
    }

    getApprovalGroupSearchHaystack(groupOption) {
        return this._normalizeApprovalGroupSearch([
            this.getApprovalGroupDisplayPath(groupOption),
            groupOption?.name || "",
            groupOption?.department_name || "",
            ...this.getApprovalGroupUserNames(groupOption),
        ].join(" "));
    }

    async searchApprovalGroupOptions(searchTerm = "") {
        if (this.props.searchApprovalGroups) {
            try {
                const rows = await this.props.searchApprovalGroups(searchTerm);
                if (Array.isArray(rows)) {
                    return rows.filter((groupOption) => this.isSelectableApprovalGroup(groupOption));
                }
            } catch {
                // Fall back to the locally loaded group catalog if the remote search is unavailable.
            }
        }
        const normalizedTerm = this._normalizeApprovalGroupSearch(searchTerm);
        const groups = [...(this.props.approvalGroups || [])];
        if (!normalizedTerm) {
            return groups.filter((groupOption) => this.isSelectableApprovalGroup(groupOption));
        }
        return groups.filter(
            (groupOption) => this.isSelectableApprovalGroup(groupOption)
                && this.getApprovalGroupSearchHaystack(groupOption).includes(normalizedTerm)
        );
    }

    async getApprovalGroupSelectorOptions(searchTerm = "") {
        const normalizedTerm = this._normalizeApprovalGroupSearch(searchTerm);
        const rawRows = await this.searchApprovalGroupOptions(searchTerm);
        const groups = [...(rawRows || [])].sort((left, right) =>
            this.getApprovalGroupDisplayPath(left).localeCompare(this.getApprovalGroupDisplayPath(right))
        );
        const options = groups.slice(0, 8).map((groupOption) => ({
            label: this.getApprovalGroupDisplayPath(groupOption),
            data: {
                type: "group",
                group: groupOption,
            },
            onSelect: () => this.selectApprovalGroup(groupOption),
        }));
        const hasExactMatch = normalizedTerm && groups.some((groupOption) => {
            const labels = [
                this.getApprovalGroupDisplayPath(groupOption),
                groupOption?.name || "",
            ];
            return labels.some((label) => this._normalizeApprovalGroupSearch(label) === normalizedTerm);
        });
        if (normalizedTerm && !hasExactMatch) {
            options.push({
                cssClass: "o_m2o_dropdown_option",
                label: sprintf(_t('Create "%s"'), searchTerm.trim()),
                data: {type: "action", action: "create"},
                onSelect: () => this.onCreateGroupFromSelector(searchTerm, {createAndEdit: false}),
            });
            options.push({
                cssClass: "o_m2o_dropdown_option",
                label: _t("Create and edit..."),
                data: {type: "action", action: "create_edit"},
                onSelect: () => this.onCreateGroupFromSelector(searchTerm, {createAndEdit: true}),
            });
        }
        if (!options.length) {
            options.push({label: _t("(no result)")});
        }
        return options;
    }

    getLinkedApprovalRowByGroupId(groupId) {
        const normalizedGroupId = Number(groupId || 0);
        if (!normalizedGroupId) {
            return null;
        }
        return (this.props.approvalLinkRows || []).find((row) => {
            const rowGroupId = Number(row?.approval_group_ref?.id || row?.approval_group_id || 0);
            return rowGroupId === normalizedGroupId;
        }) || null;
    }

    _applyLinkValues(source = {}, {preserveCurrent = false} = {}) {
        if (!preserveCurrent) {
            this.state.linkSequence = Number(source.sequence || 10) || 10;
            this.state.linkUserDomain = source.user_domain || "";
            this.state.linkDomain = source.domain || "";
            this.state.linkNote = source.note || "";
            return;
        }
        this.state.linkSequence = Number(this.state.linkSequence || source.sequence || 10) || 10;
        this.state.linkUserDomain = this.state.linkUserDomain || source.user_domain || "";
        this.state.linkDomain = this.state.linkDomain || source.domain || "";
        this.state.linkNote = this.state.linkNote || source.note || "";
    }

    _applyLinkValuesForGroup(groupId, {preserveCurrent = false} = {}) {
        const source = this.getLinkedApprovalRowByGroupId(groupId) || this.props.linkConfig || {};
        this._applyLinkValues(source, {preserveCurrent});
    }

    selectApprovalGroup(groupOption, {preserveLinkValues = false} = {}) {
        const normalizedGroupId = Number(groupOption?.id || 0);
        this.state.selectedGroupId = normalizedGroupId;
        this.state.selectedGroupOption = groupOption || null;
        this._applyLinkValuesForGroup(normalizedGroupId, {preserveCurrent: preserveLinkValues});
    }

    async onCreateGroupFromSelector(searchTerm = "", {createAndEdit = false} = {}) {
        if (!this.props.requestCreateGroup) {
            return;
        }
        await this.props.requestCreateGroup({
            initialName: `${searchTerm || ""}`.trim(),
            createAndEdit,
            afterCreate: (groupOption) => {
                if (groupOption?.id) {
                    this.selectApprovalGroup(groupOption, {preserveLinkValues: true});
                }
            },
        });
    }

    onEditSelectedGroup() {
        const group = this.selectedGroup;
        if (!group?.id || !this.props.requestEditGroup) {
            return;
        }
        this.props.requestEditGroup(group.id, {
            afterUpdate: (updatedGroupOption) => {
                if (updatedGroupOption?.id) {
                    this.state.selectedGroupOption = updatedGroupOption;
                }
            },
        });
    }

    onChangeSelectedGroup() {
        if (!this.allowGroupSelection) {
            return;
        }
        const input = this.selectorFieldRef.el?.querySelector("input");
        if (!input) {
            return;
        }
        input.focus();
        if (typeof input.select === "function") {
            input.select();
        }
        input.dispatchEvent(new MouseEvent("click", {bubbles: true}));
    }

    normalizeRuleDomainLiteral(domainLiteral) {
        return `${domainLiteral || ""}`.trim();
    }

    classifyRuleDomainState(domainLiteral) {
        const normalized = this.normalizeRuleDomainLiteral(domainLiteral);
        if (!normalized) {
            return "ignored_blank";
        }
        const compact = normalized.replace(/\s+/g, "");
        if (compact === "[]") {
            return "ignored_empty";
        }
        if (compact === "[(1,'=',1)]") {
            return "always_true";
        }
        if (compact === "[(0,'=',1)]") {
            return "always_false";
        }
        return "active_valid";
    }

    getRuleDomainState(fieldName) {
        return this.classifyRuleDomainState(this.state[fieldName] || "");
    }

    getRuleDomainHelperText(fieldName) {
        const isUserDomain = fieldName === "linkUserDomain";
        const state = this.getRuleDomainState(fieldName);
        if (state === "ignored_blank") {
            return _t("Ignored until you choose Always, Never, or a custom rule.");
        }
        if (state === "ignored_empty") {
            return _t("[] is ignored for routing. Use Always or Never instead.");
        }
        if (state === "always_true") {
            return isUserDomain
                ? _t("Always keeps every user from this group available for the selected node.")
                : _t("Always lets this link match every request record for the selected node.");
        }
        if (state === "always_false") {
            return isUserDomain
                ? _t("Never contributes any users from this group to the selected node.")
                : _t("Never lets this link match any request record for the selected node.");
        }
        return _t("Custom routing rule is configured.");
    }

    getRuleDomainHelperClass(fieldName) {
        const state = this.getRuleDomainState(fieldName);
        if (state === "ignored_blank" || state === "ignored_empty") {
            return "is-warning";
        }
        if (state === "always_false") {
            return "is-neutral";
        }
        return "is-ready";
    }

    onRuleInputChange(fieldName, event) {
        const value = event?.target?.value ?? "";
        if (fieldName === "linkSequence") {
            this.state.linkSequence = Number(value || 10) || 10;
            return;
        }
        this.state[fieldName] = value;
    }

    onRuleDomainPresetChange(fieldName, event) {
        const domain = event?.target?.value || "";
        if (!domain) {
            return;
        }
        this.state[fieldName] = domain;
        event.target.value = "";
    }

    getRuleDomainPresetSelectProps(fieldName) {
        const presets = fieldName === "linkUserDomain"
            ? this.userDomainPresets
            : this.recordDomainPresets;
        return {
            choices: presets.map((preset) => ({
                value: preset.domain,
                label: preset.label,
            })),
            value: "",
            onSelect: (domain) => {
                if (domain) {
                    this.state[fieldName] = domain;
                }
            },
            searchable: true,
            autoSort: false,
            placeholder: _t("Apply preset..."),
            class: "o_wfs_dialog_select mt-2",
            togglerClass: "form-select o_wfs_dialog_select_toggler",
            menuClass: "o_wfs_dialog_select_menu",
        };
    }

    openRuleDomainBuilder(fieldName, contextType = "generic") {
        const isUserDomain = fieldName === "linkUserDomain";
        const resolvedContext = isUserDomain ? "assignment_users_routing" : "request_scope_routing";
        const model = isUserDomain ? "res.users" : this.requestModelName;
        if (!model) {
            this.notification.add(_t("No request model configured for record domain builder."), {
                type: "warning",
            });
            return;
        }
        const presetKey = isUserDomain ? "routing_user_assignment" : "routing_request_scope";
        const presets = this.domainPresetsByKey[presetKey] || [];
        this.dialog.add(WorkflowStudioDomainDialog, {
            resModel: model,
            requestModel: this.requestModelName || model,
            requestFields: this.requestFields,
            workflowVersionId: Number(this.props.workflowVersionId || 0) || 0,
            workflowCategoryId: Number(this.props.workflowCategoryId || 0) || 0,
            domain: this.state[fieldName] || "",
            title: isUserDomain ? _t("Approval Group User Domain") : _t("Approval Group Record Domain"),
            contextType: resolvedContext,
            presets,
            isDebugMode: !!this.props.isDebugMode,
            allowBlankDomain: true,
            onConfirm: (domain) => {
                this.state[fieldName] = domain;
            },
        });
    }

    async onConfirm() {
        if (this.state.isSubmitting) {
            return;
        }
        if (!Number(this.state.selectedGroupId || 0)) {
            this.notification.add(_t("Select an approval group before saving."), {
                type: "warning",
            });
            return;
        }
        this.state.isSubmitting = true;
        try {
            const done = await this.props.confirm({
                selected_group_id: Number(this.state.selectedGroupId || 0) || 0,
                origin_group_id: this.originGroupId,
                link_values: {
                    sequence: Number(this.state.linkSequence || 10) || 10,
                    user_domain: (this.state.linkUserDomain || "").trim(),
                    domain: (this.state.linkDomain || "").trim(),
                    note: (this.state.linkNote || "").trim(),
                },
            });
            if (done) {
                this.props.close();
            }
        } finally {
            this.state.isSubmitting = false;
        }
    }
}

export class WorkflowStudioApprovalGroupDialog extends Component {
    static template = "workflow_studio.CreateApprovalGroupDialog";
    static components = {Dialog, MultiRecordSelector, SelectMenu};
    static props = {
        close: Function,
        confirm: Function,
        mode: {type: String, optional: true},
        initialGroup: {type: Object, optional: true},
        approvalGroups: {type: Array, optional: true},
        approvalLinkRows: {type: Array, optional: true},
        usersOptions: {type: Array, optional: true},
        departmentOptions: {type: Array, optional: true},
        linkConfig: {type: Object, optional: true},
        linkContextLabel: {type: String, optional: true},
        initialName: {type: String, optional: true},
        requestModel: {type: String, optional: true},
        requestFields: {type: Array, optional: true},
        domainPresetsByKey: {type: Object, optional: true},
        isDebugMode: {type: Boolean, optional: true},
        workflowVersionId: {type: Number, optional: true},
        workflowCategoryId: {type: Number, optional: true},
    };

    setup() {
        const group = this.props.initialGroup || {};
        const link = this.props.linkConfig || {};
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({
            name: this.props.initialName || group.name || "",
            parentId: group.parent_id || 0,
            departmentId: group.department_id || 0,
            userIds: Array.isArray(group.user_ids) ? [...group.user_ids] : [],
            linkSequence: Number(link.sequence || 10) || 10,
            linkUserDomain: link.user_domain || "",
            linkDomain: link.domain || "",
            linkNote: link.note || "",
            isSubmitting: false,
        });
    }

    get isEditMode() {
        return (this.props.mode || "create") === "edit";
    }

    get dialogTitle() {
        if (this.isEditMode) {
            return _t("Configure Approval Group");
        }
        return _t("Create Approval Group");
    }

    get hasLinkConfig() {
        return !!this.props.linkConfig;
    }

    get linkContextLabel() {
        return (this.props.linkContextLabel || "").trim();
    }

    get linkConfigurationTitle() {
        if (!this.linkContextLabel) {
            return _t("Rule Configuration (Selected Node)");
        }
        return sprintf(_t("Rule Configuration (%s)"), this.linkContextLabel);
    }

    get linkConfigurationHint() {
        if (this.isEditMode) {
            return _t("Update the link rule used when this group is assigned to the selected node.");
        }
        return _t("This new group will be linked to the selected node as soon as you save it. Set the user filter and record domain now so there is no second setup step.");
    }

    get routingSafetyHint() {
        return _t("Blank or [] routing domains are ignored. Choose Always, Never, or build a custom rule before saving if this link should actively route.");
    }

    get groupOptions() {
        const currentId = Number(this.props.initialGroup?.id || 0);
        return (this.props.approvalGroups || []).filter((group) => Number(group.id) !== currentId);
    }

    get departments() {
        return this.props.departmentOptions || [];
    }

    get parentGroupSelectProps() {
        return {
            choices: [
                {value: 0, label: _t("None")},
                ...this.groupOptions.map((group) => ({
                    value: Number(group.id),
                    label: group.display_path || group.name,
                })),
            ],
            value: Number(this.state.parentId || 0),
            onSelect: (value) => {
                this.state.parentId = Number(value || 0);
            },
            searchable: true,
            autoSort: false,
            class: "o_wfs_dialog_select",
            togglerClass: "o_wfs_dialog_select_toggler",
        };
    }

    get departmentSelectProps() {
        return {
            choices: [
                {value: 0, label: _t("None")},
                ...this.departments.map((department) => ({
                    value: Number(department.id),
                    label: department.name,
                })),
            ],
            value: Number(this.state.departmentId || 0),
            onSelect: (value) => {
                this.state.departmentId = Number(value || 0);
            },
            searchable: true,
            autoSort: false,
            class: "o_wfs_dialog_select",
            togglerClass: "o_wfs_dialog_select_toggler",
        };
    }

    get usersMultiSelectorProps() {
        return {
            resModel: "res.users",
            resIds: [...(this.state.userIds || [])],
            fieldString: _t("Members"),
            placeholder: _t("Select members..."),
            update: (resIds) => {
                this.state.userIds = (resIds || []).map((id) => Number(id)).filter((id) => id > 0);
            },
        };
    }

    get requestModelName() {
        return (this.props.requestModel || "").trim();
    }

    get requestFields() {
        return this.props.requestFields || [];
    }

    get domainPresetsByKey() {
        return this.props.domainPresetsByKey || {};
    }

    get userDomainPresets() {
        return this.domainPresetsByKey.routing_user_assignment
            || this.domainPresetsByKey.user_assignment
            || [];
    }

    get recordDomainPresets() {
        return this.domainPresetsByKey.routing_request_scope
            || this.domainPresetsByKey.request_scope
            || [];
    }

    get submitButtonLabel() {
        if (this.isEditMode) {
            return _t("Save");
        }
        return this.hasLinkConfig ? _t("Create, Link & Save") : _t("Create");
    }

    get submitBusyLabel() {
        if (this.isEditMode) {
            return _t("Saving...");
        }
        return this.hasLinkConfig ? _t("Creating & Linking...") : _t("Creating...");
    }

    normalizeRuleDomainLiteral(domainLiteral) {
        return `${domainLiteral || ""}`.trim();
    }

    classifyRuleDomainState(domainLiteral) {
        const normalized = this.normalizeRuleDomainLiteral(domainLiteral);
        if (!normalized) {
            return "ignored_blank";
        }
        const compact = normalized.replace(/\s+/g, "");
        if (compact === "[]") {
            return "ignored_empty";
        }
        if (compact === "[(1,'=',1)]") {
            return "always_true";
        }
        if (compact === "[(0,'=',1)]") {
            return "always_false";
        }
        return "active_valid";
    }

    getRuleDomainState(fieldName) {
        return this.classifyRuleDomainState(this.state[fieldName] || "");
    }

    getRuleDomainHelperText(fieldName) {
        const isUserDomain = fieldName === "linkUserDomain";
        const state = this.getRuleDomainState(fieldName);
        if (state === "ignored_blank") {
            return _t("Ignored until you choose Always, Never, or a custom rule.");
        }
        if (state === "ignored_empty") {
            return _t("[] is ignored for routing. Use Always or Never instead.");
        }
        if (state === "always_true") {
            return isUserDomain
                ? _t("Always keeps every user from this group available for the selected node.")
                : _t("Always lets this link match every request record for the selected node.");
        }
        if (state === "always_false") {
            return isUserDomain
                ? _t("Never contributes any users from this group to the selected node.")
                : _t("Never lets this link match any request record for the selected node.");
        }
        return _t("Custom routing rule is configured.");
    }

    getRuleDomainHelperClass(fieldName) {
        const state = this.getRuleDomainState(fieldName);
        if (state === "ignored_blank" || state === "ignored_empty") {
            return "is-warning";
        }
        if (state === "always_false") {
            return "is-neutral";
        }
        return "is-ready";
    }

    onRuleInputChange(fieldName, event) {
        const value = event?.target?.value ?? "";
        if (fieldName === "linkSequence") {
            this.state.linkSequence = Number(value || 10) || 10;
            return;
        }
        this.state[fieldName] = value;
    }

    onRuleDomainPresetChange(fieldName, event) {
        const domain = event?.target?.value || "";
        if (!domain) {
            return;
        }
        this.state[fieldName] = domain;
        event.target.value = "";
    }

    getRuleDomainPresetSelectProps(fieldName) {
        const presets = fieldName === "linkUserDomain"
            ? this.userDomainPresets
            : this.recordDomainPresets;
        return {
            choices: presets.map((preset) => ({
                value: preset.domain,
                label: preset.label,
            })),
            value: "",
            onSelect: (domain) => {
                if (domain) {
                    this.state[fieldName] = domain;
                }
            },
            searchable: true,
            autoSort: false,
            placeholder: _t("Apply preset..."),
            class: "o_wfs_dialog_select mt-2",
            togglerClass: "form-select o_wfs_dialog_select_toggler",
            menuClass: "o_wfs_dialog_select_menu",
        };
    }

    openRuleDomainBuilder(fieldName, contextType = "generic") {
        const isUserDomain = fieldName === "linkUserDomain";
        const resolvedContext = isUserDomain ? "assignment_users_routing" : "request_scope_routing";
        const model = isUserDomain ? "res.users" : this.requestModelName;
        if (!model) {
            this.notification.add(_t("No request model configured for record domain builder."), {
                type: "warning",
            });
            return;
        }
        const presetKey = isUserDomain ? "routing_user_assignment" : "routing_request_scope";
        const presets = this.domainPresetsByKey[presetKey] || [];
        this.dialog.add(WorkflowStudioDomainDialog, {
            resModel: model,
            requestModel: this.requestModelName || model,
            requestFields: this.requestFields,
            workflowVersionId: Number(this.props.workflowVersionId || 0) || 0,
            workflowCategoryId: Number(this.props.workflowCategoryId || 0) || 0,
            domain: this.state[fieldName] || "",
            title: isUserDomain ? _t("Approval Group User Domain") : _t("Approval Group Record Domain"),
            contextType: resolvedContext,
            presets,
            isDebugMode: !!this.props.isDebugMode,
            allowBlankDomain: true,
            onConfirm: (domain) => {
                this.state[fieldName] = domain;
            },
        });
    }

    async onConfirm() {
        if (this.state.isSubmitting) {
            return;
        }
        this.state.isSubmitting = true;
        try {
            const payload = {
                name: (this.state.name || "").trim(),
                parent_id: Number(this.state.parentId || 0) || false,
                department_id: Number(this.state.departmentId || 0) || false,
                user_ids: this.state.userIds || [],
            };
            if (this.hasLinkConfig) {
                payload.link_values = {
                    sequence: Number(this.state.linkSequence || 10) || 10,
                    user_domain: (this.state.linkUserDomain || "").trim(),
                    domain: (this.state.linkDomain || "").trim(),
                    note: (this.state.linkNote || "").trim(),
                };
            }
            const done = await this.props.confirm(payload);
            if (done) {
                this.props.close();
            }
        } finally {
            this.state.isSubmitting = false;
        }
    }
}

export class WorkflowStudioBpmnEditor extends Component {
    static template = "workflow_studio.BpmnEditor";
    static props = {...standardActionServiceProps};
    static components = {
        AutoComplete,
        MultiRecordSelector,
        WorkflowStudioMetaFieldDialog,
        WorkflowStudioMetaFieldManagerDialog,
        WorkflowStudioCopyMetaFieldDialog,
    };

    setup() {
        this.studio = useStudioServiceAsReactive();
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");

        this.canvasRef = useRef("canvas");
        this.fileInputRef = useRef("fileInput");
        this.zipFileInputRef = useRef("zipFileInput");

        this.state = useState({
            isLoading: true,
            isSaving: false,
            isDirty: false,
            categoryId: null,
            categoryName: "",
            versionId: null,
            versionTitle: "",
            activeVersionId: null,
            versions: [],
            rollbackCandidateId: null,
            versionIsLocked: false,
            versionIsActive: false,
            versionIsPublished: false,
            versionLifecycleState: "draft",
            versionLifecycleLabel: "Draft",
            resModelName: "",
            canEdit: false,
            infoMessage: "",
            lastSavedXml: "",
            currentXml: "",
            sidebarTab: "add",
            versionMenuOpen: false,
            canCreateInitialVersion: false,
            payload: null,
            selectedElement: null,
            selectedTask: null,
            selectedAction: null,
            notificationChannelQuery: "",
            selectedNotificationChannelQuery: "",
            metaFieldRows: [],
            metaFieldSearchQuery: "",
            pendingMetaFieldRowsByNode: {},
            approvalLinkRows: [],
            approvalGroupCatalogQuery: "",
            approvalGroupCatalogRows: [],
            approvalGroupCatalogTotal: 0,
            approvalGroupCatalogTotalGroups: 0,
            approvalGroupCatalogLinkedCount: 0,
            approvalGroupCatalogHasMore: false,
            approvalGroupCatalogPending: false,
            approvalGroupCatalogMode: "all",
            approvalGroupCatalogRoutingFilter: "all",
            workflowMapRows: [],
            isCanvasDragOver: false,
        });
        this._isUndoScheduled = false;
        this._isAutoMetaSyncInProgress = false;
        this._isRecoveringDiagram = false;
        this._lastAutoMetaSyncKey = null;
        this._propertyHelpRafId = null;
        this._approvalGroupCatalogSearchTimer = null;
        this._approvalGroupCatalogScheduledResolver = null;
        this._approvalGroupCatalogSearchSequence = 0;
        this._bpmnModelerConstructor = null;
        this._onWindowResize = () => this.fitDiagram({retries: 2});
        this._onDocumentClick = () => {
            if (this.state.versionMenuOpen) {
                this.state.versionMenuOpen = false;
            }
        };

        onWillStart(async () => {
            await this._loadModelerLibrary();
            await this._loadCategoryAndVersion();
            if (this.state.canEdit) {
                await this._loadEditorPayload();
            }
        });

        onMounted(async () => {
            if (!this.state.canEdit) {
                return;
            }
            try {
                await this._waitForCanvasReady({retries: 40});
                await this._mountModeler(this.state.currentXml || DEFAULT_BPMN_XML);
                window.addEventListener("resize", this._onWindowResize);
                document.addEventListener("click", this._onDocumentClick);
                setTimeout(() => this.fitDiagram({retries: 10}), 180);
                setTimeout(() => this.fitDiagram({retries: 10}), 600);
                setTimeout(() => this.fitDiagram({retries: 10}), 1400);
                this._scheduleApplyPropertyLabelHelp();
            } catch (error) {
                this.state.canEdit = false;
                this.state.infoMessage = this._rpcErrorMessage(
                    error,
                    _t("Failed to initialize BPMN editor.")
                );
            }
        });

        onPatched(() => {
            this._scheduleApplyPropertyLabelHelp();
        });

        onWillUnmount(() => {
            if (this._approvalGroupCatalogSearchTimer) {
                clearTimeout(this._approvalGroupCatalogSearchTimer);
                this._approvalGroupCatalogSearchTimer = null;
            }
            if (this._approvalGroupCatalogScheduledResolver) {
                this._approvalGroupCatalogScheduledResolver(false);
                this._approvalGroupCatalogScheduledResolver = null;
            }
            if (this._propertyHelpRafId) {
                cancelAnimationFrame(this._propertyHelpRafId);
                this._propertyHelpRafId = null;
            }
            if (this._commandChangedHandler && this.modeler) {
                this.modeler.get("eventBus")?.off("commandStack.changed", this._commandChangedHandler);
            }
            if (this._selectionChangedHandler && this.modeler) {
                this.modeler.get("eventBus")?.off("selection.changed", this._selectionChangedHandler);
            }
            if (this._shapeCreateHandler && this.modeler) {
                this.modeler
                    .get("eventBus")
                    ?.off("commandStack.shape.create.postExecuted", this._shapeCreateHandler);
            }
            if (this._shapeReplaceHandler && this.modeler) {
                this.modeler
                    .get("eventBus")
                    ?.off("commandStack.shape.replace.postExecuted", this._shapeReplaceHandler);
            }
            if (this._connectionCreateHandler && this.modeler) {
                this.modeler
                    .get("eventBus")
                    ?.off("commandStack.connection.create.postExecuted", this._connectionCreateHandler);
            }
            if (this._connectionReconnectHandler && this.modeler) {
                this.modeler
                    .get("eventBus")
                    ?.off("commandStack.connection.reconnectStart.postExecuted", this._connectionReconnectHandler);
            }
            window.removeEventListener("resize", this._onWindowResize);
            document.removeEventListener("click", this._onDocumentClick);
            this.modeler?.destroy?.();
            this.modeler = null;
        });
    }

    async _waitForCanvasReady({retries = 30, delay = 50} = {}) {
        for (let i = 0; i < retries; i++) {
            await new Promise((r) => requestAnimationFrame(r));

            const el = this.canvasRef.el;
            if (el && el.isConnected && el.clientWidth > 16 && el.clientHeight > 16) {
                return true;
            }
            await new Promise((r) => setTimeout(r, delay));
        }
        return false;
    }

    async _loadModelerLibrary() {
        try {
            this._bpmnModelerConstructor = this._resolveBpmnModelerConstructor();
            if (!this._bpmnModelerConstructor) {
                await loadJS(BPMN_MODELER_LIB_URL);
                this._bpmnModelerConstructor = this._resolveBpmnModelerConstructor();
            }
            // Another screen may have replaced the global constructor with the viewer variant.
            // Force-load the modeler script with a cache-busting query to recover reliably.
            if (!this._bpmnModelerConstructor) {
                await loadJS(`${BPMN_MODELER_LIB_URL}?workflow_studio_modeler=${Date.now()}`);
                this._bpmnModelerConstructor = this._resolveBpmnModelerConstructor();
            }
            if (!this._bpmnModelerConstructor) {
                this.state.infoMessage = _t(
                    "Loaded BPMN library is viewer-only. Modeler services are unavailable."
                );
            }
        } catch (error) {
            if (!(error instanceof AssetsLoadingError)) {
                throw error;
            }
            this.state.infoMessage = _t("Unable to load BPMN modeler assets.");
        }
    }

    _resolveBpmnModelerConstructor() {
        const candidates = [
            window.BpmnModeler,
            window.BpmnJS?.Modeler,
            window.BpmnJS,
        ];
        return candidates.find((Ctor) => this._isUsableModelerConstructor(Ctor)) || null;
    }

    _isUsableModelerConstructor(Ctor) {
        if (typeof Ctor !== "function" || typeof document === "undefined") {
            return false;
        }
        if (typeof Ctor.prototype?.importXML !== "function") {
            return false;
        }
        const probeContainer = document.createElement("div");
        probeContainer.style.position = "absolute";
        probeContainer.style.left = "-10000px";
        probeContainer.style.top = "-10000px";
        probeContainer.style.width = "10px";
        probeContainer.style.height = "10px";
        probeContainer.style.overflow = "hidden";
        document.body.appendChild(probeContainer);
        let instance = null;
        try {
            instance = new Ctor({container: probeContainer});
            return !!instance?.get?.("modeling", false);
        } catch {
            return false;
        } finally {
            try {
                instance?.destroy?.();
            } catch {
                // no-op
            }
            probeContainer.remove();
        }
    }

    _normalizeBpmnXml(xml, {fallbackToDefault = true} = {}) {
        const extractedXml = extractImportableBpmnXml(xml);
        if (extractedXml) {
            return ensureBpmnDiagramXml(extractedXml);
        }
        if (typeof xml === "string" && xml.trim()) {
            return xml.trim();
        }
        return fallbackToDefault ? DEFAULT_BPMN_XML : "";
    }

    _getWorkflowContextIds() {
        const editedAction = this.studio.editedAction || {};
        return resolveWorkflowContextIds({
            context: editedAction.context || {},
            routeState: router.current || {},
            actionResModel: editedAction.res_model || this.props.action?.res_model || "",
            actionResId: editedAction.res_id,
            controllerResId: this.studio.editedControllerState?.resId,
        });
    }

    async _inferCategoryIdFromCurrentModel() {
        const modelName = [
            this.studio.editedAction?.res_model,
            this.props.action?.res_model,
            this.props.action?.params?.model,
        ].find((value) => typeof value === "string" && value.trim());

        if (!modelName) {
            return null;
        }
        try {
            const categories = await this.orm.searchRead(
                "workflow.approval.category",
                [["res_model.model", "=", modelName]],
                ["id", "active_version_id"],
                {limit: 5, order: "id desc"}
            );
            if (!categories?.length) {
                return null;
            }
            const withActiveVersion = categories.find((row) => !!row.active_version_id?.[0]);
            return toPositiveInt((withActiveVersion || categories[0]).id);
        } catch (_error) {
            return null;
        }
    }

    async _readVersionRecord(versionId) {
        const [version] = await this.orm.read("workflow.approval.category.version", [versionId], [
            "title",
            "name",
            "bpmn_xml",
            "res_model_name",
            "category_id",
            "is_locked",
            "is_active",
            "is_published",
        ]);
        return version || null;
    }

    async _resolveVersionForCategory(categoryId, preferredVersionId = null) {
        if (preferredVersionId) {
            const preferred = await this._readVersionRecord(preferredVersionId);
            if (preferred && preferred.category_id?.[0] === categoryId) {
                const [category] = await this.orm.read("workflow.approval.category", [categoryId], [
                    "display_name",
                    "active_version_id",
                ]);
                return {category: category || null, versionId: preferredVersionId, version: preferred};
            }
        }

        const [category] = await this.orm.read("workflow.approval.category", [categoryId], [
            "display_name",
            "active_version_id",
        ]);
        if (!category) {
            return {category: null, versionId: null, version: null};
        }

        let versionId = category.active_version_id?.[0] || null;
        if (!versionId) {
            const versions = await this.orm.searchRead(
                "workflow.approval.category.version",
                [["category_id", "=", categoryId]],
                ["id"],
                {limit: 1, order: "sequence desc, id desc"}
            );
            versionId = versions?.[0]?.id || null;
        }
        if (!versionId) {
            return {category, versionId: null, version: null};
        }

        const version = await this._readVersionRecord(versionId);
        return {category, versionId, version};
    }

    async _loadCategoryAndVersion() {
        const {categoryId: contextCategoryId, versionId: contextVersionId} =
            this._getWorkflowContextIds();
        let categoryId = contextCategoryId;

        if (!categoryId && contextVersionId) {
            const contextVersion = await this._readVersionRecord(contextVersionId);
            categoryId = contextVersion?.category_id?.[0] || null;
        }
        if (!categoryId) {
            categoryId = await this._inferCategoryIdFromCurrentModel();
        }

        this.state.categoryId = categoryId;

        if (!categoryId) {
            this.state.infoMessage = _t(
                "Open Workflow Studio from an Approval Category to design the BPMN diagram."
            );
            this.state.canEdit = false;
            this.state.canCreateInitialVersion = false;
            this.state.isLoading = false;
            return;
        }

        const {category, versionId, version} = await this._resolveVersionForCategory(
            categoryId,
            contextVersionId || null
        );

        if (!category) {
            this.state.infoMessage = _t("Workflow category not found.");
            this.state.canEdit = false;
            this.state.canCreateInitialVersion = false;
            this.state.isLoading = false;
            return;
        }

        this.state.categoryName = category.display_name;
        if (!versionId || !version) {
            this.state.infoMessage = _t("No workflow version found for this category.");
            this.state.canEdit = false;
            this.state.canCreateInitialVersion = true;
            this.state.isLoading = false;
            return;
        }

        this.state.infoMessage = "";
        this.state.canCreateInitialVersion = false;
        this.state.versionId = versionId;
        this.state.versionTitle = version.title || version.name || _t("Active Version");
        this.state.resModelName = version.res_model_name || "";
        this.state.versionIsLocked = !!version.is_locked;
        this.state.versionIsActive = !!version.is_active;
        this.state.versionIsPublished = !!version.is_published;
        this.state.versionLifecycleState = version.is_active
            ? (version.is_published ? "published" : "deployed")
            : (version.is_published ? "published" : "draft");
        this.state.versionLifecycleLabel = this.state.versionLifecycleState === "published"
            ? _t("Published")
            : this.state.versionLifecycleState === "deployed"
                ? _t("Deployed")
                : _t("Draft");
        this.state.currentXml = this._normalizeBpmnXml(version.bpmn_xml);
        this.state.lastSavedXml = this.state.currentXml;
        this.state.canEdit = !!this._bpmnModelerConstructor;
        if (!this.state.canEdit && !this.state.infoMessage) {
            this.state.infoMessage = _t("BPMN modeler is not available in this browser session.");
        }
        this.state.isLoading = false;
    }

    async _loadEditorPayload() {
        if (!this.state.versionId) {
            return;
        }
        const payload = await this.orm.call(
            "workflow.approval.category.version",
            "workflow_studio_get_bpmn_payload",
            [[this.state.versionId]]
        );
        this._setPayload(payload);
    }

    _setPayload(payload) {
        this.state.payload = payload || {options: {}, meta: {}};
        this.state.resModelName = payload?.version?.res_model_name || this.state.resModelName;
        this.state.versionId = payload?.version?.id || this.state.versionId;
        this.state.versionIsLocked = !!payload?.version?.is_locked;
        this.state.versionIsActive = !!payload?.version?.is_active;
        this.state.versionIsPublished = !!payload?.version?.is_published;
        this.state.versionLifecycleState = payload?.version?.lifecycle_state || this.state.versionLifecycleState;
        this.state.versionLifecycleLabel = payload?.version?.lifecycle_label || this.state.versionLifecycleLabel;
        this._applyVersionControl(payload?.version_control);
        if (payload?.version?.title || payload?.version?.name) {
            this.state.versionTitle = payload.version.title || payload.version.name;
        }
        if (!this.modeler && payload?.version?.bpmn_xml) {
            this.state.currentXml = this._normalizeBpmnXml(payload.version.bpmn_xml);
            this.state.lastSavedXml = this.state.currentXml;
        }
        this._refreshSelectionMetadata();
    }

    _applyVersionControl(versionControl) {
        if (!versionControl) {
            return;
        }
        this.state.activeVersionId = toPositiveInt(versionControl.active_version_id);
        this.state.rollbackCandidateId = toPositiveInt(versionControl.rollback_candidate_id);
        this.state.versions = (versionControl.versions || []).map((version) => ({
            ...version,
            id: toPositiveInt(version.id) || version.id,
        }));
        if (!this.state.activeVersionId) {
            const active = this.state.versions.find((version) => !!version.is_active);
            this.state.activeVersionId = active ? (toPositiveInt(active.id) || active.id) : null;
        }
        if (!this.state.rollbackCandidateId && this.state.activeVersionId) {
            const fallback = this.state.versions.find(
                (version) =>
                    (toPositiveInt(version.id) || version.id) !== this.state.activeVersionId
                    && !!(version.is_published || version.deployed_at)
            );
            this.state.rollbackCandidateId = fallback ? (toPositiveInt(fallback.id) || fallback.id) : null;
        }
    }

    _rpcErrorMessage(error, fallbackMessage) {
        return error?.data?.message || error?.message || fallbackMessage;
    }

    _confirmWithDialog({
                           title,
                           body,
                           confirmLabel = _t("Confirm"),
                           cancelLabel = _t("Cancel"),
                           confirmClass = "btn-primary",
                       }) {
        return new Promise((resolve) => {
            this.dialog.add(ConfirmationDialog, {
                title,
                body,
                confirmLabel,
                cancelLabel,
                confirmClass,
                confirm: () => resolve(true),
                cancel: () => resolve(false),
            });
        });
    }

    _assertEditableVersion() {
        if (!this.state.versionIsLocked) {
            return true;
        }
        this.notification.add(
            _t("This version is locked. Unlock or duplicate it before editing."),
            {type: "warning"}
        );
        return false;
    }

    _getEventDefinitionType(element) {
        return getEventDefinitionTypeFromBusinessObject(element?.businessObject);
    }

    _getEngineNodeType(element) {
        return getEngineNodeTypeFromBpmnType(
            element?.type || "",
            this._getEventDefinitionType(element)
        );
    }

    _isSupportedType(element) {
        if (!element) {
            return false;
        }
        if (element.type === "bpmn:SequenceFlow") {
            return true;
        }
        const nodeType = this._getEngineNodeType(element);
        return (
            SUPPORTED_ENGINE_TASK_NODE_TYPES.has(nodeType)
            || SUPPORTED_ENGINE_ACTION_NODE_TYPES.has(nodeType)
        );
    }

    _isActionElement(element) {
        if (!element) {
            return false;
        }
        if (element.type === "bpmn:SequenceFlow") {
            return true;
        }
        const nodeType = this._getEngineNodeType(element);
        return SUPPORTED_ENGINE_ACTION_NODE_TYPES.has(nodeType);
    }

    _isTaskElement(element) {
        if (!element) {
            return false;
        }
        const nodeType = this._getEngineNodeType(element);
        return SUPPORTED_ENGINE_TASK_NODE_TYPES.has(nodeType);
    }

    _isConditionalEventElement(element) {
        return this._getEngineNodeType(element) === "conditionalEventDefinition";
    }

    _countOutgoingSequenceFlows(element) {
        const outgoing = element?.businessObject?.outgoing || [];
        return outgoing.filter((flow) => getLocalName(flow) === "sequenceFlow").length;
    }

    _getConditionalEventOutgoingLimitViolations() {
        return getConditionalEventOutgoingLimitViolationsFromXml(this.state.currentXml || "");
    }

    _showConditionalEventOutgoingLimitWarning(elements = []) {
        const names = (elements || [])
            .map((element) => element?.name || elementDisplayName(element))
            .filter(Boolean)
            .slice(0, 3);
        const suffix = names.length ? ` ${names.join(", ")}` : "";
        this.notification.add(
            _t("Conditional Event supports only 2 outgoing flows. Use a Gateway for multiple branches.") + suffix,
            {type: "warning"}
        );
    }

    _getTransitionFromElement(element) {
        const bo = element?.businessObject;
        if (!bo) {
            return {
                sourceId: "",
                targetId: "",
                actionKey: "",
                legacySourceId: "",
                legacyTargetId: "",
                legacyActionKey: "",
                isAmbiguousActionNode: false,
            };
        }
        const asNode = (candidate) => candidate?.id || "";
        const toActionKey = (sourceId, targetId) => (sourceId && targetId ? `${sourceId}|${targetId}` : "");

        const normalizeSource = (sourceNode) => {
            if (!sourceNode) {
                return "";
            }
            const sourceNodeType = getEngineNodeTypeFromBpmnType(
                sourceNode.$type,
                getEventDefinitionTypeFromBusinessObject(sourceNode)
            );
            if (SUPPORTED_ENGINE_ACTION_NODE_TYPES.has(sourceNodeType)) {
                const incoming = sourceNode.incoming?.[0];
                return asNode(incoming?.sourceRef) || asNode(sourceNode);
            }
            return asNode(sourceNode);
        };

        const normalizeTarget = (targetNode) => {
            if (!targetNode) {
                return "";
            }
            const targetNodeType = getEngineNodeTypeFromBpmnType(
                targetNode.$type,
                getEventDefinitionTypeFromBusinessObject(targetNode)
            );
            if (SUPPORTED_ENGINE_ACTION_NODE_TYPES.has(targetNodeType)) {
                const outgoing = targetNode.outgoing?.[0];
                return asNode(outgoing?.targetRef) || asNode(targetNode);
            }
            return asNode(targetNode);
        };

        let directSourceId = "";
        let directTargetId = "";
        let normalizedSourceId = "";
        let normalizedTargetId = "";
        let legacySourceId = "";
        let legacyTargetId = "";
        let isAmbiguousActionNode = false;

        if (element.type === "bpmn:SequenceFlow") {
            directSourceId = asNode(bo.sourceRef);
            directTargetId = asNode(bo.targetRef);
            normalizedSourceId = normalizeSource(bo.sourceRef) || directSourceId;
            normalizedTargetId = normalizeTarget(bo.targetRef) || directTargetId;
            legacySourceId =
                normalizedSourceId && (normalizedSourceId !== directSourceId || normalizedTargetId !== directTargetId)
                    ? normalizedSourceId
                    : "";
            legacyTargetId =
                normalizedTargetId && (normalizedSourceId !== directSourceId || normalizedTargetId !== directTargetId)
                    ? normalizedTargetId
                    : "";
        } else if (this._isActionElement(element)) {
            // Node-first configuration for action nodes:
            // map action metadata to the incoming transition (source -> action-node).
            const incomingTransitions = bo.incoming || [];
            isAmbiguousActionNode = incomingTransitions.length > 1;
            if (isAmbiguousActionNode) {
                const actionNodeId = asNode(bo);
                return {
                    sourceId: "",
                    targetId: actionNodeId,
                    actionKey: "",
                    legacySourceId: "",
                    legacyTargetId: "",
                    legacyActionKey: "",
                    isAmbiguousActionNode,
                };
            }
            const incomingSource = bo.incoming?.[0]?.sourceRef;
            const outgoingTarget = bo.outgoing?.[0]?.targetRef;
            directSourceId = asNode(incomingSource);
            directTargetId = asNode(bo);
            normalizedSourceId = normalizeSource(incomingSource) || directSourceId;
            normalizedTargetId = directTargetId || asNode(outgoingTarget);
            // Keep the old mapping (source -> outgoing target) as legacy fallback.
            legacySourceId = normalizedSourceId || directSourceId;
            legacyTargetId = asNode(outgoingTarget) || normalizeTarget(outgoingTarget) || "";
        }

        const sourceId = directSourceId || normalizedSourceId;
        const targetId = directTargetId || normalizedTargetId;
        const actionKey = toActionKey(sourceId, targetId);
        const legacyActionKey = toActionKey(legacySourceId, legacyTargetId);

        return {
            sourceId,
            targetId,
            actionKey,
            legacySourceId,
            legacyTargetId,
            legacyActionKey,
            isAmbiguousActionNode,
        };
    }

    _computeSelectionInfo(element) {
        if (!element || element.id === "__implicitroot") {
            return null;
        }
        const type = element.type;
        const base = {
            id: element.id,
            name: elementDisplayName(element),
            type,
            nodeType: this._getEngineNodeType(element),
            supported: this._isSupportedType(element),
            kind: "unsupported",
            sourceId: "",
            targetId: "",
            actionKey: "",
            legacySourceId: "",
            legacyTargetId: "",
            legacyActionKey: "",
            isAmbiguousActionNode: false,
        };
        if (!base.supported) {
            return base;
        }
        if (this._isActionElement(element)) {
            const transition = this._getTransitionFromElement(element);
            return {
                ...base,
                kind: "action",
                sourceId: transition.sourceId,
                targetId: transition.targetId,
                actionKey: transition.actionKey,
                legacySourceId: transition.legacySourceId,
                legacyTargetId: transition.legacyTargetId,
                legacyActionKey: transition.legacyActionKey,
                isAmbiguousActionNode: transition.isAmbiguousActionNode,
            };
        }
        if (this._isTaskElement(element)) {
            return {
                ...base,
                kind: "task",
            };
        }
        return base;
    }

    _toFieldRow(metaField) {
        const fieldKey = metaField?.field_ref
            ? `${metaField.field_ref.model}::${metaField.field_ref.name}`
            : metaField?.field_key || "";
        const isPersistedSingleRule =
            !Array.isArray(metaField?.field_types)
            && !!metaField?.field_type
            && (metaField?.field_id || metaField?.field_ref || metaField?.id);
        const fieldTypes = this._normalizeMetaFieldTypes(metaField, {
            implyVisible: !isPersistedSingleRule,
        });
        const domainsByType = this._normalizeMetaFieldDomains(metaField, fieldTypes);
        return {
            key: metaField?.id || metaField?.key || `new_${Math.random().toString(36).slice(2)}`,
            field_key: fieldKey,
            field_type: fieldTypes[0] || "visible",
            field_types: fieldTypes,
            activity_action_keys: metaField?.activity_action_keys || [],
            domains_by_type: domainsByType,
        };
    }

    _normalizeMetaFieldTypes(row = {}, options = {}) {
        const implyVisible = options.implyVisible !== false;
        const rawTypes = Array.isArray(row.field_types)
            ? row.field_types
            : row.field_type
                ? [row.field_type]
                : ["visible"];
        const types = new Set(rawTypes.filter((type) => FIELD_TYPE_OPTIONS.includes(type)));
        if (implyVisible && (types.has("required") || types.has("readonly")) && !types.has("invisible")) {
            types.add("visible");
        }
        if (types.has("readonly")) {
            types.delete("required");
        }
        if (!types.size) {
            types.add("visible");
        }
        return FIELD_TYPE_PRIORITY.filter((type) => types.has(type));
    }

    _normalizeMetaFieldDomains(row = {}, fieldTypes = null) {
        const normalizedTypes = fieldTypes || this._normalizeMetaFieldTypes(row);
        const domainsByType = {};
        if (row.domains_by_type && typeof row.domains_by_type === "object") {
            for (const [fieldType, domain] of Object.entries(row.domains_by_type)) {
                if (FIELD_TYPE_OPTIONS.includes(fieldType)) {
                    domainsByType[fieldType] = `${domain || "[]"}`.trim() || "[]";
                }
            }
        }
        for (const [fieldType, fieldName] of Object.entries({
            visible: "visible_domain",
            required: "required_domain",
            readonly: "readonly_domain",
            invisible: "invisible_domain",
        })) {
            const domain = `${row[fieldName] || ""}`.trim();
            if (domain && domain !== "[]") {
                domainsByType[fieldType] = domainsByType[fieldType] || domain;
            }
        }
        const rowDomain = `${row.condition_domain || row.domain || ""}`.trim();
        if (rowDomain) {
            const sourceTypes = FIELD_TYPE_OPTIONS.includes(row.field_type)
                ? [row.field_type]
                : normalizedTypes;
            for (const fieldType of sourceTypes) {
                domainsByType[fieldType] = domainsByType[fieldType] || rowDomain;
            }
        }
        for (const fieldType of normalizedTypes) {
            domainsByType[fieldType] = domainsByType[fieldType] || "[]";
        }
        return domainsByType;
    }

    _metaFieldTypes(row = {}) {
        return this._normalizeMetaFieldTypes(row);
    }

    _metaFieldTypeLabel(type) {
        const labels = {
            visible: _t("visible"),
            required: _t("required"),
            readonly: _t("readonly"),
            invisible: _t("hidden"),
        };
        return labels[type] || type;
    }

    _metaFieldHasDomain(row = {}) {
        const domainsByType = this._normalizeMetaFieldDomains(row);
        return Object.values(domainsByType).some((domain) => {
            const value = `${domain || ""}`.trim();
            return value && value !== "[]";
        });
    }

    _cloneMetaFieldRow(row = {}) {
        return {
            ...row,
            field_types: [...(row.field_types || [])],
            activity_action_keys: [...(row.activity_action_keys || [])],
            domains_by_type: {...(row.domains_by_type || {})},
        };
    }

    _cloneMetaFieldRows(rows = []) {
        return (rows || []).map((row) => this._cloneMetaFieldRow(row));
    }

    _pendingMetaFieldRows(taskNodeId) {
        if (!taskNodeId) {
            return null;
        }
        const pendingRowsByNode = this.state.pendingMetaFieldRowsByNode || {};
        return Object.prototype.hasOwnProperty.call(pendingRowsByNode, taskNodeId)
            ? pendingRowsByNode[taskNodeId]
            : null;
    }

    _setPendingMetaFieldRows(taskNodeId, rows = []) {
        if (!taskNodeId) {
            return;
        }
        this.state.pendingMetaFieldRowsByNode = {
            ...(this.state.pendingMetaFieldRowsByNode || {}),
            [taskNodeId]: this._cloneMetaFieldRows(this._mergeMetaFieldRows(rows)),
        };
    }

    _clearPendingMetaFieldRows(taskNodeId) {
        if (!taskNodeId) {
            return;
        }
        const nextRowsByNode = {...(this.state.pendingMetaFieldRowsByNode || {})};
        delete nextRowsByNode[taskNodeId];
        this.state.pendingMetaFieldRowsByNode = nextRowsByNode;
    }

    _stageSelectedMetaFieldRows() {
        const taskNodeId = this.state.selectedTask?.node_id;
        if (taskNodeId) {
            this._setPendingMetaFieldRows(taskNodeId, this.state.metaFieldRows);
        }
    }

    _metaFieldRowsForTask(taskNodeId) {
        if (!taskNodeId) {
            return [];
        }
        const pendingRows = this._pendingMetaFieldRows(taskNodeId);
        if (pendingRows !== null) {
            return this._cloneMetaFieldRows(pendingRows);
        }
        return this._mergeMetaFieldRows(
            (this.state.payload?.meta?.fields || []).filter((field) => field.task_node_id === taskNodeId)
        );
    }

    _mergeMetaFieldRows(metaFields) {
        const rowsByField = new Map();
        for (const metaField of metaFields || []) {
            const row = this._toFieldRow(metaField);
            if (!row.field_key) {
                continue;
            }
            const existing = rowsByField.get(row.field_key);
            if (!existing) {
                rowsByField.set(row.field_key, row);
                continue;
            }
            existing.field_types = this._normalizeMetaFieldTypes({
                field_types: [...(existing.field_types || []), ...(row.field_types || [])],
            });
            existing.field_type = existing.field_types[0] || "visible";
            existing.activity_action_keys = [
                ...new Set([...(existing.activity_action_keys || []), ...(row.activity_action_keys || [])]),
            ];
            existing.domains_by_type = {
                ...(existing.domains_by_type || {}),
                ...(row.domains_by_type || {}),
            };
        }
        return [...rowsByField.values()];
    }

    _makeMetaFieldRow(fieldKey, fieldTypes, activityActionKeys = [], domainsByType = {}) {
        const normalizedTypes = this._normalizeMetaFieldTypes({field_types: fieldTypes});
        const normalizedDomains = {};
        for (const fieldType of normalizedTypes) {
            normalizedDomains[fieldType] = `${domainsByType?.[fieldType] || "[]"}`.trim() || "[]";
        }
        return {
            key: `new_${Math.random().toString(36).slice(2)}`,
            field_key: fieldKey,
            field_type: normalizedTypes[0] || "visible",
            field_types: normalizedTypes,
            activity_action_keys: [...(activityActionKeys || [])],
            domains_by_type: normalizedDomains,
            visible_domain: normalizedDomains.visible || "[]",
            required_domain: normalizedDomains.required || "[]",
            readonly_domain: normalizedDomains.readonly || "[]",
            invisible_domain: normalizedDomains.invisible || "[]",
        };
    }

    _upsertMetaFieldRow(row) {
        const existing = this.state.metaFieldRows.find((item) => item.field_key === row.field_key);
        if (!existing) {
            this.state.metaFieldRows.push(row);
            return;
        }
        existing.field_types = this._normalizeMetaFieldTypes({
            field_types: [...(existing.field_types || []), ...(row.field_types || [])],
        });
        existing.field_type = existing.field_types[0] || "visible";
        existing.activity_action_keys = [
            ...new Set([...(existing.activity_action_keys || []), ...(row.activity_action_keys || [])]),
        ];
        existing.domains_by_type = {
            ...(existing.domains_by_type || {}),
            ...(row.domains_by_type || {}),
        };
    }

    _refreshSelectionMetadata() {
        const payload = this.state.payload;
        if (!payload || !this.state.selectedElement) {
            this.state.selectedTask = null;
            this.state.selectedAction = null;
            this.state.metaFieldRows = [];
            this.state.approvalLinkRows = [];
            this.state.workflowMapRows = [];
            return;
        }
        const meta = payload.meta || {};
        if (this.state.selectedElement.kind === "task") {
            const selectedTask = (meta.tasks || []).find(
                (task) => task.node_id === this.state.selectedElement.id
            );
            this.state.selectedTask = selectedTask || null;
            this.state.selectedAction = null;
            const taskNode = selectedTask?.node_id;
            this.state.metaFieldRows = this._metaFieldRowsForTask(taskNode);
            this.state.approvalLinkRows = (meta.approval_group_links || []).filter(
                (link) => link.task_node_id === taskNode
            );
            this.state.workflowMapRows = (meta.workflow_maps || []).filter(
                (workflowMap) => workflowMap.task_node_id === taskNode
            );
            return;
        }

        if (this.state.selectedElement.kind === "action") {
            this.state.selectedTask = null;
            const isAmbiguousActionNode = !!this.state.selectedElement.isAmbiguousActionNode;
            const selectedAction = (meta.actions || []).find(
                (action) => action.action_key === this.state.selectedElement.actionKey
                    || (
                        this.state.selectedElement.legacyActionKey
                        && action.action_key === this.state.selectedElement.legacyActionKey
                    )
                    ||
                    (
                        action.source_id === this.state.selectedElement.sourceId
                        && action.target_id === this.state.selectedElement.targetId
                    )
                    || (
                        this.state.selectedElement.legacySourceId
                        && this.state.selectedElement.legacyTargetId
                        && action.source_id === this.state.selectedElement.legacySourceId
                        && action.target_id === this.state.selectedElement.legacyTargetId
                    )
                    || (!isAmbiguousActionNode && (
                        this.state.selectedElement.id
                        && action.target_id === this.state.selectedElement.id
                    ))
            );
            this.state.selectedAction = selectedAction || null;
            this.state.metaFieldRows = [];
            this.state.approvalLinkRows = [];
            this.state.workflowMapRows = [];
            return;
        }

        this.state.selectedTask = null;
        this.state.selectedAction = null;
        this.state.metaFieldRows = [];
        this.state.approvalLinkRows = [];
        this.state.workflowMapRows = [];
    }

    async _mountModeler(xml) {
        const BpmnModeler = this._bpmnModelerConstructor || this._resolveBpmnModelerConstructor();
        if (!BpmnModeler) {
            this.state.infoMessage = _t("BPMN modeler is not available.");
            throw new Error(this.state.infoMessage);
        }

        this.modeler?.destroy?.();
        this.modeler = new BpmnModeler({
            container: this.canvasRef.el,
        });
        if (!this.modeler?.get?.("modeling", false)) {
            this.modeler?.destroy?.();
            this.modeler = null;
            throw new Error(_t("Loaded BPMN library does not provide modeling services."));
        }

        const importedXml = await this._importXmlWithFallback(xml);
        if (importedXml && importedXml !== this.state.currentXml) {
            this.state.currentXml = importedXml;
            this.state.isDirty = importedXml !== this.state.lastSavedXml;
        }
        this.fitDiagram({retries: 8});
        setTimeout(() => this.fitDiagram({retries: 6}), 120);
        setTimeout(() => this._recoverDiagramFromBlankCanvas({retries: 4}), 220);
        this._patchContextPadDeprecation();
        this._applyPaletteRestrictions();
        this._applyContextPadRestrictions();
        this._hideNativePalette();

        this._commandChangedHandler = async () => {
            this.state.currentXml = await this._getCurrentXml();
            this.state.isDirty = this.state.currentXml !== this.state.lastSavedXml;
            this._applyPaletteRestrictions();
            this._applyContextPadRestrictions();
            if (this._isRevertingConditionalOutgoingLimit) {
                return;
            }
            const violations = this._getConditionalEventOutgoingLimitViolations();
            if (violations.length) {
                this._isRevertingConditionalOutgoingLimit = true;
                this._showConditionalEventOutgoingLimitWarning(violations);
                this._undoLastCommandSafely();
                setTimeout(() => {
                    this._isRevertingConditionalOutgoingLimit = false;
                }, 0);
            }
        };
        this.modeler.get("eventBus")?.on("commandStack.changed", this._commandChangedHandler);

        this._selectionChangedHandler = ({newSelection}) => {
            const element = newSelection?.[0] || null;
            this.state.selectedElement = this._computeSelectionInfo(element);
            if (this.state.selectedElement) {
                this.state.sidebarTab = "properties";
            }
            this._refreshSelectionMetadata();
            if (
                this.state.selectedElement?.kind === "action"
                && this.state.selectedElement.isAmbiguousActionNode
                && !this.state.selectedAction
            ) {
                this.notification.add(
                    _t("This action node has multiple incoming transitions. Select the specific arrow you want to configure."),
                    {type: "warning"}
                );
            }
            this._applyContextPadRestrictions();
            this._autoSyncMetadataForSelection();
        };
        this.modeler.get("eventBus")?.on("selection.changed", this._selectionChangedHandler);

        this._shapeCreateHandler = ({context}) => {
            const shape = context?.shape;
            if (!shape || AUXILIARY_SHAPE_TYPES.has(shape.type)) {
                return;
            }
            if (!this._isSupportedType(shape)) {
                this.notification.add(_t("This BPMN node is not supported by the workflow engine yet."), {
                    type: "warning",
                });
                this._undoLastCommandSafely();
            }
        };
        this.modeler
            .get("eventBus")
            ?.on("commandStack.shape.create.postExecuted", this._shapeCreateHandler);

        this._shapeReplaceHandler = ({context}) => {
            const newShape = context?.newShape;
            if (!newShape || AUXILIARY_SHAPE_TYPES.has(newShape.type)) {
                return;
            }
            if (!this._isSupportedType(newShape)) {
                this.notification.add(_t("Replacement node type is not supported yet."), {
                    type: "warning",
                });
                this._undoLastCommandSafely();
            }
        };
        this.modeler
            .get("eventBus")
            ?.on("commandStack.shape.replace.postExecuted", this._shapeReplaceHandler);

        // Connection limits are enforced from commandStack.changed using BPMN XML as source of truth.
    }

    async _importXmlWithFallback(xml) {
        const uniqueCandidates = [];
        const addCandidate = (candidate) => {
            const normalized = this._normalizeBpmnXml(candidate, {fallbackToDefault: false});
            if (normalized && !uniqueCandidates.includes(normalized)) {
                uniqueCandidates.push(normalized);
            }
        };
        addCandidate(xml);
        addCandidate(this.state.currentXml);
        addCandidate(this.state.payload?.version?.bpmn_xml);
        addCandidate(DEFAULT_BPMN_XML);

        let lastError = null;
        for (const candidate of uniqueCandidates) {
            try {
                await this.modeler.importXML(candidate);
                await new Promise((resolve) => requestAnimationFrame(() => resolve()));
                if (this._getDiagramBounds()) {
                    return candidate;
                }
                lastError = new Error(_t("BPMN XML imported but contains no visible nodes."));
            } catch (error) {
                lastError = error;
            }
        }
        throw lastError || new Error(_t("Unable to import BPMN XML."));
    }

    _undoLastCommandSafely() {
        if (this._isUndoScheduled) {
            return;
        }
        this._isUndoScheduled = true;
        setTimeout(() => {
            try {
                this.modeler?.get("commandStack")?.undo();
            } finally {
                this._isUndoScheduled = false;
            }
        }, 0);
    }

    _applyPaletteRestrictions() {
        setTimeout(() => {
            const paletteRoot = this.canvasRef.el?.querySelector(".djs-palette");
            if (!paletteRoot) {
                return;
            }
            for (const entry of paletteRoot.querySelectorAll(".entry[data-action]")) {
                const actionName = entry.getAttribute("data-action");
                entry.style.display = ALLOWED_PALETTE_ACTIONS.has(actionName) ? "" : "none";
            }
        }, 0);
    }

    _hideNativePalette() {
        setTimeout(() => {
            const paletteRoot = this.canvasRef.el?.querySelector(".djs-palette");
            if (paletteRoot) {
                paletteRoot.classList.add("o_workflow_studio_hidden_palette");
            }
        }, 0);
    }

    _patchContextPadDeprecation() {
        let contextPad = null;
        try {
            contextPad = this.modeler?.get?.("contextPad", false);
        } catch {
            contextPad = null;
        }
        if (!contextPad || contextPad.__workflowGetPadPatched || !contextPad._getPad) {
            return;
        }
        contextPad.getPad = (...args) => contextPad._getPad(...args);
        contextPad.__workflowGetPadPatched = true;
    }

    _applyContextPadRestrictions() {
        setTimeout(() => {
            const contextPad = this.canvasRef.el?.querySelector(".djs-context-pad");
            if (!contextPad) {
                return;
            }
            for (const entry of contextPad.querySelectorAll(".entry[data-action]")) {
                const actionName = entry.getAttribute("data-action");
                entry.style.display = BLOCKED_CONTEXT_PAD_ACTIONS.has(actionName) ? "none" : "";
            }
        }, 0);
    }

    async _getCurrentXml() {
        if (!this.modeler) {
            return this.state.currentXml || DEFAULT_BPMN_XML;
        }
        const {xml} = await this.modeler.saveXML({format: true});
        return mergeConditionalEventDefaultAttrs(xml, this.state.currentXml || "");
    }

    async _loadVersionById(versionId) {
        const [version] = await this.orm.read("workflow.approval.category.version", [versionId], [
            "title",
            "name",
            "bpmn_xml",
            "res_model_name",
            "is_locked",
            "is_active",
            "is_published",
        ]);
        if (!version) {
            throw new Error(_t("Workflow version not found."));
        }

        const xml = version.bpmn_xml || DEFAULT_BPMN_XML;
        this.state.versionId = versionId;
        this.state.versionTitle = version.title || version.name || _t("Active Version");
        this.state.resModelName = version.res_model_name || this.state.resModelName;
        this.state.versionIsLocked = !!version.is_locked;
        this.state.versionIsActive = !!version.is_active;
        this.state.versionIsPublished = !!version.is_published;
        this.state.versionLifecycleState = version.is_active
            ? (version.is_published ? "published" : "deployed")
            : (version.is_published ? "published" : "draft");
        this.state.versionLifecycleLabel = this.state.versionLifecycleState === "published"
            ? _t("Published")
            : this.state.versionLifecycleState === "deployed"
                ? _t("Deployed")
                : _t("Draft");
        this.state.currentXml = xml;
        this.state.lastSavedXml = xml;
        this.state.isDirty = false;
        this.state.selectedElement = null;
        this.state.selectedTask = null;
        this.state.selectedAction = null;
        this.state.metaFieldRows = [];
        this.state.pendingMetaFieldRowsByNode = {};
        this.state.approvalLinkRows = [];
        this.state.workflowMapRows = [];

        if (this.modeler) {
            const importedXml = await this._importXmlWithFallback(xml);
            this.state.currentXml = importedXml;
            this.state.isDirty = importedXml !== this.state.lastSavedXml;
            this.fitDiagram({retries: 8});
            setTimeout(() => this._recoverDiagramFromBlankCanvas({retries: 4}), 220);
            this._applyPaletteRestrictions();
            this._applyContextPadRestrictions();
            this._hideNativePalette();
        }
        await this._loadEditorPayload();
    }

    async _switchVersion(nextVersionId) {
        if (!nextVersionId || nextVersionId === this.state.versionId) {
            return;
        }
        const saved = await this._savePendingStudioChangesBeforeAction();
        if (!saved) {
            return;
        }
        try {
            await this._loadVersionById(nextVersionId);
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to switch workflow version.")),
                {type: "danger"}
            );
        }
    }

    async onVersionSelectionChange(ev) {
        const nextVersionId = Number(ev.target.value || 0);
        await this._switchVersion(nextVersionId);
    }

    toggleVersionMenu(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        this.state.versionMenuOpen = !this.state.versionMenuOpen;
    }

    async selectVersionFromMenu(versionId, ev) {
        if (ev) {
            ev.preventDefault();
            ev.stopPropagation();
        }
        this.state.versionMenuOpen = false;
        await this._switchVersion(Number(versionId || 0));
    }

    async createVersion() {
        this.dialog.add(WorkflowStudioNewVersionDialog, {
            versions: this.state.versions || [],
            currentVersionId: this.state.versionId || 0,
            confirm: (values) => this._createVersionFromDialog(values),
        });
    }

    async createInitialVersion() {
        if (!this.state.categoryId || this.state.isLoading) {
            return;
        }
        this.state.isLoading = true;
        try {
            const result = await this.orm.call(
                "workflow.approval.category",
                "workflow_studio_create_initial_version",
                [[this.state.categoryId]]
            );
            const versionId = toPositiveInt(result?.version_id);
            if (!versionId) {
                throw new Error(_t("The workflow version could not be created."));
            }

            this.state.infoMessage = "";
            this.state.canCreateInitialVersion = false;
            this.state.canEdit = !!this._bpmnModelerConstructor;
            await this._loadVersionById(versionId);
            this.state.isLoading = false;

            if (this.state.canEdit && !this.modeler) {
                // Let OWL render the editor DOM after isLoading=false
                await new Promise((r) => requestAnimationFrame(r));

                const ok = await this._waitForCanvasReady({retries: 60, delay: 50});
                if (!ok) {
                    throw new Error(_t("Canvas is not ready (still hidden or zero-sized)."));
                }

                await this._mountModeler(this.state.currentXml || DEFAULT_BPMN_XML);

                // avoid double add if user repeats create etc.
                window.removeEventListener("resize", this._onWindowResize);
                document.removeEventListener("click", this._onDocumentClick);
                window.addEventListener("resize", this._onWindowResize);
                document.addEventListener("click", this._onDocumentClick);

                this.fitDiagram({retries: 10});
                setTimeout(() => this.fitDiagram({retries: 10}), 180);
                setTimeout(() => this.fitDiagram({retries: 10}), 600);
                setTimeout(() => this.fitDiagram({retries: 10}), 1400);
            }
            this.notification.add(_t("First workflow version created."), {type: "success"});
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to create the first workflow version.")),
                {type: "danger"}
            );
        } finally {
            this.state.isLoading = false;
        }
    }

    async copyToVersion() {
        if (!this.copyTargetVersions.length) {
            this.notification.add(
                _t("No target version available. Create another version first."),
                {type: "warning"}
            );
            return;
        }
        this.dialog.add(WorkflowStudioCopyVersionDialog, {
            versions: this.copyTargetVersions,
            confirm: (values) => this._copyCurrentVersionToTarget(values?.target_version_id),
        });
    }

    async _createVersionFromDialog(values = {}) {
        try {
            const saved = await this._savePendingStudioChangesBeforeAction();
            if (!saved) {
                return false;
            }
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_create_version",
                [[this.state.versionId], values]
            );
            this._applyVersionControl(result?.version_control);
            if (result?.version_id) {
                await this._loadVersionById(result.version_id);
            }
            this.notification.add(_t("New workflow version created."), {type: "success"});
            return true;
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to create workflow version.")),
                {type: "danger"}
            );
            return false;
        }
    }

    async _copyCurrentVersionToTarget(targetVersionId) {
        if (!targetVersionId) {
            this.notification.add(_t("Please choose a target version."), {type: "warning"});
            return false;
        }
        try {
            const saved = await this._savePendingStudioChangesBeforeAction();
            if (!saved) {
                return false;
            }
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_copy_to_version",
                [[this.state.versionId], Number(targetVersionId)]
            );
            if (result?.payload) {
                this._setPayload(result.payload);
            }
            const nextVersionId = result?.version_id || Number(targetVersionId);
            if (nextVersionId && nextVersionId !== this.state.versionId) {
                await this._loadVersionById(nextVersionId);
            } else if (!result?.payload) {
                await this._loadEditorPayload();
            }
            if (result?.warnings?.length) {
                this.notification.add(result.warnings.join("\n"), {type: "warning"});
            }
            this.notification.add(
                _t("Version copied successfully. You are now editing the target version."),
                {type: "success"}
            );
            return true;
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to copy to target version.")),
                {type: "danger"}
            );
            return false;
        }
    }

    async duplicateVersion() {
        try {
            const saved = await this._savePendingStudioChangesBeforeAction();
            if (!saved) {
                return;
            }
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_duplicate_version",
                [[this.state.versionId]]
            );
            this._applyVersionControl(result?.version_control);
            if (result?.version_id) {
                await this._loadVersionById(result.version_id);
            }
            this.notification.add(_t("Workflow version duplicated."), {type: "success"});
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to duplicate workflow version.")),
                {type: "danger"}
            );
        }
    }

    async deployVersion() {
        try {
            const saved = await this._savePendingStudioChangesBeforeAction();
            if (!saved) {
                return;
            }
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_deploy_version",
                [[this.state.versionId]]
            );
            if (result?.payload) {
                this._setPayload(result.payload);
            } else {
                await this._loadEditorPayload();
            }
            this.notification.add(_t("Workflow version deployed."), {type: "success"});
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to deploy workflow version.")),
                {type: "danger"}
            );
        }
    }

    async publishVersion() {
        try {
            const saved = await this._savePendingStudioChangesBeforeAction();
            if (!saved) {
                return;
            }
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_publish_version",
                [[this.state.versionId]]
            );
            if (result?.payload) {
                this._setPayload(result.payload);
            } else {
                await this._loadEditorPayload();
            }
            this.notification.add(_t("Workflow version published."), {type: "success"});
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to publish workflow version.")),
                {type: "danger"}
            );
        }
    }

    async rollbackVersion() {
        const rollbackTarget = this.rollbackTargetOption;
        if (!rollbackTarget) {
            this.notification.add(
                _t("No rollback target is available. Deploy or publish another version first."),
                {type: "warning"}
            );
            return;
        }

        const fromLabel = this.currentVersionDisplayName || _t("Current version");
        const toLabel = rollbackTarget.display_name || rollbackTarget.name || _t("Selected version");
        const confirmMessage = this.state.versionIsActive
            ? `${_t("Rollback active version")} "${fromLabel}" ${_t("to")} "${toLabel}"?`
            : `${_t("Activate rollback target version")} "${toLabel}"?`;
        const confirmed = await this._confirmWithDialog({
            title: _t("Confirm Rollback"),
            body: confirmMessage,
            confirmLabel: _t("Rollback"),
            cancelLabel: _t("Cancel"),
            confirmClass: "btn-warning",
        });
        if (!confirmed) {
            return;
        }
        try {
            const saved = await this._savePendingStudioChangesBeforeAction();
            if (!saved) {
                return;
            }
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_rollback_version",
                [[this.state.versionId], rollbackTarget.id]
            );
            if (result?.payload) {
                this._setPayload(result.payload);
            }
            const nextVersionId = result?.version_id || this.state.activeVersionId;
            if (nextVersionId && nextVersionId !== this.state.versionId) {
                await this._loadVersionById(nextVersionId);
            } else if (!result?.payload) {
                await this._loadEditorPayload();
            }
            const toName = result?.rolled_back_to_display_name || toLabel;
            const fromName = result?.rolled_back_from_display_name || fromLabel;
            this.notification.add(
                `${_t("Workflow rollback completed")}: "${fromName}" -> "${toName}"`,
                {type: "success"}
            );
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to rollback workflow version.")),
                {type: "danger"}
            );
        }
    }

    async lockVersion() {
        try {
            const saved = await this._savePendingStudioChangesBeforeAction();
            if (!saved) {
                return;
            }
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_lock_version",
                [[this.state.versionId]]
            );
            if (result?.payload) {
                this._setPayload(result.payload);
            } else {
                await this._loadEditorPayload();
            }
            this.notification.add(_t("Workflow version locked."), {type: "success"});
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to lock workflow version.")),
                {type: "danger"}
            );
        }
    }

    async unlockVersion() {
        try {
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_unlock_version",
                [[this.state.versionId]]
            );
            if (result?.payload) {
                this._setPayload(result.payload);
            } else {
                await this._loadEditorPayload();
            }
            this.notification.add(_t("Workflow version unlocked."), {type: "success"});
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to unlock workflow version.")),
                {type: "danger"}
            );
        }
    }

    async deleteVersion() {
        const confirmed = await this._confirmWithDialog({
            title: _t("Delete Workflow Version"),
            body: _t("Delete this workflow version? This cannot be undone."),
            confirmLabel: _t("Delete"),
            cancelLabel: _t("Cancel"),
            confirmClass: "btn-danger",
        });
        if (!confirmed) {
            return;
        }
        try {
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_delete_version",
                [[this.state.versionId]]
            );
            this._applyVersionControl(result?.version_control);
            if (result?.version_id) {
                await this._loadVersionById(result.version_id);
            }
            this.notification.add(_t("Workflow version deleted."), {type: "success"});
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to delete workflow version.")),
                {type: "danger"}
            );
        }
    }

    setSidebarTab(tab) {
        this.state.sidebarTab = tab;
    }

    get addComponentItems() {
        return ADD_COMPONENT_ITEMS;
    }

    get currentVersionOption() {
        const currentId = toPositiveInt(this.state.versionId) || this.state.versionId;
        return (this.state.versions || []).find(
            (item) => (toPositiveInt(item.id) || item.id) === currentId
        ) || null;
    }

    get copyTargetVersions() {
        return (this.state.versions || []).filter((item) => item.id !== this.state.versionId);
    }

    get currentVersionDisplayName() {
        return this.currentVersionOption?.display_name || this.state.versionTitle || _t("Version");
    }

    get currentVersionLifecycleLabel() {
        return (
            this.currentVersionOption?.lifecycle_label
            || this.state.versionLifecycleLabel
            || _t("Draft")
        );
    }

    get currentVersionLifecycleClass() {
        return this._versionLifecycleClass(this.currentVersionOption);
    }

    _versionLifecycleClass(versionOption) {
        const lifecycleState = versionOption?.lifecycle_state || "";
        if (lifecycleState === "published") {
            return "is-published";
        }
        if (lifecycleState === "deployed") {
            return "is-deployed";
        }
        if (lifecycleState === "retired") {
            return "is-retired";
        }
        return "is-draft";
    }

    versionLifecycleClass(versionOption) {
        return this._versionLifecycleClass(versionOption);
    }

    get canDeployCurrentVersion() {
        return this.currentVersionOption ? !!this.currentVersionOption.can_deploy : !this.state.versionIsActive;
    }

    get canPublishCurrentVersion() {
        return this.currentVersionOption
            ? !!this.currentVersionOption.can_publish
            : !(this.state.versionIsPublished && this.state.versionIsActive);
    }

    get canRollbackCurrentVersion() {
        const target = this.rollbackTargetOption;
        if (!target) {
            return false;
        }
        return this.currentVersionOption
            ? !!this.currentVersionOption.can_rollback
            : !!(!this.state.versionIsActive || this.state.rollbackCandidateId);
    }

    get rollbackTargetOption() {
        if (this.state.versionIsActive) {
            const candidateId = toPositiveInt(this.state.rollbackCandidateId) || this.state.rollbackCandidateId;
            return (this.state.versions || []).find(
                (version) => (toPositiveInt(version.id) || version.id) === candidateId
            ) || null;
        }
        return this.currentVersionOption || null;
    }

    get fieldsOptions() {
        return this.state.payload?.options?.fields || [];
    }

    get actionOptions() {
        return this.state.payload?.options?.actions || [];
    }

    get templateOptions() {
        return this.state.payload?.options?.templates || [];
    }

    get usersOptions() {
        return this.state.payload?.options?.users || [];
    }

    get departmentOptions() {
        return this.state.payload?.options?.departments || [];
    }

    get workflowActionOptions() {
        return this.state.payload?.options?.workflow_actions || [];
    }

    get workflowActionTypeOptions() {
        return this.state.payload?.options?.workflow_action_types || [];
    }

    get serverActionOptions() {
        return this.state.payload?.options?.server_actions || [];
    }

    get domainPresetOptions() {
        return this.state.payload?.options?.domain_presets || {};
    }

    get workflowMapFieldMappingTemplates() {
        return this.state.payload?.options?.workflow_map_field_mapping_templates || [];
    }

    get approvalGroupOptions() {
        return this.state.payload?.options?.approval_groups || [];
    }

    get groupOptions() {
        return this.state.payload?.options?.groups || [];
    }

    get workflowTaskNodeOptions() {
        const tasks = this.state.payload?.meta?.tasks || [];
        return tasks
            .filter((task) => task?.node_id)
            .map((task) => ({
                value: task.node_id,
                label: `${task.name || task.node_id} (${task.node_id})`,
            }));
    }

    getWorkflowTaskNodeAutocompleteProps(fieldName) {
        const value = this.state.selectedTask?.[fieldName] || "";
        const selected = this.workflowTaskNodeOptions.find((node) => node.value === value);
        return {
            value: selected ? selected.label : value,
            class: "o_wfs_meta_field_autocomplete",
            placeholder: _t("Search workflow node..."),
            searchOnInputClick: true,
            resetOnSelect: false,
            sources: [
                {
                    options: (searchTerm) => {
                        const term = (searchTerm || "").trim().toLowerCase();
                        return this.workflowTaskNodeOptions
                            .filter((node) => {
                                const haystack = `${node.label || ""} ${node.value || ""}`.toLowerCase();
                                return !term || haystack.includes(term);
                            })
                            .map((node) => ({
                                label: node.label,
                                onSelect: () => this.onTaskFieldChange(fieldName, node.value),
                            }));
                    },
                },
            ],
            onChange: ({inputValue, isOptionSelected}) => {
                if (!isOptionSelected && !(inputValue || "").trim()) {
                    this.onTaskFieldChange(fieldName, false);
                }
            },
        };
    }

    get nodeUserTypeOptions() {
        return this.state.payload?.options?.node_user_types || [
            {value: "assigned", label: _t("Assigned Users")},
            {value: "pending", label: _t("Pending Users")},
            {value: "decided", label: _t("Decided Users")},
        ];
    }

    get notificationRecipientSourceOptions() {
        return this.state.payload?.options?.notification_recipient_sources || [
            {value: "specific_users", label: _t("Specific Users")},
            {value: "approval_group_users", label: _t("Workflow Approval Group Users")},
            {value: "group_users", label: _t("Odoo Group Users")},
            {value: "node_users", label: _t("Users From Workflow Node")},
            {value: "domain", label: _t("Domain Over Users")},
        ];
    }

    get notificationDeliveryModeOptions() {
        return this.state.payload?.options?.notification_delivery_modes || [
            {value: "email", label: _t("Send Email")},
            {value: "log", label: _t("Log Activity")},
            {value: "channels", label: _t("Channels")},
        ];
    }

    get emailRecipientHeaderOptions() {
        return this.state.payload?.options?.email_recipient_headers || [
            {value: "to", label: _t("To")},
            {value: "cc", label: _t("CC")},
            {value: "bcc", label: _t("BCC")},
        ];
    }

    get emailRecipientSourceOptions() {
        return this.state.payload?.options?.email_recipient_sources || [
            {value: "direct", label: _t("Raw Emails")},
            {value: "send_task", label: _t("Send Task Recipients")},
            {value: "specific_users", label: _t("Specific Users")},
            {value: "approval_group_users", label: _t("Workflow Approval Group Users")},
            {value: "group_users", label: _t("Odoo Group Users")},
            {value: "node_users", label: _t("Users From Workflow Node")},
            {value: "domain", label: _t("Domain Over Users")},
        ];
    }

    _normalizePropertyLabelKey(labelText) {
        return String(labelText || "")
            .toLowerCase()
            .replace(/\s+/g, " ")
            .trim();
    }

    _extractPropertyLabelText(labelEl) {
        if (!labelEl) {
            return "";
        }
        const clone = labelEl.cloneNode(true);
        clone.querySelectorAll("button, .o_web_studio_help_icon, i").forEach((node) => node.remove());
        return String(clone.textContent || "")
            .replace(/\s+/g, " ")
            .trim();
    }

    getPropertyLabelHelp(labelText) {
        const key = this._normalizePropertyLabelKey(labelText);
        if (!key) {
            return "";
        }
        return (
            PROPERTY_LABEL_HELP[key]
            || _t("Configure this property for the selected workflow element.")
        );
    }

    _applyPropertyLabelHelp() {
        if (this.state.sidebarTab !== "properties") {
            return;
        }
        const root = this.el?.querySelector(".o_web_studio_bpmn_sidebar_content");
        if (!root) {
            return;
        }
        const labels = root.querySelectorAll("label");
        for (const labelEl of labels) {
            if (labelEl.querySelector(".o_web_studio_help_icon:not(.o_web_studio_help_icon_inline_auto)")) {
                continue;
            }
            const labelText = this._extractPropertyLabelText(labelEl);
            const helpText = this.getPropertyLabelHelp(labelText);
            if (!helpText) {
                continue;
            }
            labelEl.classList.add("o_web_studio_label_has_help");
            labelEl.setAttribute("title", helpText);

            let helpIcon = labelEl.querySelector(".o_web_studio_help_icon_inline_auto");
            if (!helpIcon) {
                helpIcon = document.createElement("span");
                helpIcon.className = "o_web_studio_help_icon o_web_studio_help_icon_inline_auto";
                helpIcon.setAttribute("aria-hidden", "true");
                helpIcon.innerHTML = '<i class="fa fa-info-circle" aria-hidden="true"></i>';
                const inlineHost = labelEl.querySelector(":scope > span");
                (inlineHost || labelEl).appendChild(helpIcon);
            }
            helpIcon.setAttribute("title", helpText);
        }
    }

    _scheduleApplyPropertyLabelHelp() {
        if (this._propertyHelpRafId) {
            cancelAnimationFrame(this._propertyHelpRafId);
        }
        this._propertyHelpRafId = requestAnimationFrame(() => {
            this._propertyHelpRafId = null;
            this._applyPropertyLabelHelp();
        });
    }

    getApprovalGroupPropertyHelp(key) {
        return APPROVAL_GROUP_PROPERTY_HELP[key] || "";
    }

    get currentNodeLinkedApprovalGroupIds() {
        const linkedIds = new Set();
        for (const row of this.state.approvalLinkRows || []) {
            const groupId = Number(row?.approval_group_ref?.id || row?.approval_group_id || 0);
            if (groupId) {
                linkedIds.add(groupId);
            }
        }
        return linkedIds;
    }

    get linkedApprovalGroupCount() {
        return this.currentNodeLinkedApprovalGroupIds.size;
    }

    get availableApprovalGroupCount() {
        return Math.max(this.approvalGroupOptions.length - this.linkedApprovalGroupCount, 0);
    }

    get approvalGroupSidebarSummaryText() {
        if (this.linkedApprovalGroupCount) {
            return sprintf(_t("%(linked)s linked of %(total)s approval groups for this node."), {
                linked: this.linkedApprovalGroupCount,
                total: this.approvalGroupOptions.length,
            });
        }
        return _t("No approval groups linked yet. Open the browser to find, review, or create the right group.");
    }

    get configuredNotificationChannelCount() {
        return new Set(
            (this.state.selectedTask?.activity_type_ids || [])
                .map((channelId) => Number(channelId || 0))
                .filter(Boolean)
        ).size;
    }

    get notificationChannelCatalogCount() {
        return this.configuredNotificationChannelCount + this.allAvailableChannelOptions.length;
    }

    get notificationChannelSidebarSummaryText() {
        if (this.configuredNotificationChannelCount) {
            return sprintf(_t("%(configured)s of %(total)s channels are configured for this node."), {
                configured: this.configuredNotificationChannelCount,
                total: this.notificationChannelCatalogCount,
            });
        }
        return _t("No channels configured yet. Open the channel manager to find, review, or create one.");
    }

    get approvalGroupBrowserNodeLabel() {
        const task = this.state.selectedTask || {};
        const taskName = `${task.name || ""}`.trim();
        const nodeId = `${task.node_id || ""}`.trim();
        if (taskName && nodeId && taskName !== nodeId) {
            return `${taskName} (${nodeId})`;
        }
        return taskName || nodeId || _t("Selected node");
    }

    get unlinkedApprovalGroupOptions() {
        return (this.approvalGroupOptions || []).filter(
            (g) => !this.currentNodeLinkedApprovalGroupIds.has(Number(g.id || 0))
        );
    }

    async onAddApprovalGroupFromSelect(ev) {
        const groupId = Number(ev.target.value || 0);
        ev.target.value = "";
        if (!groupId) {
            return;
        }
        await this.linkApprovalGroupFromCatalog(groupId);
    }

    isApprovalGroupLinkedInCurrentNode(groupOption) {
        const groupId = Number(groupOption?.id || 0);
        return Boolean(groupId && this.currentNodeLinkedApprovalGroupIds.has(groupId));
    }

    getApprovalGroupLinkedRuleCount(groupOption) {
        const targetGroupId = Number(groupOption?.id || 0);
        if (!targetGroupId) {
            return 0;
        }
        return (this.state.approvalLinkRows || []).reduce((count, row) => {
            const rowGroupId = Number(row?.approval_group_ref?.id || row?.approval_group_id || 0);
            return rowGroupId === targetGroupId ? count + 1 : count;
        }, 0);
    }

    getApprovalLinkRowsByGroupId(groupId) {
        const normalizedGroupId = Number(groupId || 0);
        if (!normalizedGroupId) {
            return [];
        }
        return (this.state.approvalLinkRows || []).filter((row) => {
            const rowGroupId = Number(row?.approval_group_ref?.id || row?.approval_group_id || 0);
            return rowGroupId === normalizedGroupId;
        });
    }

    classifyApprovalRoutingAuditState(domainLiteral) {
        const normalized = `${domainLiteral || ""}`.trim();
        if (!normalized) {
            return "ignored_blank";
        }
        if (normalized.replace(/\s+/g, "") === "[]") {
            return "ignored_empty";
        }
        return "active_valid";
    }

    getApprovalRoutingAuditMessage(domainState) {
        if (domainState === "ignored_blank") {
            return _t(
                "Blank routing domains are ignored. Use [(1, '=', 1)] for always true or [(0, '=', 1)] for always false."
            );
        }
        if (domainState === "ignored_empty") {
            return _t(
                "Empty [] routing domains are ignored. Use [(1, '=', 1)] for always true or [(0, '=', 1)] for always false."
            );
        }
        return "";
    }

    getApprovalGroupRoutingWarnings(groupOption) {
        const linkedRows = this.getApprovalLinkRowsByGroupId(groupOption?.id);
        if (!linkedRows.length) {
            return [];
        }
        const fieldSpecs = [
            {
                fieldName: "user_domain",
                blankLabel: _t("User Filter Blank"),
                emptyLabel: _t("User Filter []"),
            },
            {
                fieldName: "domain",
                blankLabel: _t("Record Domain Blank"),
                emptyLabel: _t("Record Domain []"),
            },
        ];
        const warnings = [];
        for (const fieldSpec of fieldSpecs) {
            for (const domainState of ["ignored_blank", "ignored_empty"]) {
                const affectedCount = linkedRows.filter(
                    (row) => this.classifyApprovalRoutingAuditState(row?.[fieldSpec.fieldName]) === domainState
                ).length;
                if (!affectedCount) {
                    continue;
                }
                const baseMessage = this.getApprovalRoutingAuditMessage(domainState);
                warnings.push({
                    key: `${fieldSpec.fieldName}:${domainState}`,
                    label: domainState === "ignored_blank" ? fieldSpec.blankLabel : fieldSpec.emptyLabel,
                    title:
                        affectedCount > 1
                            ? sprintf(_t("%(count)s linked rules on this node use this value. %(message)s"), {
                                count: affectedCount,
                                message: baseMessage,
                            })
                            : baseMessage,
                });
            }
        }
        return warnings;
    }

    groupMatchesApprovalRoutingFilter(groupRow, routingFilter = "all") {
        const normalizedFilter = `${routingFilter || "all"}`.trim() || "all";
        if (normalizedFilter === "all") {
            return true;
        }
        const warnings = Array.isArray(groupRow?.routingWarnings) ? groupRow.routingWarnings : [];
        if (normalizedFilter === "needs_config") {
            return warnings.length > 0;
        }
        return warnings.some((warning) => warning?.key === normalizedFilter);
    }

    isApprovalGroupLinkedInOtherRow(rowIndex, groupOption) {
        const targetGroupId = Number(groupOption?.id || 0);
        if (!targetGroupId) {
            return false;
        }
        return (this.state.approvalLinkRows || []).some((row, index) => {
            if (index === rowIndex) {
                return false;
            }
            const rowGroupId = Number(row?.approval_group_ref?.id || row?.approval_group_id || 0);
            return rowGroupId === targetGroupId;
        });
    }

    get approvalGroupCatalogRows() {
        return Array.isArray(this.state.approvalGroupCatalogRows)
            ? this.state.approvalGroupCatalogRows
            : [];
    }

    buildApprovalGroupCatalogRowsFromOptions(groupOptions = []) {
        return (groupOptions || [])
            .map((groupOption) => {
                const linkedCount = this.getApprovalGroupLinkedRuleCount(groupOption);
                const userNames = this.getApprovalGroupUserNames(groupOption);
                return {
                    ...groupOption,
                    key: groupOption.id,
                    displayPath: this.getApprovalGroupOptionDisplayPath(groupOption),
                    linkedCount,
                    linkedRowIndex: this.findApprovalLinkRowIndexByGroupId(groupOption.id),
                    isLinked: linkedCount > 0,
                    membersSummary: this.getApprovalGroupMemberSummary(groupOption),
                    memberPreview: this.getApprovalGroupMemberSummary(groupOption, 3),
                    routingWarnings: this.getApprovalGroupRoutingWarnings(groupOption),
                    userCount: userNames.length,
                };
            })
            .sort((left, right) => {
                if (left.isLinked !== right.isLinked) {
                    return left.isLinked ? -1 : 1;
                }
                return String(left.displayPath || left.name || "").localeCompare(
                    String(right.displayPath || right.name || "")
                );
            });
    }

    _normalizeApprovalGroupSearch(rawQuery) {
        return (rawQuery || "").trim().toLowerCase();
    }

    filterApprovalGroupCatalogRows(
        rows = [],
        {
            query = this.state.approvalGroupCatalogQuery,
            mode = this.state.approvalGroupCatalogMode,
            routingFilter = this.state.approvalGroupCatalogRoutingFilter,
        } = {}
    ) {
        const normalizedQuery = this._normalizeApprovalGroupSearch(query);
        let filteredRows = [...(rows || [])];
        if (mode === "linked") {
            filteredRows = filteredRows.filter((group) => group.isLinked);
        } else if (mode === "available") {
            filteredRows = filteredRows.filter((group) => !group.isLinked);
        }
        filteredRows = filteredRows.filter((group) => this.groupMatchesApprovalRoutingFilter(group, routingFilter));
        if (!normalizedQuery) {
            return filteredRows;
        }
        return filteredRows.filter((group) => {
            const haystack = [
                group?.displayPath || "",
                group?.name || "",
                group?.department_name || "",
                ...this.getApprovalGroupUserNames(group),
                ...(Array.isArray(group?.routingWarnings)
                    ? group.routingWarnings.flatMap((warning) => [warning?.label || "", warning?.title || ""])
                    : []),
            ]
                .join(" ")
                .toLowerCase();
            return haystack.includes(normalizedQuery);
        });
    }

    _normalizeApprovalGroupCatalogServerRow(groupRow = {}) {
        const userNames = this.getApprovalGroupUserNames(groupRow);
        return {
            ...groupRow,
            key: groupRow.key || groupRow.id,
            displayPath: groupRow.displayPath || groupRow.display_path || groupRow.name || "",
            linkedCount: Number(groupRow.linkedCount ?? groupRow.linked_count ?? 0) || 0,
            isLinked:
                "isLinked" in groupRow
                    ? Boolean(groupRow.isLinked)
                    : Boolean(groupRow.is_linked),
            membersSummary:
                groupRow.membersSummary
                || groupRow.members_summary
                || this.getApprovalGroupMemberSummary({user_names: userNames}),
            memberPreview:
                groupRow.memberPreview
                || groupRow.member_preview
                || this.getApprovalGroupMemberSummary({user_names: userNames}, 3),
            routingWarnings: Array.isArray(groupRow.routingWarnings)
                ? groupRow.routingWarnings
                : (Array.isArray(groupRow.routing_warnings) ? groupRow.routing_warnings : []),
            userCount: Number(groupRow.userCount ?? groupRow.user_count ?? userNames.length) || userNames.length,
            user_names: userNames,
        };
    }

    _applyApprovalGroupCatalogBrowserResult(result = {}, {append = false} = {}) {
        const normalizedRows = Array.isArray(result?.rows)
            ? result.rows.map((row) => this._normalizeApprovalGroupCatalogServerRow(row))
            : [];
        if (!append) {
            this.state.approvalGroupCatalogRows = normalizedRows;
        } else {
            const existingIds = new Set(
                (this.state.approvalGroupCatalogRows || []).map((row) => Number(row?.id || 0)).filter(Boolean)
            );
            const appendedRows = normalizedRows.filter((row) => !existingIds.has(Number(row?.id || 0)));
            this.state.approvalGroupCatalogRows = [
                ...(this.state.approvalGroupCatalogRows || []),
                ...appendedRows,
            ];
        }
        const total = Number(result?.total);
        this.state.approvalGroupCatalogTotal = Number.isFinite(total)
            ? total
            : (this.state.approvalGroupCatalogRows || []).length;
        const totalGroups = Number(result?.total_groups);
        this.state.approvalGroupCatalogTotalGroups = Number.isFinite(totalGroups)
            ? totalGroups
            : this.approvalGroupOptions.length;
        const linkedCount = Number(result?.linked_count);
        this.state.approvalGroupCatalogLinkedCount = Number.isFinite(linkedCount)
            ? linkedCount
            : this.linkedApprovalGroupCount;
        this.state.approvalGroupCatalogHasMore = Boolean(result?.has_more)
            || this.state.approvalGroupCatalogRows.length < this.state.approvalGroupCatalogTotal;
    }

    _buildLocalApprovalGroupCatalogBrowserResult({append = false} = {}) {
        const offset = append ? this.approvalGroupCatalogRows.length : 0;
        const filteredRows = this.filterApprovalGroupCatalogRows(
            this.buildApprovalGroupCatalogRowsFromOptions(this.approvalGroupOptions)
        );
        const rows = filteredRows.slice(offset, offset + APPROVAL_GROUP_CATALOG_PAGE_SIZE);
        return {
            rows,
            total: filteredRows.length,
            offset,
            limit: APPROVAL_GROUP_CATALOG_PAGE_SIZE,
            has_more: offset + rows.length < filteredRows.length,
            linked_count: this.linkedApprovalGroupCount,
            total_groups: this.approvalGroupOptions.length,
        };
    }

    _getApprovalGroupCatalogBrowserLinkRowsPayload() {
        return (this.state.approvalLinkRows || []).map((row) => ({
            approval_group_id: Number(row?.approval_group_ref?.id || row?.approval_group_id || 0) || 0,
            user_domain: row?.user_domain || "",
            domain: row?.domain || "",
        }));
    }

    _clearApprovalGroupCatalogScheduledReload() {
        if (this._approvalGroupCatalogSearchTimer) {
            clearTimeout(this._approvalGroupCatalogSearchTimer);
            this._approvalGroupCatalogSearchTimer = null;
        }
        if (this._approvalGroupCatalogScheduledResolver) {
            this._approvalGroupCatalogScheduledResolver(false);
            this._approvalGroupCatalogScheduledResolver = null;
        }
    }

    async _fetchApprovalGroupCatalogBrowserRows({append = false} = {}) {
        const requestSequence = ++this._approvalGroupCatalogSearchSequence;
        const offset = append ? this.approvalGroupCatalogRows.length : 0;
        this.state.approvalGroupCatalogPending = true;
        try {
            if (!this.state.versionId) {
                const fallbackResult = this._buildLocalApprovalGroupCatalogBrowserResult({append});
                if (requestSequence === this._approvalGroupCatalogSearchSequence) {
                    this._applyApprovalGroupCatalogBrowserResult(fallbackResult, {append});
                }
                return fallbackResult;
            }
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_browse_approval_groups",
                [[this.state.versionId], {
                    query: this.state.approvalGroupCatalogQuery || "",
                    mode: this.state.approvalGroupCatalogMode || "all",
                    routing_filter: this.state.approvalGroupCatalogRoutingFilter || "all",
                    offset,
                    limit: APPROVAL_GROUP_CATALOG_PAGE_SIZE,
                    approval_link_rows: this._getApprovalGroupCatalogBrowserLinkRowsPayload(),
                }]
            );
            if (requestSequence !== this._approvalGroupCatalogSearchSequence) {
                return false;
            }
            this._applyApprovalGroupCatalogBrowserResult(result, {append});
            return result;
        } catch {
            if (requestSequence !== this._approvalGroupCatalogSearchSequence) {
                return false;
            }
            const fallbackResult = this._buildLocalApprovalGroupCatalogBrowserResult({append});
            this._applyApprovalGroupCatalogBrowserResult(fallbackResult, {append});
            return fallbackResult;
        } finally {
            if (requestSequence === this._approvalGroupCatalogSearchSequence) {
                this.state.approvalGroupCatalogPending = false;
            }
        }
    }

    get hasMoreApprovalGroupCatalogRows() {
        return Boolean(this.state.approvalGroupCatalogHasMore);
    }

    getApprovalGroupById(groupId) {
        const normalizedGroupId = Number(groupId || 0);
        if (!normalizedGroupId) {
            return null;
        }
        return this.approvalGroupOptions.find((option) => Number(option.id || 0) === normalizedGroupId) || null;
    }

    getApprovalGroupOptionByRow(row) {
        const groupId = Number(row?.approval_group_ref?.id || row?.approval_group_id || 0);
        return this.getApprovalGroupById(groupId);
    }

    getApprovalGroupOptionDisplayPath(groupOption) {
        if (!groupOption) {
            return "";
        }
        return groupOption.display_path || groupOption.name || "";
    }

    findApprovalLinkRowIndexByGroupId(groupId) {
        const normalizedGroupId = Number(groupId || 0);
        if (!normalizedGroupId) {
            return -1;
        }
        return (this.state.approvalLinkRows || []).findIndex((row) => {
            const rowGroupId = Number(row?.approval_group_ref?.id || row?.approval_group_id || 0);
            return rowGroupId === normalizedGroupId;
        });
    }

    toPositiveIntOrFalse(rawValue) {
        const parsed = Number(rawValue || 0);
        return Number.isFinite(parsed) && parsed > 0 ? parsed : false;
    }

    getDomainPresets(presetKey, fallbackKey = "generic") {
        const presetMap = this.domainPresetOptions || {};
        const primary = Array.isArray(presetMap[presetKey]) ? presetMap[presetKey] : [];
        if (primary.length) {
            return primary;
        }
        return Array.isArray(presetMap[fallbackKey]) ? presetMap[fallbackKey] : [];
    }

    getRequestModelFieldHints(max = 20) {
        const requestModel = (this.state.resModelName || "").trim();
        if (!requestModel) {
            return [];
        }
        return (this.fieldsOptions || [])
            .filter((fieldOption) => (fieldOption?.model || "") === requestModel)
            .slice(0, max)
            .map((fieldOption) => ({
                name: fieldOption.name,
                field_description: fieldOption.field_description,
                ttype: fieldOption.ttype,
                relation: fieldOption.relation || "",
            }));
    }

    isApprovalGroupSelected(row, groupOption) {
        const selectedGroupId = Number(row?.approval_group_ref?.id || row?.approval_group_id || 0);
        const optionGroupId = Number(groupOption?.id || 0);
        return Boolean(selectedGroupId && optionGroupId && selectedGroupId === optionGroupId);
    }

    canConfigureApprovalGroup(row) {
        const groupId = Number(row?.approval_group_ref?.id || row?.approval_group_id || 0);
        return Boolean(groupId);
    }

    get actionButtonCssPresetOptions() {
        return [
            {value: "", label: _t("Default")},
            {value: "btn btn-primary", label: _t("Primary")},
            {value: "btn btn-secondary", label: _t("Secondary")},
            {value: "btn btn-success", label: _t("Success")},
            {value: "btn btn-info", label: _t("Info")},
            {value: "btn btn-warning", label: _t("Warning")},
            {value: "btn btn-danger", label: _t("Danger")},
            {value: "btn btn-outline-primary", label: _t("Outline Primary")},
            {value: "btn btn-outline-secondary", label: _t("Outline Secondary")},
            {value: "btn btn-outline-success", label: _t("Outline Success")},
            {value: "btn btn-outline-danger", label: _t("Outline Danger")},
            {value: "text-primary fw-bold", label: _t("Text Primary Bold")},
            {value: "text-success fw-bold", label: _t("Text Success Bold")},
            {value: "__custom__", label: _t("Custom")},
        ];
    }

    get actionButtonIconPresetOptions() {
        return [
            {value: "", label: _t("Default (gavel)")},
            {value: "fa-paper-plane", label: _t("Paper Plane")},
            {value: "fa-check", label: _t("Check")},
            {value: "fa-check-circle", label: _t("Check Circle")},
            {value: "fa-times", label: _t("Times")},
            {value: "fa-times-circle", label: _t("Times Circle")},
            {value: "fa-reply", label: _t("Reply")},
            {value: "fa-undo", label: _t("Undo")},
            {value: "fa-refresh", label: _t("Refresh")},
            {value: "fa-arrow-right", label: _t("Arrow Right")},
            {value: "fa-arrow-left", label: _t("Arrow Left")},
            {value: "fa-exclamation-triangle", label: _t("Warning")},
            {value: "fa-ban", label: _t("Ban")},
            {value: "__custom__", label: _t("Custom")},
        ];
    }

    _normalizeActionIconPresetValue(rawValue) {
        const value = (rawValue || "").trim();
        if (!value) {
            return "";
        }
        if (value.includes(" ")) {
            return value;
        }
        if (value.startsWith("fa-")) {
            return value;
        }
        if (value === "fa") {
            return "";
        }
        return value;
    }

    getSelectedActionCssPreset() {
        const currentValue = (this.state.selectedAction?.attr_class || "").trim();
        const knownValues = new Set(
            this.actionButtonCssPresetOptions.map((option) => option.value).filter((value) => value !== "__custom__")
        );
        return knownValues.has(currentValue) ? currentValue : "__custom__";
    }

    getSelectedActionIconPreset() {
        const currentValue = this._normalizeActionIconPresetValue(this.state.selectedAction?.icon_class || "");
        const knownValues = new Set(
            this.actionButtonIconPresetOptions.map((option) => option.value).filter((value) => value !== "__custom__")
        );
        return knownValues.has(currentValue) ? currentValue : "__custom__";
    }

    async onActionCssPresetSelectChange(event) {
        const presetValue = event?.target?.value;
        if (presetValue === "__custom__") {
            if (this.getSelectedActionCssPreset() !== "__custom__") {
                await this.onActionFieldChange("attr_class", "");
            }
            return;
        }
        await this.onActionFieldChange("attr_class", presetValue || false);
    }

    async onActionIconPresetSelectChange(event) {
        const presetValue = event?.target?.value;
        if (presetValue === "__custom__") {
            if (this.getSelectedActionIconPreset() !== "__custom__") {
                await this.onActionFieldChange("icon_class", "");
            }
            return;
        }
        await this.onActionFieldChange("icon_class", presetValue || false);
    }

    getApprovalGroupDisplayName(row) {
        const group = this.getApprovalGroupOptionByRow(row);
        if (group) {
            return this.getApprovalGroupOptionDisplayPath(group) || group.name;
        }
        if (row?.approval_group_ref?.name) {
            return row.approval_group_ref.name;
        }
        const groupId = Number(row?.approval_group_ref?.id || row?.approval_group_id || 0);
        if (groupId) {
            return _t("Unknown group");
        }
        return _t("Not selected");
    }

    get configuredApprovalGroupRows() {
        return (this.state.approvalLinkRows || []).map((row, index) => {
            const group = this.getApprovalGroupOptionByRow(row);
            const groupId = Number(row?.approval_group_ref?.id || row?.approval_group_id || 0);
            return {
                key: row?.id || `${index}_${groupId || "new"}`,
                index: index + 1,
                rowIndex: index,
                groupName: this.getApprovalGroupDisplayName(row),
                groupId: groupId || false,
                isMissingGroup: Boolean(groupId && !group),
                sequence: Number(row?.sequence || 10),
                departmentName: group?.department_name || "",
                membersSummary: this.getApprovalGroupMemberSummary(group),
                linkedRuleCount: this.getApprovalGroupLinkedRuleCount(group),
                userDomain: row?.user_domain || "",
                recordDomain: row?.domain || "",
                note: row?.note || "",
            };
        });
    }

    getApprovalGroupMemberSummary(groupOption, maxUsers = false) {
        if (!groupOption) {
            return "";
        }
        const users = this.getApprovalGroupUserNames(groupOption);
        if (!users.length) {
            return _t("No users assigned");
        }
        if (!Number.isInteger(maxUsers) || maxUsers <= 0 || users.length <= maxUsers) {
            return users.join(", ");
        }
        const preview = users.slice(0, maxUsers).join(", ");
        return `${preview} ${sprintf(_t("+%(count)s more"), {
            count: users.length - maxUsers,
        })}`;
    }

    getApprovalGroupUserNames(groupOption) {
        const rawUsers = Array.isArray(groupOption?.user_names) ? groupOption.user_names : [];
        return rawUsers
            .map((userName) => `${userName || ""}`.trim())
            .filter((userName) => userName && userName.toLowerCase() !== "nan");
    }

    get calledWorkflowOptions() {
        return this.state.payload?.options?.called_workflows || [];
    }

    get selectedTaskNodeType() {
        return this.state.selectedTask?.node_type || "";
    }

    _isTaskType(typeSet) {
        return Boolean(this.state.selectedTask && typeSet?.has(this.selectedTaskNodeType));
    }

    get isStartEventNode() {
        return this._isTaskType(START_EVENT_NODE_TYPES);
    }

    get isEndEventNode() {
        return this._isTaskType(END_EVENT_NODE_TYPES);
    }

    get isGatewayNode() {
        return this._isTaskType(GATEWAY_NODE_TYPES);
    }

    get isExclusiveGatewayNode() {
        return this.selectedTaskNodeType === "exclusiveGateway";
    }

    get isParallelGatewayNode() {
        return this.selectedTaskNodeType === "parallelGateway";
    }

    get isInclusiveGatewayNode() {
        return this.selectedTaskNodeType === "inclusiveGateway";
    }

    get isConditionalEventNode() {
        return this.selectedTaskNodeType === "conditionalEventDefinition";
    }

    get isHumanTaskNode() {
        return this._isTaskType(HUMAN_TASK_NODE_TYPES);
    }

    get isCallActivityNode() {
        return this.selectedTaskNodeType === "callActivity";
    }

    get isSubProcessNode() {
        return this.selectedTaskNodeType === "subProcess";
    }

    get isReceiveTaskNode() {
        return this.selectedTaskNodeType === "receiveTask";
    }

    get isSendTaskNode() {
        return this.selectedTaskNodeType === "sendTask";
    }

    get isServiceTaskNode() {
        return this.selectedTaskNodeType === "serviceTask";
    }

    get isScriptTaskNode() {
        return this.selectedTaskNodeType === "scriptTask";
    }

    get isBusinessRuleTaskNode() {
        return this.selectedTaskNodeType === "businessRuleTask";
    }

    get showTaskSequenceSection() {
        return this.isHumanTaskNode
            || this.isSendTaskNode
            || this.isServiceTaskNode
            || this.isScriptTaskNode
            || this.isBusinessRuleTaskNode
            || this.isReceiveTaskNode;
    }

    get showTaskCssClassSection() {
        return false;
    }

    get showTaskElementTypeSection() {
        return false;
    }

    get showTaskIsEndNodeSection() {
        return false;
    }

    get showTaskConditionalDomainSection() {
        return this.isConditionalEventNode;
    }

    get showTaskActionWindowSection() {
        return this.isStartEventNode;
    }

    get showTaskEmailTemplateSection() {
        return this.showTaskNotificationSection && this.notificationDeliveryMode === "email";
    }

    get showTaskActivityTypeSection() {
        return this.showTaskNotificationSection;
    }

    get showTaskActivityTemplateSection() {
        return this.showTaskNotificationSection && this.notificationDeliveryMode === "log";
    }

    get showTaskNotificationSection() {
        return this._isTaskType(MESSAGE_NOTIFICATION_NODE_TYPES);
    }

    get showTaskServiceBehaviorSection() {
        return this.isServiceTaskNode;
    }

    get taskServiceBehaviorHelpText() {
        if ((this.state.selectedTask?.service_behavior || "router") === "executor") {
            return _t("Executor runs every selected server action, then continues through the outgoing route.");
        }
        return _t("Router performs no workflow action; it only continues through the matching outgoing route.");
    }

    get showTaskWorkflowActionsSection() {
        return (this.isSendTaskNode && this.notificationDeliveryMode === "channels")
            || this.isScriptTaskNode
            || (this.isServiceTaskNode
                && (this.state.selectedTask?.service_behavior || "router") === "executor");
    }

    get showTaskAutomationSection() {
        return this.isSendTaskNode
            || this.isScriptTaskNode
            || (this.isServiceTaskNode
                && (this.state.selectedTask?.service_behavior || "router") === "executor");
    }

    get supportsEngineManagedAutomationTask() {
        return this.selectedTaskNodeType === "scriptTask"
            || (this.selectedTaskNodeType === "serviceTask"
                && (this.state.selectedTask?.service_behavior || "router") === "executor");
    }

    get showTaskAutomationScheduleSection() {
        return this.showTaskAutomationSection
            && this.supportsEngineManagedAutomationTask
            && (this.state.selectedTask?.automation_run_mode || "immediate") === "scheduled";
    }

    get showTaskAutomationRecurringSection() {
        return this.showTaskAutomationScheduleSection
            && !!this.state.selectedTask?.automation_is_recurring;
    }

    // Notification channels use their manager dialog; executable actions use
    // the inline many-to-many selector.
    get showTaskWorkflowActionsTagSection() {
        return this.showTaskNotificationSection && this.notificationDeliveryMode === "channels";
    }

    // ── Meta Action flow-type helpers ──────────────────────────────────────────
    // Human-triggered button actions (show button UI, confirmation, 2FA, etc.)
    get isButtonFlowAction() {
        const t = this.state.selectedAction?.flow_type;
        return t === "userAction" || t === "emailAction" || t === "noEmailAction";
    }

    get selectedActionEngineNodeType() {
        const selectedElement = this.selectedActionElement;
        if (selectedElement) {
            return this._getEngineNodeType(selectedElement);
        }
        return this.state.selectedElement?.nodeType || "";
    }

    get selectedActionTargetNodeType() {
        return this.state.selectedAction?.target_node_type || "";
    }

    get selectedActionInteractiveNodeType() {
        return this.selectedActionEngineNodeType || this.selectedActionTargetNodeType;
    }

    get selectedActionMessageNotificationTask() {
        if (this.selectedActionInteractiveNodeType !== "intermediateThrowEventMessage") {
            return null;
        }
        const nodeId = this.state.selectedElement?.id || "";
        if (!nodeId) {
            return null;
        }
        return (this.state.payload?.meta?.tasks || []).find((task) => task.node_id === nodeId) || null;
    }

    get showSelectedActionMessageNotificationSection() {
        return Boolean(this.selectedActionMessageNotificationTask);
    }

    get selectedActionMessageNotificationRecipientSource() {
        const task = this.selectedActionMessageNotificationTask;
        const source = task?.notification_recipient_source;
        if (source) {
            return source;
        }
        return (task?.notification_recipient_mode || "specific_users") === "domain" ? "domain" : "specific_users";
    }

    get isSelectedSequenceFlowAction() {
        const selectedElement = this.selectedActionElement;
        if (selectedElement?.type) {
            return selectedElement.type === "bpmn:SequenceFlow";
        }
        return this.state.selectedElement?.type === "bpmn:SequenceFlow";
    }

    get isSelectedActionNode() {
        return (
            this.state.selectedElement?.kind === "action"
            && !this.isSelectedSequenceFlowAction
            && INTERACTIVE_ACTION_NODE_TYPES.has(this.selectedActionInteractiveNodeType)
        );
    }

    get showInteractiveActionBehaviorSection() {
        return Boolean(
            this.state.selectedAction
            && this.isButtonFlowAction
            && INTERACTIVE_ACTION_NODE_TYPES.has(this.selectedActionInteractiveNodeType)
        );
    }

    get showInteractiveActionAppearanceSection() {
        if (!this.isSelectedActionNode) {
            return false;
        }
        const t = this.state.selectedAction?.flow_type;
        return t === "emailAction" || t === "noEmailAction";
    }

    get showSequenceFlowRouteDomainSection() {
        return (
            this.isSelectedSequenceFlowAction
            && !this.isAutoFlowAction
            && !this.showConditionalDefaultFlowSection
            && !INTERACTIVE_ACTION_NODE_TYPES.has(this.selectedActionTargetNodeType)
        );
    }

    get showActionAutoConditionSection() {
        return this.isAutoFlowAction;
    }

    // Timer-based auto transitions (show timer schedule, auto condition only)
    get isAutoFlowAction() {
        return this.state.selectedAction?.flow_type === "autoAction";
    }

    // System routing / subprocess (show routing domain only)
    get isSystemFlowAction() {
        const t = this.state.selectedAction?.flow_type;
        return t === "systemAction" || t === "startAction" || t === "subprocessAction";
    }

    get selectedActionElement() {
        if (!this.modeler || !this.state.selectedElement?.id) {
            return null;
        }
        return this.modeler.get("elementRegistry")?.get(this.state.selectedElement.id) || null;
    }

    get selectedActionSourceElement() {
        const sourceId = this.state.selectedAction?.source_id || this.state.selectedElement?.sourceId;
        if (!this.modeler || !sourceId) {
            return null;
        }
        return this.modeler.get("elementRegistry")?.get(sourceId) || null;
    }

    get showConditionalDefaultFlowSection() {
        return this._getEngineNodeType(this.selectedActionSourceElement) === "conditionalEventDefinition";
    }

    get isSelectedActionDefaultFlow() {
        if (!this.showConditionalDefaultFlowSection) {
            return false;
        }
        const sourceId = this.state.selectedAction?.source_id || this.state.selectedElement?.sourceId;
        const flowId = this.state.selectedElement?.id;
        if (!sourceId || !flowId) {
            return false;
        }
        const doc = parseXmlDocument(this.state.currentXml || "");
        const definitionsNode = findBpmnDefinitionsNode(doc);
        if (!definitionsNode) {
            return false;
        }
        const sourceNode = Array.from(definitionsNode.getElementsByTagName("*")).find(
            (node) => node.namespaceURI === BPMN_MODEL_NS && node.getAttribute("id") === sourceId
        );
        return !!sourceNode && sourceNode.getAttribute("default") === flowId;
    }
    // ──────────────────────────────────────────────────────────────────────────

    get showTaskApprovalGroupDomainSection() {
        return this.isHumanTaskNode;
    }

    get notificationRecipientMode() {
        return this.state.selectedTask?.notification_recipient_mode || "specific_users";
    }

    get notificationRecipientSource() {
        const source = this.state.selectedTask?.notification_recipient_source;
        if (source) {
            return source;
        }
        return this.notificationRecipientMode === "domain" ? "domain" : "specific_users";
    }

    get notificationDeliveryMode() {
        const mode = this.state.selectedTask?.notification_delivery_mode;
        if (mode) {
            return mode;
        }
        const channelIds = this.state.selectedTask?.activity_type_ids || [];
        return channelIds.length ? "channels" : "email";
    }

    get showTaskSendEmailConfig() {
        return this.showTaskNotificationSection && this.notificationDeliveryMode === "email";
    }

    get showTaskLogActivityConfig() {
        return this.showTaskNotificationSection && this.notificationDeliveryMode === "log";
    }

    get showTaskChannelsConfig() {
        return this.showTaskNotificationSection && this.notificationDeliveryMode === "channels";
    }

    get showTaskNotificationDomainSection() {
        if (!this.showTaskSendEmailConfig) {
            return false;
        }
        return ["domain", "approval_group_users", "group_users", "node_users"].includes(
            this.notificationRecipientSource
        );
    }

    get taskNotificationFilterLabel() {
        return this.notificationRecipientSource === "domain"
            ? _t("Notification Domain")
            : _t("Advanced Filter Domain");
    }

    get showTaskNotificationRecipientTagSection() {
        if (!this.showTaskSendEmailConfig) {
            return false;
        }
        return this.notificationRecipientSource === "specific_users";
    }

    get showTaskNotificationApprovalGroupSection() {
        return this.showTaskSendEmailConfig && this.notificationRecipientSource === "approval_group_users";
    }

    get showTaskNotificationGroupSection() {
        return this.showTaskSendEmailConfig && this.notificationRecipientSource === "group_users";
    }

    get showTaskNotificationNodeSourceSection() {
        if (!this.showTaskSendEmailConfig) {
            return false;
        }
        return this.notificationRecipientSource === "node_users";
    }

    get showTaskAssignmentNodeSourceSection() {
        return this.isHumanTaskNode && this.state.selectedTask?.assignment_mode === "previous_actor";
    }

    get showTaskRuntimeAssignmentSection() {
        return this.isHumanTaskNode;
    }

    get showTaskParallelAndReworkSection() {
        return this.isGatewayNode;
    }

    get showTaskConfidentialitySection() {
        return this.isHumanTaskNode;
    }

    get showTaskMetaFieldsSection() {
        return this._isTaskType(FIELD_RULE_CONFIG_NODE_TYPES) || Boolean(this.state.selectedTask?.is_end_node);
    }

    get showTaskApprovalGroupsSection() {
        return this.isHumanTaskNode;
    }

    get showTaskWorkflowMapSection() {
        return this.selectedTaskNodeType === "callActivity";
    }

    get selectedTaskWorkflowActionOptions() {
        if (!this.state.selectedTask) {
            return [];
        }
        const selectedIds = new Set(this.state.selectedTask.activity_type_ids || []);
        const query = (this.state.selectedNotificationChannelQuery || "").trim().toLowerCase();
        return (this.workflowActionOptions || []).filter((option) => {
            if (!selectedIds.has(option.id)) {
                return false;
            }
            if (!query) {
                return true;
            }
            return this._channelOptionSearchLabel(option).includes(query);
        });
    }

    get taskWorkflowActionAllowedTypes() {
        if (
            this.isServiceTaskNode
            && (this.state.selectedTask?.service_behavior || "router") === "executor"
        ) {
            return ["server_action"];
        }
        if (this.isScriptTaskNode) {
            return ["workflow", "server_action", "log"];
        }
        return [];
    }

    get selectableTaskWorkflowActionOptions() {
        const allowedTypes = new Set(this.taskWorkflowActionAllowedTypes);
        return (this.workflowActionOptions || []).filter(
            (action) => allowedTypes.has(action.action_type)
        );
    }

    get taskWorkflowActionsProps() {
        return {
            resModel: "workflow.approval.action",
            resIds: [...(this.state.selectedTask?.activity_type_ids || [])],
            domain: [["id", "in", this.selectableTaskWorkflowActionOptions.map((action) => action.id)]],
            fieldString: this.isServiceTaskNode ? _t("Server Actions") : _t("Workflow Actions"),
            placeholder: this.isServiceTaskNode
                ? _t("Select server actions...")
                : _t("Select workflow actions..."),
            update: async (resIds) => {
                await this.onTaskFieldChange(
                    "activity_type_ids",
                    (resIds || []).map((id) => Number(id)).filter((id) => id > 0)
                );
            },
        };
    }

    get taskWorkflowActionsHelpText() {
        if (this.isServiceTaskNode) {
            return _t("Select one or more server actions. Every selected action runs when this executor is reached.");
        }
        return _t("Select one or more actions. Every selected action runs when this script task is reached.");
    }

    get explicitUserSelectedIds() {
        return new Set(this.state.selectedTask?.explicit_user_ids || []);
    }

    get explicitUsersProps() {
        return {
            resModel: "res.users",
            resIds: [...this.explicitUserSelectedIds],
            update: async (resIds) => {
                await this.onTaskFieldChange("explicit_user_ids", resIds);
            },
        };
    }

    get businessActorUsersProps() {
        return {
            resModel: "res.users",
            resIds: [...(this.state.selectedAction?.business_actor_user_ids || [])],
            update: async (resIds) => {
                await this.onActionFieldChange("business_actor_user_ids", resIds);
            },
        };
    }

    get businessActorGroupsProps() {
        return {
            resModel: "res.groups",
            resIds: [...(this.state.selectedAction?.business_actor_group_ids || [])],
            update: async (resIds) => {
                await this.onActionFieldChange("business_actor_group_ids", resIds);
            },
        };
    }

    get businessActorApprovalGroupsProps() {
        return {
            resModel: "workflow.approval.group",
            resIds: [...(this.state.selectedAction?.business_actor_approval_group_ids || [])],
            update: async (resIds) => {
                await this.onActionFieldChange("business_actor_approval_group_ids", resIds);
            },
        };
    }

    get notificationRecipientProps() {
        return {
            resModel: "res.users",
            resIds: [...(this.state.selectedTask?.notification_recipient_ids || [])],
            update: async (resIds) => {
                await this.onTaskFieldChange("notification_recipient_ids", resIds);
            },
        };
    }

    get actionMessageNotificationRecipientProps() {
        return {
            resModel: "res.users",
            resIds: [...(this.selectedActionMessageNotificationTask?.notification_recipient_ids || [])],
            update: async (resIds) => {
                await this.onActionMessageNotificationTaskFieldChange("notification_recipient_ids", resIds);
            },
        };
    }

    get notificationApprovalGroupProps() {
        return {
            resModel: "workflow.approval.group",
            resIds: [...(this.state.selectedTask?.notification_approval_group_ids || [])],
            update: async (resIds) => {
                await this.onTaskFieldChange("notification_approval_group_ids", resIds);
            },
        };
    }

    get notificationGroupProps() {
        return {
            resModel: "res.groups",
            resIds: [...(this.state.selectedTask?.notification_group_ids || [])],
            update: async (resIds) => {
                await this.onTaskFieldChange("notification_group_ids", resIds);
            },
        };
    }

    get selectedNotificationChannels() {
        const selectedIds = new Set(this.state.selectedTask?.activity_type_ids || []);
        const query = (this.state.selectedNotificationChannelQuery || "").trim().toLowerCase();
        return (this.workflowActionOptions || []).filter((opt) => {
            if (!selectedIds.has(opt.id)) {
                return false;
            }
            if (!query) {
                return true;
            }
            return this._channelOptionSearchLabel(opt).includes(query);
        });
    }

    async removeNotificationChannel(channelId) {
        const current = this.state.selectedTask?.activity_type_ids || [];
        await this.onTaskFieldChange(
            "activity_type_ids",
            current.filter((id) => id !== channelId)
        );
    }

    get allAvailableChannelOptions() {
        const selectedIds = new Set(this.state.selectedTask?.activity_type_ids || []);
        const isNotificationNode = this.showTaskNotificationSection;
        // For notification nodes, only show channels whose action_type
        // is compatible. This matches the engine's _allowed_action_types_for_node()
        // for notification nodes (email, sms, telegram, webhook, log).
        const allowedTypes = isNotificationNode
            ? new Set(["email", "sms", "telegram", "webhook", "log"])
            : null;
        return (this.workflowActionOptions || []).filter((opt) => {
            if (selectedIds.has(opt.id)) {
                return false;
            }
            if (allowedTypes && opt.action_type && !allowedTypes.has(opt.action_type)) {
                return false;
            }
            return true;
        });
    }

    get availableChannelOptions() {
        const query = (this.state.notificationChannelQuery || "").trim().toLowerCase();
        return this.allAvailableChannelOptions.filter((opt) => {
            if (!query) {
                return true;
            }
            return this._channelOptionSearchLabel(opt).includes(query);
        });
    }

    get automationRunModeOptions() {
        return this.state.payload?.options?.automation_run_modes || [];
    }

    get automationScheduleModeOptions() {
        return this.state.payload?.options?.automation_schedule_modes || [];
    }

    get automationIntervalTypeOptions() {
        return this.state.payload?.options?.automation_interval_types || [];
    }

    get automationRecurrenceEndModeOptions() {
        return this.state.payload?.options?.automation_recurrence_end_modes || [];
    }

    get automationReminderPresetOptions() {
        return [
            {
                value: "once_3m",
                label: _t("One Time After 3 Minutes"),
                values: {
                    automation_run_mode: "scheduled",
                    automation_schedule_mode: "interval",
                    automation_interval_number: 3,
                    automation_interval_type: "minutes",
                    automation_is_recurring: false,
                    automation_recurrence_end_mode: "forever",
                    automation_recurrence_count: 10,
                    automation_recurrence_until: false,
                },
            },
            {
                value: "repeat_3m_forever",
                label: _t("Every 3 Minutes Forever"),
                values: {
                    automation_run_mode: "scheduled",
                    automation_schedule_mode: "interval",
                    automation_interval_number: 3,
                    automation_interval_type: "minutes",
                    automation_is_recurring: true,
                    automation_recurrence_end_mode: "forever",
                    automation_recurrence_count: 10,
                    automation_recurrence_until: false,
                },
            },
            {
                value: "repeat_hourly",
                label: _t("Every 1 Hour Forever"),
                values: {
                    automation_run_mode: "scheduled",
                    automation_schedule_mode: "interval",
                    automation_interval_number: 1,
                    automation_interval_type: "hours",
                    automation_is_recurring: true,
                    automation_recurrence_end_mode: "forever",
                    automation_recurrence_count: 10,
                    automation_recurrence_until: false,
                },
            },
            {
                value: "repeat_2h_x10",
                label: _t("Every 2 Hours, 10 Times"),
                values: {
                    automation_run_mode: "scheduled",
                    automation_schedule_mode: "interval",
                    automation_interval_number: 2,
                    automation_interval_type: "hours",
                    automation_is_recurring: true,
                    automation_recurrence_end_mode: "count",
                    automation_recurrence_count: 10,
                    automation_recurrence_until: false,
                },
            },
            {
                value: "repeat_weekly",
                label: _t("Every 1 Week Forever"),
                values: {
                    automation_run_mode: "scheduled",
                    automation_schedule_mode: "interval",
                    automation_interval_number: 1,
                    automation_interval_type: "weeks",
                    automation_is_recurring: true,
                    automation_recurrence_end_mode: "forever",
                    automation_recurrence_count: 10,
                    automation_recurrence_until: false,
                },
            },
            {
                value: "advanced",
                label: _t("Advanced / Custom"),
                values: null,
            },
        ];
    }

    get selectedAutomationPresetValue() {
        const task = this.state.selectedTask || {};
        for (const preset of this.automationReminderPresetOptions) {
            if (!preset.values) {
                continue;
            }
            const matches = Object.entries(preset.values).every(([key, value]) => {
                const current = task[key] ?? false;
                return current === value;
            });
            if (matches) {
                return preset.value;
            }
        }
        return "advanced";
    }

    get selectedActionAutomationPresetValue() {
        const action = this.state.selectedAction || {};
        for (const preset of this.automationReminderPresetOptions) {
            if (!preset.values) {
                continue;
            }
            const matches = Object.entries(preset.values).every(([key, value]) => {
                if (key === "automation_run_mode") {
                    return value === "scheduled";
                }
                const current = action[key] ?? false;
                return current === value;
            });
            if (matches) {
                return preset.value;
            }
        }
        return "advanced";
    }

    toDatetimeLocalValue(value) {
        if (!value) {
            return "";
        }
        return String(value).trim().replace(" ", "T").slice(0, 16);
    }

    fromDatetimeLocalValue(value) {
        if (!value) {
            return false;
        }
        const normalized = String(value).trim().replace("T", " ");
        return normalized.length === 16 ? `${normalized}:00` : normalized;
    }

    async _writeSelectedTaskValues(values) {
        if (!this.state.selectedTask) {
            return false;
        }
        if (!this._assertEditableVersion()) {
            return false;
        }
        try {
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_write_meta_task",
                [[this.state.versionId], this.state.selectedTask.node_id, values]
            );
            if (result?.warnings?.length) {
                this.notification.add(result.warnings.join("\n"), {type: "warning"});
            }
            const task = result ? {...result} : result;
            if (task && Object.prototype.hasOwnProperty.call(task, "warnings")) {
                delete task.warnings;
            }
            this._updateLocalTask(task);
            this._refreshSelectionMetadata();
            return true;
        } catch {
            this.notification.add(_t("Failed to update task metadata."), {type: "danger"});
            return false;
        }
    }

    async onAutomationReminderPresetChange(event) {
        const presetValue = event?.target?.value || "";
        if (!presetValue || presetValue === "advanced") {
            return;
        }
        const preset = this.automationReminderPresetOptions.find((item) => item.value === presetValue);
        if (!preset?.values) {
            return;
        }
        await this._writeSelectedTaskValues(preset.values);
    }

    async onActionAutomationReminderPresetChange(event) {
        const presetValue = event?.target?.value || "";
        if (!presetValue || presetValue === "advanced") {
            return;
        }
        const preset = this.automationReminderPresetOptions.find((item) => item.value === presetValue);
        if (!preset?.values) {
            return;
        }
        const values = {...preset.values};
        delete values.automation_run_mode;
        await this._writeSelectedActionValues(values);
    }

    async onActionAutomationTriggerModeChange(event) {
        const mode = event?.target?.value === "reminder" ? "reminder" : "route";
        const values = {automation_trigger_mode: mode};
        if (mode === "reminder" && !this.state.selectedAction?.automation_is_recurring) {
            Object.assign(values, {
                automation_is_recurring: true,
                automation_recurrence_end_mode: "forever",
            });
        }
        const optimisticAction = this.state.selectedAction
            ? {...this.state.selectedAction, ...values}
            : null;
        if (optimisticAction) {
            this._updateLocalAction(optimisticAction);
        }
        const persisted = await this._writeSelectedActionValues(values);
        if (!persisted && event?.target) {
            event.target.value = this.state.selectedAction?.automation_trigger_mode || mode;
        } else if (persisted && optimisticAction) {
            // Preserve the mode in case an old server response does not serialize it yet.
            this._updateLocalAction({...this.state.selectedAction, ...values});
        }
    }

    _channelOptionLabel(opt) {
        const name = opt.name || "";
        switch (opt.action_type) {
            case "email":
                return opt.email_template_name
                    ? `${name} → ${opt.email_template_name}`
                    : name;
            case "server_action":
                return opt.server_action_name
                    ? `${name} → ${opt.server_action_name}`
                    : name;
            case "sms":
            case "telegram": {
                const preview = (opt.message_body || "").slice(0, 40).trim();
                return preview ? `${name}: ${preview}` : name;
            }
            case "webhook":
                return opt.webhook_url
                    ? `${name} → ${opt.webhook_url}`
                    : name;
            default:
                return name;
        }
    }

    _channelOptionSearchLabel(opt) {
        return [
            opt?.name || "",
            opt?.action_type || "",
            opt?.email_template_name || "",
            opt?.server_action_name || "",
            opt?.webhook_url || "",
            this._channelOptionLabel(opt),
        ].join(" ").toLowerCase();
    }

    async addChannelById(channelId) {
        const id = Number(channelId);
        if (!id || !this._assertEditableVersion()) {
            return;
        }
        const current = this.state.selectedTask?.activity_type_ids || [];
        if (current.includes(id)) {
            return;
        }
        await this.onTaskFieldChange("activity_type_ids", [...current, id]);
    }

    get approvalGroupCatalogModeOptions() {
        return [
            {value: "all", label: _t("All")},
            {value: "linked", label: _t("Linked")},
            {value: "available", label: _t("Remaining")},
        ];
    }

    get approvalGroupCatalogRoutingFilterOptions() {
        return [
            {value: "all", label: _t("All Routing")},
            {value: "needs_config", label: _t("Needs Configuration")},
            {value: "user_domain:ignored_blank", label: _t("User Filter Blank")},
            {value: "user_domain:ignored_empty", label: _t("User Filter []")},
            {value: "domain:ignored_blank", label: _t("Record Domain Blank")},
            {value: "domain:ignored_empty", label: _t("Record Domain []")},
        ];
    }

    _normalizeTaskActionKey(action, index = 0) {
        const current = String(action?.action_key || "").trim();
        if (current) {
            return current;
        }
        const sourceId = String(action?.source_id || this.state.selectedTask?.node_id || "").trim();
        const targetId = String(action?.target_id || action?.node_id || action?.id || "").trim();
        if (sourceId && targetId) {
            return `${sourceId}|${targetId}`;
        }
        if (targetId) {
            return `action:${targetId}`;
        }
        return `action:fallback:${index}`;
    }

    get selectedTaskOutgoingActions() {
        if (!this.state.selectedTask) {
            return [];
        }
        return this._taskOutgoingActions(this.state.selectedTask.node_id);
    }

    _taskOutgoingActions(taskNodeId) {
        if (!taskNodeId) {
            return [];
        }
        const actions = this.state.payload?.meta?.actions || [];
        return actions
            .filter((action) => action?.source_id === taskNodeId)
            .map((action, index) => ({
                ...action,
                action_key: this._normalizeTaskActionKey(action, index),
            }));
    }

    get selectedSharedActionNodeIncomingActions() {
        const selected = this.state.selectedElement;
        if (!selected?.isAmbiguousActionNode) {
            return [];
        }
        const actionNodeId = selected.targetId || selected.id;
        if (!actionNodeId) {
            return [];
        }
        return (this.state.payload?.meta?.actions || [])
            .filter((action) => action?.target_id === actionNodeId)
            .sort((left, right) => {
                const leftLabel = `${left.source_name || ""} ${left.name || ""}`;
                const rightLabel = `${right.source_name || ""} ${right.name || ""}`;
                return leftLabel.localeCompare(rightLabel);
            });
    }

    triggerImport() {
        this.fileInputRef.el?.click();
    }

    triggerZipImport() {
        this.zipFileInputRef.el?.click();
    }

    async onFileSelected(ev) {
        const file = ev.target.files?.[0];
        ev.target.value = "";
        if (!file || !this.modeler) {
            return;
        }
        if (!this._assertEditableVersion()) {
            return;
        }

        try {
            const rawText = await file.text();
            const xml = this._normalizeBpmnXml(rawText, {fallbackToDefault: false});
            if (!xml) {
                throw new Error(_t("Selected file does not contain BPMN definitions."));
            }
            await this.modeler.importXML(xml);
            this.state.currentXml = xml;
            this.state.isDirty = xml !== this.state.lastSavedXml;
            this.fitDiagram();
            this._applyPaletteRestrictions();
            this.notification.add(_t("BPMN XML imported."), {type: "success"});
        } catch (error) {
            const message = error?.message ? ` ${error.message}` : "";
            this.notification.add(`${_t("Invalid BPMN XML file.")}${message}`, {type: "danger"});
        }
    }

    async exportDiagram() {
        const xml = await this._getCurrentXml();
        const blob = new Blob([xml], {type: "application/xml;charset=utf-8"});
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `${this.state.versionTitle || "workflow"}.bpmn`;
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        URL.revokeObjectURL(url);
    }

    async _syncCurrentDiagram(showSuccessToast = true) {
        if (!this.state.canEdit || this.state.isSaving) {
            return false;
        }
        if (!this._assertEditableVersion()) {
            return false;
        }
        const latestXml = await this._getCurrentXml();
        const violations = getConditionalEventOutgoingLimitViolationsFromXml(latestXml);
        if (violations.length) {
            this._showConditionalEventOutgoingLimitWarning(violations);
            return false;
        }
        this.state.isSaving = true;
        let success = false;
        try {
            const xml = latestXml;
            const payload = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_sync_from_bpmn",
                [[this.state.versionId], xml]
            );
            this.state.currentXml = xml;
            this.state.lastSavedXml = xml;
            this.state.isDirty = false;
            this._setPayload(payload);
            success = true;
            if (showSuccessToast) {
                this.notification.add(_t("BPMN diagram and metadata saved."), {type: "success"});
            }
        } catch {
            this.notification.add(_t("Failed to save BPMN diagram."), {type: "danger"});
        } finally {
            this.state.isSaving = false;
        }
        return success;
    }

    get hasPendingMetaFieldChanges() {
        return Object.keys(this.state.pendingMetaFieldRowsByNode || {}).length > 0;
    }

    async _saveStudioChanges(showSuccessToast = true) {
        this._stageSelectedMetaFieldRows();
        const synced = await this._syncCurrentDiagram(false);
        if (!synced) {
            return false;
        }
        const metaSaved = await this._savePendingMetaFields({silentSuccess: true});
        if (!metaSaved) {
            return false;
        }
        if (showSuccessToast) {
            this.notification.add(_t("BPMN diagram and metadata saved."), {type: "success"});
        }
        return true;
    }

    async _savePendingStudioChangesBeforeAction() {
        if (!this.state.isDirty && !this.hasPendingMetaFieldChanges) {
            return true;
        }
        return this._saveStudioChanges(false);
    }

    async saveDiagram() {
        await this._saveStudioChanges(true);
    }

    async syncMetadata() {
        const saved = await this._saveStudioChanges(false);
        if (saved) {
            this.notification.add(_t("Metadata synchronized from BPMN diagram."), {type: "success"});
        }
    }

    async exportStudioZip() {
        try {
            // Keep bundle consistent with the latest diagram edits.
            const saved = await this._savePendingStudioChangesBeforeAction();
            if (!saved) {
                return;
            }
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_export_bundle",
                [[this.state.versionId]]
            );
            const bytes = fromBase64(result.content);
            const blob = new Blob([bytes], {type: "application/zip"});
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement("a");
            anchor.href = url;
            anchor.download = result.filename || `${this.state.versionTitle || "workflow"}.zip`;
            document.body.appendChild(anchor);
            anchor.click();
            document.body.removeChild(anchor);
            URL.revokeObjectURL(url);
        } catch {
            this.notification.add(_t("Failed to export workflow ZIP."), {type: "danger"});
        }
    }

    async onZipFileSelected(ev) {
        const file = ev.target.files?.[0];
        ev.target.value = "";
        if (!file) {
            return;
        }
        if (!this._assertEditableVersion()) {
            return;
        }
        try {
            const buffer = await file.arrayBuffer();
            const content = toBase64(buffer);
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_import_bundle",
                [[this.state.versionId], content]
            );

            if (result?.bpmn_xml && this.modeler) {
                await this.modeler.importXML(result.bpmn_xml);
                this.fitDiagram();
                this._applyPaletteRestrictions();
                this.state.currentXml = result.bpmn_xml;
                this.state.lastSavedXml = result.bpmn_xml;
                this.state.isDirty = false;
            }
            if (result?.payload) {
                this.state.pendingMetaFieldRowsByNode = {};
                this._setPayload(result.payload);
            } else {
                this.state.pendingMetaFieldRowsByNode = {};
                await this._loadEditorPayload();
            }
            if (result?.warnings?.length) {
                this.notification.add(result.warnings.join("\n"), {type: "warning"});
            }
            this.notification.add(_t("Workflow ZIP imported successfully."), {type: "success"});
        } catch {
            this.notification.add(_t("Failed to import workflow ZIP."), {type: "danger"});
        }
    }

    fitDiagram({retries = 0} = {}) {
        const canvas = this.modeler?.get("canvas");
        const canvasEl = this.canvasRef.el;
        if (!canvas || !canvasEl) {
            return;
        }
        if (canvasEl.clientWidth <= 16 || canvasEl.clientHeight <= 16) {
            if (retries > 0) {
                setTimeout(() => this.fitDiagram({retries: retries - 1}), 80);
            }
            return;
        }
        try {
            canvas.resized?.();
        } catch {
            // Keep editor usable when resize dispatch fails.
        }
        const bounds = this._getDiagramBounds();
        if (!bounds) {
            this._recoverDiagramFromBlankCanvas({retries});
            if (retries > 0) {
                setTimeout(() => this.fitDiagram({retries: retries - 1}), 80);
            }
            return;
        }
        try {
            canvas.zoom("fit-viewport", "auto");
        } catch {
            // Keep editor usable when fit fails on early render.
        }
    }

    async _recoverDiagramFromBlankCanvas({retries = 0} = {}) {
        if (this._isRecoveringDiagram || !this.modeler) {
            return;
        }
        if (this._getDiagramBounds()) {
            return;
        }
        this._isRecoveringDiagram = true;
        try {
            const importedXml = await this._importXmlWithFallback(
                this.state.currentXml || this.state.lastSavedXml || this.state.payload?.version?.bpmn_xml
            );
            if (importedXml && importedXml !== this.state.currentXml) {
                this.state.currentXml = importedXml;
                this.state.isDirty = importedXml !== this.state.lastSavedXml;
            }
            const canvas = this.modeler?.get("canvas");
            canvas?.resized?.();
            canvas?.zoom?.("fit-viewport", "auto");
        } catch {
            // Keep trying through retries below.
        } finally {
            this._isRecoveringDiagram = false;
        }
        if (!this._getDiagramBounds() && retries > 0) {
            setTimeout(() => this._recoverDiagramFromBlankCanvas({retries: retries - 1}), 120);
        }
    }

    _getDiagramBounds() {
        const elementRegistry = this.modeler?.get("elementRegistry");
        const all = elementRegistry?.getAll?.() || [];
        let minX = Infinity;
        let minY = Infinity;
        let maxX = -Infinity;
        let maxY = -Infinity;
        for (const element of all) {
            if (!element || element.id === "__implicitroot" || AUXILIARY_SHAPE_TYPES.has(element.type)) {
                continue;
            }
            if (Array.isArray(element.waypoints) && element.waypoints.length) {
                for (const point of element.waypoints) {
                    if (!Number.isFinite(point?.x) || !Number.isFinite(point?.y)) {
                        continue;
                    }
                    minX = Math.min(minX, point.x);
                    minY = Math.min(minY, point.y);
                    maxX = Math.max(maxX, point.x);
                    maxY = Math.max(maxY, point.y);
                }
                continue;
            }
            if (
                Number.isFinite(element.x)
                && Number.isFinite(element.y)
                && Number.isFinite(element.width)
                && Number.isFinite(element.height)
            ) {
                minX = Math.min(minX, element.x);
                minY = Math.min(minY, element.y);
                maxX = Math.max(maxX, element.x + element.width);
                maxY = Math.max(maxY, element.y + element.height);
            }
        }
        if (
            !Number.isFinite(minX)
            || !Number.isFinite(minY)
            || !Number.isFinite(maxX)
            || !Number.isFinite(maxY)
        ) {
            return null;
        }
        return {
            minX,
            minY,
            maxX,
            maxY,
            centerX: (minX + maxX) / 2,
            centerY: (minY + maxY) / 2,
        };
    }

    async _autoSyncMetadataForSelection() {
        const selected = this.state.selectedElement;
        if (!selected || !selected.supported || this.state.versionIsLocked) {
            return;
        }
        if (!["task", "action"].includes(selected.kind)) {
            return;
        }
        const hasMetadata =
            (selected.kind === "task" && !!this.state.selectedTask)
            || (selected.kind === "action" && !!this.state.selectedAction);
        if (hasMetadata) {
            return;
        }
        if (this._isAutoMetaSyncInProgress || this.state.isSaving) {
            return;
        }
        const syncKey = `${selected.kind}:${selected.id}:${selected.actionKey || ""}:${this.state.currentXml?.length || 0}`;
        if (this._lastAutoMetaSyncKey === syncKey) {
            return;
        }
        this._lastAutoMetaSyncKey = syncKey;
        this._isAutoMetaSyncInProgress = true;
        let synced = false;
        try {
            synced = await this._syncCurrentDiagram(false);
        } finally {
            if (!synced) {
                this._lastAutoMetaSyncKey = null;
            }
            this._isAutoMetaSyncInProgress = false;
        }
    }

    zoom(delta) {
        const canvas = this.modeler?.get("canvas");
        if (!canvas) {
            return;
        }
        const currentZoom = Number(canvas.zoom()) || 1;
        const nextZoom = Math.max(0.1, Math.min(4, currentZoom + delta));
        if (!Number.isFinite(nextZoom)) {
            return;
        }
        try {
            canvas.zoom(nextZoom);
        } catch {
            // Keep editor usable when zoom fails.
        }
    }

    undo() {
        this.modeler?.get("commandStack")?.undo();
    }

    redo() {
        this.modeler?.get("commandStack")?.redo();
    }

    _updateLocalTask(taskData, select = true) {
        if (!taskData?.node_id) {
            return;
        }
        const tasks = this.state.payload?.meta?.tasks || [];
        const index = tasks.findIndex((task) => task.node_id === taskData.node_id);
        if (index >= 0) {
            tasks.splice(index, 1, taskData);
        } else {
            tasks.push(taskData);
        }
        if (select) {
            this.state.selectedTask = taskData;
        }
    }

    _updateLocalAction(actionData) {
        if (!actionData?.action_key) {
            return;
        }
        const actions = this.state.payload?.meta?.actions || [];
        const index = actions.findIndex((action) => action.action_key === actionData.action_key);
        if (index >= 0) {
            actions.splice(index, 1, actionData);
        } else {
            actions.push(actionData);
        }
        this.state.selectedAction = actionData;
    }

    _updateDiagramName(name) {
        if (!this.modeler || !this.state.selectedElement) {
            return;
        }
        const elementRegistry = this.modeler.get("elementRegistry");
        const modeling = this.modeler.get("modeling");
        const element = elementRegistry?.get(this.state.selectedElement.id);
        if (!element) {
            return;
        }
        modeling?.updateProperties(element, {name});
    }

    _upsertOptionList(listName, option, sortKey = "name") {
        const options = this.state.payload?.options;
        if (!options || !option?.id) {
            return;
        }
        const current = Array.isArray(options[listName]) ? options[listName] : [];
        const existingIndex = current.findIndex((item) => item.id === option.id);
        if (existingIndex >= 0) {
            current.splice(existingIndex, 1, option);
        } else {
            current.push(option);
        }
        current.sort((a, b) => String(a?.[sortKey] || "").localeCompare(String(b?.[sortKey] || "")));
        options[listName] = current;
    }

    createActionWindowOnTheFly() {
        if (!this._assertEditableVersion()) {
            return;
        }
        this.dialog.add(WorkflowStudioCreateActionWindowDialog, {
            defaultViewMode: "",
            defaultTarget: "",
            confirm: (values) => this._createActionWindowOnTheFly(values),
        });
    }

    async _createActionWindowOnTheFly(values = {}) {
        try {
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_create_action_window",
                [[this.state.versionId], values]
            );
            if (result?.payload) {
                this._setPayload(result.payload);
            }
            if (result?.action) {
                this._upsertOptionList("actions", result.action);
                await this.onTaskFieldChange("action_id", result.action.id);
            }
            this.notification.add(_t("Action window created."), {type: "success"});
            return true;
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to create action window.")),
                {type: "danger"}
            );
            return false;
        }
    }

    createEmailTemplateOnTheFly() {
        if (!this._assertEditableVersion()) {
            return;
        }
        this._createEmailTemplateOnTheFly({
            name: _t("New Email Template"),
            subject: _t("Request update"),
            body_html: "<div><p></p></div>",
        });
    }

    async _createEmailTemplateOnTheFly(values = {}) {
        try {
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_create_email_template",
                [[this.state.versionId], values]
            );
            if (result?.payload) {
                this._setPayload(result.payload);
            }
            if (result?.template) {
                this._upsertOptionList("templates", result.template);
                await this.onTaskFieldChange("email_template_external_id", result.template.id);
                await this.openEmailTemplateForm(result.template.id);
            }
            this.notification.add(_t("Email template created."), {type: "success"});
            return true;
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to create email template.")),
                {type: "danger"}
            );
            return false;
        }
    }

    async openEmailTemplateForm(templateId) {
        const id = Number(templateId || 0);
        if (!id) {
            return;
        }
        await this.action.doAction(
            {
                type: "ir.actions.act_window",
                name: _t("Email Template"),
                res_model: "mail.template",
                res_id: id,
                views: [[false, "form"]],
                target: "new",
            },
            {
                onClose: async () => {
                    await this._loadEditorPayload();
                },
            }
        );
    }

    createActivityTemplateOnTheFly() {
        if (!this._assertEditableVersion()) {
            return;
        }
        this.dialog.add(WorkflowStudioCreateActivityTemplateDialog, {
            confirm: (values) => this._createActivityTemplateOnTheFly(values),
        });
    }

    async _createActivityTemplateOnTheFly(values = {}) {
        try {
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_create_activity_template",
                [[this.state.versionId], values]
            );
            if (result?.payload) {
                this._setPayload(result.payload);
            }
            if (result?.template) {
                this._upsertOptionList("templates", result.template);
                await this.onTaskFieldChange("activity_message_template", result.template.id);
            }
            this.notification.add(_t("Activity message template created."), {type: "success"});
            return true;
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to create activity message template.")),
                {type: "danger"}
            );
            return false;
        }
    }

    createNotificationRecipientOnTheFly() {
        if (!this._assertEditableVersion()) {
            return;
        }
        this.dialog.add(WorkflowStudioCreateRecipientDialog, {
            confirm: (values) => this._createNotificationRecipientOnTheFly(values),
        });
    }

    async _createNotificationRecipientOnTheFly(values = {}) {
        if (!this.state.selectedTask) {
            return false;
        }
        try {
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_create_notification_recipient",
                [[this.state.versionId], values]
            );
            if (result?.payload) {
                this._setPayload(result.payload);
            }
            if (result?.user) {
                this._upsertOptionList("users", result.user);
                const selected = new Set(this.state.selectedTask.notification_recipient_ids || []);
                selected.add(result.user.id);
                await this.onTaskFieldChange("notification_recipient_ids", [...selected]);
            }
            if (result?.existing) {
                this.notification.add(_t("Recipient already existed and has been selected."), {
                    type: "info",
                });
            } else {
                this.notification.add(_t("Notification recipient created."), {type: "success"});
            }
            return true;
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to create notification recipient.")),
                {type: "danger"}
            );
            return false;
        }
    }

    getWorkflowActionOptionById(actionId) {
        const normalizedId = Number(actionId || 0);
        if (!normalizedId) {
            return null;
        }
        return this.workflowActionOptions.find((option) => Number(option.id || 0) === normalizedId) || null;
    }

    openNotificationChannelBrowserDialog() {
        if (!this.state.selectedTask) {
            return;
        }
        this.state.notificationChannelQuery = "";
        this.state.selectedNotificationChannelQuery = "";
        this.dialog.add(WorkflowStudioNotificationChannelBrowserDialog, {
            getNodeLabel: () => this.approvalGroupBrowserNodeLabel,
            getTotalCount: () => this.notificationChannelCatalogCount,
            getConfiguredCount: () => this.configuredNotificationChannelCount,
            getConfiguredQuery: () => this.state.selectedNotificationChannelQuery,
            setConfiguredQuery: (value) => {
                this.state.selectedNotificationChannelQuery = value || "";
            },
            getAvailableQuery: () => this.state.notificationChannelQuery,
            setAvailableQuery: (value) => {
                this.state.notificationChannelQuery = value || "";
            },
            getConfiguredRows: () => this.selectedTaskWorkflowActionOptions,
            getAvailableRows: () => this.availableChannelOptions,
            createChannel: (afterConfirm) => this.createWorkflowActionOnTheFly(afterConfirm),
            configureChannel: (channelId, afterConfirm) =>
                this.configureWorkflowActionOnTheFly(channelId, afterConfirm),
            addChannel: (channelId) => this.addChannelById(channelId),
            removeChannel: (channelId) => this.removeWorkflowActionFromTask(channelId),
        });
    }

    createWorkflowActionOnTheFly(afterConfirm = false) {
        if (!this._assertEditableVersion()) {
            return;
        }
        const onSaved = typeof afterConfirm === "function" ? afterConfirm : false;
        const isNotificationNode = this.showTaskNotificationSection;
        const allowedActionTypes = isNotificationNode
            ? ["email", "sms", "telegram", "webhook", "server_action"]
            : this.taskWorkflowActionAllowedTypes;
        const defaultActionType = this.isServiceTaskNode ? "server_action" : "workflow";
        this.dialog.add(WorkflowStudioWorkflowActionDialog, {
            title: isNotificationNode ? _t("Create Notification Channel") : _t("Create Workflow Action"),
            templateOptions: this.templateOptions,
            serverActionOptions: this.serverActionOptions,
            workflowActionTypeOptions: this.workflowActionTypeOptions,
            isNotificationChannel: isNotificationNode,
            requestModel: this.state.resModelName,
            requestFields: this.getRequestModelFieldHints(),
            workflowVersionId: Number(this.state.versionId || 0) || 0,
            workflowCategoryId: Number(this.state.categoryId || 0) || 0,
            workflowMetaTaskOptions: this.workflowTaskNodeOptions,
            domainPresetsByKey: this.domainPresetOptions,
            isDebugMode: !!this.env.debug,
            usersOptions: this.usersOptions,
            approvalGroupOptions: this.approvalGroupOptions,
            groupOptions: this.groupOptions,
            workflowTaskNodeOptions: this.workflowTaskNodeOptions,
            nodeUserTypeOptions: this.nodeUserTypeOptions,
            emailRecipientHeaderOptions: this.emailRecipientHeaderOptions,
            emailRecipientSourceOptions: this.emailRecipientSourceOptions,
            allowedActionTypes,
            initialAction: {
                action_type: isNotificationNode ? "email" : defaultActionType,
            },
            confirm: async (values) => {
                const saved = await this._createWorkflowActionOnTheFly(values);
                if (saved && onSaved) {
                    onSaved();
                }
                return saved;
            },
        });
    }

    configureWorkflowActionOnTheFly(actionId = false, afterConfirm = false) {
        if (!this._assertEditableVersion()) {
            return;
        }
        const onSaved = typeof afterConfirm === "function" ? afterConfirm : false;
        const fallbackActionId = actionId || this.state.selectedTask?.activity_type_ids?.[0];
        const workflowAction = this.getWorkflowActionOptionById(fallbackActionId);
        if (!workflowAction) {
            this.notification.add(_t("Select a workflow action first."), {type: "warning"});
            return;
        }
        const isNotificationNode = this.showTaskNotificationSection;
        const allowedActionTypes = isNotificationNode
            ? ["email", "sms", "telegram", "webhook", "server_action"]
            : this.taskWorkflowActionAllowedTypes;
        this.dialog.add(WorkflowStudioWorkflowActionDialog, {
            title: isNotificationNode ? _t("Configure Notification Channel") : _t("Configure Workflow Action"),
            templateOptions: this.templateOptions,
            serverActionOptions: this.serverActionOptions,
            workflowActionTypeOptions: this.workflowActionTypeOptions,
            isNotificationChannel: isNotificationNode,
            requestModel: this.state.resModelName,
            requestFields: this.getRequestModelFieldHints(),
            workflowVersionId: Number(this.state.versionId || 0) || 0,
            workflowCategoryId: Number(this.state.categoryId || 0) || 0,
            workflowMetaTaskOptions: this.workflowTaskNodeOptions,
            domainPresetsByKey: this.domainPresetOptions,
            isDebugMode: !!this.env.debug,
            usersOptions: this.usersOptions,
            approvalGroupOptions: this.approvalGroupOptions,
            groupOptions: this.groupOptions,
            workflowTaskNodeOptions: this.workflowTaskNodeOptions,
            nodeUserTypeOptions: this.nodeUserTypeOptions,
            emailRecipientHeaderOptions: this.emailRecipientHeaderOptions,
            emailRecipientSourceOptions: this.emailRecipientSourceOptions,
            allowedActionTypes,
            initialAction: workflowAction,
            confirm: async (values) => {
                const saved = await this._updateWorkflowActionOnTheFly(
                    workflowAction.id,
                    values,
                    this.state.selectedTask?.node_id || false
                );
                if (saved && onSaved) {
                    onSaved();
                }
                return saved;
            },
        });
    }

    async _createWorkflowActionOnTheFly(values = {}) {
        if (!this.state.selectedTask) {
            return false;
        }
        try {
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_create_workflow_action",
                [[this.state.versionId], values]
            );
            if (result?.payload) {
                this._setPayload(result.payload);
            }
            if (result?.workflow_action) {
                this._upsertOptionList("workflow_actions", result.workflow_action);
                const selectedIds = new Set(this.state.selectedTask.activity_type_ids || []);
                selectedIds.add(result.workflow_action.id);
                await this.onTaskFieldChange("activity_type_ids", [...selectedIds]);
            }
            this.notification.add(_t("Notification channel created."), {type: "success"});
            return true;
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to create notification channel.")),
                {type: "danger"}
            );
            return false;
        }
    }

    async _updateWorkflowActionOnTheFly(workflowActionId, values = {}, taskNodeId = false) {
        try {
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_update_workflow_action",
                [[this.state.versionId], workflowActionId, values, taskNodeId || false]
            );
            if (result?.payload) {
                this._setPayload(result.payload);
            }
            if (result?.workflow_action) {
                this._upsertOptionList("workflow_actions", result.workflow_action);
            }
            if (result?.isolated_from_shared) {
                this.notification.add(
                    _t("This action was duplicated for the selected node to avoid updating other nodes."),
                    {type: "info"}
                );
            }
            this.notification.add(_t("Notification channel updated."), {type: "success"});
            return true;
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to update notification channel.")),
                {type: "danger"}
            );
            return false;
        }
    }

    async removeWorkflowActionFromTask(workflowActionId) {
        if (!this.state.selectedTask) {
            return false;
        }
        const targetActionId = Number(workflowActionId || 0);
        if (!targetActionId) {
            return false;
        }
        const channel = this.getWorkflowActionOptionById(targetActionId);
        const channelLabel = channel?.name || _t("this notification channel");
        const confirmed = await this._confirmWithDialog({
            title: _t("Remove Notification Channel?"),
            body: sprintf(
                _t('Remove "%s" from this node? The channel will remain available, but this node will no longer use it for delivery.'),
                channelLabel
            ),
            confirmLabel: _t("Remove from Node"),
            cancelLabel: _t("Keep Channel"),
            confirmClass: "btn-danger",
        });
        if (!confirmed) {
            return false;
        }
        const selectedIds = (this.state.selectedTask.activity_type_ids || [])
            .filter((id) => Number(id || 0) !== targetActionId);
        await this.onTaskFieldChange("activity_type_ids", selectedIds);
        return true;
    }

    _approvalGroupDialogBaseProps(extraProps = {}) {
        return {
            approvalGroups: this.approvalGroupOptions,
            approvalLinkRows: this.state.approvalLinkRows || [],
            usersOptions: this.usersOptions,
            departmentOptions: this.departmentOptions,
            requestModel: this.state.resModelName || "",
            requestFields: this.getRequestModelFieldHints(120),
            domainPresetsByKey: this.domainPresetOptions,
            isDebugMode: !!this.env.debug,
            workflowVersionId: Number(this.state.versionId || 0) || 0,
            workflowCategoryId: Number(this.state.categoryId || 0) || 0,
            ...extraProps,
        };
    }

    _defaultApprovalGroupLinkConfig() {
        return {
            sequence: this._nextApprovalLinkSequence(),
            user_domain: "",
            domain: "",
            note: "",
        };
    }

    async searchApprovalGroupOptions(query = "") {
        const normalizedQuery = this._normalizeApprovalGroupSearch(query);
        if (!normalizedQuery || !this.state.versionId) {
            return this.approvalGroupOptions;
        }
        try {
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_search_approval_groups",
                [[this.state.versionId], query]
            );
            if (Array.isArray(result?.rows)) {
                return result.rows;
            }
        } catch {
            // Fall back to the loaded metadata if the RPC is unavailable.
        }
        return this.approvalGroupOptions.filter((groupOption) => {
            const haystack = [
                groupOption?.display_path || "",
                groupOption?.name || "",
                groupOption?.department_name || "",
                ...(groupOption?.user_names || []),
            ]
                .join(" ")
                .toLowerCase();
            return haystack.includes(normalizedQuery);
        });
    }

    openApprovalGroupCreateDialog(targetRowIndex = false, afterConfirm = false, extraDialogProps = {}) {
        if (!this._assertEditableVersion()) {
            return;
        }
        const {
            initialName = "",
            onCreated = false,
        } = extraDialogProps || {};
        const linkConfig =
            Number.isInteger(targetRowIndex) && targetRowIndex >= 0
                ? (this.state.approvalLinkRows?.[targetRowIndex] || undefined)
                : undefined;
        this.dialog.add(WorkflowStudioApprovalGroupDialog, this._approvalGroupDialogBaseProps({
            mode: "create",
            initialName,
            ...(linkConfig !== undefined ? {linkConfig} : {}),
            confirm: async (values) => {
                const created = await this._createApprovalGroupOnTheFly(values, targetRowIndex, {onCreated});
                if (created && afterConfirm) {
                    afterConfirm();
                }
                return created;
            },
        }));
    }

    openApprovalGroupCreateAndLinkDialog(afterConfirm = false) {
        this.openApprovalGroupLinkDialog({afterConfirm});
    }

    openApprovalGroupLinkDialog({
        selectedGroupId = false,
        originGroupId = false,
        allowGroupSelection = true,
        linkConfig = false,
        afterConfirm = false,
    } = {}) {
        if (!this._assertEditableVersion() || !this.state.selectedTask) {
            return;
        }
        const initialLinkConfig = linkConfig || this._defaultApprovalGroupLinkConfig();
        this.dialog.add(WorkflowStudioApprovalGroupLinkDialog, this._approvalGroupDialogBaseProps({
            selectedGroupId: Number(selectedGroupId || 0) || 0,
            originGroupId: Number(originGroupId || 0) || 0,
            allowGroupSelection,
            linkConfig: initialLinkConfig,
            linkContextLabel: this.approvalGroupBrowserNodeLabel,
            searchApprovalGroups: (query) => this.searchApprovalGroupOptions(query),
            requestCreateGroup: ({initialName = "", afterCreate = false} = {}) => {
                this.openApprovalGroupCreateDialog(false, false, {
                    initialName,
                    onCreated: afterCreate,
                });
            },
            requestEditGroup: (groupId, {afterUpdate = false} = {}) => {
                this.openApprovalGroupEditDialogById(groupId, false, {afterUpdate});
            },
            confirm: async ({selected_group_id, origin_group_id, link_values}) => {
                const saved = await this.saveApprovalGroupLinkFromDialog(selected_group_id, link_values, {
                    originGroupId: origin_group_id,
                });
                if (saved && afterConfirm) {
                    afterConfirm();
                }
                return saved;
            },
        }));
    }

    _openApprovalGroupEditDialog(group, {
        targetRowIndex = false,
        includeLinkConfig = false,
        afterConfirm = false,
        afterUpdate = false,
    } = {}) {
        if (!this._assertEditableVersion()) {
            return;
        }
        if (!group) {
            this.notification.add(_t("Approval group was not found. Refresh metadata and try again."), {
                type: "warning",
            });
            return;
        }
        const linkConfig =
            includeLinkConfig && Number.isInteger(targetRowIndex) && targetRowIndex >= 0
                ? (this.state.approvalLinkRows?.[targetRowIndex] || undefined)
                : undefined;
        this.dialog.add(WorkflowStudioApprovalGroupDialog, this._approvalGroupDialogBaseProps({
            mode: "edit",
            initialGroup: group,
            ...(linkConfig !== undefined ? {linkConfig, linkContextLabel: this.approvalGroupBrowserNodeLabel} : {}),
            confirm: async (values) => {
                const updated = await this._updateApprovalGroupOnTheFly(
                    group.id,
                    values,
                    includeLinkConfig ? targetRowIndex : false,
                    {onUpdated: afterUpdate}
                );
                if (updated && afterConfirm) {
                    afterConfirm();
                }
                return updated;
            },
        }));
    }

    openApprovalGroupConfigDialog(targetRowIndex, afterConfirm = false) {
        if (!this._assertEditableVersion()) {
            return;
        }
        const row = this.state.approvalLinkRows?.[targetRowIndex];
        const groupId = Number(row?.approval_group_ref?.id || row?.approval_group_id || 0);
        if (!groupId) {
            this.notification.add(_t("Select an approval group first."), {type: "warning"});
            return;
        }
        this.openApprovalGroupLinkDialog({
            selectedGroupId: groupId,
            originGroupId: groupId,
            allowGroupSelection: true,
            linkConfig: row,
            afterConfirm,
        });
    }

    openApprovalGroupEditDialogById(groupId, afterConfirm = false, extraOptions = {}) {
        const group = this.getApprovalGroupById(groupId);
        this._openApprovalGroupEditDialog(group, {afterConfirm, ...(extraOptions || {})});
    }

    openApprovalGroupRuleSettingsByGroupId(groupId, afterConfirm = false) {
        const rowIndex = this.findApprovalLinkRowIndexByGroupId(groupId);
        if (rowIndex < 0) {
            this.notification.add(_t("This group is not linked to the selected node."), {type: "warning"});
            return;
        }
        this.openApprovalGroupConfigDialog(rowIndex, afterConfirm);
    }

    resetApprovalGroupCatalogState() {
        this.state.approvalGroupCatalogQuery = "";
        this.state.approvalGroupCatalogRows = [];
        this.state.approvalGroupCatalogTotal = 0;
        this.state.approvalGroupCatalogTotalGroups = this.approvalGroupOptions.length;
        this.state.approvalGroupCatalogLinkedCount = this.linkedApprovalGroupCount;
        this.state.approvalGroupCatalogHasMore = false;
        this.state.approvalGroupCatalogPending = false;
        this.state.approvalGroupCatalogMode = "all";
        this.state.approvalGroupCatalogRoutingFilter = "all";
        this._clearApprovalGroupCatalogScheduledReload();
        this._approvalGroupCatalogSearchSequence += 1;
    }

    setApprovalGroupCatalogQuery(query = "") {
        this.state.approvalGroupCatalogQuery = query;
        return this._scheduleApprovalGroupCatalogBrowserReload({immediate: false});
    }

    setApprovalGroupCatalogMode(mode = "all") {
        this.state.approvalGroupCatalogMode = mode || "all";
        return this.refreshApprovalGroupCatalogBrowser({immediate: true});
    }

    setApprovalGroupCatalogRoutingFilter(filterValue = "all") {
        this.state.approvalGroupCatalogRoutingFilter = filterValue || "all";
        return this.refreshApprovalGroupCatalogBrowser({immediate: true});
    }

    _scheduleApprovalGroupCatalogBrowserReload({immediate = false, append = false} = {}) {
        this._clearApprovalGroupCatalogScheduledReload();
        this.state.approvalGroupCatalogPending = true;
        const runReload = async () => await this._fetchApprovalGroupCatalogBrowserRows({append});
        if (immediate) {
            return runReload();
        }
        return new Promise((resolve) => {
            this._approvalGroupCatalogScheduledResolver = resolve;
            this._approvalGroupCatalogSearchTimer = setTimeout(async () => {
                this._approvalGroupCatalogSearchTimer = null;
                this._approvalGroupCatalogScheduledResolver = null;
                resolve(await runReload());
            }, 180);
        });
    }

    refreshApprovalGroupCatalogBrowser({immediate = true, append = false} = {}) {
        return this._scheduleApprovalGroupCatalogBrowserReload({immediate, append});
    }

    openApprovalGroupBrowserDialog() {
        if (!this.state.selectedTask) {
            return;
        }
        this.resetApprovalGroupCatalogState();
        this._applyApprovalGroupCatalogBrowserResult(
            this._buildLocalApprovalGroupCatalogBrowserResult({append: false}),
            {append: false}
        );
        this.dialog.add(WorkflowStudioApprovalGroupBrowserDialog, {
            getNodeLabel: () => this.approvalGroupBrowserNodeLabel,
            getTotalCount: () => this.state.approvalGroupCatalogTotalGroups || this.approvalGroupOptions.length,
            getLinkedCount: () => this.state.approvalGroupCatalogLinkedCount || this.linkedApprovalGroupCount,
            getIsLoading: () => this.state.approvalGroupCatalogPending,
            getQuery: () => this.state.approvalGroupCatalogQuery,
            setQuery: (value) => this.setApprovalGroupCatalogQuery(value),
            resetFilters: () => {
                this.resetApprovalGroupCatalogState();
                return this.refreshApprovalGroupCatalogBrowser({immediate: true});
            },
            getMode: () => this.state.approvalGroupCatalogMode,
            setMode: (value) => this.setApprovalGroupCatalogMode(value),
            modeOptions: this.approvalGroupCatalogModeOptions,
            getRoutingFilter: () => this.state.approvalGroupCatalogRoutingFilter,
            setRoutingFilter: (value) => this.setApprovalGroupCatalogRoutingFilter(value),
            routingFilterOptions: this.approvalGroupCatalogRoutingFilterOptions,
            getRows: () => this.approvalGroupCatalogRows,
            hasMore: () => this.hasMoreApprovalGroupCatalogRows,
            loadMore: () => this.loadMoreApprovalGroupCatalogRows(),
            reloadRows: (options = {}) => this.refreshApprovalGroupCatalogBrowser(options),
            createGroup: (afterConfirm) => this.openApprovalGroupCreateAndLinkDialog(afterConfirm),
            editGroup: (groupId, afterConfirm) => this.openApprovalGroupEditDialogById(groupId, afterConfirm),
            editRuleSettings: (groupId, afterConfirm) => this.openApprovalGroupRuleSettingsByGroupId(groupId, afterConfirm),
            linkGroup: (groupId) => this.linkApprovalGroupFromCatalog(groupId),
            linkAndConfigureGroup: (groupId, afterConfirm) => this.linkApprovalGroupAndConfigureFromCatalog(groupId, afterConfirm),
            unlinkGroup: (groupId) => this.unlinkApprovalGroupFromCatalog(groupId),
        });
        void this.refreshApprovalGroupCatalogBrowser({immediate: true});
    }

    async _createApprovalGroupRecord(values = {}) {
        const payload = {...(values || {})};
        delete payload.link_values;
        const result = await this.orm.call(
            "workflow.approval.category.version",
            "workflow_studio_create_approval_group",
            [[this.state.versionId], payload]
        );
        if (result?.payload) {
            this._setPayload(result.payload);
        }
        if (result?.approval_group) {
            this._upsertOptionList("approval_groups", result.approval_group, "display_path");
        }
        void this.refreshApprovalGroupCatalogBrowser({immediate: true});
        return result?.approval_group || false;
    }

    async _createApprovalGroupOnTheFly(values = {}, targetRowIndex = false, {onCreated = false} = {}) {
        const payload = {...(values || {})};
        const linkValues = payload.link_values || false;
        try {
            const createdGroup = await this._createApprovalGroupRecord(payload);
            if (!createdGroup) {
                return false;
            }
            if (Number.isInteger(targetRowIndex) && targetRowIndex >= 0) {
                const linked = await this._mutateApprovalLinksAndPersist(
                    () => {
                        this.onApprovalLinkGroupChange(targetRowIndex, createdGroup.id);
                        if (linkValues) {
                            this.onApprovalLinkTextChange(
                                targetRowIndex,
                                "sequence",
                                Number(linkValues.sequence || 10) || 10
                            );
                            this.onApprovalLinkTextChange(
                                targetRowIndex,
                                "user_domain",
                                linkValues.user_domain || ""
                            );
                            this.onApprovalLinkTextChange(
                                targetRowIndex,
                                "domain",
                                linkValues.domain || ""
                            );
                            this.onApprovalLinkTextChange(
                                targetRowIndex,
                                "note",
                                linkValues.note || ""
                            );
                        }
                    },
                    {silentSuccess: true}
                );
                if (!linked) {
                    return false;
                }
            }
            if (onCreated) {
                onCreated(createdGroup);
            }
            this.notification.add(
                Number.isInteger(targetRowIndex) && targetRowIndex >= 0
                    ? _t("Approval group created and linked to this node.")
                    : _t("Approval group created."),
                {type: "success"}
            );
            return true;
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to create approval group.")),
                {type: "danger"}
            );
            return false;
        }
    }

    async _createApprovalGroupAndLinkToCurrentNode(values = {}) {
        if (!this.state.selectedTask) {
            return false;
        }
        const payload = {...(values || {})};
        const linkValues = payload.link_values || this._defaultApprovalGroupLinkConfig();
        try {
            const createdGroup = await this._createApprovalGroupRecord(payload);
            if (createdGroup) {
                const linked = await this._mutateApprovalLinksAndPersist(
                    () => {
                        this.addApprovalLinkRow(createdGroup.id);
                        const rowIndex = this.findApprovalLinkRowIndexByGroupId(createdGroup.id);
                        if (rowIndex < 0) {
                            return;
                        }
                        this.onApprovalLinkTextChange(
                            rowIndex,
                            "sequence",
                            Number(linkValues.sequence || this.state.approvalLinkRows?.[rowIndex]?.sequence || 10) || 10
                        );
                        this.onApprovalLinkTextChange(rowIndex, "user_domain", linkValues.user_domain || "");
                        this.onApprovalLinkTextChange(rowIndex, "domain", linkValues.domain || "");
                        this.onApprovalLinkTextChange(rowIndex, "note", linkValues.note || "");
                    },
                    {silentSuccess: true}
                );
                if (!linked) {
                    return false;
                }
            }
            this.notification.add(_t("Approval group created, linked, and configured for this node."), {
                type: "success",
            });
            return true;
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to create and link approval group.")),
                {type: "danger"}
            );
            return false;
        }
    }

    async saveApprovalGroupLinkFromDialog(approvalGroupId, linkValues = {}, options = {}) {
        if (!this.state.selectedTask) {
            return false;
        }
        if (!this._assertEditableVersion()) {
            return false;
        }
        const normalizedGroupId = Number(approvalGroupId || 0);
        if (!normalizedGroupId) {
            this.notification.add(_t("Select a valid approval group."), {type: "warning"});
            return false;
        }
        const normalizedOriginGroupId = Number(options?.originGroupId || 0) || 0;
        const existingRowIndex = this.findApprovalLinkRowIndexByGroupId(normalizedGroupId);
        const originRowIndex = normalizedOriginGroupId
            ? this.findApprovalLinkRowIndexByGroupId(normalizedOriginGroupId)
            : -1;
        const isReplacingExistingLink =
            originRowIndex >= 0
            && normalizedOriginGroupId !== normalizedGroupId;
        if (isReplacingExistingLink && existingRowIndex >= 0) {
            this.notification.add(
                _t("This approval group is already linked to the selected node. Open its Rule Settings directly or choose another available group."),
                {type: "warning"}
            );
            return false;
        }
        const successMessage = existingRowIndex >= 0
            ? _t("Approval group rule settings updated.")
            : (isReplacingExistingLink
                ? _t("Approval group link updated.")
                : _t("Approval group linked and configured for this node."));
        return await this._mutateApprovalLinksAndPersist(
            () => {
                if (isReplacingExistingLink) {
                    this.onApprovalLinkGroupChange(originRowIndex, normalizedGroupId);
                } else if (existingRowIndex < 0) {
                    this.addApprovalLinkRow(normalizedGroupId);
                }
                const rowIndex = isReplacingExistingLink
                    ? originRowIndex
                    : existingRowIndex >= 0
                    ? existingRowIndex
                    : this.findApprovalLinkRowIndexByGroupId(normalizedGroupId);
                if (rowIndex < 0) {
                    return;
                }
                this.onApprovalLinkGroupChange(rowIndex, normalizedGroupId);
                this.onApprovalLinkTextChange(
                    rowIndex,
                    "sequence",
                    Number(linkValues.sequence || this.state.approvalLinkRows?.[rowIndex]?.sequence || 10) || 10
                );
                this.onApprovalLinkTextChange(rowIndex, "user_domain", linkValues.user_domain || "");
                this.onApprovalLinkTextChange(rowIndex, "domain", linkValues.domain || "");
                this.onApprovalLinkTextChange(rowIndex, "note", linkValues.note || "");
            },
            successMessage
        );
    }

    async _updateApprovalGroupOnTheFly(approvalGroupId, values = {}, targetRowIndex = false, {onUpdated = false} = {}) {
        const payload = {...(values || {})};
        const linkValues = payload.link_values || false;
        delete payload.link_values;
        try {
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_update_approval_group",
                [[this.state.versionId], approvalGroupId, payload]
            );
            if (result?.payload) {
                this._setPayload(result.payload);
            }
            if (result?.approval_group) {
                this._upsertOptionList("approval_groups", result.approval_group, "display_path");
                if (Number.isInteger(targetRowIndex) && targetRowIndex >= 0) {
                    this.onApprovalLinkGroupChange(targetRowIndex, result.approval_group.id);
                    if (linkValues) {
                        const saved = await this._mutateApprovalLinksAndPersist(
                            () => {
                                this.onApprovalLinkTextChange(
                                    targetRowIndex,
                                    "sequence",
                                    Number(linkValues.sequence || 10) || 10
                                );
                                this.onApprovalLinkTextChange(
                                    targetRowIndex,
                                    "user_domain",
                                    linkValues.user_domain || ""
                                );
                                this.onApprovalLinkTextChange(
                                    targetRowIndex,
                                    "domain",
                                    linkValues.domain || ""
                                );
                                this.onApprovalLinkTextChange(
                                    targetRowIndex,
                                    "note",
                                    linkValues.note || ""
                                );
                            },
                            {silentSuccess: true}
                        );
                        if (!saved) {
                            return false;
                        }
                    }
                }
            }
            if (result?.approval_group && onUpdated) {
                onUpdated(result.approval_group);
            }
            this.notification.add(_t("Approval group updated."), {type: "success"});
            void this.refreshApprovalGroupCatalogBrowser({immediate: true});
            return true;
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to update approval group.")),
                {type: "danger"}
            );
            return false;
        }
    }

    async onTaskFieldChange(fieldName, rawValue) {
        if (!this.state.selectedTask) {
            return;
        }
        if (!this._assertEditableVersion()) {
            return;
        }
        const value = rawValue ?? false;
        try {
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_write_meta_task",
                [[this.state.versionId], this.state.selectedTask.node_id, {[fieldName]: value}]
            );
            if (result?.warnings?.length) {
                this.notification.add(result.warnings.join("\n"), {type: "warning"});
            }
            const task = result ? {...result} : result;
            if (task && Object.prototype.hasOwnProperty.call(task, "warnings")) {
                delete task.warnings;
            }
            this._updateLocalTask(task);
            if (fieldName === "name") {
                this._updateDiagramName(value || "");
            }
            this._refreshSelectionMetadata();
        } catch {
            this.notification.add(_t("Failed to update task metadata."), {type: "danger"});
        }
    }

    async onTaskElementTypeChange(event) {
        await this.onTaskFieldChange("element", event.target.value || false);
    }

    async onTaskServiceBehaviorChange(event) {
        await this.onTaskFieldChange("service_behavior", event.target.value || "router");
    }

    async onTaskActionWindowChange(event) {
        const value = event.target.value ? toPositiveInt(event.target.value) || false : false;
        await this.onTaskFieldChange("action_id", value);
    }

    async onTaskEmailTemplateChange(event) {
        const value = event.target.value ? toPositiveInt(event.target.value) || false : false;
        await this.onTaskFieldChange("email_template_external_id", value);
    }

    async onActionMessageNotificationTaskFieldChange(fieldName, rawValue) {
        const task = this.selectedActionMessageNotificationTask;
        if (!task) {
            return;
        }
        if (!this._assertEditableVersion()) {
            return;
        }
        const value = rawValue ?? false;
        try {
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_write_meta_task",
                [[this.state.versionId], task.node_id, {[fieldName]: value}]
            );
            if (result?.warnings?.length) {
                this.notification.add(result.warnings.join("\n"), {type: "warning"});
            }
            const taskData = result ? {...result} : result;
            if (taskData && Object.prototype.hasOwnProperty.call(taskData, "warnings")) {
                delete taskData.warnings;
            }
            this._updateLocalTask(taskData, false);
            this._refreshSelectionMetadata();
        } catch {
            this.notification.add(_t("Failed to update message notification metadata."), {type: "danger"});
        }
    }

    async onActionMessageNotificationEmailTemplateChange(event) {
        const value = event.target.value ? toPositiveInt(event.target.value) || false : false;
        await this.onActionMessageNotificationTaskFieldChange("email_template_external_id", value);
    }

    async onTaskActivityTypeChange(event) {
        await this.onTaskFieldChange("activity_type", event.target.value || false);
    }

    async onTaskActivityMessageTemplateChange(event) {
        const value = event.target.value ? toPositiveInt(event.target.value) || false : false;
        await this.onTaskFieldChange("activity_message_template", value);
    }

    async onTaskNotificationRecipientsChange(event) {
        await this.onTaskMany2ManyFieldChange("notification_recipient_ids", event);
    }

    async onTaskWorkflowActionsChange(event) {
        await this.onTaskMany2ManyFieldChange("activity_type_ids", event);
    }


    async onTaskMany2ManyFieldChange(fieldName, event) {
        const values = [...event.target.selectedOptions]
            .map((option) => toPositiveInt(option.value))
            .filter((value) => value);
        const currentValues = (this.state.selectedTask?.[fieldName] || [])
            .map((value) => toPositiveInt(value))
            .filter((value) => value);
        const sortedValues = [...new Set(values)].sort((a, b) => a - b);
        const sortedCurrentValues = [...new Set(currentValues)].sort((a, b) => a - b);
        const unchanged = sortedValues.length === sortedCurrentValues.length
            && sortedValues.every((value, index) => value === sortedCurrentValues[index]);
        if (unchanged) {
            return;
        }
        await this.onTaskFieldChange(fieldName, values);
    }

    async onTaskDomainPresetChange(fieldName, event) {
        const domain = event?.target?.value || "";
        if (!domain) {
            return;
        }
        await this.onTaskFieldChange(fieldName, domain);
        event.target.value = "";
    }

    async onActionDialogTypeChange(event) {
        await this.onActionFieldChange("dialog_type", event.target.value);
    }

    async onActionIntegerFieldChange(fieldName, event) {
        const value = Math.max(1, parseInt(event?.target?.value || "1", 10) || 1);
        await this.onActionFieldChange(fieldName, value);
    }

    async _writeSelectedActionValues(values) {
        if (!this.state.selectedAction) {
            return false;
        }
        if (!this._assertEditableVersion()) {
            return false;
        }
        try {
            const action = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_write_meta_action",
                [
                    [this.state.versionId],
                    this.state.selectedAction.source_id,
                    this.state.selectedAction.target_id,
                    values,
                ]
            );
            this._updateLocalAction(action);
            this._refreshSelectionMetadata();
            return true;
        } catch {
            this.notification.add(_t("Failed to update transition metadata."), {type: "danger"});
            return false;
        }
    }

    async onActionFieldChange(fieldName, rawValue) {
        if (!this.state.selectedAction) {
            return;
        }
        if (!this._assertEditableVersion()) {
            return;
        }
        const value = rawValue ?? false;
        try {
            const action = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_write_meta_action",
                [
                    [this.state.versionId],
                    this.state.selectedAction.source_id,
                    this.state.selectedAction.target_id,
                    {[fieldName]: value},
                ]
            );
            this._updateLocalAction(action);
            if (fieldName === "attr_label") {
                this._updateDiagramName(value || "");
            }
            this._refreshSelectionMetadata();
        } catch {
            this.notification.add(_t("Failed to update transition metadata."), {type: "danger"});
        }
    }

    async onActionDefaultFlowChange(event) {
        if (!this.showConditionalDefaultFlowSection) {
            return;
        }
        if (!this._assertEditableVersion()) {
            if (event?.target) {
                event.target.checked = this.isSelectedActionDefaultFlow;
            }
            return;
        }
        const flowElement = this.selectedActionElement;
        const sourceElement = this.selectedActionSourceElement;
        if (!flowElement || !sourceElement) {
            this.notification.add(_t("Unable to update the BPMN default path for this transition."), {
                type: "danger",
            });
            if (event?.target) {
                event.target.checked = this.isSelectedActionDefaultFlow;
            }
            return;
        }
        try {
            const currentXml = await this._getCurrentXml();
            const doc = parseXmlDocument(currentXml);
            const definitionsNode = findBpmnDefinitionsNode(doc);
            if (!definitionsNode) {
                throw new Error("No BPMN definitions found");
            }
            const sourceNode = Array.from(definitionsNode.getElementsByTagName("*")).find(
                (node) => node.namespaceURI === BPMN_MODEL_NS && node.getAttribute("id") === sourceElement.id
            );
            if (!sourceNode) {
                throw new Error("Conditional source node not found");
            }
            if (event?.target?.checked) {
                sourceNode.setAttribute("default", flowElement.id);
            } else {
                sourceNode.removeAttribute("default");
            }
            const updatedXml = new XMLSerializer().serializeToString(definitionsNode);
            await this.modeler.importXML(updatedXml);
            this.state.currentXml = updatedXml;
            this.state.isDirty = updatedXml !== this.state.lastSavedXml;
            const selectedFlow = this.modeler.get("elementRegistry")?.get(flowElement.id);
            if (selectedFlow) {
                this.modeler.get("selection")?.select(selectedFlow);
            }
            this._refreshSelectionMetadata();
        } catch {
            this.notification.add(_t("Failed to set the BPMN default path."), {type: "danger"});
            if (event?.target) {
                event.target.checked = this.isSelectedActionDefaultFlow;
            }
        }
    }

    async onActionDomainPresetChange(fieldName, event) {
        const domain = event?.target?.value || "";
        if (!domain) {
            return;
        }
        await this.onActionFieldChange(fieldName, domain);
        event.target.value = "";
    }

    openTaskDomainDialog(fieldName) {
        if (!this.state.selectedTask) {
            return;
        }
        const domainModelMap = {
            approval_group_domain: "res.users",
            notification_recipient_domain: "res.users",
            notification_recipient_filter_domain: "res.users",
            assignment_user_domain: "res.users",
        };
        const model = domainModelMap[fieldName] || this.state.resModelName;
        if (!model) {
            this.notification.add(_t("No target model configured for this domain field."), {
                type: "warning",
            });
            return;
        }
        const isUserDomain = model === "res.users";
        const isRoutingDomainField = [
            "approval_group_domain",
            "notification_recipient_domain",
            "notification_recipient_filter_domain",
            "assignment_user_domain",
        ].includes(fieldName);
        const titleMap = {
            approval_group_domain: _t("Approval Group Domain"),
            notification_recipient_domain: _t("Notification Recipient Domain"),
            notification_recipient_filter_domain: _t("Notification Recipient Advanced Filter"),
            assignment_user_domain: _t("Assignment User Domain"),
            automation_condition_domain: _t("Automation Condition Domain"),
        };
        const presetKey = isRoutingDomainField
            ? (isUserDomain ? "routing_user_assignment" : "routing_request_scope")
            : (isUserDomain ? "user_assignment" : "request_scope");
        const initialDomain = fieldName === "notification_recipient_filter_domain"
            ? (this.state.selectedTask.notification_recipient_filter_domain
                || this.state.selectedTask.notification_recipient_domain
                || (isRoutingDomainField ? "" : "[]"))
            : (this.state.selectedTask[fieldName] || (isRoutingDomainField ? "" : "[]"));
        this.dialog.add(WorkflowStudioDomainDialog, {
            resModel: model,
            requestModel: this.state.resModelName || model,
            requestFields: this.getRequestModelFieldHints(),
            workflowVersionId: Number(this.state.versionId || 0) || 0,
            workflowCategoryId: Number(this.state.categoryId || 0) || 0,
            domain: initialDomain,
            title: titleMap[fieldName] || _t("Task Domain"),
            contextType: isRoutingDomainField
                ? (isUserDomain ? "assignment_users_routing" : "request_scope_routing")
                : (isUserDomain ? "assignment_users" : "request_scope"),
            presets: this.getDomainPresets(presetKey),
            isDebugMode: !!this.env.debug,
            allowBlankDomain: isRoutingDomainField,
            onConfirm: (domain) => this.onTaskFieldChange(fieldName, domain),
        });
    }

    openActionDomainDialog(fieldName) {
        if (!this.state.selectedAction) {
            return;
        }
        if (!this.state.resModelName) {
            this.notification.add(_t("No request model configured on this workflow version."), {
                type: "warning",
            });
            return;
        }
        const contextTypeByField = {
            twofa_condition_domain: "twofa",
            invisible_domain: "request_scope",
            domain: "request_scope",
            require_reason_domain: "request_scope",
            comment_required_domain: "request_scope",
            require_attachment_domain: "request_scope",
            auto_action_condition: "request_scope",
            business_actor_user_domain: "assignment_users_routing",
        };
        const contextType = contextTypeByField[fieldName] || "generic";
        let title = _t("Action Domain");
        if (fieldName === "twofa_condition_domain") {
            title = _t("2FA Condition Domain");
        } else if (fieldName === "invisible_domain") {
            title = _t("Button Visibility Domain");
        } else if (fieldName === "domain") {
            title = _t("Runtime Domain Guard");
        } else if (fieldName === "require_reason_domain") {
            title = _t("Require Reason Domain");
        } else if (fieldName === "comment_required_domain") {
            title = _t("Comment Required Domain");
        } else if (fieldName === "require_attachment_domain") {
            title = _t("Require Attachment Domain");
        } else if (fieldName === "auto_action_condition") {
            title = _t("Condition Domain");
        } else if (fieldName === "business_actor_user_domain") {
            title = _t("Business Action User Domain");
        }
        const presetKey =
            fieldName === "invisible_domain" || fieldName === "domain" || fieldName === "require_reason_domain" || fieldName === "comment_required_domain" || fieldName === "require_attachment_domain" || fieldName === "auto_action_condition"
                ? "action_visibility"
                : "generic";
        const helpTextByField = {
            invisible_domain: _t(
                "Show this button only when this domain matches current request data and current actor symbols."
            ),
            domain: _t(
                "Server-side action guard. A mismatch blocks the action before approval, notification, or routing."
            ),
            require_reason_domain: _t(
                "Optional request domain. The reason input is required only when this domain matches. If it does not match, the reason box is shown but optional."
            ),
            comment_required_domain: _t(
                "Optional request domain. The comment input is required only when this domain matches. If it does not match, the comment box is shown but optional."
            ),
            require_attachment_domain: _t(
                "Optional request domain. Attachments are required only when this domain matches. If it does not match, the attachment box is shown but optional."
            ),
            auto_action_condition: _t(
                "Optional domain evaluated at runtime. The auto-transition only fires when this domain matches the current request record."
            ),
            business_actor_user_domain: _t(
                "Optional res.users domain resolved once when this task becomes active. It grants exact action assignments, not approval decisions."
            ),
        };
        const isBusinessActorUserDomain = fieldName === "business_actor_user_domain";
        this.dialog.add(WorkflowStudioDomainDialog, {
            resModel: isBusinessActorUserDomain ? "res.users" : this.state.resModelName,
            requestModel: this.state.resModelName,
            requestFields: this.getRequestModelFieldHints(),
            workflowVersionId: Number(this.state.versionId || 0) || 0,
            workflowCategoryId: Number(this.state.categoryId || 0) || 0,
            domain: this.state.selectedAction[fieldName] || (isBusinessActorUserDomain ? "" : "[]"),
            title,
            contextType,
            presets: this.getDomainPresets(
                isBusinessActorUserDomain ? "assignment_users" : presetKey
            ),
            helpText: helpTextByField[fieldName],
            isDebugMode: !!this.env.debug,
            allowBlankDomain: isBusinessActorUserDomain,
            onConfirm: (domain) => this.onActionFieldChange(fieldName, domain),
        });
    }

    _metaFieldShortLabel(fieldKey) {
        const option = (this.fieldsOptions || []).find((f) => f.key === fieldKey);
        if (!option) {
            return fieldKey || _t("Unknown Field");
        }
        const name = option.display_name || "";
        const paren = name.indexOf("(");
        return paren > 0 ? name.slice(0, paren).trim() : name;
    }

    _metaFieldFullLabel(fieldKey) {
        const option = (this.fieldsOptions || []).find((f) => f.key === fieldKey);
        return option?.display_name || fieldKey || _t("Unknown Field");
    }

    _metaFieldSearchText(row = {}) {
        const option = (this.fieldsOptions || []).find((field) => field.key === row.field_key) || {};
        return [
            row.field_key,
            option.display_name,
            option.field_description,
            option.name,
            option.model,
            option.ttype,
            option.relation,
            ...this._metaFieldTypes(row).map((type) => this._metaFieldTypeLabel(type)),
        ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();
    }

    get filteredMetaFieldRows() {
        const query = `${this.state.metaFieldSearchQuery || ""}`.trim().toLowerCase();
        return (this.state.metaFieldRows || [])
            .map((row, index) => ({row, index}))
            .filter(({row}) => !query || this._metaFieldSearchText(row).includes(query));
    }

    get usesMetaFieldManagerDialog() {
        return (this.state.metaFieldRows || []).length > META_FIELD_INLINE_LIMIT;
    }

    getMetaFieldManagerRows() {
        return (this.state.metaFieldRows || []).map((row, index) => ({
            index,
            key: row.key || row.field_key || `meta_field_${index}`,
            label: this._metaFieldShortLabel(row.field_key),
            title: this._metaFieldFullLabel(row.field_key),
            types: this._metaFieldTypes(row).map((type) => ({
                key: type,
                label: this._metaFieldTypeLabel(type),
            })),
            actionCount: (row.activity_action_keys || []).length,
            hasDomain: this._metaFieldHasDomain(row),
            searchText: this._metaFieldSearchText(row),
        }));
    }

    onMetaFieldSearchInput(ev) {
        this.state.metaFieldSearchQuery = ev.target.value || "";
    }

    clearMetaFieldSearch() {
        this.state.metaFieldSearchQuery = "";
    }

    _taskMetaFieldSourceLabel(task = {}) {
        const name = task.name || task.node_name || task.node_id || _t("Unnamed Node");
        return task.node_id && task.node_id !== name ? `${name} (${task.node_id})` : name;
    }

    get metaFieldCopySourceOptions() {
        const selectedNodeId = this.state.selectedTask?.node_id || "";
        const tasks = this.state.payload?.meta?.tasks || [];
        return tasks
            .filter((task) => task?.node_id && task.node_id !== selectedNodeId)
            .map((task) => {
                const rows = this._metaFieldRowsForTask(task.node_id);
                if (!rows.length) {
                    return null;
                }
                return {
                    nodeId: task.node_id,
                    label: this._taskMetaFieldSourceLabel(task),
                    rows,
                    actions: this._taskOutgoingActions(task.node_id),
                };
            })
            .filter(Boolean)
            .sort((left, right) => left.label.localeCompare(right.label));
    }

    _actionCopyMatchKey(action = {}) {
        return String(
            action.attr_label
            || action.name
            || action.target_name
            || action.target_id
            || action.action_key
            || ""
        )
            .trim()
            .toLowerCase();
    }

    _actionKeyMapForMetaCopy(sourceOption = {}) {
        const targetActions = this.selectedTaskOutgoingActions || [];
        const targetKeys = new Set(targetActions.map((action) => action.action_key).filter(Boolean));
        const targetByLabel = new Map();
        for (const action of targetActions) {
            const labelKey = this._actionCopyMatchKey(action);
            if (labelKey && !targetByLabel.has(labelKey)) {
                targetByLabel.set(labelKey, action.action_key);
            }
        }
        const mapped = new Map();
        for (const sourceAction of sourceOption.actions || []) {
            const sourceKey = sourceAction.action_key;
            if (!sourceKey) {
                continue;
            }
            if (targetKeys.has(sourceKey)) {
                mapped.set(sourceKey, sourceKey);
                continue;
            }
            const labelKey = this._actionCopyMatchKey(sourceAction);
            if (labelKey && targetByLabel.has(labelKey)) {
                mapped.set(sourceKey, targetByLabel.get(labelKey));
            }
        }
        return mapped;
    }

    _copyMetaFieldRowsFromSource(sourceOption = {}, rows = []) {
        if (!rows.length) {
            return;
        }
        const actionKeyMap = this._actionKeyMapForMetaCopy(sourceOption);
        let skippedActionLimitedRequired = 0;
        for (const row of rows) {
            const originalTypes = this._normalizeMetaFieldTypes(row);
            const domainsByType = this._normalizeMetaFieldDomains(row, originalTypes);
            const originalActionKeys = row.activity_action_keys || [];
            let copiedActionKeys = [];
            let copiedTypes = [...originalTypes];
            if (originalActionKeys.length) {
                copiedActionKeys = originalActionKeys
                    .map((key) => actionKeyMap.get(key))
                    .filter(Boolean);
                if (originalTypes.includes("required") && !copiedActionKeys.length) {
                    copiedTypes = copiedTypes.filter((type) => type !== "required");
                    delete domainsByType.required;
                    skippedActionLimitedRequired += 1;
                }
            }
            const copiedRow = this._makeMetaFieldRow(
                row.field_key,
                copiedTypes,
                copiedTypes.includes("required") ? copiedActionKeys : [],
                domainsByType
            );
            this._upsertMetaFieldRow(copiedRow);
        }
        this.state.metaFieldRows = this._mergeMetaFieldRows(this.state.metaFieldRows);
        this._stageSelectedMetaFieldRows();
        if (skippedActionLimitedRequired) {
            this.notification.add(
                _t(
                    "Copied field rules. Required action limits were skipped on %s rule(s) because no matching outgoing action exists on this node.",
                    skippedActionLimitedRequired
                ),
                {type: "warning"}
            );
        } else {
            this.notification.add(_t("Copied field rules."), {type: "success"});
        }
    }

    copyMetaFieldRows(onUpdated = null) {
        const notifyUpdated = typeof onUpdated === "function" ? onUpdated : () => {};
        if (!this.state.selectedTask) {
            return;
        }
        if (!this._assertEditableVersion()) {
            return;
        }
        const sourceOptions = this.metaFieldCopySourceOptions;
        if (!sourceOptions.length) {
            this.notification.add(_t("No other node has meta field rules to copy."), {type: "info"});
            return;
        }
        this.dialog.add(WorkflowStudioCopyMetaFieldDialog, {
            sourceOptions,
            fieldsOptions: this.fieldsOptions,
            confirm: ({sourceNodeId, rows}) => {
                const sourceOption = sourceOptions.find((source) => source.nodeId === sourceNodeId);
                this._copyMetaFieldRowsFromSource(sourceOption || {}, rows || []);
                notifyUpdated();
                return true;
            },
        });
    }

    openMetaFieldManagerDialog() {
        if (!this.state.selectedTask) {
            return;
        }
        this.dialog.add(WorkflowStudioMetaFieldManagerDialog, {
            getRows: () => this.getMetaFieldManagerRows(),
            canCopy: Boolean(this.metaFieldCopySourceOptions.length),
            addRow: (onUpdated) => this.openMetaFieldDialog(-1, onUpdated),
            copyRows: (onUpdated) => this.copyMetaFieldRows(onUpdated),
            editRow: (rowIndex, onUpdated) => this.openMetaFieldDialog(rowIndex, onUpdated),
            removeRow: (rowIndex, onUpdated) => this.removeMetaFieldRow(rowIndex, onUpdated),
        });
    }

    openMetaFieldDialog(rowIndex, onUpdated = null) {
        const notifyUpdated = typeof onUpdated === "function" ? onUpdated : () => {};
        const isEdit = Number.isInteger(rowIndex) && rowIndex >= 0;
        const existingRow = isEdit ? (this.state.metaFieldRows[rowIndex] || {}) : {};
        this.dialog.add(WorkflowStudioMetaFieldDialog, {
            mode: isEdit ? "edit" : "create",
            initialRow: existingRow,
            fieldsOptions: this.fieldsOptions,
            requestModel: this.state.resModelName,
            requestFields: this.getRequestModelFieldHints(120),
            workflowVersionId: Number(this.state.versionId || 0) || 0,
            workflowCategoryId: Number(this.state.categoryId || 0) || 0,
            workflowMetaTaskOptions: this.workflowMetaTaskOptions,
            isDebugMode: !!this.env.debug,
            outgoingActions: this.selectedTaskOutgoingActions,
            confirm: (updated) => {
                const updatedRows = (updated.field_keys || [updated.field_key])
                    .filter(Boolean)
                    .map((fieldKey) => this._makeMetaFieldRow(
                        fieldKey,
                        updated.field_types || [updated.field_type || "visible"],
                        (updated.field_types || [updated.field_type || "visible"]).includes("required")
                            ? (updated.activity_action_keys || [])
                            : [],
                        updated.domains_by_type || {}
                    ));
                if (isEdit) {
                    this.state.metaFieldRows.splice(rowIndex, 1, ...updatedRows);
                } else {
                    for (const row of updatedRows) {
                        this._upsertMetaFieldRow(row);
                    }
                }
                this.state.metaFieldRows = this._mergeMetaFieldRows(this.state.metaFieldRows);
                this._stageSelectedMetaFieldRows();
                notifyUpdated();
            },
        });
    }

    addMetaFieldRow() {
        this.openMetaFieldDialog(-1);
    }

    async removeMetaFieldRow(index, onUpdated = null) {
        const row = this.state.metaFieldRows[index];
        if (!row) {
            return false;
        }
        const fieldLabel = this._metaFieldShortLabel(row.field_key);
        const confirmed = await this._confirmWithDialog({
            title: _t("Remove Field Rule?"),
            body: sprintf(
                _t('Remove the field rule for "%s"? Its visibility, required, readonly, and condition settings will be discarded. This cannot be undone.'),
                fieldLabel
            ),
            confirmLabel: _t("Remove Field Rule"),
            cancelLabel: _t("Keep Rule"),
            confirmClass: "btn-danger",
        });
        if (!confirmed) {
            return false;
        }
        this.state.metaFieldRows.splice(index, 1);
        this._stageSelectedMetaFieldRows();
        if (typeof onUpdated === "function") {
            onUpdated();
        }
        return true;
    }

    _serializeMetaFieldRows(rows = []) {
        return (rows || [])
            .map((row) => {
                if (!row.field_key) {
                    return null;
                }
                const [fieldModel, fieldName] = row.field_key.split("::");
                const fieldTypes = this._normalizeMetaFieldTypes(row);
                const domainsByType = this._normalizeMetaFieldDomains(row, fieldTypes);
                return {
                    field_model: fieldModel,
                    field_name: fieldName,
                    field_types: fieldTypes,
                    field_type: fieldTypes[0] || "visible",
                    activity_action_keys: fieldTypes.includes("required")
                        ? (row.activity_action_keys || [])
                        : [],
                    domains_by_type: domainsByType,
                    visible_domain: domainsByType.visible || "[]",
                    required_domain: domainsByType.required || "[]",
                    readonly_domain: domainsByType.readonly || "[]",
                    invisible_domain: domainsByType.invisible || "[]",
                    domain: domainsByType[fieldTypes[0] || "visible"] || "[]",
                };
            })
            .filter(Boolean);
    }

    async _saveMetaFieldsForTask(taskNodeId, rows = []) {
        const result = await this.orm.call(
            "workflow.approval.category.version",
            "workflow_studio_set_meta_fields",
            [[this.state.versionId], taskNodeId, this._serializeMetaFieldRows(rows)]
        );
        const allFields = this.state.payload?.meta?.fields || [];
        const filtered = allFields.filter((metaField) => metaField.task_node_id !== taskNodeId);
        this.state.payload = this.state.payload || {};
        this.state.payload.meta = this.state.payload.meta || {};
        this.state.payload.meta.fields = [...filtered, ...(result.rows || [])];
        this._clearPendingMetaFieldRows(taskNodeId);
        if (this.state.selectedTask?.node_id === taskNodeId) {
            this.state.metaFieldRows = this._mergeMetaFieldRows(result.rows || []);
        }
        return result;
    }

    async _savePendingMetaFields(options = {}) {
        const pendingEntries = Object.entries(this.state.pendingMetaFieldRowsByNode || {})
            .map(([taskNodeId, rows]) => [taskNodeId, this._cloneMetaFieldRows(rows)]);
        if (!pendingEntries.length) {
            return true;
        }
        const warnings = [];
        try {
            for (const [taskNodeId, rows] of pendingEntries) {
                const result = await this._saveMetaFieldsForTask(taskNodeId, rows);
                warnings.push(...(result.warnings || []));
            }
            if (warnings.length) {
                this.notification.add(warnings.join("\n"), {type: "warning"});
            } else if (!options.silentSuccess) {
                this.notification.add(_t("Meta field configuration saved."), {type: "success"});
            }
            return true;
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to save field metadata.")),
                {type: "danger"}
            );
            return false;
        }
    }

    async saveMetaFields() {
        const maybeOptions = arguments[0] || {};
        const options = maybeOptions?.target ? {} : maybeOptions;
        if (!this.state.selectedTask) {
            return false;
        }
        if (!this._assertEditableVersion()) {
            return false;
        }
        try {
            const result = await this._saveMetaFieldsForTask(
                this.state.selectedTask.node_id,
                this.state.metaFieldRows
            );
            if (result.warnings?.length) {
                this.notification.add(result.warnings.join("\n"), {type: "warning"});
            } else if (!options.silentSuccess) {
                this.notification.add(_t("Meta field configuration saved."), {type: "success"});
            }
            return true;
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to save field metadata.")),
                {type: "danger"}
            );
            return false;
        }
    }

    async openTransitionProperties(action) {
        if (!action) {
            return;
        }
        const element = this.modeler?.get("elementRegistry")?.get(action.node_id);
        if (element) {
            this.modeler?.get("selection")?.select(element);
            this.state.selectedElement = this._computeSelectionInfo(element);
            this._refreshSelectionMetadata();
            this.state.sidebarTab = "properties";
            return;
        }
        this.state.selectedElement = {
            id: action.node_id,
            type: "bpmn:SequenceFlow",
            kind: "action",
            supported: true,
            sourceId: action.source_id,
            targetId: action.target_id,
            actionKey: action.action_key,
            name: action.attr_label || action.name,
        };
        this._refreshSelectionMetadata();
        this.state.sidebarTab = "properties";
    }

    async saveTaskApprovalLinks() {
        const maybeOptions = arguments[0] || {};
        const options = maybeOptions?.target ? {} : maybeOptions;
        if (!this.state.selectedTask) {
            return false;
        }
        if (!this._assertEditableVersion()) {
            return false;
        }
        const successMessage = options?.successMessage;
        const silentSuccess = !!options?.silentSuccess;
        try {
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_set_task_approval_links",
                [[this.state.versionId], this.state.selectedTask.node_id, this.state.approvalLinkRows]
            );
            const allRows = this.state.payload?.meta?.approval_group_links || [];
            const filtered = allRows.filter(
                (row) => row.task_node_id !== this.state.selectedTask.node_id
            );
            this.state.payload.meta.approval_group_links = [...filtered, ...(result.rows || [])];
            this.state.approvalLinkRows = result.rows || [];
            if (result.warnings?.length) {
                this.notification.add(result.warnings.join("\n"), {type: "warning"});
                return true;
            }
            if (!silentSuccess) {
                this.notification.add(successMessage || _t("Approval group mapping saved."), {type: "success"});
            }
            return true;
        } catch (error) {
            this.notification.add(
                this._rpcErrorMessage(error, _t("Failed to save approval group mapping.")),
                {type: "danger"}
            );
            return false;
        }
    }

    _cloneApprovalLinkRows(rows = []) {
        return (rows || []).map((row) => ({
            ...row,
            approval_group_ref: row?.approval_group_ref
                ? {...row.approval_group_ref}
                : row?.approval_group_ref,
        }));
    }

    async _mutateApprovalLinksAndPersist(mutator, options = {}) {
        const normalizedOptions =
            typeof options === "string"
                ? {successMessage: options}
                : options || {};
        const before = this._cloneApprovalLinkRows(this.state.approvalLinkRows || []);
        mutator();
        const saved = await this.saveTaskApprovalLinks({
            successMessage: normalizedOptions.successMessage || _t("Approval group mapping saved."),
            silentSuccess: !!normalizedOptions.silentSuccess,
        });
        if (!saved) {
            this.state.approvalLinkRows = before;
            return false;
        }
        return true;
    }

    _nextApprovalLinkSequence() {
        const sequences = (this.state.approvalLinkRows || [])
            .map((row) => Number(row?.sequence || 0))
            .filter((value) => Number.isFinite(value) && value > 0);
        if (!sequences.length) {
            return 10;
        }
        return Math.max(...sequences) + 10;
    }

    addApprovalLinkRow(approvalGroupId = false) {
        const normalizedGroupId = Number(approvalGroupId || 0);
        const group = normalizedGroupId
            ? this.approvalGroupOptions.find((option) => Number(option.id || 0) === normalizedGroupId)
            : null;
        this.state.approvalLinkRows.push({
            task_node_id: this.state.selectedTask?.node_id,
            sequence: this._nextApprovalLinkSequence(),
            approval_group_ref: group ? {id: group.id, name: group.name} : false,
            user_domain: "",
            domain: "",
            note: "",
        });
    }

    async linkApprovalGroupFromCatalog(approvalGroupId) {
        if (!this.state.selectedTask) {
            return false;
        }
        if (!this._assertEditableVersion()) {
            return false;
        }
        const normalizedGroupId = Number(approvalGroupId || 0);
        if (!normalizedGroupId) {
            this.notification.add(_t("Select a valid approval group."), {type: "warning"});
            return false;
        }
        const alreadyLinked = (this.state.approvalLinkRows || []).some((row) => {
            const rowGroupId = Number(row?.approval_group_ref?.id || row?.approval_group_id || 0);
            return rowGroupId === normalizedGroupId;
        });
        if (alreadyLinked) {
            this.notification.add(_t("This group is already linked to the selected node."), {type: "warning"});
            return false;
        }
        return await this._mutateApprovalLinksAndPersist(
            () => this.addApprovalLinkRow(normalizedGroupId),
            _t("Group linked to this node.")
        );
    }

    async linkApprovalGroupAndConfigureFromCatalog(approvalGroupId, afterConfirm = false) {
        if (!this.state.selectedTask) {
            return false;
        }
        const normalizedGroupId = Number(approvalGroupId || 0);
        if (!normalizedGroupId) {
            this.notification.add(_t("Select a valid approval group."), {type: "warning"});
            return false;
        }
        const existingRowIndex = this.findApprovalLinkRowIndexByGroupId(normalizedGroupId);
        this.openApprovalGroupLinkDialog({
            selectedGroupId: normalizedGroupId,
            allowGroupSelection: existingRowIndex < 0,
            linkConfig: existingRowIndex >= 0
                ? (this.state.approvalLinkRows?.[existingRowIndex] || this._defaultApprovalGroupLinkConfig())
                : this._defaultApprovalGroupLinkConfig(),
            afterConfirm,
        });
        return true;
    }

    async unlinkApprovalGroupFromCatalog(approvalGroupId) {
        const normalizedGroupId = Number(approvalGroupId || 0);
        if (!normalizedGroupId) {
            return false;
        }
        const linkedRows = (this.state.approvalLinkRows || []).filter((row) => {
            const rowGroupId = Number(row?.approval_group_ref?.id || row?.approval_group_id || 0);
            return rowGroupId === normalizedGroupId;
        });
        if (!linkedRows.length) {
            this.notification.add(_t("This group is not linked to the selected node."), {type: "info"});
            return false;
        }
        const group = this.getApprovalGroupById(normalizedGroupId);
        const groupLabel = this.getApprovalGroupOptionDisplayPath(group)
            || linkedRows[0]?.approval_group_ref?.name
            || _t("this approval group");
        const confirmed = await this._confirmWithDialog({
            title: _t("Unlink Approval Group?"),
            body: sprintf(
                _t('Unlink "%s" from this node? Its routing sequence, domains, and note for this node will be removed. This cannot be undone.'),
                groupLabel
            ),
            confirmLabel: _t("Unlink Group"),
            cancelLabel: _t("Keep Linked"),
            confirmClass: "btn-danger",
        });
        if (!confirmed) {
            return false;
        }
        return this._mutateApprovalLinksAndPersist(
            () => {
                this.state.approvalLinkRows = (this.state.approvalLinkRows || []).filter((row) => {
                    const rowGroupId = Number(row?.approval_group_ref?.id || row?.approval_group_id || 0);
                    return rowGroupId !== normalizedGroupId;
                });
            },
            _t("Group unlinked from this node.")
        );
    }

    async removeApprovalLinkRow(index) {
        const row = Number.isInteger(index) && index >= 0
            ? this.state.approvalLinkRows[index]
            : null;
        if (!row) {
            return false;
        }
        const group = this.getApprovalGroupOptionByRow(row);
        const groupLabel = this.getApprovalGroupOptionDisplayPath(group)
            || row.approval_group_ref?.name
            || _t("this approval group");
        const confirmed = await this._confirmWithDialog({
            title: _t("Remove Approval Group Rule?"),
            body: sprintf(
                _t('Remove the routing rule for "%s" from this node? Its sequence, domains, and note will be discarded. This cannot be undone.'),
                groupLabel
            ),
            confirmLabel: _t("Remove Rule"),
            cancelLabel: _t("Keep Rule"),
            confirmClass: "btn-danger",
        });
        if (!confirmed) {
            return false;
        }
        return this._mutateApprovalLinksAndPersist(
            () => {
                this.state.approvalLinkRows.splice(index, 1);
            },
            _t("Group rule removed.")
        );
    }

    onApprovalLinkGroupChange(index, approvalGroupId) {
        if (!this.state.approvalLinkRows[index]) {
            return;
        }
        const normalizedGroupId = Number(approvalGroupId || 0);
        const group = this.approvalGroupOptions.find(
            (option) => Number(option.id || 0) === normalizedGroupId
        );
        this.state.approvalLinkRows[index].approval_group_ref = group
            ? {id: group.id, name: group.name}
            : false;
    }

    async onApprovalGroupSelectChange(event) {
        const approvalIndex = Number(event.target.dataset.approvalIndex);
        if (!Number.isInteger(approvalIndex) || approvalIndex < 0) {
            return;
        }
        const approvalGroupId = event?.target?.value;
        await this._mutateApprovalLinksAndPersist(
            () => this.onApprovalLinkGroupChange(approvalIndex, approvalGroupId),
            _t("Approval group updated.")
        );
    }

    onApprovalLinkTextChange(index, fieldName, value) {
        if (!this.state.approvalLinkRows[index]) {
            return;
        }
        this.state.approvalLinkRows[index][fieldName] = value;
    }

    onApprovalLinkDomainPresetChange(index, fieldName, event) {
        const domain = event?.target?.value || "";
        if (!domain) {
            return;
        }
        this.onApprovalLinkTextChange(index, fieldName, domain);
        event.target.value = "";
    }

    openApprovalLinkDomainDialog(index, fieldName, contextType = "generic") {
        if (!this.state.selectedTask || !this.state.approvalLinkRows[index]) {
            return;
        }
        const row = this.state.approvalLinkRows[index];
        const isUserDomain = fieldName === "user_domain";
        const resolvedContextType = isUserDomain ? "assignment_users_routing" : "request_scope_routing";
        const model = isUserDomain ? "res.users" : this.state.resModelName;
        if (!model) {
            this.notification.add(_t("No target model configured for this domain field."), {
                type: "warning",
            });
            return;
        }
        const presetKey = isUserDomain ? "routing_user_assignment" : "routing_request_scope";
        this.dialog.add(WorkflowStudioDomainDialog, {
            resModel: model,
            requestModel: this.state.resModelName || model,
            requestFields: this.getRequestModelFieldHints(),
            workflowVersionId: Number(this.state.versionId || 0) || 0,
            workflowCategoryId: Number(this.state.categoryId || 0) || 0,
            domain: row[fieldName] || "",
            title: isUserDomain ? _t("Approval Group User Domain") : _t("Approval Group Record Domain"),
            contextType: resolvedContextType,
            presets: this.getDomainPresets(presetKey),
            isDebugMode: !!this.env.debug,
            allowBlankDomain: true,
            onConfirm: (domain) => this.onApprovalLinkTextChange(index, fieldName, domain),
        });
    }

    onApprovalGroupCatalogSearchInput(event) {
        this.setApprovalGroupCatalogQuery(event?.target?.value || "");
    }

    onApprovalGroupCatalogModeChange(event) {
        this.setApprovalGroupCatalogMode(event?.target?.value || "all");
    }

    loadMoreApprovalGroupCatalogRows() {
        return this.refreshApprovalGroupCatalogBrowser({immediate: true, append: true});
    }

    async saveTaskWorkflowMaps() {
        if (!this.state.selectedTask) {
            return;
        }
        if (!this._assertEditableVersion()) {
            return;
        }
        try {
            const result = await this.orm.call(
                "workflow.approval.category.version",
                "workflow_studio_set_task_workflow_maps",
                [[this.state.versionId], this.state.selectedTask.node_id, this.state.workflowMapRows]
            );
            const allRows = this.state.payload?.meta?.workflow_maps || [];
            const filtered = allRows.filter(
                (row) => row.task_node_id !== this.state.selectedTask.node_id
            );
            this.state.payload.meta.workflow_maps = [...filtered, ...(result.rows || [])];
            this.state.workflowMapRows = result.rows || [];
            if (result.warnings?.length) {
                this.notification.add(result.warnings.join("\n"), {type: "warning"});
            } else {
                this.notification.add(_t("Workflow mapping saved."), {type: "success"});
            }
        } catch {
            this.notification.add(_t("Failed to save workflow mapping."), {type: "danger"});
        }
    }

    addWorkflowMapRow() {
        this.state.workflowMapRows.push({
            task_node_id: this.state.selectedTask?.node_id,
            execution_mode: "sync",
            field_mapping: "",
            domain: "",
            called_workflow_ref: false,
        });
    }

    async removeWorkflowMapRow(index) {
        const row = this.state.workflowMapRows[index];
        if (!row) {
            return false;
        }
        const workflowLabel = row.called_workflow_ref?.display_name
            || row.called_workflow_ref?.name
            || _t("this workflow mapping");
        const confirmed = await this._confirmWithDialog({
            title: _t("Remove Workflow Mapping?"),
            body: sprintf(
                _t('Remove the mapping to "%s"? Its execution mode, field mapping, and condition will be discarded. This cannot be undone.'),
                workflowLabel
            ),
            confirmLabel: _t("Remove Mapping"),
            cancelLabel: _t("Keep Mapping"),
            confirmClass: "btn-danger",
        });
        if (!confirmed) {
            return false;
        }
        this.state.workflowMapRows.splice(index, 1);
        return true;
    }

    onWorkflowMapTextChange(index, fieldName, value) {
        if (!this.state.workflowMapRows[index]) {
            return;
        }
        this.state.workflowMapRows[index][fieldName] = value;
    }

    onWorkflowMapCalledWorkflowChange(index, workflowId) {
        if (!this.state.workflowMapRows[index]) {
            return;
        }
        const workflow = this.calledWorkflowOptions.find((option) => option.id === Number(workflowId));
        this.state.workflowMapRows[index].called_workflow_ref = workflow
            ? {
                id: workflow.id,
                name: workflow.name,
                display_name: workflow.display_name,
            }
            : false;
    }

    onWorkflowMapCalledWorkflowSelectChange(event) {
        const mapIndex = Number(event.target.dataset.mapIndex);
        if (!Number.isInteger(mapIndex) || mapIndex < 0) {
            return;
        }
        this.onWorkflowMapCalledWorkflowChange(mapIndex, event.target.value);
    }

    onWorkflowMapExecutionModeChange(event) {
        const mapIndex = Number(event.target.dataset.mapIndex);
        if (!Number.isInteger(mapIndex) || mapIndex < 0) {
            return;
        }
        this.onWorkflowMapTextChange(mapIndex, "execution_mode", event.target.value);
    }

    onWorkflowMapDomainPresetChange(index, event) {
        const domain = event?.target?.value || "";
        if (!domain) {
            return;
        }
        this.onWorkflowMapTextChange(index, "domain", domain);
        event.target.value = "";
    }

    openWorkflowMapDomainDialog(index) {
        if (!this.state.selectedTask || !this.state.workflowMapRows[index]) {
            return;
        }
        if (!this.state.resModelName) {
            this.notification.add(_t("No request model configured on this workflow version."), {
                type: "warning",
            });
            return;
        }
        this.dialog.add(WorkflowStudioDomainDialog, {
            resModel: this.state.resModelName,
            requestModel: this.state.resModelName,
            requestFields: this.getRequestModelFieldHints(),
            workflowVersionId: Number(this.state.versionId || 0) || 0,
            workflowCategoryId: Number(this.state.categoryId || 0) || 0,
            domain: this.state.workflowMapRows[index].domain || "[]",
            title: _t("Workflow Map Record Domain"),
            contextType: "generic",
            presets: this.getDomainPresets("request_scope"),
            isDebugMode: !!this.env.debug,
            onConfirm: (domain) => this.onWorkflowMapTextChange(index, "domain", domain),
        });
    }

    onWorkflowMapFieldMappingTemplateChange(index, event) {
        const templateValue = event?.target?.value || "";
        if (!templateValue) {
            return;
        }
        this.onWorkflowMapTextChange(index, "field_mapping", templateValue);
        event.target.value = "";
    }

    onComponentDragStart(ev, componentKey) {
        if (!this._assertEditableVersion()) {
            ev.preventDefault();
            return;
        }
        if (!ev.dataTransfer) {
            return;
        }
        ev.dataTransfer.effectAllowed = "copy";
        ev.dataTransfer.setData(BPMN_DRAG_MIME, componentKey);
        ev.dataTransfer.setData("text/plain", componentKey);
    }

    onCanvasDragOver(ev) {
        const types = ev.dataTransfer?.types;
        const hasShapeData = !!types
            && (
                (typeof types.includes === "function" && types.includes(BPMN_DRAG_MIME))
                || (typeof types.contains === "function" && types.contains(BPMN_DRAG_MIME))
            );
        if (!hasShapeData) {
            return;
        }
        ev.preventDefault();
        if (ev.dataTransfer) {
            ev.dataTransfer.dropEffect = "copy";
        }
        this.state.isCanvasDragOver = true;
    }

    onCanvasDragLeave(ev) {
        if (!ev.currentTarget.contains(ev.relatedTarget)) {
            this.state.isCanvasDragOver = false;
        }
    }

    onCanvasDrop(ev) {
        ev.preventDefault();
        this.state.isCanvasDragOver = false;
        const componentKey =
            ev.dataTransfer?.getData(BPMN_DRAG_MIME) || ev.dataTransfer?.getData("text/plain");
        if (!componentKey || !ALLOWED_DRAG_COMPONENT_KEYS.has(componentKey)) {
            return;
        }
        const component = ADD_COMPONENT_ITEMS_BY_KEY.get(componentKey);
        if (!component?.shapeSpec) {
            return;
        }
        this.onCreateShape(component.shapeSpec, {clientX: ev.clientX, clientY: ev.clientY});
    }

    _getDiagramPointFromClient(clientX, clientY) {
        const svg = this.canvasRef.el?.querySelector("svg");
        if (!svg || !svg.createSVGPoint) {
            return null;
        }
        const ctm = svg.getScreenCTM();
        if (!ctm) {
            return null;
        }
        const point = svg.createSVGPoint();
        point.x = clientX;
        point.y = clientY;
        const transformed = point.matrixTransform(ctm.inverse());
        return {x: transformed.x, y: transformed.y};
    }

    onCreateShape(shapeSpec, dropPosition = null) {
        if (!this.modeler) {
            return;
        }
        if (!this._assertEditableVersion()) {
            return;
        }
        const elementFactory = this.modeler.get("elementFactory");
        const modeling = this.modeler.get("modeling");
        const canvas = this.modeler.get("canvas");
        const root = canvas.getRootElement();
        const createAttrs = typeof shapeSpec === "string" ? {type: shapeSpec} : {...(shapeSpec || {})};
        if (!createAttrs.type) {
            return;
        }
        const shape = elementFactory.createShape(createAttrs);
        let position = null;
        if (dropPosition?.clientX && dropPosition?.clientY) {
            position = this._getDiagramPointFromClient(dropPosition.clientX, dropPosition.clientY);
        }
        if (!position) {
            const viewbox = canvas.viewbox();
            position = {x: viewbox.x + viewbox.width / 2, y: viewbox.y + viewbox.height / 2};
        }
        modeling.createShape(shape, position, root);
    }
}

registry.category("actions").add("workflow_studio.bpmn_editor", WorkflowStudioBpmnEditor);
