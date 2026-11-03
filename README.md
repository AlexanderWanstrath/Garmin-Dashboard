# Running Analytics Dashboard

Personal running analytics built on the official [Garmin Personal API](https://developer.garmin.com/gc-developer-program/personal/personal-api). Runs, per-second samples, laps, sleep, HRV and resting heart rate are synced into a local SQLite database, compared with a training plan, and made available to Claude Code through a local, read-only MCP server.

Work in progress. See [ROADMAP.md](ROADMAP.md) (German) for scope and plan, and [docs/data-availability.md](docs/data-availability.md) for what the API delivers.

## Setup

Requires Python 3.12+ and a Garmin Personal API key.

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows; on macOS/Linux: source .venv/bin/activate
pip install -e ".[dev,mcp]"
cp config.example.yaml config.yaml   # personal settings, ignored by git
cp plan.example.yaml plan.yaml       # optional training plan, ignored by git
```

Store the API key in `~/.config/garmin/connect-personal-api-key` or the environment variable `GARMIN_PERSONAL_API_KEY`. It is never passed on the command line.

## Usage

```bash
runlog sync                          # fetch new activities and health data
runlog log --tendon 1 --legs fresh   # morning check
runlog log --fuel 45                 # carbohydrates (g) taken during the last run
runlog check                         # traffic light, warnings, comparison with the plan
```

## Claude Code (MCP)

`runlog mcp` starts a stdio MCP server that only reads the database, `config.yaml` and `plan.yaml`. It never imports the Garmin client and never reads the API key. Register it locally (not in a shared `.mcp.json`, because the command contains local paths):

```bash
claude mcp add runlog --scope local -- <project>/.venv/Scripts/runlog.exe --config <project>/config.yaml mcp
```

If the VS Code extension does not pick up the local registration (it can see the project path with a different drive-letter case on Windows), register it with `--scope user` instead; the server is read-only and its config path is absolute.

Tools: `get_recent_runs`, `get_run_details`, `get_weekly_volume`, `get_intensity_distribution`, `get_recovery_status`, `get_warnings`, `get_plan_status`, `get_countdown`, `get_manual_entries`.

`.claude/settings.json` additionally denies Claude's file tools access to `~/.config/garmin/`.

## Privacy

The database, raw responses, FIT files, `config.yaml` and `plan.yaml` stay local and are ignored by git.

## License

MIT
