import { LoggerFactory } from "../../logger.js";
import {
    WebServer,
    RestResult,
    RestRequestHandler
} from "../../web_server.js";

import { DexProxy } from "../../dex_proxy.js";
import {
    OrderCache
} from "../../order_cache.js";

import { readFileSync } from "fs";
import { dirname } from "path";
import { Logger } from "winston";
import {DexInterface} from "../../types.js";
import {ChainInfo, TokenInfo} from "./types";
import { assertFields } from "../../utils.js";
import { ethers } from 'ethers';
import {InstrumentModel, SynFuturesV3, PERP_EXPIRY} from '@synfutures/oyster-sdk';
import { BigNumber } from 'ethers';
import {TransactionResponse} from "@ethersproject/abstract-provider";


export type Mode = "read-only" | "read-write";

class MandatoryFields {
    static DepositRequest = ["symbol", "quantity"];
    static WithdrawRequest = ["symbol", "quantity"];
}

export class Synfutures implements DexInterface {
    private logger: Logger;
    private config: any;
    private server: WebServer;
    private mode: Mode;
    private dexProxy: DexProxy;
    private logResponses: boolean;
    private signer: ethers.Wallet | null;
    private sdk: SynFuturesV3;

    private orderCache: OrderCache;
    private l1RpcProvider: string;
    private l2RpcProvider: string;
    private walletAddress: string;
    private erc20Abi: any;

    private resourceName: string;
    private l1Details: ChainInfo | null;
    private l2Details: ChainInfo | null;

    public channels: Array<string> = ["ORDER", "TRADE"];

    constructor(lf: LoggerFactory, server: WebServer, config: any, mode: Mode,
                dexProxy: DexProxy) {
        this.logger = lf.createLogger("synfutures");
        this.config = config;
        this.server = server;
        this.signer = null;
        this.dexProxy = dexProxy;
        this.erc20Abi = this.getErc20Abi();

        if (config.dex === undefined) {
            throw new Error("A section corresponding to `dex` must be present in the config");
        }

        this.orderCache = new OrderCache(lf, config.dex.order_cache);
        this.mode = mode;
        this.logger.info(`mode=${mode}`);

        this.logResponses = false;
        if (config.dex.log_responses != undefined) {
            this.logResponses = config.dex.log_responses;
        }

        if (this.mode == "read-write") {
            const secretKey = this.readPrivateKey();
            this.signer = new ethers.Wallet(secretKey);
            this.walletAddress = this.signer.address;
        } else {
            if (config.dex.wallet_address === undefined) {
                throw new Error("The key, `dex.wallet_address` must be present in the config");
            }
            this.walletAddress = config.dex.wallet_address
        }

        this.logger.info(`wallet=${this.walletAddress}`);

        this.resourceName = config.dex.resource_name;
        this.l1RpcProvider = config.dex.l1_rpc_provider;
        this.l2RpcProvider = config.dex.l2_rpc_provider;

        this.l1Details = null;
        this.l2Details = null;

        if (mode === "read-write") {
            if (this.resourceName === undefined) {
                throw new Error("The key `dex.resource_name` must be present in the config");
            }
            this.fetchWithdrawalAddresses();
        }

        this.logger.info(`L1 RPC node rest api url=${this.l1RpcProvider }`);
        this.logger.info(`L2 RPC node rest api url=${this.l2RpcProvider}`);

        this.sdk = SynFuturesV3.getInstance('blast');
        this.sdk.ctx.setProvider(new ethers.providers.JsonRpcProvider(this.l2RpcProvider));

        this.registerEndpoints();
    }

    fetchWithdrawalAddresses = (): void => {
        const filePrefix = dirname(process.argv[1]);
        const filename = `${filePrefix}/../../resources/synfutures_withdrawal_addresses.json`;
        try {
            let contents = JSON.parse(readFileSync(filename, "utf8"));
            this.logger.info(`Looking up configured withdrawal addresses for chainName=${this.resourceName} from ${filename}`);
            let resourceDetails = contents[this.resourceName];
            this.l1Details = this.loadChainDetails(resourceDetails.L1.tokens, resourceDetails.L1.bridge_address)
            this.l2Details = this.loadChainDetails(resourceDetails.L2.tokens, resourceDetails.L2.bridge_address)
        } catch (error) {
            const msg = `Failed to parse withdrawal addresses from ${filename}`;
            this.logger.error(msg);
            throw new Error(msg);
        }
    }

