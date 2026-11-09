"""Keep operational access metadata without HR queries or client addresses."""

import logging


class RequestMetadataFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) == 5:
            _, method, path, version, status = record.args
            record.args = (
                "[client]",
                method,
                str(path).split("?", 1)[0],
                version,
                status,
            )
        return True
