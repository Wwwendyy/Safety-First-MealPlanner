# agents/orchestrator_agent.py
# Two-phase orchestration:
#   Phase 1: deterministic filtering (NO LLM)
#   Phase 2: LLM verification ONLY for a small shortlist (Top-K)
# If Phase2 yields < num_days, we run substitution repair on Phase2-failed recipes,
# and re-verify repaired versions with LLM until we fill num_days or hit budgets.

from typing import Dict, List, Tuple, Any, Optional
from collections import defaultdict

from agents.recipe_agent import RecipeAgent, Recipe
from agents.reasoner_agent import ReasonerAgent
from agents.substitution_agent import SubstitutionAgent
from agents.allergy_expander_agent import AllergyExpanderAgent
from agents.final_safety_gate_agent import FinalSafetyGateAgent

# Optional: LLM ingredient extraction (Azure OpenAI)
try:
    from agents.hf_ingredient_extractor import HFIngredientExtractor
except Exception:
    HFIngredientExtractor = None


class OrchestratorAgent:
    """
    Two-Phase Pipeline (scales to large recipe corpora):

    Phase 1 (NO LLM):
      - Retrieve candidates (RecipeAgent)
      - Run deterministic Reasoner on raw ingredient lines
      - Collect a "pre-plan shortlist" (safe-first; optionally include uncertain if needed)

    Phase 2 (SMALL LLM BUDGET):
      - Take Top-K from pre-plan shortlist
      - For each: run LLM ingredient extraction + deterministic re-check + FinalSafetyGate
      - Keep only passed recipes

    If Phase2 results < requested num_days:
      - Take Phase2 failed recipes
      - Run SubstitutionAgent repair (using Phase2 violations/uncertainties as targets)
      - Re-verify repaired recipes with LLM + FinalSafetyGate
      - Continue until filled or budgets exhausted

    Key design goals:
      - LLM is used ONLY for final verification + repair verification (bounded calls).
      - Deterministic logic remains the judge (Reasoner + FinalSafetyGate).
      - Avoid LLM across broad candidate pools (prevents dozens/hundreds of calls).
    """

    def __init__(
        self,
        recipe_agent: RecipeAgent,
        reasoner_agent: ReasonerAgent,
        substitution_agent: SubstitutionAgent,
        enable_llm_extraction: bool = True,
    ):
        self.recipe_agent = recipe_agent
        self.reasoner = reasoner_agent
        self.substitution = substitution_agent

        self.allergy_expander = AllergyExpanderAgent()
        self.final_gate = FinalSafetyGateAgent(reasoner_agent)

        self.enable_llm_extraction = bool(enable_llm_extraction)
        self.extractor = None
        if self.enable_llm_extraction and HFIngredientExtractor is not None:
            try:
                self.extractor = HFIngredientExtractor()
            except Exception:
                self.extractor = None

        print("LLM extractor ready:", self.extractor is not None)

    # -------------------------
    # Helpers
    # -------------------------

    def _prepare_constraints(self, user_profile: Dict) -> Dict:
        allergies = user_profile.get("allergies", []) or []
        expanded = self.allergy_expander.expand(allergies)

        return {
            "allergies": allergies,
            "expanded_allergies": expanded,
            "allergens": expanded,  # backward compatibility
            "manual_avoid": user_profile.get("manual_avoid", []) or [],
            "halal": bool(user_profile.get("halal", False)),
            "kosher": bool(user_profile.get("kosher", False)),
            "vegan": bool(user_profile.get("vegan", False)),
        }

    def _llm_extract_recipe_ingredients(self, recipe: Recipe) -> None:
        """
        Scheme B: Replace recipe.ingredients with canonical ingredients extracted by LLM.
        Preserve full extracted metadata (raw + canonical + confidence + processing) as recipe.llm_extracted_lines.
        """
        if not self.extractor:
            setattr(recipe, "llm_uncertain_ingredients", [])
            setattr(recipe, "llm_extracted_lines", [])
            return

        raw_lines = recipe.ingredients if isinstance(recipe.ingredients, list) else []
        setattr(recipe, "original_ingredient_lines", raw_lines)

        try:
            canonical, uncertain, extracted = self.extractor.canonicalize_recipe_ingredients_with_metadata(
                raw_lines, uncertain_threshold=0.6
            )
        except Exception:
            canonical, uncertain = self.extractor.canonicalize_recipe_ingredients(
                raw_lines, uncertain_threshold=0.6
            )
            extracted = []

        recipe.ingredients = canonical
        setattr(recipe, "llm_uncertain_ingredients", uncertain)
        setattr(recipe, "llm_extracted_lines", extracted)

    def _soft_score(self, recipe: Recipe, soft: Dict) -> float:
        """Soft constraints affect ranking only (never hard-reject)."""
        if not soft:
            return 0.0

        s = 0.0
        ings = recipe.ingredients or []
        instr = recipe.instructions or ""

        if soft.get("easy_to_cook"):
            s += max(0.0, 20.0 - float(len(ings)))
            s += max(0.0, 800.0 - float(len(instr))) / 200.0

        if soft.get("low_fat"):
            bad = [
                "butter", "cream", "bacon", "lard", "mayonnaise",
                "cheese", "ghee", "ricotta", "parmesan"
            ]
            s -= 3.0 * sum(1 for x in ings if any(b in str(x).lower() for b in bad))

        if soft.get("avoid_spicy"):
            spicy = ["chili", "chile", "cayenne", "jalapeno", "hot sauce", "pepper flakes"]
            s -= 3.0 * sum(1 for x in ings if any(b in str(x).lower() for b in spicy))

        return s

    def _build_repair_targets_from_check(self, check: Dict) -> List[Dict]:
        """
        SubstitutionAgent expects a list of "violations" with ingredient/cleaned/evidence-ish fields.
        For uncertain, we convert uncertain items into repair targets too.
        """
        targets = list(check.get("violations", []) or [])

        for u in (check.get("uncertain_ingredients") or []):
            targets.append({
                "constraint": "uncertain",
                "ingredient": (u.get("cleaned") or u.get("ingredient") or ""),
                "cleaned": (u.get("cleaned") or ""),
                "evidence": u.get("reason", "uncertain"),
            })

        return targets

    def _llm_verify_one(
        self,
        recipe: Recipe,
        constraints: Dict,
        llm_calls_state: Dict[str, int],
        llm_call_budget: int
    ) -> Tuple[bool, Dict, Dict]:
        """
        LLM verify pipeline for a single recipe:
          - LLM extract -> reasoner check -> final gate verify
        Returns: (passed, check, gate_check)
        """
        if not self.extractor:
            # no llm available, fall back to deterministic only
            check = self.reasoner.check_recipe(recipe, constraints)
            gate = self.final_gate.verify(recipe, constraints)
            return bool(gate.get("passed_gate")), check, gate

        if llm_calls_state["used"] >= llm_call_budget:
            # budget exhausted: treat as not passed (or skip)
            check = self.reasoner.check_recipe(recipe, constraints)
            gate = {"passed_gate": False, "reason": "LLM budget exhausted"}
            return False, check, gate

        # 1 call per recipe verification in this implementation
        self._llm_extract_recipe_ingredients(recipe)
        llm_calls_state["used"] += 1

        check = self.reasoner.check_recipe(recipe, constraints)
        gate = self.final_gate.verify(recipe, constraints)

        return bool(gate.get("passed_gate")), check, gate

    # -------------------------
    # Main
    # -------------------------

    def generate_meal_plan(self, user_profile: Dict, num_days: int = 5) -> Dict:
        constraints = self._prepare_constraints(user_profile)
        preferences = user_profile.get("preferences", {}) or {}
        soft = user_profile.get("soft_constraints", {}) or {}

        # -------------------------
        # Budget knobs (safe defaults)
        # -------------------------
        # Phase2 verify shortlist size:
        verify_multiplier = int(user_profile.get("llm_verify_multiplier", 2) or 2)
        verify_k = max(num_days * verify_multiplier, num_days)

        # Total LLM call budget for this request:
        #  - verify_k calls for verification
        #  - plus some extra for repair verification
        # You can tune this from UI/user_profile later.
        llm_call_budget = int(user_profile.get("llm_call_budget", max(12, verify_k + num_days)) or max(12, verify_k + num_days))

        llm_calls_state = {"used": 0}

        # Candidate retrieval limits (Phase1 only; no LLM)
        strict_diet = bool(constraints.get("vegan") or constraints.get("halal") or constraints.get("kosher"))
        allergies = constraints.get("allergens") or constraints.get("allergies") or []
        many_allergies = len(allergies) >= 4

        # Keep Phase1 candidate pool reasonable (you have 30k recipes).
        # This pool size is enough for most constraints but won't blow up.
        base = 450 if (strict_diet or many_allergies) else 250
        candidate_limit = int(user_profile.get("candidate_limit", max(base, min(num_days * 80, 800))) or max(base, min(num_days * 80, 800)))

        candidates = self.recipe_agent.get_candidates(preferences, limit=candidate_limit)
        if not candidates:
            candidates = self.recipe_agent.get_candidates({}, limit=candidate_limit)

        # -------------------------
        # Phase 1: deterministic pre-filter (NO LLM)
        # -------------------------
        prelim_safe: List[Tuple[Recipe, Dict]] = []
        prelim_uncertain: List[Tuple[Recipe, Dict]] = []
        prelim_unsafe: List[Tuple[Recipe, Dict]] = []

        for recipe in candidates:
            # IMPORTANT: Phase1 uses raw ingredient lines (no llm extraction)
            check = self.reasoner.check_recipe(recipe, constraints)
            if check["label"] == "safe":
                prelim_safe.append((recipe, check))
            elif check["label"] == "uncertain":
                prelim_uncertain.append((recipe, check))
            else:
                prelim_unsafe.append((recipe, check))

        # Sort prelim pools by soft score to build a good "pre-plan" shortlist
        prelim_safe.sort(key=lambda x: self._soft_score(x[0], soft), reverse=True)
        prelim_uncertain.sort(key=lambda x: self._soft_score(x[0], soft), reverse=True)

        # Pre-plan shortlist:
        # - Prefer safe recipes
        # - If not enough, append uncertain recipes (Phase2 LLM may clarify)
        preplan: List[Tuple[Recipe, Dict, str]] = []
        for r, c in prelim_safe:
            preplan.append((r, c, "pre_safe"))
            if len(preplan) >= verify_k:
                break

        if len(preplan) < verify_k:
            for r, c in prelim_uncertain:
                preplan.append((r, c, "pre_uncertain"))
                if len(preplan) >= verify_k:
                    break

        # If still nothing, try to repair a few unsafe deterministically (NO LLM)
        # This helps when constraints are strict and safe pool is empty.
        if not preplan:
            repaired_preplan: List[Tuple[Recipe, Dict, str]] = []
            for r, c in prelim_unsafe[:min(40, len(prelim_unsafe))]:
                repair = self.substitution.repair_recipe(r, c.get("violations", []), constraints)
                if repair.get("is_repairable"):
                    repaired = repair["repaired_recipe"]
                    # Phase1 re-check, still NO LLM
                    check2 = self.reasoner.check_recipe(repaired, constraints)
                    if check2["label"] == "safe":
                        repaired_preplan.append((repaired, check2, "pre_repaired"))
                if len(repaired_preplan) >= verify_k:
                    break
            preplan = repaired_preplan

        if not preplan:
            # Nothing even for preplan -> fail fast
            samples = []
            for r, c in prelim_unsafe[:6]:
                samples.append({
                    "title": r.title,
                    "label": c.get("label"),
                    "explanation": c.get("explanation"),
                    "trace_preview": (c.get("trace") or [])[:8],
                })
            return {
                "success": False,
                "num_days": 0,
                "meal_plan": [],
                "grocery_list": [],
                "message": "No feasible pre-plan candidates found. Try relaxing constraints or keywords.",
                "rejected_samples": samples,
                "stats": {
                    "phase1_safe": len(prelim_safe),
                    "phase1_uncertain": len(prelim_uncertain),
                    "phase1_unsafe": len(prelim_unsafe),
                    "total_candidates": len(candidates),
                    "llm_calls_used": llm_calls_state["used"],
                    "llm_call_budget": llm_call_budget,
                },
            }

        # -------------------------
        # Phase 2: LLM verification for small shortlist
        # -------------------------
        verified_items: List[Dict[str, Any]] = []
        failed_items: List[Dict[str, Any]] = []

        for recipe, precheck, pre_status in preplan:
            passed, check, gate = self._llm_verify_one(
                recipe, constraints, llm_calls_state, llm_call_budget
            )
            if passed:
                verified_items.append({
                    "recipe": recipe,
                    "check_result": check,
                    "gate_check": gate,
                    "status": "verified",
                    "pre_status": pre_status,
                })
            else:
                failed_items.append({
                    "recipe": recipe,
                    "check_result": check,
                    "gate_check": gate,
                    "status": "failed_verify",
                    "pre_status": pre_status,
                })

            if len(verified_items) >= num_days:
                break

        # -------------------------
        # If verified not enough: repair failed recipes using substitution, then re-verify with LLM
        # -------------------------
        repaired_items: List[Dict[str, Any]] = []

        if len(verified_items) < num_days and failed_items:
            # repair attempts are bounded by remaining budget and remaining need
            need = num_days - len(verified_items)

            for item in failed_items:
                if need <= 0:
                    break
                if llm_calls_state["used"] >= llm_call_budget:
                    break

                recipe = item["recipe"]
                check = item["check_result"]

                repair_targets = self._build_repair_targets_from_check(check)
                # If no explicit targets, skip
                if not repair_targets:
                    continue

                repair = self.substitution.repair_recipe(recipe, repair_targets, constraints)
                if not repair.get("is_repairable"):
                    continue

                repaired = repair["repaired_recipe"]

                # Re-verify repaired recipe WITH LLM (budgeted)
                passed2, check2, gate2 = self._llm_verify_one(
                    repaired, constraints, llm_calls_state, llm_call_budget
                )

                if passed2:
                    repaired_items.append({
                        "recipe": repaired,
                        "original_recipe": recipe,
                        "check_result": check2,
                        "gate_check": gate2,
                        "substitutions": repair.get("substitutions_made", []),
                        "repair_log": repair.get("repair_log", []),
                        "status": "repaired_verified",
                    })
                    need -= 1

        # Merge verified + repaired, then rank by soft score again (final)
        all_final = verified_items + repaired_items
        all_final.sort(key=lambda x: self._soft_score(x["recipe"], soft), reverse=True)
        selected = all_final[:num_days]

        # If still short, we can optionally expand preplan with more uncertain candidates and repeat verification,
        # but keeping this minimal to avoid complexity. You can enable this later with a flag.
        if len(selected) < num_days:
            # Return partial results with a clear message.
            message = (
                f"Generated {len(selected)}/{num_days} meals under current constraints. "
                "Try relaxing constraints/keywords or increasing LLM budget."
            )
        else:
            message = "OK"

        # Build grocery list from selected recipes (use final recipe.ingredients which may be canonical if LLM ran)
        grocery = self.generate_grocery_list([x["recipe"] for x in selected])

        # Output structure
        meal_plan = []
        for i, item in enumerate(selected):
            r = item["recipe"]
            day = {
                "day": i + 1,
                "recipe_id": getattr(r, "id", None),
                "title": r.title,
                "instructions": r.instructions,
                "ingredients": r.ingredients,
                "status": item["status"],
                "pre_status": item.get("pre_status"),
                "explanation": item["check_result"].get("explanation"),
                "trace": item["check_result"].get("trace", []),
            }

            if hasattr(r, "original_ingredient_lines"):
                day["original_ingredient_lines"] = getattr(r, "original_ingredient_lines", [])

            if item["status"] == "repaired_verified":
                day["substitutions"] = item.get("substitutions", [])
                day["repair_log"] = item.get("repair_log", [])

            meal_plan.append(day)

        return {
            "success": len(meal_plan) > 0,
            "num_days": len(meal_plan),
            "requested_days": num_days,
            "meal_plan": meal_plan,
            "grocery_list": grocery,
            "message": message,
            "stats": {
                "phase1_safe": len(prelim_safe),
                "phase1_uncertain": len(prelim_uncertain),
                "phase1_unsafe": len(prelim_unsafe),
                "preplan_size": len(preplan),
                "verified_count": len(verified_items),
                "repaired_verified_count": len(repaired_items),
                "llm_calls_used": llm_calls_state["used"],
                "llm_call_budget": llm_call_budget,
                "candidate_limit": candidate_limit,
                "total_candidates": len(candidates),
            },
        }

    # -------------------------
    # Grocery list
    # -------------------------

    def generate_grocery_list(self, recipes: List[Recipe]) -> List[Dict]:
        counts = defaultdict(int)
        for r in recipes:
            for ing in (r.ingredients or []):
                counts[str(ing).lower().strip()] += 1

        items = []
        for ing, c in sorted(counts.items(), key=lambda x: -x[1]):
            items.append({"item": ing, "count": c, "category": self._categorize_ingredient(ing)})
        return items

    def _categorize_ingredient(self, ingredient: str) -> str:
        ing = str(ingredient).lower()
        if any(w in ing for w in ["onion", "garlic", "tomato", "pepper", "carrot", "celery", "broccoli", "lettuce"]):
            return "produce"
        if any(w in ing for w in ["chicken", "beef", "pork", "fish", "tofu", "bean", "lentil"]):
            return "protein"
        if any(w in ing for w in ["milk", "cheese", "butter", "cream", "yogurt", "ricotta", "parmesan"]):
            return "dairy"
        if any(w in ing for w in ["flour", "sugar", "salt", "oil", "spice", "herb", "rice", "pasta", "noodle"]):
            return "pantry"
        return "other"