import socket
import threading
import time
import random
import logging
from rudp_packet_wait import create_packet, parse_packet, FLAG_SYN, FLAG_ACK, FLAG_FIN, PacketCorruptedError,calculate_checksum

TIMEOUT = 2
MAX_PAYLOAD = 1024
PACKET_LOSS = 0.1
PACKET_CORRUPTION = 0.1
MAX_RETRIES = 10

def simulate_packet_loss():
    """Simulate packet loss with a probability."""
    return random.random() < PACKET_LOSS

def simulate_packet_corruption(packet: bytes):
    """Simulate packet corruption with a probability."""
    if random.random() < PACKET_CORRUPTION:
        corrupted_packet = bytearray(packet)
        # Corrupt one random byte in the packet
        corrupted_packet[random.randint(0, len(corrupted_packet) - 1)] ^= 0xFF  # Flip a byte
        return bytes(corrupted_packet)
    return packet


# Set up logging to both file and console
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

# File handler
file_handler = logging.FileHandler('rudp_communication.log')
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_formatter = logging.Formatter('%(levelname)s - %(message)s')  # Shorter format for console
console_handler.setFormatter(console_formatter)

# Add both handlers to the root logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)


class RUDPSocket:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(TIMEOUT)
        self.peer_address = None
        self.seq = random.randint(0, 100000)
        self.ack = 0
        self.connected = False

        self.send_lock = threading.Lock()
        self.recv_lock = threading.Lock()

        # Tracking received sequence numbers for duplicate protection
        self.received_seq_numbers = set()

        # Log connection initialization
        logging.info("RUDPSocket initialized")

    def bind(self, address):
        self.sock.bind(address)
        logging.info(f"Socket bound to address {address}")

    def connect(self, address):
        self.peer_address = address
        syn_packet = create_packet(self.seq, 0, FLAG_SYN, b'')
        self.sock.sendto(syn_packet, address)
        logging.info(f"[Client] Sent SYN to {address} seq {self.seq} flags {FLAG_SYN:#04x}")

        retries = 0
        while retries < MAX_RETRIES:
            try:
                data, _ = self.sock.recvfrom(2048)
                packet = parse_packet(data)
                if packet['flags'] & (FLAG_SYN | FLAG_ACK):
                    self.ack = packet['seq'] + 1
                    self.seq += 1
                    ack_packet = create_packet(self.seq, self.ack, FLAG_ACK, b'')
                    self.sock.sendto(ack_packet, address)
                    self.connected = True
                    logging.info(f"[Client] Connection established, received ACK seq {packet['seq']} flags {packet['flags']:#04x}")
                    return
            except socket.timeout:
                retries += 1
                logging.warning(f"[Client] Timeout: Retrying SYN ({retries}/{MAX_RETRIES})")
                self.sock.sendto(syn_packet, address)
        
        logging.error("[Client] Maximum retries reached. Connection failed.")

    def accept(self):
        logging.info("[Server] Waiting for connection...")
        while True:
            try:
                data, addr = self.sock.recvfrom(2048)
                packet = parse_packet(data)
                if packet['flags'] & FLAG_SYN:
                    self.peer_address = addr
                    self.ack = packet['seq'] + 1
                    self.seq = random.randint(0, 100000)
                    syn_ack = create_packet(self.seq, self.ack, FLAG_SYN | FLAG_ACK, b'')
                    self.sock.sendto(syn_ack, addr)
                    logging.info(f"[Server] Sent SYN+ACK flags {(FLAG_SYN | FLAG_ACK):#04x}")

                    while True:
                        try:
                            data2, _ = self.sock.recvfrom(2048)
                            packet2 = parse_packet(data2)
                            if packet2['flags'] & FLAG_ACK:
                                self.connected = True
                                logging.info(f"[Server] Connection established, received ACK seq {packet2['seq']} flags {packet2['flags']:#04x}")
                                return self, addr
                        except socket.timeout:
                            self.sock.sendto(syn_ack, addr)
            except socket.timeout:
                continue

    def assess_file(self, filename):
        try:
            with open(filename, 'rb') as f:
                file_data = f.read()
                file_size = len(file_data)
                logging.info(f"[Client] File '{filename}' has size {file_size} bytes.")
                
                total_packets = (file_size + MAX_PAYLOAD - 1) // MAX_PAYLOAD  # This rounds up the division
                logging.info(f"[Client] Total packets required: {total_packets}")

                # Show each packet size
                for i in range(total_packets):
                    start = i * MAX_PAYLOAD
                    end = min(start + MAX_PAYLOAD, file_size)
                    packet_size = end - start
                    logging.info(f"[Client] Packet {i + 1}: {packet_size} bytes")
                    
        except FileNotFoundError:
            logging.error(f"[Client] Error: File '{filename}' not found.")

    def send_data(self, data: bytes):
        if not self.connected:
            logging.error("[Client] Not connected.")
            return

        base = self.seq
        next_seq = base
        total_data = len(data)

        while next_seq < base + total_data:
            # Calculate payload slice
            start = next_seq - base
            end = min(start + MAX_PAYLOAD, total_data)
            payload = data[start:end]

            # Create the original clean packet
            original_packet = create_packet(next_seq, 0, FLAG_ACK, payload)

            retries = 0
            while retries < MAX_RETRIES:
                # Simulate corruption and loss on each attempt
                trial_packet = simulate_packet_corruption(original_packet)
                if simulate_packet_loss():
                    logging.warning(f"[Client] Packet loss simulated for seq {next_seq}. Not sending this packet (Retry {retries + 1}/{MAX_RETRIES}).")
                    retries += 1
                    continue

                self.sock.sendto(trial_packet, self.peer_address)
                logging.info(f"[Client] Sent seq {next_seq}, ACK 0, Flags {FLAG_ACK:#04x} (Retry {retries})")

                try:
                    ack_data, _ = self.sock.recvfrom(2048)
                    ack_data = simulate_packet_corruption(ack_data)

                    try:
                        ack_packet = parse_packet(ack_data)
                    except PacketCorruptedError:
                        logging.warning("[Client] Corrupted ACK packet received. Ignoring.")
                        continue

                    logging.info(f"[Client] Received ACK seq {ack_packet['ack']}, Flags {ack_packet['flags']:#04x}")

                    # Check if ACK is for this packet
                    if ack_packet['ack'] == next_seq + len(payload):
                        next_seq += len(payload)
                        break
                except socket.timeout:
                    logging.warning(f"[Client] Timeout waiting for ACK for seq {next_seq} (Retry {retries + 1}/{MAX_RETRIES})")

                retries += 1

            if retries == MAX_RETRIES:
                logging.error(f"[Client] Max retries reached for seq {next_seq}. Aborting transfer.")
                return

        # Send FIN after data is sent
        fin = create_packet(next_seq, 0, FLAG_FIN, b'')
        self.sock.sendto(fin, self.peer_address)
        logging.info(f"[Client] Sent FIN seq {next_seq}, ACK 0, Flags {FLAG_FIN:#04x}")

        
    def verify_received_data(self, received_data, expected_checksum):
        calculated_checksum = calculate_checksum(received_data)
        if calculated_checksum == expected_checksum:
            logging.info("[Receiver] Checksum is valid, data is not corrupted.")
            return True
        else:
            logging.warning("[Receiver] Checksum mismatch, data may be corrupted.")
            return False

    def receive_file(self, output_filename):
        expected_seq = 0  # Start with 0 and update from the first valid packet

        try:
            with open(output_filename, 'wb') as f:
                while True:
                    try:
                        data, addr = self.sock.recvfrom(2048)
                        # Simulate packet corruption
                        
                        # Simulate packet loss
                        if simulate_packet_loss():
                            logging.warning(f"[Server] Packet loss simulated. Skipping received packet.")
                            continue

                        try:
                            packet = parse_packet(data)
                        except PacketCorruptedError:
                            logging.warning("[Server] Corrupted packet received. Ignoring.")
                            continue

                        # Log the received packet details
                        logging.info(f"[Server] Received seq {packet['seq']}, ACK {packet['ack']}, Flags {packet['flags']:#04x}")

                        # Check if packet checksum is valid
                        if self.verify_received_data(packet['payload'], packet['checksum']):
                            logging.warning(f"[Server] Invalid checksum for packet {packet['seq']}. Ignoring.")
                            continue

                        if packet['seq'] in self.received_seq_numbers:
                            # Duplicate packet received, resend ACK and ignore
                            logging.info(f"[Server] Duplicate packet {packet['seq']} received, ignoring.")
                            ack_packet = create_packet(self.seq, expected_seq, FLAG_ACK, b'')
                            self.sock.sendto(ack_packet, addr)
                            continue

                        if expected_seq == 0 and not self.received_seq_numbers:
                            expected_seq = packet['seq']

                        if packet['seq'] == expected_seq:
                            if packet['flags'] & FLAG_FIN:
                                logging.info("[Server] Received FIN. Ending file transfer.")
                                ack_packet = create_packet(self.seq, packet['seq'] + 1, FLAG_ACK, b'')
                                self.sock.sendto(ack_packet, addr)
                                break

                            f.write(packet['payload'])
                            logging.info(f"[Server] Received packet {packet['seq']} with payload size {len(packet['payload'])}")

                            ack_packet = create_packet(self.seq, packet['seq'] + len(packet['payload']), FLAG_ACK, b'')
                            self.sock.sendto(ack_packet, addr)
                            self.received_seq_numbers.add(packet['seq'])  # Track received packet
                            expected_seq += len(packet['payload'])

                        else:
                            logging.warning(f"[Server] Unexpected seq {packet['seq']}, expected {expected_seq}. Resending ACK.")
                            ack_packet = create_packet(self.seq, expected_seq, FLAG_ACK, b'')
                            self.sock.sendto(ack_packet, addr)

                    except socket.timeout:
                        logging.warning("[Server] Timeout occurred while waiting for data. Retrying...")

        except Exception as e:
            logging.error(f"[Server] Error while receiving file: {e}")

    def receive_data(self):
        expected_seq = 0
        received_data = bytearray()  # In-memory data buffer

        try:
            while True:
                try:
                    data, addr = self.sock.recvfrom(2048)

                    # Simulate packet loss
                    if simulate_packet_loss():
                        logging.warning(f"[Server] Packet loss simulated. Skipping received packet.")
                        continue

                    try:
                        packet = parse_packet(data)
                    except PacketCorruptedError:
                        logging.warning("[Server] Corrupted packet received. Ignoring.")
                        continue

                    logging.info(f"[Server] Received seq {packet['seq']}, ACK {packet['ack']}, Flags {packet['flags']:#04x}")

                    if self.verify_received_data(packet['payload'], packet['checksum']):
                        logging.warning(f"[Server] Invalid checksum for packet {packet['seq']}. Ignoring.")
                        continue

                    if packet['seq'] in self.received_seq_numbers:
                        logging.info(f"[Server] Duplicate packet {packet['seq']} received, ignoring.")
                        ack_packet = create_packet(self.seq, expected_seq, FLAG_ACK, b'')
                        self.sock.sendto(ack_packet, addr)
                        continue

                    if expected_seq == 0 and not self.received_seq_numbers:
                        expected_seq = packet['seq']

                    if packet['seq'] == expected_seq:
                        if packet['flags'] & FLAG_FIN:
                            logging.info("[Server] Received FIN. Ending data reception.")
                            ack_packet = create_packet(self.seq, packet['seq'] + 1, FLAG_ACK, b'')
                            self.sock.sendto(ack_packet, addr)
                            break

                        received_data.extend(packet['payload'])
                        logging.info(f"[Server] Received packet {packet['seq']} with payload size {len(packet['payload'])}")

                        ack_packet = create_packet(self.seq, packet['seq'] + len(packet['payload']), FLAG_ACK, b'')
                        self.sock.sendto(ack_packet, addr)
                        self.received_seq_numbers.add(packet['seq'])
                        expected_seq += len(packet['payload'])

                    else:
                        logging.warning(f"[Server] Unexpected seq {packet['seq']}, expected {expected_seq}. Resending ACK.")
                        ack_packet = create_packet(self.seq, expected_seq, FLAG_ACK, b'')
                        self.sock.sendto(ack_packet, addr)

                except socket.timeout:
                    logging.warning("[Server] Timeout occurred while waiting for data. Retrying...")

        except Exception as e:
            logging.error(f"[Server] Error while receiving data: {e}")

        return received_data

    def send_file(self, filename):
        try:
            with open(filename, 'rb') as f:
                file_data = f.read()
                logging.info(f"[Client] Sending file '{filename}' with size {len(file_data)} bytes.")
                self.send_data(file_data)
        except FileNotFoundError:
            logging.error(f"[Client] Error: File '{filename}' not found.")
