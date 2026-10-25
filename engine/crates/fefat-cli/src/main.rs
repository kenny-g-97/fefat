//! Command-line driver: spec in, artifacts out; golden tests and benchmarks. Today it writes the
//! JSON schema of the strategy specification, which `just gen-schema` keeps in the SDK, and
//! prints the determinism digest, whose golden `just regenerate-goldens` writes into
//! `fixtures/goldens/determinism/`.

mod determinism;
mod seeded_tape;

use std::path::Path;
use std::process::ExitCode;

use fefat_core::strategy_spec::schema_text;

const USAGE: &str =
    "usage: fefat-cli schema <path> | fefat-cli determinism <seed> [--write <manifest path>]";

fn main() -> ExitCode {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    match arguments.as_slice() {
        [command, path] if command == "schema" => write_schema(path),
        [command, seed] if command == "determinism" => print_digest(seed, None),
        [command, seed, flag, path] if command == "determinism" && flag == "--write" => {
            print_digest(seed, Some(Path::new(path)))
        }
        _ => {
            eprintln!("{USAGE}");
            ExitCode::from(2)
        }
    }
}

/// Writes the JSON schema of `StrategySpec` to `path`.
fn write_schema(path: &str) -> ExitCode {
    match std::fs::write(path, schema_text()) {
        Ok(()) => {
            println!("Wrote the StrategySpec schema to {path}");
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("Expected to write the StrategySpec schema to {path}, got: {error}");
            ExitCode::FAILURE
        }
    }
}

/// Prints the determinism digest of `seed` alone on its line, and writes its golden manifest to
/// `manifest` when one is named.
fn print_digest(seed: &str, manifest: Option<&Path>) -> ExitCode {
    let Ok(seed) = seed.parse::<u64>() else {
        eprintln!(
            "Expected a seed as a whole number from 0 to {}, got {seed}",
            u64::MAX
        );
        return ExitCode::from(2);
    };
    let digest = match determinism::digest(seed) {
        Ok(digest) => digest,
        Err(error) => {
            eprintln!("Expected the determinism digest of seed {seed}, got: {error}");
            return ExitCode::FAILURE;
        }
    };
    println!("{digest}");
    match manifest {
        None => ExitCode::SUCCESS,
        Some(manifest) => write_golden(manifest, seed, &digest),
    }
}

/// Writes the golden manifest of `seed`'s `digest` to `path`, making its folder if needed.
fn write_golden(path: &Path, seed: u64, digest: &str) -> ExitCode {
    let written = determinism::golden_manifest(seed, digest)
        .map_err(|error| error.to_string())
        .and_then(|manifest| {
            let folder = path
                .parent()
                .filter(|folder| !folder.as_os_str().is_empty());
            folder
                .map_or(Ok(()), std::fs::create_dir_all)
                .map_err(|error| error.to_string())?;
            std::fs::write(path, manifest).map_err(|error| error.to_string())
        });
    match written {
        Ok(()) => {
            println!("Wrote the determinism golden to {}", path.display());
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!(
                "Expected to write the determinism golden to {}, got: {error}",
                path.display()
            );
            ExitCode::FAILURE
        }
    }
}
