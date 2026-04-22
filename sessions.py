"""
List Claude Code sessions with display text, date, and session ID.

Usage:
    python sessions.py                    # human-readable list
    python sessions.py --project /path    # specific project
    python sessions.py --limit 50         # cap human-readable list
    python sessions.py --fzf              # TSV output for fzf piping
    python sessions.py --show <sid>       # detailed card (fzf preview)

Examples:
    >>> python sessions.py
    [1]
        prompt:     let's explore the AI serving POC...
        project:    ~/workspace/zoo/playground
        created_at: 2026-02-06 18:28
        updated_at: 2026-02-07 10:15
        branch:     develop
        size:       2800KB
        session_id: 55b59df3-320e-47b5-9a7a-da81d79af894
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
HISTORY_PATH = CLAUDE_DIR / "history.jsonl"
HOME_STR = str(Path.home())
TIME_FMT = "%Y-%m-%d %H:%M"


def _format_ms(timestamp_ms: float) -> str:
    """
    Format epoch milliseconds as local-time string.

    Args:
        timestamp_ms: Epoch timestamp in milliseconds.

    Returns:
        Local-time string formatted as ``"YYYY-MM-DD HH:MM"``.

    """
    # Convert via UTC first so the source timezone is explicit, then reformat in the local zone.
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).astimezone().strftime(TIME_FMT)


def _project_dir_name(project_path: str) -> str:
    """
    Convert project path to Claude Code's directory name format.

    Claude Code stores each project's sessions under a directory whose name
    is the absolute path with ``/`` replaced by ``-`` (e.g.,
    ``/home/user/proj`` -> ``-home-user-proj``).

    Args:
        project_path: Absolute project path.

    Returns:
        Mangled directory name used under ``~/.claude/projects/``.

    """
    return project_path.replace("/", "-")


def _shorten(path: str) -> str:
    """
    Replace home prefix with ~ for compact display.

    Args:
        path: Absolute path (or empty string).

    Returns:
        Path with the home prefix collapsed to ``~``; unchanged if it does
        not start under ``$HOME``, empty string if the input is empty.

    """
    # Only replace when path starts exactly under $HOME to avoid false positives.
    if path and path.startswith(HOME_STR):
        return "~" + path[len(HOME_STR):]

    return path


def _format_duration(duration_ms: int) -> str:
    """
    Format a non-negative duration in milliseconds as a compact human-readable string.

    Returns ``"-"`` only for negative values (defensive). For a valid zero
    duration, returns ``"0s"``. Callers should decide whether to call this
    with 0 or render ``"-"`` directly when the underlying data is missing.

    Args:
        duration_ms: Duration in milliseconds. Use a negative sentinel to
                     indicate "data missing".

    Returns:
        Compact form showing the top two non-zero units (e.g., ``"2h 5m"``,
        ``"3d 7h"``, ``"45s"``).

    """
    # Defensive: caller signals "data missing" via a negative value.
    if duration_ms < 0:
        return "-"

    # Decompose into days, hours, minutes, seconds.
    total_seconds = duration_ms // 1000
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    # Return only the top two non-zero units so output stays compact.
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"

    return f"{seconds}s"


def _load_history_entries() -> dict[str, dict[str, Any]]:
    """
    Load first display, project, and timestamp per session from history.jsonl.

    ``history.jsonl`` may contain multiple lines for the same session; the
    first entry seen per session_id wins and later duplicates are ignored.

    Returns:
        Dict mapping ``session_id`` to ``{"display", "project", "timestamp"}``.
        Empty dict if ``history.jsonl`` does not exist.

    """
    # Accumulator keyed by session_id so deduplication is O(1) per line.
    entries: dict[str, dict[str, Any]] = {}

    # The history file is optional; its absence is not an error.
    if not HISTORY_PATH.exists():
        return entries

    with open(HISTORY_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Skip malformed lines; history.jsonl is append-only and crashes can leave partials.
            try:
                data = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue

            # First entry per session_id wins; later duplicates ignored.
            session_id = data.get("sessionId", "")
            if not session_id or session_id in entries:
                continue

            # Keep only the fields we use downstream.
            entries[session_id] = {
                "display": data.get("display", ""),
                "project": data.get("project", ""),
                "timestamp": data.get("timestamp", 0),
            }

    return entries


def _parse_timestamp_ms(timestamp_str: str) -> int:
    """
    Parse ISO timestamp string to milliseconds since epoch.

    Args:
        timestamp_str: ISO format timestamp string.

    Returns:
        Milliseconds since epoch, or 0 if the input is empty or parsing fails.

    """
    if not timestamp_str:
        return 0

    # Python's fromisoformat rejects a trailing "Z" before 3.11; normalize to "+00:00" first.
    try:
        return int(datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, TypeError):
        return 0


def _extract_text(content: Any) -> str:
    """
    Extract text from a Claude Code message content (str or list of blocks).

    Args:
        content: Raw ``message.content`` value, either a plain string or a
                 list of content-block dicts.

    Returns:
        The text payload; empty string if no text block is present.

    """
    # Plain-string form.
    if isinstance(content, str):
        return content

    # Structured form: the first block whose type is "text" wins.
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")

    return ""


def _read_first_prompt(file_path: Path) -> tuple[str, str, str, str]:
    """
    Read first user text, branch, timestamp, and cwd from session JSONL.

    Scans until a user-type entry with actual text is found. Metadata
    (branch/timestamp/cwd) is captured from the first user entry seen;
    display text comes from the first entry that carries it (skipping
    tool_result-only entries).

    Args:
        file_path: Path to the session ``.jsonl`` file.

    Returns:
        Tuple ``(display, branch, timestamp, cwd)``. Any field is an empty
        string if the scan did not find it.

    """
    # Accumulators; the loop fills each as the corresponding entry is seen.
    branch = timestamp = cwd = display = ""

    with open(file_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Skip malformed lines defensively.
            try:
                data = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue

            # Skip non-user events and Claude Code's internal meta records.
            if data.get("type") != "user" or data.get("isMeta"):
                continue

            # Metadata comes from the first user entry we see.
            if not branch:
                branch = data.get("gitBranch", "")
            if not timestamp:
                timestamp = data.get("timestamp", "")
            if not cwd:
                cwd = data.get("cwd", "")

            # Display may live past tool_result-only entries; keep scanning until text appears.
            if not display:
                message = data.get("message", {})
                if isinstance(message, dict):
                    display = _extract_text(message.get("content"))

            # Stop scanning once every field is populated.
            if display and branch and timestamp and cwd:
                break

    return display, branch, timestamp, cwd


def _find_project_dirs(project_path: str | None, show_all: bool) -> list[Path]:
    """
    Find matching project directories under ``PROJECTS_DIR``.

    Exact dir-name match is preferred; when absent, falls back to substring
    matching so a user-supplied ``/foo`` also matches projects like ``/foo-bar``.

    Args:
        project_path: Explicit project path to match; if None, uses
                      ``os.getcwd()`` (ignored when ``show_all`` is True).
        show_all: If True, return every project directory under ``PROJECTS_DIR``.

    Returns:
        List of matching project directory paths; empty if ``PROJECTS_DIR``
        does not exist or no directory matches.

    """
    # Nothing to enumerate when the root directory is missing.
    if not PROJECTS_DIR.exists():
        return []

    # show_all short-circuits filtering and returns every project.
    if show_all:
        return [entry for entry in PROJECTS_DIR.iterdir() if entry.is_dir()]

    # Prefer an exact match on the mangled directory name.
    target = project_path or os.getcwd()
    dir_name = _project_dir_name(target)
    exact = PROJECTS_DIR / dir_name

    # Return early when the exact match exists; skip the fuzzy fallback.
    if exact.is_dir():
        return [exact]

    # Fall back to substring matching so partial paths still resolve.
    return [entry for entry in PROJECTS_DIR.iterdir() if entry.is_dir() and dir_name in entry.name]


def list_sessions(*, project_path: str | None = None, show_all: bool = False) -> list[dict[str, Any]]:
    """
    List all sessions for the given project(s).

    Args:
        project_path: Filter to specific project path. Ignored when
                      ``show_all`` is True.
        show_all: If True, include sessions from every project.

    Returns:
        List of session dicts sorted by ``updated_at`` (newest first).
        Each dict contains:

        - ``display``: first user prompt with newlines/tabs collapsed.
        - ``created_at`` / ``updated_at``: formatted local time.
        - ``session_id``: Claude Code session UUID.
        - ``branch``: git branch captured at session start.
        - ``size_kb``: size of the session jsonl in kilobytes.
        - ``timestamp``: sort key in epoch milliseconds.
        - ``project``: absolute project path.
        - ``cwd``: working directory of the original Claude Code session.

    Examples:
        >>> sessions = list_sessions(show_all=True)
        >>> sessions[0]["session_id"]
        'a64be2f6-fb1f-4c3d-94b4-9c4d3188810c'
        >>> sessions[0]["project"]
        '/home/dmlee/workspace'

    """
    # history.jsonl is cheaper to read than scanning every session jsonl; used as primary source.
    history = _load_history_entries()
    sessions: list[dict[str, Any]] = []

    # Walk every matching project directory and collect session metadata.
    for project_dir in _find_project_dirs(project_path, show_all):
        for session_file in project_dir.iterdir():
            # Top-level sessions use UUID names; agent-*.jsonl are sub-agent transcripts.
            if not session_file.name.endswith(".jsonl") or session_file.name.startswith("agent-"):
                continue

            # Skip empty files (e.g., aborted sessions).
            file_stat = session_file.stat()
            if file_stat.st_size == 0:
                continue

            # Prefer history.jsonl metadata; fall back to scanning the session file.
            session_id = session_file.stem
            history_entry = history.get(session_id, {})
            display = history_entry.get("display", "")
            timestamp_ms = history_entry.get("timestamp", 0)

            # Fill any missing fields by reading the jsonl directly.
            prompt_display, branch, timestamp_str, cwd = _read_first_prompt(session_file)
            if not display:
                display = prompt_display
            if not timestamp_ms:
                timestamp_ms = _parse_timestamp_ms(timestamp_str)

            # Sessions with no user text are not worth listing.
            if not display:
                continue

            # created_at uses the first message time; updated_at uses file mtime.
            created_ms = timestamp_ms or file_stat.st_mtime * 1000
            updated_ms = file_stat.st_mtime * 1000
            project = cwd or history_entry.get("project", "") or project_dir.name

            # Build one session record. Collapse newlines/tabs so the display fits on one fzf line.
            sessions.append(
                {
                    "display": display.replace("\n", " ").replace("\t", " "),
                    "created_at": _format_ms(created_ms),
                    "updated_at": _format_ms(updated_ms),
                    "session_id": session_id,
                    "branch": branch,
                    "size_kb": file_stat.st_size / 1024,
                    "timestamp": updated_ms,
                    "project": project,
                    "cwd": cwd,
                }
            )

    # Newest first; fzf preserves this order with --no-sort.
    sessions.sort(key=lambda entry: entry["timestamp"], reverse=True)

    return sessions


def _print_fzf(sessions: list[dict[str, Any]]) -> None:
    """
    Emit TSV lines for fzf: ``session_id \\t cwd \\t visible_line``.

    The first two columns ride as hidden fields (consumed by fzf's preview
    and resume step); the third column is what the user sees in the picker.

    Args:
        sessions: Session dicts produced by :func:`list_sessions`.

    """
    for session in sessions:
        # Truncate branch/project to keep columns aligned even for long values.
        branch = (session["branch"] or "-")[:10]
        project = _shorten(session["project"])[:38]

        # Visible column shown to the user in fzf.
        visible = f"{session['updated_at']}  [{branch:<10}]  {project:<38}  {session['display']}"

        # session_id and cwd ride as hidden columns for the preview/resume step.
        print(f"{session['session_id']}\t{session['cwd']}\t{visible}")


def _find_session_file(session_id: str) -> Path | None:
    """
    Locate a session's JSONL file by session ID across all projects.

    Args:
        session_id: Session UUID (file stem).

    Returns:
        Path to the session jsonl, or None if no project directory contains it.

    """
    # Nothing to search when the root directory is missing.
    if not PROJECTS_DIR.exists():
        return None

    # Session UUIDs are globally unique, so the first directory containing the file wins.
    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue

        file_path = project_dir / f"{session_id}.jsonl"

        if file_path.exists():
            return file_path

    return None


def _scan_session_full(file_path: Path) -> dict[str, Any]:
    """
    Full scan of a session JSONL to gather all stats needed for preview.

    Metadata (branch/cwd/first_user_timestamp) is taken from the first user
    entry. Display and last_user_text come from the first/last user entry
    that actually carries text (tool_result entries are skipped). Duration
    anchors (first_timestamp/last_timestamp) span all user+assistant turns.

    Args:
        file_path: Path to the session ``.jsonl`` file.

    Returns:
        Dict with the following keys:

        - ``display`` / ``last_user_text``: first and last user text.
        - ``branch`` / ``cwd`` / ``first_user_timestamp``: metadata from first user entry.
        - ``user_turns`` / ``assistant_turns``: turn counts (tool_result skipped).
        - ``first_timestamp`` / ``last_timestamp``: duration anchors across all turns.

    """
    # Initialize every field so callers can rely on key presence.
    result: dict[str, Any] = {
        "display": "",
        "branch": "",
        "first_user_timestamp": "",
        "cwd": "",
        "user_turns": 0,
        "assistant_turns": 0,
        "first_timestamp": "",
        "last_timestamp": "",
        "last_user_text": "",
    }

    with open(file_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            # Skip malformed lines defensively.
            try:
                data = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            if not isinstance(data, dict):
                continue

            message_type = data.get("type")
            timestamp = data.get("timestamp", "")

            # Real user message: collect metadata and count as a turn only if text is present.
            if message_type == "user" and not data.get("isMeta"):
                # Metadata comes from the first user entry seen.
                if not result["branch"]:
                    result["branch"] = data.get("gitBranch", "")
                if not result["cwd"]:
                    result["cwd"] = data.get("cwd", "")
                if not result["first_user_timestamp"]:
                    result["first_user_timestamp"] = timestamp

                # tool_result-only user entries have no text and don't count as turns.
                message = data.get("message", {})
                text = _extract_text(message.get("content")) if isinstance(message, dict) else ""

                if text:
                    result["user_turns"] += 1
                    result["last_user_text"] = text

                    if not result["display"]:
                        result["display"] = text

                    # Only text-bearing turns advance the user-side duration anchors.
                    if timestamp:
                        if not result["first_timestamp"]:
                            result["first_timestamp"] = timestamp
                        result["last_timestamp"] = timestamp
            elif message_type == "assistant":
                # Assistant turns do not affect display but bracket the session duration.
                result["assistant_turns"] += 1

                if timestamp:
                    if not result["first_timestamp"]:
                        result["first_timestamp"] = timestamp

                    result["last_timestamp"] = timestamp

    return result


def show_session(session_id: str) -> None:
    """
    Print detailed card for a single session (used as fzf preview).

    Prints metadata (project, branch, timestamps, turns, duration, idle)
    and the first/last user message to stdout. Intended for ``fzf --preview``.

    - ``duration``: elapsed time from first to last message within the session.
    - ``idle``:     elapsed time since the last message (relative to now).

    Args:
        session_id: Session UUID to look up.

    Examples:
        >>> show_session("55b59df3-320e-47b5-9a7a-da81d79af894")
        session_id : 55b59df3-320e-47b5-9a7a-da81d79af894
        project    : ~/workspace
        branch     : main
        created_at : 2026-02-06 18:28
        updated_at : 2026-02-07 10:15
        duration   : 1h 23m
        idle       : 2h 5m ago
        turns      : user 12  /  assistant 34
        size       : 452KB

    """
    # Locate the session file; print a placeholder when the ID does not match anything.
    file_path = _find_session_file(session_id)
    if not file_path:
        print(f"Session not found: {session_id}")
        return

    # Scan the jsonl once and reuse the stats throughout.
    stats = _scan_session_full(file_path)
    file_stat = file_path.stat()

    # Prefer jsonl-embedded timestamps; fall back to file mtime when the scan finds no anchors.
    mtime_ms = int(file_stat.st_mtime * 1000)
    created_ms = _parse_timestamp_ms(stats["first_user_timestamp"]) or mtime_ms
    updated_ms = mtime_ms
    first_ms = _parse_timestamp_ms(stats["first_timestamp"])
    last_ms = _parse_timestamp_ms(stats["last_timestamp"]) or mtime_ms
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    # Duration stays blank without valid anchors; idle is always computable via mtime fallback.
    duration_str = _format_duration(last_ms - first_ms) if first_ms else "-"
    idle_str = f"{_format_duration(now_ms - last_ms)} ago"

    # Metadata card.
    print(f"session_id : {session_id}")
    print(f"project    : {_shorten(stats['cwd']) or '-'}")
    print(f"branch     : {stats['branch'] or '-'}")
    print(f"created_at : {_format_ms(created_ms)}")
    print(f"updated_at : {_format_ms(updated_ms)}")
    print(f"duration   : {duration_str}")
    print(f"idle       : {idle_str}")
    print(f"turns      : user {stats['user_turns']}  /  assistant {stats['assistant_turns']}")
    print(f"size       : {file_stat.st_size / 1024:.0f}KB")

    # First user prompt is always printed.
    print()
    print("first prompt:")
    print(stats["display"] or "(empty)")

    # Skip "last user msg" when it would just duplicate the first prompt (single-turn sessions).
    if stats["user_turns"] > 1 and stats["last_user_text"]:
        print()
        print("last user msg:")
        print(stats["last_user_text"])


def main() -> None:
    """Dispatch CLI invocations to the appropriate session view."""
    # Build the argument parser with the four supported modes.
    parser = argparse.ArgumentParser(description="List Claude Code sessions")
    parser.add_argument(
        "--project",
        type=str,
        help="Filter by project path (default: all projects)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Max sessions for human-readable list (default: 30)",
    )
    parser.add_argument(
        "--fzf",
        action="store_true",
        help="Emit TSV for fzf (session_id, cwd, visible line)",
    )
    parser.add_argument(
        "--show",
        type=str,
        metavar="SID",
        help="Print detailed card for one session (fzf preview)",
    )
    args = parser.parse_args()

    # --show: fzf preview delegates here for a single session's card.
    if args.show:
        show_session(args.show)
        return

    # Load sessions once; every remaining mode operates on this list.
    sessions = list_sessions(project_path=args.project, show_all=not args.project)
    if not sessions:
        if not args.fzf:
            print("No sessions found.")
        sys.exit(0)

    # --fzf: machine-readable TSV consumed by the interactive picker.
    if args.fzf:
        _print_fzf(sessions)
        return

    # Default: human-readable list capped by --limit.
    recent = sessions[: args.limit]
    for index, session in enumerate(recent, 1):
        print(f"[{index}]")
        print(f"    prompt:     {session['display']}")
        print(f"    project:    {_shorten(session['project'])}")
        print(f"    created_at: {session['created_at']}")
        print(f"    updated_at: {session['updated_at']}")
        print(f"    branch:     {session['branch'] or '-'}")
        print(f"    size:       {session['size_kb']:.0f}KB")
        print(f"    session_id: {session['session_id']}")
        print()

    # Indicate truncation when more sessions exist beyond --limit.
    if len(sessions) > args.limit:
        print(f"... and {len(sessions) - args.limit} more (use --limit to show more)")


if __name__ == "__main__":
    main()
