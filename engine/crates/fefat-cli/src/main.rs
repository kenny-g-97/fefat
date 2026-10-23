//! Command-line driver: spec in, artifacts out; golden tests and benchmarks. Today it writes the
//! JSON schema of the strategy specification, which `just gen-schema` keeps in the SDK.

use std::process::ExitCode;

use fefat_core::strategy_spec::schema_text;

const USAGE: &str = "usage: fefat-cli schema <path>";

fn main() -> ExitCode {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    match arguments.as_slice() {
        [command, path] if command == "schema" => write_schema(path),
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
