import os
import tkinter as tk
import tkinter.ttk as ttk
from datetime import datetime
from logging import INFO, Logger, LoggerAdapter
from pathlib import Path
from tkinter import simpledialog
from tkinter.filedialog import askopenfilename

from client_src.client_impl import ClientImpl
from client_src.configuration import Config
from client_src.const import (BLACK, BLUE, FILES_SEP, GREEN, LABEL_DEFAULTS,
                              LISTBOX_DEFAULTS, ORANGE, RED, SERVER_SEP,
                              WIDGET_DEFAULTS)
from client_src.data import AddServerDialogData, ResponseMsg, TransferProgress
from client_src.gui.add_server_dialog import AddServerDialog
from client_src.logger import ClientLogger
from common.const import CANCELED
from common.data import FileInfo
from common.utils import ScrolledListBox


class ClientMainWindow:

    client: ClientImpl
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

        self.client = ClientImpl(self, self._logger, self.config.client_buffsize, self.config.client_file_block_size)
        self.top.bind("<Destroy>", self._on_destroy)

        self.logger = LoggerAdapter(self._logger, extra={
            "window": "Main Window"
        })

        self.menubar = tk.Menu(top,
                               font="TkMenuFont",
                               bg='SystemButtonFace')
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
                                            text='''Send selected file(s)''',
                                            **WIDGET_DEFAULTS)

        self.cancel_button = tk.Button(self.top,
                                       state=tk.DISABLED,
                                       command=self._cancel_click,
                                       text='''Cancel''',
                                       **WIDGET_DEFAULTS)

        self.cancel_all_button = tk.Button(self.top,
                                           state=tk.DISABLED,
                                           command=self._cancel_all,
                                           text='''Cancel all''',
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
        self.status_label.place(x=100, y=350, width=790, height=60)

        self.cancel_button.place(x=20, y=414, height=26, width=70)
        self.cancel_all_button.place(x=100, y=414, height=26, width=70)
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

        if dest_filepath and Path(dest_filepath).is_absolute():
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

        data = AddServerDialogData()

        AddServerDialog(self._logger, top2, data)
        self.top.wait_window(top2)

        if data.host is None or data.port is None:
            self.print_status("Unable to parse new server host config")
            return

        self.servers_scrolled_listbox.insert(0, str(data))

    def print_status(self, msg: str, color: str = "black", action_msg: ResponseMsg = None, log_level: int = INFO):
        """Print defines message to status label"""

        full_msg = f"{msg}{' - ' + str(action_msg) if action_msg else ''}"

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
        self.clear_files_button.configure(state=tk.DISABLED)
        self.remove_file_button.configure(state=tk.DISABLED)
        self.add_file_button.configure(state=tk.DISABLED)

        sel = self.files_scrolled_listbox.curselection()
        fileitems = []
        for i in sel:
            fileitems.append((i, self.files_scrolled_listbox.get(i)))
            self.files_scrolled_listbox.selection_clear(i)
        self._send_files(fileitems)

        self.add_file_button.configure(state=tk.NORMAL)

    def _send_all_click(self):
        self.clear_files_button.configure(state=tk.DISABLED)
        self.remove_file_button.configure(state=tk.DISABLED)
        self.add_file_button.configure(state=tk.DISABLED)

        fileitems = list(enumerate(self.files_scrolled_listbox.get(0, tk.END)))
        self._send_files(fileitems)

        self.add_file_button.configure(state=tk.NORMAL)

    def _cancel_click(self):
        self.cancel_button.configure(state=tk.DISABLED)
        self.client.cancel_transfer = True
        self.print_status("Canceling ...")

    def _cancel_all(self):
        self.cancel_all_button.configure(state=tk.DISABLED)
        self.client.cancel_all = True
        self.print_status("Canceling all ...")

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

        self.cancel_all_button.configure(state=tk.NORMAL)

        to_rm = []
        for i, _ in fileitems:
            self.files_scrolled_listbox.itemconfigure(i, foreground=BLACK)

        for i, fileitem in fileitems:
            if self.client.cancel_all:
                self.client.cancel_all = False
                break
            self.cancel_button.configure(state=tk.NORMAL)

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

            self.files_scrolled_listbox.itemconfigure(i, foreground=BLUE)
            action_msg = ResponseMsg()
            if self.client.send_file(src, file_inf.size, action_msg, progress):
                self.print_status(f"File {src} sent successfully", GREEN, action_msg)
                self.files_scrolled_listbox.itemconfigure(i, foreground=GREEN)
                to_rm.append(i)
            else:
                self.print_status(f"File {src} could not be send", RED, action_msg)
                self.files_scrolled_listbox.itemconfigure(i, foreground=RED)
                if action_msg and hasattr(action_msg, "server_response"):
                    if action_msg.server_response == CANCELED:
                        self.print_status(f"Sending {src} canceled", ORANGE, action_msg=action_msg)
                        self.files_scrolled_listbox.itemconfigure(i, foreground=ORANGE)
                self.progressbar.configure(value=0)

            self.cancel_button.configure(state=tk.DISABLED)

        self.cancel_all_button.configure(state=tk.DISABLED)
        self.client.cancel_all = False
        self.client.cancel_transfer = False

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

    def _on_destroy(self, event: tk.Event):
        if event.widget == event.widget.winfo_toplevel():
            if self.client.is_connected:
                self.client.close()
