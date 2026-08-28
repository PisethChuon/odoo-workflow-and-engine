/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { CharField, charField } from "@web/views/fields/char/char_field";
import { onMounted, onWillStart, onWillUnmount, useEffect } from "@odoo/owl";
import { AssetsLoadingError, loadJS } from "@web/core/assets";

export class InputMaskField extends CharField {
    static template = "workflow_engine.InputMaskField";
    static props = {
        ...CharField.props,
        mask: { type: String, optional: true },
        reg: { type: String, optional: true },
        maskOptions: { type: [Object, String], optional: true },
        regexMode: { type: String, optional: true },
        keepMaskedValue: { type: Boolean, optional: true },
        allowPartial: { type: Boolean, optional: true },
    };
    static defaultProps = {
        ...CharField.defaultProps,
        maskOptions: "",
        regexMode: "auto",
        keepMaskedValue: false,
        allowPartial: false,
    };

    setup() {
        super.setup();
        this._maskInstance = null;
        this._compiledRegex = null;
        this._warnedInvalidRegex = false;
        this.notification = useService("notification");

        onWillStart(async () => {
            try {
                await loadJS("/workflow_engine/static/lib/imask/imask.js");
            } catch (error) {
                if (!(error instanceof AssetsLoadingError)) {
                    throw error;
                }
            }
        });

        onMounted(() => {
            this._compiledRegex = this._buildRegex(this.props.reg);
            this._refreshMask();
        });

        useEffect(
            () => {
                this._compiledRegex = this._buildRegex(this.props.reg);
                this._refreshMask();
            },
            () => [this.props.mask, this.props.reg, this.props.readonly]
        );

        useEffect(
            () => {
                this._syncMaskValue();
            },
            () => [this.props.record.data[this.props.name]]
        );

        onWillUnmount(() => {
            this._destroyMask();
        });
    }

    parse(value) {
        const normalized = this._normalizeOutgoingValue(value);
        if (!this._isRegexValid(normalized)) {
            throw new Error(_t("Invalid format"));
        }
        return normalized;
    }

    onBlur() {
        super.onBlur();
        const currentValue = this._normalizeOutgoingValue(this.input?.el?.value || "");
        if (!this._isRegexValid(currentValue)) {
            this.props.record.setInvalidField(this.props.name);
            this.notification.add(
                _t("Invalid format. Expected: ") + this._getExpectedHint(),
                { type: "danger" }
            );
            return;
        }
        this.props.record.resetFieldValidity(this.props.name);
    }

    _normalizeOutgoingValue(rawValue) {
        if (!this._maskInstance) {
            return super.parse(rawValue || "");
        }
        const mustKeepMasked = this.props.keepMaskedValue || this.props.allowPartial;
        const value = mustKeepMasked
            ? (this._maskInstance.value || "")
            : (this._maskInstance.unmaskedValue || "");
        return this.shouldTrim ? value.trim() : value;
    }

    _getExpectedHint() {
        const hint = this._displayMaskTemplate(this.props.mask || "") || (this.props.reg || "");
        return hint || _t("configured pattern");
    }

    _buildRegex(pattern) {
        if (!pattern) {
            return null;
        }
        try {
            return new RegExp(pattern);
        } catch (error) {
            if (!this._warnedInvalidRegex) {
                this.notification.add(
                    _t("Invalid Regular Expression configured for Input Mask widget."),
                    { type: "warning" }
                );
                this._warnedInvalidRegex = true;
            }
            console.warn("input_mask: invalid regex option", pattern, error);
            return null;
        }
    }

    _isRegexValid(value) {
        if (!this._compiledRegex) {
            return true;
        }
        const mode = String(this.props.regexMode || "auto").trim().toLowerCase();
        const normalizedValue = value || "";
        const maskedValue = this._maskInstance ? (this._maskInstance.value || "") : normalizedValue;
        const unmaskedValue = this._maskInstance
            ? (this._maskInstance.unmaskedValue || "")
            : normalizedValue;

        if (mode === "masked") {
            return this._testRegex(maskedValue);
        }
        if (mode === "unmasked") {
            return this._testRegex(unmaskedValue);
        }

        // auto mode: consider both representations so regex can be configured
        // in view options without forcing a storage mode.
        return (
            this._testRegex(normalizedValue) ||
            this._testRegex(maskedValue) ||
            this._testRegex(unmaskedValue)
        );
    }

