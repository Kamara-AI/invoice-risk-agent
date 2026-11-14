"""Entry point: `python -m tools.bot_simulator [--live] [--base-url URL]`."""

import sys

from tools.bot_simulator.simulate import main

sys.exit(main())
