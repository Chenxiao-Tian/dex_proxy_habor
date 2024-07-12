export type Mode = "read-only" | "read-write";

export interface DexInterface {
  start(): Promise<void>;
  channels: Array<string>;
}

export class ParsedOrderError extends Error {
    type: string;
    responseCode: number | null;

    constructor(type: string, message: string, responseCode: number | null=null) {
        super(message);
        this.type = type;
        this.responseCode = responseCode;
    }
}
