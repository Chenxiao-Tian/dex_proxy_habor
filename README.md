### Development via localhost (This won't be possible for some projects like 'paradex' due to some dependency issues)
- Navigate to the project you are working on and install the project
  - ```cd gte```
  - ```pip install .```

- Run your dex
  - ```python3 -u -m dex_proxy.main -s -c gte.config.json -n gte```

- Navigate to the openapi webpage to test the endpoints
  - ```http://localhost:1958/docs```

### Development via docker

- Our recommended development environment is through ```Dockerfile.local```
- Following steps assume ```dex_proxy``` repo as a working directory


#### GTE
- Building the image
  - ```docker build -t dex-proxy-gte -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:22222:22 -p 127.0.0.1:2958:2958 --name dex-proxy-gte -d dex-proxy-gte```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 22222```
- While inside the container
  - ```cd gte```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c gte/gte.config.json -n gte```

#### Paradex
- Building the image
  - ```docker build -t dex-proxy-pdex -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:32222:22 -p 127.0.0.1:3958:3958 --name dex-proxy-pdex -d dex-proxy-pdex```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 32222```
- While inside the container
  - ```cd paradex```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c paradex.config.json -n pdex```

#### Hype
- Building the image
  - ```docker build -t dex-proxy-hype -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:42222:22 -p 127.0.0.1:4958:4958 --name dex-proxy-hype -d dex-proxy-hype```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 42222```
- While inside the container
  - ```cd hype```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c hype.config.json -n hype```

#### Lyra
- Building the image
  - ```docker build -t dex-proxy-lyra -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:52222:22 -p 127.0.0.1:5958:5958 --name dex-proxy-lyra -d dex-proxy-lyra```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 52222```
- While inside the container
  - ```cd lyra```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c lyra.config.json -n lyra```

#### Native
- Building the image
  - ```docker build -t dex-proxy-native -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:62222:22 -p 127.0.0.1:6958:6958 --name dex-proxy-native -d dex-proxy-native```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 62222```
- While inside the container
  - ```cd native```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c native.config.json -n native```

#### Per
- Building the image
  - ```docker build -t dex-proxy-per -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:62223:22 -p 127.0.0.1:7958:7958 --name dex-proxy-per -d dex-proxy-per```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 62223```
- While inside the container
  - ```cd native```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c per.config.json -n per```


#### Uni3
- Building the image
  - ```docker build -t dex-proxy-uniswap_v3 -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:62224:22 -p 127.0.0.1:8958:7958 --name dex-proxy-uniswap_v4 -d dex-proxy-uniswap_v3```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 62224```
- While inside the container
  - ```cd uniswap_v3```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c uniswap_v3-arbitrum.config.json -n uniswap_v3```

#### Uni4
- Building the image
  - ```docker build -t dex-proxy-uniswap_v4 -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:62225:22 -p 127.0.0.1:9958:9958 --name dex-proxy-uniswap_v4 -d dex-proxy-uniswap_v4```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 62225```
- While inside the container
  - ```cd uniswap_v4```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c uniswap_v4.config.json -n uniswap_v4```

#### Vert
- Building the image
  - ```docker build -t dex-proxy-vert -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:62226:22 -p 127.0.0.1:10958:10958 --name dex-proxy-vert -d dex-proxy-vert```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 62226```
- While inside the container
  - ```cd vert```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c vert.config.json -n vert```

#### Notes 
- We are mounting our working directory directly to the image so you shouldn't need to rebuild the image to develop
- We assume existence of valid ssh keys in the host ```ssh-agent``` and they are forwarded to the ```sshd``` inside the Docker image
- If you are on MacOS you are probably using ```podman``` and want to replace ```docker``` accordingly
- If you are having dns problems inside container, you should try running the container with ```--net=host``` to bridge the network interfaces



### Verifying Exchange Whitelists in the resources directory
- Checks to be performed by reviewers:
  - Verify that ```token contract addresses``` are present in the ```token_contracts``` table in the ```prod TradingDB```.
  ```postgresql
  select  address, token_name, chain, added_timestamp from token_contracts where chain='<chain_name>' and address='<address>' and token_name='<token_name>';
  ```
  - Verify that ```pool adresses``` are present in the ```pools``` table in the ```prod TradingDB```.
  ```postgresql
  select id, address, dex_name, chain from pools where chain='<chain_name>' and dex_name='<dex_name>' and address='<address>';
  ```
  - Verify that the ```withdrawal_addresses``` are present in the ```exchange_addresses``` table in the ```prod TradingDB```.
  ```postgresql
  select account, token, address from exchange_addresses where token='<token_name>' and address='<address>';
  ```
  - Verify the existence and correctness of the addresses on chain using a ```block explorer```.

