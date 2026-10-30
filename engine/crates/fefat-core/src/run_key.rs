//! The engine's versions and the run key (`02` §4, ADR-0009): BLAKE3 over everything a run's
//! output depends on, the strategy specification, the run's settings with every default applied
//! (step 2.10), the signal frame's hash, the hashes of the data it reads, and the engine,
//! fill-model, and artifact-schema versions, so that a change to what a run produces changes its
//! key (D-11). The versions are bumped by hand and never taken from the crate's version (Phase 2's
//! conventions, the `engine-golden` skill).

use serde::Serialize;
use serde_json::Value;
use thiserror::Error;

use crate::strategy_spec::StrategySpec;

/// A version bumped by hand.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Version(pub u32);

/// Bumped for any change of what a run produces that changes neither its fills nor the layout of
/// its artifacts: 8 since step 2.12, whose runs record the fidelity era of each trade date and
/// their fidelity check, and build their signal bars from the level that covers their window,
/// after 7 of step 2.11, whose runs record their metrics in `run.json`, and 6 of step 2.10, whose
/// run key covers the run's settings and whose runs record their trades, their equity at each
/// decision, and each fill's trade date.
pub const ENGINE_VERSION: Version = Version(8);
/// Bumped when fills change (`02` §8), with the builder's approval and the goldens regenerated.
pub const FILL_MODEL_VERSION: Version = Version(1);
/// Bumped when the layout of a run's artifacts changes: 2 since step 2.13, whose runs store each
/// trade's path as `trade_paths` and its fall from its peak and its path's fidelity in `trades`,
/// after 1, the artifacts' first layout of step 2.10.
pub const ARTIFACT_SCHEMA_VERSION: Version = Version(2);

/// The versions a run key covers, in the order it hashes them.
pub const VERSIONS: [Version; 3] = [ENGINE_VERSION, FILL_MODEL_VERSION, ARTIFACT_SCHEMA_VERSION];

const DOMAIN: &[u8] = b"fefat run key 2\n";

/// A run key: BLAKE3 as 64 lower-case hexadecimal digits (`01-architecture.md`).
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct RunKey(String);

impl RunKey {
    /// The key's 64 hexadecimal digits.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Why a run key could not be worked out.
#[derive(Debug, Error)]
pub enum RunKeyError {
    /// Serde could not write the specification or the settings as JSON.
    #[error("Expected a strategy specification and settings that serde writes as JSON, got: {0}")]
    Json(#[from] serde_json::Error),
    /// A number JSON cannot hold, NaN or an infinity, which serde writes as null, so that two
    /// specifications would share one key.
    #[error(
        "Expected finite numbers in the strategy specification, got NaN or an infinity at {path}"
    )]
    NonFiniteNumber {
        /// Where in the specification, such as `spec.execution.sizing.units`.
        path: String,
    },
}

/// The key of a run of `spec` under `settings` on the signal frame hashed `signal_frame_hash`,
/// reading the data hashed `partition_hashes`, in any order, by this build's [`VERSIONS`]. The
/// spec and the settings are hashed as the JSON serde writes for them, so that the layout of a
/// document someone typed never changes the key; a spec with NaN or an infinity, which that JSON
/// cannot hold, is refused. The settings are a run's config (`fefat_run::config::RunConfig`),
/// integers and words alone.
pub fn run_key(
    spec: &StrategySpec,
    settings: &impl Serialize,
    signal_frame_hash: &str,
    partition_hashes: &[String],
) -> Result<RunKey, RunKeyError> {
    if let Some(path) = null_at(&serde_json::to_value(spec)?, "spec") {
        return Err(RunKeyError::NonFiniteNumber { path });
    }
    let spec_json = serde_json::to_vec(spec)?;
    let settings_json = serde_json::to_vec(settings)?;
    Ok(key_of(
        &spec_json,
        &settings_json,
        signal_frame_hash,
        partition_hashes,
        VERSIONS,
    ))
}

/// The path of the first null in `value`, which only a number JSON cannot hold puts there: a
/// specification leaves an unused rule out rather than writing null (D-53).
fn null_at(value: &Value, path: &str) -> Option<String> {
    match value {
        Value::Null => Some(path.to_owned()),
        Value::Array(items) => items
            .iter()
            .enumerate()
            .find_map(|(index, item)| null_at(item, &format!("{path}[{index}]"))),
        Value::Object(fields) => fields
            .iter()
            .find_map(|(name, field)| null_at(field, &format!("{path}.{name}"))),
        Value::Bool(_) | Value::Number(_) | Value::String(_) => None,
    }
}

