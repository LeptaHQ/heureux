"""Compact language references used alongside the EE3 formulation lessons."""

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class FormulationLanguageItem:
    french: str
    english: str
    pattern: str


def _item(french, english, pattern):
    return FormulationLanguageItem(french, english, pattern)


REPORTING_LANGUAGE = (
    _item("aborder", "to discuss / address", "aborder un thème"),
    _item("mettre en avant", "to highlight", "mettre en avant un avantage"),
    _item("souligner", "to emphasize", "souligner un constat / souligner que…"),
    _item("indiquer", "to indicate / state", "indiquer un chiffre / indiquer que…"),
    _item("rappeler", "to point out / remind", "rappeler un fait / rappeler que…"),
    _item("ajouter", "to add", "ajouter une idée / ajouter que…"),
    _item("estimer que", "to consider that", "estimer que + indicatif"),
    _item("défendre", "to support / advocate", "défendre une position"),
    _item("privilégier", "to favour", "privilégier une solution"),
    _item(
        "mettre en garde contre",
        "to warn against",
        "mettre en garde contre un risque",
    ),
)


THEME_LANGUAGE = MappingProxyType({
    "education": (
        _item(
            "la mixité sociale",
            "social diversity",
            "favoriser la mixité sociale",
        ),
        _item(
            "les classes socialement homogènes",
            "socially homogeneous classes",
            "éviter des classes socialement homogènes",
        ),
        _item(
            "l’égalité des chances",
            "equal opportunities",
            "renforcer l’égalité des chances",
        ),
        _item(
            "le décrochage scolaire",
            "dropping out of school",
            "prévenir le décrochage scolaire",
        ),
        _item(
            "la réussite scolaire",
            "academic success",
            "favoriser la réussite scolaire",
        ),
        _item(
            "les inégalités scolaires",
            "educational inequalities",
            "réduire les inégalités scolaires",
        ),
        _item(
            "un climat scolaire apaisé",
            "a positive school climate",
            "créer un climat scolaire apaisé",
        ),
        _item(
            "l’inclusion des élèves",
            "student inclusion",
            "favoriser l’inclusion des élèves",
        ),
    ),
    "sante-alimentation": (
        _item(
            "une alimentation équilibrée",
            "a balanced diet",
            "adopter une alimentation équilibrée",
        ),
        _item(
            "l’accès aux soins",
            "access to healthcare",
            "améliorer l’accès aux soins",
        ),
        _item(
            "le dépistage précoce",
            "early screening",
            "encourager le dépistage précoce",
        ),
        _item(
            "les comportements à risque",
            "risky behaviours",
            "prévenir les comportements à risque",
        ),
        _item(
            "les effets indésirables",
            "side effects",
            "signaler des effets indésirables",
        ),
        _item(
            "un mode de vie sédentaire",
            "a sedentary lifestyle",
            "lutter contre un mode de vie sédentaire",
        ),
        _item(
            "la santé mentale",
            "mental health",
            "préserver la santé mentale",
        ),
        _item(
            "une campagne de sensibilisation",
            "an awareness campaign",
            "mener une campagne de sensibilisation",
        ),
    ),
    "environnement": (
        _item(
            "la transition écologique",
            "the green transition",
            "accélérer la transition écologique",
        ),
        _item(
            "les émissions de gaz à effet de serre",
            "greenhouse-gas emissions",
            "réduire les émissions de gaz à effet de serre",
        ),
        _item(
            "l’empreinte carbone",
            "carbon footprint",
            "limiter son empreinte carbone",
        ),
        _item(
            "les énergies renouvelables",
            "renewable energy",
            "développer les énergies renouvelables",
        ),
        _item(
            "la biodiversité",
            "biodiversity",
            "préserver la biodiversité",
        ),
        _item(
            "la consommation responsable",
            "responsible consumption",
            "encourager la consommation responsable",
        ),
        _item(
            "le gaspillage",
            "waste",
            "lutter contre le gaspillage",
        ),
        _item(
            "les ressources naturelles",
            "natural resources",
            "préserver les ressources naturelles",
        ),
    ),
    "travail": (
        _item(
            "l’équilibre entre vie professionnelle et vie personnelle",
            "work-life balance",
            "préserver l’équilibre entre vie professionnelle et vie personnelle",
        ),
        _item(
            "les conditions de travail",
            "working conditions",
            "améliorer les conditions de travail",
        ),
        _item(
            "l’épuisement professionnel",
            "burnout",
            "prévenir l’épuisement professionnel",
        ),
        _item(
            "la sécurité de l’emploi",
            "job security",
            "renforcer la sécurité de l’emploi",
        ),
        _item(
            "l’évolution de carrière",
            "career development",
            "favoriser l’évolution de carrière",
        ),
        _item(
            "les compétences transférables",
            "transferable skills",
            "développer des compétences transférables",
        ),
        _item(
            "la fidélisation des salariés",
            "employee retention",
            "améliorer la fidélisation des salariés",
        ),
        _item(
            "la qualité de vie au travail",
            "quality of life at work",
            "améliorer la qualité de vie au travail",
        ),
    ),
    "numerique": (
        _item(
            "la fracture numérique",
            "the digital divide",
            "réduire la fracture numérique",
        ),
        _item(
            "la protection des données personnelles",
            "personal-data protection",
            "renforcer la protection des données personnelles",
        ),
        _item(
            "la désinformation",
            "misinformation",
            "lutter contre la désinformation",
        ),
        _item(
            "le temps d’écran",
            "screen time",
            "limiter le temps d’écran",
        ),
        _item(
            "l’esprit critique",
            "critical thinking",
            "développer l’esprit critique",
        ),
        _item(
            "le cyberharcèlement",
            "cyberbullying",
            "prévenir le cyberharcèlement",
        ),
        _item(
            "les compétences numériques",
            "digital skills",
            "acquérir des compétences numériques",
        ),
        _item(
            "un usage responsable des technologies",
            "responsible use of technology",
            "promouvoir un usage responsable des technologies",
        ),
    ),
    "societe": (
        _item(
            "la cohésion sociale",
            "social cohesion",
            "renforcer la cohésion sociale",
        ),
        _item(
            "le lien social",
            "social connections",
            "maintenir le lien social",
        ),
        _item(
            "l’isolement social",
            "social isolation",
            "rompre l’isolement social",
        ),
        _item(
            "la solidarité intergénérationnelle",
            "intergenerational solidarity",
            "encourager la solidarité intergénérationnelle",
        ),
        _item(
            "la diversité culturelle",
            "cultural diversity",
            "valoriser la diversité culturelle",
        ),
        _item(
            "les discriminations",
            "discrimination",
            "lutter contre les discriminations",
        ),
        _item(
            "la participation citoyenne",
            "civic participation",
            "favoriser la participation citoyenne",
        ),
        _item(
            "le sentiment d’appartenance",
            "sense of belonging",
            "renforcer le sentiment d’appartenance",
        ),
    ),
    "transports": (
        _item(
            "les transports en commun",
            "public transport",
            "développer les transports en commun",
        ),
        _item(
            "la mobilité douce",
            "active and low-impact transport",
            "encourager la mobilité douce",
        ),
        _item(
            "des pistes cyclables sécurisées",
            "safe cycle lanes",
            "aménager des pistes cyclables sécurisées",
        ),
        _item(
            "la congestion routière",
            "traffic congestion",
            "réduire la congestion routière",
        ),
        _item(
            "la desserte des zones rurales",
            "transport links in rural areas",
            "améliorer la desserte des zones rurales",
        ),
        _item(
            "le coût des déplacements",
            "travel costs",
            "réduire le coût des déplacements",
        ),
        _item(
            "le covoiturage",
            "carpooling",
            "favoriser le covoiturage",
        ),
        _item(
            "un réseau fiable",
            "a reliable network",
            "garantir un réseau fiable",
        ),
    ),
    "logement": (
        _item(
            "un logement abordable",
            "affordable housing",
            "proposer des logements abordables",
        ),
        _item(
            "la pénurie de logements",
            "housing shortage",
            "lutter contre la pénurie de logements",
        ),
        _item(
            "la précarité énergétique",
            "energy poverty",
            "réduire la précarité énergétique",
        ),
        _item(
            "le cadre de vie",
            "living environment",
            "améliorer le cadre de vie",
        ),
        _item(
            "la densification urbaine",
            "urban densification",
            "encadrer la densification urbaine",
        ),
        _item(
            "l’accès à la propriété",
            "access to home ownership",
            "faciliter l’accès à la propriété",
        ),
        _item(
            "la rénovation énergétique",
            "energy-efficient renovation",
            "financer la rénovation énergétique",
        ),
        _item(
            "la mixité sociale",
            "social diversity",
            "préserver la mixité sociale",
        ),
    ),
    "culture-loisirs": (
        _item(
            "l’accès à la culture",
            "access to culture",
            "élargir l’accès à la culture",
        ),
        _item(
            "le patrimoine culturel",
            "cultural heritage",
            "préserver le patrimoine culturel",
        ),
        _item(
            "les pratiques culturelles",
            "cultural practices",
            "diversifier les pratiques culturelles",
        ),
        _item(
            "la création artistique",
            "artistic creation",
            "soutenir la création artistique",
        ),
        _item(
            "l’offre culturelle",
            "cultural provision",
            "enrichir l’offre culturelle",
        ),
        _item(
            "la démocratisation de la culture",
            "wider access to culture",
            "favoriser la démocratisation de la culture",
        ),
        _item(
            "des loisirs accessibles",
            "accessible leisure activities",
            "proposer des loisirs accessibles",
        ),
        _item(
            "l’expression artistique",
            "artistic expression",
            "encourager l’expression artistique",
        ),
    ),
    "consommation": (
        _item(
            "le pouvoir d’achat",
            "purchasing power",
            "préserver le pouvoir d’achat",
        ),
        _item(
            "les achats impulsifs",
            "impulse purchases",
            "limiter les achats impulsifs",
        ),
        _item(
            "la surconsommation",
            "overconsumption",
            "lutter contre la surconsommation",
        ),
        _item(
            "les produits d’occasion",
            "second-hand goods",
            "acheter des produits d’occasion",
        ),
        _item(
            "les circuits courts",
            "short supply chains",
            "favoriser les circuits courts",
        ),
        _item(
            "le rapport qualité-prix",
            "value for money",
            "évaluer le rapport qualité-prix",
        ),
        _item(
            "l’endettement des ménages",
            "household debt",
            "prévenir l’endettement des ménages",
        ),
        _item(
            "la consommation responsable",
            "responsible consumption",
            "adopter une consommation responsable",
        ),
    ),
    "voyages": (
        _item(
            "le tourisme de masse",
            "mass tourism",
            "limiter les effets du tourisme de masse",
        ),
        _item(
            "le tourisme durable",
            "sustainable tourism",
            "développer le tourisme durable",
        ),
        _item(
            "les retombées économiques",
            "economic benefits",
            "générer des retombées économiques",
        ),
        _item(
            "la population locale",
            "the local population",
            "respecter la population locale",
        ),
        _item(
            "la haute saison",
            "peak season",
            "voyager en dehors de la haute saison",
        ),
        _item(
            "hors des sentiers battus",
            "off the beaten track",
            "sortir des sentiers battus",
        ),
        _item(
            "le patrimoine local",
            "local heritage",
            "valoriser le patrimoine local",
        ),
        _item(
            "l’empreinte environnementale",
            "environmental footprint",
            "réduire l’empreinte environnementale",
        ),
    ),
})


def formulation_language_for(category):
    if category is None:
        return ()
    if category.slug == "synthese":
        return REPORTING_LANGUAGE
    if category.kind == "theme":
        return THEME_LANGUAGE.get(category.slug, ())
    return ()
