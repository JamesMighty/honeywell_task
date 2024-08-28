import errno
import json
import os
import os.path
import platform
import socket
import sys
from datetime import datetime, timedelta
import tkinter as tk
import tkinter.ttk as ttk
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from logging import (DEBUG, INFO, FileHandler, Formatter, Logger,
                     LoggerAdapter, StreamHandler)
from pathlib import Path
from tkinter import IntVar, StringVar, simpledialog
from tkinter.filedialog import askopenfilename

HOST = "127.0.0.1"  # The server's hostname or IP address
PORT = 4040  # The port used by the server

ETB = b"\x17"
OKB = b"OK"
CANCEL_B = b"\x18\x18\x18\x18"
CANCELED = "CANCELED"
OK = "OK"

CONFIG_FILENAME = "client-config.json"


def default_json(o: object):
    return f"<not serializable {o.__qualname__}>"


class Actions(int, Enum):
    """Defines server action types"""
    ECHO = 1,
    SET_META = 2,
    START_SEND = 3,
    CLEAR_FILE_INFO = 4,
    SET_FILE_BLOCK_SIZE = 5


@dataclass
class ActionData:
    """Defines action data packet sent to server"""

    action: Actions
    data: object


@dataclass
class FileInfo:
    """"Defines file metadata, which is to be sent"""

    dest_path: str
    hash: str
    size: str


@dataclass
class Config:
    """Defines client configuration dataclass"""
    client_buffsize: int = 1024
    client_file_block_size: int = 1024*64-1
    log_level: int = INFO
    files: list[str] = field(default_factory=list)
    servers: list[str] = field(default_factory=list)

    @staticmethod
    def _create_new_file() -> 'Config':
        config_path = Path(f"./{CONFIG_FILENAME}")
        defconf = Config()
        print(defconf)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(asdict(defconf), f, indent=4)
        return defconf

    @staticmethod
    def load() -> 'Config':
        if not Config.get_path().exists():
            return Config._create_new_file()

        conf_raw: dict
        with open(Config.get_path(), "r", encoding="utf-8") as f:
            conf_raw = json.load(f)

        try:
            inst = Config(**conf_raw)
        except Exception as err:
            print(f"Could not load configuration, creating new: {err}")
            os.rename(Config.get_path(), Path(f"{Config.get_path()}.old"))
            return Config._create_new_file()

        return inst

    def save(self):
        """"Save config"""
        with open(Config.get_path(), 'w', encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=4)

    @staticmethod
    def get_path() -> Path:
        """Get default config file path"""
        return Path(f"./{CONFIG_FILENAME}")


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

    def get_progress_string(self):
        speed_str = "N/A B/s"
        time_needed_str = "N/A s"
        time_ = (datetime.now()-self.start_time)

        if time_.seconds > 2:
            speed = self.size_sent/time_.seconds
            speed_str = TransferProgress.human_readable_size(speed, 0)
            time_needed = timedelta(seconds=(self.file_size - self.size_sent)/speed)
            time_needed_str = str(time_needed).split('.', 2)[0]

        return f"{self.current_file_count}/{self.file_count} files " \
         f"- {self.current_file_src} [{TransferProgress.human_readable_size(self.size_sent)}/" \
         f"{TransferProgress.human_readable_size(self.file_size)}, {str(time_).split('.', 2)[0]}/{time_needed_str}, " \
         f"{speed_str}/s]"


class ResponseMsg:
    """Defines trace information when communicating with server"""
    client_send: str
    client_read: str
    server_response: str


