from pathlib import Path
from pokato.river_diagnostics import river_smoke


if __name__ == "__main__":
    raise SystemExit(river_smoke(Path("artifacts/turn-smoke.json"), "T"))
