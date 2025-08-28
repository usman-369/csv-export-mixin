import re
import csv
import logging
from datetime import datetime
from django.db import connection
from django.http import StreamingHttpResponse

logger = logging.getLogger("requests")


def sanitize_log_input(text):
    """
    Sanitize input for safe logging by removing/replacing dangerous characters.

    This function prevents log injection attacks by:
    - Removing newline and carriage return characters
    - Replacing control characters with safe alternatives
    - Truncating extremely long strings to prevent log flooding

    Args:
        text (str): The text to sanitize

    Returns:
        str: Sanitized text safe for logging
    """
    if not isinstance(text, str):
        text = str(text)

    # Remove newlines and carriage returns that could be used for log injection
    text = text.replace("\n", "\\n").replace("\r", "\\r")

    # Remove or replace other control characters
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # Truncate very long strings to prevent log flooding
    max_length = 1000
    if len(text) > max_length:
        text = text[:max_length] + "... [truncated]"

    return text


class Echo:
    """
    A pseudo file-like object that implements only the write method.

    This class is used as a buffer for the csv.writer when creating streaming
    CSV responses. Instead of writing to a file, it simply returns the value
    that would be written, allowing it to work with Django's StreamingHttpResponse.

    This is a common pattern for CSV streaming in Django applications.
    """

    def write(self, value):
        """
        Write method that simply returns the input value.

        Args:
            value (str): The string to be "written"

        Returns:
            str: The same value that was passed in
        """
        return value


def stream_csv_response(filename, headers, queryset, row_generator_fn, chunk_size=1000):
    """
    Create a streaming CSV file response for large querysets.

    This function generates a CSV file as a streaming HTTP response, processing
    records in chunks to optimize memory usage. It's particularly useful for
    large datasets that would consume too much memory if loaded all at once.

    The response includes proper headers for file download and uses UTF-8 with BOM
    encoding to ensure compatibility with Excel and other CSV readers.

    Args:
        filename (str): Base filename for the downloaded CSV (without extension).
            A timestamp will be automatically appended.
        headers (list[str]): List of column headers for the CSV file.
        queryset (QuerySet): Django QuerySet to export. Should support iterator() method.
        row_generator_fn (Callable): Function that takes a model instance and returns
            a list of string values for the CSV row.
        chunk_size (int, optional): Number of records to fetch from DB per chunk.
            Defaults to 1000. Larger values may use more memory
            but reduce database queries.

    Returns:
        StreamingHttpResponse: Django HTTP response that streams the CSV data.
            Content-Type is set to 'text/csv' and includes
            Content-Disposition header for file download.

    Raises:
        Exception: Re-raises any exception that occurs during CSV generation,
            after logging the error.

    Example:
        def my_row_generator(obj):
            return [obj.name, obj.email, str(obj.created_date)]

        response = stream_csv_response(
            filename="users",
            headers=["Name", "Email", "Created"],
            queryset=User.objects.all(),
            row_generator_fn=my_row_generator,
            chunk_size=500
        )

    Note:
        - The filename will have a timestamp appended automatically
        - Invalid filename characters are replaced with underscores
        - Database connection is explicitly closed after processing
        - Errors in individual row processing are logged but don't stop the export
        - All log messages are sanitized to prevent log injection attacks
    """
    safe_headers = headers or []
    record_count = queryset.count()

    # Log the start of CSV generation with key metrics
    logger.info(
        "Starting CSV generation - Records: %d, Fields: %d, Chunk size: %d", record_count, len(safe_headers), chunk_size
    )

    def row_generator():
        """
        Internal generator function that yields CSV rows.

        This nested function handles the actual data generation, including:
        - Yielding the header row first
        - Processing queryset in chunks for memory efficiency
        - Error handling for individual rows
        - Proper database connection cleanup

        Yields:
            list: Lists of string values representing CSV rows

        Note:
            If an error occurs processing an individual row, it logs the error
            and continues with the next row. If a critical error occurs,
            it yields an error message row and stops processing.
        """
        processed_count = 0
        try:
            yield safe_headers

            # Process in chunks to optimize memory usage
            for obj in queryset.iterator(chunk_size=chunk_size):
                try:
                    row = row_generator_fn(obj)
                    if row:  # Skip None/empty rows
                        yield row
                        processed_count += 1
                except Exception as e:
                    # Sanitize all logged data to prevent log injection
                    safe_pk = sanitize_log_input(str(getattr(obj, "pk", "unknown")))
                    safe_error = sanitize_log_input(str(e))

                    logger.error("Error processing row for object %s: %s", safe_pk, safe_error)
                    continue

        except Exception as e:
            # Sanitize error message before logging
            safe_error = sanitize_log_input(str(e))
            logger.error("Critical error generating CSV: %s", safe_error)
            yield ["Error generating CSV data"]

        finally:
            # Log completion with final stats
            logger.info("CSV generation completed - Processed: %d/%d records", processed_count, record_count)
            # Close DB connection explicitly to prevent connection leaks
            connection.close()

    # Create a pseudo file buffer for the CSV writer
    pseudo_buffer = Echo()
    writer = csv.writer(pseudo_buffer)

    try:
        # Generate timestamped filename
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        filename = filename.removesuffix(".csv")
        filename = f"{filename}_{timestamp}.csv"
        # Sanitize filename by replacing invalid characters with underscores
        filename = re.sub(r"[^\w_.-]", "_", filename)

        # Create streaming response with CSV data
        # Use UTF-8 with BOM for Excel compatibility
        response = StreamingHttpResponse(
            (writer.writerow(row) for row in row_generator()), content_type="text/csv; charset=utf-8-sig"
        )
        # Set download headers
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        # Sanitize error message before logging
        safe_error = sanitize_log_input(str(e))
        logger.error("Error creating CSV response: %s", safe_error)
        raise
