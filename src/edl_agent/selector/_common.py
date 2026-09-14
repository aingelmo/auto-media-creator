"""Shared config/constants for the LLM selector, #5."""

from __future__ import annotations

from typing import Any

DEFAULTS: dict[str, Any] = {
    "model": "gemini-3.7-flash",
    "thinking_level": "low",
    "thinking_level_many_candidates": "medium",  # #5.1: >=30 candidatos
    "many_candidates_threshold": 30,
    "temperature": 0.2,
    "max_output_tokens": 16384,
    "max_attempts": 2,  # #5.6
    "theme": "training",  # "training" (CrossFit/Hyrox/funcional) | "yoga"
}

# Canonical list of exercises, #5.5.
EXERCISES = [
    "back squat",
    "front squat",
    "overhead squat",
    "deadlift",
    "clean",
    "snatch",
    "jerk",
    "thruster",
    "pull-up",
    "muscle-up",
    "push-up",
    "burpee",
    "box jump",
    "wall ball",
    "kettlebell swing",
    "rowing",
    "bike",
    "ski erg",
    "run",
    "rope climb",
    "handstand",
    "double-under",
    "sled push",
    "sled pull",
    "farmers carry",
    "sandbag lunge",
    "lunge",
    "toes-to-bar",
    "sun salutation",
    "warrior pose",
    "downward dog",
    "balance pose",
    "inversion",
    "backbend",
    "stretch",
    "savasana",
    "other",
]
