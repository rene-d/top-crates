FROM scratch AS crates

COPY local-registry/ /local-registry/

FROM rust:1

COPY --from=crates /local-registry/ /local-registry/

RUN rustup +nightly component add rustfmt && \
    rustup component add clippy rls rust-analysis rust-src rust-docs

COPY docker/config /usr/local/cargo/config

COPY docker/hello/ /hello/
