import { bcs } from "@mysten/sui/bcs";

import { getFullnodeUrl, SuiClient } from "@mysten/sui/client";
import { Transaction } from "@mysten/sui/transactions";
import { Ed25519Keypair } from "@mysten/sui/keypairs/ed25519";
import { fromHEX, normalizeSuiAddress } from "@mysten/sui/utils";

const balance_manager_id =
  "0xd65d3223d2b61e7ecd85ffdf2c7dd2ddb196cdceee48e695b30bde2eeef67964";

const balanceManagers = {
  MANAGER_1: {
    address: balance_manager_id,
    tradeCap: "",
  },
  MANAGER_2: {
    address: "",
    tradeCap: "",
  },
};

const wallet_address =
  "0x6bb57d9fe982786dda345723fca19f772cae2d9b76ee22cd47337e7b1ec2718c";
const privateKey =
  "suiprivkey1qzklg5g6zq328ajfgmhhgnmruvkzdpccezueggdk8l7c957cnlkvv87lmz5";
const secretKey =
  "0xadf4511a1022a3f64946ef744f63e32c268718c8b99421b63ffd82d3d89fecc6";
const keypair = Ed25519Keypair.fromSecretKey(fromHEX(secretKey));
const address = keypair.toSuiAddress();

const suiClient = new SuiClient({ url: getFullnodeUrl("testnet") });

const SUI_DBUSDC =
  "0x966c99a5ce0ce3e09dacac0a42cc2b888d9e1a0c5f39b69f556c38f38ef0b81d";
const tx = new Transaction();
tx.moveCall({
  target: `0x48cc688a15bdda6017c730a3c65b30414e642d041f2931ef14e08f6b0b2a1b7f::pool::get_account_order_details`,
  arguments: [tx.object(SUI_DBUSDC), tx.object(balance_manager_id)],
  typeArguments: [
    `0x0000000000000000000000000000000000000000000000000000000000000002::sui::SUI`,
    `0xf7152c05930480cd740d7311b5b8b45c6f488e3a53a11c3f74a6fac36a52e0d7::DBUSDC::DBUSDC`,
  ],
});

const res = await suiClient.devInspectTransactionBlock({
  sender: normalizeSuiAddress(wallet_address),
  transactionBlock: tx,
});

const ID = bcs.struct("ID", {
  bytes: bcs.Address,
});
const OrderDeepPrice = bcs.struct("OrderDeepPrice", {
  asset_is_base: bcs.bool(),
  deep_per_asset: bcs.u64(),
});
const Order = bcs.struct("Order", {
  balance_manager_id: ID,
  order_id: bcs.u128(),
  client_order_id: bcs.u64(),
  quantity: bcs.u64(),
  filled_quantity: bcs.u64(),
  fee_is_deep: bcs.bool(),
  order_deep_price: OrderDeepPrice,
  epoch: bcs.u64(),
  status: bcs.u8(),
  expire_timestamp: bcs.u64(),
});

const ordersInformation = res.results[0].returnValues[0][0];
let orders = bcs.vector(Order).parse(new Uint8Array(ordersInformation));
console.log("SUI_DBUSDC: ", orders);
