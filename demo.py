import os
import sys
import pandas as pd

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.database import RecipeDatabase
from data.allergen_db import AllergenDatabase
from data.substitution_db import SubstitutionDatabase
from agents.recipe_agent import RecipeAgent
from agents.reasoner_agent import ReasonerAgent
from agents.substitution_agent import SubstitutionAgent
from agents.orchestrator_agent import OrchestratorAgent


def create_demo_data():
    # Create demo allergen data
    allergen_data = pd.DataFrame({
        'Food': ['peanut', 'almond', 'milk', 'cream', 'butter', 'egg', 'shrimp'],
        'Allergy': ['Peanut Allergy', 'Nut Allergy', 'Dairy Allergy', 'Dairy Allergy',
                   'Dairy Allergy', 'Egg Allergy', 'Shellfish Allergy']
    })
    
    # Create demo recipe data
    recipe_data = pd.DataFrame({
        'Title': [
            'Vegetable Stir Fry',
            'Creamy Pasta',
            'Almond Cookies',
            'Peanut Butter Sandwich'
        ],
        'Ingredients': [
            '["carrots", "broccoli", "soy sauce", "rice"]',
            '["pasta", "cream", "butter", "parmesan"]',
            '["flour", "almond flour", "sugar", "butter"]',
            '["bread", "peanut butter", "jelly"]'
        ],
        'Instructions': [
            'Stir fry vegetables',
            'Cook pasta with cream sauce',
            'Bake cookies',
            'Make sandwich'
        ],
        'Cleaned_Ingredients': [
            '["carrots", "broccoli", "soy sauce", "rice"]',
            '["pasta", "cream", "butter", "parmesan"]',
            '["flour", "almond flour", "sugar", "butter"]',
            '["bread", "peanut butter", "jelly"]'
        ]
    })
    
    return allergen_data, recipe_data


def main():
    print("=" * 60)
    print("Reasoning-Based Weekly Meal Planner - Demo")
    print("=" * 60)
    
    # Create demo data
    print("\n1. Creating demo data...")
    allergen_data, recipe_data = create_demo_data()
    
    # Initialize databases
    print("\n2. Initializing databases...")
    recipe_db = RecipeDatabase(db_path='demo_meal_planner.db')
    
    # Load demo recipes
    recipe_data.to_csv('demo_recipes.csv', index=False)
    count = recipe_db.load_from_csv('demo_recipes.csv')
    print(f"   Loaded {count} recipes")
    
    allergen_db = AllergenDatabase(allergen_df=allergen_data)
    print(f"   Loaded allergen database with {len(allergen_db.get_all_allergens())} allergen types")
    
    # Create simple substitution data
    substitution_data = {
        'cream': ['coconut cream'],
        'butter': ['olive oil'],
        'milk': ['oat milk']
    }
    substitution_db = SubstitutionDatabase(
        substitution_data=substitution_data,
        allergen_db=allergen_db
    )
    print(f"   Loaded substitution database")
    
    # Initialize agents
    print("\n3. Initializing agents...")
    recipe_agent = RecipeAgent(recipe_db)
    reasoner_agent = ReasonerAgent(allergen_db)
    substitution_agent = SubstitutionAgent(substitution_db, reasoner_agent)
    orchestrator = OrchestratorAgent(recipe_agent, reasoner_agent, substitution_agent)
    
    # Test case 1: User with peanut allergy
    print("\n4. Test Case 1: User with Peanut Allergy")
    print("-" * 60)
    user_profile_1 = {
        'allergies': ['Peanut Allergy'],
        'halal': False,
        'kosher': False,
        'vegan': False,
        'preferences': {}
    }
    
    meal_plan_1 = orchestrator.generate_meal_plan(user_profile_1, num_days=2)
    print(f"   Found {meal_plan_1['stats']['safe_recipes_found']} safe recipes")
    print(f"   Repaired {meal_plan_1['stats']['repaired_recipes']} recipes")
    print(f"   Rejected {meal_plan_1['stats']['rejected_recipes']} recipes")
    
    for day in meal_plan_1['meal_plan']:
        print(f"\n   Day {day['day']}: {day['title']}")
        print(f"   Status: {day['status'].upper()}")
        print(f"   Explanation: {day['explanation']}")
        if day.get('substitutions'):
            print(f"   Substitutions: {day['substitutions']}")
    
    # Test case 2: User with dairy allergy + halal
    print("\n5. Test Case 2: User with Dairy Allergy + Halal")
    print("-" * 60)
    user_profile_2 = {
        'allergies': ['Dairy Allergy'],
        'halal': True,
        'kosher': False,
        'vegan': False,
        'preferences': {}
    }
    
    meal_plan_2 = orchestrator.generate_meal_plan(user_profile_2, num_days=2)
    print(f"   Found {meal_plan_2['stats']['safe_recipes_found']} safe recipes")
    print(f"   Repaired {meal_plan_2['stats']['repaired_recipes']} recipes")
    print(f"   Rejected {meal_plan_2['stats']['rejected_recipes']} recipes")
    
    for day in meal_plan_2['meal_plan']:
        print(f"\n   Day {day['day']}: {day['title']}")
        print(f"   Status: {day['status'].upper()}")
        print(f"   Explanation: {day['explanation']}")
        if day.get('substitutions'):
            print(f"   Substitutions: {day['substitutions']}")
    
    # Cleanup
    print("\n6. Cleaning up...")
    recipe_db.close()
    if os.path.exists('demo_recipes.csv'):
        os.remove('demo_recipes.csv')
    if os.path.exists('demo_meal_planner.db'):
        os.remove('demo_meal_planner.db')
    
    print("\n" + "=" * 60)
    print("Demo completed!")
    print("=" * 60)


if __name__ == '__main__':
    main()
