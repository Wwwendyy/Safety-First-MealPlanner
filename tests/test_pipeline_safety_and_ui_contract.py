# /Users/wwendyw/Desktop/RRK/meal-planner/tests/test_pipeline_safety_and_ui_contract.py

import math
import pytest


# ----------------------------
# Helpers / fakes
# ----------------------------
class FakeRecipe:
    def __init__(self, title, ingredients, instructions=""):
        self.title = title
        self.ingredients = ingredients
        self.instructions = instructions


class FakePreprocessor:
    """Simulate a buggy normalizer that sometimes returns NaN."""
    def normalize_ingredient(self, raw):
        # Return NaN for anything containing "vermouth" to reproduce your trace
        if "vermouth" in str(raw).lower():
            return float("nan"), None
        return raw, None


class FakeDietaryCheckerUncertain:
    """Always returns uncertainty (should NOT become a violation)."""
    def check_dietary_constraints(self, ingredient, constraints):
        # New signature: (is_compliant, violations, uncertainties, explanation)
        return True, [], ["Halal: ambiguous source"], "ambiguous source (uncertain)"


class FakeDietaryCheckerForbidden:
    """Always returns forbidden (should become violation)."""
    def check_dietary_constraints(self, ingredient, constraints):
        return False, ["Halal: alcohol"], [], "contains alcohol (forbidden)"


# ----------------------------
# Tests: ReasonerAgent behavior
# ----------------------------
def test_reasoner_nan_fallback_does_not_produce_string_nan():
    """
    If preprocessor.normalize_ingredient() returns NaN, ReasonerAgent must fallback
    to clean_ingredient(raw) and should never use cleaned='nan'.
    """
    from agents.reasoner_agent import ReasonerAgent

    reasoner = ReasonerAgent()
    # Inject buggy preprocessor
    reasoner.preprocessor = FakePreprocessor()

    # Inject a dietary checker that won't reject it (so we can inspect cleaned output path)
    reasoner.dietary_checker = FakeDietaryCheckerUncertain()

    recipe = FakeRecipe(
        title="Test Vermouth Drink",
        ingredients=["3 oz. Noilly Prat dry vermouth", "1 oz. club soda"],
        instructions="mix"
    )

    user_constraints = {
        "allergies": [],
        "manual_avoid": [],
        "halal": False,   # keep false here; we only test fallback
        "kosher": False,
        "vegan": False,
    }

    result = reasoner.check_recipe(recipe, user_constraints)

    # Trace should not contain cleaned: 'nan'
    trace_text = "\n".join(result.get("trace", []))
    assert "cleaned: 'nan'" not in trace_text
    assert "cleaned: nan" not in trace_text  # just in case formatting differs


def test_reasoner_manual_avoid_is_hard_violation():
    """
    manual_avoid must trigger a violation if ingredient matches (hard constraint).
    """
    from agents.reasoner_agent import ReasonerAgent

    reasoner = ReasonerAgent()
    reasoner.preprocessor = None
    reasoner.dietary_checker = FakeDietaryCheckerUncertain()

    recipe = FakeRecipe(
        title="Peanut Oil Noodles",
        ingredients=["2 tbsp peanut oil", "noodles", "salt"],
        instructions="cook"
    )

    user_constraints = {
        "allergies": [],
        "manual_avoid": ["peanut", "peanut oil"],
        "halal": False,
        "kosher": False,
        "vegan": False,
    }

    result = reasoner.check_recipe(recipe, user_constraints)

    assert result["label"] == "unsafe"
    assert result["violations"], "Expected at least one violation for manual_avoid"


def test_reasoner_dietary_uncertain_becomes_uncertain_not_unsafe():
    """
    Dietary checker returning uncertainty should mark recipe uncertain (not unsafe).
    """
    from agents.reasoner_agent import ReasonerAgent

    reasoner = ReasonerAgent()
    reasoner.preprocessor = None
    reasoner.dietary_checker = FakeDietaryCheckerUncertain()

    recipe = FakeRecipe(
        title="Ambiguous Gelatin Dish",
        ingredients=["gelatin", "sugar"],
        instructions="mix"
    )

    user_constraints = {
        "allergies": [],
        "manual_avoid": [],
        "halal": True,   # the uncertainty is about halal source
        "kosher": False,
        "vegan": False,
    }

    result = reasoner.check_recipe(recipe, user_constraints)
    assert result["label"] == "uncertain"
    assert result.get("uncertain_ingredients"), "Expected uncertain_ingredients to be populated"


# ----------------------------
# Tests: Orchestrator UI contract
# ----------------------------
def test_orchestrator_returns_success_false_when_no_available_recipes(monkeypatch):
    """
    When no safe/repaired recipes exist, orchestrator should return success=False
    with message and rejected_samples so frontend won't crash (day1 index).
    """
    from agents.orchestrator_agent import OrchestratorAgent

    orch = OrchestratorAgent()

    # Force get_candidates to return some recipes that will be rejected
    bad_recipes = [
        FakeRecipe("Bad1", ["peanut oil"], "x"),
        FakeRecipe("Bad2", ["pork"], "x"),
    ]
    monkeypatch.setattr(orch.recipe_agent, "get_candidates", lambda preferences, limit=200: bad_recipes)

    # Force reasoner to mark everything unsafe (simulate strict constraints)
    def always_unsafe(recipe, user_constraints):
        return {
            "label": "unsafe",
            "violations": [{"constraint": "test", "ingredient": "x"}],
            "uncertain_ingredients": [],
            "explanation": "Unsafe for test",
            "trace": ["TRACE: unsafe"]
        }
    monkeypatch.setattr(orch.reasoner_agent, "check_recipe", always_unsafe)

    user_profile = {
        "allergies": ["Nut Allergy"],
        "manual_avoid": [],
        "halal": True,
        "kosher": False,
        "vegan": False,
        "preferences": {},
        "soft_constraints": {}
    }

    out = orch.generate_meal_plan(user_profile, num_days=5)

    assert out["success"] is False
    assert "message" in out and out["message"]
    assert "rejected_samples" in out
    assert isinstance(out["rejected_samples"], list)


# ----------------------------
# Bonus: method name compatibility
# ----------------------------
def test_reasoner_has_check_recipe_method():
    """
    Guards against the error: 'ReasonerAgent' object has no attribute 'check_recipe'
    """
    from agents.reasoner_agent import ReasonerAgent
    assert hasattr(ReasonerAgent, "check_recipe"), "ReasonerAgent must implement check_recipe()"