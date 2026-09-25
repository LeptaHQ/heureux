"""Curated language references used alongside the EE3 formulation lessons."""

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class FormulationLanguageExample:
    text: str
    provenance: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class FormulationLanguageItem:
    french: str
    english: str
    examples: tuple[FormulationLanguageExample, ...]
    role: str = ""
    usage: str = ""

    @property
    def pattern(self):
        """Keep the existing Emploi renderer useful without a UI change."""
        return self.usage or " ".join(example.text for example in self.examples)

    @property
    def provenance(self):
        return tuple(dict.fromkeys(
            pair
            for example in self.examples
            for pair in example.provenance
        ))


@dataclass(frozen=True)
class _RoleLanguageRow:
    role: str
    row: tuple


def _example(text, *provenance):
    return FormulationLanguageExample(text, tuple(provenance))


def _role(role, row):
    return _RoleLanguageRow(role, row)


def _item(french, english, pattern, *provenance):
    return FormulationLanguageItem(
        french,
        english,
        (_example(pattern, *provenance),),
        "reporting",
    )


def _source(month, combinaison, field):
    return (f"ee-tache3:{month}:combinaison-{combinaison}", field)


THEME_LANGUAGE_ROLES = (
    *("notion",) * 4,
    *("collocation",) * 4,
    *("benefit",) * 4,
    *("risk",) * 4,
    *("condition",) * 4,
    *("solution",) * 2,
    *("mechanism",) * 2,
)


def _bank(*rows):
    items = []
    implicit_index = 0
    role_order = tuple(dict.fromkeys(THEME_LANGUAGE_ROLES))
    role_rank = {role: rank for rank, role in enumerate(role_order)}
    previous_rank = -1
    for source_row in rows:
        if isinstance(source_row, _RoleLanguageRow):
            role = source_row.role
            row = source_row.row
        else:
            if implicit_index >= len(THEME_LANGUAGE_ROLES):
                raise ValueError("Additional language rows need an explicit role")
            role = THEME_LANGUAGE_ROLES[implicit_index]
            row = source_row
            implicit_index += 1
        if role not in role_rank:
            raise ValueError(f"Unknown EE3 language role {role!r}")
        if role_rank[role] < previous_rank:
            raise ValueError("EE3 language role groups must remain ordered")
        previous_rank = role_rank[role]
        items.append(_language_item(role, row))
    if set(item.role for item in items) != set(role_order):
        raise ValueError("Every EE3 theme bank needs all language role groups")
    return tuple(items)


def _language_item(role, row):
    french, english, first_example, *remainder = row
    if isinstance(first_example, FormulationLanguageExample):
        examples = (first_example, *remainder)
        if not all(
            isinstance(example, FormulationLanguageExample)
            for example in examples
        ):
            raise TypeError(f"{french!r} mixes structured and scalar examples")
    else:
        examples = (_example(first_example, *remainder),)
    return FormulationLanguageItem(french, english, tuple(examples), role)


REPORTING_LANGUAGE = (
    _item(
        "aborder",
        "to discuss / address",
        "Les deux documents abordent l’installation de distributeurs automatiques dans les lycées.",
        _source("janvier", "1", "position"),
    ),
    _item(
        "mettre en avant",
        "to highlight",
        "Le premier met en avant la prévention de certaines maladies, la réduction de la pollution et le respect des animaux.",
        _source("avril", "16", "position"),
    ),
    _item(
        "souligner",
        "to emphasize",
        "Le premier souligne son accès large à l’information, à la culture et aux enjeux sociaux.",
        _source("janvier", "7", "position"),
    ),
    _item(
        "indiquer",
        "to indicate / state",
        "Le premier soutient cette mesure pour des raisons de santé et de coût, et indique qu’elle plaît globalement aux familles.",
        _source("janvier", "18", "position"),
    ),
    _item(
        "rappeler",
        "to point out / remind",
        "De son côté, le second rappelle qu’une bonne connexion, un équipement adapté et une grande autonomie sont nécessaires, sans quoi l’apprenant risque de se décourager et d’abandonner.",
        _source("janvier", "9", "position"),
    ),
    _item(
        "ajouter",
        "to add",
        "De son côté, le second ajoute une baisse de l’absentéisme et une meilleure fidélisation des salariés, tout en exigeant une organisation efficace de l’entreprise.",
        _source("avril", "10", "position"),
    ),
    _item(
        "estimer que",
        "to consider that",
        "Le premier estime qu’elle réduit le stress, améliore l’ambiance entre collègues et renforce la motivation.",
        _source("decembre", "3", "position"),
    ),
    _item(
        "défendre",
        "to support / advocate",
        "Le premier défend le don ponctuel d’argent ou de temps, surtout en hiver, comme un geste accessible à tous.",
        _source("janvier", "16", "position"),
    ),
    _item(
        "privilégier",
        "to favour",
        "De son côté, le second privilégie l’engagement associatif quotidien, qui aide les bénéficiaires à trouver un logement, un emploi et leur autonomie.",
        _source("janvier", "4", "position"),
    ),
    _item(
        "mettre en garde contre",
        "to warn against",
        "En revanche, le second met en garde contre les tensions liées aux personnalités, au partage des tâches et au manque d’intimité, et recommande des règles claires.",
        _source("janvier", "3", "position"),
    ),
)


