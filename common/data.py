from dataclasses import dataclass

from .const import Actions


@dataclass
class FileInfo:
    """"Defines file metadata, which is to be sent"""

    dest_path: str
    hash: str
    size: str


@dataclass
class ServerFileInfo(FileInfo):

    size_transmited: int = 0


@dataclass
class ActionData:

    action: Actions
    data: object
