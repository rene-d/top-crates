#!/usr/bin/env bash

if [[ ${1-} == x ]]; then
    docker buildx create --use --name buildx-local
    docker buildx build --platform linux/arm64,linux/amd64 --push -t rene2/rust -f docker/Dockerfile .
    docker buildx rm buildx-local
else
    docker build -t rene2/rust -f docker/Dockerfile .
    # docker build --platform linux/amd64 -t rene2/rust -f docker/Dockerfile .
    # docker build --platform linux/arm64 -t rene2/rust -f docker/Dockerfile .
fi

# should work:
# docker run --rm -ti --network none -w /hello rene2/rust cargo run --release --bin hello

# also works:
# docker run --rm -ti --network none rene2/rust cargo install ripgrep

# for remote development
# docker run --rm -d --network none -v $HOME/.vscode-server:/root/.vscode-server --name rust-dev rene2/rust sleep infinity
