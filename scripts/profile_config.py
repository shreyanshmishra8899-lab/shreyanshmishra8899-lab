"""Single source of truth for the profile's non-secret, user-facing data.

Every generator script (`make_ascii_svg.py`, `make_info_card.py`,
`fetch_contributions.py`, `render_heatmap_svg.py`) imports this module
instead of hardcoding names, roles, or tech-stack strings, so the whole
profile can be re-pointed at a different GitHub account/person by setting
environment variables (see `.env.example`) -- no need to invent or guess
any detail that isn't supplied here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value else default


@dataclass(frozen=True)
class TechCategory:
    label: str
    items: tuple[str, ...]


@dataclass(frozen=True)
class ProfileConfig:
    github_username: str
    display_name: str
    role: str
    experience: str
    tech_categories: tuple[TechCategory, ...]
    highlights: tuple[str, ...] = field(default_factory=tuple)


def load_profile_config() -> ProfileConfig:
    return ProfileConfig(
        github_username=_env(
            "PROFILE_GITHUB_USERNAME", "shreyanshmishra8899-lab"
        ),
        display_name=_env("PROFILE_DISPLAY_NAME", "Shreyansh"),
        role=_env("PROFILE_ROLE", "Not employed yet - open to work"),
        experience=_env("PROFILE_EXPERIENCE", "Internships at 2 companies"),
        tech_categories=(
            TechCategory("Languages", ("Python", "C++", "SQL")),
            TechCategory(
                "AI/ML",
                (
                    "Machine Learning",
                    "Deep Learning",
                    "Computer Vision",
                    "NLP",
                    "Transfer Learning",
                    "Model Fine-Tuning",
                    "Model Evaluation",
                    "Transformer Architectures",
                ),
            ),
            TechCategory(
                "LLM & Agentic AI",
                (
                    "LLMs",
                    "Generative AI",
                    "Agentic AI",
                    "Multi-Agent Systems",
                    "RAG",
                    "Hybrid Retrieval (BM25, Dense, RRF, MMR)",
                    "Prompt Engineering",
                    "LLM Evaluation",
                ),
            ),
            TechCategory(
                "Frameworks",
                (
                    "PyTorch",
                    "TensorFlow",
                    "Scikit-learn",
                    "HF Transformers",
                    "LangChain",
                    "LangGraph",
                    "OpenCV",
                    "NetworkX",
                ),
            ),
            TechCategory(
                "Data & Serving",
                (
                    "FastAPI",
                    "REST APIs",
                    "ChromaDB",
                    "pgvector",
                    "Ollama",
                    "Gemini API",
                    "Local LLM Deployment",
                    "Git",
                    "Linux",
                    "OOP",
                ),
            ),
        ),
        # No verified project names/metrics were provided -- leave empty
        # rather than invent them. Fill in real project titles here once
        # available; `make_info_card.py` renders this section only if
        # it is non-empty.
        highlights=(),
    )
