### Development environment
- Our recommended development environment is through ```Dockerfile.local```
- Following steps assume ```dex_proxy``` repo as a working directory
- Building the image
  - ```docker build -t dex-proxy -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:22222:22 -p 127.0.0.1:1958:1958 --name dex-proxy -d dex-proxy```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 22222```
- While inside the container
  - ```pip install .```
  - ```python dex_proxy.py -s -c dexes/paradex/paradex.config.json -n pdex_proxy```

### Notes 
- We are mounting our working directory directly to the image so you shouldn't need to rebuild the image to develop
- We assume existence of valid ssh keys in the host ```ssh-agent``` and they are forwarded to the ```sshd``` inside the Docker image
- If you are on MacOS you are probably using ```podman``` and want to replace ```docker``` accordingly
- If you are having dns problems inside container, you should try running the container with ```--net=host``` to bridge the network interfaces


