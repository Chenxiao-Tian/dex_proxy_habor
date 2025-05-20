import logging
from collections import defaultdict

from pantheon import Pantheon, StandardArgParser

from whitelisting_manager_fordefi import WhitelistingManagerFordefi
from whitelisting_manager_fireblocks import WhitelistingManagerFireblocks

# run this test with command
# python -m tests.whitelisting_manager_test -c tests/whitelisting_manager_test.config.json -s
# from parent folder

class WhitelistingManagerTest:

    def __init__(self, pantheon: Pantheon):
        self.pantheon = pantheon
        self.logger = logging.getLogger('WhitelistingManagerTest')
        self.config = pantheon.config['manager']
        self.whitelist_manager = None

    async def run(self):
        if "fordefi" in self.config:
            self.whitelist_manager = WhitelistingManagerFordefi(self.pantheon, self, self.config)
        elif "fireblocks" in self.config:
            self.whitelist_manager = WhitelistingManagerFireblocks(self.pantheon, self, self.config)
        else:
            raise ValueError("Invalid config file")
        await self.whitelist_manager.start()
        self.logger.info("Whitelisting manager - started")

        while True:
            await self.pantheon.sleep(100)

    def _on_tokens_whitelist_refresh(self, tokens: dict):
        self.logger.info("_on_tokens_whitelist_refresh - called")
        for key, value in tokens.items():
            print(key, value)

    def _on_withdrawal_whitelist_refresh(self, withdrawal_address_whitelist: defaultdict):
        self.logger.info("_on_withdrawal_whitelist_refresh - called")
        for key, value in withdrawal_address_whitelist.items():
            print(key, value)

if __name__ == '__main__':
    pt = Pantheon('whitelisting-manager-test')
    parser = StandardArgParser('Whitelisting manager test')
    pt.load_args_and_config(parser)
    test = WhitelistingManagerTest(pt)
    pt.run_app(test.run())