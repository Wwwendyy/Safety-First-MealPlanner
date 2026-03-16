# agents/hf_ingredient_extractor.py
# LLM ingredient extraction for Scheme B (Azure OpenAI Chat Completions)
#
# NOTE: We keep the filename + class name for backward compatibility:
#   from agents.hf_ingredient_extractor import HFIngredientExtractor

import os
import json
import re
from typing import List, Dict, Any, Tuple, Optional

from openai import AzureOpenAI


def _extract_json_array(text: str):
    """Robustly parse a JSON array from model output.
    Accepts plain JSON or JSON wrapped in ``` fences.
    """
    t = (text or "").strip()
    t = re.sub(r"^```json\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^```\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t)

    try:
        data = json.loads(t)
        return data
    except Exception:
        pass

    m = re.search(r"\[.*\]", t, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None

    return None


def _azure_client_from_env() -> AzureOpenAI:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION")

    missing = [k for k, v in {
        "AZURE_OPENAI_ENDPOINT": endpoint,
        "AZURE_OPENAI_API_KEY": api_key,
        "AZURE_OPENAI_API_VERSION": api_version,
    }.items() if not v]

    if missing:
        raise RuntimeError(
            "Missing Azure OpenAI env vars: "
            + ", ".join(missing)
            + ". Make sure your .env is loaded."
        )

    return AzureOpenAI(
        api_version=api_version,
        azure_endpoint=endpoint,
        api_key=api_key,
    )


def _chat(client: AzureOpenAI, deployment: str, prompt: str, max_tokens: int = 900) -> str:
    resp = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": "You output ONLY valid JSON. No markdown. No explanation."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.0,
        top_p=1.0,
    )
    
    return (resp.choices[0].message.content or "").strip()


# NEW: processing clues (rule-based; not relying on LLM)
_PROCESSING_KEYWORDS = [
    "highly refined",
    "refined",
    "cold-pressed", "cold pressed",
    "expeller-pressed", "expeller pressed",
    "unrefined",
    "crude",
    "gourmet",
]


def extract_processing_clues(raw: str) -> Dict[str, Any]:
    s = (raw or "").lower()
    hits = [k for k in _PROCESSING_KEYWORDS if k in s]

    # Level heuristic:
    # - If "highly refined" or "refined" is present (without "unrefined") => refined
    # - If cold-pressed / expeller-pressed / unrefined / crude / gourmet => unrefined
    # - Otherwise unknown
    refined_hit = ("highly refined" in s) or ("refined" in s and "unrefined" not in s)
    unrefined_hit = any(k in s for k in [
        "cold-pressed", "cold pressed",
        "expeller-pressed", "expeller pressed",
        "unrefined", "crude", "gourmet"
    ])

    if refined_hit and not unrefined_hit:
        level = "refined"
    elif unrefined_hit:
        level = "unrefined"
    else:
        level = "unknown"

    return {"level": level, "keywords": hits}


class HFIngredientExtractor:
    """Scheme B LLM ingredient extractor (Azure OpenAI).

    Output per line:
      {
        raw: str,
        is_food: bool,
        canonical: [str],
        notes: str,
        confidence: float (0..1),
        processing: { level: "refined"|"unrefined"|"unknown", keywords: [str] }   # NEW
      }
    """

    def __init__(self, model: Optional[str] = None):
        self.client = _azure_client_from_env()
        self.deployment = model or os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        self.calls = 0
        if not self.deployment:
            raise RuntimeError("AZURE_OPENAI_DEPLOYMENT is not set.")
        self._line_cache: Dict[str, Dict[str, Any]] = {}

    def extract_lines(self, lines: List[str]) -> List[Dict[str, Any]]:
        normalized_lines = [str(x).strip() for x in (lines or []) if str(x).strip()]
        if not normalized_lines:
            return []

        cached_results: List[Dict[str, Any]] = []
        to_query: List[str] = []
        for l in normalized_lines:
            if l in self._line_cache:
                cached_results.append(self._line_cache[l])
            else:
                to_query.append(l)

        queried_results: List[Dict[str, Any]] = []
        if to_query:
            prompt = (
                "You are an ingredient extraction system for recipes.\n"
                "Return ONLY a valid JSON ARRAY. No markdown. No explanation.\n"
                "For each input line, output an object with keys:\n"
                "  raw (string), is_food (boolean), canonical (array of strings), notes (string), confidence (0..1).\n"
                "Rules:\n"
                "- If tool/equipment/utensil/instruction-only: is_food=false and canonical=[].\n"
                "- If garnish/optional but still food, keep the food ingredient.\n"
                "- canonical MUST remove quantities, units, brand names, and preparation words (chopped/diced/grated/finely).\n"
                "- canonical MUST preserve key nouns like 'parmesan', 'cheddar', 'ricotta salata cheese', 'spelt spaghetti'.\n"
                "- If unsure whether a token is food, set confidence low (<0.6) but still try.\n\n"
                f"Input lines:\n{json.dumps(to_query, ensure_ascii=False)}\n\n"
                "JSON:"
            )

            out_text = _chat(self.client, self.deployment, prompt, max_tokens=900)
            self.calls += 1
            print(f"[LLM] ingredient extractor call #{self.calls} | lines={len(to_query)}")
            data = _extract_json_array(out_text)

            if not isinstance(data, list):
                data = [{
                    "raw": l,
                    "is_food": True,
                    "canonical": [l],
                    "notes": "fallback (model output not JSON array)",
                    "confidence": 0.3
                } for l in to_query]

            for item in data:
                raw = str(item.get("raw", "")).strip()
                is_food = bool(item.get("is_food", True))
                canonical = item.get("canonical", [])
                if not isinstance(canonical, list):
                    canonical = [str(canonical)]
                canonical = [str(x).strip().lower() for x in canonical if str(x).strip()]

                notes = str(item.get("notes", "")).strip()
                conf = item.get("confidence", 0.5)
                try:
                    conf = float(conf)
                except Exception:
                    conf = 0.5
                conf = max(0.0, min(1.0, conf))

                processing = extract_processing_clues(raw or "")

                queried_results.append({
                    "raw": raw or "",
                    "is_food": is_food,
                    "canonical": canonical,
                    "notes": notes,
                    "confidence": conf,
                    "processing": processing,
                })

            # fallback alignment if model returned mismatched raws
            if len(queried_results) != len(to_query) or any(not x["raw"] for x in queried_results):
                queried_results = []
                for i, l in enumerate(to_query):
                    base = data[i] if i < len(data) and isinstance(data[i], dict) else {}
                    is_food = bool(base.get("is_food", True))
                    canonical = base.get("canonical", [])
                    if not isinstance(canonical, list):
                        canonical = [str(canonical)]
                    canonical = [str(x).strip().lower() for x in canonical if str(x).strip()]
                    notes = str(base.get("notes", "")).strip()
                    conf = base.get("confidence", 0.5)
                    try:
                        conf = float(conf)
                    except Exception:
                        conf = 0.5
                    conf = max(0.0, min(1.0, conf))

                    processing = extract_processing_clues(l)

                    queried_results.append({
                        "raw": l,
                        "is_food": is_food,
                        "canonical": canonical,
                        "notes": notes,
                        "confidence": conf,
                        "processing": processing,
                    })

            for item in queried_results:
                self._line_cache[item["raw"]] = item

        by_raw = {x["raw"]: x for x in (cached_results + queried_results)}
        return [by_raw[l] for l in normalized_lines if l in by_raw]

    def canonicalize_recipe_ingredients(
        self,
        lines: List[str],
        uncertain_threshold: float = 0.6
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        extracted = self.extract_lines(lines)

        canonical: List[str] = []
        uncertain: List[Dict[str, Any]] = []

        for item in extracted:
            if not item.get("is_food", True):
                continue
            conf = float(item.get("confidence", 0.5))
            if conf < uncertain_threshold:
                uncertain.append(item)

            for c in item.get("canonical", []) or []:
                c2 = str(c).strip().lower()
                if c2:
                    canonical.append(c2)

        seen = set()
        canon2 = []
        for c in canonical:
            if c not in seen:
                seen.add(c)
                canon2.append(c)

        return canon2, uncertain

    # NEW: keep full extracted metadata for downstream exception logic
    def canonicalize_recipe_ingredients_with_metadata(
        self,
        lines: List[str],
        uncertain_threshold: float = 0.6
    ) -> Tuple[List[str], List[Dict[str, Any]], List[Dict[str, Any]]]:
        extracted = self.extract_lines(lines)

        canonical: List[str] = []
        uncertain: List[Dict[str, Any]] = []

        for item in extracted:
            if not item.get("is_food", True):
                continue
            conf = float(item.get("confidence", 0.5))
            if conf < uncertain_threshold:
                uncertain.append(item)

            for c in item.get("canonical", []) or []:
                c2 = str(c).strip().lower()
                if c2:
                    canonical.append(c2)

        seen = set()
        canon2 = []
        for c in canonical:
            if c not in seen:
                seen.add(c)
                canon2.append(c)

        return canon2, uncertain, extracted