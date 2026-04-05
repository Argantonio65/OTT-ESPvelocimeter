import socket

TCP_IP = "0.0.0.0"  # Listen on all available interfaces
TCP_PORT = 8080
BUFFER_SIZE = 1024

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind((TCP_IP, TCP_PORT))
s.listen(1)

print("Server started, waiting for connections...")
while True:
    conn, addr = s.accept()
    print(f"Connection from {addr}")
    data = conn.recv(BUFFER_SIZE)
    if data:
        print(f"Received data: {data.decode()}")
    conn.close()
