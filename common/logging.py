import sys
from logging import DEBUG, FileHandler, Formatter, Logger, StreamHandler
from pathlib import Path


class CustomLogger(Logger):

    def __init__(self, name: str, msg_format: str, defaults: dict[str, str], stream_log_level: int = DEBUG, file_log_level: int = DEBUG) -> None:
        super().__init__(name, stream_log_level)

        logFormatter = Formatter(msg_format, defaults=defaults)

        file_handler = FileHandler(Path(f"./{name}-log.txt"), encoding="utf-8")
        file_handler.setFormatter(logFormatter)
        file_handler.setLevel(file_log_level)

        stream_handler = StreamHandler(sys.stdout)
        stream_handler.setFormatter(logFormatter)
        stream_handler.setLevel(stream_log_level)

        self.addHandler(file_handler)
        self.addHandler(stream_handler)
        self.debug(f"Log '{name}' built.")
