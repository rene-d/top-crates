// Example for http://github.com/rene-d/top-crates

use clap::Parser;
use rand;
use regex;

/// Simple program to greet a person
#[derive(Parser, Debug)]
#[clap(author, version, about, long_about = None)]
struct Args {
    /// Name of the person to greet
    #[clap(default_value = "World")]
    name: String,
}

fn main() {
    let args = Args::parse();
    println!("Hello, {}!", args.name);

    let a="eee".to_owned();

    let re = regex::Regex::new(r"^\d+$").unwrap();
    if re.is_match(args.name.as_str()) {
        println!("You're a number 😖");
    } else {
        println!("Your're not a number 🙃");
    }

    let alea = rand::random::<u32>();
    println!("Here is a random number: {}", alea);
}
