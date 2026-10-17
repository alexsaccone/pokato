from pathlib import Path
from pokato.automatic_diagnostics import automatic_smoke

if __name__ == '__main__':
    raise SystemExit(automatic_smoke(Path('artifacts/automatic-smoke.json')))
