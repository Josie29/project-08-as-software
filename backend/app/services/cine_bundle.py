import struct

#: Not `application/octet-stream`: a distinct type means a proxy or a browser that decides
#: to sniff this has nothing to sniff it as, and a mismatched client fails loudly.
BUNDLE_MEDIA_TYPE = "application/vnd.portal.cine-frames"

#: Storage fan-out inside one bundle request. High enough to hide per-object latency,
#: bounded so one clip cannot monopolise the connection pool of the storage client.
BUNDLE_FETCH_CONCURRENCY = 16

_HEADER = struct.Struct("<I")
_ENTRY = struct.Struct("<HI")


def pack_frames(frames: list[tuple[int, bytes]]) -> bytes:
    """Pack frames into the bundle wire format.

    Layout, little-endian throughout:

    - `uint32` frame count
    - one `uint16` sequence + `uint32` byte length per frame, in the order given
    - every frame's bytes, concatenated in that same order

    A length-prefixed index rather than multipart: the client needs to slice the payload
    into blobs by offset, and multipart would mean scanning for boundaries in binary data
    that may contain them.

    Args:
        frames: Sequence numbers paired with their bytes, in playback order.

    Returns:
        The encoded bundle.
    """
    index = bytearray(_HEADER.pack(len(frames)))
    for sequence, payload in frames:
        index += _ENTRY.pack(sequence, len(payload))
    return bytes(index) + b"".join(payload for _, payload in frames)
