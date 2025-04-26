
import fnmatch
import requests
from pathlib import Path
from config import settings
from auth import refresh_access_token_if_needed
from streams import fetch_streams_by_group_name
from process_24_7 import process_24_7
from process_movie import process_movie
from process_tv import process_tv
from log import setup_logger
from models import DispatcharrStream

logger = setup_logger(__name__)



def main():
    # load_skip_cache()
    token = refresh_access_token_if_needed()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    groups = requests.Session().get(f"{settings.api_base}/api/channels/streams/groups/", headers=headers, timeout=10).json()

    # Define routing: (pattern_list, feature_toggle, handler)
    routes = [
        (settings.groups_24_7, settings.process_groups_24_7, process_24_7),
        (settings.tv_series_groups, settings.process_tv_series_groups, process_tv),
        (settings.movies_groups, settings.process_movies_groups, process_movie),
    ]

    for grp in groups:
        handler = None
        # Select handler based on first matching route
        for patterns, enabled, func in routes:
            if enabled and any(fnmatch.fnmatch(grp, pat) for pat in patterns):
                logger.info("🔍 %s Group detected: %s", func.__name__, grp)
                handler = func
                break
        else:
            logger.info("⚠️  Skipping unknown or disabled group: %s", grp)
            continue
        
        if not handler:
            continue

        streams = fetch_streams_by_group_name(grp, headers)
        logger.info("[STREAM] 📦 Found %d streams in group '%s'", len(streams), grp)
        for s in streams:
            stream = DispatcharrStream.from_dict(s)

            if settings.only_updated_streams and not stream.was_updated_today:
                # logger.warning(f"[STREAM] ❌ Not updated: {stream.name}")
                continue

            base = settings.stream_base_url if settings.stream_base_url.startswith("http") else f"{settings.api_base}{settings.stream_base_url}"
            dispatcharr_url = base + stream.stream_hash

            # call process_24_7 / process_tv / process_movie
            handler(
                stream.name,
                stream.id,
                Path(settings.output_root),
                grp,
                headers,
                dispatcharr_url
            )

    # save_skip_cache()

if __name__ == '__main__':
    main()
