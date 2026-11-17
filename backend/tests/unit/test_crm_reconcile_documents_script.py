import subprocess
import sys
from pathlib import Path


def test_reconcile_script_registers_every_table_it_touches():
    # Run in a fresh interpreter: inside the test session other imports already registered
    # `organizations`, which would hide the NoReferencedTableError the script hit for real.
    check = (
        "import scripts.crm.reconcile_documents\n"
        "from sqlmodel import SQLModel\n"
        "assert 'organizations' in SQLModel.metadata.tables\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", check],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-500:]
