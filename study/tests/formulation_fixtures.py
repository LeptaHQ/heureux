from contextlib import ExitStack

from study.ee_formulations import FormulationCatalog, FormulationCategory, FormulationEntry
from unittest.mock import patch


THEMES = (
    "education", "sante-alimentation", "environnement", "travail", "numerique",
    "societe", "transports", "logement", "culture-loisirs", "consommation", "voyages",
)


def formulation_catalog(source_key="test-reference"):
    categories = (
        FormulationCategory("affirmation", "function", "Affirmation", "Prendre position.", "book-open"),
        FormulationCategory("synthese", "function", "Synthèse", "Présenter les documents.", "book-open"),
        *(FormulationCategory(slug, "theme", slug.title(), "Bénéfices et limites.", "book-open")
          for slug in THEMES),
    )
    entries = tuple(
        FormulationEntry(
            slug=f"cadre-{i}", category="affirmation" if i < 2 else theme,
            label=f"Prévention et équilibre {i}",
            french=f"Pour ma part, [mesure {i}] améliore [bénéfice].",
            english="In my view, [measure] improves [benefit].",
            usage="Présenter un bénéfice avec une limite.",
            grammar="Le sujet détermine l’accord du verbe.",
            example="Pour ma part, cette mesure améliore la santé.",
            example_english="In my view, this measure improves health.",
            source_key=source_key,
            transfer_prompt="Adaptez cette construction au travail.",
            essential=i < 2, themes=(theme,),
        ) for i, theme in enumerate(THEMES)
    )
    return FormulationCatalog(categories, entries, 1)


def mock_catalog(catalog):
    stack = ExitStack()
    for module in (
        "study.ee_formulations", "study.formulation_progress", "study.views.formulations",
        "study.views.library", "study.views.helpers",
    ):
        stack.enter_context(patch(f"{module}.get_ee_formulations", return_value=catalog))
    return stack
