"""Frames copied verbatim from the Longtail Duo Android HCI capture."""

STATUS_REQUEST = bytes.fromhex("62 00 0c 0b 06 07 08 09 11 0a 0b 0c 0f 23 4f 84 91 45")
STATUS_REPLY = bytes.fromhex(
    "62 00 30 0b"
    " 06 02 00 00"
    " 07 02 01 bf"
    " 08 02 00 7e"
    " 09 04 00 00 04 b1"
    " 11 01 00"
    " 0a 04 00 00 85 44"
    " 0b 02 02 8f"
    " 0c 04 00 00 04 b1"
    " 0f 01 44"
    " 23 02 00 00"
    " 4f 01 01"
    " 83 d3 45"
)
INFO_REQUEST = bytes.fromhex("62 00 05 04 04 05 4f 70 8a 12 45")
INFO_REPLY = bytes.fromhex(
    "62 00 2d 04"
    " 04 03 02 14 10"
    " 05 10 30 30 30 30 30 30 30 30 35 33 30 36 30 30 34 35"
    " 4f 01 01"
    " 70 10 59 4a 32 35 30 33 31 39 41 30 30 32 33 34 30 00"
    " 52 88 45"
)
# Clock sync written by the app; used here only as a valid write-type frame.
CLOCK_WRITE = bytes.fromhex("63 00 0a 01 3c 07 02 1a 0a 12 0e 20 12 ff f3 45")
CLOCK_REPLY = bytes.fromhex("63 00 09 01 3c 07 02 1a 12 0e 20 12 ee ed 45")
