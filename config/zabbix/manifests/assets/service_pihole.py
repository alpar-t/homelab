"""Exercise each Pi-hole resolver directly without credentials or DNS libraries."""
import ipaddress
import secrets
import socket
import struct


def name_at(data, offset):
    labels, seen, end = [], set(), None
    for _ in range(128):
        if offset >= len(data) or offset in seen:
            raise ValueError('invalid DNS name')
        seen.add(offset)
        size = data[offset]
        if size & 0xc0 == 0xc0:
            if offset + 1 >= len(data):
                raise ValueError('short DNS pointer')
            if end is None:
                end = offset + 2
            offset = ((size & 63) << 8) | data[offset + 1]
        elif size & 0xc0:
            raise ValueError('invalid DNS label')
        elif size == 0:
            return '.'.join(labels).lower(), end or offset + 1
        else:
            offset += 1
            if offset + size > len(data):
                raise ValueError('short DNS label')
            labels.append(data[offset:offset + size].decode('ascii'))
            offset += size
    raise ValueError('DNS name too long')


def question(name):
    return b''.join(bytes([len(part)]) + part.encode('ascii') for part in name.split('.')) + b'\x00' + struct.pack('!HH', 1, 1)


def answers(data, ident, name):
    if len(data) < 12:
        raise ValueError('short DNS header')
    tx, flags, qd, an, ns, ar = struct.unpack('!6H', data[:12])
    if tx != ident or not flags & 0x8000 or flags & 0x7800 or qd != 1:
        raise ValueError('DNS response identity mismatch')
    qname, offset = name_at(data, 12)
    if qname != name or data[offset:offset + 4] != struct.pack('!HH', 1, 1):
        raise ValueError('DNS question mismatch')
    offset += 4
    if flags & 15:
        raise ValueError('DNS error response')
    if flags & 0x0200:
        return None
    if an + ns + ar > 256:
        raise ValueError('too many DNS records')
    records, aliases = [], {}
    for index in range(an + ns + ar):
        owner, offset = name_at(data, offset)
        if offset + 10 > len(data):
            raise ValueError('short DNS record')
        kind, cls, ttl, size = struct.unpack('!HHIH', data[offset:offset + 10])
        offset += 10
        end = offset + size
        if end > len(data):
            raise ValueError('short DNS data')
        if index < an and cls == 1:
            if kind == 1:
                if size != 4:
                    raise ValueError('invalid A record')
                records.append((owner, str(ipaddress.IPv4Address(data[offset:end]))))
            elif kind == 5:
                target, consumed = name_at(data, offset)
                if consumed != end:
                    raise ValueError('invalid CNAME')
                aliases[owner] = target
        offset = end
    if offset != len(data):
        raise ValueError('trailing DNS data')
    owners = {name}
    for _ in range(16):
        target = aliases.get(name)
        if target is None:
            break
        if target in owners:
            raise ValueError('CNAME cycle')
        owners.add(target)
        name = target
    result = [ip for owner, ip in records if owner in owners]
    if not result:
        raise ValueError('no matching A answer')
    return result


def query(ctx, host, name, tcp=False):
    ident = secrets.randbits(16)
    packet = struct.pack('!6H', ident, 0x0100, 1, 0, 0, 0) + question(name)
    # Numeric pod addresses avoid depending on the very DNS service being tested.
    family = socket.AF_INET6 if ipaddress.ip_address(host).version == 6 else socket.AF_INET
    def receive(sock, count):
        chunks = bytearray()
        while len(chunks) < count:
            sock.settimeout(min(2, ctx.remaining()))
            if not ctx.remaining():
                raise TimeoutError()
            chunk = sock.recv(count - len(chunks))
            if not chunk:
                raise ValueError('short DNS stream')
            chunks.extend(chunk)
        return bytes(chunks)
    for transport in ([True] if tcp else [False, True]):
        if ctx.remaining() <= 0:
            raise TimeoutError()
        with socket.socket(family, socket.SOCK_STREAM if transport else socket.SOCK_DGRAM) as sock:
            sock.settimeout(min(2, ctx.remaining()))
            sock.connect((host, 53))
            if transport:
                sock.sendall(struct.pack('!H', len(packet)) + packet)
                size = struct.unpack('!H', receive(sock, 2))[0]
                if not 12 <= size <= 16384:
                    raise ValueError('DNS response size exceeds bound')
                data = receive(sock, size)
            else:
                sock.send(packet)
                data = sock.recv(16385)
                if len(data) > 16384:
                    raise ValueError('DNS response size exceeds bound')
            result = answers(data, ident, name)
            if result is not None:
                return result
    raise ValueError('truncated TCP response')


def run(ctx, config):
    try:
        pods = ctx.kube.items('/api/v1/namespaces/pihole/pods')
    except Exception:
        return [ctx.check('Pi-hole ' + instance + ' DNS', True, 'instance discovery unavailable')
                for instance in config['instances']]
    output = []
    for instance in config['instances']:
        matches = [p for p in pods if p.get('metadata', {}).get('labels', {}).get('app') == 'pihole'
                   and p['metadata']['labels'].get('instance') == instance
                   and not p['metadata'].get('deletionTimestamp')]
        detail, bad = 'UDP upstream/local and TCP local DNS answers verified', False
        try:
            if len(matches) != 1:
                raise ValueError('instance unavailable')
            host = matches[0].get('status', {}).get('podIP')
            ipaddress.ip_address(host)
            external = query(ctx, host, config['upstream_name'])
            if any(not ipaddress.ip_address(ip).is_global for ip in external):
                raise ValueError('blocked upstream response')
            for tcp in (False, True):
                if query(ctx, host, config['local_name'], tcp) != [config['local_address']]:
                    raise ValueError('local DNS mismatch')
        except Exception as exc:
            bad = True
            # Never include response contents or exception messages.
            detail = 'DNS functionality unavailable: ' + type(exc).__name__
        output.append(ctx.check('Pi-hole ' + instance + ' DNS', bad, detail))
    return output
