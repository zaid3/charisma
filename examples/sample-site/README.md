# Offline repair example

Copy `index.html` and `check.py` into a new directory outside the Charisma checkout, initialise a Git repository, configure your Git identity if needed and commit the files. The page intentionally lacks `lang`.

Run a scan, prepare a plan with `--language en`, apply it to a new worktree, then verify with `--test "python check.py" --trust-tests`. Keep the scan and plan outside that sample Git repository. The check fails before the repair and passes afterward.
