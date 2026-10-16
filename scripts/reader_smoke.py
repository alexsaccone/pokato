from pathlib import Path
from pokato.reader_diagnostics import reader_smoke


if __name__ == "__main__":
    raise SystemExit(reader_smoke(Path("artifacts/reader-smoke.json")))