class ClientLogger(Logger):
    """"Defines custom client logger"""

    MSG_FORMAT = "[%(asctime)s] [%(name)s] [%(levelname)7s] [%(window)12s] | %(message)s"

    def __init__(self, stream_log_level: int = DEBUG, file_log_level: int = DEBUG) -> None:
        name = "client"
        super().__init__(name, stream_log_level)

        logFormatter = Formatter(ClientLogger.MSG_FORMAT, defaults={
            "window": "",
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


class Client:
    """Defines file transfer client logic"""

    inb: bytearray
    responses: deque
    sock: socket.socket
    is_connected: bool
    cancel_transfer: bool

    def __init__(self, mwh: 'MainWindow', logger: Logger, buffersize: int = 1024, file_block_size: int = 1024, encoding: str = "utf-8") -> None:
        self.buffer_size = buffersize
        self.encoding = encoding
        self.mwh = mwh
        self.sock = None
        self.inb = bytearray()
        self.responses = deque()
        self.file_block_size = file_block_size
        self.is_connected = False
        self.cancel_transfer = False
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
            data_raw = json.dumps(asdict(action), default=default_json)
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
            s = self.sock.recv(self.buffer_size)
        except Exception as err:
            if msg:
                msg.client_read = err
            return False

        self.sock.setblocking(False)
        while s:
            self.inb.extend(s)
            try:
                s = self.sock.recv(self.buffer_size)
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

        while ETB in self.inb:
            split = self.inb.split(ETB, 1)[0]
            self.inb = self.inb[len(split) + 1:]
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

    def send_file(self, src_filepath: str, size: int, msg: ResponseMsg = None, prog: TransferProgress = None) -> bool:
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

        if prog:
            prog.start_time = datetime.now()
            prog.current_file_src = Path(src_filepath).name
            prog.file_size = size
            prog.size_sent = size_sent
            self.mwh.print_status(prog.get_progress_string(), log_level=DEBUG)

        self.mwh.progressbar.configure(maximum=size, value=0)

        try:
            file_io = open(src_filepath, 'rb')
        except OSError as err:
            if msg:
                msg.client_send = err
            self.logger.error(f"Could not open file {src_filepath}", exc_info=err)
            return False

        while size_sent != size:
            if self.cancel_transfer:
                self.sock.send(CANCEL_B)
                self.cancel_transfer = False

                break
            try:
                count = self.file_block_size
                if size - size_sent < count:
                    count = size - size_sent

                size_send_ = self.sock.sendfile(file_io, size_sent, count=count)
                size_sent += size_send_

                if prog:
                    prog.size_sent = size_sent
                    self.mwh.print_status(prog.get_progress_string(), log_level=DEBUG)

                self.mwh.progressbar.step(size_send_)
            except Exception as err:
                self.logger.error("Exception when sending file", exc_info=err)
                if msg:
                    msg.client_send = err
                return False

            root.update()

        file_io.close()
        if prog:
            prog.current_file_count += 1

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

        self.logger.debug(f"Connection closed")


# GUI module generated by PAGE version 8.0
#  in conjunction with Tcl version 8.6
#    Aug 24, 2024 01:46:54 PM CEST  platform: Windows NT

_fgcolor = 'SystemWindowText'


FILES_SEP = " -> "
SERVER_SEP = ":"

GREEN = "green"
RED = "red"
ORANGE = "orange"


WIDGET_DEFAULTS = {
    "disabledforeground": "#b4b4b4",
    }

LABEL_DEFAULTS = {
    "anchor": "nw",
    "compound": "left",
    "justify": "left",
    **WIDGET_DEFAULTS
}

LISTBOX_DEFAULTS = {
    "background": "white",
    "cursor": "xterm",
    "disabledforeground": "#b4b4b4",
    "font": "TkFixedFont",
    "highlightcolor": "#d9d9d9",
    "selectbackground": "#d9d9d9",
    "selectforeground": "black",
    "exportselection": False
}


class MainWindow:

    client: Client
    logger: Logger
    top: tk.Tk
    config: Config

    def __init__(self, top: tk.Tk = None):

        '''This class configures and populates the toplevel window.
           top is the toplevel containing window.'''
        top_width = 900
        top_height = 460
        top.geometry(f"{top_width}x{top_height}")
        top.resizable(0,  0)
        top.title("Files transfer client")
        top.configure(highlightcolor="SystemWindowText")
        self.top = top

        self.config = Config.load()
        self._logger = ClientLogger(self.config.log_level, self.config.log_level)
        self.client = Client(self._logger, self.config.client_buffsize, self.config.client_file_block_size)
        self.logger = LoggerAdapter(self._logger, extra={
            "window": "Main Window"
        })

        self.menubar = tk.Menu(top,
                               font="TkMenuFont",
                               bg='SystemButtonFace',
                               fg=_fgcolor,)
        self.settingsmenu = tk.Menu(self.menubar, tearoff=0)
        self.settingsmenu.add_command(label="Save", command=self._save_settings)
        self.settingsmenu.add_command(label="Load", command=self._load_settings)
        self.menubar.add_cascade(label="Settings", menu=self.settingsmenu)
        top.configure(menu=self.menubar)

        # --- FILES ---
        self.files_label = tk.Label(self.top,
                                   text='''Files''',
                                   **LABEL_DEFAULTS)

        self.files_scrolled_listbox = ScrolledListBox(self.top, selectmode=tk.MULTIPLE, **LISTBOX_DEFAULTS)
        self.files_scrolled_listbox.bind('<<ListboxSelect>>', lambda _: self._update_states())

        self.add_file_button = tk.Button(self.top,
                                       command=self._add_file_button_click,
                                       text='''+''',
                                       **WIDGET_DEFAULTS)

        self.remove_file_button = tk.Button(self.top,
                                          command=self._remove_file_selection_click,
                                          text='''-''',
                                          **WIDGET_DEFAULTS)

        self.clear_files_button = tk.Button(self.top,
                                          command=self._clear_files_click,
                                          text='''Clear''',
                                          **WIDGET_DEFAULTS)

        # --- SERVERS ---
        self.servers_label = tk.Label(self.top, text='''Servers''', **LABEL_DEFAULTS)

        self.servers_scrolled_listbox = ScrolledListBox(self.top, **LISTBOX_DEFAULTS)
        self.servers_scrolled_listbox.bind('<<ListboxSelect>>', lambda _: self._update_states())

        self.add_server_button = tk.Button(self.top,
                                           command=self._add_server_button_click,
                                           text='''+''',
                                           **WIDGET_DEFAULTS)

        self.remove_server_button = tk.Button(self.top,
                                              command=self._remove_server_selection_click,
                                              text='''-''',
                                              **WIDGET_DEFAULTS)

        self.clear_server_button = tk.Button(self.top,
                                             command=self._clear_servers_click,
                                             text='''Clear''',
                                             **WIDGET_DEFAULTS)

        # --- PROGRESS ---
        self.progressbar = ttk.Progressbar(self.top)
        self.progressbar.configure(length="560")


        # --- STATUS ---
        self.status_label = tk.Label(self.top, wraplength=780, **LABEL_DEFAULTS)

        self.status_label_ = tk.Label(self.top, text='''Status:''', **LABEL_DEFAULTS)

        # --- ACTIONS ---
        self.send_select_button = tk.Button(self.top,
                                            command=self._send_selection_click,
                                            text='''Send selected file''',
                                            **WIDGET_DEFAULTS)

        self.cancel_button = tk.Button(self.top,
                                       state=tk.DISABLED,
                                       command=self._cancel_click,
                                       text='''Cancel''',
                                       **WIDGET_DEFAULTS)

        self.send_all_files_button = tk.Button(self.top,
                                               text='''Send all files''',
                                               command=self._send_all_click,
                                               **WIDGET_DEFAULTS)

        self.files_label.place(x=20, y=20, height=20, width=500)
        self.servers_label.place(x=658, y=20,  height=20, width=222)

        self.files_scrolled_listbox.place(x=20, y=40,  height=260, width=566)
        self.servers_scrolled_listbox.place(x=658, y=40,  height=260, width=160)

        self.add_file_button.place(x=596, y=40, height=26, width=26)
        self.remove_file_button.place(x=596, y=76, height=26, width=26)
        self.clear_files_button.place(x=596, y=112, height=26, width=52)

        self.add_server_button.place(x=828, y=40, height=26, width=26)
        self.remove_server_button.place(x=828, y=76, height=26, width=26)
        self.clear_server_button.place(x=828, y=112, height=26, width=52)

        self.progressbar.place(x=20, y=320, width=860, height=20)

        self.status_label_.place(x=20, y=350, height=21, width=60)
        self.status_label.place(x=90, y=350, width=790, height=60)

        self.cancel_button.place(x=20, y=414, height=26, width=50)
        self.send_all_files_button.place(x=634, y=414, height=26, width=118)
        self.send_select_button.place(x=762, y=414, height=26, width=118)

        self._update_states()
        self._load_settings()

    def _update_states(self):
        """Update button states (disabled/normal)"""
        is_file_selected = False
        is_server_selected = False

        files = self.files_scrolled_listbox.get(0, tk.END)
        self.remove_file_button.configure(state=tk.DISABLED)
        if len(files) == 0:
            self.clear_files_button.configure(state=tk.DISABLED)
        else:
            self.clear_files_button.configure(state=tk.NORMAL)
            sel = self.files_scrolled_listbox.curselection()
            if len(sel) > 0:
                self.remove_file_button.configure(state=tk.NORMAL)
                is_file_selected = True

        servers = self.servers_scrolled_listbox.get(0, tk.END)
        self.remove_server_button.configure(state=tk.DISABLED)
        if len(servers) == 0:
            self.clear_server_button.configure(state=tk.DISABLED)
        else:
            self.clear_server_button.configure(state=tk.NORMAL)
            sel = self.servers_scrolled_listbox.curselection()
            if len(sel) > 0:
                self.remove_server_button.configure(state=tk.NORMAL)
                is_server_selected = True

        if is_server_selected:
            if is_file_selected:
                self.send_select_button.configure(state=tk.NORMAL)

            if len(files) > 0:
                self.send_all_files_button.configure(state=tk.NORMAL)
        else:
            self.send_select_button.configure(state=tk.DISABLED)
            self.send_all_files_button.configure(state=tk.DISABLED)

    def _add_file_button_click(self):
        """On button click event - Try to add file to send"""

        selected_filepath = askopenfilename()

        if selected_filepath is None:
            self.print_status("No selected file")
            return

        dest_filepath = simpledialog.askstring("", "Relative destination (optional)")

        if dest_filepath is not None and Path(dest_filepath).is_absolute():
            self.print_status("Path cannot be absolute")
            return

        if dest_filepath is None:
            dest_filepath = Path(selected_filepath).name
        elif Path(dest_filepath).is_dir() or dest_filepath.endswith(('/', '\\')):
            dest_filepath = Path(dest_filepath)/Path(selected_filepath).name

        # Check with server if filepath exists, if yes ask if u wish to continue

        self.files_scrolled_listbox.insert(0, f"{selected_filepath}{FILES_SEP}{dest_filepath}")
        self._update_states()

    def _add_server_button_click(self):
        top2 = tk.Toplevel(self.top)

        data = {}

        AddServerDialog(self._logger, top2, data)
        self.top.wait_window(top2)

        if data.get("host", None) is None or data.get("port", None) is None:
            self.print_status("Unable to parse new server host config")
            return

        host = str(data.get("host"))
        port = int(data.get("port"))

        self.servers_scrolled_listbox.insert(0, f"{host}:{port}")

    def print_status(self, msg: str, color: str = "black", action_msg: ResponseMsg = None, log_level: int = INFO):
        """Print defines message to status label"""

        full_msg = msg
        if action_msg:
            if hasattr(action_msg, "server_response"):
                full_msg += f", server response: {action_msg.server_response}"
            if hasattr(action_msg, "client_send"):
                full_msg += f", client send: {action_msg.client_send}"
            if hasattr(action_msg, "client_read"):
                full_msg += f", client read: {action_msg.client_read}"

        self.status_label.configure(text=full_msg, fg=color)
        self.logger.log(log_level, full_msg)

    def _remove_file_selection_click(self):
        for index in self.files_scrolled_listbox.curselection():
            self.files_scrolled_listbox.delete(index)
            self.files_scrolled_listbox.selection_clear(index)
        self._update_states()

    def _remove_server_selection_click(self):
        for index in self.servers_scrolled_listbox.curselection():
            self.servers_scrolled_listbox.delete(index)
            self.servers_scrolled_listbox.selection_clear(index)
        self._update_states()

    def _clear_files_click(self):
        self.files_scrolled_listbox.delete(0, tk.END)
        self._update_states()

    def _clear_servers_click(self):
        self.servers_scrolled_listbox.delete(0, tk.END)
        self._update_states()

    def _send_selection_click(self):
        sel = self.files_scrolled_listbox.curselection()
        fileitems = []
        for i in sel:
            fileitems.append((i, self.files_scrolled_listbox.get(i)))
        self._send_files(fileitems)

    def _send_all_click(self):
        fileitems = list(enumerate(self.files_scrolled_listbox.get(0, tk.END)))
        self._send_files(fileitems)

    def _cancel_click(self):
        self.client.cancel_transfer = True
        self.print_status(f"Canceling ...")

    def _save_settings(self):
        try:
            self.config.files = self.files_scrolled_listbox.get(0, tk.END)
            self.config.servers = self.servers_scrolled_listbox.get(0, tk.END)
            self.config.save()
            self.print_status(f"Config saved to {Config.get_path()}", GREEN)
        except Exception as err:
            self.print_status(f"Config could not be saved: {err}", RED)

    def _send_files(self, fileitems: list[tuple[int, str]]):
        self.send_all_files_button.configure(state=tk.DISABLED)
        self.send_select_button.configure(state=tk.DISABLED)

        server = self.servers_scrolled_listbox.get(self.servers_scrolled_listbox.curselection())
        host, port = str(server).split(SERVER_SEP)
        port = int(port)

        progress = TransferProgress(None, 0, 0, datetime.now(), 0,  len(fileitems))

        try:
            self.client.connect(host, port)
            self.print_status(f"Connected to server {server}")
            msg = ResponseMsg()
            if self.client.set_file_block_size(msg):
                self.print_status(f"Set file block size to: {self.client.file_block_size}")
            else:
                self.print_status(f"Could not set block size to: {self.client.file_block_size} bytes", action_msg=msg)
        except Exception as err:
            self.print_status(f"Could not connect to {server} - {err}", RED)
            return

        to_rm = []
        for i, fileitem in fileitems:
            self.mwh.cancel_button.configure(state=tk.NORMAL)

            src, dest = fileitem.split(FILES_SEP)
            src = Path(src)

            file_stats = os.stat(src)
            file_inf = FileInfo(dest, None, file_stats.st_size)

            action_msg = ResponseMsg()
            if self.client.set_file_info(file_inf, action_msg):
                self.print_status("Send file info", GREEN, action_msg)
            else:
                self.print_status("Error when sending file info", RED, action_msg)
                continue


            action_msg = ResponseMsg()
            if self.client.send_file(src, file_inf.size, action_msg, progress):
                self.print_status(f"File {src} sent successfully", GREEN, action_msg)
                to_rm.append(i)
            else:
                self.print_status(f"File {src} could not be send", RED, action_msg)
                if action_msg and hasattr(action_msg, "server_response"):
                    if action_msg.server_response == CANCELED:
                        self.print_status(f"Sending {src} canceled", ORANGE, action_msg=action_msg)
                self.mwh.progressbar.configure(value=0)

            self.mwh.cancel_button.configure(state=tk.DISABLED)

        to_rm.reverse()

        for i in to_rm:
            self.files_scrolled_listbox.delete(i)
            self.files_scrolled_listbox.selection_clear(i)

        self._update_states()

    def _load_settings(self):
        try:
            self.config.load()
            self._clear_files_click()
            self._clear_servers_click()
            self.files_scrolled_listbox.insert(0, *self.config.files)
            self.servers_scrolled_listbox.insert(0, *self.config.servers)
            self.client.buffer_size = self.config.client_buffsize
            self.client.file_block_size = self.config.client_file_block_size
            self._update_states()
            self.print_status(f"Config loaded from {Config.get_path()}", GREEN)
        except Exception as err:
            self.print_status(f"Config could not be loaded from {Config.get_path()}: {err}", RED)


class AddServerDialog:
    """"Defines dialog window for adding new server connection."""

    def __init__(self, logger: Logger, top: tk.Tk = None, data: object = None):

        top.geometry("380x180")
        top.resizable(0,  0)
        top.title("Add new server ")
        top.configure(highlightcolor="SystemWindowText")

        self.data = data
        self.top = top
        self.host = StringVar()
        self.port = IntVar()
        self._logger = logger
        self.logger = LoggerAdapter(logger, extra={
            "window": "Add Server Window"
            })

        self.host_entry = tk.Entry(self.top, textvariable=self.host, **WIDGET_DEFAULTS)
        self.host_entry.place(x=143, y=21, height=20, width=204)

        self.host_label = tk.Label(self.top, text='''Hostname or IP:''', **LABEL_DEFAULTS)
        self.host_label.place(x=21, y=21, height=15, width=103)

        self.port_label = tk.Label(self.top, text='''Port:''', **LABEL_DEFAULTS)
        self.port_label.place(x=21, y=52, height=15, width=85)

        self.port_entry = tk.Entry(self.top, textvariable=self.port, **WIDGET_DEFAULTS)
        self.port_entry.place(x=143, y=52, height=20, width=204)

        self.status_label_ = tk.Label(self.top, text='''Status:''', wraplength=116, **LABEL_DEFAULTS)
        self.status_label_.place(x=21, y=83, height=42, width=116)

        self.status_label = tk.Label(self.top, wraplength=205, **LABEL_DEFAULTS)
        self.status_label.place(x=143, y=83, height=42, width=209)

        self.test_button = tk.Button(self.top,
                                    command=self._test_button_click,
                                    text='''Test''',
                                    **WIDGET_DEFAULTS)
        self.test_button.place(x=240, y=135, height=26, width=47)

        self.add_button = tk.Button(self.top, state=tk.DISABLED,
                                   command=self._add_button_click,
                                   text='''Add''',
                                   **WIDGET_DEFAULTS)
        self.add_button.place(x=300, y=135, height=26, width=47)

        self.host.trace_add("write", lambda _, _b, _c: self.add_button.configure(state=tk.DISABLED))
        self.port.trace_add("write", lambda _, _b, _c: self.add_button.configure(state=tk.DISABLED))

    def _test_button_click(self):
        try:
            # Check sanity
            try:
                ip4 = socket.gethostbyname(self.host.get())
            except:
                raise ValueError("Host must be valid IP or hostname")

            port = self.port.get()
            if port < 0 or port > 65535:
                raise ValueError("Port number must be between 0 and 65535")

            self.add_button.configure(state=tk.NORMAL)
            self.top.update_idletasks()

            # test
            cli = Client(self._logger)
            cli.connect(ip4, port)
            if cli.test_connection():
                msg = "Remote server test OK"
                self.logger.info(msg)
                self.status_label.configure(text=msg, fg=GREEN)
            else:
                msg = "Remote server test ERROR"
                self.logger.info(msg)
                self.status_label.configure(text=msg, fg=RED)

        except Exception as err:
            self.logger.warning("Check error", exc_info=err)
            self.status_label.configure(text=str(err), fg=RED)

    def _add_button_click(self):
        self.data['host'] = self.host.get()
        self.data['port'] = self.port.get()
        self.top.destroy()


# The following code is added to facilitate the Scrolled widgets you specified.
class AutoScroll(object):
    '''Configure the scrollbars for a widget.'''
    def __init__(self, master):
        #  Rozen. Added the try-except clauses so that this class
        #  could be used for scrolled entry widget for which vertical
        #  scrolling is not supported. 5/7/14.
        try:
            vsb = ttk.Scrollbar(master, orient='vertical', command=self.yview)
        except:
            pass
        hsb = ttk.Scrollbar(master, orient='horizontal', command=self.xview)
        try:
            self.configure(yscrollcommand=self._autoscroll(vsb))
        except:
            pass
        self.configure(xscrollcommand=self._autoscroll(hsb))
        self.grid(column=0, row=0, sticky='nsew')
        try:
            vsb.grid(column=1, row=0, sticky='ns')
        except:
            pass
        hsb.grid(column=0, row=1, sticky='ew')
        master.grid_columnconfigure(0, weight=1)
        master.grid_rowconfigure(0, weight=1)
        # Copy geometry methods of master  (taken from ScrolledText.py)
        methods = tk.Pack.__dict__.keys() | tk.Grid.__dict__.keys() \
                  | tk.Place.__dict__.keys()
        for meth in methods:
            if meth[0] != '_' and meth not in ('config', 'configure'):
                setattr(self, meth, getattr(master, meth))

    @staticmethod
    def _autoscroll(sbar):
        '''Hide and show scrollbar as needed.'''
        def wrapped(first, last):
            first, last = float(first), float(last)
            if first <= 0 and last >= 1:
                sbar.grid_remove()
            else:
                sbar.grid()
            sbar.set(first, last)
        return wrapped

    def __str__(self):
        return str(self.master)


def _create_container(func):
    '''Creates a ttk Frame with a given master, and use this new frame to
    place the scrollbars and the widget.'''
    def wrapped(cls, master, **kw):
        container = ttk.Frame(master)
        container.bind('<Enter>', lambda e: _bound_to_mousewheel(e, container))
        container.bind('<Leave>', lambda e: _unbound_to_mousewheel(e, container))
        return func(cls, container, **kw)
    return wrapped


class ScrolledListBox(AutoScroll, tk.Listbox):
    '''A standard Tkinter Listbox widget with scrollbars that will
    automatically show/hide as needed.'''
    @_create_container
    def __init__(self, master, **kw):
        tk.Listbox.__init__(self, master, **kw)
        AutoScroll.__init__(self, master)

    def size_(self):
        sz = tk.Listbox.size(self)
        return sz


def _bound_to_mousewheel(_, widget):
    child = widget.winfo_children()[0]
    if platform.system() == 'Windows' or platform.system() == 'Darwin':
        child.bind_all('<MouseWheel>', lambda e: _on_mousewheel(e, child))
        child.bind_all('<Shift-MouseWheel>', lambda e: _on_shiftmouse(e, child))
    else:
        child.bind_all('<Button-4>', lambda e: _on_mousewheel(e, child))
        child.bind_all('<Button-5>', lambda e: _on_mousewheel(e, child))
        child.bind_all('<Shift-Button-4>', lambda e: _on_shiftmouse(e, child))
        child.bind_all('<Shift-Button-5>', lambda e: _on_shiftmouse(e, child))


def _unbound_to_mousewheel(event, widget):
    if platform.system() == 'Windows' or platform.system() == 'Darwin':
        widget.unbind_all('<MouseWheel>')
        widget.unbind_all('<Shift-MouseWheel>')
    else:
        widget.unbind_all('<Button-4>')
        widget.unbind_all('<Button-5>')
        widget.unbind_all('<Shift-Button-4>')
        widget.unbind_all('<Shift-Button-5>')


def _on_mousewheel(event, widget):
    if platform.system() == 'Windows':
        widget.yview_scroll(-1*int(event.delta/120), 'units')
    elif platform.system() == 'Darwin':
        widget.yview_scroll(-1*int(event.delta), 'units')
    else:
        if event.num == 4:
            widget.yview_scroll(-1, 'units')
        elif event.num == 5:
            widget.yview_scroll(1, 'units')


def _on_shiftmouse(event, widget):
    if platform.system() == 'Windows':
        widget.xview_scroll(-1*int(event.delta/120), 'units')
    elif platform.system() == 'Darwin':
        widget.xview_scroll(-1*int(event.delta), 'units')
    else:
        if event.num == 4:
            widget.xview_scroll(-1, 'units')
        elif event.num == 5:
            widget.xview_scroll(1, 'units')


if __name__ == "__main__":

    root = tk.Tk()
    root.protocol('WM_DELETE_WINDOW', root.destroy)

    self.mwh: MainWindow = MainWindow(root)

    root.mainloop()
