/** @odoo-module **/

import {registry} from "@web/core/registry";
import {Component, onMounted, onWillUnmount, useRef, useEffect, useState, onWillStart} from "@odoo/owl";
import {standardFieldProps} from "@web/views/fields/standard_field_props";
import {AssetsLoadingError, loadJS} from "@web/core/assets";
import {useBus, useService} from "@web/core/utils/hooks";

const BPMN_VIEWER_LIB_URL = "/workflow_engine/static/lib/bpmn-js/bpmn-navigated-viewer.production.min.js";
const BPMN_OVERLAY_VERSION = "20260304_01";

export class BpmnWidget extends Component {
    static template = "workflow_engine.BpmnWidget";
    static props = {
        ...standardFieldProps,
        name: {type: String, optional: true},
        record: {type: Object, optional: true},
        data: {type: Object, optional: true}
    };

    setup() {
        this.root = useRef("root");
        this.viewer = null;
        // Initialise isDarkTheme synchronously so the very first render already
        // applies wf-theme-dark, preventing the white-canvas flash on open.
        this.state = useState({
            mountedDone: false,
            isFullscreen: false,
            isDarkTheme: this._detectDarkMode(),
            dockExpanded: false,
        });
        this._ro = null;
        this._themeObserver = null;
        this._themeMedia = null;
        this._themeMediaHandler = null;
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.orm = useService("orm");
        this.bus = useService("bus_service");
        this._bpmnViewerConstructor = null;
        this._allowedMetaTaskIds = null;
        this._metaTaskNodeById = null;
        this._miniRequestId = null;
        this._miniBusChannel = null;
        this._miniBusCallback = null;
        this._miniRefreshTimer = null;
        this._diagramSequenceFlows = [];
        this._diagramOutgoingBySource = new Map();
        this._flowRouteCache = new Map();
        this._activeMarkers = new Map();
        this._currentNodeOverlayByNodeId = new Map();
        this._refreshDecorationsRaf = null;
        this._lastMarkerSignature = "";
        this._lastAvatarSignature = "";
        this._lastLabelContrastSignature = "";
        this._fitRaf = null;
        this._fitResizeTimer = null;
        this._resizeHandler = () => this._scheduleFitAndCenter();

        // Prefer explicit data prop; fall back to record.data (works in both field + dialog)
        this.data = this.props.data || this.props.record?.data || {};

        useBus(this.env.bus, "WF-REQUEST:MINI-UPDATE", (ev) => {
            const payload = ev?.detail || {};
            if (!this._miniRequestId || Number(payload.request_id) !== Number(this._miniRequestId)) {
                return;
            }
            this._scheduleMiniSnapshotRefresh();
        });

        onWillStart(async () => {
            try {
                await this._loadAllowedMetaTaskIds();
                await this._registerMiniUpdateChannel();
                await Promise.all([
                    loadJS(`/workflow_engine/static/lib/bpmn-js/custom_bpmn_renderer.js?v=${BPMN_OVERLAY_VERSION}`),
                    loadJS(`/workflow_engine/static/lib/bpmn-js/mobile_touch.js?v=${BPMN_OVERLAY_VERSION}`),
                ]);
                this._bpmnViewerConstructor = await this._ensureViewerConstructor();
            } catch (error) {
                if (!(error instanceof AssetsLoadingError)) throw error;
            }
        });

        onMounted(async () => {
            const ViewerCtor = this._bpmnViewerConstructor || this._resolveBpmnViewerConstructor();
            if (!ViewerCtor) {
                console.error("BPMN viewer constructor is unavailable.");
                return;
            }
            if (!window.CustomRendererModule) {
                console.error("CustomRendererModule not found on window.");
                return;
            }

            // Build avatar data once (also sent later via eventBus)
            const overlays = this._collectAvatarData();

            // Create touch-friendly viewer (pinch-to-zoom + drag)
            this.viewer = new ViewerCtor({
                container: this.root.el,
                additionalModules: [
                    window.CustomRendererModule(overlays),
                    window.MobileTouchModule(),
                ],
                zoomScroll: {enabled: true},
                moveCanvas: {enabled: true},
            });
            this._hideEditingControls();
            this._startEditingControlsObserver();
            this._startThemeObserver();
            this._syncThemeMode();

            // Render XML
            const xml = this.data.bpmn_xml || this.props.record?.data?.[this.props.name] || this.data.xml;
            if (xml) {
                try {
                    await this.viewer.importXML(xml);
                    const eventBus = this.viewer.get("eventBus");
                    const handler = (event) => {
                        const element = event.element;
                        if (!element || !element.id) return;
                        if (element.type === "label") return;
                        this._onNodeClick(element);
                    };
                    eventBus.on("element.click", handler);
                    eventBus.on("element.tap", handler);
                    eventBus.on("custom.avatars:more", (evt) => {
                        const nodeId = evt?.node_id;
                        if (!nodeId) {
                            return;
                        }
                        const registry = this.viewer?.get("elementRegistry");
                        const target = registry?.get(nodeId);
                        if (target) {
                            this._onNodeClick(target);
                        }
                    });
                    // enable smooth touch in modal
                    const canvas = this.viewer.get("canvas");
                    const el = canvas.getContainer();
                    el.style.touchAction = "none";
                    // el.addEventListener("touchstart", (ev) => ev.preventDefault(), {passive: false});

                    await this.fitAndCenter();
                } catch (err) {
                    console.error("BPMN import failed", err);
                } finally {
                    this._buildDiagramCache();
                    this.state.mountedDone = true;
                }
            }

            // Keep it fitted on container resize / orientation change
            this._ro = new ResizeObserver(() => this._scheduleFitAndCenter());
            this._ro.observe(this.root.el);
            window.addEventListener("resize", this._resizeHandler, {passive: true});
            this._fullscreenChangeHandler = () => {
                this.state.isFullscreen = this._fullscreenOwnerEl
                    ? document.fullscreenElement === this._fullscreenOwnerEl
                    : !!document.fullscreenElement;
                this._scheduleFitAndCenter();
            };
            document.addEventListener("fullscreenchange", this._fullscreenChangeHandler);

            // Initial highlights + avatars
            this._refreshDecorations();
        });

        onWillUnmount(() => {
            this._ro?.disconnect();
            window.removeEventListener("resize", this._resizeHandler);
            this._resizeHandler = null;
            if (this._fitRaf) {
                cancelAnimationFrame(this._fitRaf);
                this._fitRaf = null;
            }
            if (this._fitResizeTimer) {
                clearTimeout(this._fitResizeTimer);
                this._fitResizeTimer = null;
            }
            if (this._refreshDecorationsRaf) {
                cancelAnimationFrame(this._refreshDecorationsRaf);
                this._refreshDecorationsRaf = null;
            }
            if (this.viewer && this._currentNodeOverlayByNodeId?.size) {
                const overlays = this.viewer.get("overlays");
                for (const entry of this._currentNodeOverlayByNodeId.values()) {
                    try {
                        overlays.remove(entry.overlayId);
                    } catch {
                        // no-op
                    }
                }
            }
            this._currentNodeOverlayByNodeId.clear();
            this._diagramSequenceFlows = [];
            this._diagramOutgoingBySource.clear();
            this._flowRouteCache.clear();
            this._activeMarkers.clear();
            this.viewer?.destroy?.();
            this.viewer = null;
            this.state.isFullscreen = false;
            this._editingControlsObserver?.disconnect?.();
            this._editingControlsObserver = null;
            this._themeObserver?.disconnect?.();
            this._themeObserver = null;
            if (this._themeMedia && this._themeMediaHandler) {
                this._themeMedia.removeEventListener("change", this._themeMediaHandler);
            }
            this._themeMedia = null;
            this._themeMediaHandler = null;
            if (document.fullscreenElement && this._fullscreenOwnerEl && document.fullscreenElement === this._fullscreenOwnerEl) {
                document.exitFullscreen().catch(() => {});
            }
            this._fullscreenOwnerEl = null;
            if (this._fullscreenChangeHandler) {
                document.removeEventListener("fullscreenchange", this._fullscreenChangeHandler);
                this._fullscreenChangeHandler = null;
            }

            // restore any inline style backups
            if (this._fsBackup) {
                for (const el of Array.from(this._fsBackup.keys())) {
                    try {
                        const prev = this._fsBackup.get(el);
                        if (prev) el.setAttribute("style", prev); else el.removeAttribute("style");
                    } catch (e) { /* ignore */
                    }
                }
                this._fsBackup.clear();
            }
            this._unregisterMiniUpdateChannel();
            if (this._miniRefreshTimer) {
                clearTimeout(this._miniRefreshTimer);
                this._miniRefreshTimer = null;
            }
            // remove classes just in case
            const anyFs = document.querySelectorAll(".o_fullscreen_dialog");
            anyFs.forEach((el) => el.classList.remove("o_fullscreen_dialog"));
            document.documentElement.classList.remove("o_fullscreen_active");
        });

        // Re-highlight when state/current node changes (and after first mount)
        useEffect(() => {
            this._refreshDecorations();
        }, () => [
            this.props.record?.data?.state,
            this.data?.current_node_id,
            this.data?.wf_is_blocked,
            this.data?.wf_block_reason,
            this.state.mountedDone,
        ]);
    }

