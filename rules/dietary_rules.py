# rules/dietary_rules.py
# Deterministic dietary restriction rules with 3-valued outcomes:
#   allowed / forbidden / uncertain
# DietaryRuleChecker.check_dietary_constraints returns:
#   (is_compliant, violations, uncertainties, explanation)

from typing import Tuple, List, Dict


class HalalRules:
    """
    Simplified halal rules for a class project.
    Deterministic lexical checks + explicit uncertainty.
    """

    FORBIDDEN = {
        # pork & derivatives
        "pork", "bacon", "ham", "lard", "pork fat", "pork belly", "prosciutto", "pancetta",
        # alcohol & common spirits/wines
        "alcohol", "wine", "beer", "vodka", "rum", "whiskey", "whisky",
        "gin", "vermouth", "brandy", "cognac", "champagne", "liqueur", "tequila",
        # gelatin and animal-derived (prohibited in halal unless from halal source)
        "gelatin", "gelatine",
        # animal-derived ambiguous items (often haram unless verified)
        "rennet",
    }

    UNCERTAIN = {
        # extracts / vinegars can contain alcohol depending on process
        "vanilla extract",
        "wine vinegar",
        # generic "flavoring" type words are often ambiguous
        "extract",
    }

    def is_halal_compliant(self, ingredient: str) -> Tuple[str, str]:
        ingredient_lower = ingredient.lower().strip()

        for forbidden in self.FORBIDDEN:
            if forbidden in ingredient_lower:
                return "forbidden", f"'{ingredient}' contains '{forbidden}' which is haram (forbidden in Islam)"

        for uncertain in self.UNCERTAIN:
            if uncertain in ingredient_lower:
                return "uncertain", f"'{ingredient}' contains '{uncertain}' - source/process must be verified for halal compliance"

        return "allowed", f"'{ingredient}' appears halal-compliant"


class KosherRules:
    """
    Kosher rules: forbidden animals (pork, shellfish, camel), blood, grape products.
    Meat/dairy/cheese require certification (uncertain) since we cannot verify shechita/rennet.
    """

    FORBIDDEN = {
        # pork and byproducts
        "pork", "bacon", "ham", "lard",
        # shellfish and non-fish seafood
        "shellfish", "shrimp", "crab", "lobster", "oyster", "clam", "mussel",
        "scallop", "squid", "octopus",
        # non-permitted land animals
        "camel",
        # blood (forbidden); exception for "blood orange" handled in check
        # grape products (non-Jewish production generally prohibited)
        "wine", "grape juice",
    }

    REQUIRES_CERTIFICATION = {
        # cheeses depend on rennet/certification
        "cheese",
        # meat requires kosher slaughter (shechita)
        "meat", "chicken", "beef",
    }

    def is_kosher_compliant(self, ingredient: str) -> Tuple[str, str]:
        ingredient_lower = ingredient.lower().strip()

        # blood orange is permitted (fruit); blood as ingredient is forbidden
        if "blood" in ingredient_lower and "blood orange" not in ingredient_lower:
            return "forbidden", f"'{ingredient}' contains blood which is forbidden in kosher"

        for forbidden in self.FORBIDDEN:
            if forbidden in ingredient_lower:
                return "forbidden", f"'{ingredient}' contains '{forbidden}' which is not kosher"

        for requires in self.REQUIRES_CERTIFICATION:
            if requires in ingredient_lower:
                return "uncertain", f"'{ingredient}' requires kosher certification/context - verify"

        return "allowed", f"'{ingredient}' appears kosher-compliant"


class VeganRules:
    """
    Vegan rules: deterministic forbidden lexicon + explicit uncertainty list.
    Expanded dairy lexicon to catch common cheeses even without the token 'cheese'.
    """

    FORBIDDEN = {
        # meat
        "meat", "chicken", "beef", "pork", "lamb", "turkey", "duck", "goat",
        "bacon", "ham", "sausage", "pepperoni", "salami",
        # seafood (incl. species)
        "fish", "salmon", "tuna", "cod", "bass", "turbot", "halibut", "mackerel", "snapper", "branzino",
        "shrimp", "crab", "lobster", "oyster",
        # dairy (expanded, incl. French spellings)
        "milk", "butter", "cream", "yogurt", "yoghurt", "sour cream", "creme", "crème", "fraiche",
        "whey", "casein", "lactose",
        "cheese", "cheddar", "parmesan", "ricotta", "mozzarella", "pecorino",
        "feta", "brie", "gouda", "paneer", "ghee",
        # eggs
        "egg", "eggs", "egg white", "egg yolk", "mayonnaise", "aioli",
        # other animal products
        "honey", "beeswax",
        "gelatin", "gelatine",
        "lard", "tallow",
    }

    UNCERTAIN = {
        # some sugars processed with bone char (depends on brand/region)
        "sugar",
        # alcohol in sauces etc. depends on preparation
        "wine", "beer",
        # vitamin D3 often lanolin-derived unless specified vegan
        "vitamin d3",
    }

    def is_vegan_compliant(self, ingredient: str) -> Tuple[str, str]:
        ingredient_lower = ingredient.lower().strip()

        for forbidden in self.FORBIDDEN:
            if forbidden in ingredient_lower:
                return "forbidden", f"'{ingredient}' contains '{forbidden}' which is not vegan"

        for uncertain in self.UNCERTAIN:
            if uncertain in ingredient_lower:
                return "uncertain", f"'{ingredient}' contains '{uncertain}' - processing/source must be verified for vegan compliance"

        return "allowed", f"'{ingredient}' appears vegan-compliant"


class DietaryRuleChecker:
    def __init__(self):
        self.halal = HalalRules()
        self.kosher = KosherRules()
        self.vegan = VeganRules()

    def check_dietary_constraints(self, ingredient: str, constraints: Dict) -> Tuple[bool, List[str], List[str], str]:
        """
        Returns:
          is_compliant: bool (True iff there are NO forbidden violations)
          violations: list[str] (forbidden)
          uncertainties: list[str] (uncertain)
          explanation: str (combined explanation)
        """
        violations: List[str] = []
        uncertainties: List[str] = []
        explanations: List[str] = []

        if constraints.get("halal", False):
            status, explanation = self.halal.is_halal_compliant(ingredient)
            if status == "forbidden":
                violations.append(f"Halal: {explanation}")
            elif status == "uncertain":
                uncertainties.append(f"Halal: {explanation}")
            explanations.append(explanation)

        if constraints.get("kosher", False):
            status, explanation = self.kosher.is_kosher_compliant(ingredient)
            if status == "forbidden":
                violations.append(f"Kosher: {explanation}")
            elif status == "uncertain":
                uncertainties.append(f"Kosher: {explanation}")
            explanations.append(explanation)

        if constraints.get("vegan", False):
            status, explanation = self.vegan.is_vegan_compliant(ingredient)
            if status == "forbidden":
                violations.append(f"Vegan: {explanation}")
            elif status == "uncertain":
                uncertainties.append(f"Vegan: {explanation}")
            explanations.append(explanation)

        explanation = "; ".join(explanations) if explanations else "No dietary constraints"
        is_compliant = len(violations) == 0
        return is_compliant, violations, uncertainties, explanation