import { LoggerFactory } from "../../logger";
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
    InUse,
    SkipForRemainderOfEpoch
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
    (accountCap: AccountCap, gasCoin: GasCoin) => Promise<TransactionBlock>;

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

        throw new Error("All child account caps in use or skipped for the current epoch");
    }

    tryUpdateGasCoinVersion = (requestId: BigInt,
                               response: SuiTransactionBlockResponse,
                               gasCoin: GasCoin): boolean => {
        if (response.effects?.gasObject && response.effects?.gasUsed) {
            const versionFromTx = BigInt(response.effects!.gasObject.reference.version);
            const digestFromTx =response.effects!.gasObject.reference.digest;

            const gasUsed = BigInt(response.effects!.gasUsed.computationCost) + BigInt(response.effects!.gasUsed.storageCost) - BigInt(response.effects!.gasUsed.storageRebate);

            this.#logger.info(`[${requestId}] gasCoin=${gasCoin.objectId} attempting to update version using tx response. oldVer=${gasCoin.version} newVer=${versionFromTx}`);

            if (gasCoin.version < versionFromTx) {
                const oldVersion = gasCoin.version;
                gasCoin.version = versionFromTx;
                gasCoin.digest = digestFromTx;
                gasCoin.balanceMist -= gasUsed;

                this.#logger.info(`[${requestId}] gasCoin=${gasCoin.objectId} updated version from tx response oldVer=${oldVersion} newVer=${gasCoin.version}, digest=${gasCoin.digest} balanceMist=${gasCoin.balanceMist}`);

                return true;
            }
        }
        return false;
    }

    execute = async (requestId: BigInt,
                     txBlockGenerator: TransactionBlockGenerator,
                     txBlockResponseOptions: SuiTransactionBlockResponseOptions):
        Promise<SuiTransactionBlockResponse> => {

        let accountCap: AccountCap | null = null;
        let gasCoin: GasCoin | null = null;
        let transactionTimedOutBeforeReachingFinality: boolean = false;
        let response: SuiTransactionBlockResponse | null = null;

        try {
            accountCap = this.getFreeAccountCap();
            gasCoin = this.#gasManager.getFreeGasCoin();

            let txBlock = await txBlockGenerator(accountCap, gasCoin);
            txBlock.setGasPayment([gasCoin]);
            txBlock.setGasBudget(this.#gasBudgetMist);

            response = await this.#suiClient.signAndExecuteTransactionBlock({
                signer: this.#keyPair,
                transactionBlock: txBlock,
                options: txBlockResponseOptions
            });

            return response;

        } catch (error) {
            let error_ = error as any;
            let errorStr = error_.toString();

            if (errorStr.includes("Transaction timed out before reaching finality")) {
                transactionTimedOutBeforeReachingFinality = true;
            }

            throw error;

        } finally {
            if (accountCap) {
                if (transactionTimedOutBeforeReachingFinality) {
                    this.#logger.warn(`[${requestId}] Transaction timed out. Will skip using accountCap=${accountCap.id} for remainder of current epoch`);
                    accountCap.status = AccountCapStatus.SkipForRemainderOfEpoch;
                } else {
                    accountCap.status = AccountCapStatus.Free;
                }
            }
            if (gasCoin) {
                if (transactionTimedOutBeforeReachingFinality) {
                    this.#logger.warn(`[${requestId}] Transaction timed out. Will skip using gasCoin=${gasCoin.objectId} for remainder of current epoch`);
                    gasCoin.status = GasCoinStatus.SkipForRemainderOfEpoch;
                } else {
                    if (response && ! this.tryUpdateGasCoinVersion(requestId, response, gasCoin)) {

                        await gasCoin.updateInstance(this.#suiClient);
                    }
                    gasCoin.status = GasCoinStatus.Free;
                }
            }
        }
    }

    onEpochChange = () => {
        for (let accountCap of this.#accountCaps) {
            if (accountCap.status == AccountCapStatus.SkipForRemainderOfEpoch) {
                this.#logger.info(`Freeing accountCap=${accountCap.id} skipped for last epoch`);
                accountCap.status = AccountCapStatus.Free;
            }
        }
    }

    logSkippedObjects = () => {
        let count: number = 0;
        for (let accountCap of this.#accountCaps) {
            if (accountCap.status == AccountCapStatus.SkipForRemainderOfEpoch) {
                this.#logger.debug(`accountCap=${accountCap.id} will be skipped for the remainder of the current epoch`);
                ++count;
            }
        }
        this.#logger.info(`Skipping ${count} accountCaps for the remainder of the current epoch`);
    }
};
