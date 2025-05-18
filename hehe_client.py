import logging,os
from rudp2 import RUDPsocket
from constants import *
SERVER_ADDR = ('127.0.0.1', 50000)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - HTTP-client - %(message)s')

class httpclient():
    def __init__(self):
        pass
    
    def _connect_socket(self,loss,corrupt):
        self.socket=RUDPsocket(loss_rate = loss , corp_rate = corrupt)
        self.socket.connect(server_addr=SERVER_ADDR)
        
        logging.info(f"Attempting RUDP connect to {SERVER_ADDR[0]}:{SERVER_ADDR[1]}...")
        return True
    
    def _send_http_request(self,method,path,body_str=None):
        headers = [
            f"{method.upper()} {path} HTTP/1.0",
            f"Host: {SERVER_ADDR[0]}:{SERVER_ADDR[1]}",
            "Connection: close",
            "User-Agent: RUDP-HTTP-Client/Project"
        ]

        body_bytes = b""
        if method.upper() == "POST" and body_str:
            body_bytes = body_str.encode('utf-8')
            headers.append("Content-Type: application/x-www-form-urlencoded")
            headers.append(f"Content-Length: {len(body_bytes)}")

        req_str = "\r\n".join(headers) + "\r\n\r\n"
        full_req = req_str.encode('utf-8') + body_bytes
        logging.info(f"Sending request ({len(full_req)} bytes): {req_str.splitlines()[0]} ...")
        
        self.socket.send_data(full_req)
        logging.info("Full request sent.")
        return True
    
    def _receive_http_response(self):

        resp_bytes = b""
        headers_done = False
        body_len = -1
        temp_buf = b""
        initial_body = b""

        while not headers_done:

            seg = self.socket.receive_data()
            
            if seg is None or not seg:
                logging.error("Failed to get headers.")
                # self.socket.close()
                return None

            temp_buf += seg
            if b"\r\n\r\n" in temp_buf:
                headers_done = True
                header_part, _, initial_body = temp_buf.partition(b"\r\n\r\n")
                resp_bytes = header_part + b"\r\n\r\n"

                for line in header_part.decode('utf-8', 'ignore').split('\r\n'):
                    if line.lower().startswith('content-length:'):
                        try:
                            body_len = int(line.split(':', 1)[1].strip())
                        except:
                            break
                break
    
        if not resp_bytes and not initial_body:
            logging.error("No response headers.")
            # self.socket.close()
            return None
        current_body = initial_body
        if body_len != -1:
            while len(current_body) < body_len:
                seg = self.socket.receive_data()
                if seg is None or not seg:
                    logging.warning("Connection issue getting body (known len).")
                    break
                current_body += seg
        else:
            while True:
                seg = self.socket.receive_data()
                if seg is None:
                    logging.warning("Timeout getting body (unknown len).")
                    break
                if not seg:
                    logging.info("Server closed connection (end of body).")
                    break
                current_body += seg

        resp_bytes += current_body
        logging.info(f"Response received ({len(resp_bytes)} bytes).")

        print("\n--- SERVER RESPONSE ---")
        try:
            print(resp_bytes.decode('utf-8', errors='replace'))
        except:
            print(resp_bytes)
        print("--- END OF RESPONSE ---\n")

        self.socket.close()
        logging.info("RUDP connection closed.")
        return resp_bytes
    
    def send_request(self, method, path, body_str=None, loss=0.0, corrupt=0.0):
        if not self._connect_socket(loss, corrupt):
            return None
        if not self._send_http_request(method, path, body_str):
            return None
        return self._receive_http_response()
    
def main():
    test_cases = [
        ("GET", "/index.html", None, 0.2, 0.0),     #0.3 for loss is good
        ("GET", "/test.txt", None, 0.0, 0.0),
        ("GET", "/h ", None, 0.0, 0.0),
        ("POST", "/ay7aga", "bla=blah", 0.0, 0.0),
        ("GET", "/index.html", None, 0.0, 0.3),
        ("GET", "/index.html", None, 0.3, 0.0),
        ("GET", "/index.html", None, 0.2, 0.3),
    ]

    for i, (method, path, body, loss, corrupt) in enumerate(test_cases):
        logging.info(f"\n\n--- Test Case {i + 1} ---")
        logging.info(f"Requesting {method} {path} from {SERVER_ADDR[0]}:{SERVER_ADDR[1]} "
                     f"(Loss = {loss*100:.0f}%, Corruption = {corrupt*100:.0f}%)")
        if body:
            logging.info(f"Body: {body[:100]}...")

        client = httpclient()
        client.send_request(method, path, body_str = body, loss = loss, corrupt = corrupt)
        # client.socket.close()
        try:
            input("Press Enter to continue to the next test case...")
        except KeyboardInterrupt:
            logging.info(f"\nmonkeygang on top")
            raise SystemExit
            
        

if __name__ == "__main__":
    main()