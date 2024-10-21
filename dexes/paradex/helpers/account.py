from typing import List, Optional

from starknet_py.net.account.account import Account as StarknetAccount
from starknet_py.net.client import Client
from starknet_py.net.models import AddressRepresentation, StarknetChainId
from starknet_py.net.signer import BaseSigner
from starknet_py.net.signer.stark_curve_signer import KeyPair
from starknet_py.utils.typed_data import TypedData as TypedDataDataclass


from .typed_data import TypedData

import libsigner

import libsigner


class Account(StarknetAccount):
    def __init__(
        self,
        *,
        address: AddressRepresentation,
        client: Client,
        signer: Optional[BaseSigner] = None,
        key_pair: Optional[KeyPair] = None,
        chain: Optional[StarknetChainId] = None,
    ):
        super().__init__(
            address=address, client=client, signer=signer, key_pair=key_pair, chain=chain
        )
        self._private_key = key_pair.private_key

    def sign_message(self, typed_data: TypedData) -> List[int]:
        if typed_data['primaryType'] == "Order":
            msg = typed_data['message']
            r, s = libsigner.sign_order_message(
                private_key=hex(self._private_key),
                address=hex(self.address),
                chain_id=hex(self._chain_id),
                market=msg['market'],
                side="BUY" if msg['side'] == 1 else "SELL",
                type=msg['orderType'],
                size=hex(int(msg['size'])),
                price=hex(int(msg['price'])),
                timestamp_ms=int(msg['timestamp'])
            )
            return [int(r, 16), int(s, 16)]

        typed_data_dataclass = TypedDataDataclass.from_dict(typed_data)
        msg_hash = typed_data_dataclass.message_hash(self.address)
        r, s = libsigner.sign_message_hash(message_hash=hex(msg_hash), private_key=hex(self.signer.key_pair.private_key))
        return [int(r, 16), int(s, 16)]
