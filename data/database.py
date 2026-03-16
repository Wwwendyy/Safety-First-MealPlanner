"""
SQLite database for recipes with efficient querying
"""
import sqlite3
import pandas as pd
import ast
from typing import List, Dict, Optional, Set
import os
from data.preprocessing import IngredientPreprocessor, safe_parse_list


class RecipeDatabase:
    
    def __init__(self, db_path='meal_planner.db', preprocessor: Optional[IngredientPreprocessor] = None):
        self.db_path = db_path
        # Use check_same_thread=False for Flask's multi-threaded environment
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.preprocessor = preprocessor
        self._setup_tables()
    
    def _setup_tables(self):
        """Create database tables if they don't exist"""
        cursor = self.conn.cursor()
        
        # Recipes table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                instructions TEXT,
                cuisine TEXT,
                difficulty TEXT,
                cook_time INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Ingredients table (normalized)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ingredients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                normalized_name TEXT
            )
        ''')
        
        # Recipe-Ingredients junction table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS recipe_ingredients (
                recipe_id INTEGER,
                ingredient_id INTEGER,
                original_text TEXT,
                FOREIGN KEY (recipe_id) REFERENCES recipes(id),
                FOREIGN KEY (ingredient_id) REFERENCES ingredients(id),
                PRIMARY KEY (recipe_id, ingredient_id)
            )
        ''')
        
        # Indexes for performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_recipe_cuisine ON recipes(cuisine)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_recipe_difficulty ON recipes(difficulty)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_ingredient_name ON ingredients(normalized_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_recipe_ingredient_recipe ON recipe_ingredients(recipe_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_recipe_ingredient_ingredient ON recipe_ingredients(ingredient_id)')
        
        self.conn.commit()
    
    # safe_parse_list is now imported from preprocessing
    
    def load_from_csv(self, csv_path: str, title_col='Title', 
                     ingredients_col='Cleaned_Ingredients', 
                     instructions_col='Instructions'):
        """
        Load recipes from CSV file into database
        """
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV file not found: {csv_path}")
        
        df = pd.read_csv(csv_path)
        
        cursor = self.conn.cursor()
        
        # Get or create ingredient ID
        def get_or_create_ingredient(name: str) -> int:
            normalized = name.lower().strip()
            cursor.execute('SELECT id FROM ingredients WHERE normalized_name = ?', (normalized,))
            row = cursor.fetchone()
            if row:
                return row[0]
            cursor.execute('INSERT INTO ingredients (name, normalized_name) VALUES (?, ?)', 
                         (name, normalized))
            return cursor.lastrowid
        
        recipes_added = 0
        for idx, row in df.iterrows():
            try:
                title = str(row.get(title_col, f"Recipe {idx}")).strip()
                if not title:
                    continue
                
                instructions = str(row.get(instructions_col, "")).strip()
                
                # Parse ingredients
                ingredients_raw = safe_parse_list(row.get(ingredients_col, []))
                if not ingredients_raw:
                    continue
                
                # Insert recipe
                cursor.execute('''
                    INSERT INTO recipes (title, instructions) 
                    VALUES (?, ?)
                ''', (title, instructions))
                recipe_id = cursor.lastrowid
                
                # Insert ingredients and links
                for ing_text in ingredients_raw:
                    if not ing_text or not str(ing_text).strip():
                        continue
                    
                    # Normalize ingredient if preprocessor is available
                    if self.preprocessor:
                        normalized_ing, _ = self.preprocessor.normalize_ingredient(str(ing_text).strip())
                        # Store both original and normalized
                        ing_id = get_or_create_ingredient(normalized_ing)
                        cursor.execute('''
                            INSERT OR IGNORE INTO recipe_ingredients (recipe_id, ingredient_id, original_text)
                            VALUES (?, ?, ?)
                        ''', (recipe_id, ing_id, str(ing_text).strip()))
                    else:
                        ing_id = get_or_create_ingredient(str(ing_text).strip())
                        cursor.execute('''
                            INSERT OR IGNORE INTO recipe_ingredients (recipe_id, ingredient_id, original_text)
                            VALUES (?, ?, ?)
                        ''', (recipe_id, ing_id, str(ing_text).strip()))
                
                recipes_added += 1
                if recipes_added % 100 == 0:
                    self.conn.commit()
            
            except Exception as e:
                print(f"Error loading recipe {idx}: {e}")
                continue
        
        self.conn.commit()
        return recipes_added
    
    def search_recipes_by_name(self, name: str, limit: int = 10) -> List[Dict]:
        """Search recipes by name (case-insensitive partial match)"""
        cursor = self.conn.cursor()
        query = '''
            SELECT DISTINCT r.id, r.title, r.instructions
            FROM recipes r
            WHERE LOWER(r.title) LIKE ?
            LIMIT ?
        '''
        cursor.execute(query, (f'%{name.lower()}%', limit))
        rows = cursor.fetchall()
        
        recipes = []
        for row in rows:
            recipe_id = row['id']
            cursor.execute('''
                SELECT i.name, ri.original_text
                FROM recipe_ingredients ri
                JOIN ingredients i ON ri.ingredient_id = i.id
                WHERE ri.recipe_id = ?
            ''', (recipe_id,))
            ingredients = [r['original_text'] or r['name'] for r in cursor.fetchall()]
            
            recipes.append({
                'id': recipe_id,
                'title': row['title'],
                'instructions': row['instructions'],
                'ingredients': ingredients
            })
        
        return recipes
    
    def search_recipes_by_keywords(self, keywords: str, limit: int = 50) -> List[Dict]:
        """Search recipes by keywords in title or instructions"""
        cursor = self.conn.cursor()
        query = '''
            SELECT DISTINCT r.id, r.title, r.instructions
            FROM recipes r
            WHERE LOWER(r.title) LIKE ? OR LOWER(r.instructions) LIKE ?
            LIMIT ?
        '''
        keyword_pattern = f'%{keywords.lower()}%'
        cursor.execute(query, (keyword_pattern, keyword_pattern, limit))
        rows = cursor.fetchall()
        
        recipes = []
        for row in rows:
            recipe_id = row['id']
            cursor.execute('''
                SELECT i.name, ri.original_text
                FROM recipe_ingredients ri
                JOIN ingredients i ON ri.ingredient_id = i.id
                WHERE ri.recipe_id = ?
            ''', (recipe_id,))
            ingredients = [r['original_text'] or r['name'] for r in cursor.fetchall()]
            
            recipes.append({
                'id': recipe_id,
                'title': row['title'],
                'instructions': row['instructions'],
                'ingredients': ingredients
            })
        
        return recipes
    
    def search_recipes(self, filters: Optional[Dict] = None, limit: int = 100) -> List[Dict]:
        """
        Search recipes with optional filters.
        Orders by ingredient count (desc) so substantial meals are considered first.
        
        Args:
            filters: Dict with optional keys: cuisine, difficulty, max_cook_time
            limit: Maximum number of recipes to return
        
        Returns:
            List of recipe dictionaries with id, title, instructions, ingredients
        """
        cursor = self.conn.cursor()
        
        # Subquery for ingredient count so we can order by "substantial" recipes first
        query = '''
            SELECT r.id, r.title, r.instructions
            FROM recipes r
            LEFT JOIN recipe_ingredients ri ON ri.recipe_id = r.id
        '''
        conditions = []
        params = []
        
        if filters:
            if 'cuisine' in filters and filters['cuisine']:
                conditions.append('r.cuisine = ?')
                params.append(filters['cuisine'])
            
            if 'difficulty' in filters and filters['difficulty']:
                conditions.append('r.difficulty = ?')
                params.append(filters['difficulty'])
            
            if 'max_cook_time' in filters and filters['max_cook_time']:
                conditions.append('r.cook_time <= ?')
                params.append(filters['max_cook_time'])
        
        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)
        
        query += ' GROUP BY r.id ORDER BY COUNT(ri.recipe_id) DESC LIMIT ?'
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        recipes = []
        for row in rows:
            recipe_id = row['id']
            # Get ingredients for this recipe
            cursor.execute('''
                SELECT i.name, ri.original_text
                FROM recipe_ingredients ri
                JOIN ingredients i ON ri.ingredient_id = i.id
                WHERE ri.recipe_id = ?
            ''', (recipe_id,))
            ingredients = [r['original_text'] or r['name'] for r in cursor.fetchall()]
            
            recipes.append({
                'id': recipe_id,
                'title': row['title'],
                'instructions': row['instructions'],
                'ingredients': ingredients
            })
        
        return recipes
    
    def get_recipe_by_id(self, recipe_id: int) -> Optional[Dict]:
        """Get a single recipe by ID"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT id, title, instructions FROM recipes WHERE id = ?', (recipe_id,))
        row = cursor.fetchone()
        
        if not row:
            return None
        
        # Get ingredients
        cursor.execute('''
            SELECT i.name, ri.original_text
            FROM recipe_ingredients ri
            JOIN ingredients i ON ri.ingredient_id = i.id
            WHERE ri.recipe_id = ?
        ''', (recipe_id,))
        ingredients = [r['original_text'] or r['name'] for r in cursor.fetchall()]
        
        return {
            'id': row['id'],
            'title': row['title'],
            'instructions': row['instructions'],
            'ingredients': ingredients
        }
    
    def get_all_ingredients(self) -> Set[str]:
        """Get all unique ingredient names"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT DISTINCT normalized_name FROM ingredients')
        return {row[0] for row in cursor.fetchall()}
    
    def close(self):
        """Close database connection"""
        self.conn.close()
