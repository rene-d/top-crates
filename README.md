# top-crates

top-crates lists the top crates in the Rust ecosystem and their dependencies.

It can build an index that can be configured in [Cargo](https://doc.rust-lang.org/cargo/reference/config.html) or mirrored by [Romt](https://github.com/drmikehenry/romt) or [Panamax](https://github.com/panamax-rs/panamax).

Both are designed to mirror the entire Rust ecosystem (70-80Gb by early 2022), which can be a drawback.

top-crates can also make a local registry (like [cargo local-registry](https://crates.io/crates/cargo-local-registry)) that can be used with Cargo.

This local registry can be added to a Docker image to create an isolated development environment for Rust.

## Usage

Get full usage information with `--help` or `-h`.


### Example

Update the [crates.io index](http://github.com/rust-lang/crates.io-index) and prepare the local registry:

```shell
./top-crates.py -u -p
```

### Cargo config file

Create or add to the file `$CARGO_HOME/config` the following lines:

```toml
[source.local]
local-registry = "/path/to/local-registry"

[source.crates-io]
replace-with = "local"
```
