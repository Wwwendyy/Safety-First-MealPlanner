# agents/reasoner_agent.py
"""
Reasoner Agent - deterministic hard-constraint reasoning (Safe/Unsafe/Uncertain).

This module is the "judge" of hard constraints. LLM (if used) only helps extract/canonicalize ingredients
and provides processing clues; final decisions here remain deterministic.

Key features:
  - Title guardrail (strong signals from title)
  - Manual avoid expansion
  - Vegan guard (high recall)
  - Ambiguity handling -> Uncertain
  - Risk lexicon fallback -> Unsafe
  - Allergen exceptions (e.g., refined peanut oil vs unrefined)
  - Allergen DB check
  - Dietary rules (halal/kosher/vegan) as deterministic checks

Trace output is structured for human readability.
"""

from typing import Dict, List, Optional, Tuple, Any
import re
import math

from data.allergen_db import AllergenDatabase
from rules.dietary_rules import DietaryRuleChecker
from data.preprocessing import IngredientPreprocessor

from agents.title_guard_agent import TitleGuardAgent
from agents.risk_lexicon_agent import RiskLexiconAgent

from agents.ingredient_normalizer_agent import IngredientNormalizerAgent
from agents.vegan_guard_agent import VeganGuardAgent
from agents.manual_avoid_agent import ManualAvoidAgent


