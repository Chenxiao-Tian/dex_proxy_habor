import winston from "winston";

export class LoggerFactory {
    config: any;
    logLevel: string;
    loggers: winston.Container;

    constructor(config: any) {
        this.config = config
        this.logLevel = this.config.logging.level;
        this.loggers = new winston.Container();
    }

    public createLogger(name: string): winston.Logger {
        // format
        // timestamp level [tag]
        this.loggers.add(name, {
            level: this.logLevel,
            transports: [
                new winston.transports.Console()
            ],
            format: winston.format.combine(
                winston.format.timestamp({
                    format: "YYYY-MM-DD HH:mm:ss.SSS"
                }),
                winston.format.printf(
                    (msg) => `${msg.timestamp} ${msg.level.toUpperCase()} [${name}] ${msg.message}`
                )
            )
        });

        return this.loggers.get(name);
    }
}
