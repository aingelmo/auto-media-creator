"""Cliente local Ollama que imita la interfaz de google.genai.Client
(`.interactions.create(...)`), para poder llamar `selector.select()` sin
tocarlo y sin gastar en Gemini durante las primeras pruebas de vision (#5).

Solo para uso manual/pruebas: no aplica pricing (#11 no cubre modelos Ollama,
`_cost_usd` ya devuelve 0.0 para modelos fuera de PRICING_PER_MTOK) y no hay
"thinking_level" equivalente (se ignora).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import requests

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_NUM_CTX = 8192
# Ollama sirve con 4096 por defecto si no se pide mas; con varios candidatos +
# imagenes de referencia el prompt se acerca o pasa ese limite y el modelo
# devuelve JSON truncado/corrupto. 16384 hace spill a CPU en RTX 2070 8GB con
# qwen3-vl:8b-instruct sin mejorar fiabilidad (ver sesiones de validacion 2026-09-11)


@dataclass
class _Usage:
    total_input_tokens: int
    total_output_tokens: int
    total_thought_tokens: int = 0

    def model_dump(self) -> dict:
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_thought_tokens": self.total_thought_tokens,
        }


@dataclass
class _Interaction:
    status: str
    output_text: str
    usage: _Usage = field(default_factory=lambda: _Usage(0, 0))


class _Interactions:
    def __init__(self, base_url: str, num_ctx: int = DEFAULT_NUM_CTX) -> None:
        self._base_url = base_url
        self._num_ctx = num_ctx

    def create(
        self,
        *,
        model: str,
        system_instruction: str,
        input: list[dict],  # noqa: A002 (matches the Interactions API's `input` kwarg)
        response_format: dict,
        generation_config: dict,
        **_: object,
    ) -> _Interaction:
        content_lines = [p["text"] for p in input if p["type"] == "text"]
        images = [p["data"] for p in input if p["type"] == "image"]

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": "\n".join(content_lines), "images": images},
            ],
            "format": response_format.get("schema"),
            "stream": False,
            "options": {
                "temperature": generation_config.get("temperature"),
                "num_predict": generation_config.get("max_output_tokens"),
                "num_ctx": self._num_ctx,
            },
        }
        resp = requests.post(f"{self._base_url}/api/chat", json=payload, timeout=600)
        resp.raise_for_status()
        data = resp.json()

        status = "incomplete" if data.get("done_reason") == "length" else "completed"
        usage = _Usage(
            total_input_tokens=data.get("prompt_eval_count", 0),
            total_output_tokens=data.get("eval_count", 0),
        )
        return _Interaction(
            status=status, output_text=data["message"]["content"], usage=usage
        )


class OllamaClient:
    def __init__(
        self, base_url: str = DEFAULT_BASE_URL, num_ctx: int = DEFAULT_NUM_CTX
    ) -> None:
        self.interactions = _Interactions(base_url, num_ctx)
