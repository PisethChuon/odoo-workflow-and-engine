(function () {
  var HIGH = 2000;
  var MAX_VISIBLE_AVATARS = 4;
  var MORE_BADGE_CAP = 10;

  var APPROVAL_NODE_TYPES = new Set([
    "bpmn:Task",
    "bpmn:UserTask",
    "bpmn:ServiceTask",
    "bpmn:SendTask",
    "bpmn:ScriptTask",
    "bpmn:CallActivity",
    "bpmn:SubProcess",
  ]);

  var VISUAL_NODE_TYPES = new Set([
    "bpmn:Task",
    "bpmn:UserTask",
    "bpmn:ServiceTask",
    "bpmn:SendTask",
    "bpmn:ScriptTask",
    "bpmn:CallActivity",
    "bpmn:SubProcess",
    "bpmn:StartEvent",
    "bpmn:EndEvent",
    "bpmn:IntermediateCatchEvent",
    "bpmn:IntermediateThrowEvent",
    "bpmn:ExclusiveGateway",
    "bpmn:ParallelGateway",
    "bpmn:InclusiveGateway",
    "bpmn:EventBasedGateway",
  ]);

  var NODE_MARKER_CLASSES = [
    "wf-node-shape",
    "wf-node--task",
    "wf-node--user-task",
    "wf-node--service-task",
    "wf-node--send-task",
    "wf-node--script-task",
    "wf-node--call-activity",
    "wf-node--sub-process",
    "wf-node--start-event",
    "wf-node--start-message",
    "wf-node--start-timer",
    "wf-node--start-signal",
    "wf-node--start-conditional",
    "wf-node--end-event",
    "wf-node--end-message",
    "wf-node--end-signal",
    "wf-node--end-terminate",
    "wf-node--intermediate-catch",
    "wf-node--intermediate-catch-message",
    "wf-node--intermediate-catch-timer",
    "wf-node--intermediate-catch-signal",
    "wf-node--intermediate-catch-conditional",
    "wf-node--intermediate-throw",
    "wf-node--intermediate-throw-message",
    "wf-node--intermediate-throw-signal",
    "wf-node--intermediate-throw-escalation",
    "wf-node--exclusive-gateway",
    "wf-node--parallel-gateway",
    "wf-node--inclusive-gateway",
    "wf-node--event-based-gateway",
  ];

  var ACTED_STATUSES = new Set(["approved", "refused", "cancelled"]);
  var PASSIVE_STATUSES = new Set(["closed", "new", "pending", "waiting", "view"]);

  function ensureOverlayStyles() {
    if (document.getElementById("bpmn-overlay-fallback-css")) return;
    var css = ""
      + ".djs-overlays{position:absolute;top:0;left:0;overflow:visible;pointer-events:none}"
      + ".djs-overlays>div{position:absolute;pointer-events:auto}"
      + ".wf-approver-stack{display:flex;align-items:center;position:relative;filter:drop-shadow(0 2px 8px rgba(15,23,42,.18))}"
      + ".wf-approver{width:26px;height:26px;border-radius:999px;position:relative;display:flex;align-items:center;justify-content:center;overflow:hidden;border:2px solid #fff;background:#cbd5e1;box-shadow:0 0 0 1px rgba(15,23,42,.16);transition:opacity .2s ease,transform .2s ease,filter .2s ease}"
      + ".wf-approver+.wf-approver{margin-left:-9px}"
      + ".wf-approver img{width:100%;height:100%;object-fit:cover}"
      + ".wf-approver__fallback{font:700 10px/1 Inter,Segoe UI,Arial,sans-serif;color:#fff;background:#64748b;width:100%;height:100%;display:flex;align-items:center;justify-content:center}"
      + ".wf-approver--acted{box-shadow:0 0 0 2px #14b8a6,0 0 0 1px rgba(15,23,42,.12)}"
      + ".wf-approver--approved{box-shadow:0 0 0 2px #22c55e,0 0 0 1px rgba(15,23,42,.12)}"
      + ".wf-approver--refused,.wf-approver--cancelled{box-shadow:0 0 0 2px #ef4444,0 0 0 1px rgba(15,23,42,.12)}"
      + ".wf-approver--inactive{opacity:.42;filter:grayscale(.65)}"
      + ".wf-approver--pending{opacity:.7;filter:grayscale(.2)}"
      + ".wf-approver__status{position:absolute;right:-3px;bottom:-3px;width:12px;height:12px;border-radius:999px;border:1.5px solid #fff;display:flex;align-items:center;justify-content:center;font:700 8px/1 Inter,Segoe UI,Arial,sans-serif;color:#fff}"
      + ".wf-approver__status--approved{background:#16a34a}"
      + ".wf-approver__status--refused,.wf-approver__status--cancelled{background:#dc2626}"
      + ".wf-approver__status--closed{background:#64748b}"
      + ".wf-approver-more{width:26px;height:26px;border-radius:999px;border:2px solid #fff;background:#e2e8f0;color:#0f172a;font:700 10px/1 Inter,Segoe UI,Arial,sans-serif;display:flex;align-items:center;justify-content:center;box-shadow:0 0 0 1px rgba(15,23,42,.16)}"
      + ".wf-approver-more+.wf-approver,.wf-approver+.wf-approver-more{margin-left:-9px}"
      + ".wf-node-badge{width:14px;height:14px;border-radius:4px;display:flex;align-items:center;justify-content:center;border:1px solid rgba(15,23,42,.2);background:#ffffff;color:#0f172a;box-shadow:0 3px 8px rgba(15,23,42,.14);pointer-events:none}"
      + ".wf-node-badge i{font-size:7px;line-height:1}"
      + ".wf-node-badge--start,.wf-node-badge--catch,.wf-node-badge--throw{background:#eff6ff;color:#1d4ed8;border-color:rgba(37,99,235,.26)}"
      + ".wf-node-badge--end{background:#fff1f2;color:#be123c;border-color:rgba(225,29,72,.26)}"
      + ".wf-node-badge--user-task,.wf-node-badge--task{background:#eef2ff;color:#4338ca;border-color:rgba(67,56,202,.25)}"
      + ".wf-node-badge--service-task,.wf-node-badge--script-task{background:#ecfeff;color:#0f766e;border-color:rgba(13,148,136,.25)}"
      + ".wf-node-badge--send-task{background:#ecfdf5;color:#047857;border-color:rgba(4,120,87,.25)}"
      + ".wf-node-badge--call-activity,.wf-node-badge--sub-process{background:#fff7ed;color:#b45309;border-color:rgba(234,88,12,.24)}"
      + ".wf-node-badge--gateway{background:#fff7ed;color:#c2410c;border-color:rgba(194,65,12,.25)}"
      + "html[data-theme='dark'] .wf-approver-more,body.o_dark .wf-approver-more,body.o_web_client.o_dark .wf-approver-more,body.o_web_client.o_web_dark .wf-approver-more,html[data-bs-theme='dark'] .wf-approver-more,body[data-bs-theme='dark'] .wf-approver-more,[data-bs-theme='dark'] .wf-approver-more{background:#334155;color:#e2e8f0;box-shadow:0 0 0 1px rgba(226,232,240,.2)}"
      + "html[data-theme='dark'] .wf-node-badge,body.o_dark .wf-node-badge,body.o_web_client.o_dark .wf-node-badge,body.o_web_client.o_web_dark .wf-node-badge,html[data-bs-theme='dark'] .wf-node-badge,body[data-bs-theme='dark'] .wf-node-badge,[data-bs-theme='dark'] .wf-node-badge{background:#111827;color:#f1f5f9;border-color:rgba(148,163,184,.35);box-shadow:0 6px 16px rgba(2,6,23,.42)}"
      + "html[data-theme='dark'] .wf-node-badge--start,html[data-theme='dark'] .wf-node-badge--catch,html[data-theme='dark'] .wf-node-badge--throw,body.o_dark .wf-node-badge--start,body.o_dark .wf-node-badge--catch,body.o_dark .wf-node-badge--throw,body.o_web_client.o_dark .wf-node-badge--start,body.o_web_client.o_dark .wf-node-badge--catch,body.o_web_client.o_dark .wf-node-badge--throw,body.o_web_client.o_web_dark .wf-node-badge--start,body.o_web_client.o_web_dark .wf-node-badge--catch,body.o_web_client.o_web_dark .wf-node-badge--throw,html[data-bs-theme='dark'] .wf-node-badge--start,html[data-bs-theme='dark'] .wf-node-badge--catch,html[data-bs-theme='dark'] .wf-node-badge--throw,body[data-bs-theme='dark'] .wf-node-badge--start,body[data-bs-theme='dark'] .wf-node-badge--catch,body[data-bs-theme='dark'] .wf-node-badge--throw,[data-bs-theme='dark'] .wf-node-badge--start,[data-bs-theme='dark'] .wf-node-badge--catch,[data-bs-theme='dark'] .wf-node-badge--throw{background:#1e293b;color:#7dd3fc;border-color:rgba(125,211,252,.34)}"
      + "html[data-theme='dark'] .wf-node-badge--end,body.o_dark .wf-node-badge--end,body.o_web_client.o_dark .wf-node-badge--end,body.o_web_client.o_web_dark .wf-node-badge--end,html[data-bs-theme='dark'] .wf-node-badge--end,body[data-bs-theme='dark'] .wf-node-badge--end,[data-bs-theme='dark'] .wf-node-badge--end{background:#3f1d2e;color:#fda4af;border-color:rgba(251,113,133,.34)}"
      + "html[data-theme='dark'] .wf-node-badge--user-task,html[data-theme='dark'] .wf-node-badge--task,body.o_dark .wf-node-badge--user-task,body.o_dark .wf-node-badge--task,body.o_web_client.o_dark .wf-node-badge--user-task,body.o_web_client.o_dark .wf-node-badge--task,body.o_web_client.o_web_dark .wf-node-badge--user-task,body.o_web_client.o_web_dark .wf-node-badge--task,html[data-bs-theme='dark'] .wf-node-badge--user-task,html[data-bs-theme='dark'] .wf-node-badge--task,body[data-bs-theme='dark'] .wf-node-badge--user-task,body[data-bs-theme='dark'] .wf-node-badge--task,[data-bs-theme='dark'] .wf-node-badge--user-task,[data-bs-theme='dark'] .wf-node-badge--task{background:#1f2448;color:#c7d2fe;border-color:rgba(129,140,248,.34)}"
      + "html[data-theme='dark'] .wf-node-badge--service-task,html[data-theme='dark'] .wf-node-badge--script-task,body.o_dark .wf-node-badge--service-task,body.o_dark .wf-node-badge--script-task,body.o_web_client.o_dark .wf-node-badge--service-task,body.o_web_client.o_dark .wf-node-badge--script-task,body.o_web_client.o_web_dark .wf-node-badge--service-task,body.o_web_client.o_web_dark .wf-node-badge--script-task,html[data-bs-theme='dark'] .wf-node-badge--service-task,html[data-bs-theme='dark'] .wf-node-badge--script-task,body[data-bs-theme='dark'] .wf-node-badge--service-task,body[data-bs-theme='dark'] .wf-node-badge--script-task,[data-bs-theme='dark'] .wf-node-badge--service-task,[data-bs-theme='dark'] .wf-node-badge--script-task{background:#11323f;color:#99f6e4;border-color:rgba(45,212,191,.34)}"
      + "html[data-theme='dark'] .wf-node-badge--send-task,body.o_dark .wf-node-badge--send-task,body.o_web_client.o_dark .wf-node-badge--send-task,body.o_web_client.o_web_dark .wf-node-badge--send-task,html[data-bs-theme='dark'] .wf-node-badge--send-task,body[data-bs-theme='dark'] .wf-node-badge--send-task,[data-bs-theme='dark'] .wf-node-badge--send-task{background:#133729;color:#86efac;border-color:rgba(74,222,128,.32)}"
      + "html[data-theme='dark'] .wf-node-badge--call-activity,html[data-theme='dark'] .wf-node-badge--sub-process,html[data-theme='dark'] .wf-node-badge--gateway,body.o_dark .wf-node-badge--call-activity,body.o_dark .wf-node-badge--sub-process,body.o_dark .wf-node-badge--gateway,body.o_web_client.o_dark .wf-node-badge--call-activity,body.o_web_client.o_dark .wf-node-badge--sub-process,body.o_web_client.o_dark .wf-node-badge--gateway,body.o_web_client.o_web_dark .wf-node-badge--call-activity,body.o_web_client.o_web_dark .wf-node-badge--sub-process,body.o_web_client.o_web_dark .wf-node-badge--gateway,html[data-bs-theme='dark'] .wf-node-badge--call-activity,html[data-bs-theme='dark'] .wf-node-badge--sub-process,html[data-bs-theme='dark'] .wf-node-badge--gateway,body[data-bs-theme='dark'] .wf-node-badge--call-activity,body[data-bs-theme='dark'] .wf-node-badge--sub-process,body[data-bs-theme='dark'] .wf-node-badge--gateway,[data-bs-theme='dark'] .wf-node-badge--call-activity,[data-bs-theme='dark'] .wf-node-badge--sub-process,[data-bs-theme='dark'] .wf-node-badge--gateway{background:#3a2a16;color:#fdba74;border-color:rgba(251,146,60,.34)}"
      + "@media (max-width: 767px){.wf-node-badge{width:12px;height:12px;border-radius:3px}.wf-node-badge i{font-size:6px}}";
    var styleNode = document.createElement("style");
    styleNode.id = "bpmn-overlay-fallback-css";
    styleNode.type = "text/css";
    styleNode.appendChild(document.createTextNode(css));
    document.head.appendChild(styleNode);
  }

  function initialsFromName(name) {
    if (!name) return "??";
    var parts = String(name).trim().split(/\s+/).slice(0, 2);
    return parts.map(function (part) { return (part && part[0]) || ""; }).join("").toUpperCase();
  }

  function normalizeStatus(status) {
    return String(status || "").toLowerCase();
  }

  function statusPriority(status) {
    if (status === "approved") return 1;
    if (status === "refused" || status === "cancelled") return 2;
    if (status === "pending" || status === "waiting") return 3;
    if (status === "new" || status === "view") return 4;
    if (status === "closed") return 5;
    return 6;
  }

  function normalizeApprover(item) {
    if (!item) return null;
    if (typeof item === "string") {
      return {
        avatar_url: item,
        user_name: "",
        status: "pending",
        decision: "",
      };
    }
    if (typeof item !== "object") return null;
    return {
      avatar_url: item.avatar_url || item.url || "",
      avatar_fallback_url: item.avatar_fallback_url || "",
      user_name: item.user_name || item.name || "",
      status: normalizeStatus(item.status),
      decision: item.decision || "",
      approver_id: item.approver_id || null,
      user_id: item.user_id || null,
    };
  }

  function makeStatusBadge(approver) {
    var status = approver.status;
    var hasDecision = !!(approver.decision && String(approver.decision).trim());
    if (!["approved", "refused", "cancelled", "closed"].includes(status) && !hasDecision) {
      return null;
    }
    var badge = document.createElement("div");
    var text = "";
    var badgeClass = "";
    if (status === "approved") {
      text = "\u2713";
      badgeClass = "wf-approver__status--approved";
    } else if (status === "closed") {
      text = "\u00b7";
      badgeClass = "wf-approver__status--closed";
    } else if (status === "refused" || status === "cancelled") {
      text = "!";
      badgeClass = "wf-approver__status--refused";
    } else {
      text = "\u2713";
      badgeClass = "wf-approver__status--approved";
    }
    badge.className = "wf-approver__status " + badgeClass;
    badge.textContent = text;
    return badge;
  }

  function makeFallbackAvatar(approver) {
    var fallbackNode = document.createElement("div");
    fallbackNode.className = "wf-approver__fallback";
    fallbackNode.textContent = initialsFromName(approver.user_name);
    return fallbackNode;
  }

  function makeApproverNode(approver, hasActedUserInNode) {
    var element = document.createElement("div");
    var status = approver.status;
    var classNames = ["wf-approver"];
    var hasDecision = !!(approver.decision && String(approver.decision).trim());

    if (ACTED_STATUSES.has(status) || hasDecision) {
      classNames.push("wf-approver--acted");
      if (status === "approved") {
        classNames.push("wf-approver--approved");
      } else if (status === "refused" || status === "cancelled") {
        classNames.push("wf-approver--refused");
      } else {
        classNames.push("wf-approver--approved");
      }
    } else if (hasActedUserInNode && PASSIVE_STATUSES.has(status)) {
      classNames.push("wf-approver--inactive");
    } else if (status === "pending" || status === "waiting" || status === "new" || status === "view") {
      classNames.push("wf-approver--pending");
    }

    element.className = classNames.join(" ");
    element.title = (approver.user_name || "Approver") + (status ? " - " + status : "");

    if (approver.avatar_url) {
      var imageNode = document.createElement("img");
      imageNode.src = approver.avatar_url;
      imageNode.alt = approver.user_name || "Approver";
      var fallbackTried = false;
      imageNode.addEventListener("error", function () {
        if (!imageNode.parentNode) return;
        if (!fallbackTried && approver.avatar_fallback_url) {
          fallbackTried = true;
          imageNode.src = approver.avatar_fallback_url;
          return;
        }
        imageNode.remove();
        if (!element.querySelector(".wf-approver__fallback")) {
          element.appendChild(makeFallbackAvatar(approver));
        }
      });
      element.appendChild(imageNode);
    } else {
      element.appendChild(makeFallbackAvatar(approver));
    }

    var badge = makeStatusBadge(approver);
    if (badge) element.appendChild(badge);

    return element;
  }

  function makeMoreBadgeNode(hiddenCount, nodeId, eventBus) {
    var element = document.createElement("div");
    var badgeText = hiddenCount >= MORE_BADGE_CAP ? "10+" : ("+" + hiddenCount);
    element.className = "wf-approver-more";
    element.textContent = badgeText;
    element.title = hiddenCount + " more approvers";
    element.style.cursor = "pointer";
    element.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      if (eventBus && nodeId) {
        eventBus.fire("custom.avatars:more", { node_id: nodeId });
      }
    });
    return element;
  }

  function isApprovalNode(element) {
    return APPROVAL_NODE_TYPES.has(element && element.type);
  }

  function isVisualNode(element) {
    return VISUAL_NODE_TYPES.has(element && element.type);
  }

  function sortApprovers(approvers) {
    return approvers.slice().sort(function (a, b) {
      var statusDelta = statusPriority(a.status) - statusPriority(b.status);
      if (statusDelta !== 0) return statusDelta;
      return String(a.user_name || "").localeCompare(String(b.user_name || ""));
    });
  }

  function getEventDefinitionType(element) {
    var defs = element && element.businessObject && element.businessObject.eventDefinitions;
    if (!defs || !defs.length) {
      return "";
    }
    var raw = String(defs[0].$type || "");
    return raw.replace(/^bpmn:/, "");
  }

  function getNodeVisualMeta(element) {
    if (!element || !element.type) {
      return null;
    }

    var eventType = getEventDefinitionType(element);

    if (element.type === "bpmn:UserTask") {
      return { markerClass: "wf-node--user-task", badgeClass: "wf-node-badge--user-task", iconClass: "fa-user", label: "User Task" };
    }
    if (element.type === "bpmn:Task") {
      return { markerClass: "wf-node--task", badgeClass: "wf-node-badge--task", iconClass: "fa-check-square-o", label: "Task" };
    }
    if (element.type === "bpmn:ServiceTask") {
      return { markerClass: "wf-node--service-task", badgeClass: "wf-node-badge--service-task", iconClass: "fa-cogs", label: "Service Task" };
    }
    if (element.type === "bpmn:SendTask") {
      return { markerClass: "wf-node--send-task", badgeClass: "wf-node-badge--send-task", iconClass: "fa-paper-plane-o", label: "Send Task" };
    }
    if (element.type === "bpmn:ScriptTask") {
      return { markerClass: "wf-node--script-task", badgeClass: "wf-node-badge--script-task", iconClass: "fa-code", label: "Script Task" };
    }
    if (element.type === "bpmn:CallActivity") {
      return { markerClass: "wf-node--call-activity", badgeClass: "wf-node-badge--call-activity", iconClass: "fa-clone", label: "Call Activity" };
    }
    if (element.type === "bpmn:SubProcess") {
      return { markerClass: "wf-node--sub-process", badgeClass: "wf-node-badge--sub-process", iconClass: "fa-sitemap", label: "Sub Process" };
    }

    if (element.type === "bpmn:StartEvent") {
      if (eventType === "MessageEventDefinition") {
        return { markerClass: "wf-node--start-message", badgeClass: "wf-node-badge--start", iconClass: "fa-hand-pointer-o", label: "Start Action" };
      }
      if (eventType === "TimerEventDefinition") {
        return { markerClass: "wf-node--start-timer", badgeClass: "wf-node-badge--start", iconClass: "fa-clock-o", label: "Start Timer" };
      }
      if (eventType === "SignalEventDefinition") {
        return { markerClass: "wf-node--start-signal", badgeClass: "wf-node-badge--start", iconClass: "fa-bullhorn", label: "Start Signal" };
      }
      if (eventType === "ConditionalEventDefinition") {
        return { markerClass: "wf-node--start-conditional", badgeClass: "wf-node-badge--start", iconClass: "fa-filter", label: "Start Condition" };
      }
      return { markerClass: "wf-node--start-event", badgeClass: "wf-node-badge--start", iconClass: "fa-play", label: "Start" };
    }

    if (element.type === "bpmn:EndEvent") {
      if (eventType === "MessageEventDefinition") {
        return { markerClass: "wf-node--end-message", badgeClass: "wf-node-badge--end", iconClass: "fa-hand-pointer-o", label: "End Action" };
      }
      if (eventType === "SignalEventDefinition") {
        return { markerClass: "wf-node--end-signal", badgeClass: "wf-node-badge--end", iconClass: "fa-bullhorn", label: "End Signal" };
      }
      if (eventType === "TerminateEventDefinition") {
        return { markerClass: "wf-node--end-terminate", badgeClass: "wf-node-badge--end", iconClass: "fa-stop-circle-o", label: "Terminate" };
      }
      return { markerClass: "wf-node--end-event", badgeClass: "wf-node-badge--end", iconClass: "fa-stop", label: "End" };
    }

    if (element.type === "bpmn:IntermediateCatchEvent") {
      if (eventType === "MessageEventDefinition") {
        return { markerClass: "wf-node--intermediate-catch-message", badgeClass: "wf-node-badge--catch", iconClass: "fa-hand-pointer-o", label: "User Action" };
      }
      if (eventType === "TimerEventDefinition") {
        return { markerClass: "wf-node--intermediate-catch-timer", badgeClass: "wf-node-badge--catch", iconClass: "fa-clock-o", label: "Wait Timer" };
      }
      if (eventType === "SignalEventDefinition") {
        return { markerClass: "wf-node--intermediate-catch-signal", badgeClass: "wf-node-badge--catch", iconClass: "fa-bell-o", label: "Wait Signal" };
      }
      if (eventType === "ConditionalEventDefinition") {
        return { markerClass: "wf-node--intermediate-catch-conditional", badgeClass: "wf-node-badge--catch", iconClass: "fa-filter", label: "Wait Condition" };
      }
      return { markerClass: "wf-node--intermediate-catch", badgeClass: "wf-node-badge--catch", iconClass: "fa-dot-circle-o", label: "Intermediate Catch" };
    }

    if (element.type === "bpmn:IntermediateThrowEvent") {
      if (eventType === "MessageEventDefinition") {
        return { markerClass: "wf-node--intermediate-throw-message", badgeClass: "wf-node-badge--throw", iconClass: "fa-hand-pointer-o", label: "Action Result" };
      }
      if (eventType === "SignalEventDefinition") {
        return { markerClass: "wf-node--intermediate-throw-signal", badgeClass: "wf-node-badge--throw", iconClass: "fa-bullhorn", label: "Throw Signal" };
      }
      if (eventType === "EscalationEventDefinition") {
        return { markerClass: "wf-node--intermediate-throw-escalation", badgeClass: "wf-node-badge--throw", iconClass: "fa-level-up", label: "Escalation" };
      }
      return { markerClass: "wf-node--intermediate-throw", badgeClass: "wf-node-badge--throw", iconClass: "fa-share", label: "Intermediate Throw" };
    }

    if (element.type === "bpmn:ExclusiveGateway") {
      return { markerClass: "wf-node--exclusive-gateway", badgeClass: "wf-node-badge--gateway", iconClass: "fa-random", label: "Exclusive Gateway" };
    }
    if (element.type === "bpmn:ParallelGateway") {
      return { markerClass: "wf-node--parallel-gateway", badgeClass: "wf-node-badge--gateway", iconClass: "fa-plus", label: "Parallel Gateway" };
    }
    if (element.type === "bpmn:InclusiveGateway") {
      return { markerClass: "wf-node--inclusive-gateway", badgeClass: "wf-node-badge--gateway", iconClass: "fa-circle-o-notch", label: "Inclusive Gateway" };
    }
    if (element.type === "bpmn:EventBasedGateway") {
      return { markerClass: "wf-node--event-based-gateway", badgeClass: "wf-node-badge--gateway", iconClass: "fa-bolt", label: "Event Gateway" };
    }

    return null;
  }

  function clearNodeMarkerClasses(gfx) {
    if (!gfx || !gfx.classList) {
      return;
    }
    NODE_MARKER_CLASSES.forEach(function (className) {
      gfx.classList.remove(className);
    });
  }

  function applyNodeVisualClass(gfx, visualMeta) {
    if (!gfx || !gfx.classList) {
      return;
    }
    clearNodeMarkerClasses(gfx);
    if (!visualMeta || !visualMeta.markerClass) {
      return;
    }
    gfx.classList.add("wf-node-shape");
    gfx.classList.add(visualMeta.markerClass);
  }

  function applyNodeGeometry(gfx, element) {
    if (!gfx || !gfx.querySelector) {
      return;
    }

    var visual = gfx.querySelector(".djs-visual");
    if (!visual) {
      return;
    }

    var rect = visual.querySelector("rect");
    var circle = visual.querySelector("circle");
    var polygon = visual.querySelector("polygon");
    var path = visual.querySelector("path");
    var type = String((element && element.type) || "");

    if (rect) {
      if (
        type === "bpmn:Task"
        || type === "bpmn:UserTask"
        || type === "bpmn:ServiceTask"
        || type === "bpmn:SendTask"
        || type === "bpmn:ScriptTask"
      ) {
        rect.setAttribute("rx", "14");
        rect.setAttribute("ry", "14");
      } else if (type === "bpmn:CallActivity" || type === "bpmn:SubProcess") {
        rect.setAttribute("rx", "16");
        rect.setAttribute("ry", "16");
      }
      rect.setAttribute("stroke-linejoin", "round");
    }

    if (circle) {
      circle.setAttribute("stroke-linecap", "round");
      circle.setAttribute("stroke-linejoin", "round");
    }

    if (polygon) {
      polygon.setAttribute("stroke-linejoin", "round");
    }

    if (path) {
      path.setAttribute("stroke-linecap", "round");
      path.setAttribute("stroke-linejoin", "round");
    }
  }

  function applyConnectionGeometry(gfx) {
    if (!gfx || !gfx.classList || !gfx.querySelector) {
      return;
    }
    gfx.classList.add("wf-connection");
    var visual = gfx.querySelector(".djs-visual");
    if (!visual) {
      return;
    }
    var path = visual.querySelector("path");
    if (!path) {
      return;
    }
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
  }

  function makeNodeBadgeNode(visualMeta) {
    if (!visualMeta) {
      return null;
    }
    var badge = document.createElement("div");
    badge.className = "wf-node-badge " + (visualMeta.badgeClass || "");
    badge.setAttribute("title", visualMeta.label || "Workflow Node");
    badge.setAttribute("aria-hidden", "true");

    var icon = document.createElement("i");
    icon.className = "fa " + (visualMeta.iconClass || "fa-circle-o");
    badge.appendChild(icon);

    return badge;
  }

  function getBadgePosition(element) {
    var type = String((element && element.type) || "");
    var width = Number((element && element.width) || 0);

    if (type.indexOf("Event") !== -1 || type.indexOf("Gateway") !== -1) {
      return {
        top: -7,
        left: Math.max(Math.round(width / 2) - 7, 0),
      };
    }

    return {
      top: 4,
      left: 4,
    };
  }

  function CustomRenderer(eventBus, bpmnRenderer, overlays, elementRegistry, myData) {
    ensureOverlayStyles();

    var byId = Object.create(null);
    var avatarOverlayIdByNode = Object.create(null);
    var badgeOverlayIdByNode = Object.create(null);

    function removeOverlayForNode(map, nodeId) {
      var overlayId = map[nodeId];
      if (!overlayId) {
        return;
      }
      overlays.remove(overlayId);
      delete map[nodeId];
    }

    function index(list) {
      byId = Object.create(null);
      if (!Array.isArray(list)) {
        return;
      }
      list.forEach(function (row) {
        if (!row || !row.node_id) {
          return;
        }
        var normalizedApprovers = Array.isArray(row.approvers)
          ? sortApprovers(row.approvers.map(normalizeApprover).filter(Boolean))
          : [];
        byId[row.node_id] = {
          approvers: normalizedApprovers,
        };
      });
    }

    function renderAvatarOverlay(element) {
      removeOverlayForNode(avatarOverlayIdByNode, element.id);

      var row = byId[element.id];
      var list = row && Array.isArray(row.approvers) ? row.approvers : [];
      if (!list.length) {
        return;
      }

      var hasActedUserInNode = list.some(function (approver) {
        return ACTED_STATUSES.has(approver.status) || !!(approver.decision && String(approver.decision).trim());
      });
      var visible = list.slice(0, MAX_VISIBLE_AVATARS);
      var hiddenCount = Math.max(0, list.length - MAX_VISIBLE_AVATARS);

      var stack = document.createElement("div");
      stack.className = "wf-approver-stack";

      visible.forEach(function (approver) {
        stack.appendChild(makeApproverNode(approver, hasActedUserInNode));
      });

      if (hiddenCount > 0) {
        stack.appendChild(makeMoreBadgeNode(hiddenCount, element.id, eventBus));
      }

      var visibleCount = visible.length + (hiddenCount > 0 ? 1 : 0);
      var overlayWidth = visibleCount > 0 ? (visibleCount * 17 + 10) : 26;
      avatarOverlayIdByNode[element.id] = overlays.add(element, {
        position: {
          top: -17,
          left: (element.width / 2) - Math.round(overlayWidth / 2),
        },
        html: stack,
        scale: true,
      });
    }

    function renderNodeBadgeOverlay(element) {
      removeOverlayForNode(badgeOverlayIdByNode, element.id);

      var visualMeta = getNodeVisualMeta(element);
      if (!visualMeta) {
        return;
      }

      var badge = makeNodeBadgeNode(visualMeta);
      if (!badge) {
        return;
      }

      badgeOverlayIdByNode[element.id] = overlays.add(element, {
        position: getBadgePosition(element),
        html: badge,
        scale: false,
      });
    }

    function refreshElement(element) {
      if (!element || element.type === "label") {
        return;
      }
      if (isVisualNode(element)) {
        renderNodeBadgeOverlay(element);
      } else {
        removeOverlayForNode(badgeOverlayIdByNode, element.id);
      }
      if (isApprovalNode(element)) {
        renderAvatarOverlay(element);
      } else {
        removeOverlayForNode(avatarOverlayIdByNode, element.id);
      }
    }

    function refreshAll() {
      elementRegistry.filter(function (element) {
        return element && element.type !== "label" && (isVisualNode(element) || isApprovalNode(element));
      }).forEach(function (element) {
        refreshElement(element);
      });
    }

    index(myData);

    eventBus.on("render.shape", HIGH, function (event, context) {
      var element = context.element;
      var shape = bpmnRenderer.drawShape(context.gfx, element);
      applyNodeVisualClass(context.gfx, getNodeVisualMeta(element));
      applyNodeGeometry(context.gfx, element);
      refreshElement(element);
      return shape;
    });

    eventBus.on("render.connection", HIGH, function (event, context) {
      var connection = bpmnRenderer.drawConnection(context.gfx, context.element);
      applyConnectionGeometry(context.gfx);
      return connection;
    });

    eventBus.on("elements.changed", function (eventData) {
      var elements = (eventData && eventData.elements) || [];
      elements.forEach(function (element) {
        refreshElement(element);
      });
    });

    eventBus.on("custom.avatars:set", function (eventData) {
      index(eventData && eventData.data);
      refreshAll();
    });
  }

  CustomRenderer.$inject = ["eventBus", "bpmnRenderer", "overlays", "elementRegistry", "myData"];

  window.CustomRendererModule = function (myData) {
    return {
      __init__: ["customRenderer"],
      customRenderer: ["type", CustomRenderer],
      myData: ["value", myData],
    };
  };
})();
