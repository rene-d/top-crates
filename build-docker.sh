#!/usr/bin/env bash

image_name=rene2/rust

if [[ ${1-} == x ]]; then
    docker buildx create --use --name buildx-local
    docker buildx build --pull --platform linux/arm64,linux/amd64 --push -t ${image_name} -f docker/Dockerfile .
    docker buildx rm buildx-local

    echo
    docker manifest inspect ${image_name} | jq -r '.manifests[] | (.platform.architecture + " " + .digest)'
else
    docker build --pull -t ${image_name} -f docker/Dockerfile .
    # docker build --platform linux/amd64 -t ${image_name} -f docker/Dockerfile .
    # docker build --platform linux/arm64 -t ${image_name} -f docker/Dockerfile .
fi

# should work:
# docker run --rm -ti --network none -w /hello ${image_name} cargo run --release --bin hello

# also works:
# docker run --rm -ti --network none ${image_name} cargo install ripgrep

# for remote development
# docker run --rm -d --network none -v $HOME/.vscode-server:/root/.vscode-server --name rust-dev ${image_name} sleep infinity
