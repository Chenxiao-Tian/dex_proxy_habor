import logging

logger = logging.getLogger('dex_common.web_server.utils')


def json_type_formatter(obj) -> str:
    """
    Custom JSON encoder to handle non-serializable types.
    """
    if isinstance(obj, bytes):
        return '0x' + obj.hex()
    logger.warning('Non-serializable type encountered: %s: %s', type(obj), obj)
    return str(obj)
