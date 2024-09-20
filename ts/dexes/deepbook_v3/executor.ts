import { LoggerFactory } from "../../logger";
import { GasManager, GasCoin, GasCoinStatus } from "./gas_manager.js";
import type { TransactionGenerator } from "./types.js";

import { Logger } from "winston";
import { SuiTransactionBlockResponseOptions } from "@mysten/sui.js/client";
import { SuiClient, SuiTransactionBlockResponse } from "@mysten/sui/client";
import { Ed25519Keypair } from "@mysten/sui/keypairs/ed25519";

export class Executor {
  #logger: Logger;
  #suiClient: SuiClient;
  #keyPair: Ed25519Keypair;
  #gasManager: GasManager;
  #gasBudgetMist: bigint;

  constructor(
    lf: LoggerFactory,
    suiClient: SuiClient,
    keyPair: Ed25519Keypair,
    gasManager: GasManager,
    gasBudgetMist: bigint
  ) {
    this.#logger = lf.createLogger("executor");
    this.#suiClient = suiClient;
    this.#keyPair = keyPair;
    this.#gasManager = gasManager;
    this.#gasBudgetMist = gasBudgetMist;
  }

  tryUpdateGasCoinVersion = (
    requestId: bigint,
    response: SuiTransactionBlockResponse,
    gasCoin: GasCoin
  ): boolean => {
    if (response.effects?.gasObject && response.effects?.gasUsed) {
      const versionFromTx = BigInt(
        response.effects!.gasObject.reference.version
      );
      const digestFromTx = response.effects!.gasObject.reference.digest;

      const gasUsed =
        BigInt(response.effects!.gasUsed.computationCost) +
        BigInt(response.effects!.gasUsed.storageCost) -
        BigInt(response.effects!.gasUsed.storageRebate);

      this.#logger.info(
        `[${requestId}] gasCoin=${gasCoin.repr()} attempting to update version using tx response. NewVer=${versionFromTx}`
      );

      if (BigInt(gasCoin.version) < versionFromTx) {
        const oldVersion = gasCoin.version;
        gasCoin.version = versionFromTx.toString();
        gasCoin.digest = digestFromTx;
        gasCoin.balanceMist -= gasUsed;

        this.#logger.info(
          `[${requestId}] gasCoin=${gasCoin.repr()} updated version from tx response oldVer=${oldVersion}`
        );

        return true;
      }
    }
    return false;
  };

  execute = async (
    requestId: bigint,
    txGenerator: TransactionGenerator,
    txBlockResponseOptions: SuiTransactionBlockResponseOptions
  ): Promise<SuiTransactionBlockResponse> => {
    let response: SuiTransactionBlockResponse | null = null;
    let gasCoin: GasCoin | null = null;
    let transactionTimedOutBeforeReachingFinality: boolean = false;

    try {
      gasCoin = this.#gasManager.getFreeGasCoin();
      this.#logger.debug(`[${requestId}] gasCoin=${gasCoin.repr()}`);

      let tx = txGenerator();
      tx.setGasPayment([gasCoin]);
      tx.setGasBudget(this.#gasBudgetMist);

      response = await this.#suiClient.signAndExecuteTransaction({
        signer: this.#keyPair,
        transaction: tx,
        options: txBlockResponseOptions,
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
      if (gasCoin) {
        let gasCoinVersionUpdated = false;
        if (transactionTimedOutBeforeReachingFinality) {
          this.#logger.warn(
            `[${requestId}] Transaction timed out. Will skip using gasCoin=${gasCoin.repr()} for remainder of current epoch`
          );
          gasCoin.status = GasCoinStatus.SkipForRemainderOfEpoch;
        } else {
          if (response) {
            gasCoinVersionUpdated = this.tryUpdateGasCoinVersion(
              requestId,
              response,
              gasCoin
            );
            if (!gasCoinVersionUpdated) {
              gasCoinVersionUpdated = await gasCoin.updateInstance(
                this.#suiClient
              );
            }
          } else {
            gasCoinVersionUpdated = await gasCoin.updateInstance(
              this.#suiClient
            );
          }
          if (gasCoinVersionUpdated) {
            gasCoin.status = GasCoinStatus.Free;
          } else {
            gasCoin.status = GasCoinStatus.NeedsVersionUpdate;
          }
        }
      }
    }
  };
}
