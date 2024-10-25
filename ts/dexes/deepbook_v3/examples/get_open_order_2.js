import { DeepBookClient } from "@mysten/deepbook-v3";
import { getFullnodeUrl, SuiClient } from "@mysten/sui/client";
import { Ed25519Keypair } from "@mysten/sui/keypairs/ed25519";
import { fromHex, normalizeSuiAddress } from "@mysten/sui/utils";
import { bcs } from "@mysten/sui/bcs";
import { Transaction } from "@mysten/sui/transactions";

const balanceManagers = {
  MANAGER_1: {
    address:
      "0xff40dfdaa475ffa9d86d5e74d321f1f275a079b4e70891ad51bc88fdddfde775",
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
const keypair = Ed25519Keypair.fromSecretKey(fromHex(secretKey));
const address = keypair.toSuiAddress();

const suiClient = new SuiClient({ url: getFullnodeUrl("testnet") });
const deepBookClient = new DeepBookClient({
  client: suiClient,
  address: address,
  env: "testnet",
  balanceManagers: balanceManagers,
});

const tx = new Transaction();
tx.add(
  deepBookClient.deepBook.getOrder(
    "DEEP_SUI",
    "170141192683841268586463111715884181772"
  )
);

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

let result;
try {
  const orderInformation = res.results[0].returnValues[0][0];
  result = Order.parse(new Uint8Array(orderInformation));
} catch (e) {
  result = null;
}

console.log(`${JSON.stringify(result)}`);
