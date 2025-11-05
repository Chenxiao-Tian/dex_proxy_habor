declare global {
  namespace NodeJS {
    interface Process {
        _linkedBinding: any
    }
  }
}

let jsas = process._linkedBinding('jsas');

function getConfig(): any {
    let cfg = jsas.getConfig();
    return cfg
}

export default {getConfig};

