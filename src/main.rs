#![deny(rust_2018_idioms)]

use rust_playground_top_crates::*;
use serde::Serialize;
use std::{collections::BTreeMap, fs::File, io::Read, path::PathBuf};

/// A Cargo.toml file.
#[derive(Serialize)]
struct TomlManifest {
    package: TomlPackage,
    profile: Profiles,
    #[serde(serialize_with = "toml::ser::tables_last")]
    dependencies: BTreeMap<String, DependencySpec>,
}

/// Header of Cargo.toml file.
#[derive(Serialize)]
struct TomlPackage {
    name: String,
    version: String,
    authors: Vec<String>,
    resolver: String,
}

/// A profile section in a Cargo.toml file
#[derive(Serialize)]
#[serde(rename_all = "kebab-case")]
struct Profile {
    codegen_units: u32,
    incremental: bool,
}

/// Available profile types
#[derive(Serialize)]
struct Profiles {
    dev: Profile,
    release: Profile,
}

fn main() {
    let mut f =
        File::open("crate-modifications.toml").expect("unable to open crate modifications file");

    let mut d = Vec::new();
    f.read_to_end(&mut d)
        .expect("unable to read crate modifications file");

    let modifications: Modifications =
        toml::from_slice(&d).expect("unable to parse crate modifications file");

    let infos = rust_playground_top_crates::generate_info(&modifications);

    // Write manifest file.
    let base_directory: PathBuf = PathBuf::from(".");

    let path = base_directory.join("crate-information.json");
    let mut f = File::create(&path)
        .unwrap_or_else(|e| panic!("Unable to create {}: {}", path.display(), e));
    serde_json::to_writer_pretty(&mut f, &infos)
        .unwrap_or_else(|e| panic!("Unable to write {}: {}", path.display(), e));
    println!("Wrote {}", path.display());
}
