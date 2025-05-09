from httpx import AsyncClient, Limits, Timeout

from .config import settings
from aiolimiter import AsyncLimiter


# one‐and‐only AsyncClient for your entire app
async_client = AsyncClient(
    base_url=settings.api_base,
    # supply a single “default” timeout (applies equally to connect/read/write/pool)
    timeout=Timeout(10.0) 
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
    timeout=Timeout(10     # seconds to wait for a connection from the pool
    ),
)

tmdb_image_client = AsyncClient(
    base_url=TMDB_IMG_BASE,
    limits=Limits(
        max_connections=20,
        max_keepalive_connections=10
    ),
    timeout=Timeout(10
    ),
)

# Rate limiter parameterized by settings
tmdb_limiter = AsyncLimiter(max_rate=settings.tmdb_rate_limit, time_period=10)
