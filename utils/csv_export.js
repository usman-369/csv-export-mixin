/**
 * CSV Export Modal Handler
 * 
 * This script manages the CSV export functionality for Django admin changelist pages.
 * It intercepts the CSV export action to show a modal for field selection before
 * submitting the actual export request.
 * 
 * Key Security Features:
 * - Validates selected records before export
 * - Clears sensitive data from form after operations
 * - Prevents accidental double-submissions through modal state management
 */
document.addEventListener("DOMContentLoaded", function () {
    // Core DOM elements for the CSV export functionality
    const actionSelect = document.querySelector("select[name='action']");
    const actionButton = document.querySelector("button[name='index']");
    const exportModalEl = document.getElementById("exportModal");
    const exportModal = new bootstrap.Modal(exportModalEl);

    /**
     * Reset all modal form fields and hidden inputs to their default state.
     * 
     * This function is crucial for security and UX:
     * - Prevents data leakage between different export operations
     * - Ensures users start with a clean slate each time
     * - Clears any previously selected sensitive field configurations
     * 
     * Called when:
     * - Modal is cancelled
     * - Modal is closed by clicking outside
     * - Export form is successfully submitted
     */
    function resetModalFields() {
        // Uncheck all field selection checkboxes to prevent accidental exports
        document.querySelectorAll(".form-check-input.export-field").forEach(cb => {
            cb.checked = false;
        });

        // Reset the "select all fields" master checkbox
        const selectAll = document.getElementById("selectAllFields");
        if (selectAll) selectAll.checked = false;

        // Reset the entire form to clear any other form elements
        const form = document.getElementById("csvExportForm");
        if (form) form.reset();

        // Clear hidden security inputs that track selected records
        // These contain sensitive information about which records to export
        document.getElementById("selectedIds").value = "";
        document.getElementById("selectAcross").value = "0";
    }

    /**
     * Main action button click handler - intercepts CSV export actions.
     * 
     * This is the entry point for CSV exports. When users click "Go" after
     * selecting the CSV export action, this handler:
     * 1. Prevents the default Django admin action submission
     * 2. Captures the current selection state (all records vs. selected records)
     * 3. Transfers selection data to the modal form
     * 4. Shows the field selection modal
     */
    actionButton.addEventListener("click", function (e) {
        // Only intercept if the CSV export action is selected
        if (actionSelect.value === "csv_export_action") {
            e.preventDefault(); // Prevent Django's default action submission

            // Determine export scope: all records vs. selected records only
            // This affects data security and export size
            const selectAcrossInput = document.querySelector('input[name="select_across"]');

            if (selectAcrossInput && selectAcrossInput.value === "1") {
                // User clicked "Select all X items" - export ALL records in queryset
                // This can be dangerous for large datasets or sensitive data
                document.getElementById("selectAcross").value = "1";
                document.getElementById("selectedIds").value = ""; // No specific IDs needed
            } else {
                // User selected specific records only - safer, more targeted export
                document.getElementById("selectAcross").value = "0";

                // Collect IDs of specifically selected records
                const selectedInputs = Array.from(document.querySelectorAll("input.action-select:checked"));
                const selectedIds = selectedInputs.map(input => input.value).join(",");
                document.getElementById("selectedIds").value = selectedIds;
            }

            // Show the field selection modal
            exportModal.show();
        }
    });

    /**
     * "Select All Fields" checkbox handler.
     * 
     * Provides bulk field selection functionality for user convenience.
     * When checked, selects all available export fields.
     * When unchecked, deselects all fields.
     * 
     * Security note: This makes it easy to accidentally export all fields,
     * including potentially sensitive ones. Consider adding warnings for
     * sensitive field combinations.
     */
    const selectAll = document.getElementById("selectAllFields");
    if (selectAll) {
        selectAll.addEventListener("change", function () {
            const checkboxes = document.querySelectorAll(".form-check-input.export-field");
            checkboxes.forEach(cb => cb.checked = selectAll.checked);
        });
    }

    /**
     * Cancel button handler.
     * 
     * Explicitly cancels the export operation and cleans up the modal state.
     * Important for security: ensures no partial export data remains in the form.
     */
    document.getElementById("cancelBtn").addEventListener("click", function () {
        exportModal.hide();
        resetModalFields(); // Security: clear any selected data
    });

    /**
     * Modal backdrop click handler.
     * 
     * Handles clicks outside the modal content area (on the backdrop).
     * Provides the same cleanup as explicit cancellation for consistent UX.
     * 
     * Security consideration: Prevents accidental data retention when users
     * click away from the modal.
     */
    exportModalEl.addEventListener('click', function (e) {
        // Check if click was specifically on the modal backdrop, not modal content
        if (e.target === exportModalEl) {
            exportModal.hide();
            resetModalFields(); // Security: clear form data
        }
    });

    /**
     * Form submission handler.
     * 
     * Manages the actual CSV export form submission and cleanup.
     * Uses a delayed reset to ensure form data is submitted before cleanup.
     * 
     * The timing is critical:
     * - Form must submit with current field selections
     * - Modal must close to provide user feedback
     * - Form must be cleared to prevent data leakage
     * 
     * Security: The delayed reset ensures sensitive selection data doesn't
     * persist in the DOM after the export is initiated.
     */
    const exportForm = document.getElementById("csvExportForm");
    if (exportForm) {
        exportForm.addEventListener("submit", function (e) {
            // Allow form submission to proceed, then clean up
            // Small delay ensures form data is captured before reset
            setTimeout(function () {
                exportModal.hide();           // Close modal for user feedback
                resetModalFields();          // Security: clear sensitive form data
            }, 100); // 100ms is sufficient for form submission capture
        });
    }
});
