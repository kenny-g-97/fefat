# Phase 15 — FEAT as a Claude desktop app

**Goal.** FEAT opens like any other program on your PC: the web app, published as a Claude artifact and installed from Claude Desktop with "Install as app" (D-127), runs in a window of its own with the FEAT icon, reaches the local server, says what to do when the server is down, tells you when a job finishes, and updates itself when the artifact is published again. No installer, no signing, nothing to package: the server stays `fefat up` on this PC, and the browser keeps working as before.

**You get.** FEAT in the Start menu, a tray icon with your running jobs, and a notification when a backtest finishes behind another window, for $0 beyond the Claude plan you already pay.

**Depends on.** Phase 5 (the web MVP of step 5.13). It runs before Phase 6 by default; its rows in `PROGRESS.md` can move to any later kickoff.

**Open decisions for the kickoff.** Whether the app frames the local server's pages or carries the web app's files itself (step 15.1 decides with evidence; the kickoff confirms the questions it must answer); whether the app may start `fefat up` itself, which needs full access to this computer, or only tells you how; where the app keeps its token for the local server, if it needs one, and how it is revoked; the port and the home folder it uses; whether anyone else ever installs it (another person gets at most the app permissions, never full access, and needs FEFAT running from source until Phase 14).

## Kickoff

```text
/phase-kickoff 15 — Read docs/masterplan/phases/P15-claude-desktop-app.md, docs/masterplan/01-architecture.md §8, docs/adr/0025-agent-on-sign-in-with-chatgpt-and-an-mcp-server.md, the artifact-capabilities skill with the desktop capability's type definitions, and Anthropic's help page "Install an artifact as an app"; note what the beta allows that day (platforms, permissions, what cannot be installed). Ask me the open decisions; reconcile the steps.
```

## Steps

### 15.1 Desktop app spike and decision record

Depends on: 5.13 · Plan mode: required · Reviews: step-reviewer · Security: yes · Model hint: hard

#### Purpose

How an installed Claude app reaches the local server is decided with evidence from this PC, before anything is built on it.

#### Prerequisites

- Phase 15 kickoff done.
- Claude for Windows 6.28899.0 or later, signed in; `fefat up` running (`just up`).

#### Prompt

```text
Masterplan step 15.1 — Desktop app spike and decision record.

Read docs/masterplan/01-architecture.md §8 and the artifact-capabilities skill (the desktop capability and its type definitions). Spike two shapes of FEAT as an installed Claude app on this PC, each published as a throwaway artifact from a scratch folder and installed from Claude Desktop: (a) a page that frames the local server at its address, and (b) the built web app published as the artifact's own files, asking the API at that address. For each, record what the installed window allows (the artifact's content security policy, requests and frames to 127.0.0.1, the Default permission tier against app permissions and full access), what the local server would have to admit (a frame ancestor, an origin, the session cookie's SameSite rule or a bearer token in its place), and whether login, the pages, the job stream, an upload, and the lazily loaded charts work; then what the app shows with the server down, offline, and after a republish, when Claude asks for its permissions again. Try starting `fefat up` from the app through the desktop capability's child process. Measure rather than guess: a screenshot per finding.

Write docs/adr/NNNN-claude-desktop-app.md: the chosen shape, the measurements, the risks (a beta that can change, an app that opens only online and signed in), the server changes it needs, each behind a setting that is off by default, and the fallback if neither shape reaches the server: a launcher that starts it, shows the jobs in the tray, notifies, and opens FEAT in the browser. Delete the throwaway artifacts and record nothing private (no paths, no token).

Not in this step: the real app, the server changes, the publish skill, notifications.
```

#### Done means

1. Both shapes were tried on this PC; the ADR states the choice, what each could and could not do, and the server changes needed, with the screenshots in docs/validation/screenshots/15.1/.
2. The chosen shape shows the local server's login page inside an installed app's window (screenshot).
3. The throwaway artifacts are deleted, and the ADR holds no path or token.

#### Your checks

- Open the spike app from the Start menu's Claude Apps folder: a window opens with FEAT's icon and you log in to your local server in it; stop `fefat up` and the window says so rather than hanging.

#### If it fails

- Neither shape reaches 127.0.0.1 from the installed window: the beta's content security policy or sandbox is the cause; the ADR records it with the date, the phase pauses on the launcher fallback, and the browser route and Phase 14 stand.
- Login works in the browser and not in the app: the session cookie is not sent across sites; the ADR weighs a bearer token in the app against the cookie rule, never a weaker cookie for the browser.

### 15.2 The FEAT desktop app and its publish skill

Depends on: 15.1 · Plan mode: required · Reviews: step-reviewer, code-review, ui-verifier, design-reviewer · Security: yes · Model hint: hard

