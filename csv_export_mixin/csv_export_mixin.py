from django.urls import path
from django.contrib import admin
from django.contrib import messages
from django.utils.html import strip_tags
from django.http import HttpResponseBadRequest, HttpResponseRedirect

from .csv_export_utils import (
    logger,
    sanitize_log_input,
    stream_csv_response,
)


class CSVExportMixin:
    """
    A mixin for Django admin classes that adds CSV export functionality.

    This mixin provides a modal-based interface for selecting fields to export,
    with flexible field selection options.

    Attributes:
        csv_export_fields (tuple, optional): Explicit list of fields to include in export.
            If provided, only these fields will be available for selection.

        csv_exclude_fields (tuple, optional): Fields to exclude from export.
            If provided, all model fields except these will be available for selection.

        csv_filename (str, optional): Base filename for the exported CSV.
            Defaults to "export.csv". Timestamp will be automatically appended.

        chunk_size (int, optional): Number of records to process per chunk.
            Defaults to 1000. Useful for memory optimization with large datasets.

    Usage:
        class MyModelAdmin(CSVExportMixin, admin.ModelAdmin):
            csv_filename = "my_model_export.csv"
            csv_exclude_fields = ('password', 'internal_notes')
    """

    change_list_template = "admin/csv_export.html"

    @admin.action(description="Export selected fields as CSV")
    def csv_export_action(self, _request, _queryset):
        """
        Placeholder action for CSV export.

        The actual export logic is handled by the modal interface and csv_export_view.
        This action serves as a trigger to open the field selection modal.

        Args:
            _request: The HTTP request object (unused)
            _queryset: The queryset of selected objects (unused)
        """
        pass

    csv_export_action.short_description = "CSV Export"

    def get_csv_export_fields(self):
        """
        Get the fields available for CSV export.

        This method determines which fields should be available for selection
        in the CSV export modal based on the configured attributes.

        Priority order:
        1. csv_export_fields - explicit list of fields to include
        2. csv_exclude_fields - all model fields except these
        3. Default behavior - all model fields except default exclusions

        Returns:
            list: List of field names available for CSV export

        Note:
            Only actual model fields are considered when using csv_exclude_fields
            or default behavior. Admin methods must be explicitly included
            via csv_export_fields.
        """
        try:
            if hasattr(self, "csv_export_fields") and self.csv_export_fields:
                return self.csv_export_fields

            # Get all model fields only
            model_fields = []
            for field in self.model._meta.get_fields():
                # Skip reverse relations and many-to-many fields for simplicity
                if not field.many_to_many and not field.one_to_many:
                    model_fields.append(field.name)

            exclusions = set()

            # Check for csv_exclude_fields
            if hasattr(self, "csv_exclude_fields") and self.csv_exclude_fields:
                exclusions = set(self.csv_exclude_fields)
            else:
                # Default exclusions (you can customize this)
                # Get the primary key field name and exclude it along with password
                pk_field = self.model._meta.pk.name
                exclusions = {"password", pk_field}

            return [field for field in model_fields if field not in exclusions]

        except Exception as e:
            logger.error(
                "Error getting CSV export fields for model %s: %s",
                sanitize_log_input(getattr(self.model, "__name__", "unknown")),
                sanitize_log_input(str(e)),
            )
            return []

    def changelist_view(self, request, extra_context=None):
        """
        Override the changelist view to add CSV export field choices to template context.

        This method adds the available CSV export fields to the template context,
        formatted for display in the modal interface.

        Args:
            request: The HTTP request object
            extra_context (dict, optional): Additional context data

        Returns:
            HttpResponse: The changelist view response with added context
        """
        extra_context = extra_context or {}
        fields = self.get_csv_export_fields()

        # Create a list of tuples (field_name, display_name)
        field_choices = []
        for field in fields:
            # Format field name for display: replace underscores with spaces and title case
            display_name = field.replace("_", " ").title()
            field_choices.append((field, display_name))

        extra_context["csv_export_field_choices"] = field_choices
        return super().changelist_view(request, extra_context)

    def csv_export_view(self, request):
        """
        Handle CSV export requests from the modal form.

        This view processes the form submission from the CSV export modal,
        validates the selected fields and objects, and streams the CSV response.

        Args:
            request: The HTTP request object containing form data

        Returns:
            StreamingHttpResponse: CSV file download response
            HttpResponseBadRequest: If the request method is not POST
            HttpResponseRedirect: If validation fails (with error messages)

        Form Parameters:
            select_across (str): "1" if all objects should be exported, "0" for selected only
            selected_ids (str): Comma-separated list of object IDs (when select_across="0")
            selected_fields (list): List of field names to include in the export
        """
        if request.method != "POST":
            logger.warning(
                "Invalid CSV export request method %s from user %s for model %s",
                sanitize_log_input(request.method),
                sanitize_log_input(str(request.user)),
                sanitize_log_input(self.model.__name__),
            )
            return HttpResponseBadRequest("Invalid request")

        try:
            # Determine queryset and log export initiation
            if request.POST.get("select_across") == "1":
                queryset = self.get_queryset(request)
                scope = "all"
            else:
                ids = request.POST.get("selected_ids", "").split(",")
                if not ids or ids[0] == "":
                    logger.warning(
                        "CSV export failed: No records selected by user %s for model %s",
                        sanitize_log_input(str(request.user)),
                        sanitize_log_input(self.model.__name__),
                    )
                    messages.error(
                        request, "Please select at least one record to export."
                    )
                    return HttpResponseRedirect(
                        request.META.get("HTTP_REFERER", request.path)
                    )

                pk_field = self.model._meta.pk.name
                filter_kwargs = {f"{pk_field}__in": ids}
                queryset = self.model.objects.filter(**filter_kwargs)
                scope = "selected"

            # Validate fields
            fields = request.POST.getlist("selected_fields")
            if not fields:
                logger.warning(
                    "CSV export failed: No fields selected by user %s for model %s",
                    sanitize_log_input(str(request.user)),
                    sanitize_log_input(self.model.__name__),
                )
                messages.error(request, "Please select at least one field to export.")
                return HttpResponseRedirect(
                    request.META.get("HTTP_REFERER", request.path)
                )

            # Filter valid fields
            allowed_fields = self.get_csv_export_fields()
            original_field_count = len(fields)
            fields = [f for f in fields if f in allowed_fields]

            if len(fields) != original_field_count:
                logger.warning(
                    "Invalid fields filtered out for user %s, model %s. Original: %d, Valid: %d",
                    sanitize_log_input(str(request.user)),
                    sanitize_log_input(self.model.__name__),
                    original_field_count,
                    len(fields),
                )

            headers = [f.replace("_", " ").title() for f in fields]

            # Log successful export initiation with key details
            logger.info(
                "CSV export started - User: %s, Model: %s, Scope: %s, Records: %d, Fields: %d",
                sanitize_log_input(str(request.user)),
                sanitize_log_input(self.model.__name__),
                scope,
                queryset.count(),
                len(fields),
            )

            def row_generator(obj):
                """
                Generate a CSV row for a given model instance.

                This function extracts values for the selected fields from the model instance,
                handling both regular model fields and callable admin methods.

                Args:
                    obj: The model instance to extract data from

                Returns:
                    list: List of string values for the CSV row
                """
                row = []
                for field in fields:
                    try:
                        # Try getting from the model object
                        if hasattr(obj, field):
                            value = getattr(obj, field)
                            if callable(value):
                                try:
                                    value = value()
                                except Exception:
                                    value = ""
                        # Try getting from the admin class
                        elif hasattr(self, field):
                            try:
                                value = getattr(self, field)(obj)
                            except Exception:
                                value = ""
                        else:
                            value = ""
                        row.append(strip_tags(str(value)))
                    except Exception as e:
                        logger.error(
                            "Error processing field %s for object %s: %s",
                            sanitize_log_input(field),
                            sanitize_log_input(str(getattr(obj, "pk", "unknown"))),
                            sanitize_log_input(str(e)),
                        )
                        row.append("")
                return row

            filename = getattr(self, "csv_filename", "export.csv")

            return stream_csv_response(
                filename=filename,
                headers=headers,
                queryset=queryset,
                row_generator_fn=row_generator,
                chunk_size=getattr(self, "chunk_size", 1000),
            )

        except Exception as e:
            logger.error(
                "Critical error in CSV export for user %s, model %s: %s",
                sanitize_log_input(str(request.user)),
                sanitize_log_input(self.model.__name__),
                sanitize_log_input(str(e)),
            )
            messages.error(
                request, "An error occurred while exporting the CSV. Please try again."
            )
            return HttpResponseRedirect(request.META.get("HTTP_REFERER", request.path))

    def get_urls(self):
        """
        Add custom CSV export URL to the admin URLs.

        This method extends the default admin URLs with a custom endpoint
        for handling CSV export requests.

        Returns:
            list: List of URL patterns including the CSV export endpoint
        """
        urls = super().get_urls()
        model_name = self.model._meta.model_name
        custom = [
            path(
                "csv-export/",
                self.admin_site.admin_view(self.csv_export_view),
                name=f"{model_name}_csv_export_view",
            )
        ]
        return custom + urls
