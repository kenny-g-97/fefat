# FEFAT task runner: the same recipes on Windows, CI, and macOS.
# Windows runs recipe lines in cmd.exe (Git's sh is not on PowerShell's PATH;
# a failing command fails the recipe with its real exit code), everything else
# runs them in sh. Keep recipe lines plain commands: no &&, pipes, or env
# prefixes. Python always runs through uv; bare `python` is a Store stub here.

set windows-shell := ["cmd.exe", "/c"]

# List the recipes
default:
    @just --list --unsorted

# Report the tools FEFAT needs, each as OK, OLD, or MISSING
doctor:
    uv run --no-project python scripts/doctor.py
