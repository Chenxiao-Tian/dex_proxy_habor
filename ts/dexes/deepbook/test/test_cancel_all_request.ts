import axios from "axios";

const host = "localhost";
const port = 3001;

const cancelAll = async (poolId: string) => {
    try {
        const url = `http://${host}:${port}/orders`;
        const params = {
            data: {
                pool_id: poolId
            }
        };

        console.log(`Request: url=${url} params=${JSON.stringify(params)}`);

        let { data, status } = await axios.delete(url, params);

        console.log(`status => ${status}`);
        console.log(`payload => ${JSON.stringify(data)}`);
    } catch (error) {
        let error_ = error as any;

        console.log(`status => ${error_.response.status}`);
        console.log(`payload => ${JSON.stringify(error_.response.data)}`);
    }
}

const main = async () => {
    const poolId = "0x538091bde22b3e38aae569ed1fb8621714c8193bc6819ea2e5ebb9ae700a42d2";

    await Promise.all([
        cancelAll(poolId),
        cancelAll(poolId),
        cancelAll(poolId),
        cancelAll(poolId),
        cancelAll(poolId)
    ]);

    await setTimeout(async () => { await Promise.all([
        cancelAll(poolId),
        cancelAll(poolId),
        cancelAll(poolId),
        cancelAll(poolId),
        cancelAll(poolId)
    ])}, 1000);
}

await main()
