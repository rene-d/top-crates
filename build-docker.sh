#!/usr/bin/env bash

docker build -t rene2/rust -f devenv/Dockerfile .

# should work:
docker run --rm -ti --network none -w /hello rene2/rust cargo build

# also works:
# docker run --rm -ti --network none rene2/rust cargo install ripgrep
