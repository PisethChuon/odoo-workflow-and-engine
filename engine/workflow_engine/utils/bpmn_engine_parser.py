# File: bpmn_engine_parser.py
import logging
import re
import xml.etree.ElementTree as ET
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

NODE_TYPE = {
    'MESSAGE_EVENT_DEFINITION': 'messageEventDefinition',
    'TIMER_EVENT_DEFINITION': 'timerEventDefinition',
    'SIGNAL_EVENT_DEFINITION': 'signalEventDefinition',
    'TERMINATE_EVENT_DEFINITION': 'terminateEventDefinition',
    'TIMER_EVENT': 'timerEvent',
    'SIGNAL_EVENT': 'signalEvent',
    'CONDITIONAL_EVENT_DEFINITION': 'conditionalEventDefinition',
    'USER_TASK': 'userTask',
    'MANUAL_TASK': 'manualTask',
    'SERVICE_TASK': 'serviceTask',
    'SEND_TASK': 'sendTask',
    'RECEIVE_TASK': 'receiveTask',
    'SCRIPT_TASK': 'scriptTask',
    'BUSINESS_RULE_TASK': 'businessRuleTask',
    'CALL_ACTIVITY': 'callActivity',
    'SUB_PROCESS': 'subProcess',
    'START_EVENT': 'startEvent',
    'START_EVENT_WITH_MESSAGE': 'startEventMessage',
    'START_EVENT_WITH_TIMER': 'startEventTimer',
    'START_EVENT_WITH_SIGNAL': 'startEventSignal',
    'START_EVENT_WITH_CONDITIONAL': 'startEventConditional',
    'END_EVENT': 'endEvent',
    'END_EVENT_WITH_MESSAGE': 'endEventMessage',
    'END_EVENT_WITH_SIGNAL': 'endEventSignal',
    'END_EVENT_WITH_TERMINATE': 'endEventTerminate',
    'INTERMEDIATE_CATCH_EVENT': 'intermediateCatchEvent',
    'INTERMEDIATE_CATCH_EVENT_WITH_MESSAGE': 'intermediateEventMessage',
    'INTERMEDIATE_CATCH_EVENT_WITH_SIGNAL': 'intermediateEventSignal',
    'INTERMEDIATE_THROW_EVENT': 'intermediateThrowEvent',
    'INTERMEDIATE_THROW_EVENT_WITH_MESSAGE': 'intermediateThrowEventMessage',
    'INTERMEDIATE_THROW_EVENT_WITH_SIGNAL': 'intermediateThrowEventSignal',
    'EXCLUSIVE_GATEWAY': 'exclusiveGateway',
    'PARALLEL_GATEWAY': 'parallelGateway',
    'INCLUSIVE_GATEWAY': 'inclusiveGateway',
    'EVENT_BASED_GATEWAY': 'eventBasedGateway',
    'COMPLEX_GATEWAY': 'complexGateway',
    'TASK': 'task'
}

ACTION_TYPE = {
    'START_ACTION': 'startAction',
    'AUTO_ACTION': 'autoAction',
    'EMAIL_ACTION': 'emailAction',
    'SYSTEM_ACTION': 'systemAction',
    'SUB_PROCESS_ACTION': 'subprocessAction',
    'USER_ACTION': 'userAction',
    'NO_EMAIL_ACTION': 'noEmailAction'
}

TASK_NODE_TYPE_BY_TAG_SUFFIX = {
    NODE_TYPE['USER_TASK']: NODE_TYPE['USER_TASK'],
    NODE_TYPE['MANUAL_TASK']: NODE_TYPE['MANUAL_TASK'],
    NODE_TYPE['SERVICE_TASK']: NODE_TYPE['SERVICE_TASK'],
    NODE_TYPE['SEND_TASK']: NODE_TYPE['SEND_TASK'],
    NODE_TYPE['RECEIVE_TASK']: NODE_TYPE['RECEIVE_TASK'],
    NODE_TYPE['SCRIPT_TASK']: NODE_TYPE['SCRIPT_TASK'],
    NODE_TYPE['BUSINESS_RULE_TASK']: NODE_TYPE['BUSINESS_RULE_TASK'],
    NODE_TYPE['CALL_ACTIVITY']: NODE_TYPE['CALL_ACTIVITY'],
    NODE_TYPE['SUB_PROCESS']: NODE_TYPE['SUB_PROCESS'],
    NODE_TYPE['TASK']: NODE_TYPE['TASK'],
}

GATEWAY_NODE_TYPE_BY_TAG_SUFFIX = {
    NODE_TYPE['EXCLUSIVE_GATEWAY']: NODE_TYPE['EXCLUSIVE_GATEWAY'],
    NODE_TYPE['PARALLEL_GATEWAY']: NODE_TYPE['PARALLEL_GATEWAY'],
    NODE_TYPE['INCLUSIVE_GATEWAY']: NODE_TYPE['INCLUSIVE_GATEWAY'],
    NODE_TYPE['EVENT_BASED_GATEWAY']: NODE_TYPE['EVENT_BASED_GATEWAY'],
    NODE_TYPE['COMPLEX_GATEWAY']: NODE_TYPE['COMPLEX_GATEWAY'],
}

