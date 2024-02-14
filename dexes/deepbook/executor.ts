import { LoggerFactory } from "./logger.js";
import {
    GasManager,
    GasCoin,
    GasCoinStatus
} from "./gas_manager.js";

import { Logger } from "winston";
import {
    SuiClient,
    SuiTransactionBlockResponse,
    SuiTransactionBlockResponseOptions
} from "@mysten/sui.js/client";
import { TransactionBlock } from "@mysten/sui.js/transactions";
import { Ed25519Keypair } from "@mysten/sui.js/keypairs/ed25519";
import { DeepBookClient } from "@mysten/deepbook";

export enum AccountCapStatus {
    Free,
    InUse
};

export class AccountCap {
    id: string;
    status: AccountCapStatus = AccountCapStatus.Free;
    client: DeepBookClient;

    constructor(id: string, suiClient: SuiClient, wallet: string) {
        this.id = id;
        this.client = new DeepBookClient(suiClient, id, wallet);
    }
};

export type TransactionBlockGenerator =
    (accountCap: AccountCap) => Promise<TransactionBlock>;

export class Executor {
    #logger: Logger;
    #suiClient: SuiClient;
    #keyPair: Ed25519Keypair;
    #gasManager: GasManager;
    #gasBudgetMist: bigint;
    #accountCaps: Array<AccountCap>;
    #nextCapIdx: number = 0;

    constructor(lf: LoggerFactory, suiClient: SuiClient, keyPair: Ed25519Keypair,
                gasManager: GasManager, gasBudgetMist: bigint, wallet: string,
                accountCapIds: Array<string>) {
        this.#logger = lf.createLogger("executor");
        this.#suiClient = suiClient;
        this.#keyPair = keyPair;
        this.#gasManager = gasManager;
        this.#gasBudgetMist = gasBudgetMist;

        this.#accountCaps = new Array<AccountCap>();
        for (let id of accountCapIds) {
            this.#accountCaps.push(new AccountCap(id, suiClient, wallet));
        }
    }

    getFreeAccountCap = (): AccountCap => {
        if (this.#accountCaps.length === 0) {
            throw new Error("No child account cap configured");
        }

        const startingIdx = this.#nextCapIdx;
        let idx = startingIdx;
        do {
            let cap = this.#accountCaps[this.#nextCapIdx];
            this.#nextCapIdx = (this.#nextCapIdx + 1) % this.#accountCaps.length;

            if (cap.status === AccountCapStatus.Free) {
                cap.status = AccountCapStatus.InUse;
                return cap;
            }
        } while (idx != startingIdx);

        throw new Error("All child account caps in use");
    }

    execute = async (txBlockGenerator: TransactionBlockGenerator
                    ,txBlockResponseOptions: SuiTransactionBlockResponseOptions):
        Promise<SuiTransactionBlockResponse> => {

        let accountCap: AccountCap | null = null;
        let gasCoin: GasCoin | null = null;

        try {
            accountCap = this.getFreeAccountCap();
            gasCoin = this.#gasManager.getFreeGasCoin();

            let txBlock = await txBlockGenerator(accountCap);
            this.#logger.debug(`gasCoin=${gasCoin.objectId}`);
            txBlock.setGasPayment([gasCoin]);
            txBlock.setGasBudget(this.#gasBudgetMist);

            return await this.#suiClient.signAndExecuteTransactionBlock({
                signer: this.#keyPair,
                transactionBlock: txBlock,
                options: txBlockResponseOptions
            });

        } finally {
            if (accountCap) {
                accountCap.status = AccountCapStatus.Free;
            }
            if (gasCoin) {
                await gasCoin.updateInstance(this.#suiClient);
                gasCoin.status = GasCoinStatus.Free;
            }
        }
    }
};
