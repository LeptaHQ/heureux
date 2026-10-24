"""Curated subjunctive clauses reviewed in their complete spoken context."""

from hashlib import sha256
import json
from pathlib import Path

from django.test import SimpleTestCase

from study.tache_three_models import load_tache_three_models, spoken_text


REVIEWED_CLAUSES = {
    "culture-p1": "sans que ce soit une rupture imposée",
    "culture-p10": "n'exige pas que chaque pratique soit reproduite",
    "culture-p11": "il faut que l'information soit vérifiée",
    "culture-p12": "à condition que le programme et la durée correspondent",
    "culture-p13": "sans qu'on attende d'eux une carrière artistique",
    "culture-p14": "Il faut qu'on garde en tête",
    "culture-p15": "ils attendent qu'elle soit rentrée",
    "culture-p16": "sans qu'on ait d'amis",
    "culture-p17": "il arrive qu'on ne puisse pas rentrer",
    "culture-p18": "je trouve dommage qu'on s'envoie moins de lettres",
    "culture-p19": "sans qu'un interprète ait à tout nous expliquer",
    "culture-p2": "Il faut alors qu'on discute du comportement observé",
    "culture-p20": "à condition que l'auditeur prenne le temps",
    "culture-p21": "sans attendre qu'un compagnon décide",
    "culture-p24": "pour qu'une relation se construise",
    "culture-p25": "sans qu'un gain financier soit nécessaire",
    "culture-p26": "Il faut que je le compare",
    "culture-p27": "sans qu'on l'accuse de trahir sa culture",
    "culture-p29": "Pour qu'une visite soit possible",
    "culture-p3": "sans que les habitants sachent les utiliser",
    "culture-p30": "à condition que chacun ait envie",
    "culture-p31": "pour que chacun puisse garder une distance",
    "culture-p33": "Il faut qu'une célébrité puisse être interrogée",
    "culture-p34": "Il faut qu'on juge l'ensemble de la pratique",
    "culture-p35": "sans qu'elle ait à prouver son utilité économique",
    "culture-p4": "afin qu'elle puisse demander cette aide elle-même",
    "culture-p5": "il faut donc qu'on vérifie",
    "culture-p6": "Je ne pense pas que le livre soit devenu inutile",
    "culture-p7": "Cela ne signifie pas que toute œuvre doive plaire",
    "culture-p8": "pourrait craindre que tous les établissements soient violents",
    "culture-p9": "Il faut qu'on réfléchisse",
    "economie-p1": "je ne supposerais pas que tous les postes exigent le même bilinguisme",
    "economie-p10": "Il faut aussi qu'on examine les obstacles",
    "economie-p14": "je ne dirais pas quelle proportion part sans autre choix, ni que ceux qui restent disposent forcément de meilleures options",
    "economie-p15": "Il faut donc qu'on apprenne à se faire comprendre",
    "economie-p16": "prévoir qu'une partie des recettes serve à l'entretien et à des visites commentées",
    "economie-p17": "que cette personne soit un homme ou une femme",
    "economie-p18": "Je ne pense pas qu'il faille gagner beaucoup d'argent",
    "economie-p2": "pour que sa marque apparaisse",
    "economie-p20": "Il faut qu'on examine le poste réel",
    "economie-p22": "à condition qu'il n'en bénéficie pas déjà et que le service lui soit utile",
    "economie-p23": "sans que la personne puisse y accéder seule",
    "economie-p24": "sans que chacun doive marcher",
    "economie-p3": "exige que l'on connaisse les ressources disponibles",
    "economie-p4": "à condition qu'on ait aussi le temps de se réveiller correctement",
    "economie-p6": "demande que le travail soit bien organisé",
    "economie-p9": "Il faut qu'on regarde au-delà du salaire mensuel",
    "education-p1": "sans que sa motivation ou ses capacités aient soudainement changé",
    "education-p10": "pour que l'équipe puisse chercher une solution",
    "education-p12": "exigent qu'on ait une formation précise",
    "education-p13": "Il faut aussi qu'on tienne compte des ressources et du temps disponibles",
    "education-p14": "attendre d'un seul livre qu'il explique tout",
    "education-p15": "demander que chacun vérifie tout en permanence",
    "education-p16": "Je ne pense pas qu'un salaire exactement identique pour tous soit toujours juste",
    "education-p17": "pour que d'autres l'appellent",
    "education-p18": "Il faut que les élèves comprennent, apprennent à raisonner et puissent travailler avec les autres",
    "education-p19": "il faut que le contenu et la durée soient adaptés à l'âge et aux besoins de l'enfant",
    "education-p2": "sans qu'il soit nécessaire d'obtenir une qualification",
    "education-p20": "je souhaite que l'université soit accessible",
    "education-p21": "Il faut aussi qu'on définisse sa réussite",
    "education-p22": "sans attendre qu'un cours collectif y revienne",
    "education-p23": "Il faut que le groupe s'organise, écoute les consignes et tienne compte des visiteurs",
    "education-p3": "Pour que cette possibilité soit réelle",
    "education-p4": "accepter que les autres ne procèdent pas comme nous",
    "education-p5": "Il faut que le logement, les transports et les dépenses avant un revenu confirmé soient prévus dans un budget",
    "education-p6": "évite ainsi que tous les volontaires arrivent au même moment",
    "education-p7": "quel que soit l'âge du départ",
    "environnement-p1": "sans exiger qu'elles racontent toute leur vie",
    "environnement-p11": "J'attendrais que les résultats servent à améliorer le service",
    "environnement-p13": "sans que tout se résume à une opposition entre deux camps",
    "environnement-p14": "éviter que les gains soient annulés",
    "environnement-p2": "ne garantit pas que l'animal soit respecté",
    "environnement-p3": "sans supposer que chaque ménage gaspille volontairement",
    "environnement-p4": "pour que les animaux puissent s'éloigner des visiteurs",
    "environnement-p6": "à condition que les correspondances suivent",
    "environnement-p7": "Il faut que le label soit contrôlé",
    "environnement-p8": "Il faut aussi que les transports de liaison soient accessibles",
    "environnement-p9": "doivent guider une organisation qui permette de visiter un territoire",
    "famille-p1": "Il faut que l'enfant sache",
    "famille-p10": "sans que la relation familiale soit mauvaise",
    "famille-p11": "sans que le travail à accomplir disparaisse",
    "famille-p12": "L'objectif n'est pas que le parent décide de tout",
    "famille-p13": "sans qu'une traduction soit toujours nécessaire",
    "famille-p14": "pour que les autres puissent se reposer",
    "famille-p16": "sans que les parents aient à tout organiser",
    "famille-p2": "sans que les parents aient à tout organiser",
    "famille-p3": "sans qu'on soit obligé de reproduire exactement son parcours",
    "famille-p4": "sans que l'enfant devienne le confident des adultes",
    "famille-p5": "Il faut alors qu'on trouve d'autres appuis et qu'on prévoie",
    "famille-p6": "Je comprends qu'un parent veuille encourager son enfant",
    "famille-p7": "sans que cela signifie rejeter sa famille",
    "famille-p9": "sans qu'on soit obligé de suivre tous les conseils",
    "sante-p1": "il faut que chacun tienne compte de ce que ses partenaires savent faire",
    "sante-p10": "ne garantit pas que toute consommation cesse",
    "sante-p11": "que la vente soit publique ou privée",
    "sante-p13": "sans demander que tout le monde change son alimentation",
    "sante-p14": "il faut que la personne connaisse l'activité, puisse entrer dans le lieu et s'y sente accueillie",
    "sante-p15": "ne prouve pas qu'un âge de 70 ans convienne à tous ni qu'un dispositif unique soit suffisant",
    "sante-p16": "il ne faut pas que les repas partagés deviennent une obligation pour ceux qui vivent seuls",
    "sante-p17": "il faut aussi qu'on change les horaires ou répartisse autrement le travail",
    "sante-p19": "sans qu'on suppose que jouer le rend agressif",
    "sante-p2": "Il faut qu'il y ait des règles réalistes et des alternatives accessibles",
    "sante-p20": "Il faut qu'on puisse payer son logement, sa nourriture et les déplacements nécessaires",
    "sante-p22": "il faut qu'on prenne du temps l'un pour l'autre et qu'on s'écoute",
    "sante-p23": "il faut que la personne puisse l'obtenir et être suivie",
    "sante-p3": "Il faut donc qu'un planning réalisable prévoie du repos",
    "sante-p4": "il faut que les personnes aidées gardent une voix dans les décisions",
    "sante-p6": "Il faut qu'on regarde ce que l'on mange toute la journée",
    "sante-p7": "Il faut aussi que le budget alimentaire laisse de la place au logement et aux autres dépenses essentielles",
    "sante-p8": "quelles que soient leurs difficultés",
    "sante-p9": "Il faut que l'information éclaire le choix et ne serve pas de simple formalité",
    "technologie-p1": "sans qu'il soit nécessaire de connaître déjà ses membres",
    "technologie-p10": "à condition que l'auteur soit identifiable",
    "technologie-p11": "Cela suppose que les interlocuteurs acceptent le délai",
    "technologie-p12": "à condition que le papier n'ait pas été perdu ou abîmé",
    "technologie-p13": "à condition qu'elle reçoive le message à temps",
    "technologie-p15": "il faut que la société conserve des accès adaptés",
    "technologie-p16": "Il faut que l'accompagnement soit toujours adapté aux capacités de l'enfant",
    "technologie-p17": "Il faut donc qu'une présence humaine apporte quelque chose à l'objectif",
    "technologie-p18": "Il faut que l'interface soit utilisable",
    "technologie-p19": "afin que ses personnages puissent se rencontrer",
    "technologie-p2": "il faut qu'on ait d'autres outils",
    "technologie-p20": "Il faut qu'on améliore les alternatives",
    "technologie-p21": "Encore faut-il qu'on fasse cette recherche",
    "technologie-p22": "Il faut que les règles définissent les urgences et les délais de réponse",
    "technologie-p24": "Il faut toujours qu'on vérifie l'auteur, la date et les sources utilisées",
    "technologie-p3": "l'important est qu'il corresponde aux envies et aux possibilités de la personne",
    "technologie-p4": "Il faut aussi que les plateformes limitent les sollicitations envahissantes",
    "technologie-p5": "avant que le téléspectateur sache ce qu'elle va montrer",
    "technologie-p6": "il faut que l'image soit datée",
    "technologie-p7": "sans que personne ne lui demande comment elle va"
}