START_EVENT_DEFINITION_TO_NODE_TYPE = {
    NODE_TYPE['MESSAGE_EVENT_DEFINITION']: NODE_TYPE['START_EVENT_WITH_MESSAGE'],
    NODE_TYPE['TIMER_EVENT_DEFINITION']: NODE_TYPE['START_EVENT_WITH_TIMER'],
    NODE_TYPE['SIGNAL_EVENT_DEFINITION']: NODE_TYPE['START_EVENT_WITH_SIGNAL'],
    NODE_TYPE['CONDITIONAL_EVENT_DEFINITION']: NODE_TYPE['START_EVENT_WITH_CONDITIONAL'],
}

END_EVENT_DEFINITION_TO_NODE_TYPE = {
    NODE_TYPE['MESSAGE_EVENT_DEFINITION']: NODE_TYPE['END_EVENT_WITH_MESSAGE'],
    NODE_TYPE['SIGNAL_EVENT_DEFINITION']: NODE_TYPE['END_EVENT_WITH_SIGNAL'],
    NODE_TYPE['TERMINATE_EVENT_DEFINITION']: NODE_TYPE['END_EVENT_WITH_TERMINATE'],
}

INTERMEDIATE_CATCH_DEFINITION_TO_NODE_TYPE = {
    NODE_TYPE['MESSAGE_EVENT_DEFINITION']: NODE_TYPE['INTERMEDIATE_CATCH_EVENT_WITH_MESSAGE'],
    NODE_TYPE['TIMER_EVENT_DEFINITION']: NODE_TYPE['TIMER_EVENT'],
    NODE_TYPE['SIGNAL_EVENT_DEFINITION']: NODE_TYPE['INTERMEDIATE_CATCH_EVENT_WITH_SIGNAL'],
    NODE_TYPE['CONDITIONAL_EVENT_DEFINITION']: NODE_TYPE['CONDITIONAL_EVENT_DEFINITION'],
}

INTERMEDIATE_THROW_DEFINITION_TO_NODE_TYPE = {
    NODE_TYPE['MESSAGE_EVENT_DEFINITION']: NODE_TYPE['INTERMEDIATE_THROW_EVENT_WITH_MESSAGE'],
    NODE_TYPE['SIGNAL_EVENT_DEFINITION']: NODE_TYPE['INTERMEDIATE_THROW_EVENT_WITH_SIGNAL'],
}

NODE_METADATA_PROFILE = {
    NODE_TYPE['INTERMEDIATE_CATCH_EVENT_WITH_MESSAGE']: {
        'meta_role': 'approval_button',
        'purpose': 'Approval/decision transition step.',
    },
    NODE_TYPE['SEND_TASK']: {
        'meta_role': 'notification',
        'purpose': 'Channel-based notification node (email/sms/telegram).',
    },
    NODE_TYPE['SCRIPT_TASK']: {
        'meta_role': 'server_action',
        'purpose': 'Automation/server-action execution node.',
    },
    NODE_TYPE['INCLUSIVE_GATEWAY']: {
        'meta_role': 'conditional_router',
        'purpose': 'Condition-based multi-branch router.',
    },
}

SUPPORTED_TASK_NODE_TYPE = [
    NODE_TYPE['START_EVENT'],
    NODE_TYPE['START_EVENT_WITH_MESSAGE'],
    NODE_TYPE['START_EVENT_WITH_TIMER'],
    NODE_TYPE['START_EVENT_WITH_SIGNAL'],
    NODE_TYPE['START_EVENT_WITH_CONDITIONAL'],
    NODE_TYPE['END_EVENT'],
    NODE_TYPE['END_EVENT_WITH_MESSAGE'],
    NODE_TYPE['END_EVENT_WITH_SIGNAL'],
    NODE_TYPE['END_EVENT_WITH_TERMINATE'],
    NODE_TYPE['USER_TASK'],
    NODE_TYPE['MANUAL_TASK'],
    NODE_TYPE['TASK'],
    NODE_TYPE['SERVICE_TASK'],
    NODE_TYPE['SEND_TASK'],
    NODE_TYPE['RECEIVE_TASK'],
    NODE_TYPE['SCRIPT_TASK'],
    NODE_TYPE['BUSINESS_RULE_TASK'],
    NODE_TYPE['SUB_PROCESS'],
    NODE_TYPE['CALL_ACTIVITY'],
    NODE_TYPE['CONDITIONAL_EVENT_DEFINITION'],
    NODE_TYPE['TIMER_EVENT'],
    NODE_TYPE['SIGNAL_EVENT'],
    NODE_TYPE['INTERMEDIATE_CATCH_EVENT'],
    NODE_TYPE['INTERMEDIATE_CATCH_EVENT_WITH_MESSAGE'],
    NODE_TYPE['INTERMEDIATE_CATCH_EVENT_WITH_SIGNAL'],
    NODE_TYPE['INTERMEDIATE_THROW_EVENT'],
    NODE_TYPE['INTERMEDIATE_THROW_EVENT_WITH_MESSAGE'],
    NODE_TYPE['INTERMEDIATE_THROW_EVENT_WITH_SIGNAL'],
    NODE_TYPE['EXCLUSIVE_GATEWAY'],
    NODE_TYPE['PARALLEL_GATEWAY'],
    NODE_TYPE['INCLUSIVE_GATEWAY'],
    NODE_TYPE['EVENT_BASED_GATEWAY'],
    NODE_TYPE['COMPLEX_GATEWAY'],
]

