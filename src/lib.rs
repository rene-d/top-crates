#![deny(rust_2018_idioms)]

use cargo::{
    core::{
        compiler::{CompileKind, CompileTarget, TargetInfo},
        package::PackageSet,
        registry::PackageRegistry,
        resolver::{self, features::RequestedFeatures, ResolveOpts},
        source::SourceMap,
        Dependency, Source, SourceId, TargetKind,
    },
    sources::RegistrySource,
    util::{Config, VersionExt},
};
use globset::{Glob, GlobMatcher};
use itertools::Itertools;
use serde::{Deserialize, Deserializer, Serialize};
use std::collections::HashMap;
use std::{
    collections::{BTreeSet, HashSet},
    io::Read,
};

const PLAYGROUND_TARGET_PLATFORM: &str = "x86_64-unknown-linux-gnu";

/// The list of crates from crates.io
#[derive(Debug, Deserialize)]
struct TopCrates {
    crates: Vec<Crate>,
}

/// The shared description of a crate
#[derive(Debug, Deserialize)]
struct Crate {
    #[serde(rename = "id")]
    name: String,
}

/// A mapping of a crates name to its identifier used in source code
#[derive(Debug, Serialize)]
pub struct CrateInformation {
    pub name: String,
    pub version: String,
    pub id: String,
}

#[derive(Debug, Default)]
pub struct Exclusions {
    pub globs: Vec<GlobMatcher>,
}

/// Hand-curated changes to the crate list
#[derive(Debug, Default, Deserialize)]
pub struct Modifications {
    #[serde(default)]
    pub exclusions: Exclusions,
    #[serde(default)]
    pub additions: BTreeSet<String>,

    #[serde(default)]
    pub commands: BTreeSet<String>,
}

impl<'de> Deserialize<'de> for Exclusions {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let json: serde_json::value::Value = serde_json::value::Value::deserialize(deserializer)?;
        let patterns = serde_json::from_value::<Vec<String>>(json).unwrap();

        let mut excl = Exclusions::default();
        for pattern in patterns {
            let glob = Glob::new(pattern.as_str()).unwrap().compile_matcher();
            excl.globs.push(glob);
        }

        Ok(excl)
    }
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "kebab-case")]
pub struct DependencySpec {
    #[serde(skip_serializing_if = "String::is_empty")]
    pub package: String,
    #[serde(serialize_with = "exact_version")]
    pub version: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub features: Vec<String>,
    #[serde(skip_serializing_if = "is_true")]
    pub default_features: bool,
}

fn exact_version<S>(version: &String, serializer: S) -> Result<S::Ok, S::Error>
where
    S: serde::Serializer,
{
    format!("={}", version).serialize(serializer)
}

fn is_true(b: &bool) -> bool {
    *b
}

impl Modifications {
    fn excluded(&self, name: &str) -> bool {
        self.exclusions.globs.iter().any(|n| n.is_match(name))
    }
}

fn simple_get(url: &str) -> reqwest::Result<reqwest::blocking::Response> {
    reqwest::blocking::ClientBuilder::new()
        .user_agent("Rust Playground - Top Crates Utility")
        .build()?
        .get(url)
        .send()
}

impl TopCrates {
    /// List top crates by number of downloads on crates.io.
    fn download() -> TopCrates {
        let mut top = TopCrates { crates: Vec::new() };

        let mut get_top = |pages, count, category| {

            let category = if category != "" {
                format!("&category={}", category)
            } else {
                "".to_string()
            };

            for page in 1..=pages {
                let url = format!(
                    "https://crates.io/api/v1/crates?page={}&per_page={}&sort=downloads{}",
                    page, count, category
                );
                let resp = simple_get(&url).expect("Failed to fetch crates.io");
                let p: TopCrates = serde_json::from_reader(resp).expect("Invalid JSON");
                top.crates.extend(p.crates);
            }
        };

        get_top(5, 100, "");
        get_top(1, 100, "network-programming");
        get_top(1, 10, "filesystem");
        get_top(1, 10, "web-programming");
        // get_top(1, 50, "mathematics");
        // get_top(1, 50, "science");

        top
    }

    fn add_rust_cookbook_crates(&mut self) {
        let mut resp = simple_get(
            "https://raw.githubusercontent.com/rust-lang-nursery/rust-cookbook/master/Cargo.toml",
        )
        .expect("Could not fetch cookbook manifest");
        assert!(
            resp.status().is_success(),
            "Could not download cookbook; HTTP status was {}",
            resp.status()
        );

        let mut content = String::new();
        resp.read_to_string(&mut content)
            .expect("could not read cookbook manifest");

        let manifest = content
            .parse::<toml::Value>()
            .expect("could not parse cookbook manifest");

        let dependencies = manifest["dependencies"]
            .as_table()
            .expect("no dependencies found for cookbook manifest");
        self.crates.extend({
            dependencies.iter().map(|(name, _)| Crate {
                name: name.to_string(),
            })
        })
    }

    /// Add crates that have been hand-picked
    fn add_curated_crates(&mut self, modifications: &Modifications) {
        self.crates.extend({
            modifications
                .additions
                .iter()
                .cloned()
                .map(|name| Crate { name })
        });
    }
}

pub fn generate_info(modifications: &Modifications) -> Vec<CrateInformation> {
    let mut top = TopCrates::download();
    top.add_rust_cookbook_crates();
    top.add_curated_crates(modifications);

    println!("{:?} crates", top.crates.len());

    let mut crates: Vec<String> = Vec::new();
    for Crate { name } in &top.crates {
        crates.push(name.clone());
    }

    let mut infos = get_packages_info(&crates, modifications);

    for command in &modifications.commands {
        let mut crates: Vec<String> = Vec::new();
        crates.push(command.to_owned());
        let more_infos = get_packages_info(&crates, modifications);

        infos.extend(more_infos);
    }

    infos.into_values().collect()
}