#### Purpose

FEAT is installed as an app on this PC from a published artifact, reaches the local server, and is published again from a new build in one command.

#### Prerequisites

- Step 15.1 merged, its ADR accepted.

#### Prompt

```text
Masterplan step 15.2 — The FEAT desktop app and its publish skill.

Read the ADR of step 15.1, docs/masterplan/01-architecture.md §8, and the artifact-capabilities skill. Build the app the ADR chose: the artifact's page and files, with the fox of D-89 as its icon and a manifest naming only the permissions it uses; the server's admission of the app (the frame ancestor or the origin, the token flow) as a setting in config.toml that is off by default, refused when unset and tested both ways; the states the window shows when the server is down (how to start it, or a Start button through the desktop capability where you allowed full access), when you are offline, and while a republish is pending; and, where the ADR chose the web app's own files, a build of the web app for the artifact (relative asset paths, hash history, the API's address) that leaves the browser build identical, Playwright passing on both. In Claude Desktop the page offers Install as app itself when it is not yet installed.

Add a `publish-desktop-app` skill for Claude Code: it builds web/dist and publishes the artifact to the same URL with the Artifact tool (the published files within the tool's limits per publish), then records the URL, the version, and the date in docs/desktop-app.md with how to install, update, and uninstall, and never a token or a local path.

Tests: the server refuses an unconfigured frame ancestor or origin and admits the configured one; the artifact build passes vitest and Playwright; a check that every asset the page references is among the published files.

Not in this step: notifications, the tray, sharing the app with anyone else.
```

#### Done means

1. The app installs from Claude Desktop on this PC and shows your runs after login (screenshots in docs/validation/screenshots/15.2/).
2. The server admits only the configured frame ancestor or origin, and the tests fail without the change.
3. A republish through the skill updates the installed app, and docs/desktop-app.md records the URL and the version.
4. Playwright passes on both projects for the browser build, and on the artifact build where the ADR chose one.

#### Your checks

- Run `/publish-desktop-app` in a fresh session, then open FEAT from the Start menu: your runs page shows. Stop `fefat up`: the app says the server is down and how to start it; start it again and the app recovers without a restart.

#### If it fails

- Claude asks for the app's permissions again after every republish, your own edits included: the platform's rule, not a bug; docs/desktop-app.md says so.
- A blank window after a republish: an asset path in the build is absolute or a file was left out of the publish; the asset check names it.

### 15.3 Notifications and the tray

Depends on: 15.2 · Plan mode: optional · Reviews: step-reviewer, ui-verifier, design-reviewer · Security: no · Model hint: default

#### Purpose

The app tells you when a job finishes while you work elsewhere, and its tray icon shows what is running: the completion journey deferred with the phone (step 5.11, D-54), back on the desktop.

#### Prerequisites

- Step 15.2 merged.

#### Prompt

```text
Masterplan step 15.3 — Notifications and the tray.

Read the skipped step 5.11, the job stream of step 5.19, and the desktop capability's notifications and menu bar sections. Through the desktop capability, and only in the installed window: a system notification when a job finishes or fails while the window is hidden or behind another one, which opens the job's run or its page when clicked; a tray icon with the count of running jobs, a menu with Open FEAT and Quit, and a window title that names the running jobs; preferences per job kind in Settings, as 5.11 planned, kept by the server so that the browser and the app share them. Nothing changes in a browser.

Tests: vitest over the decision of what notifies (job kinds, states, the window's visibility, the preferences) and over the tray's text; a manual checklist with screenshots for the installed window, since Playwright cannot drive it.

Not in this step: web push, the phone, sounds.
```

#### Done means

1. A backtest finished behind another window shows a notification that opens its run (screenshots in docs/validation/screenshots/15.3/).
2. The tray icon shows the count of running jobs, and its menu opens FEAT and quits (screenshots).
3. The decision of what notifies is tested with the preferences, failing without the change.

#### Your checks

- Start a long backtest, switch to another program: a notification arrives when it finishes, and clicking it opens the run. Turn backtests off in Settings and run again: no notification.

#### If it fails

- No notification arrives: the app's permission was not allowed on first use; File > Apps > Permissions in Claude Desktop shows it.
- The tray icon stays after the window closes: the platform keeps an app with a tray item running; Quit in its menu stops it, as docs/desktop-app.md says.

## Phase exit

```text
/phase-exit 15 — Run the exit procedure for Phase 15: the app installed on this PC from a fresh publish; /security-review over the server's admission of the app and the token flow; the design-reviewer over the window's states (server down, offline, republish pending); demo = open FEAT from the Start menu, run a backtest, switch away, get the notification, click it; update docs/desktop-app.md; retro; tag phase-15.
```
