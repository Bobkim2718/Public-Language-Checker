from __future__ import annotations

import sys


if "--self-test" in sys.argv:
    import app.ui
    import app.document_loader
    import app.analyzer
    import app.batch
    import app.data_store

    raise SystemExit(0)


from app.main import main


if __name__ == "__main__":
    main()
