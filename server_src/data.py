

import json
import uuid
from collections import deque
from io import TextIOWrapper
from logging import Logger, LoggerAdapter

from common.const import ERROR_B, ETB
from common.data import ActionData, ServerFileInfo
from common.utils import json_default


class ClientSession:
    id: uuid.UUID

    addr: tuple[str, int]
    encoding: str = "utf-8"

    actions: deque[ActionData]

    stdout: bytearray
    stdin: bytearray

    file_info: ServerFileInfo
    file_io: TextIOWrapper
    is_receiving_file: bool
    file_block_size: int

    log: Logger

    def __init__(self, addr: tuple[str, int], file_block_size: int,  logger: Logger) -> None:
        self.addr = addr

        self.id = uuid.uuid4()
        self.stdin = bytearray()
        self.stdout = bytearray()
        self.actions = deque()
        self.is_receiving_file = False
        self.file_io = None
        self.file_info = None
        self.file_block_size = file_block_size

        self.log = LoggerAdapter(logger, extra={
            'client': addr,
        })

    def parse_block(self) -> ActionData:
        """Parse data block from session bytes input"""
        try:
            split = self.stdin.split(ETB, 1)[0]
            self.log.debug(f"Parsing block from stdin: '{split}'")
            decoded = split.decode(self.encoding)

            data = json.loads(decoded)
            action = ActionData(**data)
            self.actions.appendleft(action)

            self.log.info(f"New queued action: {json.dumps(data, indent=4, default=json_default)}")
        except Exception as exc:
            self.log.warning("Could not parse block into action data, dropping", exc_info=exc)

            self.stdout.extend(str(exc).encode(self.encoding))
            self.stdout.extend(ERROR_B)
            self.stdout.extend(ETB)

        self.stdin = self.stdin[len(split) + 1:]
