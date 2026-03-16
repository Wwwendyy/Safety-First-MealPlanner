
from __future__ import annotations
from typing import Dict, List, Tuple
import re

# Simple expansion map (focus on high-impact dairy/meat/fish words users commonly type)
EXPANSIONS = {
    "cheese": ["cheese","parmesan","mozzarella","cheddar","ricotta","feta","gouda","brie","cream cheese","mascarpone", "pecorino romano", 'cashew-Cream'],
    "milk": ["milk","whey","casein","lactose","buttermilk"],
    "egg": ["egg","eggs","albumen","mayonnaise"],
    "fish": ["fish","tuna","salmon","snapper","anchovy","cod","sea bream"],
    "pork": ["pork","bacon","ham","pancetta","prosciutto"],
}

def _clean(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9\s\-]", " ", s)
    s = re.sub(r"\s+"," ", s).strip()
    return s

class ManualAvoidAgent:
    def expand(self, manual_avoid: List[str]) -> List[str]:
        out = []
        for x in (manual_avoid or []):
            c = _clean(x)
            if not c:
                continue
            out.append(c)
            if c in EXPANSIONS:
                out.extend(EXPANSIONS[c])
        # de-dupe
        seen=set()
        uniq=[]
        for x in out:
            if x not in seen:
                seen.add(x); uniq.append(x)
        return uniq

    def check(self, ingredient_clean: str, expanded_bans: List[str]) -> Tuple[bool, str]:
        for banned in expanded_bans:
            if banned and (banned == ingredient_clean or banned in ingredient_clean):
                return True, banned
        return False, ""
