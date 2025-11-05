class Cloid:
    def __init__(self, raw_cloid: str):
        self._raw_cloid: str = raw_cloid

    @staticmethod
    def from_int(cloid: int) -> 'Cloid':
        return Cloid(f"{cloid:#034x}")

    @staticmethod
    def from_str(cloid: str) -> 'Cloid':
        assert cloid[:2] == "0x", "cloid is not a hex string"
        assert len(cloid[2:]) == 32, "cloid is not 16 bytes"
        return Cloid(cloid)

    def to_raw(self):
        return self._raw_cloid
