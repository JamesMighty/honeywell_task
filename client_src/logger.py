from logging import DEBUG

from common.logging import CustomLogger


class ClientLogger(CustomLogger):
    """"Defines custom client logger"""

    MSG_FORMAT = "[%(asctime)s] [%(name)s] [%(levelname)7s] [%(window)12s] | %(message)s"
    DEFAULTS = {
            "window": "",
        }
    NAME = "client"

    def __init__(self, stream_log_level: int = DEBUG, file_log_level: int = DEBUG) -> None:
        super().__init__(
            ClientLogger.NAME,
            ClientLogger.MSG_FORMAT,
            ClientLogger.DEFAULTS,
            stream_log_level,
            file_log_level
            )