fn get_packages_info(
    crates: &[String],
    modifications: &Modifications,
) -> HashMap<String, CrateInformation> {
    // Setup to interact with cargo.
    let config = Config::default().expect("Unable to create default Cargo config");
    let _lock = config.acquire_package_cache_lock();
    let crates_io = SourceId::crates_io(&config).expect("Unable to create crates.io source ID");
    let mut source = RegistrySource::remote(crates_io, &HashSet::new(), &config);
    source.update().expect("Unable to update registry");

    // Find the newest (non-prerelease, non-yanked) versions of all
    // the interesting crates.
    let mut summaries = Vec::new();
    for name in crates.iter() {
        if modifications.excluded(name) {
            println!("Excluding {}", name);
            continue;
        }

        // Query the registry for a summary of this crate.
        // Usefully, this doesn't seem to include yanked versions
        let dep = Dependency::parse(name, None, crates_io)
            .unwrap_or_else(|e| panic!("Unable to parse dependency for {}: {}", name, e));

        let matches = source.query_vec(&dep).unwrap_or_else(|e| {
            panic!("Unable to query registry for {}: {}", name, e);
        });

        // Find the newest non-prelease version
        let summary = matches
            .into_iter()
            .filter(|summary| !summary.version().is_prerelease())
            .max_by_key(|summary| summary.version().clone())
            .unwrap_or_else(|| panic!("Registry has no viable versions of {}", name));

        println!("{}", name);
        // for dep in summary.dependencies() {
        //     println!("  {}", dep.package_name());
        // }
        // println!();

        // panic!();

        // Add a dependency on this crate.
        summaries.push((
            summary,
            ResolveOpts {
                dev_deps: false,
                features: RequestedFeatures::DepFeatures {
                    features: Default::default(),
                    uses_default_features: true,
                },
            },
        ));
    }

    // Resolve transitive dependencies.
    let mut registry = PackageRegistry::new(&config).expect("Unable to create package registry");
    registry.lock_patches();
    let try_to_use = Default::default();
    let resolve = resolver::resolve(&summaries, &[], &mut registry, &try_to_use, None, true)
        .expect("Unable to resolve dependencies");

    // Find crates incompatible with the playground's platform
    let mut valid_for_our_platform: BTreeSet<_> =
        summaries.iter().map(|(s, _)| s.package_id()).collect();

    let ct =
        CompileTarget::new(PLAYGROUND_TARGET_PLATFORM).expect("Unable to create a CompileTarget");
    let ck = CompileKind::Target(ct);
    let rustc = config
        .load_global_rustc(None)
        .expect("Unable to load the global rustc");

    let ti = TargetInfo::new(&config, &[ck], &rustc, ck).expect("Unable to create a TargetInfo");
    let cc = ti.cfg();

    let mut to_visit = valid_for_our_platform.clone();

    while !to_visit.is_empty() {
        let mut visit_next = BTreeSet::new();

        for package_id in to_visit {
            for (dep_pkg, deps) in resolve.deps(package_id) {
                let for_this_platform = deps.iter().any(|dep| {
                    dep.platform().map_or(true, |platform| {
                        platform.matches(PLAYGROUND_TARGET_PLATFORM, cc)
                    })
                });

                if for_this_platform {
                    valid_for_our_platform.insert(dep_pkg);
                    visit_next.insert(dep_pkg);
                }
            }
        }

        to_visit = visit_next;
    }

    // Remove invalid and excluded packages that have been added due to resolution
    let package_ids: Vec<_> = resolve
        .iter()
        .filter(|pkg| valid_for_our_platform.contains(pkg))
        .filter(|pkg| !modifications.excluded(pkg.name().as_str()))
        .collect();

    let mut sources = SourceMap::new();
    sources.insert(Box::new(source));

    let package_set =
        PackageSet::new(&package_ids, sources, &config).expect("Unable to create a PackageSet");

    let mut packages = package_set
        .get_many(package_set.package_ids())
        .expect("Unable to download packages");

    // Sort all packages by name then version (descending), so that
    // when we group them we know we get all the same crates together
    // and the newest version first.
    packages.sort_by(|a, b| {
        a.name()
            .cmp(&b.name())
            .then(a.version().cmp(&b.version()).reverse())
    });

    let mut infos = HashMap::new();

    for (name, pkgs) in &packages.into_iter().group_by(|pkg| pkg.name()) {
        let mut first = true;

        for pkg in pkgs {
            let version = pkg.version();

            let crate_name = pkg
                .targets()
                .iter()
                .flat_map(|target| match target.kind() {
                    TargetKind::Lib(_) => Some(target.crate_name()),
                    TargetKind::Bin => Some(target.crate_name()),
                    _ => None,
                })
                .next()
                .unwrap_or_else(|| panic!("{} did not have a library", name));

            // We see the newest version first. Any subsequent
            // versions will have their version appended so that they
            // are uniquely named
            let exposed_name = if first {
                crate_name.clone()
            } else {
                format!(
                    "{}_{}_{}_{}",
                    crate_name, version.major, version.minor, version.patch
                )
            };

            infos.insert(
                exposed_name.clone(),
                CrateInformation {
                    name: name.to_string(),
                    version: version.to_string(),
                    id: exposed_name,
                },
            );

            first = false;
        }
    }

    infos
}
