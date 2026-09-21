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

# Suggested exercise names for the ground-truth labelling UI's dropdown
# (tools/label_exercises.py) only. The selector itself no longer constrains
# `exercise` to this list -- see prompts.py's open-vocabulary schema -- since
# eval showed a full model names movements outside any fixed list just as
# accurately, and a closed enum can't keep up with real footage variety
# (box squat, air squat, single leg deadlift, ... all missing at one point).
EXERCISES = [
    "back squat",
    "front squat",
    "overhead squat",
    "box squat",
    "air squat",
    "deadlift",
    "single leg deadlift",
    "good morning",
    "clean",
    "snatch",
    "jerk",
    "thruster",
    "pull-up",
    "muscle-up",
    "push-up",
    "burpee",
    "box jump",
    "box step up",
    "wall ball",
    "kettlebell swing",
    "svend press",
    "v-up",
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
