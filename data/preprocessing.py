import pandas as pd
import re
import os
from typing import Dict, Optional, List, Tuple


class IngredientPreprocessor:
    UNITS = {
        "cup", "cups", "tbsp", "tablespoon", "tablespoons", "tsp", "teaspoon", "teaspoons",
        "oz", "ounce", "ounces", "lb", "pound", "pounds", "g", "kg", "ml", "l", "pinch"
    }

    COOKING_WORDS = {
        "chopped", "diced", "minced", "sliced", "ground", "crushed", "fresh", "frozen",
        "boneless", "skinless", "lean", "extra", "virgin", "optional", "to", "taste"
    }

    # IMPORTANT: Do NOT alias "peanut oil" -> "peanut".
    # Because refined vs unrefined peanut oil can be handled as an allergen exception.
    ALIASES = {
        "groundnut": "peanut",
        "peanut butter": "peanut",
        "arachis oil": "peanut",
        "almond milk": "almond",
    }

    # Tokens that indicate animal-derived or clearly non-vegan content.
    # If any of these appear in the parsed ingredient phrase, we avoid
    # collapsing it via the original→processed mapping so that downstream
    # safety checks (vegan/halal/allergy) can still see the risky tokens.
    ANIMAL_TOKENS = {
        "chicken", "beef", "pork", "bacon", "ham", "sausage", "turkey",
        "lamb", "duck", "goat",
        "fish", "salmon", "tuna", "cod", "bass", "turbot", "halibut", "mackerel", "snapper", "branzino",
        "anchovy", "anchovies", "shrimp", "prawn", "crab", "lobster", "oyster", "clam", "mussel",
        "scallop", "squid", "octopus",
        "gelatin", "lard", "tallow",
        "milk", "butter", "cream", "yogurt", "cheese", "ghee", "egg", "eggs",
        "creme", "mayonnaise", "aioli",
    }
    # Halal: alcohol and intoxicants — never collapse so reasoner can flag haram
    HARAM_ALCOHOL_TOKENS = {
        "alcohol", "wine", "beer", "vodka", "rum", "whiskey", "whisky",
        "gin", "tequila", "vermouth", "brandy", "cognac", "champagne", "liqueur",
    }
    # Kosher: grape products (wine/grape juice) — preserve so reasoner can flag
    DIETARY_CRITICAL_TOKENS = {"grape"}

    # NEW: tokens/patterns indicating a multi-ingredient phrase ("olive or peanut oil")
    COMBINATION_TOKENS = {
        "or", "and", "andor", "either", "combination", "mix", "mixed", "blend", "plus"
    }
    COMBINATION_PATTERNS = ["/", " and/or "]

    def __init__(
        self,
        original_to_processed_path: Optional[str] = None,
        processed_ingredients_path: Optional[str] = None
    ):
        self.original_to_processed_map: Dict[str, str] = {}
        self.processed_to_original_map: Dict[str, List[str]] = {}
        self.processed_ingredients: Dict[str, str] = {}  # id -> processed name

        if original_to_processed_path and os.path.exists(original_to_processed_path):
            self._load_original_to_processed_mapping(original_to_processed_path)

        if processed_ingredients_path and os.path.exists(processed_ingredients_path):
            self._load_processed_ingredients(processed_ingredients_path)

    def _load_original_to_processed_mapping(self, csv_path: str):
        df = pd.read_csv(csv_path)

        for _, row in df.iterrows():
            original = str(row.get('original', '')).lower().strip()
            processed = str(row.get('processed', '')).lower().strip()

            if original and processed:
                self.original_to_processed_map[original] = processed
                if processed not in self.processed_to_original_map:
                    self.processed_to_original_map[processed] = []
                self.processed_to_original_map[processed].append(original)

    def _load_processed_ingredients(self, csv_path: str):
        df = pd.read_csv(csv_path)

        for _, row in df.iterrows():
            ingredient_id = str(row.get('id', '')).strip()
            processed = str(row.get('processed', '')).lower().strip()

            if ingredient_id and processed:
                self.processed_ingredients[ingredient_id] = processed

    def clean_text(self, s: str) -> str:
        # cleaning text by lowercasing, removing parenthetical content, numbers, units, and non-alphabetic characters
        s = str(s).lower()
        # Remove parenthetical content
        s = re.sub(r"\([^)]*\)", " ", s)
        # Remove numbers and measurements
        s = re.sub(r"[\d¼½¾⅓⅔⅛⅜⅝⅞/.\-–—]+", " ", s)
        # Remove non-alphabetic characters (keep spaces)
        s = re.sub(r"[^a-z\s]", " ", s)
        # Normalize whitespace
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def apply_alias(self, phrase: str) -> str:
        p = phrase.lower().strip()
        return self.ALIASES.get(p, p)

    def _has_animal_token(self, phrase: str) -> bool:
        """
        Detect safety-critical tokens (animal products, haram alcohol, grape) in the parsed phrase.
        If present, we do NOT collapse the phrase via mapping so the reasoner can flag violations.
        """
        toks = (phrase or "").lower().split()
        if any(t in self.ANIMAL_TOKENS for t in toks):
            return True
        if any(t in self.HARAM_ALCOHOL_TOKENS for t in toks):
            return True
        if any(t in self.DIETARY_CRITICAL_TOKENS for t in toks):
            return True
        return False

    def _looks_like_multi_ingredient(self, phrase: str) -> bool:
        p = (phrase or "").lower().strip()
        if not p:
            return False

        # token-based detection
        toks = p.split()
        if any(t in self.COMBINATION_TOKENS for t in toks):
            return True

        # pattern-based detection
        p2 = f" {p} "
        if any(x in p2 for x in self.COMBINATION_PATTERNS):
            return True

        return False

    def parse_ingredient(self, raw: str) -> str:
        s = self.clean_text(raw)
        if not s:
            return ""

        # Remove units and cooking words
        toks = [t for t in s.split() if t not in self.UNITS and t not in self.COOKING_WORDS]
        return " ".join(toks[:6]).strip()  # NEW: keep a bit more context than 4 tokens

    def normalize_ingredient(self, ingredient: str) -> Tuple[str, Optional[str]]:
        """
        Returns (normalized_phrase, note).
        note is optional debug info that callers may ignore.
        """
        parsed = self.parse_ingredient(ingredient)
        if not parsed:
            return ingredient.lower().strip(), None

        # Apply alias
        parsed = self.apply_alias(parsed)

        # NEW: protect multi-ingredient phrases from collapsing into a single mapped token
        # e.g., "olive or peanut oil" should NOT be mapped to "olive"
        if self._looks_like_multi_ingredient(parsed):
            return parsed, "multi_ingredient_phrase_no_collapse"

        # Safety: if parsed phrase still contains clear animal/alcohol/grape tokens,
        # skip collapsing via original_to_processed mapping so the downstream logic can see those tokens.
        if self._has_animal_token(parsed):
            return parsed, "safety_tokens_no_collapse"

        # Try direct mapping
        if parsed in self.original_to_processed_map:
            processed = self.original_to_processed_map[parsed]
            return processed, "direct_mapping"

        # Try to find processed ingredient that matches
        parsed_lower = parsed.lower().strip()
        for processed, originals in self.processed_to_original_map.items():
            if parsed_lower == processed or parsed_lower in processed:
                return processed, "processed_match"
            # Check if any original matches (but avoid aggressive collapse)
            for orig in originals:
                if parsed_lower == orig:
                    return processed, "orig_exact_match"
                # Only allow substring mapping when it's not ambiguous (short strings are too risky)
                if len(parsed_lower) >= 6 and (parsed_lower in orig or orig in parsed_lower):
                    return processed, "orig_substring_match"

        # If not found, return parsed version
        return parsed, "no_mapping"

    def normalize_ingredient_list(self, ingredients: List[str]) -> List[str]:
        normalized = []
        seen = set()

        for ing in ingredients:
            norm_ing, _ = self.normalize_ingredient(ing)
            if norm_ing and norm_ing not in seen:
                normalized.append(norm_ing)
                seen.add(norm_ing)

        return normalized

    def get_all_processed_ingredients(self) -> List[str]:
        return list(self.processed_ingredients.values()) + list(self.processed_to_original_map.keys())


def safe_parse_list(x):
    import ast

    if isinstance(x, list):
        return x
    if not isinstance(x, str):
        return []
    s = x.strip()
    if not s:
        return []
    try:
        v = ast.literal_eval(s)
        return v if isinstance(v, list) else []
    except Exception:
        return [t.strip() for t in s.split(",") if t.strip()]