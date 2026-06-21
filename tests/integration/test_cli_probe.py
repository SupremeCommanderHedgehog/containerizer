"""End-to-end test for the `containerizer probe` subcommand."""

import json
from pathlib import Path

from click.testing import CliRunner

from containerizer.cli import main


def test_cli_probe_prints_probe_json(fixtures_dir: Path) -> None:
    elf = fixtures_dir / "probe" / "elf-dynamic-x86_64"
    runner = CliRunner()
    result = runner.invoke(main, ["probe", str(elf)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["kind"] == "elf"
    assert payload["arch"] == "x86_64"
    assert payload["elf"]["interpreter"].endswith("ld-linux-x86-64.so.2")
    assert payload["base_image"]["image"].startswith("ubuntu:")


def test_cli_probe_writes_output_file(fixtures_dir: Path, tmp_path: Path) -> None:
    elf = fixtures_dir / "probe" / "elf-dynamic-x86_64"
    out = tmp_path / "probe.json"
    runner = CliRunner()
    result = runner.invoke(main, ["probe", str(elf), "-o", str(out)])
    assert result.exit_code == 0, result.output
    payload = json.loads(out.read_text())
    assert payload["kind"] == "elf"


def test_cli_probe_unsupported_kind_exits_nonzero(tmp_path: Path) -> None:
    f = tmp_path / "wat.rpm"
    f.write_bytes(b"\xed\xab\xee\xdb")
    runner = CliRunner()
    result = runner.invoke(main, ["probe", str(f)])
    assert result.exit_code != 0
    assert "not yet supported" in (result.output + (result.stderr if result.stderr else ""))
