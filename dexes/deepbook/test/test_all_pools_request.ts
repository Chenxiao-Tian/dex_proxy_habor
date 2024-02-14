import axios from "axios";

const host = "localhost";
const port = 3001;

const getPools = async () => {
    try {
        const url = `http://${host}:${port}/pools`;
        console.log(`Request: url=${url}`);

        let { data, status } = await axios.get(url);

        console.log(`status => ${status}`);
        console.log(`payload => ${JSON.stringify(data)}`);
    } catch (error) {
        let error_ = error as any;

        console.log(`status => ${error_.response.status}`);
        console.log(`payload => ${JSON.stringify(error_.response.data)}`);
    }
}

const main = async () => {
    getPools();
}

await main()
