from dataclasses import dataclass
from datetime import datetime, timedelta

from client_src.const import SERVER_SEP


@dataclass
class TransferProgress:
    current_file_src: str

    file_size: int
    size_sent: int

    start_time: datetime

    current_file_count: int
    file_count: int = 1

    @staticmethod
    def human_readable_size(size, decimal_places=2):
        for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']:
            if size < 1024.0 or unit == 'PiB':
                break
            size /= 1024.0
        return f"{size:.{decimal_places}f} {unit}"

    def __str__(self):
        speed_str = "N/A B/s"
        time_needed_str = "N/A s"
        time_ = (datetime.now()-self.start_time)

        if time_.seconds > 2:
            speed = self.size_sent/time_.seconds
            speed_str = TransferProgress.human_readable_size(speed, 0)
            time_needed = timedelta(seconds=(self.file_size - self.size_sent)/speed)
            time_needed_str = str(time_needed).split('.', 2)[0]

        return f"({self.current_file_count}/{self.file_count}) files - " \
               f"{self.current_file_src} [{TransferProgress.human_readable_size(self.size_sent)}/" \
               f"{TransferProgress.human_readable_size(self.file_size)}, {str(time_).split('.', 2)[0]}/{time_needed_str}, " \
               f"{speed_str}/s]"


class ResponseMsg:
    """Defines trace information when communicating with server"""
    client_send: str
    client_read: str
    server_response: str

    def __str__(self) -> str:
        msg = []
        if hasattr(self, "server_response"):
            msg.append(f"server response: {self.server_response}")
        if hasattr(self, "client_send"):
            msg.append(f"client send: {self.client_send}")
        if hasattr(self, "client_read"):
            msg.append(f"client read: {self.client_read}")
        if len(msg) > 0:
            return ", ".join(msg)
        return ""


@dataclass(init=False)
class AddServerDialogData:
    host: str = None
    port: int = None

    def __str__(self) -> str:
        return f"{self.host}{SERVER_SEP}{self.port}"
