from flask import Flask, render_template, request, jsonify
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.database import RecipeDatabase
from data.allergen_db import AllergenDatabase
from data.substitution_db import SubstitutionDatabase
from data.preprocessing import IngredientPreprocessor
from agents.recipe_agent import RecipeAgent
from agents.reasoner_agent import ReasonerAgent
from agents.substitution_agent import SubstitutionAgent
from agents.orchestrator_agent import OrchestratorAgent

from dotenv import load_dotenv
load_dotenv()  # loads .env into os.environ

app = Flask(__name__)

# Global agents (initialized lazily or at startup)
recipe_db = None
allergen_db = None
substitution_db = None
orchestrator = None


def initialize_system():
    """
    Initialize DBs + agents.
    This is safe to call multiple times (will reassign globals).
    """
    global recipe_db, allergen_db, substitution_db, orchestrator

    # Configuration - use actual data files in data/ folder
    DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
    RECIPE_CSV = os.environ.get(
        "RECIPE_CSV_PATH",
        os.path.join(DATA_DIR, "Food Ingredients and Recipe Dataset with Image Name Mapping.csv"),
    )
    ALLERGEN_CSV = os.environ.get(
        "ALLERGEN_CSV_PATH",
        os.path.join(DATA_DIR, "FoodData.csv"),
    )
    SUBSTITUTION_JSON = os.environ.get(
        "SUBSTITUTION_JSON_PATH",
        os.path.join(DATA_DIR, "substitution_pairs.json"),
    )
    ORIG_TO_PROCESSED = os.path.join(DATA_DIR, "original_to_processed_mapping.csv")
    PROCESSED_ING = os.path.join(DATA_DIR, "processed_ingredients_with_id.csv")
    DB_PATH = os.environ.get("DB_PATH", "meal_planner.db")

    print("Initializing meal planner system...")

    # Initialize preprocessor
    print("Loading ingredient preprocessor...")
    preprocessor = IngredientPreprocessor(
        original_to_processed_path=ORIG_TO_PROCESSED if os.path.exists(ORIG_TO_PROCESSED) else None,
        processed_ingredients_path=PROCESSED_ING if os.path.exists(PROCESSED_ING) else None,
    )
    if getattr(preprocessor, "original_to_processed_map", None):
        print(f"    Loaded {len(preprocessor.original_to_processed_map)} ingredient mappings")

    # Initialize databases
    print("Loading recipe database...")
    recipe_db = RecipeDatabase(db_path=DB_PATH, preprocessor=preprocessor)

    # Check if database is empty (simple check)
    cursor = recipe_db.conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM recipes")
    recipe_count = cursor.fetchone()[0]

    # Load recipes from CSV if database is empty
    if recipe_count == 0 and os.path.exists(RECIPE_CSV):
        try:
            print(f"Loading recipes from {RECIPE_CSV}...")
            count = recipe_db.load_from_csv(RECIPE_CSV)
            print(f"Loaded {count} recipes")
        except Exception as e:
            print(f"Warning: Could not load recipes from CSV: {e}")
    elif recipe_count > 0:
        print(f"Database already contains {recipe_count} recipes")
    else:
        print(f"Warning: Recipe CSV not found at {RECIPE_CSV}")

    print("Loading allergen database...")
    if os.path.exists(ALLERGEN_CSV):
        allergen_db = AllergenDatabase(allergen_csv_path=ALLERGEN_CSV)
        try:
            print(f"Loaded allergen database with {len(allergen_db.get_all_allergens())} allergen types")
        except Exception:
            print("Loaded allergen database.")
    else:
        print(f"Warning: Allergen CSV not found at {ALLERGEN_CSV}")
        # Create empty allergen DB
        import pandas as pd
        allergen_db = AllergenDatabase(allergen_df=pd.DataFrame(columns=["Food", "Allergy"]))

    print("Loading substitution database...")
    if os.path.exists(SUBSTITUTION_JSON):
        substitution_db = SubstitutionDatabase(
            substitution_json_path=SUBSTITUTION_JSON,
            allergen_db=allergen_db,
        )
        print(f"Loaded substitution database with {len(substitution_db.graph)} substitutions")
    else:
        print(f"Warning: Substitution JSON not found at {SUBSTITUTION_JSON}")
        # Try alternative paths
        alt_paths = [
            os.path.join(DATA_DIR, "conceptnet.json"),
            os.path.join(DATA_DIR, "edamam.json"),
        ]
        found = False
        for alt_path in alt_paths:
            if os.path.exists(alt_path):
                substitution_db = SubstitutionDatabase(
                    substitution_json_path=alt_path,
                    allergen_db=allergen_db,
                )
                print(f"Loaded substitution database from {alt_path} with {len(substitution_db.graph)} substitutions")
                found = True
                break
        if not found:
            substitution_db = SubstitutionDatabase(substitution_data={}, allergen_db=allergen_db)

    # Initialize agents
    print("Initializing agents...")
    recipe_agent = RecipeAgent(recipe_db)
    reasoner_agent = ReasonerAgent(allergen_db, preprocessor=preprocessor)
    substitution_agent = SubstitutionAgent(substitution_db, reasoner_agent)
    orchestrator = OrchestratorAgent(recipe_agent, reasoner_agent, substitution_agent)

    print("✓ System initialized successfully!")
    return True


