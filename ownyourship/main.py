import os
import socket
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

app = typer.Typer(
    name="oys",
    help="Quiz yourself on your own vibe-coded projects.",
    add_completion=False,
)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def _load_api_key() -> Optional[str]:
    """Load API key from ~/.oys/.env then CWD .env. Never hardcode."""
    home_env = Path.home() / ".oys" / ".env"
    if home_env.exists():
        load_dotenv(home_env, override=False)
    load_dotenv(override=False)
    return os.getenv("ANTHROPIC_API_KEY")


def _show_disclaimer_prompt(project_path: Path) -> bool:
    typer.echo("")
    typer.echo("=" * 62)
    typer.echo("  OWNYOURSHIP — PLEASE READ BEFORE CONTINUING")
    typer.echo("=" * 62)
    typer.echo("")
    typer.echo("  1. YOUR CODE IS SENT TO ANTHROPIC")
    typer.echo("     Snippets of this project are transmitted to the Anthropic")
    typer.echo("     API to generate questions and grade answers.")
    typer.echo("     Do NOT use on confidential, classified, or proprietary")
    typer.echo("     code without your organisation's explicit consent.")
    typer.echo("")
    typer.echo("  2. YOU PAY FOR EVERY API CALL")
    typer.echo("     This tool uses YOUR Anthropic API key. Every question and")
    typer.echo("     every graded answer costs real money.")
    typer.echo("")
    typer.echo("     >>> SET A SPEND LIMIT NOW (strongly recommended):")
    typer.echo("     https://console.anthropic.com/settings/limits")
    typer.echo("")
    typer.echo("  3. NO WARRANTY — NO LIABILITY")
    typer.echo("     This software is provided as-is. The author accepts no")
    typer.echo("     liability for API costs, data exposure, or any damages.")
    typer.echo("     See DISCLAIMER.md for full terms.")
    typer.echo("")
    typer.echo("  4. .oys/ WILL BE CREATED IN YOUR PROJECT")
    typer.echo(f"     {project_path}")
    typer.echo("     This folder will be added to your project's .gitignore.")
    typer.echo("")
    typer.echo("=" * 62)
    typer.echo("")
    try:
        answer = typer.prompt(
            'Type "yes" to acknowledge and continue'
        ).strip().lower()
    except (KeyboardInterrupt, EOFError):
        typer.echo("\nCancelled.")
        return False

    if answer != "yes":
        typer.echo("Cancelled. Run `oys` again when ready.")
        return False
    return True


def _patch_gitignore(project_path: Path) -> None:
    """Ensure .oys/ is in the target project's .gitignore."""
    gi = project_path / ".gitignore"
    entry = ".oys/"
    if gi.exists():
        if entry not in gi.read_text(encoding="utf-8"):
            with open(gi, "a", encoding="utf-8") as f:
                f.write(f"\n# ownyourship\n{entry}\n")
    else:
        gi.write_text(f"# ownyourship\n{entry}\n", encoding="utf-8")


@app.command()
def main(
    path: Optional[Path] = typer.Argument(
        default=None,
        help="Project folder to quiz on (defaults to current directory).",
    ),
):
    """Quiz yourself on your own vibe-coded projects."""
    from . import config as cfg
    from . import db
    from . import scanner
    from .server import create_app
    import uvicorn

    project_path = Path(path).resolve() if path else Path.cwd()

    if not project_path.exists() or not project_path.is_dir():
        typer.echo(f"\nERROR: '{project_path}' is not a valid directory.", err=True)
        typer.echo("\nTroubleshooting:")
        typer.echo("  - Run `oys` from inside your project folder, or pass the path:")
        typer.echo("    oys C:\\path\\to\\your\\project")
        raise typer.Exit(1)

    api_key = _load_api_key()
    if not api_key:
        typer.echo("\nERROR: ANTHROPIC_API_KEY not found.", err=True)
        typer.echo("\nFix: create one of these files with your key:")
        typer.echo("  Option 1 (recommended — works for all projects):")
        typer.echo("    %USERPROFILE%\\.oys\\.env")
        typer.echo("  Option 2 (this project only):")
        typer.echo("    .env  (in the current directory)")
        typer.echo("\nFile contents:")
        typer.echo("  ANTHROPIC_API_KEY=your_key_here")
        typer.echo("\nGet your key: https://console.anthropic.com/keys")
        raise typer.Exit(1)

    project_config = cfg.load_config(project_path)
    if not project_config.get("disclaimer_acknowledged", False):
        if not _show_disclaimer_prompt(project_path):
            raise typer.Exit(0)
        cfg.acknowledge_disclaimer(project_path)

    _patch_gitignore(project_path)
    db.init_db(project_path)

    # Verify there's something to scan
    config = cfg.load_config(project_path)
    included_exts = set(config.get("included_extensions", [".py"]))
    has_files = False
    for f in project_path.rglob("*"):
        if (
            f.is_file()
            and f.suffix.lower() in included_exts
            and not scanner.should_exclude(f, project_path, config)
        ):
            has_files = True
            break

    if not has_files:
        typer.echo(f"\nERROR: No scannable source files found in:", err=True)
        typer.echo(f"  {project_path}", err=True)
        typer.echo("\nTroubleshooting:")
        typer.echo(f"  - Supported extensions: {', '.join(sorted(included_exts))}")
        typer.echo("  - Check .oys/config.json — adjust included_extensions,")
        typer.echo("    excluded_dirs, or excluded_patterns")
        typer.echo("  - Make sure your source files aren't inside an excluded")
        typer.echo("    directory (venv/, node_modules/, etc.)")
        typer.echo("  - If you have no .oys/config.json yet, run `oys` from")
        typer.echo("    inside a project directory that contains source code.")
        raise typer.Exit(1)

    port = _find_free_port()
    url = f"http://127.0.0.1:{port}"
    shutdown_event = threading.Event()

    fastapi_app = create_app(project_path, api_key, shutdown_event)
    uvi_config = uvicorn.Config(
        app=fastapi_app,
        host="127.0.0.1",  # local only — never 0.0.0.0
        port=port,
        log_level="error",
    )
    server = uvicorn.Server(uvi_config)

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    time.sleep(1.2)  # give uvicorn a moment to bind

    typer.echo(f"\nOwnYourShip running at {url}")
    typer.echo(f"Project: {project_path.name}")
    typer.echo("Press Ctrl+C to stop.\n")
    webbrowser.open(url)

    try:
        shutdown_event.wait()
        typer.echo("\nShutting down (browser requested)...")
    except KeyboardInterrupt:
        typer.echo("\nShutting down...")
    finally:
        server.should_exit = True
        server_thread.join(timeout=3)
        typer.echo("Done. Progress saved to .oys/progress.db")


def entry():
    app()
