import threading
import time
import os
from rudp_socket_wait_with_assess import RUDPSocket

SERVER_ADDR = ('127.0.0.1', 5005)
INPUT_FILE = 'paradiseLostText.txt'
OUTPUT_FILE = 'test_output.txt'


def run_server():
    rudp_server = RUDPSocket()
    rudp_server.bind(SERVER_ADDR)
    conn, addr = rudp_server.accept()
    print(f"[Test Server] Accepted connection from {addr}")
    conn.receive_data()
    print(f"[Test Server] File received and saved as '{OUTPUT_FILE}'")

def run_client():
    time.sleep(1)  # Ensure server is ready
    rudp_client = RUDPSocket()
    rudp_client.connect(SERVER_ADDR)
    # rudp_client.assess_file(INPUT_FILE)
    # rudp_client.send_file(INPUT_FILE)
    rudp_client.send_data(b'Hello, Server! This is a test message.')
    print(f"[Test Client] File '{INPUT_FILE}' sent to server.")

def main():
    print("[Test] Creating test file...")
    

    print("[Test] Starting RUDP server and client threads...")
    server_thread = threading.Thread(target=run_server)
    client_thread = threading.Thread(target=run_client)

    server_thread.start()
    client_thread.start()

    client_thread.join()
    server_thread.join()

    # Verify content
    with open(INPUT_FILE, 'r') as f1, open(OUTPUT_FILE, 'r') as f2:
        input_data = f1.read()
        output_data = f2.read()
        if input_data == output_data:
            print("[Test] ✅ File transfer successful. Data matches.")
        else:
            print("[Test] ❌ File transfer failed. Data mismatch.")

    # Clean up
    # os.remove(INPUT_FILE)
    # os.remove(OUTPUT_FILE)

if __name__ == "__main__":
    main()
