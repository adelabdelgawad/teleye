from prometheus_fastapi_instrumentator import Instrumentator, metrics

# Configure Instrumentator with exclusions
instrumentator = Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    excluded_handlers=[
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
    ],
    should_respect_env_var=False,
    should_instrument_requests_inprogress=True,
)

# Add custom metrics for better error tracking
instrumentator.add(
    metrics.request_size(
        should_include_handler=True,
        should_include_method=True,
        should_include_status=True,
    )
).add(
    metrics.response_size(
        should_include_handler=True,
        should_include_method=True,
        should_include_status=True,
    )
)
