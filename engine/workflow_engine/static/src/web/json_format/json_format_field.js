/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useInputField } from "@web/views/fields/input_field_hook";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component } from "@odoo/owl";

export class JsonFormatField extends Component {
    static template = "workflow_engine.JsonFormatField";
    static props = {
        ...standardFieldProps,
        rows: { type: Number, optional: true },
        indent: { type: Number, optional: true },
        placeholder: { type: String, optional: true },
    };
    static defaultProps = {
        rows: 8,
        indent: 2,
    };

    setup() {
        useInputField({
            refName: "jsonInput",
            getValue: () => this._formatForEditor(this.props.record.data[this.props.name]),
            parse: (value) => this._parseEditorValue(value),
        });
    }

    get fieldType() {
        return this.props.record.fields[this.props.name]?.type || "json";
    }

    get isJsonType() {
        return this.fieldType === "json";
    }

    get formattedValue() {
        return this._formatForReadonly(this.props.record.data[this.props.name]);
    }

    get errorMessage() {
        if (!this.props.record.isFieldInvalid(this.props.name)) {
            return "";
        }
        return _t("Invalid JSON format");
    }

    _tryParseString(value) {
        try {
            return { ok: true, value: JSON.parse(value) };
        } catch {
            return { ok: false, value: null };
        }
    }

    _formatForReadonly(value) {
        return this._formatForEditor(value);
    }

    _formatForEditor(value) {
        if (value === undefined || value === null || value === "") {
            return "";
        }
        if (typeof value === "string") {
            const parsed = this._tryParseString(value);
            if (!parsed.ok) {
                return value;
            }
            return JSON.stringify(parsed.value, null, this.props.indent);
        }
        return JSON.stringify(value, null, this.props.indent);
    }

    _parseEditorValue(rawValue) {
        const value = (rawValue || "").trim();
        if (!value) {
            return this.isJsonType ? false : "";
        }
        let parsed;
        try {
            parsed = JSON.parse(value);
        } catch {
            throw new Error(_t("Invalid JSON format"));
        }
        if (this.isJsonType) {
            return parsed;
        }
        return JSON.stringify(parsed);
    }
}

function parsePositiveInteger(value, fallback) {
    const parsed = Number(value);
    if (Number.isInteger(parsed) && parsed > 0) {
        return parsed;
    }
    return fallback;
}

export const jsonFormatField = {
    component: JsonFormatField,
    displayName: _t("JSON Formatter"),
    supportedTypes: ["json", "text", "char"],
    supportedOptions: [
        {
            label: _t("Rows"),
            name: "rows",
            type: "integer",
        },
        {
            label: _t("Indent"),
            name: "indent",
            type: "integer",
        },
    ],
    extractProps: ({ options, attrs, placeholder }) => ({
        placeholder,
        rows: parsePositiveInteger(options?.rows ?? attrs?.rows, 8),
        indent: parsePositiveInteger(options?.indent, 2),
    }),
};

registry.category("fields").add("json_format", jsonFormatField);
registry.category("fields").add("json_pretty", jsonFormatField);
