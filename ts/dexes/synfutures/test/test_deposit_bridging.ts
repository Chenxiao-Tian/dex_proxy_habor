import axios from "axios";

const host = "localhost";
const port = 3001;

const deposit = async (symbol: string, quantity: string) => {
    try {
        const url = `http://${host}:${port}/deposit-into-l2`;
        const params = {
            symbol: symbol,
            quantity: quantity
        };

        console.log(`Request: url=${url} params=${JSON.stringify(params)}`);

        let { data, status } = await axios.post(url, params);

        console.log(`status => ${status}`);
        console.log(`payload => ${JSON.stringify(data)}`);
    } catch (error) {
        let error_ = error as any;

        console.log(`status => ${error_.response.status}`);
        console.log(`payload => ${JSON.stringify(error_.response.data)}`);
    }
}

const main = async () => {
    await deposit("ETH", "0.01");
}

await main()
