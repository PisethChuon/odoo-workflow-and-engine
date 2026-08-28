/** @odoo-module **/

import {Component, onMounted, onWillUnmount, useRef} from "@odoo/owl";
import {AssetsLoadingError, loadJS} from "@web/core/assets";

// import TokenSimulationModule from '@workflow_engine/../lib/bpmn-js-token-simulation/lib';
const BPMN_OVERLAY_VERSION = "20260304_01";

export class BpmnApprovalDesigner extends Component {
    static template = "workflow_engine.BpmnApprovalDesigner";

    static props = {
        xml: {type: String, optional: true},
        onSave: {type: Function, optional: true}
    };

    setup() {
        this.canvasRef = useRef("canvas");
        this.panelRef = useRef("panel");
        this.modeler = null;

        onMounted(async () => {
            try {
                await Promise.all([
                    loadJS(`/workflow_engine/static/lib/bpmn-js/custom_bpmn_renderer.js?v=${BPMN_OVERLAY_VERSION}`),
                    loadJS(`/workflow_engine/static/lib/bpmn-js/mobile_touch.js?v=${BPMN_OVERLAY_VERSION}`),
                ]);
            } catch (error) {
                if (!(error instanceof AssetsLoadingError)) {
                    throw error;
                }
            }

            const additionalModules = [];
            if (window.CustomRendererModule) {
                additionalModules.push(window.CustomRendererModule([]));
            }
            if (window.MobileTouchModule) {
                additionalModules.push(window.MobileTouchModule());
            }

            this.modeler = new window.BpmnJS({
                container: this.canvasRef.el,
                additionalModules,
                // additionalModules: [
                //     TokenSimulationModule
                // ],
                // additionalModules: [
                //     window.TokenSimulationModule,
                //     window.BpmnPropertiesPanelModule,
                //     window.BpmnPropertiesProviderModule
                // ],
                propertiesPanel: {parent: this.panelRef.el}
            });

            if (this.props.xml) {
                await this.modeler.importXML(this.props.xml);
                this.modeler.get("canvas").zoom("fit-viewport");
            }

            this.modeler.get('eventBus').on('commandStack.changed', async () => {
                const {xml} = await this.modeler.saveXML({format: true});
                if (this.props.onSave) {
                    this.props.onSave(xml);
                }
            });
        });

        onWillUnmount(() => {
            this.modeler?.destroy?.();
            this.modeler = null;
        });
    }

    async getXML() {
        const {xml} = await this.modeler.saveXML({format: true});
        return xml;
    }
}
