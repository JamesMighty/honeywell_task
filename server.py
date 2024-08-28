import argparse
import json
import os
import selectors
import socket
import sys
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from enum import Enum
from io import TextIOWrapper
from logging import (DEBUG, ERROR, INFO, WARNING, FileHandler, Formatter,
                     Logger, LoggerAdapter, StreamHandler)
from pathlib import Path

# End of transmission block
ETB = b"\x17"
# return status
OK_B = b"OK"
# One char does not always work
# can be contained in some file types
CANCEL_B = b"\x18\x18\x18\x18"
CANCELED_B = b"CANCELED"
ERROR_B = b"ERROR"

OK = "OK"


def default_json(o: object):
    return f"<not serializable {o.__qualname__}>"


class ServerLogger(Logger):

    MSG_FORMAT = "[%(asctime)s] [%(name)s] [%(levelname)7s] [%(client)20s] [%(action)10s] | %(message)s"

    def __init__(self, stream_log_level = DEBUG, file_log_level = DEBUG) -> None:
        name = "server"
        super().__init__(name, stream_log_level)

        logFormatter = Formatter(ServerLogger.MSG_FORMAT, defaults={
            "client": "",
            "action": ""
        })

        file_handler = FileHandler(Path(f"./{name}-log.txt"), encoding="utf-8")
        file_handler.setFormatter(logFormatter)
        file_handler.setLevel(file_log_level)

        stream_handler = StreamHandler(sys.stdout)
        stream_handler.setFormatter(logFormatter)
        stream_handler.setLevel(stream_log_level)

        self.addHandler(file_handler)
        self.addHandler(stream_handler)
        self.debug(f"Log '{name}' built.")


class Actions(int, Enum):

    ECHO = 1,
    SET_META = 2,
    START_SEND = 3,
    CLEAR_FILE_INFO = 4,
    SET_FILE_BLOCK_SIZE = 5,


@dataclass
class ActionData:

    action: Actions
    data: object


@dataclass
class FileInfo:
    dest_path: str
    hash: str
    size: str

    size_transmited: int = 0

class ClientSession:
    ID: uuid.UUID

    addr: tuple[str, int]
    encoding: str = "utf-8"

    actions: deque[ActionData]

    outb: bytearray
    inb: bytearray

    file_info: FileInfo
    file_io: TextIOWrapper
    is_receiving_file: bool
    file_block_size: int

    logger: Logger

    def __init__(self, addr: tuple[str, int], file_block_size: int,  logger: Logger) -> None:
        self.addr = addr

        self.ID = uuid.uuid4()
        self.inb = bytearray()
        self.outb = bytearray()
        self.actions = deque()
        self.is_receiving_file = False
        self.file_io = None
        self.file_info = None
        self.file_block_size = file_block_size

        self.logger = LoggerAdapter(logger, extra={
            'client': addr,
        })

    def parse_block(self) -> ActionData:
        """Parse data block from session bytes input"""
        try:
            self.logger.debug(f"Parsing from inb: '{self.inb}'")
            split = self.inb.split(ETB, 1)[0]
            decoded = split.decode(self.encoding)

            data = json.loads(decoded)
            action = ActionData(**data)
            self.actions.appendleft(action)

            self.logger.info(f"New queued action: {json.dumps(data, indent=4, default=default_json)}")
        except Exception as exc:
            self.logger.warning(f"WARN - could not parse block into action data, dropping", exc_info=exc)

            self.outb.extend(str(exc).encode(self.encoding))
            self.outb.extend(ERROR_B)
            self.outb.extend(ETB)

        self.inb = self.inb[len(split) + 1:]


