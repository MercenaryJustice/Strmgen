import logging

from strmgen.api.routers.logs import SSELogHandler


def setup_sse_logging():
    handler = SSELogHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logging.getLogger().addHandler(handler)