def ensure_initialized():
    """
    Lazy init: ensures orchestrator is ready even when running via `flask run`.
    Returns (ok: bool, err: str|None)
    """
    global orchestrator
    if orchestrator is not None:
        return True, None
    try:
        ok = initialize_system()
        if ok and orchestrator is not None:
            return True, None
        return False, "Initialization returned False or orchestrator is still None."
    except Exception as e:
        import traceback
        return False, f"{e}\n{traceback.format_exc()}"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "initialized": orchestrator is not None,
        "recipes_loaded": recipe_db is not None,
        "allergen_db_loaded": allergen_db is not None,
        "substitution_db_loaded": substitution_db is not None,
    })


@app.route("/profile", methods=["POST"])
def create_profile():
    data = request.get_json(force=True)

    profile = {
        "allergies": data.get("allergies", []),
        "manual_avoid": data.get("manual_avoid", []),
        "halal": bool(data.get("halal", False)),
        "kosher": bool(data.get("kosher", False)),
        "vegan": bool(data.get("vegan", False)),
        "preferences": data.get("preferences", {}),
        "soft_constraints": data.get("soft_constraints", {}),
    }

    return jsonify({
        "ok": True,
        "profile": profile,
        "message": "Profile saved successfully",
    })


@app.route("/generate_plan", methods=["POST"])
def generate_plan():
    """
    Generate meal plan
    Returns: JSON with recipes + explanations + grocery list
    """
    ok, err = ensure_initialized()
    if not ok:
        return jsonify({
            "ok": False,
            "error": "System not initialized",
            "details": err,
        }), 500

    try:
        data = request.get_json(force=True)
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": f"Invalid JSON: {str(e)}",
        }), 400

    user_profile = {
        "allergies": data.get("allergies", []),
        "manual_avoid": data.get("manual_avoid", []),
        "halal": bool(data.get("halal", False)),
        "kosher": bool(data.get("kosher", False)),
        "vegan": bool(data.get("vegan", False)),
        "preferences": data.get("preferences", {}),
        "soft_constraints": data.get("soft_constraints", {}),
    }

    try:
        num_days = int(data.get("days", 5))
        num_days = max(1, min(num_days, 28))  # clamp 1–28 days
    except (ValueError, TypeError):
        num_days = 5

    try:
        meal_plan = orchestrator.generate_meal_plan(user_profile, num_days)
        return jsonify({
            "ok": True,
            **meal_plan,
        })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error generating meal plan: {error_trace}")
        return jsonify({
            "ok": False,
            "error": f"Error generating meal plan: {str(e)}",
            "traceback": error_trace,
        }), 500


@app.route("/evaluate_recipe", methods=["POST"])
def evaluate_recipe():
    """
    Evaluate a single recipe against user constraints
    """
    ok, err = ensure_initialized()
    if not ok:
        return jsonify({
            "ok": False,
            "error": "System not initialized",
            "details": err,
        }), 500

    data = request.get_json(force=True)

    user_constraints = {
        "allergies": data.get("allergies", []),
        "allergens": data.get("allergies", []),  # compatibility
        "manual_avoid": data.get("manual_avoid", []),
        "halal": bool(data.get("halal", False)),
        "kosher": bool(data.get("kosher", False)),
        "vegan": bool(data.get("vegan", False)),
    }

    recipe_id = data.get("recipe_id")
    ingredients = data.get("ingredients", [])

    if recipe_id:
        recipe = orchestrator.recipe_agent.get_recipe_by_id(recipe_id)
        if not recipe:
            return jsonify({
                "ok": False,
                "error": "Recipe not found",
            }), 404
    elif ingredients:
        from agents.recipe_agent import Recipe
        recipe = Recipe(
            recipe_id=0,
            title=data.get("title", "Custom Recipe"),
            instructions=data.get("instructions", ""),
            ingredients=ingredients,
        )
    else:
        return jsonify({
            "ok": False,
            "error": "Must provide recipe_id or ingredients",
        }), 400

    check_result = orchestrator.reasoner.check_recipe(recipe, user_constraints)

    return jsonify({
        "ok": True,
        "recipe": recipe.to_dict(),
        "evaluation": check_result,
    })


if __name__ == "__main__":
    # If you run "python app.py", init once here (fast path).
    try:
        initialize_system()
    except Exception as e:
        print(f"Error initializing system: {e}")
        print("System will start but may not function correctly")

    app.run(host="0.0.0.0", port=8000, debug=True)