    // ---- Helpers ----------------------------------------------------------------

    async _registerMiniUpdateChannel() {
        const requestId = await this._getBaseRequestId();
        if (!requestId) {
            return;
        }
        this._miniRequestId = Number(requestId);
        this._miniBusChannel = `workflow_approval.request_${this._miniRequestId}`;
        this.bus.addChannel(this._miniBusChannel);
        this.bus.start();
        this._miniBusCallback = (payload) => {
            if (!payload || Number(payload.request_id) !== Number(this._miniRequestId)) {
                return;
            }
            this.env.bus.trigger("WF-REQUEST:MINI-UPDATE", payload);
        };
        this.bus.subscribe("workflow_approval.request_mini_update", this._miniBusCallback);
    }

    _unregisterMiniUpdateChannel() {
        if (this._miniBusCallback) {
            this.bus.unsubscribe("workflow_approval.request_mini_update", this._miniBusCallback);
            this._miniBusCallback = null;
        }
        if (this._miniBusChannel) {
            this.bus.deleteChannel(this._miniBusChannel);
            this._miniBusChannel = null;
        }
        this._miniRequestId = null;
    }

    _scheduleMiniSnapshotRefresh() {
        if (this._miniRefreshTimer) {
            return;
        }
        this._miniRefreshTimer = setTimeout(async () => {
            this._miniRefreshTimer = null;
            await this._refreshMiniSnapshot();
        }, 120);
    }

    async _refreshMiniSnapshot() {
        if (!this._miniRequestId) {
            return;
        }
        try {
            const snapshot = await this.orm.call(
                "workflow.base.approval.request",
                "workflow_get_mini_update_snapshot",
                [this._miniRequestId]
            );
            if (snapshot && snapshot.request_id === this._miniRequestId) {
                this._applyMiniSnapshot(snapshot);
            }
        } catch (error) {
            console.warn("BpmnWidget mini snapshot refresh failed.", error);
        }
    }

    _applyMiniSnapshot(snapshot) {
        this.data.current_node_id = snapshot.current_node_id || "";
        this.data.previous_node_id = snapshot.previous_node_id || "";
        this.data.previous_node_ids = Array.isArray(snapshot.previous_node_ids)
            ? snapshot.previous_node_ids
            : [];
        this.data.current_activity_name = snapshot.current_activity_name || "";
        this.data.previous_activity_name = snapshot.previous_activity_name || "";
        this.data.state = snapshot.state || this.data.state;
        this.data.request_status = snapshot.request_status || this.data.request_status;
        this.data.current_iteration_no = snapshot.current_iteration_no || this.data.current_iteration_no || 1;
        this.data.wf_is_blocked = Boolean(snapshot.wf_is_blocked);
        this.data.wf_block_reason = snapshot.wf_block_reason || "";

        const rows = Array.isArray(snapshot.approver_rows) ? snapshot.approver_rows : [];
        this.data.approver_ids = {
            records: rows.map((row) => ({
                resId: row.id,
                data: row,
            })),
        };
        this._refreshDecorations();
    }

    _refreshDecorations() {
        if (!this.viewer || !this.state.mountedDone) {
            return;
        }
        if (this._refreshDecorationsRaf) {
            return;
        }
        this._refreshDecorationsRaf = requestAnimationFrame(() => {
            this._refreshDecorationsRaf = null;
            this._refreshDecorationsNow();
        });
    }

    _refreshDecorationsNow() {
        if (!this.viewer || !this.state.mountedDone) {
            return;
        }

        const canvas = this.viewer.get("canvas");
        const registry = this.viewer.get("elementRegistry");
        const currentNodeIds = this._computeCurrentNodeIds();
        const isBlocked = this._isWorkflowBlocked();
        const blockedReason = this._getWorkflowBlockedReason();
        const previousNodeIds = this._computeHistoryNodeIds(currentNodeIds);
        const currentNodeSet = new Set(currentNodeIds);
        const primaryCurrentNodeId = currentNodeIds[0] || "";

        if (!this._diagramSequenceFlows.length) {
            this._buildDiagramCache();
        }

        const existingCurrentNodes = new Set(currentNodeIds.filter((nodeId) => Boolean(registry.get(nodeId))));
        const existingHistoryNodes = new Set(previousNodeIds.filter((nodeId) => Boolean(registry.get(nodeId))));

        const {donePathMarkers, pendingPathMarkers} = this._computePathMarkerSets({
            previousNodeIds,
            currentNodeSet,
            primaryCurrentNodeId,
        });

        this._applyMarkerDiff(canvas, "is-current", existingCurrentNodes);
        this._applyMarkerDiff(canvas, "is-blocked", isBlocked ? new Set(existingCurrentNodes) : new Set());
        this._applyMarkerDiff(canvas, "is-previous", existingHistoryNodes);
        this._applyMarkerDiff(canvas, "is-history", existingHistoryNodes);
        this._applyMarkerDiff(canvas, "is-done-path", donePathMarkers);
        this._applyMarkerDiff(canvas, "is-pending-path", pendingPathMarkers);

        const markerSignature = this._buildNodeSignature({
            currentNodeIds: [...existingCurrentNodes],
            previousNodeIds: [...existingHistoryNodes],
            isBlocked,
            donePathCount: donePathMarkers.size,
            pendingPathCount: pendingPathMarkers.size,
        });
        this._lastMarkerSignature = markerSignature;
        this._forceLabelContrast(markerSignature);
        this._refreshCurrentNodeDot(registry, currentNodeIds, {isBlocked, blockedReason});

        const overlays = this._collectAvatarData();
        this._emitAvatarOverlayUpdate(overlays);
    }

