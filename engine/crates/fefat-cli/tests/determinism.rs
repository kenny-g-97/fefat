//! The determinism harness of step 2.4 (Done means 2): two processes print one digest, the
//! golden's, which both CI systems, Windows and Ubuntu, check against the same manifest.

use std::error::Error;
use std::process::Command;

use fefat_core::run_key::VERSIONS;
use serde_json::Value;

const GOLDEN: &str = include_str!("../../../../fixtures/goldens/determinism/MANIFEST.json");

/// The digest a new `fefat-cli determinism <seed>` process prints.
fn digest_printed_by_a_new_process(seed: u64) -> Result<String, Box<dyn Error>> {
    let output = Command::new(env!("CARGO_BIN_EXE_fefat-cli"))
        .args(["determinism", &seed.to_string()])
        .output()?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!(
            "Expected fefat-cli determinism to succeed, got {}: {stderr}",
            output.status
        )
        .into());
    }
    Ok(String::from_utf8(output.stdout)?.trim().to_owned())
}

fn golden() -> Result<Value, serde_json::Error> {
    serde_json::from_str(GOLDEN)
}

#[test]
fn two_processes_print_the_golden_digest() {
    let golden = golden().unwrap();
    let seed = golden["inputs"]["seed"].as_u64().unwrap();
    let first = digest_printed_by_a_new_process(seed).unwrap();
    let second = digest_printed_by_a_new_process(seed).unwrap();
    assert_eq!(
        first, second,
        "two processes printed different digests of seed {seed}"
    );
    assert_eq!(
        first,
        golden["outputs"]["digest"].as_str().unwrap(),
        "Expected the digest of fixtures/goldens/determinism/MANIFEST.json; a change of what the \
         engine computes changes it only with the builder's approval, a version bump, and \
         `just regenerate-goldens` (the engine-golden skill)"
    );
}

#[test]
fn the_golden_was_written_by_this_builds_versions() {
    let golden = golden().unwrap();
    let written =
        ["engine", "fill_model", "artifact_schema"].map(|name| golden["versions"][name].as_u64());
    assert_eq!(
        written,
        VERSIONS.map(|version| Some(u64::from(version.0))),
        "Expected the golden's versions to be this build's: regenerate the goldens after a version \
         bump (the engine-golden skill)"
    );
}