PASS_THROUGH_NODE_TYPE = {
    NODE_TYPE['START_EVENT_WITH_MESSAGE'],
    NODE_TYPE['START_EVENT_WITH_TIMER'],
    NODE_TYPE['START_EVENT_WITH_SIGNAL'],
    NODE_TYPE['START_EVENT_WITH_CONDITIONAL'],
    NODE_TYPE['INTERMEDIATE_CATCH_EVENT'],
    NODE_TYPE['INTERMEDIATE_CATCH_EVENT_WITH_MESSAGE'],
    NODE_TYPE['INTERMEDIATE_CATCH_EVENT_WITH_SIGNAL'],
    NODE_TYPE['INTERMEDIATE_THROW_EVENT'],
    NODE_TYPE['INTERMEDIATE_THROW_EVENT_WITH_MESSAGE'],
    NODE_TYPE['INTERMEDIATE_THROW_EVENT_WITH_SIGNAL'],
    NODE_TYPE['TIMER_EVENT'],
    NODE_TYPE['SIGNAL_EVENT'],
    NODE_TYPE['CONDITIONAL_EVENT_DEFINITION'],
    NODE_TYPE['EXCLUSIVE_GATEWAY'],
    NODE_TYPE['PARALLEL_GATEWAY'],
    NODE_TYPE['INCLUSIVE_GATEWAY'],
    NODE_TYPE['EVENT_BASED_GATEWAY'],
    NODE_TYPE['COMPLEX_GATEWAY'],
}

