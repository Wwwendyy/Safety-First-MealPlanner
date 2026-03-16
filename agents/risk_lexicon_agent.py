from typing import Dict, List, Optional

class RiskLexiconAgent:
    """Fallback detector for high-risk keywords.

    Purpose: avoid false-safe when KB misses obvious allergens (e.g., cashew) or dietary bans (cheese).
    """

    TREE_NUTS = {'cashew','almond','walnut','pecan','pistachio','hazelnut','macadamia','brazil nut','pine nut'}
    DAIRY = {'cheese','cheddar','ricotta','parmesan','mozzarella','feta','gouda','cream','butter','milk','yogurt','whey','casein','Parmesan','creme','crème','fraiche'}
    EGGS = {'egg','eggs','mayonnaise','aioli'}
    MEAT = {'chicken','beef','pork','bacon','ham','sausage','turkey','lamb','fish','shrimp','crab','lobster',
            'bass','salmon','tuna','cod','turbot','halibut','mackerel','snapper','branzino','trout'}
    # Gluten/wheat: grains + common gluten-containing foods (allergen DB often only has raw grains)
    GLUTEN_TERMS = {
        'wheat', 'barley', 'rye', 'semolina', 'bulgur', 'farro', 'spelt',
        'bread', 'breadcrumb', 'breadcrumbs', 'flour', 'pasta', 'noodle', 'noodles',
        'couscous', 'seitan', 'graham', 'malt', 'breaded',
    }

    def check(self, ingredient_clean: str, dietary: Dict, allergens: List[str], manual_avoid_clean: List[str]) -> Optional[Dict]:
        s = (ingredient_clean or '').lower()

        # manual avoid expansion: if banned is 'cheese', treat dairy set as banned too
        banned = set(manual_avoid_clean or [])
        if 'cheese' in banned and any(x in s for x in self.DAIRY):
            return {'constraint': 'manual_avoid', 'evidence': f"Ingredient contains dairy term under manual avoid 'cheese': '{ingredient_clean}'"}

        allergen_set = set([str(a).lower().strip() for a in (allergens or [])])

        if ('nut allergy' in allergen_set) or ('tree nut allergy' in allergen_set):
            if any(n in s for n in self.TREE_NUTS):
                return {'constraint': 'allergy', 'evidence': f"Ingredient contains tree nut keyword under nut allergy: '{ingredient_clean}'"}

        if 'peanut allergy' in allergen_set:
            if 'peanut' in s:
                return {'constraint': 'allergy', 'evidence': f"Ingredient contains 'peanut' under peanut allergy: '{ingredient_clean}'"}

        if ('egg allergy' in allergen_set) or ('poultry allergy' in allergen_set):
            if any(x in s for x in self.EGGS):
                return {'constraint': 'allergy', 'evidence': f"Ingredient contains egg keyword: '{ingredient_clean}'"}

        if ('gluten allergy' in allergen_set) or ('wheat allergy' in allergen_set):
            if 'gluten-free' in s or 'gluten free' in s:
                pass
            elif 'bread and butter' in s and 'pickle' in s:
                pass
            elif any(g in s for g in self.GLUTEN_TERMS):
                return {'constraint': 'allergy', 'evidence': f"Ingredient contains gluten/wheat keyword: '{ingredient_clean}'"}

        if dietary.get('vegan', False):
            if any(x in s for x in (self.DAIRY | self.EGGS | self.MEAT)):
                return {'constraint': 'dietary', 'evidence': f"Ingredient contains non-vegan keyword: '{ingredient_clean}'"}

        if dietary.get('halal', False):
            haram = {
                'pork', 'bacon', 'ham', 'lard', 'prosciutto', 'pancetta',
                'alcohol', 'wine', 'beer', 'vodka', 'rum', 'whiskey', 'whisky',
                'gin', 'vermouth', 'tequila', 'brandy', 'cognac', 'champagne', 'liqueur',
                'gelatin', 'gelatine',
            }
            if any(x in s for x in haram):
                return {'constraint': 'dietary', 'evidence': f"Ingredient contains haram keyword: '{ingredient_clean}'"}

        if dietary.get('kosher', False):
            kosher_forbidden = {
                'pork', 'bacon', 'ham', 'lard',
                'shellfish', 'shrimp', 'crab', 'lobster', 'oyster', 'clam', 'mussel',
                'scallop', 'squid', 'octopus', 'camel',
                'wine', 'grape juice',
            }
            if any(x in s for x in kosher_forbidden):
                return {'constraint': 'dietary', 'evidence': f"Ingredient contains non-kosher keyword: '{ingredient_clean}'"}
            if 'blood' in s and 'blood orange' not in s:
                return {'constraint': 'dietary', 'evidence': f"Ingredient contains blood (forbidden in kosher): '{ingredient_clean}'"}

        return None
