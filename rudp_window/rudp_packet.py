import struct
import zlib

# SEQ (4), ACK (4), FLAGS (1), WINDOW (2), LENGTH (2), CHECKSUM (4)
HEADER_FORMAT = '!IIBHHI'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

FLAG_SYN = 0x01
FLAG_ACK = 0x02
FLAG_FIN = 0x04

def calculate_checksum(data):
    return zlib.crc32(data) & 0xFFFFFFFF  # 32-bit checksum

def create_packet(seq, ack, flags, window, payload: bytes) -> bytes:
    length = len(payload)
    dummy_checksum = 0

    # Create header with dummy checksum
    header = struct.pack(HEADER_FORMAT, seq, ack, flags, window, length, dummy_checksum)
    checksum = calculate_checksum(header + payload)

    # Final header with actual checksum
    header = struct.pack(HEADER_FORMAT, seq, ack, flags, window, length, checksum)
    return header + payload

def parse_packet(packet: bytes):
    if len(packet) < HEADER_SIZE:
        raise ValueError("Packet too short")

    header = packet[:HEADER_SIZE]
    seq, ack, flags, window, length, checksum = struct.unpack(HEADER_FORMAT, header)
    payload = packet[HEADER_SIZE:]

    if len(payload) != length:
        raise ValueError("Payload length mismatch")

    # Recreate header with checksum field zeroed out
    dummy_header = struct.pack(HEADER_FORMAT, seq, ack, flags, window, length, 0)
    computed_checksum = calculate_checksum(dummy_header + payload)
    if checksum != computed_checksum:
        raise ValueError("Checksum mismatch")

    return {
        'seq': seq,
        'ack': ack,
        'flags': flags,
        'window': window,
        'length': length,
        'checksum': checksum,
        'payload': payload
    } 