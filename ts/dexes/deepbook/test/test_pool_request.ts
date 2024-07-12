import axios from "axios";

const host = "localhost";
const port = 3001;

const getPool = async (poolId: string) => {
    try {
        const url = `http://${host}:${port}/pool`;
        const params = {
            params: {
                id: poolId
            }
        };

        console.log(`Request: url=${url} params=${JSON.stringify(params)}`);

        let { data, status } = await axios.get(url, params);

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

    const nonExistentPoolId = "0x538091bde22b3e38aae569ed1fb8621714c8193bc6819ea2e5ebb9ae700a4211";

    Promise.all([
        getPool(poolId),
        getPool(nonExistentPoolId)
    ]);
}

await main()
