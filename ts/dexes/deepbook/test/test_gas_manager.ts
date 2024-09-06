import { LoggerFactory } from "../../../logger";
import { GasManager, GasCoin, GasCoinStatus } from "../gas_manager.js";
import { SuiClient } from "@mysten/sui.js/client";
import { Ed25519Keypair } from "@mysten/sui.js/keypairs/ed25519";
import { fromHEX } from "@mysten/sui.js/utils";
import { TransactionBlock } from "@mysten/sui.js/transactions";

import { readFileSync } from "fs";

let readPrivateKey = (): string => {
    const keyStoreFilePath: string = "./test/wallet_1.txt";
    return readFileSync(keyStoreFilePath, "utf8").trimEnd();
}

let main = async () => {
    const logConfig = {
        logging: {
            level: "debug"
        }
    };
    let lf = new LoggerFactory(logConfig);
    let logger = lf.createLogger("test_gas_mgr");

    let suiClient = new SuiClient({
        url: "https://mysten-rpc.testnet.sui.io:443"
    });

    const secretKey = readPrivateKey();
    let keyPair = Ed25519Keypair.fromSecretKey(fromHEX(secretKey));
    const wallet = keyPair.getPublicKey().toSuiAddress();
    const expectedCount = 6;
    const balancePerInstance = BigInt(1_000_000_000); // 1 SUI
    const minBalancePerInstance = BigInt(100_000_000); // 0.1 SUI
    const topupIntervalMs = 10_000; // 10 seconds
    let gasMgr = new GasManager(lf, suiClient, wallet, keyPair, expectedCount,
                                balancePerInstance, minBalancePerInstance,
                                topupIntervalMs);
    await gasMgr.start();

    let serializer = (_: any, value: any) => {
        return (typeof value === "bigint") ? value.toString() : value;
    };

    let i = 0;
    let coinsToFree = new Array<GasCoin>();
    for (;i < expectedCount; ++i) {
        coinsToFree.push(gasMgr.getFreeGasCoin());
        logger.info(`[${i + 1}] coin=${coinsToFree[i].objectId} balanceMist=${coinsToFree[i].balanceMist.toString()}`);
    }

    try {
        let coin = gasMgr.getFreeGasCoin();
        logger.info(`[${i + 1}] coin=${coin.objectId} balanceMist=${coin.balanceMist.toString()}`);
    } catch (error) {
        logger.error(error);
    }

    for (let coin of coinsToFree) {
        coin.status = GasCoinStatus.Free;
    }

    logger.info("Splitting the mainGasCoin for testing");
    let mainGasCoin = await gasMgr.getMainGasCoin();
    if (mainGasCoin !== null) {
        logger.info(`mainGasCoin=${mainGasCoin.objectId} version=${mainGasCoin.version}`);
        try {
            let txBlock = new TransactionBlock();
            let coin = txBlock.splitCoins(txBlock.gas, [1_000_000_000]);
            txBlock.transferObjects([coin], wallet);
            txBlock.setGasPayment([mainGasCoin]);

            let response = await suiClient.signAndExecuteTransactionBlock({
                signer: keyPair,
                transactionBlock: txBlock,
                options: { showEffects: true }
            });

            logger.info(`split mainGasCoin=${mainGasCoin.objectId} digest=${response.digest} status=${response.effects?.status.status}`);
        } finally {
            mainGasCoin.updateInstance(suiClient);
            mainGasCoin.status = GasCoinStatus.Free;
        }
    } else {
        logger.info("Failed to fetch mainGasCoin");
    }
}

await main();
