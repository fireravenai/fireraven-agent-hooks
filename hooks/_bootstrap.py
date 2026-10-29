from __future__ import annotations

import sys
from pathlib import Path


def setup_path() -> Path:
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from core.update_check import maybe_prompt_update

        maybe_prompt_update()
    except Exception:
        pass
    return root
