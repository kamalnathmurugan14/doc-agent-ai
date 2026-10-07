"""Classifier adapter: HTTP client to project 2 (doc-classifier-ml), keyword-rule fallback, and a fake."""

import re
from typing import Protocol

import httpx

from app.config import Settings
from app.errors import AppError

RULES: dict[str, list[str]] = {
    "Invoice": ["invoice", "bill to", "amount due", "subtotal", "total due", "gst", "vat", "payment due"],
    "Contract": [
        "agreement",
        "hereby",
        "parties",
        "termination",
        "governing law",
        "renewal",
        "confidential",
        "whereas",
    ],
    "Resume": ["resume", "curriculum vitae", "work experience", "education", "skills", "objective", "references"],
    "Report": [
        "executive summary",
        "findings",
        "conclusion",
        "methodology",
        "recommendations",
        "quarterly",
        "analysis",
    ],
}


class Classifier(Protocol):
    name: str

    async def classify(self, text: str, rel_path: str) -> dict: ...
    async def ping(self) -> bool: ...


class RuleClassifier:
    """Built-in fallback: count keyword hits per category; confidence = share of all hits."""

    name = "keyword-rules"

    async def classify(self, text: str, rel_path: str) -> dict:
        low = text.lower()
        hits = {c: sum(len(re.findall(re.escape(k), low)) for k in kws) for c, kws in RULES.items()}
        total = sum(hits.values())
        if total == 0:
            return {
                "category": "Other",
                "confidence": 0.5,
                "top3": [{"category": "Other", "confidence": 0.5}],
                "method": self.name,
            }
        ranked = sorted(hits.items(), key=lambda kv: -kv[1])[:3]
        top3 = [{"category": c, "confidence": round(n / total, 3)} for c, n in ranked if n > 0]
        return {"category": top3[0]["category"], "confidence": top3[0]["confidence"], "top3": top3, "method": self.name}

    async def ping(self) -> bool:
        return True


class HttpClassifier:
    """Calls project 2 `POST /predict {rel_path}`. Both projects must point at the same DOCS_ROOT."""

    name = "classifier-service"

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base, self.timeout = base_url.rstrip("/"), timeout

    async def classify(self, text: str, rel_path: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as http:
                r = await http.post(f"{self.base}/predict", json={"rel_path": rel_path})
        except httpx.HTTPError as exc:
            raise AppError(
                "CLASSIFIER_UNAVAILABLE", f"Classifier service at {self.base} is not reachable", 503
            ) from exc
        if r.status_code >= 400:
            msg = (
                (r.json().get("error") or {}).get("message", f"HTTP {r.status_code}")
                if r.headers.get("content-type", "").startswith("application/json")
                else f"HTTP {r.status_code}"
            )
            raise AppError("CLASSIFIER_ERROR", f"Classifier service error: {msg}", 502)
        preds = r.json()["predictions"]
        return {
            "category": "Uncertain" if r.json().get("uncertain") else preds[0]["category"],
            "confidence": preds[0]["confidence"],
            "top3": preds,
            "method": self.name,
        }

    async def ping(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as http:
                return (await http.get(f"{self.base}/health")).status_code == 200
        except httpx.HTTPError:
            return False


class FakeClassifier:
    name = "fake"

    def __init__(self, category: str = "Invoice") -> None:
        self.category, self.calls = category, []

    async def classify(self, text: str, rel_path: str) -> dict:
        self.calls.append(rel_path)
        return {
            "category": self.category,
            "confidence": 0.9,
            "top3": [{"category": self.category, "confidence": 0.9}],
            "method": self.name,
        }

    async def ping(self) -> bool:
        return True


def build_classifier(settings: Settings) -> Classifier:
    return HttpClassifier(settings.classifier_service_url) if settings.classifier_service_url else RuleClassifier()
