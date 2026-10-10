"""Paperless Redis protocol evidence; document authentication stays deferred."""
import socket


def documents(ctx, config):
    # view_document exposes ownerless documents; an ID-only query does not scope a stolen token.
    return dict(ctx.check("Paperless document API", True,
        "coverage deferred: native document token can read ownerless household documents; no token is mounted", 1),
        observation="deferred", notification="dashboard")


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
