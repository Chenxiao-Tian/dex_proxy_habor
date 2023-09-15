import logging

from pantheon import Pantheon
from pyutils.exchange_apis.dex_common import RequestType, RequestStatus

from web3.exceptions import TransactionNotFound


class TransactionsStatusPoller:
    def __init__(self, pantheon: Pantheon, config, dex):
        self.pantheon = pantheon
        self.__dex = dex
        self.__logger = logging.getLogger('transactions_status_poller')

        self.__tx_hash_to_client_rid_and_request_type = {}
        self.__poll_interval_s = config['poll_interval_s']

    async def start(self):
        self.pantheon.spawn(self.__poll_tx_for_status())

    def add_for_polling(self, tx_hash: str, client_request_id: str, request_type: RequestType):
        self.__tx_hash_to_client_rid_and_request_type[tx_hash] = (
            client_request_id, request_type)

    async def poll_for_status(self, tx_hash: str):
        if tx_hash in self.__tx_hash_to_client_rid_and_request_type:
            await self.__poll_tx({tx_hash: self.__tx_hash_to_client_rid_and_request_type[tx_hash]})
        else:
            self.__logger.error(f'No request found for the tx_hash={tx_hash}')

    async def __poll_tx_for_status(self):
        self.__logger.debug(
            f'Start polling for transaction status every {self.__poll_interval_s}s')

        while True:
            self.__logger.debug('Polling status for transactions')
            await self.__poll_tx(self.__tx_hash_to_client_rid_and_request_type)
            await self.pantheon.sleep(self.__poll_interval_s)
            
    async def finalise(self, tx_hash: str, request_status: RequestStatus):
        assert request_status is not None, 'Invalid request_status provided'
        
        if tx_hash not in self.__tx_hash_to_client_rid_and_request_type:
            return
        
        client_request_id, _ = self.__tx_hash_to_client_rid_and_request_type[tx_hash]
        await self.__dex.on_request_status_update(client_request_id, request_status, None)

    async def __poll_tx(self, tx_hash_to_client_r_id_and_request_type: dict):
        for tx_hash in list(tx_hash_to_client_r_id_and_request_type.keys()):
            self.__logger.debug(f'Polling tx_hash {tx_hash}')
            client_request_id, request_type = tx_hash_to_client_r_id_and_request_type[tx_hash]
            request = self.__dex.get_request(client_request_id)
            if request is None or request.is_finalised():
                tx_hash_to_client_r_id_and_request_type.pop(tx_hash)
            else:
                try:
                    receipt = await self.__dex.get_transaction_receipt(request, tx_hash)
                    if receipt is not None:
                        self.__logger.debug(f'Polled receipt of tx_hash {tx_hash}: {receipt}')
                        
                        # No need to check receipt['status'] in case of RequestType.CANCEL because
                        # it doesn't matter whether the transaction which was used to cancel the original
                        # ORDER/TRANSFER/APPROVE/WRAP_UNWRAP request has succeeded or not, even if it has failed
                        # the nonce is used up and hence the original request by the client is cancelled now
                        if request_type == RequestType.CANCEL:
                            request_status = RequestStatus.CANCELED
                        else:
                            status = receipt['status']
                            if status == 1:
                                request_status = RequestStatus.SUCCEEDED
                            else:
                                request_status = RequestStatus.FAILED

                        await self.__dex.on_request_status_update(client_request_id, request_status, receipt)

                except Exception as e:
                    if not isinstance(e, TransactionNotFound):
                        self.__logger.exception(
                            f'Error polling tx_hash: {tx_hash} for client_request_id={client_request_id}, '
                            f'request_type={request_type}: %r', e)
