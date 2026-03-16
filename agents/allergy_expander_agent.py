from typing import List, Set

class AllergyExpanderAgent:
    """Expand user-selected allergy labels into a more complete set.

    This fixes common label mismatches like:
      - 'Nut Allergy' should cover 'Tree Nut Allergy' foods.
      - Optionally include peanuts if desired (configurable).
    """

    EXPANSION = {
        'nut allergy': {'nut allergy', 'tree nut allergy'},
        'tree nut allergy': {'tree nut allergy'},
        'peanut allergy': {'peanut allergy'},
        'dairy allergy': {'dairy allergy', 'milk allergy'},
        'milk allergy': {'milk allergy', 'dairy allergy'},
        'egg allergy': {'egg allergy', 'poultry allergy'},
        'poultry allergy': {'egg allergy', 'poultry allergy'},
        'soy allergy': {'soy allergy'},
        'sesame allergy': {'sesame allergy'},
        'wheat allergy': {'wheat allergy', 'gluten allergy'},
        'gluten allergy': {'gluten allergy', 'wheat allergy'},
        'shellfish allergy': {'shellfish allergy'},
        'fish allergy': {'fish allergy'},
    }

    def __init__(self, include_peanut_in_nut: bool = False):
        self.include_peanut_in_nut = include_peanut_in_nut

    def expand(self, allergies: List[str]) -> List[str]:
        out: Set[str] = set()
        for a in allergies or []:
            key = str(a).lower().strip()
            if not key:
                continue
            if key in self.EXPANSION:
                out |= set(self.EXPANSION[key])
                if self.include_peanut_in_nut and key == 'nut allergy':
                    out.add('peanut allergy')
            else:
                out.add(key)
        # return original casing? reasoner uses lower, so keep lower
        return sorted(out)
