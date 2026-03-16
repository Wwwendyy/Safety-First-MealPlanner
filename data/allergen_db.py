import pandas as pd
from typing import Dict, Set, List, Tuple, Optional
import re


class AllergenDatabase:
    def __init__(self, allergen_csv_path: Optional[str] = None, allergen_df: Optional[pd.DataFrame] = None):
        if allergen_df is not None:
            df = allergen_df
        elif allergen_csv_path:
            df = pd.read_csv(allergen_csv_path)
        else:
            raise ValueError("Must provide either allergen_csv_path or allergen_df")
        
        self.lookups = self._build_lookups(df)
        self.allergen_categories = self._build_allergen_categories(df)
    
    def _build_lookups(self, df: pd.DataFrame) -> Dict[str, Set[str]]:
        food_to_allergens: Dict[str, Set[str]] = {}
        allergen_to_foods: Dict[str, Set[str]] = {}
        
        for _, row in df.iterrows():
            food = str(row.get('Food', '')).lower().strip()
            allergy = str(row.get('Allergy', '')).strip()
            
            if not food or not allergy or food == 'nan' or allergy == 'nan':
                continue
            
            # Build food -> allergens mapping
            food_to_allergens.setdefault(food, set()).add(allergy)
            
            # Build allergen -> foods mapping
            allergen_to_foods.setdefault(allergy, set()).add(food)
        
        self.allergen_to_foods = allergen_to_foods
        return food_to_allergens
    
    def _build_allergen_categories(self, df: pd.DataFrame) -> Dict[str, Set[str]]:
        categories: Dict[str, Set[str]] = {}
        
        # Group foods by allergy type
        for allergen, foods in self.allergen_to_foods.items():
            categories[allergen.lower()] = foods
        
        return categories
    
    def check_ingredient(self, ingredient: str, user_allergens: List[str]) -> Tuple[bool, Optional[str], str, float]:
        ingredient_lower = ingredient.lower().strip()
        
        if not ingredient_lower:
            return True, None, "Empty ingredient", 0.0
        
        # Normalize user allergens
        user_allergens_lower = [a.lower().strip() for a in user_allergens]
        
        # 1. Direct match
        if ingredient_lower in self.lookups:
            triggered_allergens = self.lookups[ingredient_lower] & set(user_allergens_lower)
            if triggered_allergens:
                allergen = list(triggered_allergens)[0]
                return False, allergen, f"Direct match: '{ingredient}' is in allergen database as '{allergen}'", 1.0
        
        # 2. Partial match (derivative detection)
        # Check if any allergen food is a substring of the ingredient
        for food, allergens in self.lookups.items():
            if food in ingredient_lower:  # substring match
                triggered = set(allergens) & set(user_allergens_lower)
                if triggered:
                    allergen = list(triggered)[0]
                    return False, allergen, f"Partial match: '{ingredient}' contains '{food}' which triggers '{allergen}'", 0.9
        
        # 3. Reverse partial match (ingredient is substring of allergen food)
        for food, allergens in self.lookups.items():
            if ingredient_lower in food:
                triggered = set(allergens) & set(user_allergens_lower)
                if triggered:
                    allergen = list(triggered)[0]
                    return False, allergen, f"Reverse partial match: '{ingredient}' is contained in '{food}' which triggers '{allergen}'", 0.8
        
        # 4. Category-based reasoning
        # Check if ingredient matches any food in user's allergen categories
        for allergen in user_allergens_lower:
            if allergen in self.allergen_categories:
                category_foods = self.allergen_categories[allergen]
                # Check if ingredient matches any food in this category
                for food in category_foods:
                    if food in ingredient_lower or ingredient_lower in food:
                        return False, allergen, f"Category match: '{ingredient}' matches '{food}' in '{allergen}' category", 0.85
        
        # Safe - no matches found
        return True, None, f"No allergen match found for '{ingredient}'", 0.5
    
    def get_forbidden_foods(self, user_allergens: List[str]) -> Set[str]:
        forbidden = set()
        user_allergens_lower = [a.lower().strip() for a in user_allergens]
        
        for allergen in user_allergens_lower:
            if allergen in self.allergen_categories:
                forbidden.update(self.allergen_categories[allergen])
        
        return forbidden
    
    def get_all_allergens(self) -> Set[str]:
        return set(self.allergen_to_foods.keys())
