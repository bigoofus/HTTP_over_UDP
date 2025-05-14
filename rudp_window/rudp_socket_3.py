import socket
import threading
import time
import random
from rudp_packet import create_packet, parse_packet, FLAG_SYN, FLAG_ACK, FLAG_FIN

TIMEOUT = 2
MAX_PAYLOAD = 512
WINDOW_SIZE = 4
MAX_RETRIES = 5

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
        self.expected_seq = 0
        self.recv_buffer = {}

    def bind(self, address):
        self.sock.bind(address)

    def connect(self, address):
        self.peer_address = address
        syn_packet = create_packet(self.seq, 0, FLAG_SYN, 0, b'')
        self.sock.sendto(syn_packet, address)
        print(f"[Client] Sent SYN to {address}")

        while True:
            try:
                data, _ = self.sock.recvfrom(2048)
                packet = parse_packet(data)
                if packet['flags'] & (FLAG_SYN | FLAG_ACK):
                    self.ack = packet['seq'] + 1
                    self.seq += 1
                    ack_packet = create_packet(self.seq, self.ack, FLAG_ACK, 0, b'')
                    self.sock.sendto(ack_packet, address)
                    self.connected = True
                    print("[Client] Connection established")
                    return
            except socket.timeout:
                print("[Client] Timeout: Retrying SYN")
                self.sock.sendto(syn_packet, address)

    def accept(self):
        print("[Server] Waiting for connection...")
        while True:
            try:
                data, addr = self.sock.recvfrom(2048)
                packet = parse_packet(data)
                if packet['flags'] & FLAG_SYN:
                    self.peer_address = addr
                    self.ack = packet['seq'] + 1
                    self.seq = random.randint(0, 100000)
                    syn_ack = create_packet(self.seq, self.ack, FLAG_SYN | FLAG_ACK, 0, b'')
                    self.sock.sendto(syn_ack, addr)
                    print("[Server] Sent SYN+ACK")

                    while True:
                        try:
                            data2, _ = self.sock.recvfrom(2048)
                            packet2 = parse_packet(data2)
                            if packet2['flags'] & FLAG_ACK:
                                self.connected = True
                                print("[Server] Connection established")
                                return self, addr
                        except socket.timeout:
                            self.sock.sendto(syn_ack, addr)
            except socket.timeout:
                continue

    def send_data(self, data: bytes):
        if not self.connected:
            print("[Client] Not connected.")
            return

        base = self.seq
        next_seq = base
        unacked_packets = {}
        acked = set()
        total_data = len(data)
        window = WINDOW_SIZE

        def listen_for_acks():
            nonlocal base
            while base < self.seq + total_data:
                try:
                    ack_data, _ = self.sock.recvfrom(2048)
                    ack_packet = parse_packet(ack_data)
                    acked_seq = ack_packet['ack']
                    acked.update(range(base, acked_seq))
                    print(f"[Client] ACK received for seq < {acked_seq}")
                    base = max(base, acked_seq)
                except socket.timeout:
                    continue

        ack_thread = threading.Thread(target=listen_for_acks, daemon=True)
        ack_thread.start()

        retries = {s: 0 for s in range(base, base + total_data, MAX_PAYLOAD)}

        while base < self.seq + total_data:
            while next_seq < base + window * MAX_PAYLOAD and next_seq < self.seq + total_data:
                start = next_seq - self.seq
                end = min(start + MAX_PAYLOAD, total_data)
                payload = data[start:end]
                packet = create_packet(next_seq, 0, FLAG_ACK, 0, payload)
                self.sock.sendto(packet, self.peer_address)
                unacked_packets[next_seq] = payload
                print(f"[Client] Sent seq {next_seq}")
                next_seq += len(payload)

            time.sleep(0.5)  # Window pacing

            for s in list(unacked_packets.keys()):
                if s in acked:
                    unacked_packets.pop(s)
                else:
                    retries[s] += 1
                    if retries[s] > MAX_RETRIES:
                        print(f"[Client] Packet {s} failed after {MAX_RETRIES} retries.")
                        del unacked_packets[s]
                    else:
                        print(f"[Client] Retransmitting seq {s}")
                        payload = unacked_packets[s]
                        packet = create_packet(s, 0, FLAG_ACK, 0, payload)
                        self.sock.sendto(packet, self.peer_address)

        # Send FIN
        fin = create_packet(self.seq + total_data, 0, FLAG_FIN, 0, b'')
        self.sock.sendto(fin, self.peer_address)
        print("[Client] Sent FIN")

    def receive_file(self, output_filename):
        try:
            with open(output_filename, 'wb') as f:
                print(f"[Server] Receiving into '{output_filename}'...")
                while True:
                    try:
                        data, addr = self.sock.recvfrom(2048)
                        packet = parse_packet(data)

                        if packet['flags'] & FLAG_FIN:
                            print("[Server] FIN received. Closing file.")
                            fin_ack = create_packet(self.seq, packet['seq'] + 1, FLAG_ACK, 0, b'')
                            self.sock.sendto(fin_ack, addr)
                            break

                        seq = packet['seq']
                        if seq == self.expected_seq:
                            f.write(packet['payload'])
                            self.expected_seq += len(packet['payload'])

                            # Deliver buffered packets in order
                            while self.expected_seq in self.recv_buffer:
                                f.write(self.recv_buffer[self.expected_seq])
                                self.expected_seq += len(self.recv_buffer[self.expected_seq])
                                del self.recv_buffer[self.expected_seq]

                        elif seq > self.expected_seq:
                            # Out-of-order packet
                            if seq not in self.recv_buffer:
                                self.recv_buffer[seq] = packet['payload']
                            print(f"[Server] Buffered out-of-order packet {seq}")

                        ack_packet = create_packet(self.seq, self.expected_seq, FLAG_ACK, 0, b'')
                        self.sock.sendto(ack_packet, addr)
                        print(f"[Server] ACKed {self.expected_seq}")

                    except socket.timeout:
                        print("[Server] Timeout waiting for packets.")

        except Exception as e:
            print(f"[Server] Error receiving file: {e}")
    def send_file(self, filename):
        try:
            with open(filename, 'rb') as f:
                file_data = f.read()
                print(f"[Client] Sending file '{filename}' with size {len(file_data)} bytes.")
                self.send_data(file_data)
        except FileNotFoundError:
            print(f"[Client] Error: File '{filename}' not found.")

    def receive_file(self, output_filename):
        expected_seq = 0  # Start with 0 and update from first valid packet

        try:
            with open(output_filename, 'wb') as f:
                while True:
                    try:
                        data, addr = self.sock.recvfrom(2048)
                        packet = parse_packet(data)

                        if expected_seq == 0:
                            expected_seq = packet['seq']

                        if packet['seq'] == expected_seq:
                            if packet['flags'] & FLAG_FIN:
                                print("[Server] Received FIN. Ending file transfer.")
                                ack_packet = create_packet(
                                    self.seq, packet['seq'] + 1, FLAG_ACK, 0, b''
                                )
                                self.sock.sendto(ack_packet, addr)
                                break

                            f.write(packet['payload'])
                            print(f"[Server] Received packet {packet['seq']} with payload size {len(packet['payload'])}")

                            ack_packet = create_packet(
                                self.seq, packet['seq'] + len(packet['payload']), FLAG_ACK, 0, b''
                            )
                            self.sock.sendto(ack_packet, addr)
                            expected_seq += len(packet['payload'])

                        else:
                            print(f"[Server] Unexpected seq {packet['seq']}, expected {expected_seq}. Resending ACK.")
                            ack_packet = create_packet(
                                self.seq, expected_seq, FLAG_ACK, 0, b''
                            )
                            self.sock.sendto(ack_packet, addr)

                    except socket.timeout:
                        print("[Server] Timeout occurred while waiting for data. Retrying...")

        except Exception as e:
            print(f"[Server] Error while receiving file: {e}")