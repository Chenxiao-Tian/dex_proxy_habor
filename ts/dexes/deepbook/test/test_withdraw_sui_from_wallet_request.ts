import { post } from "./requests.js";

const main = async () => {
    let payload = {
        "recipient": "0xefaf8e50dcca14d62edd8f2497a2bb07ae33fdefd795db0b0d70a3e9c4cbc3c0",
        "quantity": "0.01"
    }

    post("withdraw-sui", payload);
}

await main()
