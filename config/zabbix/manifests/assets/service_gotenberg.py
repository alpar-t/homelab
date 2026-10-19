"""Exercise Chromium with a fixed, self-contained document; retain no PDF."""

BOUNDARY = 'zabbix-gotenberg-fixed-document'
HTML = b'<!doctype html><html><head><meta charset="utf-8"><title>Monitoring</title></head><body><p>Gotenberg functional monitoring</p></body></html>'
PAYLOAD = (('--' + BOUNDARY + '\r\nContent-Disposition: form-data; name="files"; filename="index.html"\r\nContent-Type: text/html\r\n\r\n').encode()
           + HTML + ('\r\n--' + BOUNDARY + '--\r\n').encode())


def run(ctx, config):
    name = 'Gotenberg HTML to PDF'
    try:
        remaining = ctx.remaining()
        if remaining <= 0:
            return [ctx.check(name, True, 'conversion deadline exhausted')]
        response = ctx.http(
            config['url'], method='POST',
            headers={'Content-Type': 'multipart/form-data; boundary=' + BOUNDARY},
            data=PAYLOAD, timeout=min(15, remaining), max_bytes=262144,
            follow_redirects=False)
        if response.status != 200:
            return [ctx.check(name, True, 'conversion returned HTTP ' + str(response.status))]
        content_type = next((v for k, v in response.headers.items() if k.lower() == 'content-type'), '')
        body = response.body
        valid = (content_type.split(';', 1)[0].strip().lower() == 'application/pdf'
                 and 512 <= len(body) <= 262144 and body.startswith(b'%PDF-')
                 and b'%%EOF' in body[-1024:])
        return [ctx.check(name, not valid,
                          'fixed HTML converted to bounded PDF' if valid else 'conversion returned an invalid PDF')]
    except Exception:
        # HTTP/config exceptions may contain URLs or document content.
        return [ctx.check(name, True, 'conversion unavailable or response exceeded bounds')]