    _buildDiagramCache() {
        if (!this.viewer) {
            return;
        }
        const registry = this.viewer.get("elementRegistry");
        const allElements = registry.getAll();
        this._diagramSequenceFlows = allElements
            .filter((el) => el?.type === "bpmn:SequenceFlow")
            .map((flow) => ({
                id: flow.id,
                sourceId: flow?.businessObject?.sourceRef?.id || flow?.source?.id || "",
                targetId: flow?.businessObject?.targetRef?.id || flow?.target?.id || "",
            }))
            .filter((flow) => flow.id && flow.sourceId && flow.targetId);
        this._diagramOutgoingBySource.clear();
        this._flowRouteCache.clear();
        this._diagramSequenceFlows.forEach((flow) => {
            if (!this._diagramOutgoingBySource.has(flow.sourceId)) {
                this._diagramOutgoingBySource.set(flow.sourceId, []);
            }
            this._diagramOutgoingBySource.get(flow.sourceId).push(flow);
        });
    }

    _buildNodeSignature({currentNodeIds = [], previousNodeIds = [], isBlocked = false, donePathCount = 0, pendingPathCount = 0}) {
        const current = [...currentNodeIds].sort().join(",");
        const previous = [...previousNodeIds].sort().join(",");
        return `${isBlocked ? 1 : 0}|c:${current}|p:${previous}|d:${donePathCount}|q:${pendingPathCount}`;
    }

    _applyMarkerDiff(canvas, markerClass, nextSet) {
        const previousSet = this._activeMarkers.get(markerClass) || new Set();
        for (const elementId of previousSet) {
            if (!nextSet.has(elementId)) {
                canvas.removeMarker(elementId, markerClass);
            }
        }
        for (const elementId of nextSet) {
            if (!previousSet.has(elementId)) {
                canvas.addMarker(elementId, markerClass);
            }
        }
        this._activeMarkers.set(markerClass, new Set(nextSet));
    }

    _computePathMarkerSets({previousNodeIds = [], currentNodeSet = new Set(), primaryCurrentNodeId = ""}) {
        const donePathMarkers = new Set();
        const pendingPathMarkers = new Set();
        const completedNodes = new Set(previousNodeIds);
        const flows = this._diagramSequenceFlows || [];

        flows.forEach((flow) => {
            if (currentNodeSet.size && currentNodeSet.has(flow.sourceId)) {
                pendingPathMarkers.add(flow.id);
                return;
            }
            if (
                completedNodes.has(flow.sourceId)
                && (
                    completedNodes.has(flow.targetId)
                    || (currentNodeSet.size && currentNodeSet.has(flow.targetId))
                    || flow.targetId === primaryCurrentNodeId
                )
            ) {
                donePathMarkers.add(flow.id);
            }
        });

        const visitedTransitionPairs = this._computeVisitedTransitionPairs({
            previousNodeIds,
            currentNodeSet,
        });
        visitedTransitionPairs.forEach((pairKey) => {
            const [sourceNodeId, targetNodeId] = pairKey.split("=>");
            if (!sourceNodeId || !targetNodeId) {
                return;
            }
            const routedFlowIds = this._resolveFlowRouteBetweenNodes(sourceNodeId, targetNodeId);
            routedFlowIds.forEach((flowId) => donePathMarkers.add(flowId));
        });

        pendingPathMarkers.forEach((flowId) => donePathMarkers.delete(flowId));
        return {donePathMarkers, pendingPathMarkers};
    }

    _computeVisitedTransitionPairs({previousNodeIds = [], currentNodeSet = new Set()}) {
        const pairs = new Set();
        const terminalStatuses = new Set(["approved", "refused", "cancelled", "closed"]);
        const records = this.data?.approver_ids?.records || [];

        records.forEach((approver) => {
            const row = approver?.data || {};
            const status = String(row.status || "").toLowerCase();
            if (!terminalStatuses.has(status)) {
                return;
            }
            const sourceNodeId = this._resolveMetaTaskNodeIdFromRelation(row.previous_meta_id);
            const targetNodeId = row.current_meta_node_id || "";
            if (!sourceNodeId || !targetNodeId || sourceNodeId === targetNodeId) {
                return;
            }
            pairs.add(`${sourceNodeId}=>${targetNodeId}`);
        });

        const explicitPreviousNodeId = this.data?.previous_node_id || "";
        if (explicitPreviousNodeId && currentNodeSet?.size) {
            currentNodeSet.forEach((currentNodeId) => {
                if (currentNodeId && currentNodeId !== explicitPreviousNodeId) {
                    pairs.add(`${explicitPreviousNodeId}=>${currentNodeId}`);
                }
            });
        }

        const orderedHistory = Array.isArray(previousNodeIds) ? previousNodeIds.filter(Boolean) : [];
        for (let index = 1; index < orderedHistory.length; index += 1) {
            const sourceNodeId = orderedHistory[index - 1];
            const targetNodeId = orderedHistory[index];
            if (sourceNodeId && targetNodeId && sourceNodeId !== targetNodeId) {
                pairs.add(`${sourceNodeId}=>${targetNodeId}`);
            }
        }

        return pairs;
    }

    _resolveMetaTaskNodeIdFromRelation(relationValue) {
        const metaTaskId = Array.isArray(relationValue)
            ? relationValue[0]
            : (relationValue?.id || (typeof relationValue === "number" ? relationValue : null));
        if (!metaTaskId || !this._metaTaskNodeById) {
            return "";
        }
        return this._metaTaskNodeById.get(metaTaskId) || "";
    }

    _resolveFlowRouteBetweenNodes(sourceNodeId, targetNodeId) {
        if (!sourceNodeId || !targetNodeId || sourceNodeId === targetNodeId) {
            return [];
        }
        const cacheKey = `${sourceNodeId}=>${targetNodeId}`;
        if (this._flowRouteCache.has(cacheKey)) {
            return this._flowRouteCache.get(cacheKey) || [];
        }
        if (!this._diagramOutgoingBySource?.size) {
            this._flowRouteCache.set(cacheKey, []);
            return [];
        }

        const queue = [sourceNodeId];
        const visitedNodeIds = new Set([sourceNodeId]);
        const previousNodeByNodeId = new Map();
        const previousFlowByNodeId = new Map();

        while (queue.length) {
            const currentNodeId = queue.shift();
            const outgoingFlows = this._diagramOutgoingBySource.get(currentNodeId) || [];
            for (const flow of outgoingFlows) {
                const nextNodeId = flow.targetId;
                if (!nextNodeId || visitedNodeIds.has(nextNodeId)) {
                    continue;
                }
                visitedNodeIds.add(nextNodeId);
                previousNodeByNodeId.set(nextNodeId, currentNodeId);
                previousFlowByNodeId.set(nextNodeId, flow.id);
                if (nextNodeId === targetNodeId) {
                    const route = [];
                    let cursor = targetNodeId;
                    while (previousNodeByNodeId.has(cursor)) {
                        const incomingFlowId = previousFlowByNodeId.get(cursor);
                        if (incomingFlowId) {
                            route.push(incomingFlowId);
                        }
                        cursor = previousNodeByNodeId.get(cursor);
                    }
                    route.reverse();
                    this._flowRouteCache.set(cacheKey, route);
                    return route;
                }
                queue.push(nextNodeId);
            }
        }

        this._flowRouteCache.set(cacheKey, []);
        return [];
    }

