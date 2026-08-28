import { describe, expect, test } from "@odoo/hoot";

import { DynamicTransitionButtons } from "@workflow_engine/web/approval_button/approval_button";

describe.current.tags("desktop");

const renderer = Object.create(DynamicTransitionButtons.prototype);

test("workflow action icons always include a Font Awesome family class", () => {
    expect(renderer.getButtonIconClass({icon_class: "fa-check"})).toBe("me-1 fa fa-check");
    expect(renderer.getButtonIconClass({icon_class: "fa fa-check-circle"})).toBe(
        "me-1 fa fa-check-circle"
    );
    expect(renderer.getButtonIconClass({icon_class: "check"})).toBe("me-1 fa fa-check");
});

test("configured button style controls menu tone and single-button variant", () => {
    const approve = {
        action_key: "Approve",
        css_class: "btn btn-primary",
    };
    const configuredSuccessReject = {
        action_key: "Reject",
        css_class: "btn btn-success",
    };

    expect(renderer.getButtonCssClass(approve)).toInclude("wf-approval-action--primary");
    expect(renderer.getDesktopSingleButtonCssClass(approve)).toInclude("btn-primary");
    expect(renderer.getButtonCssClass(configuredSuccessReject)).toInclude(
        "wf-approval-action--success"
    );
    expect(renderer.getButtonCssClass(configuredSuccessReject)).not.toInclude(
        "wf-approval-action--danger"
    );
});