THEME_LANGUAGE = MappingProxyType({
    "education": _bank(
        # Notions
        (
            "la mixité sociale",
            "social diversity",
            _example(
                "La mixité sociale développe l’ouverture d’esprit et prépare les élèves à vivre ensemble.",
                _source("mars", "5", "position_claire"),
            ),
            _example(
                "Des frais élevés limitent la mixité sociale et excluent les familles défavorisées.",
                _source("mars", "5", "position"),
            ),
        ),
        (
            "les devoirs à la maison",
            "homework",
            "Les devoirs à la maison restent utiles lorsqu’ils sont courts et adaptés.",
            _source("mars", "6", "reformulation"),
            _source("juillet", "9", "reformulation"),
        ),
        (
            "les technologies à l’école",
            "technology at school",
            "Les technologies à l’école doivent compléter les livres et les échanges directs.",
            _source("mars", "7", "reformulation"),
        ),
        (
            "l’uniforme scolaire",
            "school uniform",
            _example(
                "L’uniforme scolaire peut créer une identité commune sans effacer la personnalité.",
                _source("avril", "12", "reformulation"),
            ),
            _example(
                "L’uniforme scolaire doit aussi rester confortable et adapté aux saisons.",
                _source("decembre", "10", "reformulation"),
            ),
        ),
        # Productive collocations
        (
            "garantir les mêmes apprentissages fondamentaux",
            "to guarantee the same core learning",
            "Une école bien financée doit garantir les mêmes apprentissages fondamentaux à chaque élève.",
            _source("mars", "5", "position_claire"),
        ),
        (
            "développer l’autonomie",
            "to develop independence",
            "Une révision courte peut développer l’autonomie sans épuiser les élèves.",
            _source("mars", "6", "position"),
            _source("juillet", "9", "position"),
        ),
        (
            "adapter les exercices au niveau de l’élève",
            "to tailor exercises to the pupil’s level",
            "Le numérique permet d’adapter les exercices au niveau de l’élève.",
            _source("mars", "7", "position_claire"),
        ),
        (
            "renforcer le sentiment d’appartenance",
            "to strengthen a sense of belonging",
            "Une tenue commune peut renforcer le sentiment d’appartenance à l’école.",
            _source("avril", "12", "position"),
        ),
        _role("collocation", (
            "préserver le lien humain",
            "to preserve human connection",
            _example(
                "Un travail collectif avec un professeur permet de préserver le lien humain entre les élèves.",
                _source("mars", "7", "position_claire"),
            ),
            _example(
                "Limiter la dépendance aux écrans aide à préserver le lien humain nécessaire au développement.",
                _source("mars", "7", "position"),
            ),
        )),
        # Benefits
        (
            "financer du matériel scolaire",
            "to fund school equipment",
            _example(
                "Les recettes des distributeurs peuvent financer du matériel scolaire utile à tous.",
                _source("janvier", "1", "position"),
                _source("janvier", "1", "position_claire"),
            ),
            _example(
                "Un lycée peut financer du matériel scolaire en consacrant une partie des recettes à sa bibliothèque.",
                _source("novembre", "3", "position_claire"),
            ),
        ),
        (
            "consolider les apprentissages",
            "to reinforce learning",
            "Dix minutes de révision régulière peuvent consolider les apprentissages.",
            _source("mars", "6", "position_claire"),
            _source("juillet", "9", "position_claire"),
        ),
        (
            "développer l’ouverture d’esprit",
            "to develop open-mindedness",
            "La mixité sociale peut développer l’ouverture d’esprit des élèves.",
            _source("mars", "5", "position_claire"),
        ),
        (
            "simplifier les choix du matin",
            "to simplify morning choices",
            "Une tenue commune peut simplifier les choix du matin pour les familles.",
            _source("avril", "12", "position_claire"),
            _source("decembre", "10", "position_claire"),
        ),
        _role("benefit", (
            "réduire la comparaison des marques",
            "to reduce comparison of brands",
            "Une tenue commune peut réduire la comparaison des marques et rendre les écarts de moyens moins visibles.",
            _source("avril", "12", "position_claire"),
            _source("decembre", "10", "position_claire"),
        )),
        # Risks and limits
        (
            "reproduire les inégalités",
            "to perpetuate inequalities",
            "Des frais élevés risquent de reproduire les inégalités entre les familles.",
            _source("mars", "5", "position"),
        ),
        (
            "les classes socialement homogènes",
            "socially homogeneous classes",
            "Les classes socialement homogènes limitent les rencontres entre élèves de milieux différents.",
            _source("mars", "5", "position"),
        ),
        (
            "la dépendance aux écrans",
            "screen dependency",
            "La dépendance aux écrans peut réduire les interactions humaines nécessaires aux élèves.",
            _source("mars", "7", "position"),
        ),
        (
            "limiter l’expression personnelle",
            "to limit self-expression",
            "Une règle trop rigide peut limiter l’expression personnelle des adolescents.",
            _source("avril", "12", "position"),
            _source("decembre", "10", "position"),
        ),
        # Conditions
        (
            "des devoirs réalisables sans aide parentale",
            "homework pupils can do without parental help",
            "L’enseignant doit proposer des devoirs réalisables sans aide parentale.",
            _source("mars", "6", "position_claire"),
            _source("juillet", "9", "position_claire"),
        ),
        (
            "un usage limité et guidé",
            "limited and guided use",
            "Un usage limité et guidé du numérique protège le lien humain.",
            _source("mars", "7", "position_claire"),
        ),
        (
            "un uniforme abordable et adapté aux saisons",
            "an affordable uniform suited to the seasons",
            "Un uniforme abordable et adapté aux saisons respecte les besoins des élèves.",
            _source("decembre", "10", "position_claire"),
        ),
        (
            "un contenu strictement contrôlé",
            "strictly controlled contents",
            _example(
                "Un contenu strictement contrôlé rend les distributeurs compatibles avec la santé des jeunes.",
                _source("janvier", "1", "position_claire"),
            ),
            _example(
                "Un contenu strictement contrôlé peut se limiter à l’eau, au lait et aux boissons sans sucre ajouté.",
                _source("novembre", "3", "position_claire"),
            ),
        ),
        # Solutions
        (
            "limiter les effectifs et renforcer le tutorat",
            "to limit class sizes and strengthen tutoring",
            "Un collège peut limiter les effectifs et renforcer le tutorat pour mieux accompagner chacun.",
            _source("mars", "5", "position_claire"),
        ),
        (
            "alterner outils numériques, livres et échanges directs",
            "to alternate digital tools, books and direct discussion",
            "Une classe peut alterner outils numériques, livres et échanges directs selon l’objectif.",
            _source("mars", "7", "position_claire"),
        ),
        # Reusable mechanisms
        (
            "rendre les écarts de moyens moins visibles",
            "to make differences in means less visible",
            "Une tenue commune peut rendre les écarts de moyens moins visibles dans la cour.",
            _source("avril", "12", "position_claire"),
            _source("decembre", "10", "position_claire"),
        ),
        (
            "retenir ce qui a été appris en classe",
            "to retain what was learned in class",
            "Une révision régulière aide à retenir ce qui a été appris en classe.",
            _source("mars", "6", "position_claire"),
            _source("juillet", "9", "position_claire"),
        ),
    ),
    "sante-alimentation": _bank(
        # Notions
        (
            "le savoir-faire en cuisine",
            "culinary expertise",
            "Le savoir-faire en cuisine exige de la technique autant que de la passion.",
            _source("janvier", "2", "reformulation"),
        ),
        (
            "les repas équilibrés",
            "balanced meals",
            "Les repas équilibrés permettent de contrôler le sel, le gras et le sucre.",
            _source("janvier", "12", "position_claire"),
        ),
        (
            "les protéines",
            "protein sources",
            "Les protéines peuvent provenir de la viande, des céréales ou des légumineuses.",
            _source("janvier", "18", "reformulation"),
        ),
        (
            "la restauration rapide",
            "fast food",
            _example(
                "La restauration rapide doit rester un choix occasionnel plutôt qu’une habitude.",
                _source("avril", "13", "reformulation"),
            ),
            _example(
                "La restauration rapide est pratique, mais elle peut coûter cher à la santé.",
                _source("aout", "8", "reformulation"),
            ),
            _example(
                "La restauration rapide laisse une liberté de choix qui exige une vraie responsabilité.",
                _source("aout", "15", "reformulation"),
            ),
        ),
        # Productive collocations
        (
            "maîtriser l’hygiène et les techniques",
            "to master hygiene and techniques",
            "Un cuisinier professionnel doit maîtriser l’hygiène et les techniques de son métier.",
            _source("janvier", "2", "position_claire"),
        ),
        (
            "composer des repas équilibrés",
            "to put together balanced meals",
            _example(
                "Cuisiner chez soi aide à composer des repas équilibrés avec des produits frais.",
                _source("janvier", "12", "position_claire"),
            ),
            _example(
                "Des connaissances nutritionnelles permettent de composer des repas équilibrés sans viande.",
                _source("avril", "16", "position"),
            ),
        ),
        (
            "réduire la consommation de viande",
            "to reduce meat consumption",
            _example(
                "On peut réduire la consommation de viande pour limiter l’empreinte écologique.",
                _source("avril", "15", "position_claire"),
            ),
            _example(
                "Il vaut mieux réduire la consommation de viande progressivement que la supprimer sans préparation.",
                _source("mai", "6", "position_claire"),
            ),
        ),
        (
            "assurer des soins continus",
            "to provide continuous care",
            "Un personnel qualifié peut assurer des soins continus aux personnes âgées.",
            _source("octobre", "4", "position_claire"),
        ),
        # Benefits
        (
            "contrôler la qualité de l’assiette",
            "to control the quality of one’s food",
            "Préparer ses repas permet de contrôler la qualité de l’assiette au quotidien.",
            _source("janvier", "12", "position"),
        ),
        (
            "maîtriser le budget alimentaire",
            "to keep the food budget under control",
            "Préparer des produits frais permet de maîtriser le budget alimentaire d’un ménage.",
            _source("janvier", "12", "position_claire"),
        ),
        (
            "réduire l’impact environnemental",
            "to reduce environmental impact",
            _example(
                "Manger moins de viande peut réduire l’impact environnemental lié à l’eau, aux terres et aux émissions.",
                _source("avril", "15", "position_claire"),
            ),
            _example(
                "Les fruits, les légumes et les légumineuses peuvent réduire l’impact environnemental d’un régime.",
                _source("avril", "16", "position_claire"),
            ),
            _example(
                "Des produits locaux et saisonniers peuvent réduire l’impact environnemental des transports inutiles.",
                _source("mai", "5", "position_claire"),
            ),
        ),
        (
            "rompre l’isolement des aînés",
            "to break older people’s isolation",
            "Des activités collectives peuvent rompre l’isolement des aînés sans remplacer leur famille.",
            _source("aout", "1", "position"),
            _source("aout", "1", "position_claire"),
            _source("octobre", "4", "position"),
        ),
        # Risks and limits
        (
            "le risque de prise de poids",
            "the risk of weight gain",
            "Des menus trop riches augmentent le risque de prise de poids.",
            _source("avril", "13", "position_claire"),
            _source("aout", "15", "position"),
        ),
        (
            "l’élevage intensif",
            "intensive livestock farming",
            "L’élevage intensif mobilise beaucoup d’eau et de terres et produit des émissions.",
            _source("avril", "15", "position"),
            _source("avril", "16", "position_claire"),
            _source("mai", "5", "position_claire"),
        ),
        (
            "les risques de carences",
            "the risk of nutrient deficiencies",
            _example(
                "Les risques de carences diminuent lorsque les repas végétariens sont bien planifiés.",
                _source("avril", "16", "position"),
            ),
            _example(
                "Associer céréales et légumineuses limite les risques de carences redoutés lors d’une réduction de la viande.",
                _source("mai", "6", "position"),
                _source("mai", "6", "position_claire"),
            ),
        ),
        (
            "l’éloignement de la famille",
            "distance from one’s family",
            "L’éloignement de la famille peut fragiliser une personne âgée.",
            _source("aout", "1", "position"),
            _source("octobre", "4", "position"),
        ),
        # Conditions
        (
            "un apport suffisant en protéines",
            "an adequate protein intake",
            "Une diététicienne peut vérifier qu’un menu fournit un apport suffisant en protéines.",
            _source("janvier", "18", "position_claire"),
        ),
        (
            "une alimentation bien planifiée",
            "a well-planned diet",
            _example(
                "Une alimentation bien planifiée permet de choisir le végétarisme sans déséquilibre.",
                _source("avril", "16", "position_claire"),
            ),
            _example(
                "Une alimentation bien planifiée associe différentes sources de protéines pendant une transition progressive.",
                _source("mai", "6", "position_claire"),
            ),
        ),
        (
            "des choix équilibrés variés et abordables",
            "balanced, varied and affordable choices",
            _example(
                "Des menus transparents doivent offrir des choix équilibrés variés et abordables avec moins d’emballages.",
                _source("aout", "8", "position_claire"),
            ),
            _example(
                "Des choix équilibrés variés et abordables doivent être aussi visibles que les plats gras.",
                _source("aout", "15", "position_claire"),
            ),
        ),
        (
            "le libre choix de la personne âgée",
            "the older person’s free choice",
            "Le libre choix de la personne âgée doit guider toute entrée en résidence.",
            _source("aout", "1", "position_claire"),
        ),
        _role("condition", (
            "des informations nutritionnelles claires",
            "clear nutritional information",
            _example(
                "Des informations nutritionnelles claires sur les calories, le sel et le sucre aident à composer un repas équilibré.",
                _source("aout", "8", "position_claire"),
            ),
            _example(
                "Des informations nutritionnelles claires permettent au client pressé de choisir une formule plus saine.",
                _source("aout", "15", "position"),
                _source("aout", "15", "position_claire"),
            ),
        )),
        # Solutions
        (
            "indiquer clairement les calories, le sel et le sucre",
            "to clearly state calories, salt and sugar",
            "Un restaurant devrait indiquer clairement les calories, le sel et le sucre.",
            _source("aout", "8", "position_claire"),
        ),
        (
            "offrir un choix entre accompagnement à domicile et accueil spécialisé",
            "to offer a choice between home support and specialist care",
            "La collectivité doit offrir un choix entre accompagnement à domicile et accueil spécialisé.",
            _source("octobre", "4", "position_claire"),
        ),
        _role("solution", (
            "soutenir les producteurs locaux",
            "to support local producers",
            _example(
                "La transition des cantines doit soutenir les producteurs locaux qui risquent de perdre un débouché.",
                _source("janvier", "18", "position"),
            ),
            _example(
                "Conserver un menu carné local chaque semaine permet de soutenir les producteurs locaux.",
                _source("janvier", "18", "position_claire"),
            ),
        )),
        # Reusable mechanisms
        (
            "remplacer la viande par des légumineuses",
            "to replace meat with pulses",
            _example(
                "Une famille peut remplacer la viande par des légumineuses plusieurs jours par semaine.",
                _source("avril", "15", "position_claire"),
            ),
            _example(
                "On peut remplacer la viande par des légumineuses locales plutôt que par des légumes importés par avion.",
                _source("mai", "5", "position_claire"),
            ),
            _example(
                "Un nutritionniste peut expliquer comment remplacer la viande par des légumineuses sans déséquilibrer les repas.",
                _source("mai", "6", "position_claire"),
            ),
        ),
        (
            "repérer tôt un problème de santé",
            "to identify a health problem early",
            "Une surveillance quotidienne permet de repérer tôt un problème de santé.",
            _source("octobre", "4", "position_claire"),
        ),
    ),
    "environnement": _bank(
        # Notions
        (
            "les usages essentiels du plastique",
            "essential uses of plastic",
            "Les usages essentiels du plastique doivent être distingués des emballages évitables.",
            _source("janvier", "6", "reformulation"),
        ),
        (
            "la pollution des océans",
            "ocean pollution",
            "La pollution des océans menace durablement les animaux et la santé publique.",
            _source("janvier", "10", "position"),
        ),
        (
            "la protection de la nature",
            "nature conservation",
            "La protection de la nature peut parfois justifier une régulation strictement contrôlée.",
            _source("avril", "4", "position"),
        ),
        (
            "la croissance urbaine",
            "urban growth",
            "La croissance urbaine devient durable lorsqu’elle évite de détruire de nouveaux terrains.",
            _source("decembre", "16", "reformulation"),
        ),
        # Productive collocations
        (
            "éliminer les objets à usage unique",
            "to eliminate single-use items",
            "Les commerces peuvent éliminer les objets à usage unique lorsqu’une alternative existe.",
            _source("janvier", "6", "position_claire"),
        ),
        (
            "préserver les usages médicaux essentiels",
            "to preserve essential medical uses",
            _example(
                "La réduction du plastique doit préserver les usages médicaux essentiels.",
                _source("janvier", "10", "position_claire"),
            ),
            _example(
                "Une clinique peut préserver les usages médicaux essentiels en réservant le plastique aux emballages stériles.",
                _source("janvier", "6", "position_claire"),
            ),
        ),
        (
            "protéger un écosystème",
            "to protect an ecosystem",
            "Des agents formés peuvent réguler une espèce envahissante pour protéger un écosystème.",
            _source("avril", "4", "position_claire"),
        ),
        (
            "préserver des espèces menacées",
            "to preserve endangered species",
            _example(
                "Des soins et des programmes de reproduction peuvent préserver des espèces menacées.",
                _source("mai", "2", "position"),
            ),
            _example(
                "Un parc peut préserver des espèces menacées puis relâcher de jeunes animaux dans une réserve.",
                _source("mai", "2", "position_claire"),
            ),
        ),
        _role("collocation", (
            "le plastique à usage unique",
            "single-use plastic",
            _example(
                "Le plastique à usage unique doit être éliminé lorsqu’une solution durable existe.",
                _source("janvier", "6", "position_claire"),
            ),
            _example(
                "Le plastique à usage unique reste justifié pour une seringue stérile, mais pas pour un emballage évitable.",
                _source("janvier", "10", "position_claire"),
            ),
        )),
        # Benefits
        (
            "prévenir les infections",
            "to prevent infections",
            _example(
                "Le matériel médical stérile permet de prévenir les infections chez les patients.",
                _source("janvier", "6", "position_claire"),
            ),
            _example(
                "Des seringues, des cathéters et des pansements en plastique peuvent prévenir les infections.",
                _source("janvier", "10", "position"),
            ),
        ),
        (
            "réduire le stress des animaux",
            "to reduce animal stress",
            "Des espaces vastes et adaptés peuvent réduire le stress des animaux captifs.",
            _source("mai", "2", "position_claire"),
        ),
        (
            "limiter les longs déplacements",
            "to limit long journeys",
            "Une ville compacte peut limiter les longs déplacements de ses habitants.",
            _source("decembre", "16", "position_claire"),
        ),
        (
            "partager efficacement les infrastructures",
            "to share infrastructure efficiently",
            "Un quartier dense permet de partager efficacement les infrastructures urbaines.",
            _source("decembre", "16", "position_claire"),
        ),
        # Risks and limits
        (
            "menacer la faune marine",
            "to threaten marine wildlife",
            "Les déchets abandonnés peuvent menacer la faune marine.",
            _source("janvier", "10", "position"),
        ),
        (
            "remonter dans la chaîne alimentaire",
            "to move up the food chain",
            "Des fragments de plastique peuvent remonter dans la chaîne alimentaire.",
            _source("janvier", "10", "position"),
        ),
        (
            "banaliser la souffrance animale",
            "to normalise animal suffering",
            "La chasse pratiquée uniquement pour le plaisir risque de banaliser la souffrance animale.",
            _source("avril", "4", "position_claire"),
        ),
        (
            "détruire les forêts voisines",
            "to destroy nearby forests",
            "L’étalement urbain peut détruire les forêts voisines et leurs réserves de carbone.",
            _source("decembre", "16", "position_claire"),
        ),
        # Conditions
        (
            "une garantie équivalente",
            "an equivalent guarantee",
            "Un matériau médical ne peut remplacer le plastique que s’il offre une garantie équivalente.",
            _source("janvier", "6", "position_claire"),
        ),
        (
            "des quotas établis par des biologistes",
            "quotas set by biologists",
            "Toute régulation doit respecter des quotas établis par des biologistes.",
            _source("avril", "4", "position_claire"),
        ),
        (
            "la priorité au bien-être et à la conservation",
            "priority for welfare and conservation",
            "Un zoo acceptable donne la priorité au bien-être et à la conservation.",
            _source("mai", "2", "position_claire"),
        ),
        (
            "une densité accompagnée de transports en commun",
            "density supported by public transport",
            "Une densité accompagnée de transports en commun réduit les besoins énergétiques.",
            _source("decembre", "16", "position_claire"),
        ),
        # Solutions
        (
            "proposer la vente en vrac et des contenants réutilisables",
            "to offer bulk sales and reusable containers",
            _example(
                "Un supermarché peut proposer la vente en vrac et des contenants réutilisables.",
                _source("janvier", "6", "position_claire"),
            ),
            _example(
                "Un commerce peut proposer la vente en vrac et des contenants réutilisables pour protéger les océans.",
                _source("janvier", "10", "position_claire"),
            ),
        ),
        (
            "construire sur des terrains déjà urbanisés",
            "to build on already developed land",
            "Une municipalité peut construire sur des terrains déjà urbanisés près du métro.",
            _source("decembre", "16", "position_claire"),
        ),
        _role("solution", (
            "la responsabilité des producteurs",
            "producer responsibility",
            "La responsabilité des producteurs doit accompagner la réduction et le réemploi du plastique.",
            _source("janvier", "6", "position_claire"),
        )),
        # Reusable mechanisms
        (
            "réserver le plastique aux besoins indispensables",
            "to reserve plastic for essential needs",
            "Il faut réserver le plastique aux besoins indispensables et remplacer les usages évitables.",
            _source("janvier", "10", "position_claire"),
        ),
        (
            "relâcher les jeunes animaux dans une réserve protégée",
            "to release young animals into a protected reserve",
            "Un programme de conservation peut relâcher les jeunes animaux dans une réserve protégée.",
            _source("mai", "2", "position_claire"),
        ),
    ),
    "travail": _bank(
        # Notions
        (
            "l’épanouissement professionnel",
            "professional fulfilment",
            "L’épanouissement professionnel dépend du sens donné au travail et de ses conditions.",
            _source("avril", "5", "reformulation"),
        ),
        (
            "l’égalité professionnelle",
            "workplace equality",
            "L’égalité professionnelle exige que les compétences passent avant le sexe.",
            _source("avril", "7", "reformulation"),
        ),
        (
            "la réduction du temps de travail",
            "a reduction in working time",
            "La réduction du temps de travail doit s’accompagner d’une nouvelle organisation.",
            _source("avril", "10", "reformulation"),
        ),
        (
            "le bien-être au travail",
            "workplace well-being",
            "Le bien-être au travail dépend de l’organisation autant que du mobilier.",
            _source("juillet", "6", "reformulation"),
        ),
        # Productive collocations
        (
            "garantir un revenu décent",
            "to guarantee a decent income",
            _example(
                "Pour être favorable, le travail doit garantir un revenu décent et s’exercer dans des conditions équilibrées.",
                _source("avril", "5", "position_claire"),
            ),
            _example(
                "Un emploi stable doit garantir un revenu décent tout en procurant des relations et un sentiment d’utilité.",
                _source("mai", "3", "position_claire"),
            ),
        ),
        (
            "préserver l’équilibre entre vie professionnelle et vie personnelle",
            "to preserve work-life balance",
            _example(
                "Des horaires moins rigides permettent de préserver l’équilibre entre vie professionnelle et vie personnelle.",
                _source("avril", "5", "position"),
            ),
            _example(
                "Le travail ne doit pas envahir la vie familiale afin de préserver l’équilibre entre vie professionnelle et vie personnelle.",
                _source("mai", "3", "position_claire"),
            ),
        ),
        (
            "garantir une rémunération égale",
            "to guarantee equal pay",
            "Les employeurs doivent garantir une rémunération égale à compétences égales.",
            _source("avril", "7", "position_claire"),
        ),
        (
            "respecter le temps de travail",
            "to respect working hours",
            "Un poste confortable ne dispense jamais de respecter le temps de travail.",
            _source("juillet", "6", "position"),
            _source("juillet", "6", "position_claire"),
        ),
        # Benefits
        (
            "développer la ponctualité et le travail en équipe",
            "to develop punctuality and teamwork",
            "Un emploi saisonnier peut développer la ponctualité et le travail en équipe.",
            _source("avril", "6", "position_claire"),
        ),
        (
            "réduire l’absentéisme",
            "to reduce absenteeism",
            _example(
                "Une semaine plus courte peut réduire l’absentéisme et fidéliser les salariés.",
                _source("avril", "10", "position"),
            ),
            _example(
                "Des salariés reposés commettent moins d’erreurs, ce qui peut réduire l’absentéisme.",
                _source("avril", "10", "position_claire"),
            ),
        ),
        (
            "faciliter l’entraide",
            "to facilitate mutual support",
            "La confiance entre collègues peut faciliter l’entraide face à un problème.",
            _source("juillet", "44", "position_claire"),
        ),
        (
            "réduire la fatigue et améliorer la concentration",
            "to reduce fatigue and improve concentration",
            _example(
                "Quelques minutes de sieste peuvent réduire la fatigue et améliorer la concentration de l’après-midi.",
                _source("aout", "19", "position_claire"),
            ),
            _example(
                "Vingt minutes de repos peuvent réduire la fatigue et améliorer la concentration sans perturber la journée.",
                _source("novembre", "4", "position_claire"),
            ),
        ),
        # Risks and limits
        (
            "le stress et l’épuisement",
            "stress and exhaustion",
            "Des horaires rigides peuvent provoquer le stress et l’épuisement.",
            _source("avril", "5", "position"),
        ),
        (
            "intensifier chaque journée",
            "to intensify each working day",
            "Réduire les heures sans revoir la charge risque d’intensifier chaque journée.",
            _source("avril", "10", "position_claire"),
        ),
        (
            "les discriminations à l’embauche",
            "hiring discrimination",
            _example(
                "Une photo sur le CV peut favoriser les discriminations à l’embauche liées à l’apparence.",
                _source("juin", "1", "position"),
            ),
            _example(
                "Une première sélection anonyme peut limiter les discriminations à l’embauche.",
                _source("juin", "1", "position_claire"),
            ),
        ),
        (
            "les allergies et les distractions",
            "allergies and distractions",
            "La présence d’animaux peut provoquer les allergies et les distractions au bureau.",
            _source("decembre", "3", "position"),
        ),
        # Conditions
        (
            "une véritable période de repos",
            "a proper period of rest",
            "Un étudiant qui travaille l’été doit garder une véritable période de repos.",
            _source("avril", "6", "position_claire"),
        ),
        (
            "des objectifs et des effectifs adaptés",
            "suitable targets and staffing levels",
            "Une semaine plus courte exige des objectifs et des effectifs adaptés.",
            _source("avril", "10", "position_claire"),
        ),
        (
            "des décisions justes",
            "fair decisions",
            "L’amitié entre collègues reste positive si les responsables prennent des décisions justes.",
            _source("juillet", "44", "position_claire"),
        ),
        (
            "une pause courte et volontaire",
            "a short, voluntary break",
            _example(
                "Une pause courte et volontaire de quinze minutes peut rester compatible avec l’organisation de l’entreprise.",
                _source("aout", "19", "position_claire"),
            ),
            _example(
                "Une pause courte et volontaire peut être proposée sur réservation dans une salle calme.",
                _source("novembre", "4", "position_claire"),
            ),
        ),
        _role("condition", (
            "maintenir la qualité du service",
            "to maintain service quality",
            "L’entreprise doit réorganiser le travail pour maintenir la qualité du service sans transférer la pression aux salariés.",
            _source("avril", "10", "position_claire"),
        )),
        # Solutions
        (
            "évaluer chaque candidature selon les mêmes critères",
            "to assess each application using the same criteria",
            "Une entreprise doit évaluer chaque candidature selon les mêmes critères.",
            _source("juin", "1", "position_claire"),
        ),
        (
            "associer cours exigeants et expériences professionnelles",
            "to combine demanding study with professional experience",
            "Une formation utile doit associer cours exigeants et expériences professionnelles.",
            _source("aout", "18", "position_claire"),
        ),
        _role("solution", (
            "discuter de la charge de travail",
            "to discuss workload",
            "Une entreprise peut discuter de la charge de travail avec ses équipes avant de fixer des objectifs réalistes.",
            _source("avril", "5", "position_claire"),
        )),
        # Reusable mechanisms
        (
            "mettre ses connaissances à l’épreuve sur le terrain",
            "to put one’s knowledge to the test in the workplace",
            "Un stage permet de mettre ses connaissances à l’épreuve sur le terrain.",
            _source("aout", "18", "position_claire"),
        ),
        (
            "protéger les personnes allergiques ou craintives",
            "to protect people with allergies or fears",
            "Des espaces séparés peuvent protéger les personnes allergiques ou craintives.",
            _source("decembre", "3", "position_claire"),
        ),
    ),
    "numerique": _bank(
        # Notions
        (
            "le rôle éducatif de la télévision",
            "the educational role of television",
            "Le rôle éducatif de la télévision dépend du contenu et de l’accompagnement.",
            _source("janvier", "7", "reformulation"),
        ),
        (
            "l’apprentissage des langues en ligne",
            "online language learning",
            "L’apprentissage des langues en ligne offre de la flexibilité aux personnes autonomes.",
            _source("janvier", "9", "reformulation"),
        ),
        (
            "la vidéosurveillance urbaine",
            "urban video surveillance",
            "La vidéosurveillance urbaine peut aider une enquête sans remplacer la prévention.",
            _source("avril", "1", "reformulation"),
        ),
        (
            "les objets connectés",
            "connected devices",
            "Les objets connectés sont utiles, mais ils restent vulnérables aux intrusions.",
            _source("aout", "13", "reformulation"),
        ),
        # Productive collocations
        (
            "limiter le temps d’écran",
            "to limit screen time",
            _example(
                "Les familles doivent limiter le temps d’écran pour préserver la lecture, le sport et les interactions.",
                _source("janvier", "7", "position"),
            ),
            _example(
                "Les parents peuvent limiter le temps d’écran tout en accompagnant un programme bien choisi.",
                _source("decembre", "14", "position_claire"),
            ),
        ),
        (
            "entretenir la motivation",
            "to sustain motivation",
            "Un suivi humain régulier peut entretenir la motivation de l’apprenant.",
            _source("janvier", "9", "position_claire"),
        ),
        (
            "prévenir les conflits par le dialogue",
            "to prevent conflict through dialogue",
            "Une école doit prévenir les conflits par le dialogue avant de compter sur les caméras.",
            _source("avril", "8", "position"),
            _source("avril", "8", "position_claire"),
        ),
        (
            "limiter la collecte des données",
            "to limit data collection",
            _example(
                "Une norme stricte doit limiter la collecte des données au nécessaire.",
                _source("aout", "13", "position_claire"),
            ),
            _example(
                "Une montre médicale doit limiter la collecte des données avant de transmettre une information au médecin.",
                _source("aout", "13", "position_claire"),
            ),
        ),
        _role("collocation", (
            "protéger le sommeil",
            "to protect sleep",
            _example(
                "Limiter une pratique excessive permet de protéger le sommeil, l’activité physique et la concentration.",
                _source("avril", "11", "position_claire"),
            ),
            _example(
                "Des horaires de jeu clairs aident à protéger le sommeil sans interdire les jeux vidéo.",
                _source("mai", "1", "position_claire"),
                _source("juillet", "5", "position_claire"),
            ),
        )),
        _role("collocation", (
            "protéger la vie privée",
            "to protect privacy",
            "Des normes prévues dès la conception doivent protéger la vie privée des utilisateurs d’objets connectés.",
            _source("aout", "13", "position_claire"),
        )),
        # Benefits
        (
            "développer l’esprit critique",
            "to develop critical thinking",
            "Un documentaire bien choisi peut développer l’esprit critique d’un enfant.",
            _source("janvier", "7", "position_claire"),
        ),
        (
            "apprendre sans perdre de temps en trajets",
            "to learn without losing time travelling",
            "Un cours à distance permet d’apprendre sans perdre de temps en trajets.",
            _source("janvier", "9", "position_claire"),
        ),
        (
            "développer la réflexion et la coordination",
            "to develop thinking and coordination",
            "Certains jeux peuvent développer la réflexion et la coordination.",
            _source("avril", "11", "position_claire"),
            _source("mai", "1", "position_claire"),
        ),
        (
            "favoriser l’autonomie des personnes âgées",
            "to promote older people’s independence",
            "Une alarme connectée peut favoriser l’autonomie des personnes âgées.",
            _source("aout", "13", "position_claire"),
        ),
        # Risks and limits
        (
            "remplacer la lecture et le lien humain",
            "to replace reading and human connection",
            "Un écran ne doit jamais remplacer la lecture et le lien humain.",
            _source("janvier", "7", "position_claire"),
            _source("decembre", "14", "position"),
        ),
        (
            "se décourager et abandonner",
            "to become discouraged and give up",
            "Sans accompagnement, un apprenant risque de se décourager et abandonner.",
            _source("janvier", "9", "position"),
        ),
        (
            "une surveillance permanente",
            "constant surveillance",
            "Des caméras installées partout créeraient une surveillance permanente.",
            _source("avril", "8", "position_claire"),
        ),
        (
            "remplacer le sommeil, les études ou le sport",
            "to replace sleep, study or sport",
            _example(
                "Une dépendance apparaît lorsque le jeu vient remplacer le sommeil, les études ou le sport.",
                _source("mai", "3-bis", "position"),
            ),
            _example(
                "Un temps de jeu excessif peut remplacer le sommeil, les études ou le sport et réduire la concentration.",
                _source("juillet", "5", "position_claire"),
            ),
        ),
        # Conditions
        (
            "un équipement fiable et un suivi humain",
            "reliable equipment and human support",
            "Une formation en ligne efficace exige un équipement fiable et un suivi humain.",
            _source("janvier", "9", "position_claire"),
        ),
        (
            "un contenu adapté à l’âge",
            "age-appropriate content",
            _example(
                "Un contenu adapté à l’âge peut développer la réflexion sans exposer l’enfant à une violence excessive.",
                _source("avril", "11", "position_claire"),
                _source("mai", "1", "position_claire"),
            ),
            _example(
                "Un contenu adapté à l’âge doit s’inscrire dans des loisirs variés et bien encadrés.",
                _source("juillet", "5", "position_claire"),
            ),
        ),
        (
            "un usage strictement encadré",
            "strictly regulated use",
            _example(
                "La vidéosurveillance exige un usage strictement encadré et transparent.",
                _source("avril", "1", "position_claire"),
            ),
            _example(
                "Un usage strictement encadré limite la conservation des images et leur accès aux personnes habilitées.",
                _source("avril", "1", "position_claire"),
            ),
        ),
        (
            "des mises à jour régulières et des mots de passe solides",
            "regular updates and strong passwords",
            "Des mises à jour régulières et des mots de passe solides limitent les intrusions.",
            _source("aout", "13", "position_claire"),
        ),
        _role("condition", (
            "un consentement éclairé",
            "informed consent",
            "Un consentement éclairé est nécessaire avant qu’une montre transmette des données médicales au médecin.",
            _source("aout", "13", "position_claire"),
        )),
        # Solutions
        (
            "conserver les consoles hors de la chambre",
            "to keep consoles out of the bedroom",
            "Les parents peuvent conserver les consoles hors de la chambre pendant la nuit.",
            _source("mai", "3-bis", "position_claire"),
        ),
        (
            "prolonger un programme par une activité créative",
            "to follow a programme with a creative activity",
            "Une famille peut prolonger un programme par une activité créative sans écran.",
            _source("decembre", "14", "position_claire"),
        ),
        # Reusable mechanisms
        (
            "cibler les lieux les plus exposés",
            "to target the highest-risk places",
            _example(
                "La ville peut cibler les lieux les plus exposés plutôt que filmer partout.",
                _source("avril", "1", "position_claire"),
            ),
            _example(
                "Une école peut cibler les lieux les plus exposés en filmant uniquement ses accès.",
                _source("avril", "8", "position_claire"),
            ),
        ),
        (
            "transformer un usage passif en échange instructif",
            "to turn passive use into an instructive discussion",
            "La présence d’un adulte peut transformer un usage passif en échange instructif.",
            _source("janvier", "7", "position_claire"),
        ),
    ),
    "societe": _bank(
        # Notions
        (
            "l’aide aux personnes pauvres",
            "help for people in poverty",
            "L’aide aux personnes pauvres doit répondre à l’urgence et préparer l’autonomie.",
            _source("janvier", "4", "reformulation"),
            _source("juin", "3", "reformulation"),
        ),
        (
            "un accompagnement à long terme",
            "long-term support",
            _example(
                "Un accompagnement à long terme doit compléter l’aide immédiate apportée aux personnes pauvres.",
                _source("janvier", "4", "position_claire"),
                _source("juin", "3", "position_claire"),
            ),
            _example(
                "Un accompagnement à long terme peut commencer après un don ponctuel et faciliter l’accès au logement.",
                _source("janvier", "16", "position_claire"),
            ),
        ),
        (
            "un engagement familial",
            "a family commitment",
            "Un engagement familial est indispensable avant l’adoption d’un animal.",
            _source("mars", "2", "reformulation"),
        ),
        (
            "l’autorité parentale",
            "parental authority",
            "L’autorité parentale doit protéger les jeunes sans les étouffer.",
            _source("mars", "10", "reformulation"),
        ),
        # Productive collocations
        (
            "répondre à une urgence",
            "to respond to an emergency",
            _example(
                "Un secours sans délai doit répondre à une urgence lorsque la faim ou le froid menacent.",
                _source("janvier", "4", "position_claire"),
                _source("juin", "3", "position_claire"),
            ),
            _example(
                "Une association de quartier peut répondre à une urgence en distribuant un repas chaud.",
                _source("janvier", "16", "position_claire"),
            ),
        ),
        (
            "agir sur les causes de la pauvreté",
            "to address the causes of poverty",
            "Un suivi régulier permet d’agir sur les causes de la pauvreté.",
            _source("janvier", "16", "position_claire"),
        ),
        (
            "développer l’empathie et le sens des responsabilités",
            "to develop empathy and a sense of responsibility",
            "S’occuper d’un animal peut développer l’empathie et le sens des responsabilités.",
            _source("mars", "2", "position_claire"),
        ),
        (
            "faire évoluer les règles avec l’âge",
            "to adapt rules as a child grows",
            "Les parents doivent faire évoluer les règles avec l’âge de l’enfant.",
            _source("mars", "10", "position_claire"),
        ),
        # Benefits
        (
            "soulager la faim et le froid",
            "to relieve hunger and cold",
            "Une aide immédiate peut soulager la faim et le froid sans délai.",
            _source("janvier", "4", "position_claire"),
            _source("janvier", "16", "position_claire"),
            _source("juin", "3", "position_claire"),
        ),
        (
            "ouvrir la voie à l’autonomie",
            "to pave the way to independence",
            "Un accompagnement stable peut ouvrir la voie à l’autonomie du bénéficiaire.",
            _source("janvier", "16", "position_claire"),
        ),
        (
            "rompre la solitude",
            "to break isolation",
            _example(
                "La présence quotidienne d’un animal peut rompre la solitude d’un enfant.",
                _source("mars", "2", "position"),
            ),
            _example(
                "Après un déménagement, promener son chien chaque soir peut rompre la solitude d’un jeune.",
                _source("mars", "2", "position_claire"),
            ),
        ),
        (
            "offrir un cadre agréable aux familles",
            "to provide families with a pleasant setting",
            "Le calme et l’espace de la campagne peuvent offrir un cadre agréable aux familles.",
            _source("aout", "17", "position_claire"),
        ),
        _role("benefit", (
            "retrouver son autonomie",
            "to regain independence",
            _example(
                "Un accompagnement durable aide chaque bénéficiaire à retrouver son autonomie.",
                _source("janvier", "4", "position_claire"),
                _source("juin", "3", "position_claire"),
            ),
            _example(
                "Une solidarité efficace aide la personne à retrouver son autonomie une fois l’urgence soulagée.",
                _source("janvier", "16", "position_claire"),
            ),
        )),
        # Risks and limits
        (
            "une aide trop temporaire",
            "support that is too temporary",
            "Une aide trop temporaire ne règle pas les causes de l’exclusion.",
            _source("janvier", "16", "position"),
        ),
        (
            "une responsabilité coûteuse et durable",
            "a costly, long-term responsibility",
            "Un animal représente une responsabilité coûteuse et durable pour toute la famille.",
            _source("mars", "2", "position"),
        ),
        (
            "une liberté totale et floue",
            "total, unclear freedom",
            "Une liberté totale et floue peut inquiéter un jeune au lieu de le rassurer.",
            _source("mars", "10", "position_claire"),
        ),
        (
            "renoncer à l’accès aux emplois et à la culture",
            "to give up access to jobs and culture",
            "Vivre au calme ne doit pas obliger une famille à renoncer à l’accès aux emplois et à la culture.",
            _source("aout", "17", "position_claire"),
        ),
        # Conditions
        (
            "un suivi régulier",
            "regular support",
            _example(
                "Un suivi régulier peut aider une personne à trouver un logement, une formation et un emploi.",
                _source("janvier", "4", "position_claire"),
                _source("juin", "3", "position_claire"),
            ),
            _example(
                "Un suivi régulier agit sur les causes de la pauvreté après l’aide d’urgence.",
                _source("janvier", "16", "position_claire"),
            ),
        ),
        (
            "du temps, un budget et des conditions de vie adaptées",
            "time, a budget and suitable living conditions",
            "Une adoption exige du temps, un budget et des conditions de vie adaptées.",
            _source("mars", "2", "position_claire"),
        ),
        (
            "un équilibre entre sécurité, dialogue et liberté",
            "a balance between safety, dialogue and freedom",
            "L’éducation doit chercher un équilibre entre sécurité, dialogue et liberté.",
            _source("mars", "10", "position_claire"),
        ),
        (
            "des transports fiables",
            "reliable transport",
            "Des transports fiables sont indispensables pour vivre à la campagne sans s’isoler.",
            _source("aout", "17", "position_claire"),
        ),
        # Solutions
        (
            "faciliter l’accès au logement, à la formation et à l’emploi",
            "to facilitate access to housing, training and employment",
            _example(
                "Après un repas chaud, une association peut faciliter l’accès au logement, à la formation et à l’emploi.",
                _source("janvier", "4", "position_claire"),
                _source("juin", "3", "position_claire"),
            ),
            _example(
                "Un suivi incluant une aide au CV peut faciliter l’accès au logement, à la formation et à l’emploi.",
                _source("janvier", "16", "position_claire"),
            ),
        ),
        (
            "fixer ensemble une heure de retour",
            "to agree on a return time together",
            "Des parents et leur adolescente peuvent fixer ensemble une heure de retour.",
            _source("mars", "10", "position_claire"),
        ),
        # Reusable mechanisms
        (
            "unir solidarité concrète et solutions durables",
            "to combine practical solidarity with lasting solutions",
            "Une politique efficace doit unir solidarité concrète et solutions durables.",
            _source("janvier", "4", "position_claire"),
        ),
        (
            "consacrer davantage d’argent aux besoins des enfants",
            "to devote more money to children’s needs",
            "Un logement moins cher permet de consacrer davantage d’argent aux besoins des enfants.",
            _source("aout", "17", "position_claire"),
        ),
    ),
    "transports": _bank(
        # Notions
        (
            "la circulation automobile",
            "car traffic",
            "La circulation automobile peut être réduite progressivement en centre-ville.",
            _source("janvier", "17", "reformulation"),
        ),
        (
            "des alternatives à la voiture",
            "alternatives to cars",
            "Des alternatives à la voiture doivent précéder toute restriction importante.",
            _source("janvier", "17", "reformulation"),
        ),
        (
            "la gratuité des transports publics",
            "free public transport",
            _example(
                "La gratuité des transports publics doit reposer sur un réseau fiable.",
                _source("juillet", "8", "reformulation"),
            ),
            _example(
                "La gratuité des transports publics peut réduire les voitures, la pollution et les maladies respiratoires.",
                _source("juillet", "8", "position"),
            ),
            _example(
                "La gratuité des transports publics est utile lorsque le réseau dessert tous les quartiers.",
                _source("juillet", "8", "position_claire"),
            ),
        ),
        (
            "un réseau fiable",
            "a reliable network",
            _example(
                "Un réseau fiable compte davantage qu’un service gratuit mais trop rare.",
                _source("juillet", "8", "reformulation"),
            ),
            _example(
                "Un réseau fiable doit aussi être fréquent et bien entretenu.",
                _source("juillet", "8", "position_claire"),
            ),
        ),
        # Productive collocations
        (
            "réduire la dépendance au pétrole",
            "to reduce dependence on oil",
            "Moins de circulation permet de réduire la dépendance au pétrole.",
            _source("janvier", "17", "position"),
        ),
        (
            "réduire le risque d’accident",
            "to reduce the risk of accidents",
            "Une baisse du trafic peut réduire le risque d’accident pour les habitants.",
            _source("janvier", "17", "position_claire"),
        ),
        (
            "réduire les embouteillages",
            "to reduce traffic congestion",
            "Des transports attractifs peuvent réduire les embouteillages en centre-ville.",
            _source("juillet", "8", "position_claire"),
        ),
        (
            "desservir tous les quartiers",
            "to serve every neighbourhood",
            "Le réseau doit desservir tous les quartiers, y compris les zones éloignées.",
            _source("juillet", "8", "position_claire"),
        ),
        # Benefits
        (
            "améliorer la qualité de l’air",
            "to improve air quality",
            "Une réduction mesurée des voitures peut améliorer la qualité de l’air sans bouleverser la ville.",
            _source("janvier", "17", "position"),
            _source("janvier", "17", "position_claire"),
        ),
        (
            "réduire le stress des habitants",
            "to reduce residents’ stress",
            "Des rues moins encombrées peuvent réduire le stress des habitants.",
            _source("janvier", "17", "position_claire"),
        ),
        (
            "ramener les clients au centre-ville",
            "to bring customers back to the city centre",
            "Un réseau gratuit peut ramener les clients au centre-ville.",
            _source("juillet", "8", "position"),
        ),
        (
            "laisser sa voiture au garage",
            "to leave one’s car at home",
            "Un billet gratuit peut inciter un automobiliste à laisser sa voiture au garage.",
            _source("juillet", "8", "position_claire"),
        ),
        # Risks and limits
        (
            "bouleverser toute la ville",
            "to disrupt the whole city",
            "Une interdiction brutale risque de bouleverser toute la ville.",
            _source("janvier", "17", "position_claire"),
        ),
        (
            "dépendre de son véhicule",
            "to depend on one’s vehicle",
            "Un travailleur peut dépendre de son véhicule pour exercer un métier essentiel.",
            _source("janvier", "17", "position_claire"),
        ),
        (
            "un service trop coûteux",
            "an excessively costly service",
            "Un service trop coûteux peut empêcher l’amélioration des lignes éloignées.",
            _source("juillet", "8", "position"),
        ),
        (
            "attendre une heure",
            "to wait an hour",
            "Un réseau gratuit reste peu utile si les habitants doivent attendre une heure.",
            _source("juillet", "8", "position_claire"),
        ),
        # Conditions
        (
            "une réduction progressive",
            "a gradual reduction",
            "Une réduction progressive permet de mesurer les effets avant d’aller plus loin.",
            _source("janvier", "17", "position_claire"),
        ),
        (
            "des alternatives accessibles et fiables",
            "accessible and reliable alternatives",
            "La ville doit construire des alternatives accessibles et fiables avant de limiter la voiture.",
            _source("janvier", "17", "position_claire"),
        ),
        (
            "un réseau fréquent et bien entretenu",
            "a frequent, well-maintained network",
            "La gratuité doit s’accompagner d’un réseau fréquent et bien entretenu.",
            _source("juillet", "8", "position_claire"),
        ),
        (
            "des bus dans les zones mal desservies",
            "buses in underserved areas",
            "La collectivité doit ajouter des bus dans les zones mal desservies.",
            _source("juillet", "8", "position_claire"),
        ),
        # Solutions
        (
            "renforcer les lignes de bus",
            "to improve bus services",
            "Une ville peut renforcer les lignes de bus avant de fermer une rue.",
            _source("janvier", "17", "position_claire"),
        ),
        (
            "délivrer des autorisations adaptées aux métiers essentiels",
            "to issue permits to essential professions",
            _example(
                "Une ville en transition doit délivrer des autorisations adaptées aux métiers essentiels qui dépendent d’un véhicule.",
                _source("janvier", "17", "position"),
            ),
            _example(
                "La mairie peut délivrer des autorisations adaptées aux métiers essentiels comme les livraisons et les services d’urgence.",
                _source("janvier", "17", "position_claire"),
            ),
        ),
        # Reusable mechanisms
        (
            "tester la gratuité le week-end",
            "to test free travel at weekends",
            "Une ville peut tester la gratuité le week-end avant de généraliser la mesure.",
            _source("juillet", "8", "position_claire"),
        ),
        (
            "vérifier les effets sans imposer un changement brutal",
            "to assess effects without imposing abrupt change",
            "Une expérience limitée permet de vérifier les effets sans imposer un changement brutal.",
            _source("janvier", "17", "position_claire"),
        ),
    ),
    "logement": _bank(
        # Notions
        (
            "la colocation",
            "shared housing",
            "La colocation demande un équilibre entre économies, dialogue et intimité.",
            _source("janvier", "3", "reformulation"),
        ),
        (
            "une expérience enrichissante",
            "an enriching experience",
            "Une expérience enrichissante devient possible lorsque les colocataires communiquent.",
            _source("avril", "14", "reformulation"),
            _source("mai", "7", "reformulation"),
        ),
        (
            "la colocation entre adultes",
            "shared housing among adults",
            "La colocation entre adultes exige des règles sur le bruit et les invités.",
            _source("juin", "2", "reformulation"),
        ),
        (
            "un soutien vers l’autonomie",
            "support toward independence",
            "Vivre chez ses parents peut constituer un soutien vers l’autonomie.",
            _source("decembre", "15", "reformulation"),
        ),
        # Productive collocations
        (
            "partager le loyer",
            "to share the rent",
            "Deux étudiants peuvent partager le loyer pour vivre près de leur université.",
            _source("janvier", "3", "position_claire"),
        ),
        (
            "répartir équitablement les tâches",
            "to divide chores fairly",
            "Un planning hebdomadaire permet de répartir équitablement les tâches ménagères.",
            _source("janvier", "3", "position_claire"),
            _source("avril", "14", "position_claire"),
        ),
        (
            "respecter les besoins de chacun",
            "to respect everyone’s needs",
            "La vie commune apprend à respecter les besoins de chacun.",
            _source("mai", "7", "position_claire"),
            _source("juin", "2", "position_claire"),
        ),
        (
            "constituer une réserve financière",
            "to build up financial savings",
            "Un jeune adulte peut constituer une réserve financière avant de déménager.",
            _source("decembre", "15", "position_claire"),
        ),
        _role("collocation", (
            "partager les dépenses",
            "to share expenses",
            _example(
                "Trois colocataires peuvent partager les dépenses courantes selon des règles fixées ensemble.",
                _source("avril", "14", "position_claire"),
            ),
            _example(
                "Un jeune adulte vivant chez ses parents peut partager les dépenses en payant une partie des courses.",
                _source("decembre", "15", "position_claire"),
            ),
        )),
        # Benefits
        (
            "réduire les dépenses de logement",
            "to reduce housing costs",
            _example(
                "La colocation permet aux étudiants de réduire les dépenses de logement.",
                _source("janvier", "3", "position"),
            ),
            _example(
                "Partager le loyer peut réduire les dépenses de logement et rapprocher les colocataires du centre-ville.",
                _source("avril", "14", "position_claire"),
            ),
            _example(
                "Trois adultes peuvent réduire les dépenses de logement en divisant le loyer.",
                _source("juin", "2", "position_claire"),
            ),
        ),
        (
            "favoriser la convivialité",
            "to foster sociability",
            "Des repas partagés peuvent favoriser la convivialité entre colocataires.",
            _source("avril", "14", "position_claire"),
        ),
        (
            "rompre l’isolement",
            "to break isolation",
            _example(
                "Partager un logement peut rompre l’isolement d’un étudiant dans une nouvelle ville.",
                _source("mai", "7", "position_claire"),
            ),
            _example(
                "Une colocation entre adultes peut rompre l’isolement et éviter de rentrer seul chaque soir.",
                _source("juin", "2", "position_claire"),
            ),
        ),
        (
            "financer une formation",
            "to fund training",
            "Une économie de loyer peut financer une formation utile.",
            _source("decembre", "15", "position_claire"),
        ),
        # Risks and limits
        (
            "le manque d’intimité",
            "lack of privacy",
            _example(
                "Le manque d’intimité peut provoquer des tensions entre des personnalités différentes.",
                _source("janvier", "3", "position"),
            ),
            _example(
                "Le manque d’intimité devient plus difficile lorsque le bruit et les rythmes de vie s’opposent.",
                _source("avril", "14", "position"),
            ),
        ),
        (
            "les différences de rythme",
            "differences in daily routines",
            "Les différences de rythme deviennent pénibles sans heures calmes.",
            _source("avril", "14", "position"),
        ),
        (
            "les invités imposés",
            "unwanted guests",
            "Les invités imposés peuvent créer des conflits dans un logement partagé.",
            _source("mai", "7", "position"),
        ),
        (
            "les obstacles à l’indépendance",
            "obstacles to independence",
            "Un séjour sans échéance chez ses parents peut renforcer les obstacles à l’indépendance.",
            _source("decembre", "15", "position"),
        ),
        # Conditions
        (
            "des responsabilités définies dès le départ",
            "responsibilities defined from the outset",
            _example(
                "Des responsabilités définies dès le départ protègent le repos, les espaces privés et une répartition équitable du ménage.",
                _source("avril", "14", "position_claire"),
            ),
            _example(
                "Des responsabilités définies dès le départ permettent de fixer des limites sur les invités.",
                _source("mai", "7", "position_claire"),
            ),
            _example(
                "Des responsabilités définies dès le départ peuvent être réévaluées lors d’un bilan mensuel.",
                _source("juin", "2", "position_claire"),
            ),
        ),
        (
            "des colocataires fiables et respectueux",
            "reliable and respectful flatmates",
            "Il faut choisir des colocataires fiables et respectueux.",
            _source("mai", "7", "position_claire"),
        ),
        (
            "des règles concernant le bruit et les invités",
            "rules about noise and guests",
            "Les adultes doivent fixer des règles concernant le bruit et les invités.",
            _source("juin", "2", "position"),
            _source("juin", "2", "position_claire"),
        ),
        (
            "un objectif d’épargne et une échéance",
            "a savings goal and a deadline",
            "Un retour temporaire chez ses parents exige un objectif d’épargne et une échéance.",
            _source("decembre", "15", "position_claire"),
        ),
        _role("condition", (
            "le respect de l’intimité",
            "respect for privacy",
            _example(
                "Le respect de l’intimité évite que le partage d’un logement ne provoque des tensions.",
                _source("janvier", "3", "position"),
                _source("janvier", "3", "position_claire"),
            ),
            _example(
                "Des règles sur les espaces privés garantissent le respect de l’intimité de chaque colocataire.",
                _source("avril", "14", "position_claire"),
            ),
        )),
        # Solutions
        (
            "fixer des heures calmes",
            "to set quiet hours",
            "Les colocataires peuvent fixer des heures calmes pour protéger le repos.",
            _source("avril", "14", "position_claire"),
            _source("mai", "7", "position_claire"),
            _source("juin", "2", "position_claire"),
        ),
        (
            "faire un bilan chaque mois",
            "to review arrangements each month",
            "Trois adultes peuvent faire un bilan chaque mois pour résoudre les difficultés.",
            _source("juin", "2", "position_claire"),
        ),
        _role("solution", (
            "un calendrier de ménage",
            "a cleaning rota",
            _example(
                "Un calendrier de ménage affiché dans la cuisine répartit les tâches dès l’emménagement.",
                _source("janvier", "3", "position_claire"),
            ),
            _example(
                "Un calendrier de ménage hebdomadaire peut être revu lors du bilan mensuel des colocataires.",
                _source("mai", "7", "position_claire"),
                _source("juin", "2", "position_claire"),
            ),
        )),
        # Reusable mechanisms
        (
            "diviser le loyer et les dépenses courantes",
            "to divide the rent and household expenses",
            _example(
                "Deux étudiants peuvent diviser le loyer et les dépenses courantes pour vivre près du campus.",
                _source("janvier", "3", "position_claire"),
            ),
            _example(
                "Trois colocataires peuvent diviser le loyer et les dépenses courantes tout en habitant près des transports.",
                _source("avril", "14", "position_claire"),
            ),
        ),
        (
            "préparer un retour progressif à l’autonomie",
            "to prepare a gradual return to independence",
            "Une étape chez ses parents doit préparer un retour progressif à l’autonomie.",
            _source("decembre", "15", "position_claire"),
        ),
    ),
    "culture-loisirs": _bank(
        # Notions
        (
            "la coexistence du papier et du numérique",
            "the coexistence of print and digital formats",
            "La coexistence du papier et du numérique répond à des besoins différents.",
            _source("janvier", "5", "reformulation"),
        ),
        (
            "la lecture des enfants",
            "children’s reading",
            "La lecture des enfants doit être encouragée sans devenir une punition.",
            _source("mars", "3", "reformulation"),
        ),
        (
            "l’héritage d’un événement sportif",
            "the legacy of a sporting event",
            "L’héritage d’un événement sportif doit profiter durablement aux habitants.",
            _source("avril", "17", "reformulation"),
        ),
        (
            "l’art urbain",
            "urban art",
            "L’art urbain peut enrichir la ville sans dégrader les bâtiments.",
            _source("aout", "12", "reformulation"),
            _source("novembre", "10", "reformulation"),
        ),
        # Productive collocations
        (
            "agrandir les caractères",
            "to enlarge the text",
            _example(
                "Le livre numérique permet d’agrandir les caractères selon les besoins du lecteur.",
                _source("janvier", "5", "position"),
            ),
            _example(
                "Une personne malvoyante peut agrandir les caractères d’un roman sur sa liseuse.",
                _source("janvier", "5", "position_claire"),
            ),
        ),
        (
            "nourrir le vocabulaire et la capacité d’analyse",
            "to develop vocabulary and analytical skills",
            "Des textes adaptés peuvent nourrir le vocabulaire et la capacité d’analyse.",
            _source("mars", "3", "position_claire"),
        ),
        (
            "moderniser les infrastructures",
            "to modernise infrastructure",
            "Un tournoi peut moderniser les infrastructures utilisées par les habitants.",
            _source("avril", "17", "position"),
        ),
        (
            "démocratiser la culture",
            "to broaden access to culture",
            "Des créneaux gratuits peuvent démocratiser la culture.",
            _source("novembre", "11", "position"),
        ),
        # Benefits
        (
            "faciliter la lecture des personnes malvoyantes",
            "to make reading easier for visually impaired people",
            "Le format numérique peut faciliter la lecture des personnes malvoyantes.",
            _source("janvier", "5", "position_claire"),
        ),
        (
            "associer les livres au plaisir",
            "to associate books with enjoyment",
            "Un moment partagé avec un parent peut associer les livres au plaisir.",
            _source("mars", "3", "position_claire"),
        ),
        (
            "rendre la culture accessible",
            "to make culture accessible",
            _example(
                "Une œuvre dans la rue peut rendre la culture accessible sans billet.",
                _source("aout", "12", "position_claire"),
            ),
            _example(
                "Des espaces publics peuvent rendre la culture accessible aux personnes qui fréquentent peu les musées.",
                _source("aout", "12", "position_claire"),
            ),
        ),
        (
            "soutenir les artistes et les commerces locaux",
            "to support local artists and businesses",
            "Un parcours guidé peut soutenir les artistes et les commerces locaux.",
            _source("novembre", "10", "position"),
            _source("novembre", "10", "position_claire"),
        ),
        _role("benefit", (
            "nourrir la curiosité",
            "to foster curiosity",
            "Des œuvres colorées et des rencontres avec les artistes peuvent nourrir la curiosité des passants.",
            _source("aout", "12", "position"),
        )),
        _role("benefit", (
            "réduire les inégalités d’accès à la culture",
            "to reduce inequalities in access to culture",
            _example(
                "Des journées gratuites régulières peuvent réduire les inégalités d’accès à la culture pour les ménages modestes.",
                _source("aout", "14", "position_claire"),
            ),
            _example(
                "Des réductions ciblées peuvent réduire les inégalités d’accès à la culture sans supprimer toutes les recettes.",
                _source("novembre", "11", "position_claire"),
            ),
        )),
        # Risks and limits
        (
            "des dépenses publiques considérables",
            "substantial public spending",
            "Des dépenses publiques considérables peuvent détourner des ressources de la santé.",
            _source("avril", "17", "position"),
        ),
        (
            "la dégradation des biens communs",
            "damage to public property",
            _example(
                "Des graffitis non autorisés peuvent entraîner la dégradation des biens communs et une pollution visuelle.",
                _source("aout", "12", "position"),
            ),
            _example(
                "La dégradation des biens communs impose des frais de nettoyage et nuit à l’image du quartier.",
                _source("novembre", "10", "position"),
            ),
        ),
        (
            "une affluence excessive",
            "excessive crowds",
            "Une affluence excessive peut réduire la qualité de la visite au musée.",
            _source("aout", "14", "position"),
        ),
        (
            "fragiliser les musées",
            "to weaken museums financially",
            "Une gratuité sans financement stable risque de fragiliser les musées.",
            _source("novembre", "11", "position_claire"),
        ),
        # Conditions
        (
            "respecter les goûts et le rythme de chacun",
            "to respect everyone’s tastes and pace",
            "Les adultes doivent respecter les goûts et le rythme de chacun.",
            _source("mars", "3", "position_claire"),
        ),
        (
            "un budget contrôlé et transparent",
            "a controlled and transparent budget",
            "Une grande compétition exige un budget contrôlé et transparent.",
            _source("avril", "17", "position_claire"),
        ),
        (
            "des espaces autorisés",
            "authorised spaces for art",
            _example(
                "Des espaces autorisés permettent de créer une fresque avec les habitants sans dégrader les bâtiments.",
                _source("aout", "12", "position_claire"),
            ),
            _example(
                "La façade d’un centre communautaire peut faire partie des espaces autorisés choisis avec les résidents.",
                _source("novembre", "10", "position_claire"),
            ),
        ),
        (
            "des ressources suffisantes pour protéger les œuvres",
            "sufficient resources to protect artworks",
            _example(
                "Des journées gratuites exigent des ressources suffisantes pour protéger les œuvres.",
                _source("aout", "14", "position_claire"),
            ),
            _example(
                "Des réductions ciblées peuvent maintenir des ressources suffisantes pour protéger les œuvres.",
                _source("novembre", "11", "position_claire"),
            ),
        ),
        # Solutions
        (
            "prévoir l’usage futur des équipements",
            "to plan the future use of facilities",
            "Les autorités doivent prévoir l’usage futur des équipements avant la compétition.",
            _source("avril", "17", "position_claire"),
        ),
        (
            "limiter l’affluence par une réservation horaire",
            "to limit crowds through timed booking",
            _example(
                "Un musée peut limiter l’affluence par une réservation horaire plutôt que renoncer à la gratuité.",
                _source("aout", "14", "position"),
            ),
            _example(
                "Des billets à heure fixe permettent de limiter l’affluence par une réservation horaire.",
                _source("aout", "14", "position_claire"),
            ),
        ),
        # Reusable mechanisms
        (
            "transformer une contrainte en projet commun",
            "to turn a constraint into a shared project",
            "Un cadre négocié peut transformer une contrainte en projet commun.",
            _source("novembre", "10", "position_claire"),
        ),
        (
            "accompagner la gratuité d’une médiation adaptée",
            "to support free entry with appropriate educational guidance",
            _example(
                "Un musée doit accompagner la gratuité d’une médiation adaptée aux différents publics.",
                _source("novembre", "11", "position"),
            ),
            _example(
                "Un musée peut accompagner la gratuité d’une médiation adaptée en organisant une visite pour adolescents.",
                _source("novembre", "11", "position_claire"),
            ),
        ),
    ),
    "consommation": _bank(
        # Notions
        (
            "la livraison de repas au bureau",
            "meal delivery to the workplace",
            "La livraison de repas au bureau reste pratique sans remplacer une vraie pause.",
            _source("janvier", "8", "reformulation"),
            _source("avril", "2", "reformulation"),
            _source("juillet", "3", "reformulation"),
        ),
        (
            "les vêtements de marque",
            "branded clothing",
            "Les vêtements de marque ne devraient pas définir l’identité d’un enfant.",
            _source("mars", "1", "reformulation"),
        ),
        (
            "les produits faits maison",
            "homemade products",
            "Les produits faits maison peuvent être naturels sans être dépourvus de risques.",
            _source("mars", "4", "reformulation"),
            _source("decembre", "13", "reformulation"),
        ),
        (
            "les petits commerces",
            "small local shops",
            "Les petits commerces complètent les supermarchés et maintiennent un service de proximité.",
            _source("mars", "9", "reformulation"),
        ),
        # Productive collocations
        (
            "préserver les échanges entre collègues",
            "to preserve interaction between colleagues",
            "Déjeuner ensemble dans une salle commune ou dehors permet de préserver les échanges entre collègues.",
            _source("janvier", "8", "position_claire"),
            _source("avril", "2", "position_claire"),
            _source("juillet", "3", "position_claire"),
        ),
        (
            "protéger le budget familial",
            "to protect the family budget",
            "Des vêtements solides et abordables permettent de protéger le budget familial.",
            _source("mars", "1", "position_claire"),
        ),
        (
            "réduire les emballages",
            "to reduce packaging",
            _example(
                "Des contenants réutilisables permettent de réduire les emballages et les dépenses.",
                _source("mars", "4", "position"),
                _source("mars", "4", "position_claire"),
            ),
            _example(
                "Du vinaigre et du savon noir peuvent réduire les emballages en remplaçant plusieurs flacons industriels.",
                _source("decembre", "13", "position_claire"),
            ),
        ),
        (
            "soutenir les emplois locaux",
            "to support local jobs",
            "Acheter dans son quartier peut soutenir les emplois locaux.",
            _source("mars", "9", "position_claire"),
        ),
        _role("collocation", (
            "faire une vraie pause",
            "to take a proper break",
            _example(
                "Faire une vraie pause permet de se détendre avant de reprendre le travail avec plus de concentration.",
                _source("janvier", "8", "position_claire"),
            ),
            _example(
                "Faire une vraie pause loin de son poste réduit la fatigue et favorise les échanges.",
                _source("avril", "2", "position_claire"),
            ),
            _example(
                "Faire une vraie pause permet de quitter l’écran et de déjeuner avec ses collègues.",
                _source("juillet", "3", "position_claire"),
            ),
        )),
        # Benefits
        (
            "gagner du temps",
            "to save time",
            _example(
                "Un service disponible à toute heure permet de gagner du temps et de choisir entre plusieurs restaurants.",
                _source("janvier", "8", "position"),
            ),
            _example(
                "Commander à l’avance permet de gagner du temps après une réunion tardive.",
                _source("avril", "2", "position"),
            ),
            _example(
                "Éviter une file d’attente permet de gagner du temps sans raccourcir la pause.",
                _source("juillet", "3", "position"),
            ),
        ),
        (
            "résister à la pression des marques",
            "to resist pressure from brands",
            "Choisir selon la qualité aide les jeunes à résister à la pression des marques.",
            _source("mars", "1", "position_claire"),
        ),
        (
            "connaître l’origine des produits",
            "to know where products come from",
            "Acheter à la ferme permet de connaître l’origine des produits.",
            _source("aout", "3", "position_claire"),
        ),
        (
            "informer les consommateurs",
            "to inform consumers",
            _example(
                "La publicité peut informer les consommateurs sur les produits, les promotions et les prix.",
                _source("octobre", "1", "position"),
            ),
            _example(
                "Une plateforme locale peut informer les consommateurs sans remplir leurs boîtes aux lettres.",
                _source("octobre", "1", "position_claire"),
            ),
        ),
        # Risks and limits
        (
            "normaliser les repas pris devant l’écran",
            "to normalise meals eaten in front of a screen",
            "La livraison ne doit pas normaliser les repas pris devant l’écran.",
            _source("janvier", "8", "position_claire"),
        ),
        (
            "encourager la surconsommation",
            "to encourage overconsumption",
            "La pression sociale peut encourager la surconsommation de vêtements.",
            _source("mars", "1", "position_claire"),
        ),
        (
            "les risques d’irritation ou de contamination",
            "the risk of irritation or contamination",
            _example(
                "Une erreur de formulation augmente les risques d’irritation ou de contamination.",
                _source("mars", "4", "position"),
            ),
            _example(
                "De mauvais ingrédients ou une conservation défaillante augmentent les risques d’irritation ou de contamination.",
                _source("decembre", "13", "position"),
            ),
        ),
        (
            "l’exposition constante à la publicité",
            "constant exposure to advertising",
            "L’exposition constante à la publicité influence les demandes des enfants.",
            _source("aout", "16", "position"),
        ),
        # Conditions
        (
            "une vraie pause loin de son écran",
            "a proper break away from one’s screen",
            _example(
                "Chaque salarié doit prendre une vraie pause loin de son écran pour revenir plus concentré.",
                _source("janvier", "8", "position_claire"),
            ),
            _example(
                "Une équipe peut prendre une vraie pause loin de son écran dans une salle commune ou dehors.",
                _source("avril", "2", "position_claire"),
                _source("juillet", "3", "position_claire"),
            ),
        ),
        (
            "des recettes simples et fiables",
            "simple, reliable recipes",
            _example(
                "La fabrication maison doit se limiter à des recettes simples et fiables pour éviter les produits sensibles.",
                _source("mars", "4", "position_claire"),
            ),
            _example(
                "Des recettes simples et fiables permettent de préparer un produit étiqueté et correctement conservé.",
                _source("decembre", "13", "position_claire"),
            ),
        ),
        (
            "acheter local sans dépasser son budget",
            "to buy local without exceeding one’s budget",
            "Une famille peut acheter local sans dépasser son budget en combinant les commerces.",
            _source("aout", "3", "position_claire"),
        ),
        (
            "une publicité mieux encadrée",
            "better regulated advertising",
            _example(
                "Une publicité mieux encadrée protège les enfants du ciblage tout en développant leur esprit critique.",
                _source("aout", "16", "position_claire"),
            ),
            _example(
                "Une publicité mieux encadrée peut informer sans envahir l’espace public ni gaspiller du papier.",
                _source("octobre", "1", "position_claire"),
            ),
        ),
        # Solutions
        (
            "interdire le ciblage publicitaire des mineurs",
            "to ban advertising targeted at minors",
            "Une plateforme devrait interdire le ciblage publicitaire des mineurs.",
            _source("aout", "16", "position_claire"),
        ),
        (
            "interdire les prospectus non sollicités",
            "to ban unsolicited leaflets",
            "Une municipalité peut interdire les prospectus non sollicités pour réduire les déchets.",
            _source("octobre", "1", "position_claire"),
        ),
        # Reusable mechanisms
        (
            "répartir ses achats selon le prix, la qualité et l’impact local",
            "to divide purchases according to price, quality and local impact",
            _example(
                "Un ménage peut répartir ses achats selon le prix, la qualité et l’impact local entre commerces et supermarché.",
                _source("mars", "9", "position_claire"),
            ),
            _example(
                "Une famille peut répartir ses achats selon le prix, la qualité et l’impact local entre ferme et supermarché.",
                _source("aout", "3", "position_claire"),
            ),
        ),
        (
            "distinguer un produit ménager d’un produit pour la peau",
            "to distinguish a household product from a skincare product",
            "Il faut distinguer un produit ménager d’un produit pour la peau avant de fabriquer.",
            _source("mars", "4", "position_claire"),
            _source("decembre", "13", "position_claire"),
        ),
    ),
    "voyages": _bank(
        # Notions
        (
            "voyager moins cher",
            "to travel more cheaply",
            _example(
                "Voyager moins cher reste possible sans négliger la sécurité.",
                _source("janvier", "19", "reformulation"),
            ),
            _example(
                "Un billet abordable permet aux petits budgets de voyager moins cher et plus souvent.",
                _source("janvier", "19", "position_claire"),
            ),
        ),
        (
            "la sécurité",
            "safety",
            "La sécurité doit rester prioritaire, quel que soit le prix du billet.",
            _source("janvier", "19", "reformulation"),
        ),
        (
            "une compagnie aérienne à bas prix",
            "a low-cost airline",
            "Une compagnie aérienne à bas prix peut convenir à un trajet court.",
            _source("janvier", "19", "position"),
        ),
        (
            "un transport à bas prix",
            "low-cost transport",
            "Un transport à bas prix doit rester transparent, sûr et encadré.",
            _source("janvier", "19", "position_claire"),
        ),
        # Productive collocations
        (
            "proposer des tarifs avantageux",
            "to offer competitive fares",
            "Une compagnie à bas prix peut proposer des tarifs avantageux aux voyageurs.",
            _source("janvier", "19", "position"),
        ),
        (
            "respecter les normes de sécurité",
            "to comply with safety standards",
            "Toute compagnie doit respecter les normes de sécurité sans exception.",
            _source("janvier", "19", "position_claire"),
        ),
        (
            "assurer l’entretien des avions",
            "to ensure aircraft maintenance",
            "Le transporteur doit assurer l’entretien des avions malgré la baisse des prix.",
            _source("janvier", "19", "position_claire"),
        ),
        (
            "garantir de bonnes conditions de travail",
            "to guarantee good working conditions",
            "Une compagnie responsable doit garantir de bonnes conditions de travail à son personnel.",
            _source("janvier", "19", "position"),
            _source("janvier", "19", "position_claire"),
        ),
        # Benefits
        (
            "rendre le voyage accessible",
            "to make travel accessible",
            "Un billet abordable peut rendre le voyage accessible aux petits budgets.",
            _source("janvier", "19", "position_claire"),
        ),
        (
            "voyager plus souvent",
            "to travel more often",
            "Des tarifs réduits permettent à certains voyageurs de voyager plus souvent.",
            _source("janvier", "19", "position_claire"),
        ),
        (
            "payer moins cher qu’en train",
            "to pay less than for a train ticket",
            "Sur certains trajets, un passager peut payer moins cher qu’en train.",
            _source("janvier", "19", "position"),
        ),
        (
            "bénéficier de davantage de confort",
            "to enjoy greater comfort",
            "Sur un trajet long, un voyageur peut choisir de bénéficier de davantage de confort.",
            _source("janvier", "19", "position_claire"),
        ),
        # Risks and limits
        (
            "l’absence de services à bord",
            "the lack of on-board services",
            "L’absence de services à bord est plus facile à accepter sur un vol court.",
            _source("janvier", "19", "position"),
        ),
        (
            "des conditions de travail difficiles",
            "difficult working conditions",
            "Des conditions de travail difficiles ne peuvent pas justifier un billet moins cher.",
            _source("janvier", "19", "position"),
        ),
        (
            "des avions vieillissants",
            "ageing aircraft",
            "Des avions vieillissants peuvent susciter des inquiétudes chez les passagers.",
            _source("janvier", "19", "position"),
        ),
        (
            "réduire l’entretien pour baisser les prix",
            "to cut maintenance to lower prices",
            "Une compagnie ne doit jamais réduire l’entretien pour baisser les prix.",
            _source("janvier", "19", "position_claire"),
        ),
        # Conditions
        (
            "des normes de sécurité respectées",
            "safety standards that are met",
            "Un vol à bas prix reste acceptable avec des normes de sécurité respectées.",
            _source("janvier", "19", "position_claire"),
        ),
        (
            "un tarif transparent",
            "transparent pricing",
            "Un tarif transparent doit préciser quels services sont absents du billet à bas prix.",
            _source("janvier", "19", "position"),
            _source("janvier", "19", "position_claire"),
        ),
        (
            "de meilleures garanties de sécurité",
            "better safety guarantees",
            "Un voyageur peut payer davantage pour de meilleures garanties de sécurité.",
            _source("janvier", "19", "position_claire"),
        ),
        (
            "un encadrement correct du transport",
            "proper regulation of transport",
            "Un encadrement correct du transport protège les passagers et le personnel.",
            _source("janvier", "19", "position_claire"),
        ),
        _role("condition", (
            "le coût total",
            "the total cost",
            _example(
                "Le coût total d’un vol doit être comparé à celui du train ou de la voiture lorsque les services à bord sont absents.",
                _source("janvier", "19", "position"),
            ),
            _example(
                "Le coût total peut être plus élevé sur un trajet long lorsque la sécurité et le confort priment.",
                _source("janvier", "19", "position_claire"),
            ),
        )),
        # Solutions
        (
            "contrôler régulièrement l’état des avions",
            "to regularly check the condition of aircraft",
            _example(
                "Les autorités doivent contrôler régulièrement l’état des avions vieillissants.",
                _source("janvier", "19", "position"),
            ),
            _example(
                "Il faut contrôler régulièrement l’état des avions sans réduire leur entretien pour baisser les prix.",
                _source("janvier", "19", "position_claire"),
            ),
        ),
        (
            "informer clairement sur les services inclus",
            "to clearly explain the services included",
            _example(
                "La compagnie doit informer clairement sur les services inclus lorsque le repas à bord est absent.",
                _source("janvier", "19", "position"),
            ),
            _example(
                "Un transport transparent doit informer clairement sur les services inclus dans le billet.",
                _source("janvier", "19", "position_claire"),
            ),
        ),
        # Reusable mechanisms
        _role("mechanism", (
            "l’empreinte carbone",
            "carbon footprint",
            "Comparer l’avion et le train exige de considérer l’empreinte carbone en plus du prix.",
            _source("janvier", "19", "position"),
            _source("mai", "5", "position"),
        )),
        (
            "adapter son choix à la durée du trajet",
            "to adapt one’s choice to the length of the journey",
            _example(
                "Un passager peut adapter son choix à la durée du trajet en prenant un vol à bas prix pour un parcours court.",
                _source("janvier", "19", "position_claire"),
            ),
            _example(
                "On peut adapter son choix à la durée du trajet en payant davantage pour un vol transatlantique.",
                _source("janvier", "19", "position_claire"),
            ),
        ),
        (
            "économiser sans négliger la sécurité",
            "to save money without neglecting safety",
            "Un voyageur peut économiser sans négliger la sécurité ni les conditions de travail.",
            _source("janvier", "19", "position_claire"),
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