    _emitAvatarOverlayUpdate(overlays = []) {
        if (!this.viewer) {
            return;
        }
        const signature = overlays
            .map((item) => {
                const approvers = Array.isArray(item.approvers) ? item.approvers : [];
                const users = approvers
                    .map((approver) => `${approver.user_id || 0}:${approver.status || ""}:${approver.decision || ""}`)
                    .sort()
                    .join("|");
                return `${item.node_id || ""}=${users}`;
            })
            .sort()
            .join(";");
        if (signature === this._lastAvatarSignature) {
            return;
        }
        this._lastAvatarSignature = signature;
        this.viewer.get("eventBus").fire("custom.avatars:set", {data: overlays});
    }

    _forceLabelContrast(markerSignature = "") {
        if (!this.root?.el) {
            return;
        }
        const signature = `${this.state.isDarkTheme ? "dark" : "light"}|${markerSignature || this._lastMarkerSignature}`;
        if (signature === this._lastLabelContrastSignature) {
            return;
        }
        this._lastLabelContrastSignature = signature;
        const root = this.root.el;
        const isDark = Boolean(this.state.isDarkTheme);
        const darkSurfaceFill = "#f8fafc";
        const darkSurfaceStroke = "rgba(2, 6, 23, 0.92)";
        const lightSurfaceFill = "#111827";
        const lightSurfaceStroke = "rgba(255, 255, 255, 0.96)";
        const historyLightFill = "#0f172a";
        const historyLightStroke = "rgba(255, 255, 255, 0.96)";
        const historyDarkFill = "#f8fafc";
        const historyDarkStroke = "rgba(2, 6, 23, 0.96)";

        const parseColor = (rawColor) => {
            if (!rawColor) {
                return null;
            }
            const value = String(rawColor).trim().toLowerCase();
            if (!value || value === "none" || value === "transparent") {
                return null;
            }
            if (value.startsWith("#")) {
                let hex = value.slice(1);
                if (hex.length === 3) {
                    hex = hex
                        .split("")
                        .map((part) => part + part)
                        .join("");
                }
                if (hex.length === 6) {
                    const intValue = Number.parseInt(hex, 16);
                    if (Number.isFinite(intValue)) {
                        return {
                            r: (intValue >> 16) & 255,
                            g: (intValue >> 8) & 255,
                            b: intValue & 255,
                        };
                    }
                }
                return null;
            }
            const rgbMatch = value.match(/rgba?\(([^)]+)\)/i);
            if (!rgbMatch || !rgbMatch[1]) {
                return null;
            }
            const parts = rgbMatch[1]
                .split(",")
                .slice(0, 3)
                .map((part) => Number.parseFloat(part.trim()));
            if (parts.some((part) => Number.isNaN(part))) {
                return null;
            }
            return {
                r: Math.max(0, Math.min(255, parts[0])),
                g: Math.max(0, Math.min(255, parts[1])),
                b: Math.max(0, Math.min(255, parts[2])),
            };
        };

        const luminance = (rgb) => {
            if (!rgb) {
                return null;
            }
            return (0.2126 * rgb.r + 0.7152 * rgb.g + 0.0722 * rgb.b) / 255;
        };

        const getOwnerShape = (labelElementId) => {
            if (!labelElementId || !labelElementId.endsWith("_label")) {
                return null;
            }
            const targetId = labelElementId.slice(0, -6);
            return root.querySelector(`.djs-element[data-element-id="${targetId}"]`);
        };

        const resolveShapeFill = (ownerShape) => {
            if (!ownerShape) {
                return null;
            }
            const shapeVisual = ownerShape.querySelector(
                ".djs-visual > rect, .djs-visual > circle, .djs-visual > polygon, .djs-visual > path:not([fill='none'])"
            );
            if (shapeVisual) {
                return (
                    parseColor(shapeVisual.style?.fill) ||
                    parseColor(shapeVisual.getAttribute?.("fill")) ||
                    parseColor(window.getComputedStyle(shapeVisual).fill)
                );
            }
            return parseColor(window.getComputedStyle(ownerShape).fill);
        };

        const labelNodes = root.querySelectorAll(
            ".djs-element.djs-label .djs-visual text, " +
            ".djs-element.djs-label .djs-visual tspan, " +
            ".djs-connection .djs-visual text, " +
            ".djs-connection .djs-visual tspan, " +
            ".djs-shape .djs-visual text, " +
            ".djs-shape .djs-visual tspan, " +
            ".djs-element.djs-label .djs-visual foreignObject *, " +
            ".djs-shape .djs-visual foreignObject *"
        );

