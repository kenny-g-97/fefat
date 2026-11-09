"""The executor (step 4.5, `01-architecture.md` section 6, D-16): the trader's code, a feature's
preview or a snippet of Python, runs in a runner, a process of the workspace's interpreter started
as `python -m fefat_app.executor`, never in the server's own process.

What it protects the app against: code that loops for ever, which the runner's timeout stops with
every process the code started; code that allocates without end, whose allocation fails at the
memory limit, a Job Object's on Windows and the runner's address space on Linux, as a
`MemoryError` that fails the execution; code that crashes or ends its process, which costs the
runner alone, a warm runner being started again for the next preview; a result that is not one,
or too large, which is refused before the app reads it; and the server's own secrets, since the
runner's environment holds the system's variables and FEFAT's folders alone, and keyring's null
backend, which gives no key.

What it does not protect against, being crash containment and not a security boundary, since a
trader runs their own code on their own machine: code that reads or writes a file the trader may,
FEFAT's home and the data folder included, read-only by convention alone; code that reads the
Windows credential store, or another secret, through the operating system's own interfaces; the
network; the processor time of the machine's other processes, short of the timeout; the disk
that code fills; and code that leaves its Job Object or its session on purpose."""
