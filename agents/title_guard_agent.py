import re
from typing import Dict, List

class TitleGuardAgent:
    """Hard guardrails from the recipe title.

    Rationale: some datasets have incomplete ingredient lists.
    If title contains explicit forbidden items, treat as Unsafe (strong evidence).
    """

    DAIRY_TITLE = re.compile(
        r"\b(cheddar|parmesan|ricotta|mozzarella|feta|gouda|cheese|cream|butter|milk|Parmesan"
        r"|creme fraiche|crème fraîche|creme fraîche)\b", re.I
    )
    NUT_TITLE = re.compile(r"\b(cashew|almond|walnut|pecan|pistachio|hazelnut|macadamia|peanut)\b", re.I)
    # Meat + fish (vegan forbids all) — include fish species that often appear in titles
    MEAT_TITLE = re.compile(
        r"\b(chicken|beef|pork|bacon|ham|sausage|turkey|lamb|fish|shrimp|crab|lobster"
        r"|bass|salmon|cod|tuna|turbot|halibut|mackerel|snapper|branzino|trout|tilapia)\b",
        re.I
    )
    # Halal: pork and byproducts, alcohol and intoxicants
    HALAL_FORBIDDEN_TITLE = re.compile(
        r"\b(pork|bacon|ham|lard|prosciutto|pancetta|alcohol|wine|beer|vodka|rum|whiskey|whisky|gin|tequila|brandy|cognac|champagne|liqueur|vermouth)\b",
        re.I
    )
    # Kosher: pork, shellfish, non-permitted animals (blood omitted to avoid "blood orange" false positive)
    KOSHER_FORBIDDEN_TITLE = re.compile(
        r"\b(pork|bacon|ham|lard|shellfish|shrimp|crab|lobster|oyster|clam|mussel|scallop|squid|octopus|camel)\b",
        re.I
    )
    # Gluten/wheat allergy: title implies bread/gluten (e.g. "toasts", "sandwich", "bruschetta")
    GLUTEN_TITLE = re.compile(
        r"\b(toast|toasts|bread|sandwich|bruschetta|crouton|pizza|pasta|noodle|lasagna|ravioli)\b",
        re.I
    )

    def check_title(self, title: str, dietary: Dict, manual_avoid_clean: List[str], allergens: List[str]) -> Dict:
        trace = []
        violations = []

        t = str(title or '')
        if not t.strip():
            return {'violations': [], 'trace': []}

        # manual avoid: if any banned word appears in title, Unsafe
        low = t.lower()
        for banned in manual_avoid_clean or []:
            if banned and banned in low:
                violations.append({
                    'constraint': 'manual_avoid_title',
                    'ingredient': t,
                    'cleaned': t,
                    'evidence': f"Title contains manual-avoid token '{banned}'"
                })
                trace.append(f"TITLE GUARD → VIOLATION: {t} contains manual-avoid '{banned}'")
                return {'violations': violations, 'trace': trace}

        # halal: title must not indicate pork or alcohol
        if dietary.get('halal', False):
            if self.HALAL_FORBIDDEN_TITLE.search(t):
                m = self.HALAL_FORBIDDEN_TITLE.search(t).group(0).lower()
                violations.append({
                    'constraint': 'dietary_title',
                    'ingredient': t,
                    'cleaned': t,
                    'evidence': f"Title indicates haram '{m}' (pork or alcohol prohibited for halal)"
                })
                trace.append(f"TITLE GUARD → VIOLATION: halal but title indicates haram '{m}'")
                return {'violations': violations, 'trace': trace}

        # kosher: title must not indicate pork, shellfish, or blood
        if dietary.get('kosher', False):
            if self.KOSHER_FORBIDDEN_TITLE.search(t):
                m = self.KOSHER_FORBIDDEN_TITLE.search(t).group(0).lower()
                violations.append({
                    'constraint': 'dietary_title',
                    'ingredient': t,
                    'cleaned': t,
                    'evidence': f"Title indicates non-kosher '{m}' (pork/shellfish/blood prohibited)"
                })
                trace.append(f"TITLE GUARD → VIOLATION: kosher but title indicates '{m}'")
                return {'violations': violations, 'trace': trace}

        # vegan implies no dairy and no meat
        if dietary.get('vegan', False):
            if self.DAIRY_TITLE.search(t):
                m = self.DAIRY_TITLE.search(t).group(0)
                violations.append({'constraint': 'dietary_title', 'ingredient': t, 'cleaned': t,
                                   'evidence': f"Title indicates dairy '{m}' which is not vegan"})
                trace.append(f"TITLE GUARD → VIOLATION: vegan but title indicates dairy '{m}'")
            if self.MEAT_TITLE.search(t):
                m = self.MEAT_TITLE.search(t).group(0)
                violations.append({'constraint': 'dietary_title', 'ingredient': t, 'cleaned': t,
                                   'evidence': f"Title indicates meat/seafood '{m}' which is not vegan"})
                trace.append(f"TITLE GUARD → VIOLATION: vegan but title indicates meat/seafood '{m}'")

        # gluten/wheat allergy: title indicates bread or gluten dish
        allergen_set = set([str(a).lower().strip() for a in (allergens or [])])
        if 'gluten allergy' in allergen_set or 'wheat allergy' in allergen_set:
            if self.GLUTEN_TITLE.search(t):
                m = self.GLUTEN_TITLE.search(t).group(0).lower()
                violations.append({
                    'constraint': 'allergy_title',
                    'ingredient': t,
                    'cleaned': t,
                    'evidence': f"Title indicates gluten/wheat dish '{m}' (toast, bread, pasta, etc.)"
                })
                trace.append(f"TITLE GUARD → VIOLATION: gluten/wheat allergy but title indicates '{m}'")
                return {'violations': violations, 'trace': trace}

        # egg allergy: title indicates mayonnaise/aioli/egg dish
        if 'egg allergy' in allergen_set or 'poultry allergy' in allergen_set:
            if re.search(r"\b(mayonnaise|aioli|egg\s+salad|deviled\s+eggs)\b", t, re.I):
                violations.append({
                    'constraint': 'allergy_title',
                    'ingredient': t, 'cleaned': t,
                    'evidence': "Title indicates egg-containing dish (mayonnaise/aioli)"
                })
                trace.append("TITLE GUARD → VIOLATION: egg allergy but title indicates egg")
                return {'violations': violations, 'trace': trace}

        # nut allergy: title indicates cashew etc.
        if 'nut allergy' in allergen_set or 'tree nut allergy' in allergen_set or 'peanut allergy' in allergen_set:
            if self.NUT_TITLE.search(t):
                m = self.NUT_TITLE.search(t).group(0).lower()
                # only trigger peanut if peanut allergy or nut allergy covers it; keep conservative: if nut/tree nut and 'cashew' etc => violation
                violations.append({'constraint': 'allergy_title', 'ingredient': t, 'cleaned': t,
                                   'evidence': f"Title indicates nut '{m}' under nut-related allergy"})
                trace.append(f"TITLE GUARD → VIOLATION: nut-related allergy but title indicates '{m}'")

        return {'violations': violations, 'trace': trace}
