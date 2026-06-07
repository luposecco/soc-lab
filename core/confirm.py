from __future__ import annotations

import os


def assume_yes() -> bool:
    return os.environ.get("SOC_LAB_ASSUME_YES", "0") == "1"


def confirm(prompt: str) -> bool:
    if assume_yes():
        return True
    answer = input(f"{prompt} [y/N] ").strip()
    return answer.lower() == "y"
