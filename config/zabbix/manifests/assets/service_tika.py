"""Exercise both Tika text parsers using a fixed, disposable memory payload."""

PAYLOAD = b'HomePBP functional monitoring text extraction 7319.\n'


def run(ctx, config):
    records = []
    for instance in config['instances']:
        name = 'Tika ' + instance['name'] + ' text extraction'
        try:
            response = ctx.http(
                instance['url'], method='PUT',
                headers={'Content-Type': 'text/plain; charset=UTF-8',
                         'Accept': 'text/plain'}, data=PAYLOAD,
                timeout=min(8, ctx.remaining()), max_bytes=4096)
            content_type = next((v for k, v in response.headers.items()
                                 if k.lower() == 'content-type'), '')
            if response.status != 200:
                bad, detail = True, 'text extraction returned HTTP %d' % response.status
            elif content_type.split(';', 1)[0].strip().lower() != 'text/plain':
                bad, detail = True, 'text extraction returned unexpected content type'
            elif response.body.decode('utf-8').strip() != PAYLOAD.decode('utf-8').strip():
                bad, detail = True, 'extracted text does not match fixed input'
            else:
                bad, detail = False, 'fixed text extracted successfully'
        except Exception:
            bad, detail = True, 'text extraction unavailable or invalid response'
        records.append(ctx.check(name, bad, detail))
    return records
