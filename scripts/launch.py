"""Absolute-import entry point for the standalone Windows executable."""
from pathlib import Path
import sys
from pokato.app import main


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test-reader":
        from pokato.reader_diagnostics import reader_smoke
        sys.exit(reader_smoke(Path(sys.argv[2])))
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from pokato.diagnostics import packaged_smoke
        sys.exit(packaged_smoke(Path(sys.argv[2])))
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test-river":
        from pokato.river_diagnostics import river_smoke
        sys.exit(river_smoke(Path(sys.argv[2])))
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test-turn":
        from pokato.river_diagnostics import river_smoke
        sys.exit(river_smoke(Path(sys.argv[2]), "T"))
    main()
