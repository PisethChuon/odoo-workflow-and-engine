/** @odoo-module **/
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { BpmnDialog } from "./bpmn_dialog";


export class BpmnButton extends Component {
  static template = "workflow_engine.BpmnButton";
  static props = { ...standardWidgetProps };
  setup() { this.dialog = useService("dialog"); }

   async onClick() {
    //debugger;
    if (!this.props.record) return;
    const data = this.props.record.data || {};
    const version_id = data.version_id ? data.version_id[0] : null;
    const recordId = data.id ?  data.id : null
    let workflows =  await this.getSubWorkflows(recordId,data.res_model_name);
    if (workflows.length == 0) {
        workflows = await this.env.services.orm.call(
            "workflow.approval.category.version",
            "get_called_workflows",
            [version_id]
        );
    } 
    
    this.dialog.add(BpmnDialog, {
      data: { ...data, sub_workflows: workflows },
      title: "Preview Flow",
    });
  }

  async getSubWorkflows(id,res_model_name) {
    const allRequests = await this.env.services.orm.call(
        "workflow.base.approval.request",
        "get_all_by_parent",
        [id,res_model_name]
    );
    return allRequests;
  }
 

}

registry.category("view_widgets").add("bpmn_button", { component: BpmnButton });
