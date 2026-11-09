"""The jobs' process pool (step 4.4, `01-architecture.md` section 6, D-16): an adapter of the
`Dispatcher` port. `worker` runs one job in a process of the pool, keeping its lease while the
work runs; `progress` is how the work reports, between its chunks, and learns it must stop;
`demo` is the one kind of work so far, which counts seconds; and `dispatcher` submits jobs to the
pool and reaps those whose workers stopped answering or were asked to stop."""
