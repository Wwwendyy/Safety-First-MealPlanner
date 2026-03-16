"""
Test suite for SubstitutionAgent with repair scenarios
"""
import unittest
import sys
import os
import pandas as pd

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.allergen_db import AllergenDatabase
from data.substitution_db import SubstitutionDatabase
from agents.reasoner_agent import ReasonerAgent
from agents.substitution_agent import SubstitutionAgent
from agents.recipe_agent import Recipe


class TestSubstitutionAgent(unittest.TestCase):
    """Test cases for SubstitutionAgent"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        # Create allergen database
        test_allergen_data = pd.DataFrame({
            'Food': ['milk', 'cream', 'butter', 'coconut', 'oat'],
            'Allergy': ['Dairy Allergy', 'Dairy Allergy', 'Dairy Allergy', 
                       'None', 'None']
        })
        
        cls.allergen_db = AllergenDatabase(allergen_df=test_allergen_data)
        cls.reasoner = ReasonerAgent(cls.allergen_db)
        
        # Create substitution database
        substitution_data = {
            'cream': ['coconut cream', 'oat cream'],
            'butter': ['olive oil', 'coconut oil'],
            'milk': ['oat milk', 'almond milk', 'coconut milk']
        }
        
        cls.substitution_db = SubstitutionDatabase(
            substitution_data=substitution_data,
            allergen_db=cls.allergen_db
        )
        
        cls.substitution_agent = SubstitutionAgent(cls.substitution_db, cls.reasoner)
    
    def test_successful_repair(self):
        """Test 1: Successful recipe repair"""
        recipe = Recipe(
            recipe_id=1,
            title="Creamy Pasta",
            instructions="Make pasta with cream",
            ingredients=["pasta", "cream", "salt"]
        )
        
        user_constraints = {
            'allergens': ['Dairy Allergy'],
            'halal': False,
            'kosher': False,
            'vegan': False
        }
        
        # First check - should be unsafe
        check_result = self.reasoner.check_recipe(recipe, user_constraints)
        self.assertEqual(check_result['label'], 'unsafe')
        
        # Try to repair
        repair_result = self.substitution_agent.repair_recipe(
            recipe, check_result['violations'], user_constraints
        )
        
        # Should be repairable
        self.assertTrue(repair_result['is_repairable'])
        self.assertIsNotNone(repair_result['repaired_recipe'])
        self.assertGreater(len(repair_result['substitutions_made']), 0)
        
        # Final check should be safe
        self.assertEqual(repair_result['final_check']['label'], 'safe')
    
    def test_repair_with_revalidation(self):
        """Test 2: Repair includes re-validation"""
        recipe = Recipe(
            recipe_id=2,
            title="Buttery Rice",
            instructions="Cook rice with butter",
            ingredients=["rice", "butter", "salt"]
        )
        
        user_constraints = {
            'allergens': ['Dairy Allergy'],
            'halal': False,
            'kosher': False,
            'vegan': False
        }
        
        check_result = self.reasoner.check_recipe(recipe, user_constraints)
        repair_result = self.substitution_agent.repair_recipe(
            recipe, check_result['violations'], user_constraints
        )
        
        # Should have re-validated
        self.assertIsNotNone(repair_result['final_check'])
        self.assertIn('trace', repair_result['final_check'])
    
    def test_repair_failure(self):
        """Test 3: Repair failure (no suitable substitute)"""
        recipe = Recipe(
            recipe_id=3,
            title="Special Dish",
            instructions="Cook",
            ingredients=["unknown_ingredient_xyz", "salt"]
        )
        
        user_constraints = {
            'allergens': ['Dairy Allergy'],
            'halal': False,
            'kosher': False,
            'vegan': False
        }
        
        # Create violation manually (since unknown ingredient won't trigger)
        violations = [{
            'constraint': 'allergy',
            'ingredient': 'unknown_ingredient_xyz',
            'cleaned': 'unknown_ingredient_xyz',
            'allergen': 'Dairy Allergy',
            'evidence': 'Test violation',
            'confidence': 1.0
        }]
        
        repair_result = self.substitution_agent.repair_recipe(
            recipe, violations, user_constraints
        )
        
        # Should not be repairable (no substitute found)
        self.assertFalse(repair_result['is_repairable'])


if __name__ == '__main__':
    unittest.main()
