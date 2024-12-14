import { LoggerFactory } from "../../logger";
import { GasManager, GasCoin, GasCoinStatus } from "./gas_manager.js";
import type { TransactionGenerator } from "./types.js";

import { Logger } from "winston";
import {
  SuiClient,
  SuiTransactionBlockResponse,
  SuiTransactionBlockResponseOptions,
} from "@mysten/sui/client";
import { Ed25519Keypair } from "@mysten/sui/keypairs/ed25519";

export class Executor {
  #logger: Logger;
  #keyPair: Ed25519Keypair;
  #gasManager: GasManager;
  #gasBudgetMist: bigint;

  constructor(
    lf: LoggerFactory,
    keyPair: Ed25519Keypair,
    gasManager: GasManager,
    gasBudgetMist: bigint
  ) {
    this.#logger = lf.createLogger("executor");
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
    suiClient: SuiClient,
    txGenerator: TransactionGenerator,
    txBlockResponseOptions: SuiTransactionBlockResponseOptions
  ): Promise<SuiTransactionBlockResponse> => {
    let response: SuiTransactionBlockResponse | null = null;
    let gasCoin: GasCoin | null = null;
    let skipGasCoinUntilNextEpoch: boolean = false;

    try {
      gasCoin = this.#gasManager.getFreeGasCoin();
      this.#logger.debug(`[${requestId}] gasCoin=${gasCoin.repr()}`);

      let tx = txGenerator();
      tx.setGasPayment([gasCoin]);
      tx.setGasBudget(this.#gasBudgetMist);

      response = await suiClient.signAndExecuteTransaction({
        signer: this.#keyPair,
        transaction: tx,
        options: txBlockResponseOptions,
      });

      return response;
    } catch (error) {
      let error_ = error as any;
      let errorStr = error_.toString();

      if (
        errorStr.includes("Transaction timed out before reaching finality") ||
        errorStr.includes("equivocated until the next epoch")
      ) {
        skipGasCoinUntilNextEpoch = true;
      }

      throw error;
    } finally {
      if (gasCoin) {
        let gasCoinVersionUpdated = false;
        if (skipGasCoinUntilNextEpoch) {
          this.#logger.warn(
            `[${requestId}] Will skip using gasCoin=${gasCoin.repr()} for remainder of current epoch`
          );
          gasCoin.status = GasCoinStatus.SkipForRemainderOfEpoch;
        } else {
          if (response) {
            gasCoinVersionUpdated = this.tryUpdateGasCoinVersion(
              requestId,
              response,
              gasCoin
            );
          }
          if (!gasCoinVersionUpdated) {
            gasCoinVersionUpdated =
              await this.#gasManager.tryUpdateGasCoinVersion(
                gasCoin,
                suiClient
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
