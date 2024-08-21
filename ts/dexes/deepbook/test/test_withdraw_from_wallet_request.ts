import { post } from "./requests.js";

const main = async () => {
    let payload = {
        "coin_type_id": "0x5d4b302506645c37ff133b98c4b50a5ae14841659738d6d733d59d0d217a93bf::coin::COIN",
        "recipient": "0xefaf8e50dcca14d62edd8f2497a2bb07ae33fdefd795db0b0d70a3e9c4cbc3c0",
        "quantity": "0.01"
    }

    post("withdraw", payload);
}

await main()