    loadChainDetails = (tokensDict: any, bridge_address: string): ChainInfo => {
        let tokens = new Map<string, TokenInfo>();

        for (let t of tokensDict) {
            tokens.set(t.symbol, {
                symbol: t.symbol,
                address: t.address,
                validWithdrawalAddresses: new Set<string>(t.valid_withdrawal_addresses)
            });
        }

        return {
                tokens: tokens,
                bridge_address: bridge_address
            }
    }

    registerEndpoints = () => {
        const GET = (path: string, handler: RestRequestHandler) => {
            this.server.register("GET", path, handler);
        };
        const POST = (path: string, handler: RestRequestHandler) => {
            if (this.mode === "read-write") {
                this.server.register("POST", path, handler);
            }
        };
        const DELETE = (path: string, handler: RestRequestHandler) => {
            if (this.mode === "read-write") {
                this.server.register("DELETE", path, handler);
            }
        };

        GET("/", async (path, params, receivedAtMs) => {
            return {statusCode: 200, payload: {"result": "Synfutures API"}};
        });
        GET("/status", this.getStatus);
        GET("/instruments", this.getInstruments);
        GET("/account-info", this.getAccountInfo);
        POST("/withdraw", this.withdraw);
        POST("/deposit-into-l2", this.depositIntoL2);
        POST("/withdraw-from-l2", this.withdrawFromL2);
        POST("/deposit-into-exchange", this.depositIntoExchange);
        POST("/withdraw-from-exchange", this.withdrawFromExchange);
    }

    start = async () => {
        // TODO
        await this.server.start();
    }

    getStatus = async (requestId: bigint,
                       path: string,
                       params: any,
                       receivedAtMs: number): Promise<RestResult> => {
        this.logger.debug(`[${requestId}] Handling ${path} request`);

        return {
            statusCode: 200,
            payload: {
                status: "ok"
            }
        }
    }

    getInstruments = async (requestId: bigint,
                        path: string,
                        params: any,
                        receivedAtMs: number): Promise<RestResult> => {
        this.logger.debug(`[${requestId}] Querying all instruments`);
        const instResponse = await this.sdk.getAllInstruments();

        let jsonString = JSON.stringify(instResponse, this.replaceBigNumber);

        return {
            statusCode: 200,
            payload: JSON.parse(jsonString)
        };
    }

    getAccountInfo = async (requestId: bigint,
                        path: string,
                        params: any,
                        receivedAtMs: number): Promise<RestResult> => {
        this.logger.debug(`[${requestId}] Querying account info`);
        const symbol = params.get("symbol");

        const instResponse = await this.sdk.getAllInstruments();

        const instrument = this.getInstrument(instResponse, symbol);

        const accountResponse = await this.sdk.getPairLevelAccount(this.walletAddress, instrument.info.addr, PERP_EXPIRY);

        let jsonString = JSON.stringify(accountResponse, this.replaceBigNumber)

        return {
            statusCode: 200,
            payload: JSON.parse(jsonString)
        };
    }

    canWithdraw = (symbol: string, withdrawalAddress: string): boolean => {
        let tokenInfo = this.l1Details?.tokens.get(symbol);
        if (tokenInfo === undefined) {
            this.logger.error(`No entry for symbol=${symbol} in the withdrawal addresses file`);
            return false;
        }

        return tokenInfo.validWithdrawalAddresses.has(withdrawalAddress)
    }

    withdraw = async (requestId: bigint,
                  path: string,
                  params: any,
                  receivedAtMs: number): Promise<RestResult> => {
        if (this.signer === undefined) {
            throw new Error("Proxy is in read-only mode");
        }

        assertFields(params, MandatoryFields.WithdrawRequest);

        const symbol: string = params["symbol"];
        const quantity: string = params["quantity"];
        const recipient: string = params["recipient"];

        this.logger.debug(`[${requestId}] Handling withdraw request. params=${JSON.stringify(params)}`);

        let tokenInfo = this.l1Details?.tokens.get(symbol);

        if (tokenInfo === undefined) {
            throw new Error(`Symbol ${symbol} has not been configured`);
        }

        if (! this.canWithdraw(symbol, recipient)) {
            const msg = `Cannot withdraw symbol=${symbol} to address=${recipient}. Please check the valid_addresses file`
            this.logger.error(`Alert: ${msg}`);
            throw new Error(msg);
        }

        let response = null;
        let status: string | undefined = undefined;
        try {
            const provider = new ethers.providers.JsonRpcProvider(this.l1RpcProvider);
            const wallet = this.signer!.connect(provider);

            if (symbol == "ETH") {
                const tx = {
                    to: recipient,
                    value: ethers.utils.parseEther(quantity)
                };

                response = await wallet.sendTransaction(tx);
                await response.wait();
            }
            else {
                const tokenContract = new ethers.Contract(tokenInfo.address, this.erc20Abi, provider);
                const amount = ethers.utils.parseUnits(quantity, tokenContract.decimals());
                const data = tokenContract.interface.encodeFunctionData("transfer", [recipient, amount] );
                const tx = {
                    to: recipient,
                    value: ethers.utils.parseUnits("0.000", "ether"),
                    data: data
                };

                response =  await wallet.sendTransaction(tx);
                await response.wait();
            }

        } catch (error) {
            this.logger.error(`[${requestId}] ${error}`);
            throw error;
        }

        const txid = response.hash;

        status = txid === undefined ? "failed" : "success";

        if (status === "success") {
            this.logger.info(`[${requestId}] Successfully deposited ${quantity}. Txid=${txid}`);
        } else {
            this.logger.error(`[${requestId}] Failed to deposit ${quantity}. Txid=${txid}`);
        }

        return {
            statusCode: (status === "success") ? 200 : 400,
            payload: response
        }
    }

