FROM scratch AS crates

COPY local-registry/ /local-registry/

FROM rust:1.59.0

RUN rustup component add rustfmt clippy rls rust-analysis rust-src rust-docs

# https://crates.io/crates/cargo-audit
RUN git clone https://github.com/rustsec/advisory-db /usr/local/cargo/advisory-db

# add your local registry
COPY --from=crates /local-registry/ /local-registry/

# add the config to use the local registry
COPY docker/config /usr/local/cargo/config

# copy the example project
COPY docker/hello/ /hello/
