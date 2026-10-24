//! The engine's versions and the run key (`02` §4, ADR-0009): BLAKE3 over everything a run's
//! output depends on, the strategy specification, the signal frame's hash, the hashes of the data
//! partitions it reads, and the engine, fill-model, and artifact-schema versions, so that a change
//! to what a run produces changes its key (D-11). The versions are bumped by hand and never taken
//! from the crate's version (Phase 2's conventions, the `engine-golden` skill).

use std::fmt;

use thiserror::Error;

use crate::strategy_spec::StrategySpec;

/// A version bumped by hand.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Version(pub u32);

/// Bumped for any change of what a run produces that changes neither its fills nor the layout of
/// its artifacts.
pub const ENGINE_VERSION: Version = Version(1);
/// Bumped when fills change (`02` §8), with the builder's approval and the goldens regenerated.
pub const FILL_MODEL_VERSION: Version = Version(1);
/// Bumped when the layout of a run's artifacts changes.
pub const ARTIFACT_SCHEMA_VERSION: Version = Version(1);

/// The versions a run key covers, in the order it hashes them.
pub const VERSIONS: [Version; 3] = [ENGINE_VERSION, FILL_MODEL_VERSION, ARTIFACT_SCHEMA_VERSION];

const DOMAIN: &[u8] = b"fefat run key 1\n";

/// A run key: BLAKE3 as 64 lower-case hexadecimal digits (`01-architecture.md`).
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct RunKey(String);

impl RunKey {
    /// The key's 64 hexadecimal digits.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for RunKey {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

/// A specification serde could not write as JSON.
#[derive(Debug, Error)]
#[error("Expected a strategy specification that serde writes as JSON, got: {0}")]
pub struct RunKeyError(#[from] serde_json::Error);

/// The key of a run of `spec` on the signal frame hashed `signal_frame_hash`, reading the data
/// partitions hashed `partition_hashes`, in any order, by this build's [`VERSIONS`]. The spec is
/// hashed as the JSON serde writes for it, so that the layout of a document someone typed never
/// changes the key.
pub fn run_key(
    spec: &StrategySpec,
    signal_frame_hash: &str,
    partition_hashes: &[String],
) -> Result<RunKey, RunKeyError> {
    let spec_json = serde_json::to_vec(spec)?;
    Ok(key_of(
        &spec_json,
        signal_frame_hash,
        partition_hashes,
        VERSIONS,
    ))
}

/// BLAKE3 over a domain tag and the parts, each framed by its length so that no two inputs give
/// the same bytes: the specification's JSON, the signal frame's hash, the partition hashes
/// sorted, and the versions.
fn key_of(
    spec_json: &[u8],
    signal_frame_hash: &str,
    partition_hashes: &[String],
    versions: [Version; 3],
) -> RunKey {
    let mut partitions: Vec<&str> = partition_hashes.iter().map(String::as_str).collect();
    partitions.sort_unstable();
    let mut hasher = blake3::Hasher::new();
    hasher.update(DOMAIN);
    framed(&mut hasher, spec_json);
    framed(&mut hasher, signal_frame_hash.as_bytes());
    hasher.update(&(partitions.len() as u64).to_le_bytes());
    for partition in partitions {
        framed(&mut hasher, partition.as_bytes());
    }
    for version in versions {
        hasher.update(&version.0.to_le_bytes());
    }
    RunKey(hasher.finalize().to_hex().to_string())
}

fn framed(hasher: &mut blake3::Hasher, part: &[u8]) {
    hasher.update(&(part.len() as u64).to_le_bytes());
    hasher.update(part);
}

#[cfg(test)]
mod tests {
    use super::*;

    const FRAME: &str = "signal frame hash";

    fn spec(timeframe: &str) -> StrategySpec {
        let document = format!(
            r#"{{"spec_version": 1, "instrument": "ES", "timeframe": "{timeframe}",
                "execution": {{"entry": {{"kind": "market"}}, "sizing": {{"kind": "fixed", "units": 1}}}}}}"#
        );
        serde_json::from_str(&document).unwrap()
    }

    fn partitions() -> Vec<String> {
        vec!["a".repeat(64), "b".repeat(64)]
    }

    #[test]
    fn a_run_key_is_64_lower_case_hexadecimal_digits_and_the_same_for_the_same_inputs() {
        let key = run_key(&spec("5m"), FRAME, &partitions()).unwrap();
        assert_eq!(key.as_str().len(), 64);
        assert!(
            key.as_str()
                .chars()
                .all(|digit| matches!(digit, '0'..='9' | 'a'..='f'))
        );
        assert_eq!(run_key(&spec("5m"), FRAME, &partitions()).unwrap(), key);
    }

    #[test]
    fn every_input_and_every_version_changes_the_key() {
        let spec_json = serde_json::to_vec(&spec("5m")).unwrap();
        let base = key_of(&spec_json, FRAME, &partitions(), VERSIONS);
        let [engine, fill_model, artifact_schema] = VERSIONS;
        let changed = [
            key_of(
                &serde_json::to_vec(&spec("1m")).unwrap(),
                FRAME,
                &partitions(),
                VERSIONS,
            ),
            key_of(
                &spec_json,
                "another signal frame hash",
                &partitions(),
                VERSIONS,
            ),
            key_of(&spec_json, FRAME, &partitions()[..1], VERSIONS),
            key_of(
                &spec_json,
                FRAME,
                &partitions(),
                [Version(2), fill_model, artifact_schema],
            ),
            key_of(
                &spec_json,
                FRAME,
                &partitions(),
                [engine, Version(2), artifact_schema],
            ),
            key_of(
                &spec_json,
                FRAME,
                &partitions(),
                [engine, fill_model, Version(2)],
            ),
        ];
        for key in changed {
            assert_ne!(key, base);
        }
    }

    #[test]
    fn the_order_of_the_partitions_does_not_change_the_key() {
        let mut reversed = partitions();
        reversed.reverse();
        assert_eq!(
            run_key(&spec("5m"), FRAME, &reversed).unwrap(),
            run_key(&spec("5m"), FRAME, &partitions()).unwrap()
        );
    }

    #[test]
    fn framing_keeps_the_parts_apart() {
        let joined = key_of(b"{}", "ab", &["c".to_owned()], VERSIONS);
        let split_elsewhere = key_of(b"{}", "a", &["bc".to_owned()], VERSIONS);
        assert_ne!(joined, split_elsewhere);
    }

    #[test]
    fn the_layout_of_a_typed_document_does_not_change_the_key() {
        let typed = r#"{ "timeframe" : "5m", "instrument": "ES", "spec_version": 1,
            "execution": { "sizing": { "units": 1, "kind": "fixed" }, "entry": { "kind": "market" } } }"#;
        let typed: StrategySpec = serde_json::from_str(typed).unwrap();
        assert_eq!(
            run_key(&typed, FRAME, &partitions()).unwrap(),
            run_key(&spec("5m"), FRAME, &partitions()).unwrap()
        );
    }
}