    depositIntoL2 = async (requestId: bigint,
                             path: string,
                             params: any,
                             receivedAtMs: number): Promise<RestResult> => {
        if (this.signer === undefined) {
            throw new Error("Proxy is in read-only mode");
        }

        if (this.l1Details === undefined) {
            throw new Error("L1 details have not been loaded");
        }

        assertFields(params, MandatoryFields.DepositRequest);

        const symbol: string = params["symbol"];
        const quantity: string = params["quantity"];

        this.logger.debug(`[${requestId}] Handling depositIntoL2 request. params=${JSON.stringify(params)}`);

        let tokenInfo = this.l1Details?.tokens.get(symbol);

        if (tokenInfo === undefined) {
            throw new Error(`Symbol ${symbol} has not been configured`);
        }

        let response = null;
        let status: string | undefined = undefined;
        try {
            response = await this.bridge(tokenInfo, symbol, quantity, this.l1Details!.bridge_address, this.l1RpcProvider);
        } catch (error) {
            this.logger.error(`[${requestId}] ${error}`);
            throw error;
        }

        const txid = response.hash;

        status = txid === undefined ? "failed" : "success";

        if (status === "success") {
            this.logger.info(`[${requestId}] Successfully deposited ${quantity}. Txid=${txid}`);
        } else {
            this.logger.error(`[${requestId}] Failed to deposit ${quantity}. Txid=${txid}`);
        }

        return {
            statusCode: (status === "success") ? 200 : 400,
            payload: response
        }
    }

    withdrawFromL2 = async (requestId: bigint,
                             path: string,
                             params: any,
                             receivedAtMs: number): Promise<RestResult> => {
        if (this.signer === undefined) {
            throw new Error("Proxy is in read-only mode");
        }

        if (this.l2Details === undefined) {
            throw new Error("L2 details have not been loaded");
        }

        assertFields(params, MandatoryFields.WithdrawRequest);

        const symbol: string = params["symbol"];
        const quantity: string = params["quantity"];

        this.logger.debug(`[${requestId}] Handling withdrawFromL2 request. params=${JSON.stringify(params)}`);

        let tokenInfo = this.l2Details?.tokens.get(symbol);

        if (tokenInfo === undefined) {
            throw new Error(`Symbol ${symbol} has not been configured`);
        }

        let response = null;
        let status: string | undefined = undefined;
        try {
            response = await this.bridge(tokenInfo, symbol, quantity, this.l2Details!.bridge_address, this.l2RpcProvider);
        } catch (error) {
            this.logger.error(`[${requestId}] ${error}`);
            throw error;
        }

        const txid = response.hash;

        status = txid === undefined ? "failed" : "success";

        if (status === "success") {
            this.logger.info(`[${requestId}] Successfully deposited ${quantity}. Txid=${txid}`);
        } else {
            this.logger.error(`[${requestId}] Failed to deposit ${quantity}. Txid=${txid}`);
        }

        return {
            statusCode: (status === "success") ? 200 : 400,
            payload: response
        }
    }

