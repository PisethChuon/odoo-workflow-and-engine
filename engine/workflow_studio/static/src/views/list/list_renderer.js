import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { useService } from "@web/core/utils/hooks";

export const patchListRendererStudio = () => ({
    setup() {
        super.setup(...arguments);
        this.studioService = useService("workflow_studio");
    },
    /**
     * This function opens the studio mode with current view
     *
     * @override
     */
    onSelectedAddCustomField() {
        this.studioService.open();
    },

    isWorkflowStudioEditable() {
        return !this.studioService.mode && super.isWorkflowStudioEditable();
    },
});

export const unpatchListRendererStudio = patch(ListRenderer.prototype, patchListRendererStudio());
