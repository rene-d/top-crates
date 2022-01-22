FROM scratch AS crates

COPY local-registry/ /local-registry/

FROM rust:1

COPY --from=crates /local-registry/ /local-registry/

RUN rustup component add rls
RUN rustup +nightly component add rustfmt

COPY docker/config /usr/local/cargo/config

COPY docker/hello/ /hello/
