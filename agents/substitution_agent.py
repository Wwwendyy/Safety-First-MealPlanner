from typing import Dict, List, Optional
from data.substitution_db import SubstitutionDatabase
from agents.reasoner_agent import ReasonerAgent
from agents.recipe_agent import Recipe


class SubstitutionAgent:
    def __init__(self, substitution_db: SubstitutionDatabase, reasoner_agent: ReasonerAgent):
        self.sub_db = substitution_db
        self.reasoner = reasoner_agent
    
    def repair_recipe(self, recipe: Recipe, violations: List[Dict], user_constraints: Dict) -> Dict:
        repair_log = []
        substitutions_made = []
        repaired_ingredients = recipe.ingredients.copy()
        
        repair_log.append(f"Attempting to repair recipe: {recipe.title}")
        repair_log.append(f"Found {len(violations)} violation(s)")
        
        # Group violations by ingredient
        violations_by_ingredient = {}
        for violation in violations:
            ing = violation.get('ingredient') or violation.get('cleaned', '')
            if ing not in violations_by_ingredient:
                violations_by_ingredient[ing] = []
            violations_by_ingredient[ing].append(violation)
        
        # Try to repair each violating ingredient
        for original_ingredient, ingredient_violations in violations_by_ingredient.items():
            repair_log.append(f"\nProcessing violation: '{original_ingredient}'")
            
            # Find candidate substitutes
            constraints_for_sub = {
                'allergens': user_constraints.get('allergens', []),
                'halal': user_constraints.get('halal', False),
                'kosher': user_constraints.get('kosher', False),
                'vegan': user_constraints.get('vegan', False)
            }
            
            candidates = self.sub_db.find_substitutes(original_ingredient, constraints_for_sub)
            
            if not candidates:
                repair_log.append(f"  → No substitutes found for '{original_ingredient}'")
                return {
                    'is_repairable': False,
                    'repaired_recipe': None,
                    'substitutions_made': [],
                    'repair_log': repair_log,
                    'final_check': None,
                    'reason': f"No substitutes found for '{original_ingredient}'"
                }
            
            repair_log.append(f"  → Found {len(candidates)} candidate substitute(s)")
            
            # Try each candidate substitute
            repaired = False
            for candidate in candidates:
                repair_log.append(f"  → Trying substitute: '{candidate}'")
                
                # Create repaired recipe with this substitution
                test_ingredients = []
                substitution_applied = False
                
                for ing in repaired_ingredients:
                    if ing == original_ingredient and not substitution_applied:
                        test_ingredients.append(candidate)
                        substitution_applied = True
                    else:
                        test_ingredients.append(ing)
                
                # Create test recipe
                test_recipe = Recipe(
                    recipe_id=recipe.id,
                    title=recipe.title,
                    instructions=recipe.instructions,
                    ingredients=test_ingredients
                )
                
                repair_log.append(f"    → Re-checking recipe with substitute...")
                recheck_result = self.reasoner.check_recipe(test_recipe, user_constraints)
                
                if recheck_result['label'] == 'safe':
                    # Success, This substitution works
                    repaired_ingredients = test_ingredients
                    substitutions_made.append({
                        'original': original_ingredient,
                        'substitute': candidate,
                        'reason': f"Resolves violations: {[v.get('constraint') for v in ingredient_violations]}"
                    })
                    repair_log.append(f"    → SUCCESS: '{candidate}' resolves violations")
                    repaired = True
                    break
                elif recheck_result['label'] == 'unsafe':
                    repair_log.append(f"    → FAILED: '{candidate}' introduces new violations")
                else:  # uncertain
                    repair_log.append(f"    → UNCERTAIN: '{candidate}' results in uncertain recipe")
            
            if not repaired:
                repair_log.append(f"  → Could not repair '{original_ingredient}' - no safe substitute found")
                return {
                    'is_repairable': False,
                    'repaired_recipe': None,
                    'substitutions_made': substitutions_made,
                    'repair_log': repair_log,
                    'final_check': None,
                    'reason': f"Could not find safe substitute for '{original_ingredient}'"
                }
        
        # All violations repaired - create final recipe
        repaired_recipe = Recipe(
            recipe_id=recipe.id,
            title=recipe.title,
            instructions=recipe.instructions,
            ingredients=repaired_ingredients
        )
        
        # Final re-validation
        repair_log.append(f"\nFinal re-validation of repaired recipe...")
        final_check = self.reasoner.check_recipe(repaired_recipe, user_constraints)
        
        if final_check['label'] == 'safe':
            repair_log.append(f"✓ Recipe successfully repaired!")
            return {
                'is_repairable': True,
                'repaired_recipe': repaired_recipe,
                'substitutions_made': substitutions_made,
                'repair_log': repair_log,
                'final_check': final_check
            }
        else:
            repair_log.append(f"✗ Final check failed: {final_check['explanation']}")
            return {
                'is_repairable': False,
                'repaired_recipe': repaired_recipe,
                'substitutions_made': substitutions_made,
                'repair_log': repair_log,
                'final_check': final_check,
                'reason': "Final re-validation failed"
            }
