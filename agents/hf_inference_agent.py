import os
import json
import re
from typing import Any, Dict, Optional

from openai import AzureOpenAI


def _extract_json(text: str) -> Dict[str, Any]:
    if not text:
        return {"allergies": [], "manual_avoid": [], "soft_constraints": {}}

    t = text.strip()
    t = re.sub(r"^```json\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^```\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t)

    try:
        return json.loads(t)
    except Exception:
        pass

    m = re.search(r"\{.*\}", t, flags=re.DOTALL)
    if not m:
        return {"allergies": [], "manual_avoid": [], "soft_constraints": {}}

    try:
        return json.loads(m.group(0))
    except Exception:
        return {"allergies": [], "manual_avoid": [], "soft_constraints": {}}


def _azure_client_from_env() -> AzureOpenAI:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION")

    missing = [k for k, v in {
        "AZURE_OPENAI_ENDPOINT": endpoint,
        "AZURE_OPENAI_API_KEY": api_key,
        "AZURE_OPENAI_API_VERSION": api_version,
    }.items() if not v]

    if missing:
        raise RuntimeError(
            "Missing Azure OpenAI env vars: "
            + ", ".join(missing)
            + ". Make sure your .env is loaded."
        )

    return AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_version,
    )


class HFInferenceProfileParser:
    """(Legacy name) Profile parser using Azure OpenAI Chat Completions.

    Keeps the old class name so the rest of the project doesn't need to change imports.
    Env vars:
      - AZURE_OPENAI_ENDPOINT  (e.g., https://<resource>.cognitiveservices.azure.com/)
      - AZURE_OPENAI_API_KEY
      - AZURE_OPENAI_API_VERSION (e.g., 2024-12-01-preview)
      - AZURE_OPENAI_DEPLOYMENT (deployment name, e.g., gpt-4o)
    """

    def __init__(self, model: Optional[str] = None):
        self.client = _azure_client_from_env()
        self.deployment = model or os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        if not self.deployment:
            raise RuntimeError("AZURE_OPENAI_DEPLOYMENT is not set.")

    def parse(self, user_text: str) -> Dict[str, Any]:
        instructions = (
            "Return ONLY a valid JSON object with EXACT keys:\n"
            "  allergies: list of strings (e.g., 'Peanut Allergy', 'Nut Allergy', 'Dairy Allergy')\n"
            "  manual_avoid: list of ingredient strings\n"
            "  soft_constraints: object with boolean keys easy_to_cook, low_fat, avoid_spicy\n"
            "No extra keys. No explanations. If unsure, empty lists/objects.\n"
        )

        resp = self.client.chat.completions.create(
            model=self.deployment,
            messages=[
                {"role": "system", "content": "You output ONLY valid JSON. No markdown. No explanation."},
                {"role": "user", "content": f"{instructions}\nUser text: {user_text}\nJSON:"},
            ],
            temperature=0.0,
            max_tokens=256,
        )

        out = (resp.choices[0].message.content or "").strip()
        data = _extract_json(out)

        allergies = data.get("allergies") if isinstance(data.get("allergies"), list) else []
        manual_avoid = data.get("manual_avoid") if isinstance(data.get("manual_avoid"), list) else []
        soft = data.get("soft_constraints") if isinstance(data.get("soft_constraints"), dict) else {}

        soft_constraints = {
            "easy_to_cook": bool(soft.get("easy_to_cook", False)),
            "low_fat": bool(soft.get("low_fat", False)),
            "avoid_spicy": bool(soft.get("avoid_spicy", False)),
        }

        return {
            "allergies": [str(a).strip() for a in allergies if str(a).strip()],
            "manual_avoid": [str(x).strip() for x in manual_avoid if str(x).strip()],
            "soft_constraints": soft_constraints,
        }
