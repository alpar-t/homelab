"""Read only Node-RED's runtime state, never flow definitions or credentials."""
import json


def run(ctx, config):
    name = 'Node-RED flow runtime'
    try:
        headers = {'Accept': 'application/json'}
        if config.get('token_key'):
            return [dict(ctx.check(name, True, 'coverage deferred: authenticated runtime access requires a separate permission review', 1), observation='deferred', notification='dashboard')]
        remaining = ctx.remaining()
        if remaining <= 0:
            return [ctx.check(name, True, 'runtime state unavailable: deadline exhausted')]
        response = ctx.http(config['url'], headers=headers, timeout=min(5, remaining),
                            max_bytes=4096, follow_redirects=False)
        if response.status != 200:
            return [ctx.check(name, True, f'runtime state unavailable: HTTP {response.status}')]
        state = json.loads(response.body)
        if not isinstance(state, dict) or state.get('state') not in ('start', 'stop', 'safe'):
            return [ctx.check(name, True, 'invalid runtime state response')]
        value = state['state']
        return [ctx.check(name, value != 'start', 'flow runtime state=' + value)]
    except Exception:
        # No exception text: HTTP/parser/credential failures can carry private data.
        return [ctx.check(name, True, 'runtime state unavailable: request, credential or parsing failure')]
