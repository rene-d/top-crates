#![deny(rust_2018_idioms)]

use git2::{build::RepoBuilder, FetchOptions, Repository};
use rust_playground_top_crates::*;
use serde::Serialize;
use std::path::Path;
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

/// Synchronize the crates.io-index repository.
///
/// `mirror_path`: Root path to the mirror directory.
pub fn sync_crates_repo(mirror_path: &Path) {
    let repo_path = mirror_path.join("crates.io-index");

    let source_index = "https://github.com/rust-lang/crates.io-index";

    let mut fetch_opts = FetchOptions::new();

    if !repo_path.join(".git").exists() {
        println!("git clone {}", source_index);

        let mut repo_builder = RepoBuilder::new();
        repo_builder.fetch_options(fetch_opts);
        repo_builder.clone(&source_index, &repo_path).unwrap();
    } else {
        println!("git fetch {}", source_index);

        // Get (fetch) the branch's latest remote "master" commit
        let repo = Repository::open(&repo_path).unwrap();
        let mut remote = repo.find_remote("origin").unwrap();
        remote
            .fetch(&["master"], Some(&mut fetch_opts), None)
            .unwrap();
    }
}

fn write_index() {
    let repo = Path::new("crates.io-index");

    let f = File::open("crate-information.json").expect("unable to open crate information file");
    let json: serde_json::Value = serde_json::from_reader(f).expect("file should be proper JSON");

    assert!(json.is_array());

    let new_repo = Path::new("top-crates-index");

    let mut total_crates = 0;

    if let Some(a) = json.as_array() {
        for c in a {
            let crate_index = prefix_path(c["name"].as_str().unwrap());
            let index = repo.join(&crate_index);

            let mut new_info = Vec::new();

            let data = std::fs::read_to_string(index).unwrap();
            for line in data.lines() {
                let info: serde_json::Value = serde_json::from_str(&line).unwrap();
                if info.get("vers").unwrap() == c["version"].as_str().unwrap() {
                    new_info.push(line);
                    break;
                }
            }

            let new_index = new_repo.join(&crate_index);

            std::fs::create_dir_all(new_index.parent().unwrap()).unwrap();
            std::fs::write(&new_index, new_info.join("\n")).unwrap();

            total_crates += new_info.len();
        }
    }

    println!("{} crates", total_crates);
}

fn get_top_crates() {
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

fn main() {
    sync_crates_repo(Path::new("."));
    get_top_crates();
    write_index();
}

fn prefix_path(name: &str) -> String {
    let mut s = String::new();

    match name.len() {
        0 => panic!("empty name"),
        1 => s.push('1'),
        2 => s.push('2'),
        3 => {
            s.push_str("3/");
            s.push(name.chars().next().unwrap());
        }
        _ => {
            s.push_str(name[0..2].to_string().as_str());
            s.push('/');
            s.push_str(name[2..4].to_string().as_str());
        }
    }

    s.push('/');
    s.push_str(name);
    s
}

#[cfg(test)]
#[test]
fn test_prefix() {
    assert_eq!(prefix_path("f"), "1/f");
    assert_eq!(prefix_path("fo"), "2/fo");
    assert_eq!(prefix_path("foo"), "3/f/foo");
    assert_eq!(prefix_path("foobar"), "fo/ob/foobar");
}