/// BLAKE3 over a domain tag and the parts, each framed by its length so that no two inputs give
/// the same bytes: the specification's JSON, the settings' JSON, the signal frame's hash, the
/// partition hashes sorted, and the versions.
fn key_of(
    spec_json: &[u8],
    settings_json: &[u8],
    signal_frame_hash: &str,
    partition_hashes: &[String],
    versions: [Version; 3],
) -> RunKey {
    let mut partitions: Vec<&str> = partition_hashes.iter().map(String::as_str).collect();
    partitions.sort_unstable();
    let mut hasher = blake3::Hasher::new();
    hasher.update(DOMAIN);
    framed(&mut hasher, spec_json);
    framed(&mut hasher, settings_json);
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
    use serde_json::json;

    use super::*;

    const FRAME: &str = "signal frame hash";
    const SETTINGS: &[u8] = br#"{"latency_ms":100}"#;

    fn spec(timeframe: &str) -> StrategySpec {
        let document = format!(
            r#"{{"spec_version": 1, "instrument": "ES", "timeframe": "{timeframe}",
                "execution": {{"entry": {{"kind": "market"}}, "sizing": {{"kind": "fixed", "units": 1}}}}}}"#
        );
        serde_json::from_str(&document).unwrap()
    }

    fn settings(market_ticks: u32) -> Value {
        json!({"latency_ms": 100, "slippage_ticks": {"market": market_ticks, "stop": 1}})
    }

    fn partitions() -> Vec<String> {
        vec!["a".repeat(64), "b".repeat(64)]
    }

    #[test]
    fn a_run_key_is_64_lower_case_hexadecimal_digits_and_the_same_for_the_same_inputs() {
        let key = run_key(&spec("5m"), &settings(1), FRAME, &partitions()).unwrap();
        assert_eq!(key.as_str().len(), 64);
        assert!(
            key.as_str()
                .chars()
                .all(|digit| matches!(digit, '0'..='9' | 'a'..='f'))
        );
        assert_eq!(
            run_key(&spec("5m"), &settings(1), FRAME, &partitions()).unwrap(),
            key
        );
    }

    #[test]
    fn a_setting_changes_the_key() {
        // Step 2.10 (BACKLOG's run settings in the run key): one slippage tick is another run.
        let one_tick = run_key(&spec("5m"), &settings(1), FRAME, &partitions()).unwrap();
        let two_ticks = run_key(&spec("5m"), &settings(2), FRAME, &partitions()).unwrap();
        assert_ne!(one_tick, two_ticks);
    }

    #[test]
    fn every_input_and_every_version_changes_the_key() {
        let spec_json = serde_json::to_vec(&spec("5m")).unwrap();
        let base = key_of(&spec_json, SETTINGS, FRAME, &partitions(), VERSIONS);
        let [engine, fill_model, artifact_schema] = VERSIONS;
        let changed = [
            key_of(
                &serde_json::to_vec(&spec("1m")).unwrap(),
                SETTINGS,
                FRAME,
                &partitions(),
                VERSIONS,
            ),
            key_of(
                &spec_json,
                br#"{"latency_ms":0}"#,
                FRAME,
                &partitions(),
                VERSIONS,
            ),
            key_of(
                &spec_json,
                SETTINGS,
                "another signal frame hash",
                &partitions(),
                VERSIONS,
            ),
            key_of(&spec_json, SETTINGS, FRAME, &partitions()[..1], VERSIONS),
            key_of(
                &spec_json,
                SETTINGS,
                FRAME,
                &partitions(),
                [Version(engine.0 + 1), fill_model, artifact_schema],
            ),
            key_of(
                &spec_json,
                SETTINGS,
                FRAME,
                &partitions(),
                [engine, Version(fill_model.0 + 1), artifact_schema],
            ),
            key_of(
                &spec_json,
                SETTINGS,
                FRAME,
                &partitions(),
                [engine, fill_model, Version(artifact_schema.0 + 1)],
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
            run_key(&spec("5m"), &settings(1), FRAME, &reversed).unwrap(),
            run_key(&spec("5m"), &settings(1), FRAME, &partitions()).unwrap()
        );
    }

    #[test]
    fn framing_keeps_the_parts_apart() {
        let joined = key_of(b"{}", b"{}", "ab", &["c".to_owned()], VERSIONS);
        let split_elsewhere = key_of(b"{}", b"{}", "a", &["bc".to_owned()], VERSIONS);
        let moved_between_documents = key_of(b"{}{", b"}", "ab", &["c".to_owned()], VERSIONS);
        assert_ne!(joined, split_elsewhere);
        assert_ne!(joined, moved_between_documents);
    }

    #[test]
    fn the_layout_of_a_typed_document_does_not_change_the_key() {
        let typed = r#"{ "timeframe" : "5m", "instrument": "ES", "spec_version": 1,
            "execution": { "sizing": { "units": 1, "kind": "fixed" }, "entry": { "kind": "market" } } }"#;
        let typed: StrategySpec = serde_json::from_str(typed).unwrap();
        assert_eq!(
            run_key(&typed, &settings(1), FRAME, &partitions()).unwrap(),
            run_key(&spec("5m"), &settings(1), FRAME, &partitions()).unwrap()
        );
    }

    #[test]
    fn a_spec_with_a_number_json_cannot_write_is_refused() {
        let sized = |units: f64| {
            let mut spec = spec("5m");
            spec.execution.sizing = crate::strategy_spec::Sizing::Fixed { units };
            spec
        };
        let key = |units: f64| run_key(&sized(units), &settings(1), FRAME, &partitions());
        assert!(key(f64::NAN).is_err());
        assert!(key(f64::INFINITY).is_err());
        assert_eq!(
            key(f64::NEG_INFINITY).unwrap_err().to_string(),
            "Expected finite numbers in the strategy specification, got NaN or an infinity at \
             spec.execution.sizing.units"
        );
    }
}
