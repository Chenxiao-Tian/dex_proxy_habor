import axios from "axios";
import AxiosResponse from "axios";

const host = "localhost";
const port = 3001;

let requestId: number = 0;

type RequestMethod = (url: string, data: any) => any;

const requestImpl = async (requestMethod: RequestMethod,
                           endpoint: string,
                           payload: any | null = null): Promise<any> => {
    try {
        const url = `http://${host}:${port}/${endpoint}`;

        console.log(`Request: id=${++requestId} url=${url} payload=${JSON.stringify(payload)}`);

        let { data, status } = await requestMethod(url, payload);

        console.log(`[id=${requestId}] status=${status}`);
        console.log(`[id=${requestId}] payload=${JSON.stringify(data)}`);

    } catch (error) {
        let error_ = error as any;

        console.log(`[id=${requestId}] status=${error_.response.status}`);
        console.log(`[id=${requestId}] payload=${JSON.stringify(error_.response.data)}`);
    }
}

export const get = async (endpoint: string, queryParams: any | null = null) => {
    if (queryParams) {
        return await requestImpl(axios.get, endpoint, { params: queryParams });
    } else {
        return await requestImpl(axios.get, endpoint);
    }
}

export const post = async (endpoint: string, payload: any | null = null) => {
    if (payload) {
        return await requestImpl(axios.post, endpoint, payload);
    } else {
        return await requestImpl(axios.post, endpoint);
    }
}

export const delete_ = async (endpoint: string, queryParams: any | null = null) => {
    if (queryParams) {
        return await requestImpl(axios.delete, endpoint, { params: queryParams });
    } else {
        return await requestImpl(axios.delete, endpoint);
    }
}

const main = async () => {
    await get("wallet-balance-info");
    await get("user-position", { "id": "0x4405b50d791fd3346754e8171aaab6bc2ed26c2c46efdd033c14b30ae507ac33" });
}

//await main()
