#![deny(rust_2018_idioms)]

use git2::{build::CheckoutBuilder, Repository};
use std::{fs, fs::File, io::Read, path::Path, path::PathBuf};
use top_crates::*;

fn main() {
    let mirror_path = Path::new(".");

    sync_crates_repo(&mirror_path);
    find_top_crates();
    write_top_crates_index();
}

/// Synchronize the crates.io-index repository.
///
/// `mirror_path`: Root path to the mirror directory.
pub fn sync_crates_repo(mirror_path: &Path) {
    let repo_path = mirror_path.join("crates.io-index");

    if !repo_path.exists() {
        fs::create_dir_all(&repo_path).unwrap();
    }

    let source_index = "https://github.com/rust-lang/crates.io-index";

    if !repo_path.join(".git").exists() {
        println!("git clone {}", source_index);

        // Clone the project.
        Repository::clone(&source_index, &repo_path).expect("Cannot clone index repository");
    } else {
        println!("git fetch {}", source_index);

        // Get (fetch) the branch's latest remote "master" commit
        let repo = Repository::open(&repo_path).expect(&format!(
            "Cannot open repository at {}",
            repo_path.display()
        ));

        let mut remote = repo.find_remote("origin").expect(&format!(
            "Cannot find remote 'origin' in {}",
            repo_path.display()
        ));

        remote.fetch(&["master"], None, None).expect(&format!(
            "Cannot fetch master branch in {}",
            repo_path.display()
        ));

        let object = repo
            .revparse_single("origin/master")
            .expect("failed to find identifier");

        let mut checkout_opts = CheckoutBuilder::new();
        checkout_opts.force();

        repo.reset(&object, git2::ResetType::Hard, Some(&mut checkout_opts))
            .expect(&format!("failed to checkout '{:?}'", object));
    }
}

/// find_top_crates reads the configuration file, asks for Cargo
/// and build the list of top crates.
fn find_top_crates() {
    let mut f =
        File::open("crate-modifications.toml").expect("unable to open crate modifications file");

    let mut d = Vec::new();
    f.read_to_end(&mut d)
        .expect("unable to read crate modifications file");

    let modifications: Modifications =
        toml::from_slice(&d).expect("unable to parse crate modifications file");

    let infos = generate_info(&modifications);

    // Write the top crates file.
    let base_directory: PathBuf = PathBuf::from(".");

    let path = base_directory.join("crate-information.json");
    let mut f = File::create(&path)
        .unwrap_or_else(|e| panic!("Unable to create {}: {}", path.display(), e));

    serde_json::to_writer_pretty(&mut f, &infos)
        .unwrap_or_else(|e| panic!("Unable to write {}: {}", path.display(), e));

    println!("Wrote {}", path.display());
}

fn write_top_crates_index() {
    // the crates.io index repository
    let source_repo = Path::new("crates.io-index");

    // our crates list
    let f = File::open("crate-information.json").expect("unable to open crate information file");
    let json: serde_json::Value = serde_json::from_reader(f).expect("file should be proper JSON");
    assert!(json.is_array());

    // the new repo with the selected crates
    let new_repo = Path::new("top-crates-index");

    let mut total_crates = 0;

    for c in json.as_array().unwrap() {
        let crate_index = prefix_path(c["name"].as_str().unwrap());
        let index = source_repo.join(&crate_index);

        let mut new_info = Vec::new();

        // copy the information for the requested crate versions
        let data = fs::read_to_string(index).unwrap();
        for line in data.lines() {
            let info: serde_json::Value = serde_json::from_str(&line).unwrap();
            if info.get("vers").unwrap() == c["version"].as_str().unwrap() {
                new_info.push(line);
                break;
            }
        }

        let new_index = new_repo.join(&crate_index);

        fs::create_dir_all(new_index.parent().unwrap()).unwrap();
        fs::write(&new_index, new_info.join("\n")).unwrap();

        total_crates += new_info.len();
    }

    println!("{} crates", total_crates);
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
