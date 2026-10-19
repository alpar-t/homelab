"""Exercise Kubernetes service records over UDP and TCP without upstream DNS."""
import ipaddress
import secrets
import socket
import struct
import time


def name_at(data, offset):
    labels, visited, end = [], set(), None
    while True:
        if offset in visited or offset >= len(data) or len(visited) >= 128:
            raise ValueError('invalid DNS name')
        visited.add(offset)
        size = data[offset]
        if size & 0xc0 == 0xc0:
            if offset + 1 >= len(data):
                raise ValueError('short DNS pointer')
            end = end or offset + 2
            offset = ((size & 63) << 8) | data[offset + 1]
            continue
        if size & 0xc0 or size > 63 or offset + 1 + size > len(data):
            raise ValueError('invalid DNS label')
        offset += 1
        if not size:
            return '.'.join(labels).lower(), end or offset
        labels.append(data[offset:offset + size].decode('ascii'))
        offset += size
        if sum(map(len, labels)) + len(labels) > 254:
            raise ValueError('long DNS name')


def validate(data, transaction, hostname, expected):
    if len(data) < 12:
        raise ValueError('short DNS reply')
    ident, flags, qd, an, ns, ar = struct.unpack('!6H', data[:12])
    if ident != transaction or flags & 0x8000 == 0 or flags & 0x7800 or flags & 0x0200 or flags & 15 or qd != 1 or an > 64 or ns + ar > 64:
        raise ValueError('invalid DNS reply header')
    question, offset = name_at(data, 12)
    if question != hostname or data[offset:offset + 4] != b'\x00\x01\x00\x01':
        raise ValueError('unexpected DNS question')
    offset += 4
    addresses = set()
    for index in range(an + ns + ar):
        owner, offset = name_at(data, offset)
        if offset + 10 > len(data):
            raise ValueError('short DNS record')
        kind, cls, ttl, size = struct.unpack('!HHIH', data[offset:offset + 10])
        offset += 10
        if offset + size > len(data):
            raise ValueError('short DNS data')
        if index < an and owner == hostname and kind == 1 and cls == 1 and size == 4:
            addresses.add(socket.inet_ntoa(data[offset:offset + size]))
        offset += size
    if offset != len(data) or addresses != {expected}:
        raise ValueError('unexpected service address')


def query(ctx, server, hostname, expected, tcp):
    transaction = secrets.randbits(16)
    question = b''.join(bytes([len(label)]) + label.encode('ascii') for label in hostname.split('.')) + b'\0\0\1\0\1'
    packet = struct.pack('!6H', transaction, 0x0100, 1, 0, 0, 0) + question
    deadline = time.monotonic() + min(1, ctx.remaining())
    def timeout(sock):
        remaining = min(ctx.remaining(), deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError()
        sock.settimeout(remaining)
    family = socket.AF_INET6 if ':' in server else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as sock:
        timeout(sock)
        sock.connect((server, 53))
        timeout(sock)
        sock.sendall(struct.pack('!H', len(packet)) + packet if tcp else packet)
        if tcp:
            def read(size):
                data = b''
                while len(data) < size:
                    timeout(sock)
                    chunk = sock.recv(size - len(data))
                    if not chunk:
                        raise ValueError('short DNS stream')
                    data += chunk
                return data
            size = struct.unpack('!H', read(2))[0]
            if not 12 <= size <= 4096:
                raise ValueError('invalid DNS frame')
            data = read(size)
        else:
            timeout(sock)
            data = sock.recv(4097)
            if len(data) > 4096:
                raise ValueError('large DNS reply')
    validate(data, transaction, hostname, expected)


def run(ctx, config):
    rows = []
    # Each Kubernetes.get has a five-second timeout. Reserve four seconds for
    # probes; never start another API request without its full timeout budget.
    try:
        records = []
        for target in config['services']:
            if ctx.remaining() < 9:
                raise TimeoutError()
            service = ctx.kube.get('/api/v1/namespaces/' + target['namespace'] + '/services/' + target['service'])
            address = str(ipaddress.IPv4Address(service['spec']['clusterIP']))
            hostname = target['service'] + '.' + target['namespace'] + '.svc.cluster.local'
            records.append((hostname, address))
        server = records[1][1]  # Actual kube-dns Service IP, not a fixed address.
    except Exception:
        return [ctx.check('CoreDNS service lookup', True, 'service metadata unavailable or deadline budget exhausted')]
    for tcp in (False, True):
        bad = False
        for hostname, address in records:
            try:
                query(ctx, server, hostname, address, tcp)
            except Exception:
                bad = True
        rows.append(ctx.check('CoreDNS ' + ('TCP' if tcp else 'UDP') + ' service lookup', bad,
                              'two service A records match Kubernetes API' if not bad else 'service DNS response invalid or unavailable'))
    return rows
