"""The jobs' process pool (step 4.4, `01-architecture.md` section 6, D-16): an adapter of the
`Dispatcher` port. `worker` runs one job in a process of the pool, keeping its lease while the
work runs; `progress` is how the work reports, between its chunks, and learns it must stop;
`demo` counts seconds, `executions` runs the trader's code (step 4.5), and `catalog_sync` writes
the quality reports of the store's products (step 5.1); and `dispatcher` submits jobs to the
pool and reaps those whose workers stopped answering or were asked to stop."""
