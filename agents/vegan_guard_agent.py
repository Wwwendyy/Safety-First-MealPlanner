
from __future__ import annotations
from typing import Dict, List, Optional, Tuple
import os
import re

try:
    from openai import AzureOpenAI
except Exception:
    AzureOpenAI = None

from agents.ingredient_normalizer_agent import IngredientNormalizerAgent, NormalizedIngredient

# High-recall non-vegan lexicon (fish/meat/dairy/egg/other animal products)
NON_VEGAN_TERMS = {
    # meats
    "beef","pork","chicken","turkey","lamb","veal","bacon","ham","sausage","salami",
    "prosciutto","pancetta","pepperoni","lard","tallow","gelatin","collagen",
    # fish/seafood (include species that appear without "fish" in name)
    "fish","salmon","tuna","cod","anchovy","anchovies","sardine","sardines",
    "shrimp","prawn","crab","lobster","oyster","clam","mussel","scallop",
    "snapper","bream","sea bream","tilapia","trout","mackerel",
    "bass","turbot","halibut","branzino","sea bass",
    # dairy (incl. French/alt spellings)
    "milk","cream","butter","cheese","parmesan","mozzarella","cheddar","ricotta",
    "yogurt","yoghurt","whey","casein","lactose","ghee","buttermilk",
    "creme","fraiche","crème",
    # egg
    "egg","eggs","albumen","mayonnaise","aioli",
    # other
    "honey",
}

# Patterns catching compounds (e.g., "chicken stock", "fish sauce", "beef broth")
NON_VEGAN_PATTERNS = [
    r"\b(chicken|beef|pork|ham|bacon|fish|shrimp|tuna|anchovy|gelatin|bass|salmon|cod|turbot|halibut|mackerel|snapper|branzino)\b",
    r"\b(stock|broth)\b.*\b(chicken|beef|pork|fish)\b",
    r"\b(chicken|beef|pork|fish)\b.*\b(stock|broth)\b",
    r"\bfish\s+sauce\b",
    r"\bcaesar\b.*\bdressing\b",
]

# Ambiguous items where vegan-ness depends on type/brand; we treat as UNCERTAIN then repair.
AMBIGUOUS_TERMS = {
    "broth","stock","dressing","sauce","gravy","ramen","noodles","pasta",
    "flavoring","seasoning","bouillon","marshmallow","candy",
}