class BpmnEngine:
    def __init__(self, xml_string):
        self.tree = ET.ElementTree(ET.fromstring(xml_string))
        self.root = self.tree.getroot()
        self.ns = {
            'bpmn': 'http://www.omg.org/spec/BPMN/20100524/MODEL',
            'custom': 'http://example.com/schema/custom',
        }
        self.process = self.root.find('bpmn:process', self.ns)
        self.sequence_flows = self._map_sequence_flows()
        self.elements_by_id = self._map_elements_by_id()
        # self.incoming_flows = self._map_incoming_flows()  # NEW

    def _map_elements_by_id(self):
        return {
            el.attrib['id']: el
            for el in self.root.findall('.//*')
            if 'id' in el.attrib
        }

    def _map_sequence_flows(self):
        flows = {}
        for flow in self.root.findall('.//bpmn:sequenceFlow', self.ns):
            source = flow.attrib['sourceRef']
            target = flow.attrib['targetRef']
            condition = flow.find('bpmn:conditionExpression', self.ns)
            condition_text = condition.text.strip() if condition is not None and condition.text else None
            flows[source] = flows.get(source, []) + [{
                'id': flow.attrib['id'],
                'source': source,
                'target': target,
                'name': flow.attrib.get('name', ''),
                'condition': condition_text,
                # 'custom': self.get_custom_extensions(flow),  # parsed once and reused
            }]
        return flows
    
    def is_user_task(self, el):
        """
        <bpmn:userTask id="Activity_1rorq9y" name="Submission">
            <bpmn:incoming>Flow_0aih05y</bpmn:incoming>
            <bpmn:outgoing>Flow_17qhj8r</bpmn:outgoing>
            <bpmn:outgoing>Flow_1h82xk3</bpmn:outgoing>
        </bpmn:userTask>
        or
        <bpmn:task id="Activity_1rorq9y" name="Submission">
            <bpmn:incoming>Flow_0aih05y</bpmn:incoming>
            <bpmn:outgoing>Flow_17qhj8r</bpmn:outgoing>
            <bpmn:outgoing>Flow_1h82xk3</bpmn:outgoing>
        </bpmn:task>
        """
        return el.tag.endswith(NODE_TYPE['USER_TASK']) or el.tag.endswith(NODE_TYPE['TASK'])

    def is_start_event(self, el):
        """
        <bpmn:startEvent id="StartEvent_1" name="Start">
            <bpmn:outgoing>Flow_0aih05y</bpmn:outgoing>
        </bpmn:startEvent>
        """
        return el.tag.endswith(NODE_TYPE['START_EVENT'])

    def is_send_task(self, el):
        """
        <bpmn:sendTask id="Activity_1co02hd" name="Email Notify">
            <bpmn:incoming>Flow_1bdqfmb</bpmn:incoming>
            <bpmn:incoming>Flow_1b81fpm</bpmn:incoming>
            <bpmn:outgoing>Flow_16ymq2e</bpmn:outgoing>
            <bpmn:outgoing>Flow_1ro1ryc</bpmn:outgoing>
        </bpmn:sendTask>
        """
        return el.tag.endswith(NODE_TYPE['SEND_TASK'])

    def is_end_event(self, el):
        """
        End Event can be an explicit BPMN endEvent or a legacy signal throw-event.
        """
        if el is None:
            return False
        element_type = self.get_element_type(el)
        return element_type in (
            NODE_TYPE['END_EVENT'],
            NODE_TYPE['END_EVENT_WITH_MESSAGE'],
            NODE_TYPE['END_EVENT_WITH_SIGNAL'],
            NODE_TYPE['END_EVENT_WITH_TERMINATE'],
            NODE_TYPE['INTERMEDIATE_THROW_EVENT_WITH_SIGNAL'],
        )

    def is_service_task(self, el):
        """
        <bpmn:serviceTask id="Activity_18ced0k" name="Is Casino App?">
            <bpmn:incoming>Flow_0r6314j</bpmn:incoming>
            <bpmn:outgoing>Flow_09snrtg</bpmn:outgoing>
            <bpmn:outgoing>Flow_1trnfvf</bpmn:outgoing>
        </bpmn:serviceTask>
        """
        return el.tag.endswith(NODE_TYPE['SERVICE_TASK'])

    def is_no_alert_task(self, el):
        """
        <bpmn:intermediateThrowEvent id="Event_1c9p31l" name="Approve">
            <bpmn:incoming>Flow_1t1l6xp</bpmn:incoming>
            <bpmn:outgoing>Flow_0uobr9p</bpmn:outgoing>
        </bpmn:intermediateThrowEvent>
        """
        return el.tag.endswith(NODE_TYPE['INTERMEDIATE_THROW_EVENT'])

    @classmethod
    def is_user_action(self, source_node_type, action_type):
        """
        A user action is the action that allows user to interact.
        It is user action if:
        - source node type is either user task/manual task/generic task
        - action type is either email action or no email action 
        :param source_node_type: one of NODE_TYPE
        :param action_type: one of ACTION_TYPE
        """
        return bool(
            source_node_type in (NODE_TYPE['USER_TASK'], NODE_TYPE['MANUAL_TASK'], NODE_TYPE['TASK'])
            and action_type in [ACTION_TYPE['USER_ACTION'], ACTION_TYPE['EMAIL_ACTION'], ACTION_TYPE['NO_EMAIL_ACTION']]
        )

    @classmethod
    def get_action_type(self, action_node_type):
        if action_node_type in [NODE_TYPE['START_EVENT']]:
            flow_type = ACTION_TYPE['START_ACTION']
        elif action_node_type in [NODE_TYPE['TIMER_EVENT']]:
            flow_type = ACTION_TYPE['AUTO_ACTION']
        elif action_node_type in [
            NODE_TYPE['SERVICE_TASK'],
            NODE_TYPE['CONDITIONAL_EVENT_DEFINITION'],
            NODE_TYPE['EXCLUSIVE_GATEWAY'],
            NODE_TYPE['PARALLEL_GATEWAY'],
            NODE_TYPE['INCLUSIVE_GATEWAY'],
            NODE_TYPE['EVENT_BASED_GATEWAY'],
            NODE_TYPE['COMPLEX_GATEWAY'],
        ]:
            flow_type = ACTION_TYPE['SYSTEM_ACTION']
        elif action_node_type in [NODE_TYPE['SUB_PROCESS']]:
            flow_type = ACTION_TYPE['SUB_PROCESS_ACTION']
        elif action_node_type in [
            NODE_TYPE['INTERMEDIATE_THROW_EVENT'],
            NODE_TYPE['INTERMEDIATE_THROW_EVENT_WITH_SIGNAL'],
            NODE_TYPE['END_EVENT'],
            NODE_TYPE['END_EVENT_WITH_SIGNAL'],
            NODE_TYPE['END_EVENT_WITH_TERMINATE'],
        ]:
            flow_type = ACTION_TYPE['NO_EMAIL_ACTION']
        elif action_node_type in [
            NODE_TYPE['INTERMEDIATE_CATCH_EVENT_WITH_MESSAGE'],
            NODE_TYPE['INTERMEDIATE_THROW_EVENT_WITH_MESSAGE'],
            NODE_TYPE['END_EVENT_WITH_MESSAGE'],
        ]:
            flow_type = ACTION_TYPE['EMAIL_ACTION']
        else:
            flow_type = ACTION_TYPE['USER_ACTION']
        return flow_type

    def _get_event_definition_tag_name(self, el):
        if el is None:
            return ""
        for definition in (
            NODE_TYPE['MESSAGE_EVENT_DEFINITION'],
            NODE_TYPE['TIMER_EVENT_DEFINITION'],
            NODE_TYPE['SIGNAL_EVENT_DEFINITION'],
            NODE_TYPE['CONDITIONAL_EVENT_DEFINITION'],
            NODE_TYPE['TERMINATE_EVENT_DEFINITION'],
        ):
            if el.find(f".//bpmn:{definition}", self.ns) is not None:
                return definition
        return ""

    def _classify_task_type(self, tag):
        for suffix, node_type in TASK_NODE_TYPE_BY_TAG_SUFFIX.items():
            if suffix == NODE_TYPE['TASK']:
                if tag.endswith(NODE_TYPE['TASK']):
                    return node_type
                continue
            if suffix in tag:
                return node_type
        return ""

    def _classify_gateway_type(self, tag):
        for suffix, node_type in GATEWAY_NODE_TYPE_BY_TAG_SUFFIX.items():
            if suffix in tag:
                return node_type
        return ""

    def _classify_start_event_type(self, el):
        event_def = self._get_event_definition_tag_name(el)
        return START_EVENT_DEFINITION_TO_NODE_TYPE.get(event_def, NODE_TYPE['START_EVENT'])

    def _classify_end_event_type(self, el):
        event_def = self._get_event_definition_tag_name(el)
        return END_EVENT_DEFINITION_TO_NODE_TYPE.get(event_def, NODE_TYPE['END_EVENT'])

    def _classify_intermediate_catch_type(self, el):
        event_def = self._get_event_definition_tag_name(el)
        return INTERMEDIATE_CATCH_DEFINITION_TO_NODE_TYPE.get(event_def, NODE_TYPE['INTERMEDIATE_CATCH_EVENT'])

    def _classify_intermediate_throw_type(self, el):
        event_def = self._get_event_definition_tag_name(el)
        return INTERMEDIATE_THROW_DEFINITION_TO_NODE_TYPE.get(event_def, NODE_TYPE['INTERMEDIATE_THROW_EVENT'])
    
    def get_element_type(self, el):
        """
        Determine the type of the BPMN element.
        Covers: tasks, events, callActivity, subProcess, gateways.
        """
        if el is None:
            return ""

        tag = el.tag

        task_type = self._classify_task_type(tag)
        if task_type:
            return task_type

        gateway_type = self._classify_gateway_type(tag)
        if gateway_type:
            return gateway_type

        if NODE_TYPE['START_EVENT'] in tag:
            return self._classify_start_event_type(el)
        if NODE_TYPE['END_EVENT'] in tag:
            return self._classify_end_event_type(el)
        if NODE_TYPE['INTERMEDIATE_CATCH_EVENT'] in tag:
            return self._classify_intermediate_catch_type(el)
        if NODE_TYPE['INTERMEDIATE_THROW_EVENT'] in tag:
            return self._classify_intermediate_throw_type(el)
        return ""

    def is_pass_through_node(self, el):
        return self.get_element_type(el) in PASS_THROUGH_NODE_TYPE

    def get_element_by_id(self, element_id):
        return self.elements_by_id.get(element_id)
    
    def get_element_incoming_by_id(self, element_id):
        return self.incoming_flows.get(element_id)

    def get_element_name_by_id(self, element_id):
        element = self.elements_by_id.get(element_id)
        name = None
        if element:
            name = element.get('name')
        return name

    def get_start_event(self, scope_node=None):
        return self.process.find('bpmn:startEvent', self.ns)

    def get_next_elements(self, element, form_data=None, evaluate_conditions=True):
        if element is None or 'id' not in element.attrib:
            return []
        source_id = element.attrib['id']
        outgoing = self.sequence_flows.get(source_id, [])
        selected_flows = outgoing
        if evaluate_conditions:
            selected_flows = []
            element_type = self.get_element_type(element)
            if element_type == NODE_TYPE['PARALLEL_GATEWAY']:
                selected_flows = outgoing
            elif element_type == NODE_TYPE['EXCLUSIVE_GATEWAY'] and outgoing:
                conditional_matches = []
                fallback_flows = []
                for seq in outgoing:
                    condition = seq.get('condition')
                    if condition:
                        if self.evaluate_condition(condition, form_data or {}):
                            conditional_matches.append(seq)
                    else:
                        fallback_flows.append(seq)

                if conditional_matches:
                    if len(conditional_matches) > 1:
                        _logger.warning(
                            "Exclusive gateway %s matched multiple outgoing conditions; choosing the first BPMN flow.",
                            source_id,
                        )
                    # Exclusive gateways must select one route only. Preserve BPMN order.
                    selected_flows = conditional_matches[:1]
                else:
                    default_flow_id = element.attrib.get("default")
                    if default_flow_id:
                        default_flow = next(
                            (seq for seq in outgoing if seq.get("id") == default_flow_id),
                            None,
                        )
                        selected_flows = [default_flow] if default_flow else fallback_flows
                    else:
                        selected_flows = fallback_flows
            else:
                selected_flows = [
                    seq
                    for seq in outgoing
                    if not seq.get('condition')
                    or self.evaluate_condition(seq['condition'], form_data or {})
                ]
        result = []
        for seq in selected_flows:
            target = self.get_element_by_id(seq['target'])
            if target is not None:
                result.append(target)
        return result

    def _is_leaf_condition(self, node):
        return (
            isinstance(node, (list, tuple))
            and len(node) == 3
            and isinstance(node[0], str)
            and isinstance(node[1], str)
        )

    def _resolve_field_value(self, form_data, field_path):
        if not isinstance(form_data, dict):
            return None
        if field_path in form_data:
            return form_data.get(field_path)

        value = form_data
        for token in str(field_path or "").split("."):
            if isinstance(value, dict):
                value = value.get(token)
                continue
            if hasattr(value, token):
                value = getattr(value, token)
                continue
            return None
        return value

    def _normalize_domain_value(self, value):
        if hasattr(value, "ids"):
            ids = list(getattr(value, "ids", []))
            if len(ids) == 1:
                return ids[0]
            return ids
        if hasattr(value, "id") and not isinstance(
            value, (bool, int, float, str, list, tuple, dict, set)
        ):
            return getattr(value, "id")
        return value

    def _match_like(self, actual, pattern, case_sensitive=False):
        if actual is None:
            return False
        text = str(actual)
        pattern = "" if pattern is None else str(pattern)
        if "%" not in pattern and "_" not in pattern:
            if case_sensitive:
                return pattern in text
            return pattern.lower() in text.lower()

        regex = "^" + re.escape(pattern).replace(r"\%", ".*").replace(r"\_", ".") + "$"
        flags = 0 if case_sensitive else re.IGNORECASE
        return re.match(regex, text, flags) is not None

    def _evaluate_leaf_condition(self, condition, form_data):
        if not self._is_leaf_condition(condition):
            return False

        field_name, operator, expected = condition
        actual = self._normalize_domain_value(self._resolve_field_value(form_data, field_name))
        expected = self._normalize_domain_value(expected)

        if operator in ("=", "=="):
            if expected in (False, None):
                return not bool(actual)
            return actual == expected
        if operator == "=?":
            if expected in (False, None):
                return True
            return actual == expected
        if operator == "!=":
            if expected in (False, None):
                return bool(actual)
            return actual != expected

        if operator in ("in", "not in"):
            expected_values = expected if isinstance(expected, (list, tuple, set)) else [expected]
            if isinstance(actual, (list, tuple, set)):
                matched = any(item in expected_values for item in actual)
            else:
                matched = actual in expected_values
            return matched if operator == "in" else not matched

        if operator in (">", "<", ">=", "<="):
            try:
                if operator == ">":
                    return actual > expected
                if operator == "<":
                    return actual < expected
                if operator == ">=":
                    return actual >= expected
                return actual <= expected
            except Exception:
                return False

        if operator in ("like", "=like"):
            return self._match_like(actual, expected, case_sensitive=True)
        if operator in ("ilike", "=ilike"):
            return self._match_like(actual, expected, case_sensitive=False)
        if operator == "not like":
            return not self._match_like(actual, expected, case_sensitive=True)
        if operator == "not ilike":
            return not self._match_like(actual, expected, case_sensitive=False)
        return False

    def _eval_domain_tokens(self, tokens, index, form_data):
        if index >= len(tokens):
            return False, index

        token = tokens[index]
        if token == "&":
            left, next_index = self._eval_domain_tokens(tokens, index + 1, form_data)
            right, final_index = self._eval_domain_tokens(tokens, next_index, form_data)
            return (left and right), final_index
        if token == "|":
            left, next_index = self._eval_domain_tokens(tokens, index + 1, form_data)
            right, final_index = self._eval_domain_tokens(tokens, next_index, form_data)
            return (left or right), final_index
        if token == "!":
            value, next_index = self._eval_domain_tokens(tokens, index + 1, form_data)
            return (not value), next_index

        return self._evaluate_domain(token, form_data), index + 1

    def _evaluate_domain(self, domain, form_data):
        if isinstance(domain, bool):
            return domain
        if domain in (None, ""):
            return False
        if self._is_leaf_condition(domain):
            return self._evaluate_leaf_condition(domain, form_data)

        if isinstance(domain, (list, tuple)):
            if not domain:
                return True
            operator_tokens = {"&", "|", "!"}
            has_operator = any(isinstance(item, str) and item in operator_tokens for item in domain)

            if not has_operator:
                return all(self._evaluate_domain(item, form_data) for item in domain)

            value, cursor = self._eval_domain_tokens(list(domain), 0, form_data)
            while cursor < len(domain):
                value = value and self._evaluate_domain(domain[cursor], form_data)
                cursor += 1
            return value

        return False

    def evaluate_condition(self, condition, form_data):
        try:
            domain = safe_eval(condition)
            return self._evaluate_domain(domain, form_data or {})
        except Exception:
            return False

    def get_current_buttons(self, element):
        """
        Return list of user-action buttons from current node.
        Works for direct sequence flows and event/gateway indirections.
        """
        source_id = element.attrib['id']
        flows = self.sequence_flows.get(source_id, [])
        buttons = []
        for flow in flows:
            target = self.get_element_by_id(flow['target'])
            if target is None:
                continue
            label = (
                target.attrib.get('name')
                or flow.get('name')
                or target.attrib.get('id')
                or flow.get('id')
            )
            if not label:
                continue
            buttons.append({
                'button_label': label,
                'target_node': target,
                'raw': flow,
            })
        return buttons

    def get_submission_task(self):
        """
        Returns the <bpmn:userTask> element whose name contains 'Submit' or 'Submission'.
        """
        for el in self.process.findall('.//bpmn:userTask', self.ns):
            name = el.attrib.get('name', '').lower()
            if 'submit' in name or 'submission' in name:
                return el
        return None

    def get_node_metadata_profile(self, node_type):
        return NODE_METADATA_PROFILE.get(node_type, {})

    def _build_meta_task(self, el, element_type):
        node_id = el.attrib['id']
        name = el.attrib.get('name')
        description = ''
        doc = el.find('bpmn:documentation', self.ns)
        if doc is not None and doc.text:
            description = doc.text.strip()

        profile = self.get_node_metadata_profile(element_type)
        return {
            'node_id': node_id,
            'name': name,
            'description': description,
            'node_type': element_type,
            'attr_class': '',
            'attr_label': name,
            'element': 'sequence',
            'field_ids': [],
            'approval_group_ids': [],
            'email_template_external_id': '',
            'notification_recipient_ids': [],
            'approval_group_domain': '',
            'notification_recipient_domain': '',
            'node_profile': profile,
        }

    def _build_meta_action(self, source_node_id, source_name, source_node_type, seq, action, target):
        action_type = self.get_element_type(action)
        target_type = self.get_element_type(target)
        target_name = target.attrib.get('name', '')
        flow_type = self.get_action_type(action_type)
        button_label = (
            (action.attrib.get('name') or '').strip()
            or (seq.get('name') or '').strip()
            or target_name
            or seq.get('id')
        )
        return {
            'source_id': source_node_id,
            'source_name': source_name,
            'source_node_type': source_node_type,
            'target_id': target.attrib['id'],
            'target_name': target_name,
            'target_node_type': target_type,
            'node_id': seq['id'],
            'attr_label': button_label,
            'attr_class': seq['custom'].get('attr_class', '') if seq.get('custom') else '',
            'invisible_domain': seq['custom'].get('invisible_domain', '') if seq.get('custom') else '',
            'flow_type': flow_type,
            'domain': seq.get('condition') or '',
        }

    def get_meta_tasks_and_actions(self):
        """
        Returns:
            - meta_tasks: list of dicts for workflow.category.version.meta.task
            - meta_actions: list of dicts for workflow.category.version.meta.task.action
        """
        meta_tasks = []
        meta_actions = []

        for el in self.process.findall('.//*', self.ns):

            element_type = self.get_element_type(el)
            if element_type in SUPPORTED_TASK_NODE_TYPE:
                node_id = el.attrib['id']
                name = el.attrib.get('name')
                meta_tasks.append(self._build_meta_task(el, element_type))

                """
                flow: source ------action------target
                
                An action is considered as user action if:
                - source is user task
                - action is intermediateEventMesseage, intermediateThrowEvent,
                  conditionalEventDefinition, timerEvent
                """
                for seq in self.sequence_flows.get(node_id, []):
                    action = self.get_element_by_id(seq['target'])
                    if action is None or 'id' not in action.attrib:
                        continue
                    target = action
                    meta_actions.append(
                        self._build_meta_action(
                            source_node_id=node_id,
                            source_name=name,
                            source_node_type=element_type,
                            seq=seq,
                            action=action,
                            target=target,
                        )
                    )

        return meta_tasks, meta_actions
    

    # def resolve_group_ids(self, group_xml_csv):
    #     if not group_xml_csv:
    #         return []
    #     xml_ids = group_xml_csv.split(',')
    #     return [self.env.ref(xml_id).id for xml_id in xml_ids if xml_id]

    # def resolve_user_ids(self, user_xml_csv):
    #     if not user_xml_csv:
    #         return []
    #     xml_ids = user_xml_csv.split(',')
    #     return [self.env.ref(xml_id).id for xml_id in xml_ids if xml_id]

    # def execute_service_task(self, node, request):
    #     '''
    #     <bpmn:serviceTask id="AutoGenerateOrder" name="Create Order">
    #         <bpmn:extensionElements>
    #             <custom:code>env['sale.order'].create({'partner_id': request.partner_id.id})</custom:code>
    #         </bpmn:extensionElements>
    #     </bpmn:serviceTask>

    #     '''

    #     code = self.get_custom_extensions(node).get('code')
    #     if not code:
    #         return
    #     localdict = {'env': request.env, 'request': request}
    #     safe_eval(code, localdict, mode="exec")

    # def execute_send_task(self, node, request):
    #     """
    #     Executes email sending defined in <custom:emailTemplate> of a sendTask node.

    #     Args:
    #         node: The BPMN sendTask node element.
    #         request: The `workflow.approval.request` record triggering this.

    #     Raises:
    #         UserError: If email template(s) are not found or sending fails.
    #     """
    #     custom = self.get_custom_extensions(node)
    #     template_ids = custom.get('emailTemplate')

    #     if not template_ids:
    #         raise UserError("No <custom:emailTemplate> defined in the sendTask node.")

    #     sent_templates = []
    #     for xml_id in template_ids.split(','):
    #         xml_id = xml_id.strip()
    #         if not xml_id:
    #             continue
    #         try:
    #             template = request.env.ref(xml_id)
    #             template.send_mail(request.id, force_send=True)
    #             sent_templates.append(xml_id)
    #         except Exception as e:
    #             raise UserError(f"Failed to send email from template '{xml_id}': {e}")

    #     return {"status": "emails_sent", "templates": sent_templates}

      # def get_sequence_flow_type(self, flow):
    #     """
    #     Determine if the sequence flow is a user action or auto action.
    #     """
    #     target_id = flow.attrib['targetRef']
    #     target_element = self.get_element_by_id(target_id)
    #     if target_element.tag in AUTO_NODE_ACTION:
    #         return 'autoAction'
    #     if trget_element.tag in SYSTEM_ACTION:
    #         return 'systemAction'
    #     return 'userAction'

    # def get_element_type_from_node_id(self, element):
    #     ele = self.get_element_by_id(element)
    #     return self.get_element_type(ele)
    
    # def get_dynamic_context(self, element):
    #     """
    #     Get full context:
    #     - request_status (from node name)
    #     - buttons = sequenceFlow names
    #     - visible/required/readonly fields
    #     - etc.
    #     """
    #     return {
    #         # 'status': self.get_status_from_node(element),
    #         # 'buttons': [btn['button_label'] for btn in self.get_current_buttons(element)],
    #         **self.get_workflow_context(element)
    #     }

    # def get_all_sequence_flows(self):
    #     """
    #     Return list of all flows with conditions and custom metadata
    #     """
    #     flows = []
    #     for source_id, items in self.sequence_flows.items():
    #         for seq in items:
    #             flows.append({
    #                 'source': source_id,
    #                 'target': seq['target'],
    #                 'condition': seq['condition'],
    #                 'custom': seq.get('custom', {}),
    #             })
    #     return flows

    # def get_stage_list_for_model(self):
    #     """
    #     Extract all userTasks as stages to be stored in workflow.request.stage
    #     """
    #     stages = []
    #     for el in self.process.findall('.//bpmn:userTask', self.ns):
    #         stages.append({
    #             'id': el.attrib['id'],
    #             'name': el.attrib.get('name'),
    #             'custom': self.get_custom_extensions(el),
    #         })
    #     return stages

    # def get_workflow_metadata(self):

    #     metadata = {'tasks': [], 'sequence_flows': []}

    #     # Extract tasks (userTask, serviceTask, sendTask)
    #     for element in self.process.findall('.//*', self.ns):
    #         element_type = self.get_element_type(element)

    #         # Handle task elements (userTask, serviceTask, sendTask)
    #         if element_type in [NODE_TYPE['START_EVENT'], 'userTask', 'serviceTask', 'sendTask', 'scriptTask', 'endEvent', 'subProcess', 'parallelGateway', 'callActivity',
    #                         'startEventMessage', 'endEventMessage', 'intermediateCatchEvent', 'intermediateThrowEvent', 'timerEvent', ] \
    #                 and element.attrib.get('id') and element.attrib.get('name'):
    #             task_metadata = {
    #                 'name': element.attrib.get('name'),
    #                 'description': element.attrib.get('documentation', ''),
    #                 'node_id': element.attrib.get('id'),
    #                 'node_type': element_type,
    #                 'attr_class': '',  # Placeholder for user input
    #                 'attr_label': '',  # Placeholder for user input
    #                 'element': 'sequence',  # Placeholder for element type
    #                 'field_ids': [],  # Placeholder for user input (fields)
    #                 'approval_group_ids': [],  # Placeholder for user input (approval groups)
    #                 'email_template_external_id': '',  # Placeholder for user input (email template)
    #                 'notification_recipient_ids': [],  # Placeholder for user input (users)
    #                 'domain': '',  # Placeholder for user input (domain rule)
    #             }
    #             metadata['tasks'].append(task_metadata)

    #     # Extract sequence flows
    #     # for flow in self.root.findall('.//bpmn:sequenceFlow', self.ns):
    #     #     sequence_flow_metadata = {
    #     #         'name': flow.attrib.get('name'),
    #     #         'node_id': flow.attrib.get('id'),
    #     #         'source_id': flow.attrib.get('sourceRef'),
    #     #         'source_name': self.get_element_name_by_id(flow.attrib.get('sourceRef')),
    #     #         'source_node_type': self.get_element_type_from_node_id(flow.attrib.get('sourceRef')),
    #     #         'target_id': flow.attrib.get('targetRef'),
    #     #         'target_name': self.get_element_name_by_id(flow.attrib.get('targetRef')),
    #     #         'target_node_type': self.get_element_type_from_node_id(flow.attrib.get('targetRef')),
    #     #         'domain': '',
    #     #     }
    #     #     metadata['sequence_flows'].append(sequence_flow_metadata)

    #     return metadata

    # def _map_incoming_flows(self):
    #     """
    #     Maps sequence flows by target_id so we can get all incoming flows for a node.
    #     """
    #     incoming = {}
    #     for flow in self.root.findall('.//bpmn:sequenceFlow', self.ns):
    #         target = flow.attrib['targetRef']
    #         source = flow.attrib['sourceRef']
    #         condition = flow.find('bpmn:conditionExpression', self.ns)
    #         condition_text = condition.text.strip() if condition is not None and condition.text else None
    #         incoming[target] = incoming.get(target, []) + [{
    #             'id': flow.attrib['id'],
    #             'source': source,
    #             'condition': condition_text,
    #             'custom': self.get_custom_extensions(flow),
    #             'name': flow.attrib.get('name', ''),
    #         }]
    #     return incoming

        # def get_custom_extensions(self, el):
    #     """
    #     Extracts <bpmn:extensionElements> children into a dictionary.
    #     """
    #     if isinstance(el, dict):
    #         return el  # Already parsed
    #     extensions = {}
    #     ext_node = el.find('bpmn:extensionElements', self.ns)
    #     if ext_node is not None:
    #         for child in list(ext_node):
    #             tag = child.tag.split('}')[-1]
    #             extensions[tag] = (child.text or '').strip()
    #     return extensions

    # def get_workflow_context(self, element):
    #     """
    #     Returns a dictionary to populate context for rendering stage-based views.
    #     """
    #     custom = self.get_custom_extensions(element)
    #     return {
    #         'visible_buttons': custom.get('visibleButton', '').split(',') if custom.get('visibleButton') else [],
    #         'required_fields': custom.get('requireFields', '').split(',') if custom.get('requireFields') else [],
    #         'readonly_fields': custom.get('readonlyFields', '').split(',') if custom.get('readonlyFields') else [],
    #         'invisible_fields': custom.get('invisibleFields', '').split(',') if custom.get('invisibleFields') else [],
    #         'user_groups': custom.get('userGroups', '').split(',') if custom.get('userGroups') else [],
    #         'users': custom.get('users', '').split(',') if custom.get('users') else [],
    #         'state': custom.get('state'),
    #     }
