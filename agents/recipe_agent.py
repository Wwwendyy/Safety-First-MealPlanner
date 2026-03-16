"""
Recipe Agent - Handles recipe retrieval from database
"""
import re
from typing import List, Dict, Optional
from data.database import RecipeDatabase


# Minimum ingredients to count as a "meal" (filters out single-item sides, minimal dishes)
MIN_INGREDIENTS_FOR_MEAL = 4

# Title patterns that indicate a drink, spice blend, seasoning, or bread-only (not a main meal)
NON_MEAL_TITLE_PATTERNS = (
    r"\bcocktail\b",
    r"\bmargarita\b",
    r"\bdrink[s]?\b",
    r"\bdrinks\s+bar\b",
    r"\bsmoothie\b",
    r"\btea\s+bag",
    r"curry\s+powder$",
    r"green\s+seasoning$",
    r"spice\s+blend$",
    r"\bpowder$",
    r"\bseasoning$",
    r"^pita$",   # standalone bread
    r"^bread$",
    r"^naan$",
)

# Alcohol keywords in ingredients → treat as drink if recipe has few ingredients
ALCOHOL_TOKENS = {
    "tequila", "vodka", "rum", "gin", "whiskey", "whisky", "bourbon",
    "vermouth", "liqueur", "brandy", "cognac", "champagne",
}


class Recipe:
    def __init__(self, recipe_id: int, title: str, instructions: str, ingredients: List[str]):
        self.id = recipe_id
        self.title = title
        self.instructions = instructions
        self.ingredients = ingredients
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'instructions': self.instructions,
            'ingredients': self.ingredients
        }


class RecipeAgent:
    def __init__(self, database: RecipeDatabase):
        self.db = database

    def _is_likely_meal(self, recipe: Recipe) -> bool:
        """
        Filter out obvious non-meals: drinks, spice blends, seasonings, and
        recipes with too few ingredients (e.g. "just onions" or a cocktail).
        """
        ingredients = recipe.ingredients or []
        n = len(ingredients)
        if n < MIN_INGREDIENTS_FOR_MEAL:
            return False
        title_lower = (recipe.title or "").lower()
        for pat in NON_MEAL_TITLE_PATTERNS:
            if re.search(pat, title_lower):
                return False
        # Drink: alcohol present and few ingredients
        ing_lower = " ".join(str(x).lower() for x in ingredients)
        if any(a in ing_lower for a in ALCOHOL_TOKENS) and n <= 6:
            return False
        return True

    def get_candidates(self, user_preferences: Optional[Dict] = None, limit: int = 200) -> List[Recipe]:
        def _filter_meals(recipes: List[Recipe], max_count: int) -> List[Recipe]:
            out = [r for r in recipes if self._is_likely_meal(r)]
            return out[:max_count]

        # If user specified recipe names, search for those first
        if user_preferences and 'recipe_names' in user_preferences and user_preferences['recipe_names']:
            recipes = []
            for recipe_name in user_preferences['recipe_names']:
                found = self.search_by_name(recipe_name, limit=10)
                recipes.extend(found)
            # Also get general candidates
            all_recipes = self.db.search_recipes(filters=None, limit=limit)
            recipes.extend([self._dict_to_recipe(r) for r in all_recipes])
            # Deduplicate by ID
            seen_ids = set()
            unique_recipes = []
            for r in recipes:
                if r.id not in seen_ids:
                    seen_ids.add(r.id)
                    unique_recipes.append(r)
            return _filter_meals(unique_recipes, limit)
        
        # If keywords provided, search by keywords
        if user_preferences and 'keywords' in user_preferences and user_preferences['keywords']:
            keywords = user_preferences['keywords'].lower()
            recipes = self.search_by_keywords(keywords, limit=limit)
            if recipes:
                return _filter_meals(recipes, limit)
        
        # Otherwise, return general candidates (fetch extra so after filtering we have enough)
        fetch_limit = min(limit * 3, 2500)
        recipe_dicts = self.db.search_recipes(filters=None, limit=fetch_limit)
        recipes = [self._dict_to_recipe(r) for r in recipe_dicts]
        return _filter_meals(recipes, limit)
    
    def _dict_to_recipe(self, r_dict: Dict) -> Recipe:
        return Recipe(
            recipe_id=r_dict['id'],
            title=r_dict['title'],
            instructions=r_dict['instructions'],
            ingredients=r_dict['ingredients']
        )
    
    def search_by_name(self, recipe_name: str, limit: int = 10) -> List[Recipe]:
        recipe_dicts = self.db.search_recipes_by_name(recipe_name, limit=limit)
        return [self._dict_to_recipe(r) for r in recipe_dicts]
    
    def search_by_keywords(self, keywords: str, limit: int = 50) -> List[Recipe]:
        recipe_dicts = self.db.search_recipes_by_keywords(keywords, limit=limit)
        return [self._dict_to_recipe(r) for r in recipe_dicts]
    
    def get_recipe_by_id(self, recipe_id: int) -> Optional[Recipe]:
        recipe_dict = self.db.get_recipe_by_id(recipe_id)
        if not recipe_dict:
            return None
        
        return Recipe(
            recipe_id=recipe_dict['id'],
            title=recipe_dict['title'],
            instructions=recipe_dict['instructions'],
            ingredients=recipe_dict['ingredients']
        )
