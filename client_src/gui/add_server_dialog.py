import socket
import tkinter as tk
from logging import Logger, LoggerAdapter
from tkinter import IntVar, StringVar

from client_src.client_impl import ClientImpl
from client_src.data import AddServerDialogData, ResponseMsg
from client_src.const import GREEN, LABEL_DEFAULTS, RED, WIDGET_DEFAULTS


class AddServerDialog:
    """"Defines dialog window for adding new server connection."""

    GEOMETRY = "380x180"
    TITLE = "Add new server"

    def __init__(self, logger: Logger, top: tk.Tk = None, data: AddServerDialogData = None):

        top.geometry(AddServerDialog.GEOMETRY)
        top.resizable(0,  0)
        top.title(AddServerDialog.TITLE)
        top.configure(highlightcolor="SystemWindowText")

        self.data = data
        self.top = top
        self.host = StringVar()
        self.port = IntVar()
        self._logger = logger
        self.log = LoggerAdapter(logger, extra={
            "window": "Add Server Window"
            })

        self.host_entry = tk.Entry(self.top, textvariable=self.host, **WIDGET_DEFAULTS)
        self.host_label = tk.Label(self.top, text='''Hostname or IP:''', **LABEL_DEFAULTS)
        self.port_label = tk.Label(self.top, text='''Port:''', **LABEL_DEFAULTS)
        self.port_entry = tk.Entry(self.top, textvariable=self.port, **WIDGET_DEFAULTS)
        self.status_label_ = tk.Label(self.top, text='''Status:''', wraplength=116, **LABEL_DEFAULTS)
        self.status_label = tk.Label(self.top, wraplength=205, **LABEL_DEFAULTS)
        self.test_button = tk.Button(self.top,
                                     command=self._test_button_click,
                                     text='''Test''',
                                     **WIDGET_DEFAULTS)
        self.add_button = tk.Button(self.top,
                                    state=tk.DISABLED,
                                    command=self._add_button_click,
                                    text='''Add''',
                                    **WIDGET_DEFAULTS)

        self.host_entry.place(x=143, y=21, height=20, width=204)
        self.host_label.place(x=21, y=21, height=15, width=103)
        self.port_label.place(x=21, y=52, height=15, width=85)
        self.port_entry.place(x=143, y=52, height=20, width=204)
        self.status_label_.place(x=21, y=83, height=42, width=116)
        self.status_label.place(x=143, y=83, height=42, width=209)
        self.test_button.place(x=240, y=135, height=26, width=47)
        self.add_button.place(x=300, y=135, height=26, width=47)

        self.host.trace_add("write", lambda *_: self.add_button.configure(state=tk.DISABLED))
        self.port.trace_add("write", lambda *_: self.add_button.configure(state=tk.DISABLED))

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
            cli = ClientImpl(None, self._logger)
            cli.connect(ip4, port)
            report = ResponseMsg()
            if cli.test_connection(report):
                msg = "Remote server test OK"
                self.log.info(msg)
                self.status_label.configure(text=msg, fg=GREEN)
            else:
                msg = f"Remote server test ERROR ({report})"
                self.log.info(msg)
                self.status_label.configure(text=msg, fg=RED)

        except Exception as err:
            self.log.warning("Check error", exc_info=err)
            self.status_label.configure(text=str(err), fg=RED)

    def _add_button_click(self):
        self.data.host = self.host.get()
        self.data.port = self.port.get()
        self.top.destroy()