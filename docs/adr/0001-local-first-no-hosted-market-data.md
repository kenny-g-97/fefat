# ADR-0001: Local-first, and FEFAT never hosts or ships market data

Decision log: [D-02](../masterplan/DECISIONS.md), 2026-10-05/06 (planning)

## Context

Hosting CME market data for customers needs exchange licences, which cost about $21k to $130k a year. Databento licenses its data for internal use only.

## Decision

FEFAT is local-first: it never hosts or ships market data.

## Consequences

Customers bring their own data and their own vendor keys. The importer and the data folder are per machine.

## How we would know it is wrong

If traders needed ready-to-use data for the main products to get started, and the licences to deliver it became worth their cost.

## Status

Superseded by [ADR-0013](0013-platform-data-and-own-imports.md) (D-24, 2026-10-08): FEFAT now provides market data for a curated set of products, and compute stays local. Recorded in step 0.7.