    bridge = async (tokenInfo: TokenInfo, symbol: string, quantity: string, bridgeAddress: string, rpcProvider: string) : Promise<TransactionResponse> => {
        let response;
        const provider = new ethers.providers.JsonRpcProvider(rpcProvider);
        const wallet = this.signer!.connect(provider);

        if (symbol == "ETH") {
            const tx = {
                to: bridgeAddress,
                value: ethers.utils.parseEther(quantity)
            };

            response = await wallet.sendTransaction(tx);
            await response.wait();
        }
        else {
            const tokenContract = new ethers.Contract(tokenInfo.address, this.erc20Abi, provider);
            const amount = ethers.utils.parseUnits(quantity, tokenContract.decimals());
            const data = tokenContract.interface.encodeFunctionData("transfer", [bridgeAddress, amount] );
            const tx = {
                to: bridgeAddress,
                value: ethers.utils.parseUnits("0.000", "ether"),
                data: data
            };

            response =  await wallet.sendTransaction(tx);
            await response.wait();
        }

        return response
    }

    depositIntoExchange = async (requestId: bigint,
                             path: string,
                             params: any,
                             receivedAtMs: number): Promise<RestResult> => {
        if (this.signer === undefined) {
            throw new Error("Proxy is in read-only mode");
        }

        assertFields(params, MandatoryFields.DepositRequest);

        const symbol: string = params["symbol"];
        const quantity: string = params["quantity"];

        this.logger.debug(`[${requestId}] Handling depositIntoExchange request. params=${JSON.stringify(params)}`);

        let response = null;
        let status: string | undefined = undefined;
        try {
            const token = await this.sdk.ctx.getTokenInfo(symbol);
            await this.sdk.ctx.erc20.approveIfNeeded(
                this.signer!,
                token.address,
                this.sdk.config.contractAddress.gate,
                ethers.constants.MaxUint256,
            );

            response = await this.sdk.deposit(this.signer!, token.address, ethers.utils.parseUnits(quantity, token.decimals));
        } catch (error) {
            this.logger.error(`[${requestId}] ${error}`);
            throw error;
        }

        const txid = response.blockHash

        status = txid === undefined ? "failed" : "success";

        if (status === "success") {
            this.logger.info(`[${requestId}] Successfully deposited ${quantity}. Txid=${txid}`);
        } else {
            this.logger.error(`[${requestId}] Failed to deposit ${quantity}. Txid=${txid}`);
        }

        return {
            statusCode: (status === "success") ? 200 : 400,
            payload: response
        }
    }

    withdrawFromExchange = async (requestId: bigint,
                             path: string,
                             params: any,
                             receivedAtMs: number): Promise<RestResult> => {
        if (this.signer === undefined) {
            throw new Error("Proxy is in read-only mode");
        }

        assertFields(params, MandatoryFields.WithdrawRequest);

        const symbol: string = params["symbol"];
        const quantity: string = params["quantity"];

        this.logger.debug(`[${requestId}] Handling withdrawFromExchange request. params=${JSON.stringify(params)}`);

        let response = null;
        let status: string | undefined = undefined;
        try {
            const token = await this.sdk.ctx.getTokenInfo(symbol);
            response = await this.sdk.withdraw(this.signer!, token.address, ethers.utils.parseUnits(quantity, token.decimals));
        } catch (error) {
            this.logger.error(`[${requestId}] ${error}`);
            throw error;
        }

        const txid = response.blockHash

        status = txid === undefined ? "failed" : "success";

        if (status === "success") {
            this.logger.info(`[${requestId}] Successfully withdrawn ${quantity}. Txid=${txid}`);
        } else {
            this.logger.error(`[${requestId}] Failed to withdraw ${quantity}. Txid=${txid}`);
        }

        return {
            statusCode: (status === "success") ? 200 : 400,
            payload: response
        }
    }

    replaceBigNumber = (key: string, value: any): string => {
        if (value instanceof Object && 'type' in value && value['type'] === 'BigNumber') {
            return ethers.utils.formatUnits(value).toString();
        }
        else {
            return value;
        }
    }

    getInstrument = (instruments: InstrumentModel[], symbol: string): InstrumentModel => {
        const instrument = instruments.find((i) => i.info.symbol === symbol);
        if (!instrument) {
            throw new Error('unknown symbol: ' + symbol);
        }
        return instrument;
    }

    readPrivateKey = (): string => {
        if (this.config.key_store_file_path === undefined) {
            throw new Error("The key `key_store_file_path` must be defined in the config")
        }
        const keyStoreFilePath: string = this.config.key_store_file_path;
        try {
            return readFileSync(keyStoreFilePath, "utf8").trimEnd();
        } catch(error) {
            this.logger.error(`Cannot read private key from ${keyStoreFilePath}`);
            this.logger.error(error);
            throw(error);
        }
    }

    getErc20Abi = (): any => {
        const filePrefix = dirname(process.argv[1]);
        const filename = `${filePrefix}/../erc20_abi.json`;
        return JSON.parse(readFileSync(filename, "utf8").trimEnd());
    }
}
