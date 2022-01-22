FROM rust:1

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y gdb vim

RUN rustup component add rls
RUN rustup +nightly component add rustfmt

COPY local-registry/ /local-registry/

COPY docker/config /usr/local/cargo/config

COPY docker/hello/ /hello/
