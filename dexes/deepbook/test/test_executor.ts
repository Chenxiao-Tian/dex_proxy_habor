import { LoggerFactory } from "../logger.js";
import { GasManager } from "../gas_manager.js";
import { Executor } from "../executor.js";

import { SuiClient } from "@mysten/sui.js/client";
import { Ed25519Keypair } from "@mysten/sui.js/keypairs/ed25519";
import { fromHEX } from "@mysten/sui.js/utils";

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
    let logger = lf.createLogger("test_executor");

    let suiClient = new SuiClient({
        url: "https://mysten-rpc.testnet.sui.io:443"
    });

    const secretKey = readPrivateKey();
    let keyPair = Ed25519Keypair.fromSecretKey(fromHEX(secretKey));
    const wallet = keyPair.getPublicKey().toSuiAddress();
    const expectedCount = 4;
    const balancePerInstance = BigInt(1_000_000_000); // 1 SUI
    const minBalancePerInstance = BigInt(100_000_000); // 0.1 SUI
    const gasBudget = BigInt(1_000_000); // 0.01 SUI
    const topupIntervalMs = 30_000; // 30 seconds
    let gasMgr = new GasManager(lf, suiClient, wallet, keyPair, expectedCount,
                                balancePerInstance, minBalancePerInstance,
                                topupIntervalMs);
    await gasMgr.start();

    let serializer = (_: any, value: any) => {
        return (typeof value === "bigint") ? value.toString() : value;
    };

    const accountCapIds = new Array<string>(
        "0x2605db4d2e7028c8679fcc006fe2c247f51006f900c3881103303475343adff2",
        "0x1087331ff37a00ec630f24eb8612f8c701cecda9298f7686bd8ca95212f5a5c7",
        "0x0cc98ca37176afff5c8265f988382132828ef9dc13f9545047047b168a8f9ca7",
        "0x7bb93fe4894260d11ad8dd8549d8b0a39d1fe2d8315d2d542d378284a04aff18"
    );

    let executor = new Executor(lf, suiClient, keyPair, gasMgr, gasBudget, wallet,
                                accountCapIds);

    for (let i = 0; i < accountCapIds.length; ++i) {
        let coin = executor.getFreeAccountCap();
        logger.info(JSON.stringify(coin, null, 2));
    }

    try {
        logger.info(JSON.stringify(executor.getFreeAccountCap(), null, 2));
    } catch (error) {
        logger.error(error);
    }
}

await main();