class Server:
    """"File transfer server implementation"""

    def __init__(self,
                 host: str = None,
                 listening_port: int = 4040,
                 bufsize: int = 1024,
                 file_block_size: int = 1024*64-1,
                 root_dir: str = "./",
                 log_level: int = DEBUG):

        # if file_block_size > 65535:
        #     raise ValueError("File block size cannot be bigger than 65535 bytes")

        self.host = host
        self.port = listening_port
        self.buffsize = bufsize
        self.sel = selectors.DefaultSelector()
        self.logger = ServerLogger(log_level, log_level)
        self.file_block_size = file_block_size
        self.root_dir = Path(root_dir)

    def start(self):
        if self.host is None:
            self.host = socket.gethostname()

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind((self.host, self.port))

        self.socket.listen()
        self.socket.setblocking(False)
        self.sel.register(self.socket, selectors.EVENT_READ, data=None)

        self.logger.info(f"Server listening on {self.host}:{self.port}, root dir: {self.root_dir}")

        while True:
            for key in self.sel.get_map().values():
                if key.data is not None:
                    self._handle_action(key.data)

            events = self.sel.select(timeout=None)
            for key, mask in events:
                if key.data is None:
                    self._accept_connection(key.fileobj)
                else:
                    self._handle_connection(key, mask)

    def _handle_action(self, session: ClientSession):
        if len(session.actions) == 0:
            return

        action: ActionData = session.actions.pop()
        logger = LoggerAdapter(self.logger, {
            'client': session.addr,
            'action': Actions(action.action).name
        })

        if action.action == Actions.ECHO:
            session.outb.extend(str(action.data).encode(session.encoding))

            logger.info(f"{action.data}")

        elif action.action == Actions.SET_META:
            try:
                if session.is_receiving_file:
                    raise PermissionError("Cannot set file metadata, currently receiving file")

                session.file_info = FileInfo(**action.data)
                if Path(session.file_info.dest_path).is_absolute():
                    raise ValueError("Destination file path cannot be absolute")

                session.file_info.dest_path = str(self.root_dir/session.file_info.dest_path)

                logger.info(f"Set file info to {json.dumps(asdict(session.file_info), indent=4, default=default_json)}")

                session.outb.extend(OK_B)
            except Exception as err:
                session.outb.extend(str(err).encode(session.encoding))
                logger.warning("Could not set file info for this session", exc_info=err)

        elif action.action == Actions.START_SEND:
            try:
                path = Path(session.file_info.dest_path)

                if path.exists():
                    raise FileExistsError(f"File '{path.name}' already exists")

                os.makedirs(path.parent, exist_ok=True)

                session.file_io = open(path, "wb")
                session.is_receiving_file = True

                session.outb.extend(OK_B)

                logger.info(f"Prepared to receive file")
            except Exception as err:
                session.outb.extend(str(err).encode(session.encoding))
                logger.warning("Could not prepare to receive file", exc_info=err)

        elif action.action == Actions.CLEAR_FILE_INFO:
            if session.is_receiving_file:
                msg = "Cannot clear file info, file is still open"
                session.outb.extend(msg.encode(session.encoding))
                logger.warning(msg)
            else:
                session.file_info = None
                session.outb.extend(OK_B)
                logger.info(OK)

        elif action.action == Actions.SET_FILE_BLOCK_SIZE:
            try:
                session.file_block_size = min(self.file_block_size, int(action.data))
                logger.info(f"File block size set to {session.file_block_size}")
                session.outb.extend(OK_B)
            except Exception as err:
                logger.info(f"File block size could not be set to {session.file_block_size}", exc_info=err)
                session.outb.extend(str(err).encode(session.encoding))

        session.outb.extend(ETB)

    def _accept_connection(self, sock: socket.socket):
        """Handle new client connection"""
        conn, addr = sock.accept()

        conn.setblocking(False)

        session = ClientSession(addr, self.file_block_size, self.logger)
        events = selectors.EVENT_READ | selectors.EVENT_WRITE
        self.sel.register(conn, events, data=session)

        self.logger.info(f"Accepted connection from {addr}")

    def _handle_connection(self, key: selectors.SelectorKey, mask: int):
        """Handle client connection"""
        sock: socket.socket = key.fileobj
        session: ClientSession = key.data

        # This is quite nested, but I didn't want to declare nested func for performance reasons
        if mask & selectors.EVENT_READ:
            try:
                recv_data: bytes
                if session.is_receiving_file:
                    recv_data = sock.recv(session.file_block_size)
                else:
                    recv_data = sock.recv(self.buffsize)

                session.logger.debug(f"Received {len(recv_data)} bytes of data: {recv_data}")
                if recv_data:

                    if session.is_receiving_file:
                        if recv_data.endswith(CANCEL_B):
                            session.file_io.close()
                            session.is_receiving_file = False
                            session.file_io = None

                            session.outb.extend(CANCELED_B)
                            session.outb.extend(ETB)

                            os.remove(session.file_info.dest_path)
                            session.logger.warning(f"File transfer canceled for {session.file_info.dest_path}, file removed")
                            return

                        if session.file_info.size_transmited == 0:
                            session.logger.info(f"Starting to download file {session.file_info.dest_path}")

                        session.file_io.write(recv_data)
                        session.file_info.size_transmited += len(recv_data)

                        session.logger.debug(f"""{session.file_info.size_transmited}/{session.file_info.size} bytes
                                             successfuly received""")

                        if session.file_info.size == session.file_info.size_transmited:

                            session.file_io.close()
                            session.is_receiving_file = False
                            session.file_io = None

                            session.logger.info(f"File {session.file_info.dest_path} successfuly received")

                            session.outb.extend(OK_B)
                            session.outb.extend(ETB)

                    else:
                        session.inb += recv_data
                        session.logger.debug(f"Inb: {session.inb}")
                        while ETB in session.inb:
                            session.parse_block()

                else:
                    self._close_connection(key)

            except WindowsError as err:
                session.logger.error(f"ERROR - connection with {session.addr}", exc_info=err)
                self._close_connection(key)

        if mask & selectors.EVENT_WRITE:
            if session.outb:
                try:
                    self.logger.debug(f"Trying to send data from outb '{session.outb}'")
                    sent = sock.send(session.outb)  # Should be ready to write
                    session.outb = session.outb[sent:]
                except Exception as err:
                    self.logger.error(err)
                    self._close_connection(key)

    def _close_connection(self, key: selectors.SelectorKey):
        sock: socket.socket = key.fileobj
        session: ClientSession = key.data

        self.logger.info(f"Closing connection to {session.addr}")

        if session.file_io:
            session.file_io.close()
            session.logger.warning(f"File {session.file_info.dest_path} was still open, closing ..")

        _ = self.sel.unregister(key.fileobj)

        sock.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
                    prog='server.py',
                    description='File transfer server')
    parser.add_argument("host",
                        help="IP address or hostname")
    parser.add_argument("port",
                        help="Listening port",
                        type=int)
    parser.add_argument("--root-dir",
                        help="Download root dir",
                        required=False,
                        default="./",
                        type=str)
    parser.add_argument("--buffsize",
                        required=False,
                        default=1024,
                        help="Buffer size for basic communication",
                        type=int)
    parser.add_argument("--file-block-size",
                        required=False,
                        default=65535,
                        help="File block size in bytes (65535 max)",
                        type=int)

    choices = ["DEBUG", "INFO", "WARNING", "ERROR"]
    parser.add_argument("--log-level",
                        required=False,
                        default=INFO,
                        choices=[DEBUG, INFO, WARNING, ERROR],
                        help=f"Logging level, choises resp.: {", ".join(choices)}",
                        type=int)

    args = parser.parse_args()
    server = Server(args.host, args.port, args.buffsize, args.file_block_size, args.root_dir, args.log_level)
    server.start()
