"""Official-provider image generation for Discord responses."""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Optional

import requests

from config.settings import (
    CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN, CLOUDFLARE_IMAGE_MODELS,
    EDENAI_API_KEY, GEMINI_API_KEY, GEMINI_MODELS,
)


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes
    filename: str
    provider: str


class ImageGenerator:
    """Uses Cloudflare first; Eden is an opt-in fallback when configured."""

    def __init__(self):
        self._last_errors: list[str] = []

    def generate(self, prompt: str) -> tuple[Optional[GeneratedImage], str]:
        prompt = prompt.strip()[:2048]
        self._last_errors = []
        if not prompt:
            return None, "give me something to draw first~"
        configured = []
        if CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN:
            configured.append("Cloudflare")
            image = self._cloudflare(prompt)
            if image:
                return image, ""
        if EDENAI_API_KEY:
            configured.append("Eden AI")
            image = self._eden(prompt)
            if image:
                return image, ""
        if configured:
            detail = "; ".join(dict.fromkeys(self._last_errors)) or "no usable image returned"
            return None, f"{', '.join(configured)} is configured but failed: {detail}. Try again in a moment."
        return None, "image generation isn't configured yet — add Cloudflare Workers AI credentials to `.env` and restart me."

    def _cloudflare(self, prompt: str) -> Optional[GeneratedImage]:
        for model in CLOUDFLARE_IMAGE_MODELS:
            try:
                response = requests.post(
                    f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{model}",
                    headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"},
                    # Current Cloudflare schema for this route accepts prompt and
                    # steps; it rejects the formerly documented `seed` field.
                    json={"prompt": prompt, "steps": 4},
                    timeout=30,
                )
                if response.status_code != 200:
                    self._last_errors.append(f"Cloudflare HTTP {response.status_code}")
                    continue
                if response.headers.get("Content-Type", "").startswith("image/"):
                    return GeneratedImage(response.content, "aishu_flux.jpg", "Cloudflare FLUX")
                payload = response.json()
                encoded = (payload.get("result") or {}).get("image") or payload.get("image")
                if encoded:
                    return GeneratedImage(base64.b64decode(encoded), "aishu_flux.jpg", "Cloudflare FLUX")
            except (requests.RequestException, ValueError, TypeError) as exc:
                self._last_errors.append(f"Cloudflare {type(exc).__name__}")
                continue
        return None

    def _eden(self, prompt: str) -> Optional[GeneratedImage]:
        """Eden's documented v3 universal endpoint; never used without an env key."""
        try:
            response = requests.post(
                "https://api.edenai.run/v3/universal-ai",
                headers={"Authorization": f"Bearer {EDENAI_API_KEY}"},
                json={
                    "model": "image/generation/stabilityai/stable-diffusion-xl-1024-v1-0",
                    "input": {"text": prompt, "resolution": "1024x1024", "num_images": 1},
                },
                timeout=45,
            )
            if response.status_code != 200:
                self._last_errors.append(f"Eden AI HTTP {response.status_code}")
                return None
            payload = response.json()
            encoded = payload.get("image") or (payload.get("data") or {}).get("image")
            image_url = payload.get("image_resource_url") or (payload.get("data") or {}).get("image_resource_url")
            if encoded and encoded.startswith("data:"):
                encoded = encoded.split(",", 1)[-1]
            if encoded:
                return GeneratedImage(base64.b64decode(encoded), "aishu_eden.png", "Eden AI")
            if image_url:
                download = requests.get(image_url, timeout=30)
                if download.status_code == 200 and download.content:
                    return GeneratedImage(download.content, "aishu_eden.png", "Eden AI")
        except (requests.RequestException, ValueError, TypeError) as exc:
            self._last_errors.append(f"Eden AI {type(exc).__name__}")
        return None

    def analyze(self, image_bytes: bytes, mime_type: str = "image/png", prompt: str = "") -> tuple[Optional[str], str]:
        """Analyze an image using configured vision-capable AI models with fallback."""
        if not image_bytes:
            return None, "no image data received to analyze~"

        # Detect mime type from magic bytes if generic
        if image_bytes.startswith(b"\x89PNG"):
            mime_type = "image/png"
        elif image_bytes.startswith(b"\xff\xd8\xff"):
            mime_type = "image/jpeg"
        elif image_bytes.startswith(b"GIF8"):
            mime_type = "image/gif"
        elif image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:16]:
            mime_type = "image/webp"

        p = prompt.strip() or "Look at this image and tell me what you see. Share your authentic, cute, and playful reaction."
        b64_data = base64.b64encode(image_bytes).decode("utf-8")

        # 1. Primary: Gemini Vision API (fast multimodal)
        if GEMINI_API_KEY:
            for gem_model in GEMINI_MODELS:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{gem_model}:generateContent?key={GEMINI_API_KEY}"
                    res = requests.post(
                        url,
                        json={
                            "contents": [{
                                "role": "user",
                                "parts": [
                                    {"inline_data": {"mime_type": mime_type, "data": b64_data}},
                                    {"text": f"You are Aishu (17, playful, sweet, real girl). Respond naturally, casually, lowercase: {p}"},
                                ],
                            }],
                            "generationConfig": {
                                "maxOutputTokens": 350,
                                "temperature": 0.8,
                            },
                        },
                        timeout=25,
                    )
                    if res.status_code == 200:
                        data = res.json()
                        text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                        if text:
                            return text, ""
                except Exception as exc:
                    self._last_errors.append(f"Gemini {gem_model}: {exc}")
                    continue

        return None, "couldn't inspect this image right now 😔 please check that your vision provider API key is active."


image_generator = ImageGenerator()
