
export type TokenInfo = {
    symbol: string;
    address: string;
    validWithdrawalAddresses: Set<string>;
};

export type ChainInfo = {
    tokens: Map<string, TokenInfo>;
    bridge_address: string;
};