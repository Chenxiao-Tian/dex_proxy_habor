import base64
import time
import ujson


class ParadexJWT(object):
    def __init__(self, value: str, expiration: int):
        self.value = value
        self.expiration = expiration


    @staticmethod
    def from_string(token: str):
        jwt = ParadexJWT(token, ParadexJWT.__parse_expiration(token))
        return jwt


    @staticmethod
    def __parse_expiration(token: str) -> int:
        try:
            # The payload is the part of the string b/w the first and second dots
            payload = token[token.find('.') + 1: token.rfind('.')]
            # The payload needs to be padded to make it's length a multiple of 4
            payload += '=' * ((4 - (len(payload) % 4)) % 4)
            json_payload = ujson.loads(base64.b64decode(payload).decode('utf-8'))
            expiry = json_payload["exp"]
            return expiry

        except Exception:
            # The docs mention that the jwt token will expire after 5 minutes.
            return int(time.time()) + 5 * 60
