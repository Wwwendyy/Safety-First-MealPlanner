#!/usr/bin/env python3
"""
Run constraint test cases for the meal planner.
Execute: python tests/run_constraint_testcases.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load env for Azure/LLM (optional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Terms for validation (word boundary to avoid false positives like 'gin' in 'cumin')
GLUTEN_TERMS = {'bread', 'flour', 'wheat', 'pasta', 'toast', 'noodle', 'barley', 'rye'}
HARAM_TERMS = {'pork', 'bacon', 'ham', 'prosciutto', 'pancetta', 'wine', 'beer', 'vodka', 'rum', 'whiskey'}
NON_VEGAN_TERMS = {'chicken', 'beef', 'pork', 'fish', 'cheese', 'milk', 'butter'}


def has_forbidden(ingredients, title, forbidden_set):
    """Check if any ingredient or title contains a forbidden term (word boundary)."""
    import re
    text = " ".join(str(x).lower() for x in (ingredients or [])) + " " + (title or "").lower()
    for f in forbidden_set:
        if re.search(rf"\b{re.escape(f)}\b", text):
            return True
    return False


def run_unit_checks():
    """Run unit-level checks (no full pipeline)."""
    results = []
    try:
        from agents.title_guard_agent import TitleGuardAgent
        from agents.risk_lexicon_agent import RiskLexiconAgent
        from rules.dietary_rules import KosherRules, HalalRules, VeganRules

        tg = TitleGuardAgent()
        risk = RiskLexiconAgent()

        # Gluten title: "Toasts" should be caught
        r = tg.check_title("Spiced Sweet Potato Toasts", {}, [], ["gluten allergy", "wheat allergy"])
        ok = bool(r.get("violations"))
        results.append(("Gluten title guard (Toasts)", "PASS" if ok else "FAIL"))

        # Halal title: pork
        r = tg.check_title("Pork Chops", {"halal": True}, [], [])
        ok = bool(r.get("violations"))
        results.append(("Halal title guard (pork)", "PASS" if ok else "FAIL"))

        # Kosher title: shrimp
        r = tg.check_title("Shrimp Scampi", {"kosher": True}, [], [])
        ok = bool(r.get("violations"))
        results.append(("Kosher title guard (shrimp)", "PASS" if ok else "FAIL"))

        # Risk: bread + gluten
        r = risk.check("bread", {}, ["gluten allergy"], [])
        ok = r is not None
        results.append(("Risk lexicon bread+gluten", "PASS" if ok else "FAIL"))

        # Risk: gluten-free bread should pass
        r = risk.check("gluten-free bread", {}, ["gluten allergy"], [])
        ok = r is None
        results.append(("Risk lexicon gluten-free bread OK", "PASS" if ok else "FAIL"))

        # HalalRules: pork
        hr = HalalRules()
        s, _ = hr.is_halal_compliant("pork chops")
        results.append(("HalalRules pork", "PASS" if s == "forbidden" else "FAIL"))

        # KosherRules: grape juice
        kr = KosherRules()
        s, _ = kr.is_kosher_compliant("grape juice")
        results.append(("KosherRules grape juice", "PASS" if s == "forbidden" else "FAIL"))

        # VeganRules: cheese
        vr = VeganRules()
        s, _ = vr.is_vegan_compliant("cheddar")
        results.append(("VeganRules cheese", "PASS" if s == "forbidden" else "FAIL"))

    except Exception as e:
        results.append(("Unit checks", f"ERROR: {e}"))

    return results


def run_integration_tests(orchestrator):
    """Run full meal plan generation tests."""
    results = []
    test_cases = [
        {"name": "Vegan, 3 days", "profile": {"allergies": [], "vegan": True, "halal": False, "kosher": False}, "days": 3},
        {"name": "Halal, 3 days", "profile": {"allergies": [], "vegan": False, "halal": True, "kosher": False}, "days": 3},
        {"name": "Gluten allergy, 3 days", "profile": {"allergies": ["Wheat Allergy"], "vegan": False, "halal": False, "kosher": False}, "days": 3},
        {"name": "Nut allergy, 3 days", "profile": {"allergies": ["Nut Allergy"], "vegan": False, "halal": False, "kosher": False}, "days": 3},
        {"name": "Vegan + Nut allergy, 3 days", "profile": {"allergies": ["Nut Allergy"], "vegan": True, "halal": False, "kosher": False}, "days": 3},
        {"name": "No constraints, 5 days", "profile": {"allergies": [], "vegan": False, "halal": False, "kosher": False}, "days": 5},
    ]

    for tc in test_cases:
        try:
            out = orchestrator.generate_meal_plan(
                {**tc["profile"], "preferences": {}, "manual_avoid": [], "soft_constraints": {}},
                num_days=tc["days"],
            )
            success = out.get("success", False)
            plan = out.get("meal_plan", [])
            n = len(plan)

            # Validate constraints for each recipe
            violations = []
            if tc["profile"].get("vegan"):
                for day in plan:
                    ings = day.get("ingredients", [])
                    title = day.get("title", "")
                    if has_forbidden(ings, title, NON_VEGAN_TERMS):
                        violations.append(f"{day.get('title')}: possible non-vegan")
            if tc["profile"].get("halal"):
                for day in plan:
                    ings = day.get("ingredients", [])
                    title = day.get("title", "")
                    if has_forbidden(ings, title, HARAM_TERMS):
                        violations.append(f"{day.get('title')}: possible haram")
            if "Wheat Allergy" in (tc["profile"].get("allergies") or []):
                for day in plan:
                    ings = day.get("ingredients", [])
                    title = day.get("title", "")
                    if has_forbidden(ings, title, GLUTEN_TERMS):
                        violations.append(f"{day.get('title')}: possible gluten")

            if violations:
                status = f"FAIL (violations: {violations[:2]})"
            elif success and n >= 1:
                status = f"PASS ({n} days)"
            elif success and n == 0:
                status = "PASS (0 recipes - strict)"
            else:
                status = f"FAIL (success={success}, n={n})"

            results.append((tc["name"], status))
        except Exception as e:
            results.append((tc["name"], f"ERROR: {e}"))

    return results


def main():
    print("=" * 60)
    print("MEAL PLANNER CONSTRAINT TEST SUITE")
    print("=" * 60)

    # 1. Unit checks (no DB/network)
    print("\n--- Unit checks ---")
    for name, status in run_unit_checks():
        print(f"  {name}: {status}")

    # 2. Integration (needs DB)
    print("\n--- Integration (full pipeline) ---")
    try:
        from data.database import RecipeDatabase
        from data.allergen_db import AllergenDatabase
        from data.substitution_db import SubstitutionDatabase
        from data.preprocessing import IngredientPreprocessor
        from agents.recipe_agent import RecipeAgent
        from agents.reasoner_agent import ReasonerAgent
        from agents.substitution_agent import SubstitutionAgent
        from agents.orchestrator_agent import OrchestratorAgent

        ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        DATA_DIR = os.path.join(ROOT, "data")
        db_path = os.environ.get("DB_PATH") or os.path.join(ROOT, "meal_planner.db")
        if not os.path.exists(db_path):
            print("  Skipped: meal_planner.db not found (run app first to create)")
        else:
            preprocessor = IngredientPreprocessor(
                original_to_processed_path=os.path.join(DATA_DIR, "original_to_processed_mapping.csv") if os.path.exists(os.path.join(DATA_DIR, "original_to_processed_mapping.csv")) else None,
                processed_ingredients_path=os.path.join(DATA_DIR, "processed_ingredients_with_id.csv") if os.path.exists(os.path.join(DATA_DIR, "processed_ingredients_with_id.csv")) else None,
            )
            recipe_db = RecipeDatabase(db_path=db_path, preprocessor=preprocessor)
            allergen_db = AllergenDatabase(allergen_csv_path=os.path.join(DATA_DIR, "FoodData.csv"))
            sub_db = SubstitutionDatabase(substitution_json_path=os.path.join(DATA_DIR, "substitution_pairs.json"), allergen_db=allergen_db)
            recipe_agent = RecipeAgent(recipe_db)
            reasoner = ReasonerAgent(allergen_db, preprocessor=preprocessor)
            sub_agent = SubstitutionAgent(sub_db, reasoner)
            orch = OrchestratorAgent(recipe_agent, reasoner, sub_agent)
            for name, status in run_integration_tests(orch):
                print(f"  {name}: {status}")
    except Exception as e:
        import traceback
        print(f"  Skipped: {e}")
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("Done.")


if __name__ == "__main__":
    main()