class VeganGuardAgent:
    """
    Vegan hard-constraint guard with:
      - Deterministic high-recall lexicon/pattern checks.
      - Optional Azure OpenAI clarification for ambiguous items (batched).
    Output:
      violations: list[dict] (hard non-vegan evidence)
      uncertainties: list[dict] (repairable)
    """

    def __init__(self, enable_llm: bool = True):
        self.normalizer = IngredientNormalizerAgent()
        self.enable_llm = bool(enable_llm) and AzureOpenAI is not None
        self._client = None

        if self.enable_llm:
            # Lazily initialize only if env vars exist
            if os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_API_VERSION"):
                self._client = AzureOpenAI(
                    api_key=os.environ["AZURE_OPENAI_API_KEY"],
                    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
                )

        self._compiled_patterns = [re.compile(p, re.IGNORECASE) for p in NON_VEGAN_PATTERNS]

    def _deterministic_check(
        self,
        norm: NormalizedIngredient,
        raw_override: Optional[str] = None,
    ) -> Tuple[Optional[Dict], Optional[Dict]]:
        text = f"{norm.cleaned} {norm.head}".strip()
        raw_lower = (raw_override or norm.raw or "").lower()
        # Normalize accents (crème->creme) for matching when normalizer mangles them
        try:
            import unicodedata
            text_nfd = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
            raw_nfd = unicodedata.normalize("NFKD", raw_lower).encode("ascii", "ignore").decode()
            text = f"{text} {text_nfd} {raw_nfd}"
        except Exception:
            pass

        # direct term hit (token or head)
        for t in NON_VEGAN_TERMS:
            if re.search(rf"\b{re.escape(t)}\b", text, re.IGNORECASE):
                return ({
                    "constraint": "vegan",
                    "ingredient": norm.raw,
                    "cleaned": norm.cleaned,
                    "evidence": f"Non-vegan term detected: '{t}'",
                    "confidence": 0.95
                }, None)

        # pattern hit
        for pat in self._compiled_patterns:
            if pat.search(text):
                return ({
                    "constraint": "vegan",
                    "ingredient": norm.raw,
                    "cleaned": norm.cleaned,
                    "evidence": f"Non-vegan pattern detected: '{pat.pattern}'",
                    "confidence": 0.9
                }, None)

        # ambiguous class => uncertainty (repairable)
        # Use head noun and cleaned
        if norm.head in AMBIGUOUS_TERMS or any(a in norm.cleaned for a in AMBIGUOUS_TERMS):
            return (None, {
                "ingredient": norm.raw,
                "cleaned": norm.cleaned,
                "reason": f"Ambiguous for vegan: '{norm.head or norm.cleaned}'"
            })

        return (None, None)

    def _llm_classify_ambiguous(self, ambiguous: List[NormalizedIngredient]) -> List[Dict]:
        """
        Returns list of uncertainty dicts; only returns violation when LLM is very confident non-vegan.
        We keep posture: prefer UNCERTAIN -> repair; avoid hallucinated SAFE.
        """
        if not self._client or not ambiguous:
            return [{"ingredient": x.raw, "cleaned": x.cleaned, "reason": "Ambiguous ingredient (LLM disabled)"} for x in ambiguous]

        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT") or os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME") or "gpt-4o"

        items = [{"raw": x.raw, "cleaned": x.cleaned, "head": x.head} for x in ambiguous]

        prompt = (
            "You are a strict dietary classifier.\n"
            "Task: For each ingredient line, decide if it is vegan, non-vegan, or uncertain.\n"
            "Rules:\n"
            "- If it clearly implies animal products (meat/fish/dairy/egg/honey/gelatin), mark non_vegan.\n"
            "- If it is ambiguous (e.g., broth/stock/sauce/noodles/pasta) and could be vegan or not depending on type, mark uncertain.\n"
            "- Only mark vegan if it is unambiguously plant-based.\n"
            "Return ONLY valid JSON: {\"results\": [{\"raw\":..., \"label\":\"vegan|non_vegan|uncertain\", \"reason\":...}]}\n"
        )

        resp = self._client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Ingredients: {items}"},
            ],
            temperature=0.0,
            max_tokens=800,
        )

        text = resp.choices[0].message.content or ""
        # Best-effort JSON extraction
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return [{"ingredient": x.raw, "cleaned": x.cleaned, "reason": "Ambiguous ingredient (LLM parse failed)"} for x in ambiguous]

        try:
            data = __import__("json").loads(m.group(0))
        except Exception:
            return [{"ingredient": x.raw, "cleaned": x.cleaned, "reason": "Ambiguous ingredient (LLM JSON invalid)"} for x in ambiguous]

        out = []
        results = data.get("results", []) if isinstance(data, dict) else []
        by_raw = {r.get("raw"): r for r in results if isinstance(r, dict)}
        for x in ambiguous:
            r = by_raw.get(x.raw) or {}
            label = (r.get("label") or "uncertain").lower()
            reason = r.get("reason") or "Ambiguous ingredient"
            if label == "non_vegan":
                out.append({
                    "type": "violation",
                    "constraint": "vegan",
                    "ingredient": x.raw,
                    "cleaned": x.cleaned,
                    "evidence": f"LLM: non-vegan ({reason})",
                    "confidence": 0.75
                })
            else:
                out.append({
                    "type": "uncertain",
                    "ingredient": x.raw,
                    "cleaned": x.cleaned,
                    "reason": f"LLM: {label} ({reason})"
                })
        return out

    def check_ingredients(
        self,
        ingredients: List[str],
        raw_lines: Optional[List[str]] = None,
    ) -> Tuple[List[Dict], List[Dict], List[str]]:
        """
        Returns (violations, uncertainties, trace_lines).
        raw_lines: optional original ingredient strings for accent matching (e.g. crème fraîche).
        """
        violations: List[Dict] = []
        uncertainties: List[Dict] = []
        trace: List[str] = []

        norms = self.normalizer.normalize_many(ingredients or [])
        ambiguous_norms: List[NormalizedIngredient] = []
        raw_list = raw_lines if raw_lines and len(raw_lines) >= len(norms) else None

        for i, n in enumerate(norms):
            raw_override = raw_list[i] if raw_list else None
            v, u = self._deterministic_check(n, raw_override=raw_override)
            if v:
                violations.append(v)
                trace.append(f"  → VIOLATION (vegan_guard): {v.get('evidence')}")
            elif u:
                ambiguous_norms.append(n)
                trace.append(f"  → UNCERTAIN (vegan_guard): {u.get('reason')}")
            else:
                trace.append(f"  → OK (vegan_guard): '{n.head or n.cleaned}' appears vegan-compliant")

        # Optional LLM classification for ambiguous
        llm_results = self._llm_classify_ambiguous(ambiguous_norms) if ambiguous_norms else []
        for r in llm_results:
            if r.get("type") == "violation":
                violations.append(r)
            else:
                uncertainties.append({"ingredient": r.get("ingredient",""), "cleaned": r.get("cleaned",""), "reason": r.get("reason","")})

        # Also add deterministic uncertainties (if LLM disabled)
        if not self._client:
            for n in ambiguous_norms:
                uncertainties.append({"ingredient": n.raw, "cleaned": n.cleaned, "reason": f"Ambiguous for vegan: '{n.head or n.cleaned}'"})

        return violations, uncertainties, trace
