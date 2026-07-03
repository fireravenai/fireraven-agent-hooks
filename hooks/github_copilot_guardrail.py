#!/usr/bin/env python3
from _bootstrap import setup_path

setup_path()

from adapters.github_copilot import main

if __name__ == "__main__":
    main()
