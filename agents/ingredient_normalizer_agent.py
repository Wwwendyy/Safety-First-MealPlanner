
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
import re

try:
    from data.preprocessing import IngredientPreprocessor
except Exception:
    IngredientPreprocessor = None


STOPWORDS = {
    "fresh","dried","ground","crushed","minced","chopped","sliced","diced","grated",
    "large","small","medium","extra","virgin","optional","to","taste","of","and"
}

UNITS = {
    "tsp","tbsp","teaspoon","teaspoons","tablespoon","tablespoons",
    "cup","cups","oz","ounce","ounces","lb","lbs","pound","pounds",
    "g","gram","grams","kg","ml","l","liter","liters",
    "pinch","clove","cloves","slice","slices","can","cans","package","packages"
}

def _basic_clean(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _strip_leading_qty_and_units(tokens: List[str]) -> List[str]:
    # Remove leading quantities/units, e.g., "2 cups chopped parsley" -> ["parsley"]
    out = list(tokens)
    while out:
        t = out[0]
        if re.fullmatch(r"\d+(\.\d+)?", t):
            out.pop(0)
            continue
        if t in UNITS:
            out.pop(0)
            continue
        break
    return out

def _singularize(token: str) -> str:
    # lightweight singularization
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("es") and len(token) > 3:
        return token[:-2]
    if token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
        return token[:-1]
    return token

@dataclass
class NormalizedIngredient:
    raw: str
    cleaned: str
    head: str  # canonical token best for matching (e.g., "snapper", "tuna", "pancetta")

class IngredientNormalizerAgent:
    """
    Normalizes ingredient strings into high-recall tokens for constraint checks.
    Goal: make it easy to match fish/meat/dairy terms that appear in compounds.
    """

    def __init__(self):
        self.preprocessor = IngredientPreprocessor() if IngredientPreprocessor else None

    def normalize_one(self, ingredient_raw: str) -> NormalizedIngredient:
        raw = ingredient_raw or ""
        cleaned = ""
        if self.preprocessor:
            cleaned, _ = self.preprocessor.normalize_ingredient(raw)
        cleaned = cleaned or _basic_clean(raw)

        toks = cleaned.split()
        toks = _strip_leading_qty_and_units(toks)
        toks = [t for t in toks if t and t not in STOPWORDS]
        toks = [_singularize(t) for t in toks]

        # Heuristic for head noun: last informative token
        head = toks[-1] if toks else cleaned
        head = head.strip()

        # Preserve multi-word proteins like "sea bream"
        if "sea" in toks and "bream" in toks:
            head = "sea bream"
        if "red" in toks and "snapper" in toks:
            head = "snapper"
        if "snapper" in toks:
            head = "snapper"
        if "tuna" in toks:
            head = "tuna"
        if "pancetta" in toks:
            head = "pancetta"

        return NormalizedIngredient(raw=raw, cleaned=cleaned, head=head)

    def normalize_many(self, ingredients: List[str]) -> List[NormalizedIngredient]:
        return [self.normalize_one(x) for x in (ingredients or [])]
