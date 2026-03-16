"""
Test suite for ReasonerAgent with critical test cases
"""
import unittest
import sys
import os
import pandas as pd

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.allergen_db import AllergenDatabase
from agents.reasoner_agent import ReasonerAgent
from agents.recipe_agent import Recipe


class TestReasonerAgent(unittest.TestCase):
    """Test cases for ReasonerAgent"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        # Create minimal allergen database for testing
        test_allergen_data = pd.DataFrame({
            'Food': ['peanut', 'almond', 'milk', 'egg', 'shrimp', 'crab'],
            'Allergy': ['Peanut Allergy', 'Nut Allergy', 'Dairy Allergy', 
                       'Egg Allergy', 'Shellfish Allergy', 'Shellfish Allergy']
        })
        
        cls.allergen_db = AllergenDatabase(allergen_df=test_allergen_data)
        cls.reasoner = ReasonerAgent(cls.allergen_db)
    
    def test_direct_allergen_match(self):
        """Test 1: Direct allergen match"""
        recipe = Recipe(
            recipe_id=1,
            title="Thai Peanut Noodles",
            instructions="Cook noodles",
            ingredients=["noodles", "peanut sauce", "vegetables"]
        )
        
        user_constraints = {
            'allergens': ['Peanut Allergy'],
            'halal': False,
            'kosher': False,
            'vegan': False
        }
        
        result = self.reasoner.check_recipe(recipe, user_constraints)
        
        self.assertEqual(result['label'], 'unsafe')
        self.assertGreater(len(result['violations']), 0)
        self.assertTrue(any('peanut' in str(v).lower() for v in result['violations']))
    
    def test_derivative_detection(self):
        """Test 2: Derivative detection (almond flour contains almond)"""
        recipe = Recipe(
            recipe_id=2,
            title="Almond Crusted Chicken",
            instructions="Coat chicken with almond flour",
            ingredients=["chicken", "almond flour", "salt"]
        )
        
        user_constraints = {
            'allergens': ['Nut Allergy'],
            'halal': False,
            'kosher': False,
            'vegan': False
        }
        
        result = self.reasoner.check_recipe(recipe, user_constraints)
        
        self.assertEqual(result['label'], 'unsafe')
        # Should detect almond in "almond flour"
        violations_text = str(result['violations']).lower()
        self.assertTrue('almond' in violations_text)
    
    def test_halal_violation(self):
        """Test 3: Halal constraint violation"""
        recipe = Recipe(
            recipe_id=3,
            title="Pork Chops",
            instructions="Cook pork",
            ingredients=["pork", "salt", "pepper"]
        )
        
        user_constraints = {
            'allergens': [],
            'halal': True,
            'kosher': False,
            'vegan': False
        }
        
        result = self.reasoner.check_recipe(recipe, user_constraints)
        
        self.assertEqual(result['label'], 'unsafe')
        violations_text = str(result['violations']).lower()
        self.assertTrue('halal' in violations_text or 'haram' in violations_text)
    
    def test_vegan_violation(self):
        """Test 4: Vegan constraint violation"""
        recipe = Recipe(
            recipe_id=4,
            title="Cheeseburger",
            instructions="Make burger",
            ingredients=["beef", "cheese", "bun"]
        )
        
        user_constraints = {
            'allergens': [],
            'halal': False,
            'kosher': False,
            'vegan': True
        }
        
        result = self.reasoner.check_recipe(recipe, user_constraints)
        
        self.assertEqual(result['label'], 'unsafe')
        violations_text = str(result['violations']).lower()
        self.assertTrue('vegan' in violations_text)
    
    def test_safe_recipe(self):
        """Test 5: Safe recipe (no violations)"""
        recipe = Recipe(
            recipe_id=5,
            title="Vegetable Stir Fry",
            instructions="Stir fry vegetables",
            ingredients=["carrots", "broccoli", "soy sauce", "rice"]
        )
        
        user_constraints = {
            'allergens': ['Peanut Allergy'],
            'halal': False,
            'kosher': False,
            'vegan': True
        }
        
        result = self.reasoner.check_recipe(recipe, user_constraints)
        
        # Should be safe (assuming no allergens in ingredients)
        # Note: This might be uncertain if ingredients aren't in allergen DB
        self.assertIn(result['label'], ['safe', 'uncertain'])
    
    def test_uncertain_ingredient(self):
        """Test 6: Uncertain ingredient (ambiguous)"""
        recipe = Recipe(
            recipe_id=6,
            title="Mystery Dish",
            instructions="Cook",
            ingredients=["chicken", "mystery sauce", "rice"]
        )
        
        user_constraints = {
            'allergens': ['Peanut Allergy'],
            'halal': False,
            'kosher': False,
            'vegan': False
        }
        
        result = self.reasoner.check_recipe(recipe, user_constraints)
        
        # Should be uncertain due to "mystery sauce"
        self.assertEqual(result['label'], 'uncertain')
        self.assertGreater(len(result['uncertain_ingredients']), 0)
    
    def test_multi_constraint(self):
        """Test 7: Multiple constraints"""
        recipe = Recipe(
            recipe_id=7,
            title="Creamy Pasta",
            instructions="Make pasta",
            ingredients=["pasta", "cream", "butter", "parmesan"]
        )
        
        user_constraints = {
            'allergens': ['Dairy Allergy'],
            'halal': True,
            'kosher': False,
            'vegan': False
        }
        
        result = self.reasoner.check_recipe(recipe, user_constraints)
        
        # Should be unsafe due to dairy allergy
        self.assertEqual(result['label'], 'unsafe')
        violations_text = str(result['violations']).lower()
        self.assertTrue('dairy' in violations_text or 'cream' in violations_text)


if __name__ == '__main__':
    unittest.main()
