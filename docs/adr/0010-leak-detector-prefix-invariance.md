# ADR-0010: A leak detector based on prefix invariance, run on save

Decision log: [D-12](../masterplan/DECISIONS.md), 2026-10-05/06 (planning)

## Context

Look-ahead is the most common silent error in feature research.

## Decision

A leak detector checks every feature for prefix invariance, and it runs whenever a feature is saved. A feature is prefix-invariant when its values before a cut never change after the data past the cut is removed.

## Consequences

Features declare their inputs and their warm-up. Alternative data carries an `available_at` timestamp.

## How we would know it is wrong

If a feature that passed the detector later proved to look ahead, or if the detector failed features that are provably prefix-invariant.

## Status

Accepted; recorded in step 0.7.
