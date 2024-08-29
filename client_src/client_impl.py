import errno
import json
import socket
from collections import deque
from dataclasses import asdict
from datetime import datetime
from logging import DEBUG, Logger, LoggerAdapter
from pathlib import Path
from typing import TYPE_CHECKING

from client_src.data import ResponseMsg, TransferProgress
from common.const import CANCEL_B, ETB, OK, Actions
from common.data import ActionData, FileInfo
from common.utils import json_default

if TYPE_CHECKING:
    from client_src.gui.main_window import ClientMainWindow


class ClientImpl:
    """Defines file transfer client logic"""

    stdin: bytearray
    responses: deque
    sock: socket.socket
    is_connected: bool
    cancel_transfer: bool
    cancel_all: bool

    def __init__(self, mwh: 'ClientMainWindow', logger: Logger, buffersize: int = 1024, file_block_size: int = 1024, encoding: str = "utf-8") -> None:
        self.sock = None
        self.stdin = bytearray()
        self.responses = deque()
        self.is_connected = False
        self.cancel_transfer = False
        self.cancel_all = False

        self.buffer_size = buffersize
        self.encoding = encoding
        self.mwh = mwh
        self.file_block_size = file_block_size

        self.logger = LoggerAdapter(logger)

    def connect(self, host: str, port: int):
        """Connect to specific host, if connection already established, disconnect first"""
        if self.sock:
            self.close()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))

        self.is_connected = True
        self.logger.info(f"Connected to {host}:{port}")

    def _sent_action(self, action: ActionData, msg: ResponseMsg = None) -> bool:
        """Sends action data to server side, waits for response and check status"""
        self.logger.info(f"Sending action {action.action.name}")
        action_send_ok = False
        try:
            data_raw = json.dumps(asdict(action), default=json_default)
            self.sock.send(data_raw.encode(self.encoding))
            self.sock.send(ETB)
            action_send_ok = True
        except socket.error as err:
            if msg:
                msg.client_send = err
            return False
        resp_ok = self._read_responses()
        return action_send_ok and resp_ok

    def _read_responses(self, msg: ResponseMsg = None) -> bool:
        """waits for response from server and parses them to respose queue"""
        try:
            self.sock.setblocking(True)
            new_data = self.sock.recv(self.buffer_size)
        except Exception as err:
            if msg:
                msg.client_read = err
            return False

        self.sock.setblocking(False)
        while new_data:
            self.stdin.extend(new_data)
            try:
                new_data = self.sock.recv(self.buffer_size)
            except socket.error as err:
                if err.errno == errno.EAGAIN or err.errno == errno.EWOULDBLOCK:
                    # This is ok - no blocking - so no msg to receive
                    break
                else:
                    # This is bad
                    if msg:
                        msg.client_read = err
                    return False

        self.sock.setblocking(True)

        while ETB in self.stdin:
            split = self.stdin.split(ETB, 1)[0]
            self.stdin = self.stdin[len(split) + 1:]
            resp = split.decode(self.encoding)
            self.responses.appendleft(resp)
            self.logger.info(f"Server response: {resp}")

        self.logger.debug(f"Responses: {self.responses}")
        return True

    def set_file_block_size(self, msg: ResponseMsg = None) -> bool:
        if not self.is_connected:
            if msg:
                msg.client_send = ConnectionError("Client not connected")
            return False

        action_ok = self._sent_action(ActionData(Actions.SET_FILE_BLOCK_SIZE, self.file_block_size))
        if not action_ok:
            return False
        resp = self.responses.pop()
        if msg:
            msg.server_response = resp
        return resp == OK

    def test_connection(self, msg: ResponseMsg = None) -> bool:
        if not self.is_connected:
            if msg:
                msg.client_send = ConnectionError("Client not connected")
            return False

        echo_msg = "Hello world"
        self._sent_action(ActionData(Actions.ECHO, echo_msg), msg)
        resp = self.responses.pop()
        if msg:
            msg.server_response = resp
        return resp == echo_msg

    def set_file_info(self, fileinf: FileInfo, msg: ResponseMsg = None) -> bool:
        if not self.is_connected:
            if msg:
                msg.client_send = ConnectionError("Client not connected")
            return False

        self._sent_action(ActionData(Actions.SET_META, fileinf), msg)
        resp = self.responses.pop()
        if msg:
            msg.server_response = resp
        return resp == OK

    def send_file(self, src_filepath: str, size: int, msg: ResponseMsg = None, progress: TransferProgress = None) -> bool:
        if not self.is_connected:
            if msg:
                msg.client_send = ConnectionError("Client not connected")
            return False

        self._sent_action(ActionData(Actions.START_SEND, None), msg)
        start_file_resp = self.responses.pop()
        if start_file_resp != OK:
            if msg:
                msg.server_response = start_file_resp
            return False

        size_sent = 0

        # Update progress
        if progress:
            progress.start_time = datetime.now()
            progress.current_file_src = Path(src_filepath).name
            progress.file_size = size
            progress.size_sent = size_sent

        # Update window
        if self.mwh:
            self.mwh.print_status(str(progress), log_level=DEBUG)
            self.mwh.progressbar.configure(maximum=size, value=0)

        try:
            file_io = open(src_filepath, 'rb')
        except OSError as err:
            if msg:
                msg.client_send = err
            self.logger.error(f"Could not open file {src_filepath}", exc_info=err)
            return False

        while size_sent != size:
            # Check if cancel flag is up
            if self.cancel_transfer or self.cancel_all:
                self.sock.send(CANCEL_B)
                self.cancel_transfer = False
                break
            # Try send data
            try:
                count = self.file_block_size
                if size - size_sent < count:
                    count = size - size_sent

                size_send_ = self.sock.sendfile(file_io, size_sent, count)
                size_sent += size_send_

                if progress:
                    progress.size_sent = size_sent

                if self.mwh:
                    self.mwh.print_status(str(progress), log_level=DEBUG)
                    self.mwh.progressbar.step(size_send_)

            except Exception as err:
                self.logger.error("Exception when sending file", exc_info=err)
                if msg:
                    msg.client_send = err
                return False

            if self.mwh:
                self.mwh.top.update()

        file_io.close()

        if progress:
            progress.current_file_count += 1

        if not self._read_responses(msg):
            return False

        resp = self.responses.pop()
        if msg:
            msg.server_response = resp
        return resp == OK

    def clear_file_info(self, msg: ResponseMsg = None) -> bool:
        if not self.is_connected:
            if msg:
                msg.client_send = ConnectionError("Client not connected")
            return False

        self._sent_action(ActionData(Actions.CLEAR_FILE_INFO, None), msg)
        resp = self.responses.pop()
        if msg:
            msg.server_response = resp
        return resp == OK

    def close(self, msg: ResponseMsg = None):
        if not self.is_connected:
            if msg:
                msg.client_send = ConnectionError("Client not connected")
            return False

        self.sock.close()
        self.sock = None
        self.is_connected = False

        self.logger.debug("Connection closed")
