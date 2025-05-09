# strmgen/core/httpclient.py

from httpx import AsyncClient, Limits, Timeout
from aiolimiter import AsyncLimiter

from strmgen.core.config import get_settings

# Load settings once into module-level variable for client configuration
d = get_settings()

# one-and-only AsyncClient for your entire app
async_client = AsyncClient(
    base_url=d.api_base,
    timeout=Timeout(10.0)
)

# Constants
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p"

# Shared HTTP Clients for TMDb
# Configured with connection limits and timeouts
tmdb_client = AsyncClient(
    base_url=TMDB_BASE,
    limits=Limits(
        max_connections=20,
        max_keepalive_connections=10
    ),
    timeout=Timeout(10.0)
)

tmdb_image_client = AsyncClient(
    base_url=TMDB_IMG_BASE,
    limits=Limits(
        max_connections=20,
        max_keepalive_connections=10
    ),
    timeout=Timeout(10.0)
)

# Rate limiter parameterized by settings
tmdb_limiter = AsyncLimiter(
    max_rate=d.tmdb_rate_limit,
    time_period=10
)
