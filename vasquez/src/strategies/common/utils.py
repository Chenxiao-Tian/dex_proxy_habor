from common.types import Ccy


def get_base_and_quote(symbol: str) -> tuple[Ccy, Ccy]:
    # type | symbol | expiry
    _, pair = symbol.split("-")
    base, quote = pair.split("/")
    return Ccy(base), Ccy(quote)
