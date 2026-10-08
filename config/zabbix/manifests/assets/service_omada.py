"""Validate the anonymous configured-controller bootstrap, without logging in."""
import json
import re


def run(ctx, config):
    name = 'Omada configured controller API'
    try:
        response = ctx.http(config['url'], timeout=min(8, ctx.remaining()),
                            max_bytes=16384)
        if response.status != 200:
            return [ctx.check(name, True, 'controller bootstrap HTTP unavailable')]
        data = json.loads(response.body)
        result = data.get('result') if isinstance(data, dict) else None
        valid = (type(data.get('errorCode')) is int and data['errorCode'] == 0
                 and isinstance(result, dict)
                 and isinstance(result.get('controllerVer'), str)
                 and re.fullmatch(r'\d+(?:\.\d+){2,3}', result['controllerVer'])
                 and str(result.get('apiVer')) == config['api_version']
                 and result.get('configured') is True
                 and result.get('registeredRoot') is True)
        return [ctx.check(name, not valid,
                          'configured controller bootstrap contract valid; device connectivity unverified'
                          if valid else 'controller bootstrap contract invalid, unconfigured or unsupported')]
    except Exception:
        return [ctx.check(name, True, 'controller bootstrap unavailable or malformed')]
