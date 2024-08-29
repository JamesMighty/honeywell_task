from logging import DEBUG

from common.logging import CustomLogger


class ServerLogger(CustomLogger):
    """"Defines custom server logger"""

    MSG_FORMAT = "[%(asctime)s] [%(name)s] [%(levelname)7s] [%(client)20s] [%(action)10s] | %(message)s"
    DEFAULTS = {
            "client": "",
            "action": ""
        }
    NAME = "server"

    def __init__(self, stream_log_level: int = DEBUG, file_log_level: int = DEBUG) -> None:
        super().__init__(
            ServerLogger.NAME,
            ServerLogger.MSG_FORMAT,
            ServerLogger.DEFAULTS,
            stream_log_level,
            file_log_level
            )