class ReasonerAgent:
    AMBIGUOUS = {
        "nuts", "nut", "spices", "seasoning", "sauce", "broth", "stock",
        "gelatin", "flavoring", "mystery sauce", "secret sauce"
    }

    # Allergen exception rules (minimal v1)
    # You can extend this list later for other nuanced cases.
    ALLERGEN_EXCEPTIONS = [
        {
            "allergen_key": "peanut",
            "pattern": r"\bpeanut\s+oil\b",
            "allow_if_processing": "refined",
            "deny_if_processing": "unrefined",
            "default": "uncertain",  # if processing is unknown
            "note": "Peanut oil safety depends on refinement level."
        }
    ]

    def __init__(self, allergen_db: AllergenDatabase, preprocessor: Optional[IngredientPreprocessor] = None):
        self.allergen_db = allergen_db
        self.dietary_checker = DietaryRuleChecker()
        self.preprocessor = preprocessor
        self.title_guard = TitleGuardAgent()
        self.risk = RiskLexiconAgent()

        self.normalizer = IngredientNormalizerAgent()
        self.vegan_guard = VeganGuardAgent(enable_llm=True)
        self.manual_avoid_agent = ManualAvoidAgent()

    # -------------------------
    # Formatting helpers (trace)
    # -------------------------

    def _h(self, trace: List[str], title: str):
        trace.append("")
        trace.append(f"=== {title} ===")

    def _bullet(self, trace: List[str], msg: str):
        trace.append(f"- {msg}")

    def _ok(self, trace: List[str], msg: str):
        trace.append(f"  ✓ {msg}")

    def _warn(self, trace: List[str], msg: str):
        trace.append(f"  ⚠ {msg}")

    def _bad(self, trace: List[str], msg: str):
        trace.append(f"  ✗ {msg}")

    # -------------------------
    # Cleaning / parsing
    # -------------------------

    def clean_ingredient(self, ingredient: str) -> str:
        if ingredient is None:
            return ''
        if isinstance(ingredient, float) and math.isnan(ingredient):
            return ''
        s = str(ingredient).lower().strip()
        if s in {'nan', 'none', ''}:
            return ''
        s = re.sub(r'\([^)]*\)', ' ', s)
        s = re.sub(r'[\d¼½¾⅓⅔⅛⅜⅝⅞/.\-–—]+', ' ', s)
        s = re.sub(r'[^a-z\s]', ' ', s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    def _any_allergen_enabled(self, allergens: List[str], key: str) -> bool:
        k = (key or "").lower()
        for a in (allergens or []):
            if k in str(a).lower():
                return True
        return False

    def _apply_allergen_exceptions(
        self,
        allergens: List[str],
        raw_line: str,
        cleaned_line: str,
        processing: Optional[Dict[str, Any]]
    ) -> Tuple[str, Optional[str]]:
        """
        Returns (decision, message):
          decision in {"none","allow","deny","uncertain"}
        """
        raw_l = (raw_line or "").lower()
        cleaned_l = (cleaned_line or "").lower()
        proc_level = (processing or {}).get("level", "unknown")
        proc_level = str(proc_level or "unknown").lower()

        for rule in self.ALLERGEN_EXCEPTIONS:
            key = rule.get("allergen_key", "")
            if not self._any_allergen_enabled(allergens, key):
                continue

            pattern = rule.get("pattern", "")
            if pattern:
                if not (re.search(pattern, raw_l) or re.search(pattern, cleaned_l)):
                    continue
            else:
                continue

            allow_if = str(rule.get("allow_if_processing", "")).lower()
            deny_if = str(rule.get("deny_if_processing", "")).lower()
            default = str(rule.get("default", "uncertain")).lower()

            if proc_level == allow_if:
                return "allow", f"{key} oil allowed when processing='{proc_level}'"
            if proc_level == deny_if:
                return "deny", f"{key} oil NOT allowed when processing='{proc_level}'"

            # unknown or other -> uncertain (by default)
            if default == "allow":
                return "allow", f"{key} oil allowed by default (processing='{proc_level}')"
            if default == "deny":
                return "deny", f"{key} oil denied by default (processing='{proc_level}')"
            return "uncertain", f"{key} oil requires processing info (processing='{proc_level}')"

        return "none", None

    def _iter_ingredient_units(self, recipe) -> List[Dict[str, Any]]:
        """
        Prefer iterating over recipe.llm_extracted_lines (raw + canonical + processing).
        Fallback to recipe.ingredients if no extracted lines.
        Returns list of units:
          { raw: str, text: str, processing: dict|None }
        """
        extracted = getattr(recipe, "llm_extracted_lines", []) or []
        units: List[Dict[str, Any]] = []

        if extracted:
            for item in extracted:
                if not item.get("is_food", True):
                    continue
                raw = str(item.get("raw", "")).strip()
                canonical = item.get("canonical", []) or []
                text = " ".join([str(x).strip().lower() for x in canonical if str(x).strip()]).strip()
                if not text:
                    text = raw.lower().strip()
                units.append({
                    "raw": raw,
                    "text": text,
                    "processing": item.get("processing") or {"level": "unknown", "keywords": []},
                })
            return units

        for ing in (recipe.ingredients or []):
            units.append({"raw": str(ing), "text": str(ing), "processing": {"level": "unknown", "keywords": []}})
        return units

    # -------------------------
    # Main check
    # -------------------------

    def check_recipe(self, recipe, user_constraints: Dict) -> Dict:
        violations: List[dict] = []
        uncertain_ingredients: List[dict] = []
        trace: List[str] = []

        title = getattr(recipe, "title", "")

        # Use expanded allergies if provided; else fall back
        allergens = user_constraints.get("expanded_allergies")
        if allergens is None:
            allergens = user_constraints.get("allergens")
        if allergens is None:
            allergens = user_constraints.get("allergies", [])

        manual_avoid = user_constraints.get("manual_avoid", []) or []
        manual_avoid_clean = self.manual_avoid_agent.expand(manual_avoid)

        dietary_constraints = {
            "halal": bool(user_constraints.get("halal", False)),
            "kosher": bool(user_constraints.get("kosher", False)),
            "vegan": bool(user_constraints.get("vegan", False)),
        }

        # ---------
        # Overview
        # ---------
        self._h(trace, "Recipe Safety Check Overview")
        self._bullet(trace, f"Title: {title}")
        self._bullet(trace, f"Hard constraints: "
                           f"allergens={allergens or []}, manual_avoid={manual_avoid_clean or []}, "
                           f"dietary={ {k:v for k,v in dietary_constraints.items() if v} or {} }")

        # ---------
        # Step 0: Title guard
        # ---------
        self._h(trace, "Step 0 — Title Guard (strong signals)")
        t_guard = self.title_guard.check_title(
            title,
            dietary_constraints,
            manual_avoid_clean,
            allergens
        )

        if t_guard.get("trace"):
            for tline in t_guard["trace"]:
                self._bullet(trace, tline)

        if t_guard.get("violations"):
            violations.extend(t_guard["violations"])
            self._bad(trace, f"Title indicates forbidden content → {len(t_guard['violations'])} violation(s)")
        else:
            self._ok(trace, "No title-based violations detected")

        # ---------
        # Step 0.5: LLM extraction uncertainty (if present)
        # ---------
        llm_uncertain = getattr(recipe, "llm_uncertain_ingredients", []) or []
        self._h(trace, "Step 0.5 — LLM Extraction Confidence (if used)")
        if not llm_uncertain:
            self._ok(trace, "No low-confidence extraction lines reported")
        else:
            self._warn(trace, f"{len(llm_uncertain)} ingredient line(s) had low extraction confidence")
            for item in llm_uncertain:
                uncertain_ingredients.append({
                    "ingredient": item.get("raw", ""),
                    "cleaned": (item.get("canonical") or [""])[0] if item.get("canonical") else "",
                    "reason": f"LLM extraction low confidence ({float(item.get('confidence', 0.0)):.2f}): {item.get('notes','')}"
                })
                self._bullet(trace, f"Low-confidence line: raw='{item.get('raw','')}' "
                                   f"canonical={item.get('canonical',[])} "
                                   f"confidence={float(item.get('confidence', 0.0)):.2f}")

        # ---------
        # Ingredient loop
        # ---------
        self._h(trace, "Step 1 — Ingredient-by-Ingredient Checks")
        units = self._iter_ingredient_units(recipe)
        self._bullet(trace, f"Ingredients evaluated: {len(units)}")

        for idx, unit in enumerate(units, start=1):
            ingredient_raw = unit.get("raw", "")
            ingredient_text = unit.get("text", "")
            processing = unit.get("processing") or {"level": "unknown", "keywords": []}

            ingredient_clean = ""
            note = None
            if self.preprocessor:
                ingredient_clean, note = self.preprocessor.normalize_ingredient(ingredient_text)

            if (not ingredient_clean) or (str(ingredient_clean).lower().strip() in {"nan", "none"}):
                ingredient_clean = self.clean_ingredient(ingredient_text)

            if not ingredient_clean:
                continue

            proc_level = str((processing or {}).get("level", "unknown") or "unknown")
            proc_keywords = (processing or {}).get("keywords", []) or []

            trace.append("")
            trace.append(f"[Ingredient {idx}] raw='{ingredient_raw}'")
            self._bullet(trace, f"canonical='{ingredient_text}'")
            self._bullet(trace, f"cleaned='{ingredient_clean}'"
                                + (f" (preprocessor={note})" if note else ""))
            self._bullet(trace, f"processing='{proc_level}'"
                                + (f", keywords={proc_keywords}" if proc_keywords else ""))

            # 1) Vegan guard (only if vegan enabled)
            if dietary_constraints.get("vegan"):
                vg_violations, vg_uncertainties, vg_trace = self.vegan_guard.check_ingredients(
                    [ingredient_clean],
                    raw_lines=[ingredient_raw]
                )
                for tline in (vg_trace or []):
                    self._bullet(trace, f"[vegan_guard] {tline}")

                if vg_violations:
                    for v in vg_violations:
                        violations.append({
                            "constraint": "dietary",
                            "ingredient": ingredient_raw,
                            "cleaned": ingredient_clean,
                            "violation": "vegan",
                            "explanation": v.get("evidence", "Non-vegan ingredient")
                        })
                    self._bad(trace, f"Vegan violation: {vg_violations[0].get('evidence','Non-vegan')}")
                    continue

                if vg_uncertainties:
                    uncertain_ingredients.append({
                        "ingredient": ingredient_raw,
                        "cleaned": ingredient_clean,
                        "reason": vg_uncertainties[0].get("reason", "Ambiguous for vegan")
                    })
                    self._warn(trace, f"Vegan uncertainty: {vg_uncertainties[0].get('reason','Ambiguous')}")
                    continue

                self._ok(trace, "Vegan check passed")

            # 2) Manual avoid
            manual_hit = None
            for banned in (manual_avoid_clean or []):
                if banned and (banned == ingredient_clean or banned in ingredient_clean):
                    manual_hit = banned
                    break

            if manual_hit:
                violations.append({
                    "constraint": "manual_avoid",
                    "ingredient": ingredient_raw,
                    "cleaned": ingredient_clean,
                    "banned": manual_hit,
                    "evidence": f"Manual avoid match: '{manual_hit}'"
                })
                self._bad(trace, f"Manual avoid violation: matched '{manual_hit}'")
                continue
            else:
                if manual_avoid_clean:
                    self._ok(trace, "No manual-avoid match")

            # 3) Ambiguity handling
            if ingredient_clean in self.AMBIGUOUS or any(amb in ingredient_clean for amb in self.AMBIGUOUS):
                uncertain_ingredients.append({
                    "ingredient": ingredient_raw,
                    "cleaned": ingredient_clean,
                    "reason": "Ambiguous ingredient - cannot verify safety"
                })
                self._warn(trace, f"Ambiguous ingredient → uncertain: '{ingredient_clean}'")
                continue
            else:
                self._ok(trace, "Not ambiguous")

            # 4) Risk lexicon (high precision violations)
            risk_hit = self.risk.check(ingredient_clean, dietary_constraints, allergens, manual_avoid_clean)
            if risk_hit:
                violations.append({
                    "constraint": risk_hit["constraint"],
                    "ingredient": ingredient_raw,
                    "cleaned": ingredient_clean,
                    "evidence": risk_hit["evidence"],
                    "confidence": 0.95
                })
                self._bad(trace, f"Risk lexicon violation ({risk_hit['constraint']}): {risk_hit['evidence']}")
                continue
            else:
                self._ok(trace, "No risk-lexicon violation")

            # 5) Allergen exceptions & Allergen DB
            if allergens:
                exc_decision, exc_msg = self._apply_allergen_exceptions(
                    allergens=allergens,
                    raw_line=ingredient_raw,
                    cleaned_line=ingredient_clean,
                    processing=processing
                )

                if exc_decision == "allow":
                    self._ok(trace, f"Allergen exception applied: {exc_msg} (skip allergen DB)")
                elif exc_decision == "deny":
                    violations.append({
                        "constraint": "allergy",
                        "ingredient": ingredient_raw,
                        "cleaned": ingredient_clean,
                        "allergen": "peanut",
                        "evidence": exc_msg or "Allergen exception deny",
                        "confidence": 0.95
                    })
                    self._bad(trace, f"Allergen exception violation: {exc_msg}")
                    continue
                elif exc_decision == "uncertain":
                    uncertain_ingredients.append({
                        "ingredient": ingredient_raw,
                        "cleaned": ingredient_clean,
                        "reason": exc_msg or "Allergen exception requires manual verification"
                    })
                    self._warn(trace, f"Allergen exception uncertain: {exc_msg}")
                    continue
                else:
                    is_safe, allergen_triggered, evidence, confidence = self.allergen_db.check_ingredient(
                        ingredient_clean, allergens
                    )
                    if not is_safe:
                        violations.append({
                            "constraint": "allergy",
                            "ingredient": ingredient_raw,
                            "cleaned": ingredient_clean,
                            "allergen": allergen_triggered,
                            "evidence": evidence,
                            "confidence": confidence
                        })
                        self._bad(trace, f"Allergen violation: {evidence} (confidence={confidence})")
                        continue
                    self._ok(trace, f"Allergen check passed: {evidence}")

            # 6) Dietary rules (halal/kosher/vegan)
            if any(dietary_constraints.values()):
                is_compliant, dietary_violations, dietary_uncertainties, explanation = \
                    self.dietary_checker.check_dietary_constraints(ingredient_clean, dietary_constraints)

                if dietary_violations:
                    for v in dietary_violations:
                        violations.append({
                            "constraint": "dietary",
                            "ingredient": ingredient_raw,
                            "cleaned": ingredient_clean,
                            "violation": v,
                            "explanation": explanation
                        })
                    self._bad(trace, f"Dietary violation: {explanation}")
                    continue

                if dietary_uncertainties:
                    uncertain_ingredients.append({
                        "ingredient": ingredient_raw,
                        "cleaned": ingredient_clean,
                        "reason": "; ".join(dietary_uncertainties)
                    })
                    self._warn(trace, f"Dietary uncertainty: {explanation}")
                    continue

                self._ok(trace, f"Dietary check passed: {explanation}")

            # If we reached here, ingredient passed all enabled checks
            self._ok(trace, "Ingredient passed all enabled checks")

        # ---------
        # Final summary
        # ---------
        self._h(trace, "Final Decision Summary")

        if violations:
            label = "unsafe"
            explanation = f"Recipe contains {len(violations)} violation(s)"
            self._bad(trace, explanation)
            self._bullet(trace, "Top violation(s):")
            for v in violations[:5]:
                self._bullet(trace, f"{v.get('constraint')} | ingredient='{v.get('cleaned') or v.get('ingredient')}' | {v.get('evidence') or v.get('explanation')}")
            if len(violations) > 5:
                self._bullet(trace, f"...and {len(violations) - 5} more")
        elif uncertain_ingredients:
            label = "uncertain"
            explanation = f"Recipe contains {len(uncertain_ingredients)} uncertain ingredient(s) - manual verification required"
            self._warn(trace, explanation)
            self._bullet(trace, "Uncertain item(s):")
            for u in uncertain_ingredients[:6]:
                self._bullet(trace, f"ingredient='{u.get('cleaned') or u.get('ingredient')}' | reason={u.get('reason')}")
            if len(uncertain_ingredients) > 6:
                self._bullet(trace, f"...and {len(uncertain_ingredients) - 6} more")
        else:
            label = "safe"
            explanation = "Recipe satisfies all constraints"
            self._ok(trace, explanation)

        return {
            "label": label,
            "violations": violations,
            "uncertain_ingredients": uncertain_ingredients,
            "explanation": explanation,
            "trace": trace
        }