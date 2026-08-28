/** @odoo-module **/

import { Domain } from "@web/core/domain";
import { patch } from "@web/core/utils/patch";
import { user } from "@web/core/user";
import { session } from "@web/session";
import { Record } from "@web/model/relational_model/record";

function _safeString(value) {
    return (value || "").toString();
}

function _buildActorContext(recordEvalContext) {
    const actor = session.workflow_actor || {};
    const actorIsHod = Boolean(actor.is_hod);
    const actorLogin = _safeString(actor.login || "").toLowerCase();
    const actorNameBase = _safeString(actor.name || user.name || "").toLowerCase();
    const actorName = [actorNameBase, actorLogin]
        .filter(Boolean)
        .join(" ");
    const actorDepartment = _safeString(actor.department_name || "").toLowerCase();
    const actorPosition = _safeString(actor.position_name || "").toLowerCase();
    const actorGroups = Array.isArray(actor.group_xmlids) ? actor.group_xmlids : [];
    const actorGroupCsv = actorGroups.length ? `,${actorGroups.join(",")},` : ",";
    const actorUid = actor.user_id || user.userId || recordEvalContext?.uid || 0;

    const managerId = recordEvalContext?.manager_user_id?.id || recordEvalContext?.manager_user_id || false;
    const isManager = Boolean(managerId && Number(managerId) === Number(actorUid));
    const isHod = actorIsHod;
    const actionKey = _safeString(
        recordEvalContext?.wf_action_key ||
            recordEvalContext?.action_key ||
            session.workflow_action_key ||
            ""
    );
    const currentNodeId = _safeString(
        recordEvalContext?.wf_current_node_id ||
            recordEvalContext?.current_node_id ||
            ""
    );

    return {
        wf_actor_uid: actorUid,
        wf_actor_name: actorName,
        wf_actor_login: actorLogin,
        wf_actor_department_name: actorDepartment,
        wf_actor_position_name: actorPosition,
        wf_actor_group_xmlids: actorGroupCsv,
        wf_actor_is_manager: isManager,
        wf_actor_is_hod: isHod,
        wf_action_key: actionKey,
        wf_current_node_id: currentNodeId,

        // Backward compatibility for early domain presets.
        __actor_uid__: actorUid,
        __actor_name__: actorName,
        __actor_login__: actorLogin,
        __actor_department__: actorDepartment,
        __actor_position__: actorPosition,
        __actor_group_xmlids__: actorGroupCsv,
        __actor_is_manager__: isManager,
        __actor_is_hod__: isHod,
        __action_key__: actionKey,
        __current_node_id__: currentNodeId,
    };
}

patch(Record.prototype, {
    _setEvalContext() {
        super._setEvalContext(...arguments);

        const withVirtual = this.evalContextWithVirtualIds || {};
        const actorContext = _buildActorContext(withVirtual);
        const domainCache = this.__wfDomainCache || new Map();
        this.__wfDomainCache = domainCache;

        const wfMatchDomain = (domainExpression) => {
            const expression = typeof domainExpression === "string" ? domainExpression.trim() : domainExpression;
            if (!expression || expression === "[]") {
                return true;
            }
            try {
                const parsed = domainCache.get(expression) || new Domain(expression);
                if (!domainCache.has(expression)) {
                    domainCache.set(expression, parsed);
                }
                const runtimeContext = { ...this.evalContextWithVirtualIds, ...actorContext };
                const evaluatedDomain = parsed.toList(runtimeContext);
                const domain = new Domain(evaluatedDomain);
                return domain.contains(runtimeContext);
            } catch {
                return false;
            }
        };

        Object.assign(this.evalContext, actorContext, {
            wf_match_domain: wfMatchDomain,
        });
        Object.assign(this.evalContextWithVirtualIds, actorContext, {
            wf_match_domain: wfMatchDomain,
        });
    },
});