class TacheThreeSubjunctiveTests(SimpleTestCase):
    def test_every_model_has_its_reviewed_subjunctive_in_spoken_content(self):
        models = load_tache_three_models()
        self.assertEqual(len(REVIEWED_CLAUSES), 131)
        self.assertEqual(set(REVIEWED_CLAUSES), {key.split('/')[-1] for key in models})
        for group, clause in REVIEWED_CLAUSES.items():
            with self.subTest(group=group):
                self.assertIn(clause, spoken_text(models['eo/tache-3/' + group].response))

    def test_protected_book_model_and_plan_remain_verbatim(self):
        directory = Path(__file__).resolve().parents[1] / 'content' / 'tache_3'
        for filename, expected in (
            ('responses/culture.json', 'c01c6069fe9302d6a8abe2c8c543e757a32104957d8b958d9da6edf9ca7be58e'),
            ('hints.json', '5e2f11e171028382a01bd8da1ac6d24277954d9a8c82af9c43d7ac941b7442d7'),
        ):
            with self.subTest(file=filename):
                text = (directory / filename).read_text()
                start = text.index('{', text.index('"culture-p6":'))
                _, end = json.JSONDecoder().raw_decode(text[start:])
                self.assertEqual(sha256(text[start:start + end].encode()).hexdigest(), expected)
