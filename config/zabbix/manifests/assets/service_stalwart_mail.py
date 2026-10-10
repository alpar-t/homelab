"""Anonymous bounded SMTP and IMAP negotiations; never access mail or authenticate."""
import socket
import ssl
import time


class ProtocolError(Exception):
    pass


class Session:
    def __init__(self, ctx, endpoint):
        self.ctx = ctx
        self.end = time.monotonic() + min(5, ctx.remaining())
        self.sock = socket.create_connection((endpoint['host'], endpoint['port']), self.timeout())
        self.buffer = b''
        self.bytes = 0

    def timeout(self):
        remaining = min(self.end - time.monotonic(), self.ctx.remaining())
        if remaining <= 0:
            raise TimeoutError()
        return remaining

    def send(self, command):
        self.sock.settimeout(self.timeout())
        self.sock.sendall(command)

    def line(self):
        while b'\r\n' not in self.buffer:
            self.sock.settimeout(self.timeout())
            data = self.sock.recv(1024)
            self.bytes += len(data)
            if not data or self.bytes > 16384 or len(self.buffer) + len(data) > 4096:
                raise ProtocolError()
            self.buffer += data
        line, self.buffer = self.buffer.split(b'\r\n', 1)
        return line

    def tls(self, endpoint):
        if self.buffer:
            raise ProtocolError()
        context = ssl.create_default_context()
        if endpoint.get('ca_key'):
            # A missing private trust anchor is an actionable rollout failure.
            context.load_verify_locations(cadata=self.ctx.secret(endpoint['ca_key']))
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.sock.settimeout(self.timeout())
        self.sock = context.wrap_socket(self.sock, server_hostname=endpoint['server_name'])

    def smtp_reply(self, code):
        lines = []
        for _ in range(40):
            line = self.line()
            if len(line) < 4 or line[:3] != str(code).encode() or line[3:4] not in (b'-', b' '):
                raise ProtocolError()
            lines.append(line[4:])
            if line[3:4] == b' ':
                return lines
        raise ProtocolError()

    def ehlo(self):
        self.send(b'EHLO monitor.invalid\r\n')
        lines = self.smtp_reply(250)
        if not lines or not lines[0]:
            raise ProtocolError()
        return {line.split()[0].upper() for line in lines[1:] if line.split()}

    def smtp(self, endpoint):
        self.smtp_reply(220)
        capabilities = self.ehlo()
        if endpoint['tls'] == 'starttls':
            if b'STARTTLS' not in capabilities:
                raise ProtocolError()
            self.send(b'STARTTLS\r\n')
            self.smtp_reply(220)
            self.tls(endpoint)
            self.ehlo()  # RFC 3207 requires fresh capabilities after TLS.
        self.send(b'QUIT\r\n')
        self.smtp_reply(221)

    def imap(self):
        greeting = self.line().upper()
        if not greeting.startswith(b'* OK '):
            raise ProtocolError()
        self.send(b'M1 CAPABILITY\r\n')
        capabilities = set()
        for _ in range(40):
            line = self.line().upper()
            if line.startswith(b'* CAPABILITY '):
                capabilities.update(line.split()[2:])
            elif line.startswith(b'M1 '):
                if not line.startswith(b'M1 OK ') or not capabilities.intersection({b'IMAP4REV1', b'IMAP4REV2'}):
                    raise ProtocolError()
                return
            elif not line.startswith(b'* '):
                raise ProtocolError()
        raise ProtocolError()


def probe(ctx, endpoint):
    session = Session(ctx, endpoint)
    try:
        if endpoint['tls'] == 'implicit':
            session.tls(endpoint)
        if endpoint['protocol'] == 'smtp':
            session.smtp(endpoint)
        else:
            session.imap()
    finally:
        session.sock.close()


def run(ctx, config):
    records = []
    for endpoint in config['endpoints']:
        if endpoint['tls'] != 'none' and endpoint.get('ca_key'):
            try:
                ctx.secret(endpoint['ca_key'])
            except Exception:
                records.append(dict(ctx.check(endpoint['name'], True,
                    'coverage deferred: approved local public TLS trust anchor unavailable', severity=1),
                    observation='deferred', notification='dashboard'))
                continue
        try:
            probe(ctx, endpoint)
            detail = 'anonymous protocol negotiation succeeded'
            if endpoint['tls'] != 'none':
                detail += '; TLS certificate and hostname verified'
            bad = False
        except ssl.SSLCertVerificationError:
            bad, detail = True, 'TLS certificate identity or trust validation failed'
        except (TimeoutError, socket.timeout):
            bad, detail = True, 'bounded protocol negotiation timed out'
        except ProtocolError:
            bad, detail = True, 'mail protocol greeting, capability or completion invalid'
        except Exception:
            bad, detail = True, 'protocol unavailable; check connectivity and configured TLS trust anchor'
        records.append(ctx.check(endpoint['name'], bad, detail))
    return records
