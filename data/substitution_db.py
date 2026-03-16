import json
import os
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict


class SubstitutionDatabase:
    def __init__(self, substitution_json_path: Optional[str] = None, 
                 substitution_data: Optional[Dict] = None,
                 allergen_db=None):
        self.allergen_db = allergen_db
        self.graph = self._build_graph(substitution_json_path, substitution_data)
        if allergen_db:
            self._annotate_with_allergens()
    
    def _build_graph(self, json_path: Optional[str], data: Optional[Dict]) -> Dict[str, List[str]]:
        substitutions: Dict[str, List[str]] = defaultdict(list)
        
        if data:
            # Simple dict format: {ingredient: [substitutes]}
            for ingredient, subs in data.items():
                substitutions[ingredient.lower().strip()].extend([s.lower().strip() for s in subs])
        elif json_path and os.path.exists(json_path):
            # Check if it's substitution_pairs.json format
            with open(json_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            
            # Handle substitution_pairs.json format: list of {ingredient, substitution, ...}
            if isinstance(json_data, list) and len(json_data) > 0:
                first_item = json_data[0]
                if 'ingredient' in first_item and 'substitution' in first_item:
                    # This is substitution_pairs.json format
                    for item in json_data:
                        ingredient = str(item.get('ingredient', '')).lower().strip()
                        substitution = str(item.get('substitution', '')).lower().strip()
                        if ingredient and substitution and ingredient != substitution:
                            substitutions[ingredient].append(substitution)
                    # Deduplicate and return
                    result = {}
                    for k, vs in substitutions.items():
                        seen = set()
                        unique = []
                        for v in vs:
                            if v not in seen and v != k:
                                seen.add(v)
                                unique.append(v)
                        result[k] = unique[:10]
                    return result
            
            # Otherwise, try ConceptNet format
            edges = json_data.get("edges", []) if isinstance(json_data, dict) else json_data
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            edges = data.get("edges", []) if isinstance(data, dict) else data
            
            REL_KEYS = {"substitute", "substituted", "replace", "replaces", "similar", "synonym", "used_for"}
            
            def norm_node(x):
                if x is None:
                    return ""
                x = str(x).lower().strip()
                # Handle ConceptNet format: /c/en/peanut -> peanut
                if "/" in x:
                    x = x.split("/")[-1]
                x = x.replace("_", " ")
                return x.strip()
            
            for e in edges:
                rel = str(e.get("rel", "") or e.get("relation", "")).lower()
                rel_simple = rel.split("/")[-1].lower()
                
                if not any(k in rel_simple for k in REL_KEYS):
                    continue
                
                s = norm_node(e.get("start") or e.get("source") or e.get("from"))
                t = norm_node(e.get("end") or e.get("target") or e.get("to"))
                
                if s and t and s != t:
                    substitutions[s].append(t)
        
        # Deduplicate and limit
        result = {}
        for k, vs in substitutions.items():
            seen = set()
            unique = []
            for v in vs:
                if v not in seen and v != k:
                    seen.add(v)
                    unique.append(v)
            result[k] = unique[:10]  # Top 10 substitutes
        
        return result
    
    def _annotate_with_allergens(self):
        self.substitution_solves_allergen = defaultdict(set)
        
        if not self.allergen_db:
            return
        
        # For each substitution pair, check if substitute is allergen-free
        for ingredient, substitutes in self.graph.items():
            # Get allergens for original ingredient
            ingredient_allergens = set()
            lookups = getattr(self.allergen_db, 'lookups', None) or getattr(self.allergen_db, 'lookup', {}) or {}
            if ingredient in lookups:
                ingredient_allergens = lookups[ingredient]
            
            for substitute in substitutes:
                # Check if substitute triggers same allergens
                is_safe, triggered, _, _ = self.allergen_db.check_ingredient(
                    substitute, list(ingredient_allergens)
                )
                
                # If substitute is safe for allergens that original triggers, it's useful
                if is_safe and ingredient_allergens:
                    for allergen in ingredient_allergens:
                        self.substitution_solves_allergen[(ingredient, substitute)].add(allergen)
    
    def find_substitutes(self, ingredient: str, constraints: Optional[Dict] = None) -> List[str]:
        ingredient_lower = ingredient.lower().strip()
        
        if ingredient_lower not in self.graph:
            return []
        
        candidates = self.graph[ingredient_lower]
        
        if not constraints:
            return candidates
        
        # Filter by constraints
        filtered = []
        for candidate in candidates:
            if self._satisfies_constraints(candidate, constraints):
                filtered.append(candidate)
        
        return filtered if filtered else candidates  # Return all if none satisfy
    
    def _satisfies_constraints(self, ingredient: str, constraints: Dict) -> bool:
        # Check allergens
        if 'allergens' in constraints and constraints['allergens']:
            if self.allergen_db:
                is_safe, _, _, _ = self.allergen_db.check_ingredient(
                    ingredient, constraints['allergens']
                )
                if not is_safe:
                    return False
        
        # Check halal
        if constraints.get('halal', False):
            # Basic check - will be enhanced in dietary rules
            forbidden_halal = {'pork', 'bacon', 'ham', 'lard', 'alcohol', 'wine', 'beer', 'gelatin'}
            if any(f in ingredient.lower() for f in forbidden_halal):
                return False
        
        # Check vegan
        if constraints.get('vegan', False):
            # Basic check - will be enhanced in dietary rules
            forbidden_vegan = {'meat', 'chicken', 'beef', 'pork', 'fish', 'milk', 'cheese', 'butter', 'egg', 'honey'}
            if any(f in ingredient.lower() for f in forbidden_vegan):
                return False
        
        return True
    
    def get_substitution_pairs(self) -> List[Tuple[str, str]]:
        pairs = []
        for ingredient, substitutes in self.graph.items():
            for substitute in substitutes:
                pairs.append((ingredient, substitute))
        return pairs
