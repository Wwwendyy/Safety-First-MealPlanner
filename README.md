# Safety-First MealPlanner

A safety-first weekly meal planning system that helps users generate meal plans under strict dietary constraints such as allergies, veganism, halal, and kosher requirements.

Unlike typical recipe recommenders or LLM-only assistants, this project treats dietary rules as **hard constraints**, performs **ingredient-level safety checks**, applies **automatic correction when possible**, and returns **transparent reasoning traces** for each decision.

---

## Demo Video


https://github.com/user-attachments/assets/6b450dcd-42f9-4b80-a892-03b949a3833d


---

## Poster

https://github.com/user-attachments/files/26037784/team3-final-final.pdf

---

## Overview

Planning meals sounds simple until safety becomes critical.

For users with food allergies or strict dietary needs, choosing a recipe can be risky. Many recipe websites and even AI assistants cannot guarantee food safety: they may miss hidden allergens, misunderstand dietary rules, or suggest unsafe substitutions. For these users, a small mistake can have serious consequences.

Safety-First MealPlanner explores a different design direction. Instead of treating user constraints as soft preferences, it treats them as **non-negotiable hard rules**. The system validates recipes at the ingredient level, attempts safe corrections when possible, and rejects recipes that cannot be made safe. The result is a meal planning workflow centered on **trust, transparency, and safety**.

---

## Problem Statement

Most existing meal planning tools are optimized for convenience, not safety.

Common failure points include:

- recipe titles that hide unsafe ingredients
- vague ingredient descriptions
- unsafe substitutions
- confusion between allergy, intolerance, and preference
- probabilistic LLM outputs that may hallucinate or overlook critical details

This creates a major gap for users who need meal recommendations they can actually rely on.

---

## Solution

Safety-First MealPlanner is a weekly meal planning system that:

- enforces dietary constraints as **hard constraints**
- validates recipes through **ingredient-level checking**
- automatically **replaces unsafe ingredients** with safer alternatives when possible
- **rejects recipes** that cannot be made safe
- provides a **deterministic reasoning trace** explaining each decision

The goal is not only to generate meal plans, but to make the decision process **auditable and trustworthy**.

---

## Key Features

- **Hard-constraint meal planning**  
  Supports strict dietary requirements rather than treating them as optional preferences.

- **Ingredient-level validation**  
  Checks each ingredient individually instead of relying only on recipe names or summaries.

- **Automatic correction logic**  
  Repairs recipes by substituting problematic ingredients with safer alternatives when feasible.

- **Safe rejection behavior**  
  Rejects recipes when safety cannot be guaranteed.

- **Transparent reasoning trace**  
  Returns interpretable, step-by-step explanations for acceptance, correction, or rejection.

- **Weekly planning workflow**  
  Designed for multi-day meal planning rather than isolated single-recipe checking.

---

## Supported Constraints

This project is designed to support dietary constraints such as:

- food allergies
- vegan
- halal
- kosher
- manual ingredient avoid lists

Depending on your implementation, the system can also be extended to support:

- lactose intolerance
- vegetarian
- pescatarian
- gluten-free
- nutrition- or budget-aware planning

---

## Why This Matters

Large language models are powerful, but they generate outputs probabilistically. That makes them useful for brainstorming, but risky for safety-critical recommendation tasks.

In food planning, a system that sounds fluent is not enough. It must also be correct, consistent, and explainable.

This project demonstrates how combining structured checks with AI-assisted planning can move meal planning toward:

- safer recommendations
- more transparent decision-making
- more trustworthy human-AI interaction

This makes the project relevant to broader themes in:

- trustworthy AI
- explainable AI
- human-centered AI
- health and accessibility
- constraint-based planning systems

---

## System Workflow

The system follows a safety-first pipeline:

1. **Collect user constraints**  
   Gather dietary requirements such as allergies, vegan/halal/kosher rules, and manual avoid lists.

2. **Retrieve or generate candidate recipes**  
   Produce possible meals for the planning horizon.

3. **Normalize and inspect ingredients**  
   Clean ingredient text and map ingredients into a structured representation.

4. **Run ingredient-level safety checks**  
   Validate each ingredient against the user's hard constraints.

5. **Attempt correction if needed**  
   Replace unsafe ingredients with safer alternatives while preserving the recipe as much as possible.

6. **Reject if correction is impossible**  
   If safety cannot be guaranteed, the recipe is rejected rather than returned.

7. **Assemble the weekly plan**  
   Verified recipes are selected into a multi-day meal plan.

8. **Return reasoning traces**  
   Each decision is accompanied by an interpretable explanation.

---

## Example System Output

The system may classify recipes into outcomes such as:

- **SAFE** — recipe satisfies all constraints
- **CORRECTED** — recipe originally contained an unsafe ingredient but was repaired safely
- **REJECTED** — recipe could not be made safe under the given constraints

Reasoning traces may include checks such as:

- title-based guard checks
- ingredient normalization
- allergen matching
- dietary rule validation
- substitution attempts
- final verification status

---

## Tech Stack

This project may include components such as:

- **Python**
- **Flask** for backend APIs and orchestration
- **LLM-assisted reasoning** for planning and explanation support
- **Rule-based safety validation**
- **Structured ingredient normalization**
- **Frontend interface** for user input and result display

You can edit this section to match your exact implementation.

---

## Repository Structure

.
├── backend/              # backend logic, APIs, planning pipeline, safety checks
├── frontend/             # frontend UI (if applicable)
├── data/                 # ingredient mappings, rules, resources, sample inputs
├── assets/               # poster, screenshots, demo preview images
├── docs/                 # additional documentation
├── notebooks/            # experiments or prototype notebooks (if applicable)
└── README.md

---

## Project Highlights

* Built a **safety-first meal planning pipeline** for users with strict dietary constraints
* Treated allergies and dietary restrictions as **hard constraints**, not soft preferences
* Designed **ingredient-level rule checking** rather than relying only on recipe titles
* Added **automatic correction logic** to safely substitute ingredients when possible
* Returned **deterministic reasoning traces** to improve trust and interpretability
* Framed meal planning as a **trustworthy AI and human-centered systems problem**

---

## Research and Design Focus

This project was motivated by a central question:

**How can AI meal planning systems become genuinely trustworthy for users with strict dietary needs?**

Rather than optimizing only for convenience or fluency, this system prioritizes:

* safety
* consistency
* explainability
* user trust

This shift is important because food recommendation is not just a personalization task. In many cases, it is a **safety-critical decision-making task**.

---

## Team

* **Wenjun**
* **Srija**
* **Natasha**

---

## Acknowledgments

This project was developed as part of an academic team project.

We thank our instructors, mentors, and classmates for their guidance and feedback throughout the design, implementation, and presentation process.

---

## Future Work

Possible next steps include:

* expanding ingredient and allergen knowledge coverage
* handling more nuanced exception cases
* integrating trusted external food safety databases
* improving substitution quality
* supporting nutrition, budget, and time-aware planning
* building a stronger interactive user interface
* evaluating the system with broader real-world dietary scenarios

---

## License

MIT License
