import os
import sys
import argparse

from data.database import RecipeDatabase
from data.preprocessing import IngredientPreprocessor


def main():
    parser = argparse.ArgumentParser(description='Load recipe data into database')
    parser.add_argument('--recipe-csv', type=str, required=True,
                       help='Path to recipe CSV file')
    parser.add_argument('--db-path', type=str, default='meal_planner.db',
                       help='Path to SQLite database file')
    parser.add_argument('--title-col', type=str, default='Title',
                       help='Name of title column in CSV')
    parser.add_argument('--ingredients-col', type=str, default='Cleaned_Ingredients',
                       help='Name of ingredients column in CSV')
    parser.add_argument('--instructions-col', type=str, default='Instructions',
                       help='Name of instructions column in CSV')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.recipe_csv):
        print(f"Error: Recipe CSV file not found: {args.recipe_csv}")
        sys.exit(1)
    
    print(f"Loading recipes from {args.recipe_csv}...")
    print(f"Database: {args.db_path}")
    
    # Initialize preprocessor if mapping files exist
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    orig_to_processed = os.path.join(data_dir, 'original_to_processed_mapping.csv')
    processed_ing = os.path.join(data_dir, 'processed_ingredients_with_id.csv')
    
    preprocessor = None
    if os.path.exists(orig_to_processed) or os.path.exists(processed_ing):
        print("Initializing ingredient preprocessor...")
        preprocessor = IngredientPreprocessor(
            original_to_processed_path=orig_to_processed if os.path.exists(orig_to_processed) else None,
            processed_ingredients_path=processed_ing if os.path.exists(processed_ing) else None
        )
        if preprocessor.original_to_processed_map:
            print(f"  Loaded {len(preprocessor.original_to_processed_map)} ingredient mappings")
    
    db = RecipeDatabase(db_path=args.db_path, preprocessor=preprocessor)
    
    try:
        count = db.load_from_csv(
            csv_path=args.recipe_csv,
            title_col=args.title_col,
            ingredients_col=args.ingredients_col,
            instructions_col=args.instructions_col
        )
        print(f"✓ Successfully loaded {count} recipes into database")
    except Exception as e:
        print(f"Error loading recipes: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == '__main__':
    main()
