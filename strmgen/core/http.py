import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Create a single, shared session with connection pooling and retry logic

def create_session(
    pool_connections: int = 10,
    pool_maxsize: int = 50,
    total_retries: int = 3,
    backoff_factor: float = 0.3,
    status_forcelist: tuple = (429, 502, 503, 504),
) -> requests.Session:
    """
    Returns a requests.Session configured with a HTTPAdapter that
    handles connection pooling and automatic retries on specified status codes.

    :param pool_connections: Number of connection pools to cache
    :param pool_maxsize: Maximum number of connections to save in the pool
    :param total_retries: Total number of retry attempts
    :param backoff_factor: Backoff multiplier between retry attempts
    :param status_forcelist: HTTP status codes that should trigger a retry
    """
    session = requests.Session()

    # Configure retry strategy
    retry_strategy = Retry(
        total=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["HEAD", "GET", "OPTIONS", "POST", "PUT", "DELETE"],
    )

    # Mount adapter with the retry strategy to both HTTP and HTTPS
    adapter = HTTPAdapter(
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
        max_retries=retry_strategy,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session

# Shared session instance
session = create_session()
