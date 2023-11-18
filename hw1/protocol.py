import time
import threading
import socket
import sys


class UDPBasedProtocol:
    def __init__(self, *, local_addr, remote_addr):
        self.udp_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        self.remote_addr = remote_addr
        self.udp_socket.bind(local_addr)

    def sendto(self, data):
        return self.udp_socket.sendto(data, self.remote_addr)

    def recvfrom(self, n):
        msg, addr = self.udp_socket.recvfrom(n)
        return msg


class TCPPacket():
    header_size = 16

    def __init__(self, send_seqno, recv_ack, window_size, body):
        self.send_seqno = send_seqno
        self.recv_ack = recv_ack
        self.window_size = window_size
        self.body_len = len(body)
        self.body = body

def serialize_packet(packet):
    buf = b''
    buf += packet.send_seqno.to_bytes(4, 'big')
    buf += packet.recv_ack.to_bytes(4, 'big')
    buf += packet.window_size.to_bytes(4, 'big')
    buf += packet.body_len.to_bytes(4, 'big')
    buf += packet.body
    return buf

def deserialize_packet(buf):
    send_seqno = int.from_bytes(buf[0:4], 'big')
    recv_ack = int.from_bytes(buf[4:8], 'big')
    window_size = int.from_bytes(buf[8:12], 'big')
    body_len = int.from_bytes(buf[12:16], 'big')
    if body_len + TCPPacket.header_size != len(buf):
        raise RuntimeError(f"{body_len} + {TCPPacket.header_size} != {len(buf)}")

    return TCPPacket(send_seqno=send_seqno, recv_ack=recv_ack, window_size=window_size, body=buf[TCPPacket.header_size:])


class MyTCPProtocol(UDPBasedProtocol):
    max_packet_size = 4096
    timeout = 0.0005

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lock = threading.Lock()
        self.ready = threading.Condition(self.lock)
        self.send_buf = b''
        self.send_seqno = 0
        self.recv_buf = b''
        self.recv_seqno = 0
        self.window_size = 0
        self.udp_socket.settimeout(MyTCPProtocol.timeout)
        self.io = threading.Thread(target=self.loop)
        self.io.start()

    def send(self, data: bytes):
        with self.lock:
            self.send_buf += data

        return len(data)

    def recv(self, n: int):
        with self.lock:
            while self.recv_seqno + n > len(self.recv_buf):
                self.lock.release()
                time.sleep(MyTCPProtocol.timeout)
                self.lock.acquire()

            buf_copy = self.recv_buf[self.recv_seqno:self.recv_seqno + n]
            self.recv_seqno += n

        return buf_copy

    def loop(self):
        while True:
            with self.lock:
                if self.send_seqno < len(self.send_buf):
                    packet = TCPPacket(
                        send_seqno=self.send_seqno,
                        recv_ack=len(self.recv_buf),
                        window_size=self.window_size,
                        body=self.send_buf[self.send_seqno:self.send_seqno + MyTCPProtocol.max_packet_size],
                    )

                    self.lock.release()
                    self.sendto(serialize_packet(packet))
                    self.lock.acquire()

                try:
                    self.lock.release()
                    packet = deserialize_packet(self.recvfrom(MyTCPProtocol.max_packet_size + TCPPacket.header_size))
                    self.lock.acquire()
                except TimeoutError:
                    self.lock.acquire()
                    continue

                self.send_seqno = max(self.send_seqno, packet.recv_ack)

                if packet.body_len > 0:
                    if packet.send_seqno == len(self.recv_buf):
                        self.recv_buf += packet.body
                    elif packet.send_seqno > len(self.recv_buf):
                        with open('./log/log.txt', 'a') as f:
                            f.write('lol\n')

                        raise RuntimeError("")

                    ping = TCPPacket(
                        send_seqno=self.send_seqno,
                        recv_ack=len(self.recv_buf),
                        window_size=self.window_size,
                        body=b'',
                    )

                    self.lock.release()
                    self.sendto(serialize_packet(ping))
                    self.lock.acquire()

