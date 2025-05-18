import logging,os
from rudp2 import RUDPsocket
from constants import *

SERVER_ADDR = ('127.0.0.1', 50000)
ROOT = './content_rudp'

class httpserver:
    def __init__(self,loss=0,corruption=0):
       self.root = ROOT
       self._prepare_directory()
       
    def _prepare_directory(self):
        os.makedirs(self.root, exist_ok=True)
        default_files = {
            "index.html": "<html><body><h1>RUDP Server Test</h1><a href='/test.txt'>Test File</a>"
                          "<form method='POST' action='/post_test'><input type='text' name='data' value='Hello RUDP'>"
                          "<input type='submit' value='POST Test'></form></body></html>",
            "test.txt": "This is a test file for the RUDP HTTP server."
        }
        for filename, content in default_files.items():
            file_path = os.path.join(self.root, filename)
            if not os.path.exists(file_path):
                with open(file_path, 'w') as f:
                    f.write(content)

    def _get_mime_type(self, filepath):
        if filepath.endswith(".html"):
            return "text/html; charset=utf-8"
        elif filepath.endswith(".txt"):
            return "text/plain; charset=utf-8"
        return "application/octet-stream" 
    
    def _send_response(self, sock:RUDPsocket , code , message , content_type , body):
        headers = [
            f"HTTP/1.0 {code} {message}",
            "Server: RUDP-HTTP-Server/1.0",
            f"Content-Type: {content_type}",
            f"Content-Length: {len(body)}",
            "Connection: close"
        ]

        response = "\r\n".join(headers) + "\r\n\r\n"
        data = response.encode() + body

        if not sock.send_data(data):
            logging.warning(f"HTTP-Server: Failed to send response")
            return False
        
        logging.info(f"HTTP-Server: Response {code} {message} sent.")

        return True
            
    def _handle_client(self , sock:RUDPsocket , client_addr):
        try:
            raw_data=b""
            body_len=0
            buffer=b""
            
            while b"\r\n\r\n" not in buffer:
                
                seg=sock.receive_data()
                
                if not seg:
                    logging.error(f"HTTP-Server: Failed to receive headers from {client_addr}")
                    return
                buffer +=seg
            header_data, _, body_start = buffer.partition(b"\r\n\r\n")
            raw_data += header_data + b"\r\n\r\n"
            for line in header_data.decode(errors='ignore').split('\r\n'):
                if line.lower().startswith("content-length:"):
                    try:
                        body_len = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass
            req_body = body_start
            while len(req_body) < body_len:
                seg = sock.receive_data()
                if not seg:
                    logging.error(f"HTTP-Server: Failed to receive body from {client_addr}")
                    return
                req_body += seg
            request_line = raw_data.decode(errors='ignore').splitlines()[0]
            logging.info(f"HTTP-Server: Request from {client_addr}: {request_line}")

            try:
                method, path, _ = request_line.split()
            except ValueError:
                self._send_response(sock, 400, "Bad Request", "text/html", b"<h1>400 Bad Request</h1>")
                return

            if method.upper() == "GET":
                if path == "/":
                    path = "/index.html"
                file_path = os.path.normpath(os.path.join(self.root, path.lstrip('/')))
                if not file_path.startswith(os.path.normpath(self.root)) or not os.path.isfile(file_path):
                    self._send_response(sock, 404, "Not Found", "text/html", b"<h1>404 Not Found</h1>")
                else:
                    with open(file_path, 'rb') as f:
                        content = f.read()
                    self._send_response(sock, 200, "OK", self._get_mime_type(file_path), content)

            elif method.upper() == "POST":
                logging.info(f"HTTP-Server: POST to {path}, body: {req_body.decode(errors='ignore')[:100]}")
                response_body = b"<h1>POST OK</h1><p>Received your data.</p>"
                self._send_response(sock, 200, "OK", "text/html; charset=utf-8", response_body)

            else:
                self._send_response(sock, 501, "Not Implemented", "text/html", b"<h1>501 Not Implemented</h1>")

        except Exception as e:
            logging.error(f"HTTP-Server: Exception while handling client {client_addr}: {e}", exc_info=True)
            self._send_response(sock, 500, "Internal Server Error", "text/html", b"<h1>500 Error</h1>")
        finally:
            logging.info(f"HTTP-Server: Closing connection to {client_addr}")
            sock.close()
            sock.receive_data()

    def start(self):
        logging.info(f"HTTP-Server: Starting on {SERVER_ADDR[0]}:{SERVER_ADDR[1]}, serving from {os.path.abspath(self.root)}")
        server_socket = RUDPsocket(address=SERVER_ADDR)
        while True:
            try:
                client_socket = server_socket.accept()
                
                if client_socket:
                    self._handle_client(client_socket[0], client_socket[1])
                else:
                    logging.warning("HTTP-Server: Failed to accept connection.")
            except KeyboardInterrupt:
                logging.info("HTTP-Server: Shutting down...")
                # server_socket.close()
                break
            finally:
                logging.info("HTTP-Server: Listener socket closed — exiting.")
                raise SystemExit 

if __name__=="__main__":
    serv = httpserver()
    serv.start()
            
                