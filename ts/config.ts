import { parse, resolve, format } from "node:path";
import fs from "fs";

function getDefaultConfig(): string {
    // arg 1 as arg 0 is node
    let defaultConfigPath = parse(process.argv[1]);
    defaultConfigPath.ext = "config.json";
    defaultConfigPath.base = "";

    return format(defaultConfigPath);
}

export function parseConfig(configFile?: string): any {
    if (configFile === null || configFile === undefined) {
        configFile = getDefaultConfig();
    }
    console.log(`Reading config file ${resolve(configFile)}`);
    try {
        return JSON.parse(fs.readFileSync(configFile!, "utf8"));
    } catch(error) {
        console.log(`Unable to parse config, ${configFile}`);
        console.log(error);
        throw(error);
    }
}
