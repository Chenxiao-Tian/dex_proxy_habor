## TS Dex Proxy

### Steps to install the required dependencies
1. `cd` into the subdirectory `ts/`.
2. Run the command `npm install`. This will install the dependencies mentioned in `package.json` which is present in the same directory.

### Steps to run the dex_proxy locally
1. in the subdirectory `ts/`.
2. Invoke the typescript compiler, `tsc`.
3. Run the server, `node dist/dex_proxy.js -c dexes/deepbook/dex_proxy_1.config.json`.
   - The server will accept requests on port 3000.
4. To run a read-only version of the server, run `node dist/dex_proxy.js -c dex_proxy.config.json --mode read-only`.


### Webpack
1. `npx webpack`
2. `node packed/main.js -c dex_proxy.config.json`

# Dev setup

```
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.5/install.sh | bash

# new terminal

nvm install node

# shouldn't need these. npm install should have sorted them
npm install -g typescript
npm install webpack webpack-cli --save-dev

```

# Debugging
1. Copy config files into the generated 'dist' folder
2. Set breakpoints in the dist/*.js files 
3. Right click on the dex_proxy.js and hit debug
