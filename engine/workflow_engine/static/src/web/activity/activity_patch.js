/** @odoo-module */

import { Activity } from "@mail/core/web/activity";

import { Approval } from "@workflow_engine/web/activity/approval";

Object.assign(Activity.components, { Approval });
