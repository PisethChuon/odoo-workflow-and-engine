/** @odoo-module **/

import {registry} from '@web/core/registry';
import {Component, onWillStart, useState, onMounted ,useRef} from "@odoo/owl";
import {Layout} from "@web/search/layout";
import {useService} from "@web/core/utils/hooks";
import {BpmnApprovalDesigner} from "@workflow_engine/web/bpmn_view/bpmn_approval_designer";


export class BpmnViewer extends Component {
    static template = "workflow_engine.BpmnViewerComponent";
    static props = {
        xml: { type: String },
        readonly: { type: Boolean, optional: true },
    };

    setup() {
        this.root = useRef("root");
        onMounted(async () => {
            const BpmnJS = window.BpmnJS;
            this.modeler = new BpmnJS({ container: this.root.el });
            if (this.props.xml) {
                await this.modeler.importXML(this.props.xml);
                this.modeler.get("canvas").zoom("fit-viewport");
            }
        });
    }
}


export class BpmnView extends Component {
    static template = "workflow.bpmn_view";
    static components = {
        Layout,
        BpmnViewer,
        BpmnApprovalDesigner,
    };
    static props = {
        action: {type: Object, optional: true},
        display: {type: Object, optional: true},
        actionId: {type: Number, optional: true},
        updateActionState: {type: Function, optional: true},
        className: {type: String, optional: true},
        context: { type: Object, optional: true },
    };

    setup() {
        this.pwaService = useService("pwa");
        this.homeMenu = useService("home_menu");
        this.display = {
            ...this.props.display,
        };
        this.state = useState({
            activeId:0,
            approveType:{}
        });
        this.orm = useService("orm");
         onWillStart(async () => {
             if (this.props.action.context.active_id) {
                 const [record] = await this.orm.read("workflow.approval.category", [this.props.action.context.active_id], ["display_name", "bpmn_xml"]);
                this.state.approveType = record;
            }
         });
    }

    close() {
        this.homeMenu.toggle();
    }

    onClickRefresh() {
        this.env.reload();
    }


}

registry.category('actions').add('workflow_bpmn_view', BpmnView)