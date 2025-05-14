import socket
import threading
import time
import random
import logging
from rudp_packet_wait import create_packet, parse_packet, FLAG_SYN, FLAG_ACK, FLAG_FIN

TIMEOUT = 2
MAX_PAYLOAD = 512
MAX_RETRIES = 5

# Set up logging to a file
logging.basicConfig(
    filename='rudp_communication.log',  # Log file name
    level=logging.DEBUG,               # Log level (DEBUG to capture everything)
    format='%(asctime)s - %(levelname)s - %(message)s',  # Log format
)

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
        logging.info(f"[Client] Sent SYN to {address}")

        while True:
            try:
                data, _ = self.sock.recvfrom(2048)
                packet = parse_packet(data)
                if packet['flags'] & (FLAG_SYN | FLAG_ACK):
                    self.ack = packet['seq'] + 1
                    self.seq += 1
                    ack_packet = create_packet(self.seq, self.ack, FLAG_ACK, b'')
                    self.sock.sendto(ack_packet, address)
                    self.connected = True
                    logging.info("[Client] Connection established")
                    return
            except socket.timeout:
                logging.warning("[Client] Timeout: Retrying SYN")
                self.sock.sendto(syn_packet, address)

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
                    logging.info("[Server] Sent SYN+ACK")

                    while True:
                        try:
                            data2, _ = self.sock.recvfrom(2048)
                            packet2 = parse_packet(data2)
                            if packet2['flags'] & FLAG_ACK:
                                self.connected = True
                                logging.info("[Server] Connection established")
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
            start = next_seq - self.seq
            end = min(start + MAX_PAYLOAD, total_data)
            payload = data[start:end]
            packet = create_packet(next_seq, 0, FLAG_ACK, payload)
            self.sock.sendto(packet, self.peer_address)
            logging.info(f"[Client] Sent seq {next_seq}")

            while True:
                try:
                    ack_data, _ = self.sock.recvfrom(2048)
                    ack_packet = parse_packet(ack_data)
                    if ack_packet['ack'] == next_seq + len(payload):
                        logging.info(f"[Client] ACK received for seq {next_seq}")
                        next_seq += len(payload)  # Move to the next packet
                        break
                except socket.timeout:
                    logging.warning(f"[Client] Timeout waiting for ACK for seq {next_seq}")
                    self.sock.sendto(packet, self.peer_address)  # Retransmit the packet

        # Send FIN
        fin = create_packet(self.seq + total_data, 0, FLAG_FIN, b'')
        self.sock.sendto(fin, self.peer_address)
        logging.info("[Client] Sent FIN")

    def receive_file(self, output_filename):
        expected_seq = 0  # Start with 0 and update from first valid packet

        try:
            with open(output_filename, 'wb') as f:
                while True:
                    try:
                        data, addr = self.sock.recvfrom(2048)
                        packet = parse_packet(data)

                        if packet['seq'] in self.received_seq_numbers:
                            # Duplicate packet received, resend ACK and ignore
                            logging.info(f"[Server] Duplicate packet {packet['seq']} received, ignoring.")
                            ack_packet = create_packet(
                                self.seq, expected_seq, FLAG_ACK, b'' 
                            )
                            self.sock.sendto(ack_packet, addr)
                            continue

                        if expected_seq == 0:
                            expected_seq = packet['seq']

                        if packet['seq'] == expected_seq:
                            if packet['flags'] & FLAG_FIN:
                                logging.info("[Server] Received FIN. Ending file transfer.")
                                ack_packet = create_packet(
                                    self.seq, packet['seq'] + 1, FLAG_ACK, b'' 
                                )
                                self.sock.sendto(ack_packet, addr)
                                break

                            f.write(packet['payload'])
                            logging.info(f"[Server] Received packet {packet['seq']} with payload size {len(packet['payload'])}")

                            ack_packet = create_packet(
                                self.seq, packet['seq'] + len(packet['payload']), FLAG_ACK, b'' 
                            )
                            self.sock.sendto(ack_packet, addr)
                            self.received_seq_numbers.add(packet['seq'])  # Track received packet
                            expected_seq += len(packet['payload'])

                        else:
                            logging.warning(f"[Server] Unexpected seq {packet['seq']}, expected {expected_seq}. Resending ACK.")
                            ack_packet = create_packet(
                                self.seq, expected_seq, FLAG_ACK, b'' 
                            )
                            self.sock.sendto(ack_packet, addr)

                    except socket.timeout:
                        logging.warning("[Server] Timeout occurred while waiting for data. Retrying...")

        except Exception as e:
            logging.error(f"[Server] Error while receiving file: {e}")
    
    def send_file(self, filename):
        try:
            with open(filename, 'rb') as f:
                file_data = f.read()
                logging.info(f"[Client] Sending file '{filename}' with size {len(file_data)} bytes.")
                self.send_data(file_data)
        except FileNotFoundError:
            logging.error(f"[Client] Error: File '{filename}' not found.")
