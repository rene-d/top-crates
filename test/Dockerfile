FROM rust

ARG MIRROR=localhost:9830

ENV CARGO_HOME=/root/.cargo \
    RUSTUP_DIST_SERVER=http://${MIRROR} \
    RUSTUP_UPDATE_ROOT=http://${MIRROR}/rustup

COPY config /root/.cargo/config
RUN sed -i 's/<MIRROR>/'${MIRROR}'/' /root/.cargo/config

COPY hello/ /src/hello/
