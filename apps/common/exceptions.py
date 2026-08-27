from rest_framework.views import exception_handler as drf_exception_handler


def custom_exception_handler(exc, context):
    """
    Wraps DRF's default exception handler so every error response (validation
    errors, throttling, 404s, etc.) has a consistent shape:

        {"error": {"detail": ..., "code": "..."}}

    Keeps API consumers from having to special-case each exception type.
    """
    response = drf_exception_handler(exc, context)
    if response is not None:
        response.data = {
            "error": {
                "detail": response.data,
                "status_code": response.status_code,
            }
        }
    return response
