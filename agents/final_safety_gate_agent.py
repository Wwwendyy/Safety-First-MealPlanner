
from __future__ import annotations
from typing import Dict
from agents.reasoner_agent import ReasonerAgent
from agents.recipe_agent import Recipe

class FinalSafetyGateAgent:
    """
    Final gate: only allow label == 'safe'.
    Uncertain is not allowed at the end; it should have been repaired or candidate swapped.
    """
    def __init__(self, reasoner: ReasonerAgent):
        self.reasoner = reasoner

    def verify(self, recipe: Recipe, constraints: Dict) -> Dict:
        check = self.reasoner.check_recipe(recipe, constraints)
        check["passed_gate"] = (check.get("label") == "safe")
        return check
