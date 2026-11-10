# Phase 4 demo: the local app

What Phase 4 built, shown in about thirty minutes without reading code: FEAT running on your PC with `fefat up`, its login in your browser, a job whose progress you watch live, survive a reload, and cancel, and the executor that runs your own Python code within a time limit. Run everything in PowerShell from the repository folder, `C:\Users\<you>\Documents\AlgoTrading_app\FEFAT`, on `main` after the exit pull request is merged: `git switch main`, then `git pull --ff-only`, then `just setup` once, since the exit moved the lockfiles, then `just build-web`, which builds the web app that `fefat up` serves. Actions 1 to 4 are the everyday checks, 5 to 10 the exit prompt's demo in your browser, and 11 to 16 check what the exit changed.

What the exit changes on your PC: nothing in your data store or your feature library. The app's database keeps its tables and rows; the index of your workspace's files changes only if you run the new `--rebuild` yourself (action 13 does not). At its start, `fefat up` now removes what the executor left in `%LOCALAPPDATA%\FEFAT\cache\executions` more than a day ago.

1. **Check the tools.** Run `just doctor`.
   It prints the table of fourteen tools, each `OK` with its version, and ends with `All 14 tools OK on Windows (AMD64).`

2. **Run every check.** Run `just check`.
   It ends with `OK` after the masterplan checker, in under a minute.

3. **Run every test.** Run `just test`; it takes about twelve minutes.
   Four lines matter: `2978 passed` from pytest, `All 291 hook cases passed.` from the Claude Code guards, the `test result: ok.` lines of the Rust tests, 267 in all, and vitest's `Tests  9 passed (9)`. No line says `FAILED`.

4. **Run the UI harness.** A program outside FEAT keeps port 8766, the harness's own, open on this PC, so give the harness another port for this one run:

   ```text
   $env:FEFAT_E2E_PORT = "8767"; just e2e; Remove-Item Env:FEFAT_E2E_PORT
   ```

   It builds the web app, starts FEAT on a seeded home of its own, and drives Chromium through every page; it ends with `64 passed`, and its screenshots are in `web\test-results\screenshots\`. If Playwright says its browser is missing, run `pnpm --dir web exec playwright install chromium` once and run it again.

5. **Start the app.** Run `just up`.
   It prints `FEAT serves http://127.0.0.1:8765 to this computer alone; stop it with Ctrl+C.` and `The web app: built, at http://127.0.0.1:8765.` Open that address in your browser and log in with your password. If the second line says `not built yet`, stop the server with Ctrl+C, run `just build-web`, and start it again.

6. **Start the demo job.** Open Settings and click _Run demo job_ under Demo job.
   It says `Demo job queued`, and the jobs button at the top right shows a `1`. Click it: the drawer lists `Demo job`, its badge `Running`, a bar, and a line such as `Counted 3 of 60`, its count rising each second. Home's `Running jobs` card shows the same job and bar.

7. **Reload midway.** When the bar is at about a third, press F5.
   After the reload the bar stands where it was, or a little further, never further back, and keeps moving. The reload opens the job's stream of events again, and the bar skips the reports it has already shown.

8. **Cancel it.** Open the drawer and click _Cancel_ on the job's row.
   The badge reads `Cancelling`, then within two seconds `Cancelled`, with `Ended` and the time, and the last count stays under it; the bar goes, the jobs button loses its count, and Home's card reads `No jobs running.`

9. **Exit check: two tabs and three jobs.** Open the app in a second tab, click _Run demo job_ three times there, then switch between the two tabs and click through the pages: every page answers at once, and _Cancel_ works in both. Before the exit, two tabs following three jobs took all six of the browser's connections to the server, and both froze until a reload. Cancel the three jobs.

10. **The theme and an API token.** In Settings, choose _Light_ under Appearance and reload: the page stays light, since the server keeps your choice. Choose _Dark_ again. Under API tokens, type `demo`, click _Create token_, and _Copy_. In a second PowerShell window, run, with the token pasted in place of `<token>`:

    ```text
    curl.exe -i -H "Authorization: Bearer <token>" http://127.0.0.1:8765/v1/me
    ```

    It answers `HTTP/1.1 200 OK` and `"name":"demo"`. Click _Revoke_, then _Revoke now_, and run the same command: it answers `HTTP/1.1 401 Unauthorized`.

11. **Exit check: the API's docs work offline.** Open `http://127.0.0.1:8765/docs` and log in on its page if it asks: the interactive docs of FEAT's API load. Turn Wi-Fi off, or unplug the network cable, and reload: they still load, since the app now serves Swagger UI itself, where it fetched it from a website before. Turn the network back on, then stop the server with Ctrl+C in its window.

12. **The executor.** Open `notebooks/checks/4.05.ipynb` in VS Code, pick the `.venv` kernel (Python 3.12) at the top right, and click _Run All_.
    It prints `30% Running the snippet`, then `timed_out after 5.0 s`: a snippet that sleeps 30 seconds stopped at its 5-second limit. The last cell prints `PASSED` twice: no runner still runs, and nothing is left in the executions' folder.

13. **Exit check: rebuilding the index.** Run:

    ```text
    uv run pytest python/tests/test_database_commands.py python/tests/test_database_workspace_index.py -k rebuild -q
    ```

    It prints `2 passed`. A feature version file deleted or replaced by hand used to stop `fefat db import-workspace` for good, the index being kept insert-only, and deleting the database to index anew would have lost your password, sessions, and tokens. Now `fefat db import-workspace --rebuild` indexes the files as they are and keeps the rest. Run it on your own folder only when the plain command refuses: it also drops the index's rows of reports that a later validation replaced.

14. **Exit checks: the jobs.** Run:

    ```text
    uv run pytest python/tests/server/test_local_dispatcher.py python/tests/server/test_services_jobs.py python/tests/server/test_job_records.py -k "hung_inside_a_write or server_slept or older_than_the_hundred or meets_a_requeue or not_queued_again or snippet_job_runs" -q
    ```

    It prints `6 passed` in about ten seconds. Before the exit: a job whose worker hung while writing to the database ran for ever, since the hang blocked the reaper's every change; after the PC slept, a healthy worker could be ended a few seconds after the wake; a queue of a hundred newer jobs hid the running ones and their Cancel; and a Cancel clicked as the reaper requeued a job could be lost, so the job ran again.

15. **Exit checks: the study, the executor's folder, and the runner.** Run:

    ```text
    uv run pytest python/tests/test_analytics_study.py python/tests/test_server_commands.py python/tests/server/test_executor_preview.py -k "same_at_each_run or executions_left or empty_entry_of_pythonpath" -q
    ```

    It prints `3 passed`. The feature study's quantile returns are now the same at every run, where their last digits changed from run to run; `fefat up` clears what executions left behind; and a runner never imports a file from its working folder, which a stray separator in `PYTHONPATH` allowed.

16. **Exit check: the reviewers are still read-only.** Start a new Claude Code session and type: _Run the step-reviewer subagent and ask it to run `printf probe`, then report what happened._
    The reviewer reports `Reviewers are read-only: "printf probe" is not on the read-only list.`: the hook knows the agent as a reviewer and checks its every command, on Claude Code 2.1.319 as on 2.1.318.

Then check the exit pull request's Checks tab: the Ubuntu job now has a step `Run the UI harness`, green, which runs action 4's harness on every pull request.

Afterwards, tag the phase as the exit pull request describes: `git tag phase-4`, then `git push origin phase-4`.
