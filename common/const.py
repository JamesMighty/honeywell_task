from enum import Enum


# End of transmission block
ETB = b"\x17"
# One char does not always work
# can be contained in some file types
CANCEL_B = b"\x18\x18\x18\x18"

OK_B = b"OK"
CANCELED_B = b"CANCELED"
ERROR_B = b"ERROR"
HASH_OK_B = b"HASH_OK"
HASH_BAD_B = b"HASH_BAD"

OK = "OK"
CANCELED = "CANCELED"
HASH_OK = "HASH_OK"
HASH_BAD = "HASH_BAD"


class Actions(int, Enum):

    ECHO = 1,
    SET_META = 2,
    START_SEND = 3,
    CLEAR_FILE_INFO = 4,
    SET_FILE_BLOCK_SIZE = 5,
