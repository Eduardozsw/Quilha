import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from hermes import caminhos


@pytest.mark.skipif(not (caminhos.PROJECT_ROOT / "pyproject.toml").is_file(), reason="só no checkout")
def test_wheel_leva_sql_templates_e_padroes(tmp_path):
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(tmp_path)], cwd=caminhos.PROJECT_ROOT,
                   check=True, capture_output=True)
    wheel = next(Path(tmp_path).glob("quilha-*.whl"))
    nomes = set(zipfile.ZipFile(wheel).namelist())

    assert "hermes/sql/schema.sql" in nomes
    assert any(n.startswith("hermes/templates/") and n.endswith(".typ") for n in nomes)
    assert {f"hermes/dados/{p}" for p in caminhos.PADROES} <= nomes
    assert any(n.endswith("entry_points.txt") for n in nomes)