        labelNodes.forEach((node) => {
            const owner = node.closest(".djs-element");
            const ownerIsHistory = owner?.classList?.contains("is-history");
            const ownerId = owner?.getAttribute?.("data-element-id") || "";
            const ownerShape = getOwnerShape(ownerId);
            const targetIsHistory = ownerShape?.classList?.contains("is-history");
            const isHistory = Boolean(ownerIsHistory || targetIsHistory);
            const effectiveOwnerShape = ownerShape || owner;
            const surfaceFill = resolveShapeFill(effectiveOwnerShape);
            const surfaceLuminance = luminance(surfaceFill);
            const isLightSurface = surfaceLuminance !== null ? surfaceLuminance >= 0.58 : !isDark;
            const fill = isHistory
                ? (isLightSurface ? historyLightFill : historyDarkFill)
                : (isLightSurface ? lightSurfaceFill : darkSurfaceFill);
            const stroke = isHistory
                ? (isLightSurface ? historyLightStroke : historyDarkStroke)
                : (isLightSurface ? lightSurfaceStroke : darkSurfaceStroke);
            const strokeWidth = isHistory ? "2.8px" : "3.4px";
            const fontWeight = isHistory ? "700" : "600";
            const nodeTag = (node.tagName || "").toLowerCase();
            const isSvgTextNode = nodeTag === "text" || nodeTag === "tspan";
            const computedFontSize = Number.parseFloat(window.getComputedStyle(node).fontSize || "0");

            if (Number.isFinite(computedFontSize) && computedFontSize > 0 && computedFontSize < 11.5) {
                node.style.setProperty("font-size", "11.5px", "important");
            }

            if (isSvgTextNode) {
                node.style.setProperty("fill", fill, "important");
                node.style.setProperty("fill-opacity", "1", "important");
                node.style.setProperty("paint-order", "stroke", "important");
                node.style.setProperty("stroke", stroke, "important");
                node.style.setProperty("stroke-width", strokeWidth, "important");
                node.style.setProperty("stroke-linejoin", "round", "important");
            } else {
                // foreignObject labels are HTML nodes, so use color + text-shadow contrast fallback.
                node.style.setProperty("color", fill, "important");
                node.style.setProperty("-webkit-text-fill-color", fill, "important");
                node.style.setProperty(
                    "text-shadow",
                    `${stroke} 0 0 1px, ${stroke} 0 0 2px, ${stroke} 0 0 3px`,
                    "important"
                );
            }

            node.style.setProperty("opacity", "1", "important");
            node.style.setProperty("font-weight", fontWeight, "important");
        });
    }

    _computeCurrentNodeIds() {
        if (this._isTerminalRequestState()) {
            return [];
        }
        const nodeIds = [];
        if (this.data?.current_node_id) {
            nodeIds.push(this.data.current_node_id);
        }
        if (Array.isArray(this.data?.current_node_ids)) {
            this.data.current_node_ids.forEach((nodeId) => {
                if (nodeId) {
                    nodeIds.push(nodeId);
                }
            });
        }

        if (!nodeIds.length) {
            const activeStatuses = new Set(["pending", "waiting", "new", "view", "in_progress"]);
            const records = this.data?.approver_ids?.records || [];
            records.forEach((approver) => {
                const status = String(approver?.data?.status || "").toLowerCase();
                const nodeId = approver?.data?.current_meta_node_id;
                if (nodeId && activeStatuses.has(status)) {
                    nodeIds.push(nodeId);
                }
            });
        }

        return Array.from(new Set(nodeIds.filter(Boolean)));
    }

    _computeHistoryNodeIds(currentNodeIds = []) {
        const historyNodeSet = new Set();
        const previousNodeIds = this.data?.previous_node_ids || [];
        previousNodeIds.filter(Boolean).forEach((nodeId) => historyNodeSet.add(nodeId));
        if (this.data?.previous_node_id) {
            historyNodeSet.add(this.data.previous_node_id);
        }
        if (this._isTerminalRequestState() && this.data?.current_node_id) {
            historyNodeSet.add(this.data.current_node_id);
        }

        const terminalStatuses = new Set(["approved", "refused", "cancelled", "closed"]);
        const records = this.data?.approver_ids?.records || [];
        records.forEach((approver) => {
            const status = String(approver?.data?.status || "").toLowerCase();
            const nodeId = approver?.data?.current_meta_node_id;
            if (nodeId && terminalStatuses.has(status)) {
                historyNodeSet.add(nodeId);
            }
        });
        currentNodeIds.forEach((nodeId) => historyNodeSet.delete(nodeId));
        return Array.from(historyNodeSet);
    }

    _isTerminalRequestState() {
        const state = String(this.data?.state || "").toLowerCase();
        return ["completed", "cancelled", "auto_cancelled", "refused", "auto_approved"].includes(state);
    }

    _refreshCurrentNodeDot(registry, currentNodeIds = [], options = {}) {
        if (!this.viewer) {
            return;
        }
        const isBlocked = Boolean(options.isBlocked);
        const blockedReason = options.blockedReason || "";
        const overlays = this.viewer.get("overlays");
        const markerTitle = blockedReason || (isBlocked ? "Blocked current node" : "Current node");
        const desiredNodeIds = new Set(currentNodeIds);

        for (const [nodeId, entry] of this._currentNodeOverlayByNodeId.entries()) {
            if (!desiredNodeIds.has(nodeId)) {
                try {
                    overlays.remove(entry.overlayId);
                } catch {
                    // no-op
                }
                this._currentNodeOverlayByNodeId.delete(nodeId);
            }
        }

        desiredNodeIds.forEach((currentNodeId) => {
            const node = registry.get(currentNodeId);
            if (!node) {
                return;
            }
            const existing = this._currentNodeOverlayByNodeId.get(currentNodeId);
            if (existing?.markerEl) {
                existing.markerEl.classList.toggle("is-blocked", isBlocked);
                existing.markerEl.title = markerTitle;
                return;
            }
            const marker = document.createElement("span");
            marker.className = "ngflow-current-node-dot";
            if (isBlocked) {
                marker.classList.add("is-blocked");
            }
            marker.title = markerTitle;
            const overlayId = overlays.add(node, {
                position: {
                    top: Math.max(Math.round((node.height || 0) / 2) - 6, 0),
                    left: Math.max((node.width || 0) + 8, 0),
                },
                html: marker,
                scale: false,
            });
            this._currentNodeOverlayByNodeId.set(currentNodeId, {
                overlayId,
                markerEl: marker,
            });
        });
    }

    _isWorkflowBlocked() {
        const raw = this.data?.wf_is_blocked;
        if (raw === true || raw === 1 || raw === "1" || raw === "true") {
            return true;
        }
        const taskRows = this.data?.task_instance_ids?.records || [];
        return taskRows.some((row) => {
            const status = String(row?.data?.status || row?.status || "").toLowerCase();
            return status === "blocked";
        });
    }

    _getWorkflowBlockedReason() {
        const explicit = this.data?.wf_block_reason;
        if (explicit) {
            return String(explicit);
        }
        const taskRows = this.data?.task_instance_ids?.records || [];
        const blockedRow = taskRows.find((row) => {
            const status = String(row?.data?.status || row?.status || "").toLowerCase();
            return status === "blocked";
        });
        return blockedRow?.data?.blocked_reason || blockedRow?.blocked_reason || "";
    }

    async _ensureViewerConstructor() {
        let ctor = this._resolveBpmnViewerConstructor();
        if (ctor) {
            return ctor;
        }
        await loadJS(BPMN_VIEWER_LIB_URL);
        ctor = this._resolveBpmnViewerConstructor();
        if (ctor) {
            return ctor;
        }
        await loadJS(`${BPMN_VIEWER_LIB_URL}?workflow_preview_viewer=${Date.now()}`);
        return this._resolveBpmnViewerConstructor();
    }

    _collectAvatarData() {
        // Build from approver_ids whenever possible because it contains status/decision metadata.
        const approvers = this.data?.approver_ids?.records ?? [];
        if (!approvers.length) {
            const prebuilt = this.data?.avatar_overlays;
            return Array.isArray(prebuilt) ? prebuilt : [];
        }
        const isTerminalRequest = this._isTerminalRequestState();
        const activeStatuses = new Set(["new", "pending", "waiting", "view", "in_progress"]);
        const currentNodeSet = new Set(this._computeCurrentNodeIds());
        const byNode = new Map(); // node_id -> Map(user_id -> payload)
        for (const a of approvers) {
            const approverId = a?.resId || a?.id || a?.data?.id;
            const metaRel = a?.data?.current_meta_id;
            const metaId = Array.isArray(metaRel)
                ? metaRel[0]
                : (metaRel?.id || (typeof metaRel === "number" ? metaRel : null));
            const nodeId = a?.data?.current_meta_node_id;
            const user = a?.data?.user_id;
            const userId = Array.isArray(user) ? user[0] : user?.id;
            const userName = Array.isArray(user) ? user[1] : user?.display_name || user?.name || "";
            const status = String(a?.data?.status || "").toLowerCase();
            const decision = String(a?.data?.user_decision || "");
            const required = a?.data?.required;
            if (this._allowedMetaTaskIds && (!metaId || !this._allowedMetaTaskIds.has(metaId))) continue;
            if (!nodeId || !userId) continue;
            const isRequiredAssignment = required === true || required === 1 || required === "1";
            const hasDecision = Boolean(decision.trim());
            const isActiveAssignment =
                !isTerminalRequest
                && isRequiredAssignment
                && currentNodeSet.has(nodeId)
                && activeStatuses.has(status);
            if (!hasDecision && !isActiveAssignment) continue;

            const url = `/web/image/res.users/${userId}/avatar_128`;
            const fallbackUrl = approverId
                ? `/web/image/workflow.approval.approver/${approverId}/avatar_128`
                : "";
            const payload = {
                user_id: userId,
                approver_id: approverId || null,
                user_name: userName,
                avatar_url: url,
                avatar_fallback_url: fallbackUrl,
                status,
                decision,
            };

            // Avatar badges summarize users per node. They should not show the
            // same person multiple times for assignment+decision rows, loopback
            // history, or auto-closed required assignments.
            if (!byNode.has(nodeId)) {
                byNode.set(nodeId, new Map());
            }
            const nodeUsers = byNode.get(nodeId);
            const existing = nodeUsers.get(userId);
            const rank = currentNodeSet.has(nodeId) && isActiveAssignment ? 0 : hasDecision ? 1 : 2;
            if (!existing || rank < existing._rank) {
                nodeUsers.set(userId, {...payload, _rank: rank});
            }
        }
        return Array.from(byNode, ([node_id, usersById]) => ({
            node_id,
            approvers: Array.from(usersById.values(), ({_rank, ...approver}) => approver),
        }));
    }

    async _loadAllowedMetaTaskIds() {
        const versionRel = this.data?.version_id;
        const versionId = Array.isArray(versionRel)
            ? versionRel[0]
            : (versionRel?.id || (typeof versionRel === "number" ? versionRel : null));
        if (!versionId) {
            this._allowedMetaTaskIds = null;
            return;
        }
        try {
            const rows = await this.orm.searchRead(
                "workflow.category.version.meta.task",
                [["version_id", "=", versionId]],
                ["id", "node_id"]
            );
            const metaRows = rows || [];
            this._allowedMetaTaskIds = new Set(metaRows.map((row) => row.id).filter(Boolean));
            this._metaTaskNodeById = new Map(
                metaRows
                    .filter((row) => row.id && row.node_id)
                    .map((row) => [row.id, row.node_id])
            );
        } catch (error) {
            console.warn("BpmnWidget: failed to load version-scoped meta tasks, fallback to unfiltered avatars.", error);
            this._allowedMetaTaskIds = null;
            this._metaTaskNodeById = null;
        }
    }

    _resolveBpmnViewerConstructor() {
        const candidates = [
            window.BpmnNavigatedViewer,
            window.BpmnViewer,
            window.BpmnJS,
        ];
        return candidates.find((Ctor) => this._isUsableViewerConstructor(Ctor)) || null;
    }

    _startThemeObserver() {
        if (this._themeObserver || typeof document === "undefined") {
            return;
        }
        const onThemeChanged = () => this._syncThemeMode();
        this._themeObserver = new MutationObserver(onThemeChanged);
        this._themeObserver.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ["class", "data-theme", "data-bs-theme", "style"],
        });
        if (document.body) {
            this._themeObserver.observe(document.body, {
                attributes: true,
                attributeFilter: ["class", "data-theme", "data-bs-theme", "style"],
            });
        }
        if (window.matchMedia) {
            this._themeMedia = window.matchMedia("(prefers-color-scheme: dark)");
            this._themeMediaHandler = onThemeChanged;
            this._themeMedia.addEventListener("change", this._themeMediaHandler);
        }
    }

    _syncThemeMode() {
        const isDark = this._detectDarkMode();
        this.state.isDarkTheme = isDark;
        if (this.root?.el) {
            this.root.el.classList.toggle("wf-theme-dark", isDark);
            this.root.el.classList.toggle("wf-theme-light", !isDark);
        }
        if (this.state.mountedDone) {
            this._forceLabelContrast();
        }
    }

    _detectDarkMode() {
        if (typeof document === "undefined") {
            return false;
        }
        const html = document.documentElement;
        const body = document.body;
        const attrs = [
            html?.getAttribute("data-theme"),
            html?.getAttribute("data-bs-theme"),
            body?.getAttribute("data-theme"),
            body?.getAttribute("data-bs-theme"),
        ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();
        if (attrs.includes("dark")) {
            return true;
        }

        const classText = `${html?.className || ""} ${body?.className || ""}`.toLowerCase();
        const darkClassHints = ["o_dark", "o_web_dark", "theme-dark", "dark-mode", "dark"];
        if (darkClassHints.some((keyword) => classText.includes(keyword))) {
            return true;
        }

        const bgColor = window.getComputedStyle(body || html).backgroundColor || "";
        const rgb = bgColor.match(/rgba?\(([^)]+)\)/i);
        if (rgb && rgb[1]) {
            const [r, g, b] = rgb[1]
                .split(",")
                .slice(0, 3)
                .map((value) => Number.parseFloat(value.trim()))
                .map((value) => (Number.isFinite(value) ? value : 255));
            const luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
            return luminance < 0.48;
        }

        return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
    }

    _hasAnyService(instance, serviceNames) {
        if (!instance?.get) {
            return false;
        }
        for (const serviceName of serviceNames) {
            try {
                if (instance.get(serviceName, false)) {
                    return true;
                }
            } catch {
                // no-op
            }
        }
        return false;
    }

    _isLikelyModelerConstructor(Ctor) {
        if (typeof Ctor !== "function") {
            return false;
        }
        const modelingModules = Ctor?.prototype?._modelingModules;
        return Array.isArray(modelingModules) && modelingModules.length > 0;
    }

    _isUsableViewerConstructor(Ctor) {
        if (typeof Ctor !== "function" || typeof document === "undefined") {
            return false;
        }
        if (typeof Ctor.prototype?.importXML !== "function") {
            return false;
        }
        if (this._isLikelyModelerConstructor(Ctor)) {
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
            const hasCanvas = !!instance?.get?.("canvas", false);
            const hasModeling = this._hasAnyService(instance, [
                "modeling",
                "palette",
                "contextPad",
                "create",
                "connect",
                "directEditing",
            ]);
            return hasCanvas && !hasModeling;
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

    _hideEditingControls() {
        if (!this.root?.el) {
            return;
        }
        const controls = this.root.el.querySelectorAll(
            ".djs-palette, .djs-context-pad, .djs-popup, .djs-direct-editing-parent, .bio-properties-panel-parent, .properties-panel-parent"
        );
        controls.forEach((el) => {
            el.style.display = "none";
        });
    }

    _startEditingControlsObserver() {
        if (!this.root?.el || this._editingControlsObserver) {
            return;
        }
        this._editingControlsObserver = new MutationObserver(() => this._hideEditingControls());
        this._editingControlsObserver.observe(this.root.el, {childList: true, subtree: true});
    }

    _changeZoomBy(delta) {
        //debugger;
        try {
            if (!this.viewer) return;
            const canvas = this.viewer.get("canvas");
            if (!canvas || typeof canvas.zoom !== "function") return;

            // defensive: coerce delta to a number
            let d = Number(delta);
            if (!Number.isFinite(d)) {
                // try parseFloat for strings like "0.1" or "10%"
                const pd = parseFloat(delta);
                if (Number.isFinite(pd)) {
                    d = pd;
                } else {
                    console.warn("bpmn-widget: invalid zoom delta, defaulting to 0.1", {delta});
                    d = 0.1;
                }
            }

            // 1) try the official getter
            let current = canvas.zoom();

            // 2) fallback: viewbox scale
            if (!Number.isFinite(current)) {
                try {
                    const viewbox = canvas.viewbox && canvas.viewbox();
                    if (viewbox && Number.isFinite(viewbox.scale)) {
                        current = viewbox.scale;
                    }
                } catch (e) { /* ignore */
                }
            }

            // 3) fallback: parse <g> transform matrix
            if (!Number.isFinite(current)) {
                try {
                    const container = canvas.getContainer && canvas.getContainer();
                    const svg = container && container.querySelector && container.querySelector("svg");
                    const g = svg && svg.querySelector && svg.querySelector("g");
                    if (g) {
                        const tr = g.getAttribute("transform") || "";
                        const m = tr.match(/matrix\(([-0-9.eE+, ]+)\)/);
                        if (m && m[1]) {
                            const parts = m[1].split(/[ ,]+/).map(p => parseFloat(p));
                            if (Number.isFinite(parts[0])) current = parts[0];
                        }
                    }
                } catch (e) { /* ignore */
                }
            }

            // final fallback
            if (!Number.isFinite(current)) {
                console.warn("bpmn-widget: could not read current zoom, defaulting to 1", {current});
                current = 1;
            }

            // compute new zoom safely
            const MIN_ZOOM = 0.1;
            const MAX_ZOOM = 4.0;
            const newZoomUnclamped = current + d;

            if (!Number.isFinite(newZoomUnclamped)) {
                console.error("bpmn-widget: computed newZoom was not finite", {
                    current, d, newZoomUnclamped
                });
                return;
            }

            const newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, newZoomUnclamped));

            if (Math.abs(newZoom - current) < 1e-6) return;

            canvas.zoom(newZoom);
        } catch (err) {
            console.error("bpmn-widget: zoom change failed", err);
        }
    }

    zoomIn() {
        this._changeZoomBy(0.1);
    }

    zoomOut() {
        this._changeZoomBy(-0.1);
    }

    toggleDock() {
        this.state.dockExpanded = !this.state.dockExpanded;
    }

    // Robust fullscreen toggle: prefers browser Fullscreen API and falls back to dialog fullscreen styles.
    async toggleFullscreen() {
        const fullscreenTarget = this._getFullscreenTarget();
        if (fullscreenTarget && document.fullscreenEnabled && typeof fullscreenTarget.requestFullscreen === "function") {
            try {
                if (document.fullscreenElement === fullscreenTarget) {
                    await document.exitFullscreen();
                    this.state.isFullscreen = false;
                    this._fullscreenOwnerEl = null;
                } else {
                    if (document.fullscreenElement && document.fullscreenElement !== fullscreenTarget) {
                        await document.exitFullscreen();
                    }
                    await fullscreenTarget.requestFullscreen();
                    this.state.isFullscreen = true;
                    this._fullscreenOwnerEl = fullscreenTarget;
                }
                await new Promise((resolve) => requestAnimationFrame(resolve));
                await this.fitAndCenter();
                return;
            } catch (error) {
                console.warn("BpmnWidget.toggleFullscreen: fullscreen api failed, fallback to modal fullscreen", error);
            }
        }

        const rootEl = this.root?.el;
        if (!rootEl) {
            console.warn("BpmnWidget.toggleFullscreen: no root element");
            return;
        }

        // 1) Candidate selectors commonly used for dialogs / modals
        const candidateSelectors = [".o_dialog", ".o_dialog_container",   // Odoo dialog wrappers
            ".modal", ".modal-dialog", ".modal-content", // bootstrap-like modals
            ".o_modal", ".o_modal_dialog"];

        // Build candidate list from document
        const candidates = Array.from(document.querySelectorAll(candidateSelectors.join(",")));

        // Try: 1) find a candidate that contains our root; 2) else find the nearest ancestor with any dialog-like class;
        // 3) else find the nearest ancestor which is position: fixed/absolute (likely the modal box); 4) fallback to document.body.
        let dialogEl = candidates.find((el) => el.contains(rootEl));

        if (!dialogEl) {
            dialogEl = rootEl.closest(candidateSelectors.join(",")) || null;
        }

        if (!dialogEl) {
            // walk ancestors to find an element with computed position fixed/absolute which likely is the modal box
            let anc = rootEl;
            while (anc && anc !== document.body) {
                const cs = window.getComputedStyle(anc);
                if (cs && (cs.position === "fixed" || cs.position === "absolute")) {
                    dialogEl = anc;
                    break;
                }
                anc = anc.parentElement;
            }
        }

        // final fallback
        if (!dialogEl) dialogEl = candidates[0] || document.body;

        // toggle class
        const entering = !dialogEl.classList.contains("o_fullscreen_dialog");
        dialogEl.classList.toggle("o_fullscreen_dialog", entering);
        this.state.isFullscreen = entering;

        // page-level class to prevent scrolling
        document.documentElement.classList.toggle("o_fullscreen_active", entering);

        // We'll apply inline styles to key nodes to force full-viewport. Save previously applied inline styles
        // so we can restore them on exit.
        if (!this._fsBackup) this._fsBackup = new Map();

        const applyInline = (el, styles) => {
            if (!el) return;
            if (!this._fsBackup.has(el)) {
                // store previous inline style so we can restore
                this._fsBackup.set(el, el.getAttribute("style") || "");
            }
            for (const [k, v] of Object.entries(styles)) {
                el.style.setProperty(k, v, "important");
            }
        };

        const restoreInline = (el) => {
            if (!el) return;
            const prev = this._fsBackup.get(el);
            if (prev === undefined) return;
            if (prev) {
                el.setAttribute("style", prev);
            } else {
                el.removeAttribute("style");
            }
            this._fsBackup.delete(el);
        };

        // Important nodes to apply styles to:
        const modalDialog = dialogEl.querySelector(".modal-dialog") || dialogEl.querySelector(".o_dialog") || dialogEl;
        const modalContent = dialogEl.querySelector(".modal-content") || dialogEl.querySelector(".o_dialog_box") || dialogEl;

        if (entering) {
            // force the dialog element to occupy viewport
            applyInline(dialogEl, {
                position: "fixed",
                top: "0",
                left: "0",
                right: "0",
                bottom: "0",
                width: "100vw",
                height: "100vh",
                margin: "0",
                padding: "0",
                "z-index": "300000"
            });

            // override transforms / centering of inner modal container
            applyInline(modalDialog, {
                transform: "none",
                top: "0",
                left: "0",
                width: "100vw",
                height: "100vh",
                margin: "0",
                padding: "0",
                position: "fixed"
            });

            // make content fill area
            applyInline(modalContent, {
                width: "100%", height: "100%", overflow: "hidden", padding: "0"
            });

            // ensure bpmn container fills available space
            const bpmnEl = dialogEl.querySelector(".bpmn_container, .o_bpmn_container, .bpmn-container");
            if (bpmnEl) {
                applyInline(bpmnEl, {width: "100%", height: "100%", "min-height": "0"});
                // also ensure inner svg expands
                const svg = bpmnEl.querySelector("svg");
                if (svg) applyInline(svg, {width: "100%", height: "100%"});
            }
        } else {
            // exiting: restore inline styles for nodes we've modified
            restoreInline(dialogEl);
            restoreInline(modalDialog);
            restoreInline(modalContent);
            const bpmnEl = dialogEl.querySelector(".bpmn_container, .o_bpmn_container, .bpmn-container");
            if (bpmnEl) {
                restoreInline(bpmnEl);
                const svg = bpmnEl.querySelector("svg");
                if (svg) restoreInline(svg);
            }
            // remove page class
            document.documentElement.classList.remove("o_fullscreen_active");
        }

        // give browser a tick for layout, then ask bpmn-js to recalc size and fit
        await new Promise((r) => requestAnimationFrame(r));
        await new Promise((r) => setTimeout(r, 40));
        try {
            const canvas = this.viewer?.get("canvas");
            if (canvas && typeof canvas.resized === "function") canvas.resized();
            await this.fitAndCenter();
        } catch (e) {
            console.warn("BpmnWidget: fitAndCenter failed after fullscreen toggle", e);
        }
    }

    _getFullscreenTarget() {
        if (typeof document !== "undefined" && document.documentElement) {
            return document.documentElement;
        }
        return this.root?.el || null;
    }

    _scheduleFitAndCenter() {
        if (!this.viewer) {
            return;
        }
        if (this._fitRaf) {
            cancelAnimationFrame(this._fitRaf);
        }
        this._fitRaf = requestAnimationFrame(() => {
            this._fitRaf = null;
            if (this._fitResizeTimer) {
                clearTimeout(this._fitResizeTimer);
            }
            this._fitResizeTimer = setTimeout(() => {
                this._fitResizeTimer = null;
                this.fitAndCenter();
            }, 36);
        });
    }

    async fitAndCenter() {
        if (!this.viewer) return;
        const canvas = this.viewer.get("canvas");
        await new Promise((r) => requestAnimationFrame(r)); // ensure layout settled (esp. on mobile)
        canvas.resized();
        canvas.zoom("fit-viewport", "auto");
    };

    /**
     * Run an action window when user clicks on each activity exluding the following scenarios:
     * - if node is not bpmn:UserTask
     * - if user clicks on activity node from the configuration page
     *
     * @param {*} element
     * @returns
     */
    async _onNodeClick(element) {
        const nodeId = element.id;
        const nodeName = element?.businessObject?.name || element?.businessObject?.$attrs?.name || nodeId;
        const requestId = await this._getBaseRequestId();
        const currentNodeId = this.data?.current_node_id || "";

        if (!requestId) {
            return
        }

        if (!this._isApprovalNodeType(element.type)) {
            return;
        }

        let popupAction = null;
        try {
            popupAction = await this.orm.call(
                "workflow.approval.approver",
                "action_open_node_approvers",
                [requestId, nodeId, nodeName, nodeId === currentNodeId, this.env.isSmall ? "kanban" : false]
            );
        } catch (error) {
            console.warn(
                "workflow.approval.approver.action_open_node_approvers unavailable, falling back to client-side action.",
                error
            );
            popupAction = this._buildFallbackApproverAction({
                requestId,
                nodeId,
                nodeName,
                isCurrentNode: nodeId === currentNodeId,
                preferredView: this.env.isSmall ? "kanban" : "list",
            });
        }
        if (popupAction) {
            await this.action.doAction(popupAction);
        }
    }

    _buildFallbackApproverAction({requestId, nodeId, nodeName, isCurrentNode, preferredView = "list"}) {
        const versionMetaDomain = this._allowedMetaTaskIds && this._allowedMetaTaskIds.size
            ? [["current_meta_id", "in", [...this._allowedMetaTaskIds]]]
            : [];
        const viewTypes = ["list", "kanban"];

        const domain = [
            ["request_id", "=", requestId],
            ["user_id", "!=", false],
            ...versionMetaDomain,
            ["current_meta_node_id", "=", nodeId],
            "|",
            ["required", "=", true],
            ["user_decision", "not in", [false, ""]],
        ];

        return {
            name: `User Activity - ${nodeName || nodeId}`,
            type: "ir.actions.act_window",
            res_model: "workflow.approval.approver",
            view_mode: [...viewTypes, "form"].join(","),
            views: [...viewTypes.map((viewType) => [false, viewType]), [false, "form"]],
            mobile_view_mode: preferredView === "kanban" ? "kanban" : false,
            target: "new",
            domain,
            context: {
                search_default_node_related: 1,
                search_default_decided_users_only: 1,
                wf_allow_dialog_view_switch: true,
                wf_node_popup_request_id: requestId,
                wf_node_popup_node_id: nodeId,
                wf_node_popup_node_name: nodeName || "",
                wf_node_popup_is_current_node: Boolean(isCurrentNode),
                wf_node_popup_default_view: viewTypes[0],
                wf_node_popup_close_footer: true,
                footer: true,
            },
        };
    }

    _isApprovalNodeType(nodeType) {
        const supportedNodeTypes = new Set([
            "bpmn:UserTask",
            "bpmn:Task",
            "bpmn:ServiceTask",
            "bpmn:SendTask",
            "bpmn:ScriptTask",
            "bpmn:CallActivity",
            "bpmn:SubProcess",
        ]);
        return supportedNodeTypes.has(nodeType);
    }

    _getBaseRequestId() {
        const requestRel = this.data?.request_id;
        if (Array.isArray(requestRel) && requestRel[0]) {
            return requestRel[0];
        }
        if (requestRel?.id) {
            return requestRel.id;
        }
        if (typeof requestRel === "number") {
            return requestRel;
        }
        const baseRel = this.data?.x_approval_base_id;
        if (Array.isArray(baseRel) && baseRel[0]) {
            return baseRel[0];
        }
        if (baseRel?.id) {
            return baseRel.id;
        }
        const baseIdRaw = this.data?.x_approval_base_id;
        if (typeof baseIdRaw === "number") {
            return baseIdRaw;
        }
        const model = this.data?.res_model_name;
        const childId = this.data?.id;
        if (model && childId && model !== "workflow.base.approval.request") {
            return this.orm.read(model, [childId], ["x_approval_base_id"])
                .then((rows) => {
                    const row = rows?.[0] || {};
                    const rel = row.x_approval_base_id;
                    if (Array.isArray(rel) && rel[0]) {
                        return rel[0];
                    }
                    if (rel?.id) {
                        return rel.id;
                    }
                    return childId;
                })
                .catch(() => childId);
        }
        return Promise.resolve(childId || null);
    }
}

registry.category("fields").add("bpmn_widget", {component: BpmnWidget});
