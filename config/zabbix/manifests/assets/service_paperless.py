"""Read-only Paperless database/auth and Redis protocol checks."""
import json
import socket


def documents(ctx, config):
    try:
        token = ctx.secret(config["token_key"])
        response = ctx.http(config["documents_url"], headers={"Authorization": "Token " + token,
                            "Accept": "application/json"},
                            timeout=min(8, ctx.remaining()), max_bytes=16384)
        if response.status != 200:
            return ctx.check("Paperless document API", True, "document query rejected; HTTP " + str(response.status))
        value = json.loads(response.body)
        valid = (isinstance(value, dict) and type(value.get("count")) is int and value["count"] >= 0
                 and isinstance(value.get("results"), list) and len(value["results"]) <= 1
                 and all(isinstance(row, dict) and set(row) == {"id"} and type(row["id"]) is int
                         and row["id"] > 0 for row in value["results"])
                 and len(value["results"]) == min(value["count"], 1))
        return ctx.check("Paperless document API", not valid,
                         "authenticated bounded database query succeeded" if valid else "invalid field-limited document response")
    except Exception:
        return ctx.check("Paperless document API", True, "document API unavailable; check dedicated credential and connectivity")


def redis(ctx, config):
    try:
        timeout = min(4, ctx.remaining())
        if timeout <= 0:
            raise TimeoutError()
        with socket.create_connection((config["redis_host"], config["redis_port"]), timeout=timeout) as connection:
            connection.settimeout(min(4, ctx.remaining()))
            connection.sendall(b"*1\r\n$4\r\nPING\r\n")
            reply = b""
            while len(reply) < 64 and not reply.endswith(b"\r\n"):
                remaining = ctx.remaining()
                if remaining <= 0:
                    raise TimeoutError()
                connection.settimeout(min(4, remaining))
                part = connection.recv(64 - len(reply))
                if not part:
                    break
                reply += part
        valid = reply == b"+PONG\r\n"
        return ctx.check("Paperless Redis protocol", not valid,
                         "Redis PING succeeded" if valid else "Redis did not return PONG")
    except Exception:
        return ctx.check("Paperless Redis protocol", True, "Redis protocol unavailable")


def run(ctx, config):
    return [documents(ctx, config), redis(ctx, config)]
