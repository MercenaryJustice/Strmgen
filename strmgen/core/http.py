# strmgen/core/http.py

import logging
import httpx
from httpx import Limits

logger = logging.getLogger(__name__)

# Try importing RetryTransport for automatic retries
try:
    from httpx import RetryTransport
    _RETRY_AVAILABLE = True
except ImportError:
    RetryTransport = None  # type: ignore
    _RETRY_AVAILABLE = False


def create_async_client(
    pool_connections: int = 10,
    pool_maxsize: int = 50,
    total_retries: int = 3,
    backoff_factor: float = 0.3,
    status_forcelist: tuple[int, ...] = (429, 502, 503, 504),
) -> httpx.AsyncClient:
    """
    Returns an httpx.AsyncClient configured with connection pooling
    and, if available, automatic retries on specified status codes.

    :param pool_connections: Maximum keep-alive connections
    :param pool_maxsize: Maximum concurrent connections
    :param total_retries: Number of retry attempts on failures
    :param backoff_factor: Backoff multiplier between retry attempts
    :param status_forcelist: HTTP status codes that trigger a retry
    """
    limits = Limits(
        max_keepalive_connections=pool_connections,
        max_connections=pool_maxsize
    )

    if _RETRY_AVAILABLE and RetryTransport is not None:
        # configure retry transport
        transport = RetryTransport(
            retries=total_retries,
            backoff_factor=backoff_factor,
            status_forcelist=status_forcelist,
        )
        client = httpx.AsyncClient(limits=limits, transport=transport)
    else:
        logger.warning(
            "RetryTransport unavailable; HTTP client will not retry on failures"
        )
        client = httpx.AsyncClient(limits=limits)

    return client


# Shared async client instance
async_client: httpx.AsyncClient = create_async_client()