    _refreshMask() {
        const input = this.input?.el;
        if (!input || this.props.readonly) {
            this._destroyMask();
            return;
        }
        const options = this._getMaskOptions();
        if (!options) {
            this._destroyMask();
            return;
        }
        if (!window.IMask) {
            return;
        }
        this._destroyMask();
        this._maskInstance = window.IMask(input, options);
        this._syncMaskValue();
    }

    _getMaskOptions() {
        const configuredMask = String(this.props.mask || "").trim();
        if (!configuredMask) {
            return null;
        }
        const configuredMaskOptions = this._parseMaskOptions(this.props.maskOptions);
        if (configuredMask === "weight") {
            return {
                mask: Number,
                min: 5,
                max: 200,
                scale: 2,
                radix: ".",
                mapToRadix: ["."],
                thousandsSeparator: "",
                ...(configuredMaskOptions || {}),
            };
        }
        if (configuredMask === "decimal") {
            return {
                mask: Number,
                scale: 2,
                radix: ".",
                mapToRadix: ["."],
                thousandsSeparator: "",
                ...(configuredMaskOptions || {}),
            };
        }
        if (configuredMask.startsWith("{")) {
            try {
                const parsed = JSON.parse(configuredMask);
                if (parsed && typeof parsed === "object") {
                    return {
                        ...parsed,
                        ...(configuredMaskOptions || {}),
                    };
                }
            } catch {
                // Keep backward compatibility when configured as plain string mask.
            }
        }
        const normalizedTemplate = this._normalizeMaskTemplate(configuredMask);
        if (this.props.allowPartial) {
            const partialRegex = this._buildPartialRegexFromTemplate(normalizedTemplate);
            if (partialRegex) {
                return {
                    mask: partialRegex,
                    ...(configuredMaskOptions || {}),
                };
            }
        }
        const placeholderChar = "_";
        return {
            mask: normalizedTemplate,
            placeholderChar,
            lazy: true,
            ...(configuredMaskOptions || {}),
        };
    }

    _parseMaskOptions(maskOptions) {
        if (!maskOptions) {
            return null;
        }
        if (typeof maskOptions === "object") {
            return maskOptions;
        }
        if (typeof maskOptions !== "string") {
            return null;
        }
        const raw = maskOptions.trim();
        if (!raw) {
            return null;
        }
        try {
            const parsed = JSON.parse(raw);
            return parsed && typeof parsed === "object" ? parsed : null;
        } catch {
            return null;
        }
    }

    _testRegex(value) {
        if (!this._compiledRegex) {
            return true;
        }
        const regex = new RegExp(this._compiledRegex.source, this._compiledRegex.flags);
        return regex.test(value || "");
    }

    _expandMaskLiterals(template) {
        if (!template) {
            return "";
        }
        // IMask literal groups like "{/}" should be interpreted as visible literal "/".
        return template.replace(/\{([^{}]*)\}/g, "$1");
    }

