/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, useRef, useState } from "@odoo/owl";

const MAX_EXCEL_SIZE = 5 * 1024 * 1024;

export class RequestorExcelImportField extends Component {
    static template = "workflow_engine.RequestorExcelImportField";
    static props = {
        ...standardFieldProps,
        acceptedFileExtensions: { type: String, optional: true },
        fileNameField: { type: String, optional: true },
        hideOnMobile: { type: Boolean, optional: true },
    };
    static defaultProps = {
        acceptedFileExtensions: ".xlsx",
        fileNameField: "excel_filename",
        hideOnMobile: false,
    };

    setup() {
        this.notification = useService("notification");
        this.fileInput = useRef("fileInput");
        this.state = useState({ loading: false });
    }

    get fileName() {
        return this.props.record.data[this.props.fileNameField] || "";
    }

    get rootClass() {
        const displayClass = this.props.hideOnMobile ? "d-none d-md-flex" : "d-flex";
        return `o_requestor_excel_import ${displayClass} align-items-center gap-2`;
    }

    onChooseFile() {
        if (!this.props.readonly) {
            this.fileInput.el?.click();
        }
    }

    async onFileChange(ev) {
        const file = ev.target.files[0];
        if (!file) {
            return;
        }
        if (!file.name.toLowerCase().endsWith(".xlsx")) {
            this._notifyError(_t("Please choose a valid Excel .xlsx file using the provided template."));
            return;
        }
        if (file.size > MAX_EXCEL_SIZE) {
            this._notifyError(_t("File is too large. Max 5MB."));
            return;
        }

        this.state.loading = true;
        try {
            const data = await this._readAsBase64(file);
            const changes = { [this.props.name]: data };
            if (this.props.fileNameField in this.props.record.fields) {
                changes[this.props.fileNameField] = file.name;
            }
            await this.props.record.update(changes);
        } catch (error) {
            this._notifyError(error.message || _t("Unable to load the Excel file."));
        } finally {
            this.state.loading = false;
            ev.target.value = "";
        }
    }

    _readAsBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result.split(",")[1]);
            reader.onerror = () => reject(new Error(_t("Unable to read the selected file.")));
            reader.readAsDataURL(file);
        });
    }

    _notifyError(message) {
        this.notification.add(message, { type: "danger" });
        if (this.fileInput.el) {
            this.fileInput.el.value = "";
        }
    }
}

export const requestorExcelImportField = {
    component: RequestorExcelImportField,
    supportedTypes: ["binary"],
    extractProps: ({ attrs, options }) => ({
        acceptedFileExtensions: options.accepted_file_extensions || ".xlsx",
        fileNameField: attrs.filename || "excel_filename",
        hideOnMobile: Boolean(options.hide_on_mobile),
    }),
};

registry.category("fields").add("requestor_excel_import", requestorExcelImportField);
