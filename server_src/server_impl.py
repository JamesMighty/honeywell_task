import json
import os
import selectors
import socket
from dataclasses import asdict
from logging import DEBUG, LoggerAdapter
from pathlib import Path

from common.const import CANCEL_B, CANCELED_B, ETB, OK, OK_B, Actions
from common.data import ActionData, ServerFileInfo
from common.utils import json_default
from server_src.data import ClientSession
from server_src.logger import ServerLogger


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
        #    raise ValueError("File block size cannot be bigger than 65535 bytes")

        self.host = host
        self.port = listening_port
        self.buffsize = bufsize
        self.sel = selectors.DefaultSelector()
        self.logger = ServerLogger(log_level, log_level)
        self.max_file_block_size = file_block_size
        self.root_dir = Path(root_dir)
        self.socket: socket.socket

        self.logger.info("Server created, configuration:\n " \
                         f"{self.host=}\n {self.port=}\n {self.root_dir=}\n " \
                         f"{self.buffsize=}\n {self.max_file_block_size=}")

    def start(self):
        if self.host is None:
            self.host = socket.gethostname()

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind((self.host, self.port))

        self.socket.listen()
        self.socket.setblocking(False)
        self.sel.register(self.socket, selectors.EVENT_READ, data=None)

        self.logger.info(f"Server listening on {self.host}:{self.port}")

        while True:
            for key in self.sel.get_map().values():
                if key.data is not None:
                    try:
                        self._handle_action(key.data)
                    except Exception as err:
                        self.logger.error("Could not handle action", exc_info=err)
                        # TODO: what to do? server should not stop but session should be handeled some how
                        raise err

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
        log = LoggerAdapter(self.logger, {
            'client': session.addr,
            'action': Actions(action.action).name
        })

        if action.action == Actions.ECHO:
            session.stdout.extend(str(action.data).encode(session.encoding))

            log.info(f"{action.data}")

        elif action.action == Actions.SET_META:
            try:
                if session.is_receiving_file:
                    raise PermissionError("Cannot set file metadata, currently receiving file")

                session.file_info = ServerFileInfo(**action.data)
                if Path(session.file_info.dest_path).is_absolute():
                    raise ValueError("Destination file path cannot be absolute")

                session.file_info.dest_path = str(self.root_dir/session.file_info.dest_path)

                log.info(f"Set file info to {json.dumps(asdict(session.file_info), indent=4, default=json_default)}")

                session.stdout.extend(OK_B)
            except Exception as err:
                session.stdout.extend(str(err).encode(session.encoding))
                log.warning("Could not set file info for this session", exc_info=err)

        elif action.action == Actions.START_SEND:
            try:
                if session.is_receiving_file:
                    raise PermissionError("Cannot start file transmission, currently receiving file")

                path = Path(session.file_info.dest_path)

                if path.exists():
                    raise FileExistsError(f"File '{path.name}' already exists")

                os.makedirs(path.parent, exist_ok=True)

                session.file_io = open(path, "wb")
                session.is_receiving_file = True

                session.stdout.extend(OK_B)

                log.info("Prepared to receive file")
            except Exception as err:
                session.stdout.extend(str(err).encode(session.encoding))
                log.warning("Could not prepare to receive file", exc_info=err)

        elif action.action == Actions.CLEAR_FILE_INFO:
            if session.is_receiving_file:
                msg = "Cannot clear file info, file is still open"
                session.stdout.extend(msg.encode(session.encoding))
                log.warning(msg)
            else:
                session.file_info = None
                session.stdout.extend(OK_B)
                log.info(OK)

        elif action.action == Actions.SET_FILE_BLOCK_SIZE:
            try:
                session.file_block_size = min(self.max_file_block_size, int(action.data))
                log.info(f"File block size set to {session.file_block_size}")
                session.stdout.extend(OK_B)
            except Exception as err:
                log.info(f"File block size could not be set to {session.file_block_size}", exc_info=err)
                session.stdout.extend(str(err).encode(session.encoding))

        session.stdout.extend(ETB)

    def _accept_connection(self, sock: socket.socket):
        """Handle new client connection"""
        conn, addr = sock.accept()

        conn.setblocking(False)

        session = ClientSession(addr, self.max_file_block_size, self.logger)
        events = selectors.EVENT_READ | selectors.EVENT_WRITE
        self.sel.register(conn, events, data=session)

        self.logger.info(f"Accepted connection from {addr}")

    def _handle_file_cancel(self, session: ClientSession):
        session.file_io.close()
        session.is_receiving_file = False
        session.file_io = None

        session.stdout.extend(CANCELED_B)
        session.stdout.extend(ETB)

        os.remove(session.file_info.dest_path)
        session.log.warning(f"File transfer canceled for {session.file_info.dest_path}, file removed")

    def _handle_file_done(self, session: ClientSession):
        session.file_io.close()
        session.is_receiving_file = False
        session.file_io = None

        session.log.info(f"File {session.file_info.dest_path} successfuly received")

        session.stdout.extend(OK_B)
        session.stdout.extend(ETB)

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

                if not recv_data:
                    self._close_connection(key)
                    return

                session.log.debug(f"Received {len(recv_data)} bytes of data: {recv_data}")

                if session.is_receiving_file:
                    if recv_data.endswith(CANCEL_B):
                        self._handle_file_cancel(session)
                        return

                    if session.file_info.size_transmited == 0:
                        session.log.info(f"Starting to download file {session.file_info.dest_path}")

                    session.file_io.write(recv_data)
                    session.file_info.size_transmited += len(recv_data)

                    if session.file_info.size == session.file_info.size_transmited:
                        self._handle_file_done(session)

                else:
                    session.stdin += recv_data
                    session.log.debug(f"Added data to stdin: '{recv_data}'")
                    while ETB in session.stdin:
                        session.parse_block()

            except WindowsError as err:
                session.log.error("EVENT_READ", exc_info=err)
                self._close_connection(key)

        if mask & selectors.EVENT_WRITE:
            if session.stdout:
                try:
                    session.log.debug(f"Trying to send data from outb '{session.stdout}'")
                    sent = sock.send(session.stdout)
                    session.stdout = session.stdout[sent:]
                except Exception as err:
                    session.log.error("EVENT_WRITE", exc_info=err)
                    self._close_connection(key)

    def _close_connection(self, key: selectors.SelectorKey):
        sock: socket.socket = key.fileobj
        session: ClientSession = key.data

        session.log.info("Closing connection")

        if session.file_io:
            session.file_io.close()
            session.log.warning(f"File {session.file_info.dest_path} was still open, closing ..")

        _ = self.sel.unregister(key.fileobj)

        sock.close()