    _displayMaskTemplate(template) {
        if (!template) {
            return "";
        }
        const configured = String(template).trim();
        if (!configured || configured.startsWith("{") || configured === "weight" || configured === "decimal") {
            return "";
        }
        const expanded = this._expandMaskLiterals(configured);
        return expanded.replace(/[0_#]/g, "#");
    }

    _normalizeMaskTemplate(template) {
        // Support user-friendly templates like ___/___ by mapping "_" and "#" to IMask digit token "0".
        return this._expandMaskLiterals(template).replace(/[_#]/g, "0");
    }

    _buildPartialRegexFromTemplate(template) {
        if (!template) {
            return null;
        }
        const placeholderToken = "0";
        if (!template.includes(placeholderToken)) {
            return null;
        }
        const segmentLengths = [];
        const separators = [];
        let currentSegment = 0;
        let currentSeparator = "";
        for (const ch of template) {
            if (ch === placeholderToken) {
                if (currentSeparator) {
                    separators.push(currentSeparator);
                    currentSeparator = "";
                }
                currentSegment += 1;
            } else {
                if (currentSegment > 0) {
                    segmentLengths.push(currentSegment);
                    currentSegment = 0;
                }
                currentSeparator += ch;
            }
        }
        if (currentSeparator) {
            separators.push(currentSeparator);
        }
        if (currentSegment > 0) {
            segmentLengths.push(currentSegment);
        }
        if (!segmentLengths.length) {
            return null;
        }

        const escapeRegex = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        let pattern = `^\\d{0,${segmentLengths[0]}}`;
        for (let i = 0; i < separators.length; i++) {
            const nextLen = segmentLengths[i + 1];
            if (!nextLen) {
                break;
            }
            pattern += `(?:${escapeRegex(separators[i])}\\d{0,${nextLen}})?`;
        }
        pattern += "$";
        try {
            return new RegExp(pattern);
        } catch {
            return null;
        }
    }

    _syncMaskValue() {
        const input = this.input?.el;
        if (!input) {
            return;
        }
        const raw = this.props.record.data[this.props.name];
        const normalized = raw === false || raw === null || raw === undefined ? "" : String(raw);
        if (!this._maskInstance) {
            const displayValue = this.props.readonly
                ? this._formatReadonlyDisplayValue(normalized)
                : normalized;
            if (input.value !== displayValue) {
                input.value = displayValue;
            }
            return;
        }
        const mustKeepMasked = this.props.keepMaskedValue || this.props.allowPartial;
        if (mustKeepMasked) {
            if (this._maskInstance.value !== normalized) {
                this._maskInstance.value = normalized;
            }
            return;
        }
        if (this._maskInstance.unmaskedValue !== normalized) {
            this._maskInstance.unmaskedValue = normalized;
        }
    }

    _formatReadonlyDisplayValue(value) {
        const raw = value || "";
        const configuredMask = String(this.props.mask || "").trim();
        if (!configuredMask || configuredMask === "weight" || configuredMask === "decimal" || configuredMask.startsWith("{")) {
            return raw;
        }
        const template = this._normalizeMaskTemplate(configuredMask);
        if (!template.includes("0")) {
            return raw;
        }
        const digits = raw.replace(/\D/g, "");
        if (!digits) {
            return raw;
        }
        let out = "";
        let index = 0;
        for (const ch of template) {
            if (ch === "0") {
                if (index >= digits.length) {
                    break;
                }
                out += digits[index];
                index += 1;
                continue;
            }
            // Only display literals between digit groups when there are more digits to show.
            if (index > 0 && index < digits.length) {
                out += ch;
            }
        }
        return out || raw;
    }

    _destroyMask() {
        if (!this._maskInstance) {
            return;
        }
        this._maskInstance.destroy();
        this._maskInstance = null;
    }
}

export const inputMaskField = {
    ...charField,
    component: InputMaskField,
    supportedOptions: [
        ...charField.supportedOptions,
        {
            label: _t("Mask"),
            name: "mask",
            type: "string",
        },
        {
            label: _t("Regular Expression"),
            name: "reg",
            type: "string",
        },
        {
            label: _t("Mask Options (JSON)"),
            name: "mask_options",
            type: "string",
        },
        {
            label: _t("Regex Mode"),
            name: "regex_mode",
            type: "string",
        },
        {
            label: _t("Keep Masked Value"),
            name: "keep_masked_value",
            type: "boolean",
        },
        {
            label: _t("Allow Partial Length"),
            name: "allow_partial",
            type: "boolean",
        },
    ],
    extractProps: ({ attrs, options }) => {
        const { mask, reg } = options;
        return {
            ...charField.extractProps({ attrs, options }),
            mask: mask || "",
            reg: reg || "",
            maskOptions: options.mask_options || "",
            regexMode: options.regex_mode || "auto",
            keepMaskedValue: Boolean(options.keep_masked_value),
            allowPartial: Boolean(options.allow_partial),
        };
    },
};

registry.category("fields").add("input_mask", inputMaskField);
