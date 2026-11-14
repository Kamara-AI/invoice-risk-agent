"""Bot simulator: replays what the UiPath bot will send to Kagua and checks contract v1.

Run (repo root, Kagua running):
    python -m tools.bot_simulator                 # offline scenarios only (no DB, no LLM)
    python -m tools.bot_simulator --live          # all scenarios: writes rows, costs OpenAI, may post Slack
"""
