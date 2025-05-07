from httpx import AsyncClient, Limits, Timeout

from .config import settings
from aiolimiter import AsyncLimiter


# one‐and‐only AsyncClient for your entire app
async_client = AsyncClient(
    base_url=settings.api_base,
    limits=Limits(
        max_connections=20,
        max_keepalive_connections=10,
    ),
    timeout=Timeout(
        connect=5.0,    # your connect/read/write defaults
        read=10.0,
        write=5.0,
        pool=30.0       # pool‐acquire timeout
    ),
)


# Constants
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p"


# Shared HTTP Clients
tmdb_client = AsyncClient(
    base_url=TMDB_BASE,
    limits=Limits(
        max_connections=20,
        max_keepalive_connections=10
    ),
    timeout=Timeout(
        connect=5.0,   # seconds to establish a connection
        read=10.0,     # seconds to read a response
        pool=30.0      # seconds to wait for a connection from the pool
    ),
)

tmdb_image_client = AsyncClient(
    base_url=TMDB_IMG_BASE,
    limits=Limits(
        max_connections=20,
        max_keepalive_connections=10
    ),
    timeout=Timeout(
        connect=5.0,
        read=10.0,
        pool=30.0
    ),
)

# Rate limiter parameterized by settings
tmdb_limiter = AsyncLimiter(max_rate=settings.tmdb_rate_limit, time_period=10)
