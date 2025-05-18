import logging,struct,socket,random
from constants import *
HEADER_FORMAT = '!IIBH H'  #4-byte each for ACK and SYN , 1-byte for flags , 2-bytes each for length and checksum 
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def checksum_calc(header_tuple, data):
    #Extract Header and convert to bytes format
    seq, ack, flags, length = header_tuple
    header_bytes = struct.pack('!IIBH', seq, ack, flags, length)

    # whole packet on bytes format
    packet = header_bytes + data

    if len(packet) % 2 == 1:
        packet += b'\x00'
    checksum = 0

    #Iterate through the packet 2 bytes at a time creating 16-bit words and adding them to checksum
    for i in range(0, len(packet), 2):
        word = (packet[i] << 8) + packet[i + 1]
        checksum += word
        while checksum >> 16:
            #Wrap overflow bits
            checksum = (checksum & 0xFFFF) + (checksum >> 16)

    return ~checksum & 0xFFFF #One's Complement of checksum value

def pack_packet(seq, ack, flags, payload=b''):

    if len(payload) > MAX_PAYLOAD_SIZE:
        raise ValueError(f"Payload size exceeds {MAX_PAYLOAD_SIZE} bytes.")
    
    length = len(payload) 
    checksum = checksum_calc((seq, ack, flags, length), payload)    #Calculate Checksum value for error detection
    header = struct.pack(HEADER_FORMAT, seq, ack, flags, length, checksum)  

    return header + payload

def unpack_packet(packet_bytes):

    if len(packet_bytes) < HEADER_SIZE: #Data Loss
        logging.warning("RUDP: Packet too short for header (Data Loss).")
        return None
    
    #Split header bytes from payload bytes
    header = packet_bytes[:HEADER_SIZE]     
    payload = packet_bytes[HEADER_SIZE:]

    #Extract header data from header bytes
    seq_num, ack, flags, length, checksum_recvd = struct.unpack(HEADER_FORMAT, header)  

    if length != len(payload):
        logging.warning(f"RUDP: Length incorrect (Data Loss). Length in Header: {length}, Actual: {len(payload)}.")
        return None
    
    expected_checksum = checksum_calc((seq_num, ack, flags, length), payload)

    if checksum_recvd != expected_checksum:
        logging.warning(f"RUDP: Checksum is not Same (Data Corruption). Received: {checksum_recvd}, Calculated: {expected_checksum}.")
        return None
    
    return seq_num , ack , flags , payload

