import tkinter as tk

from client_src.gui.main_window import ClientMainWindow


if __name__ == "__main__":
    root = tk.Tk()
    root.protocol('WM_DELETE_WINDOW', root.destroy)

    mwh: ClientMainWindow = ClientMainWindow(root)

    root.mainloop()
