//! The dependency rule of `08-code-design.md` §1.5: no engine crate depends on `fefat-data`, the
//! only crate that opens files, but `fefat-py` and `fefat-cli`, which wire it into the engine.

use std::error::Error;
use std::process::Command;

use serde_json::Value;

const MAY_DEPEND_ON_THE_DATA_CRATE: [&str; 2] = ["fefat-cli", "fefat-py"];

/// A package of the workspace and the names of the packages it depends on, of every kind.
#[derive(Debug)]
struct Package {
    name: String,
    dependencies: Vec<String>,
}

/// The workspace's packages, as `cargo metadata` lists them.
fn workspace_packages() -> Result<Vec<Package>, Box<dyn Error>> {
    let manifest = concat!(env!("CARGO_MANIFEST_DIR"), "/../../Cargo.toml");
    let output = Command::new(env!("CARGO"))
        .args([
            "metadata",
            "--format-version",
            "1",
            "--no-deps",
            "--manifest-path",
            manifest,
        ])
        .output()?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!(
            "Expected cargo metadata to succeed, got {}: {stderr}",
            output.status
        )
        .into());
    }
    let metadata: Value = serde_json::from_slice(&output.stdout)?;
    let packages = metadata.get("packages").and_then(Value::as_array);
    let packages = packages.ok_or("Expected cargo metadata to list the packages")?;
    packages.iter().map(package).collect()
}

fn package(listed: &Value) -> Result<Package, Box<dyn Error>> {
    let name = listed.get("name").and_then(Value::as_str);
    let name = name.ok_or("Expected each package to have a name")?;
    let dependencies = listed.get("dependencies").and_then(Value::as_array);
    let dependencies = dependencies
        .ok_or_else(|| format!("Expected cargo metadata to list the dependencies of {name}"))?;
    let names: Option<Vec<String>> = dependencies
        .iter()
        .map(|dependency| {
            dependency
                .get("name")
                .and_then(Value::as_str)
                .map(str::to_owned)
        })
        .collect();
    let dependencies =
        names.ok_or_else(|| format!("Expected every dependency of {name} to have a name"))?;
    Ok(Package {
        name: name.to_owned(),
        dependencies,
    })
}

#[test]
fn only_the_python_module_and_the_cli_depend_on_the_data_crate() {
    let packages = workspace_packages().unwrap();
    assert!(
        packages.iter().any(|package| package.name == "fefat-data"),
        "{packages:?}"
    );
    let dependents: Vec<&str> = packages
        .iter()
        .filter(|package| package.dependencies.iter().any(|name| name == "fefat-data"))
        .map(|package| package.name.as_str())
        .collect();
    assert!(
        dependents
            .iter()
            .all(|name| MAY_DEPEND_ON_THE_DATA_CRATE.contains(name)),
        "Expected only fefat-py and fefat-cli to depend on fefat-data (08-code-design.md §1.5), \
         got {dependents:?}"
    );
}