class RUDPsocket:
    def __init__(self,loss_rate=0.0,corp_rate=0.0,address=None):

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.peer_addr = None
        self.seq = 0
        self.ack = 0
        self.expected_seq_num = 0
        
        self.loss_rate = loss_rate
        self.corruption_rate = corp_rate
        self.closed = False
        # self.state = CLOSED

        self.timeout_duration = TIMEOUT
        self.max_retries = RETRANSMISSIONS
        
        self.packet_to_be_resent = None
        self.current_retry_count = 0

        if address:
            try:
                self.socket.bind(address)
                logging.info(f"RUDP: Socket bound to {address}")
            except socket.error as e:
                logging.error(f"RUDP: Bind failed for {address}: {e}")
                raise
            
    def _simulate_packet_loss(self):
        if random.random() < self.loss_rate and self.loss_rate > 0:
            logging.info("RUDP: packet is to be lost.")
            return True
        
    def _simulate_packet_corruption(self,packet):
        if self.corruption_rate > 0 and random.random() < self.corruption_rate:

            logging.info(f"RUDP: packet is to be corrupted")
            temp_list = bytearray(packet)

            if len(temp_list) > 0:

                # Flip bits of a random byte in packet
                idx = random.randint(0, len(temp_list) - 1) 
                temp_list[idx] ^= 0xFF  
                temp = packet = bytes(temp_list)

                return temp
            
        return packet
    
    def _send_packet(self,seq,ack,flag,payload=b''):
        if self.closed == False:
            packet = pack_packet(seq,ack,flag,payload)
        
            if self._simulate_packet_loss():
                return True
            packet_to_send = packet 
            packet_to_send = self._simulate_packet_corruption(packet)
            
            try:
                #If no exception raised at sending process of packet then sent succesfully
                self.socket.sendto(packet_to_send, self.peer_addr)  
                logging.info(f"[RUDP-SEND] To {self.peer_addr}, seq={seq}, len={len(payload)}")

                # logging.info(f"RUDP: Sent packet: {seq}, {ack}, {flag}, {len(payload)} bytes")
            
                return True
            
            except socket.error as e:

                #If exception raised at sending process of packet then error occured while UDP sending
                logging.error(f"RUDP: Socket error sending packet: {e}")
            
                return False
            
    def _receive_packet(self):
        
        try:
            self.socket.settimeout(self.timeout_duration)

            packet_bytes , addr = self.socket.recvfrom(HEADER_SIZE + MAX_PAYLOAD_SIZE)

            unpacked = unpack_packet(packet_bytes)

            if unpacked != None:
                seq_num , ack , flags , payload = unpacked[0],unpacked[1],unpacked[2],unpacked[3]

                logging.info(f"[RUDP] Packet received from {addr}: seq={seq_num}, ack={ack}, flags={flags}, len={len(payload)}")

                return (seq_num , ack , flags , payload , addr)
            else:
                logging.warning("[RUDP] Invalid packet discarded.")
                return "invalid"
            
        except socket.timeout:
            #return error if timeout of socket ended and no packet was received
            logging.debug("[RUDP] Socket timeout — no packet received.")
            return "timeout"
        
        except socket.error as e:
            #return error otherwise if no packet received by socket
            logging.error(f"RUDP: Socket error receiving packet: {e}")
            return "error"
    
    #Server Side Function to accept connection
    def accept(self):
        while True:
            pkt = self._receive_packet()

            if pkt == "timeout":
                continue
            if pkt == "error":
                logging.info(f"[RUDP SERVER] runtime error no connection established")
                continue
            if pkt =="invalid":
                continue

            rseq, rack, rflags, payload, client_addr = pkt

            if rflags == SYN_FLAG:

                # Reuse self instead of child socket
                self.peer_addr = client_addr
                self.seq = random.randint(0, 0xFFFFFFFF-1)
                self.ack = rseq + 1
                self.expected_seq_num = rseq + 1

                # 1) send SYN-ACK
                self._send_packet(self.seq, self.ack, SYNACK_FLAG)
                self.seq += 1
                logging.info(f"[RUDP SERVER] SYN-ACK sent to {client_addr} seq {self.seq} ack {self.ack}")

                # 2) wait for final ACK
                reply = self._wait_for_reply(expected_flags=ACK_FLAG,
                                            exp_seq = None,
                                            exp_ack = self.seq + 1)
                if reply == "timeout":
                    continue
                if reply == "error":
                    logging.info(f"[RUDP SERVER] runtime error no connection established")
                    continue

                logging.info(f"[RUDP SERVER]: Accepted connection from {client_addr}")
                return self, client_addr
            
    def _wait_for_reply(self, expected_flags, exp_seq=None, exp_ack=None):
        """
        Internal helper: wait once for a packet matching the expected criteria.
        Returns the unpacked packet tuple or "timeout"/"error".
        """
        pkt = self._receive_packet()

        if isinstance(pkt, tuple):
            rseq, rack, rflags, _payload,_addr = pkt
            if (rflags & expected_flags) == expected_flags \
               and (exp_seq is None or rseq == exp_seq)     \
               and (exp_ack is None or rack == exp_ack):
                return pkt
            
        return pkt  # timeout or error string        

    #Client Side Function to establish a connection     
    def connect(self , server_addr):

        self.peer_addr = server_addr

        #sending intial syn the ack should be 0
        self.seq=random.randint(0, 0xFFFFFFFF)
        self.ack=0
        
        flag=SYN_FLAG
        
        for attempt in range(self.max_retries):
            #Attempt to send SYN
            if self._send_packet(self.seq,self.ack,flag) == False:
                return
            
            logging.info(f"[RUDP-CLIENT] SYN sent seq={self.seq} ack={self.ack} attempt {attempt+1}/{self.max_retries}")

            #wait for SYN-ACK to be received from server
            reply = self._wait_for_reply(expected_flags = SYNACK_FLAG)

            if reply == "timeout":
                #Resend SYN again
                continue
            if reply == "error":
                break
            if reply=="invalid":
                continue

            rseq, rack , rflags , _ , _ = reply

            #if SYN-ACK Received then its respective ACK and then connection is established
            if rflags == SYNACK_FLAG and rack == self.seq + 1:
                logging.info(f"[RUDP-CLIENT] SYN-ACK received with ack = {rack}")
                self.expected_seq_num = rseq + 1
                self.seq += 1
                self._send_packet(self.seq,self.expected_seq_num , ACK_FLAG)
                logging.info(f"[RUDP-CLIENT] Sending ACK with seq = {self.seq} and ack = {self.expected_seq_num}")
                return True
            
        raise RuntimeError("RUDP: connect failed – handshake exhausted")
    
    def send_data(self,data):
        
        offset=0
        while offset<len(data):
            chunk = data[offset:offset+MAX_PAYLOAD_SIZE]
            length=len(chunk)
            
            for attempt in range(self.max_retries):
                self._send_packet(self.seq,0,DATA_FLAG,chunk)
                logging.info(f"[RUDP-SEND] seq={self.seq} len={length} attempt {attempt+1}")  
                reply=self._wait_for_reply(expected_flags=ACK_FLAG,
                                           exp_seq=None,
                                           exp_ack=self.seq + length)
                if reply == "timeout":
                    continue
                if reply =="error":
                    logging.error("RUDP: socket error during send")
                    return False
                if reply =="invalid":
                    logging.warning("[RUDP-SEND] receiver reported INVALID → resend")
                    continue
                
                self.seq+=length
                break

            else:
                logging.error("RUDP: send_data exhausted retries")
                return False
            
            offset += length
        return True
    
    def receive_data(self, max_retries =RETRANSMISSIONS):

        retries = 0
        logging.warning(f"[RUDP-RECV] receive data called")

        while retries < max_retries:

            pkt = self._receive_packet()

            if pkt == "timeout":
                retries += 1
                logging.warning(f"[RUDP-RECV] timeout waiting for packet, retry {retries}/{max_retries}")

                continue

            if pkt == "invalid":
                logging.warning("[RUDP]: Invalid Packet Flag Received")
                retries += 1
                continue

            if pkt == "error":
                logging.warning("[RUDP]: Error Packet Flag Received")
                raise RuntimeError("RUDP: error while receiving")

            rseq, rack, rflags, payload, sender_addr = pkt

            logging.warning(f"[RUDP-RECV] Received packet seq={rseq} expected_seq={self.expected_seq_num} flags={rflags} len={len(payload)}")
            # if rflags & FIN_FLAG:
            #     # remember peer address so close() later can still talk to them
            #     self.peer_addr = sender_addr
            #     # FINs consume a byte → ack next byte after FIN
            #     self._send_packet(self.seq, rseq + 1, FIN_FLAG | ACK_FLAG)
            #     logging.info("[RUDP-RECV] FIN received → FIN|ACK sent. Receiver side done.")
            #     self.closed = True
            #     return None                # receiver is finished

                

            if rflags & DATA_FLAG and rseq == self.expected_seq_num:

                self.peer_addr = sender_addr  # remember who we talk to
                self.expected_seq_num += len(payload)  # next byte we want

                # send ACK
                self._send_packet(self.seq, self.expected_seq_num, ACK_FLAG)
                logging.info(f"[RUDP-RECV] got seq={rseq} len = {len(payload)}  ACK {self.expected_seq_num} sent")
                return payload  
            
                
            
            else:
                self._send_packet(self.seq, self.expected_seq_num, ACK_FLAG)

        logging.warning("[RUDP-RECV] receive_data max retries reached without receiving expected packet.")
        return None 

    #Close Connection with FIN Exchange   
        # -----------------------------------------------------------------
    # graceful shutdown with reliable FIN exchange
    # -----------------------------------------------------------------
    def close(self, max_retries: int = RETRANSMISSIONS):
        if self.closed:
            return

        fin_seq = self.seq
        retries = 0

        while retries < max_retries:

            # ---- send FIN -------------------------------------------------
            self._send_packet(fin_seq, 0, FIN_FLAG)
            attempt_no = retries + 1
            logging.info(f"[RUDP] FIN sent (try {attempt_no}/{max_retries}) seq={fin_seq}")

            # ---------------------------------------------------------------
            pkt = self._receive_packet()

            # analyse reply -------------------------------------------------
            if pkt == "error":
                logging.error("[RUDP] socket error during close")
                break

            if pkt in ("timeout", "invalid"):
                # lost / corrupted → just loop again
                retries += 1
                continue

            rseq, rack, rflags, _payload, _addr = pkt

            # correct FIN|ACK?
            if (rflags & (FIN_FLAG | ACK_FLAG)) == (FIN_FLAG | ACK_FLAG) \
               and rack == fin_seq + 1:
                logging.info("[RUDP] FIN|ACK received – connection closed cleanly")
                break

            # bare FIN → acknowledge and wait again
            if rflags & FIN_FLAG and not (rflags & ACK_FLAG):
                self._send_packet(self.seq, rseq + 1, FIN_FLAG | ACK_FLAG)
                logging.info("[RUDP] peer sent bare FIN → FIN|ACK replied")
                retries += 1          # count this round too
                continue

            # any other packet: ignore, retry
            retries += 1

        else:
            logging.warning("[RUDP] close: retries exhausted – closing anyway")

        self.closed = True
        self.socket.close()
        logging.info("[RUDP] socket closed")

