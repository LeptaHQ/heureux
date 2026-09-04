# EE — Tâche 2 — sujets 2025

Corpus **verbatim** des consignes d'**Expression écrite, Tâche 2** publiées en 2025
(article de blog, message sur un forum ou page d'un site : raconter une expérience,
la décrire et l'expliquer).

La tâche est active dans `sections.json`. Son parcours conserve les 138 publications,
les classe par thème et relie les republications à 88 exercices canoniques :

- `responses/<theme>.json` contient **92 versions modèles** de **120 à 150 mots**.
  Les versions `origin: author` viennent de la
  [banque personnelle de l'auteur](https://dot-ear-743.notion.site/2d82e3acbb10809eb5d2c44ed17bccbf?v=3d02e3acbb1080e5878b000c3c0edec0) ;
  les réponses manquantes ont été rédigées dans le même registre et contrôlées
  contre leur consigne.
- `load_ee_writing_categories(2)` valide la couverture, l'ordre, les limites et
  place les versions de l'auteur en premier.
- Chaque occurrence garde son mois et son numéro de combinaison, tandis que la
  réponse personnelle et la progression sont partagées avec son sujet canonique.
- `ai_examiner_prompt.md` — prompt d’évaluation propre à la Tâche 2 ; la page
  du sujet y ajoute automatiquement la consigne exacte avant la copie.

### Méthodologie appliquée

Conformément à la description officielle, la Tâche 2 est un **compte rendu
d’expérience ou un récit**, accompagné des commentaires, opinions ou arguments
demandés par la consigne. Chaque réponse situe l’expérience, raconte des actions
avec des détails et des émotions, puis répond à l’objectif précis. FEI fixe
**60 minutes pour les trois tâches réunies**, sans temps officiel par tâche.

## Contenu

- `subjects/<mois>.json` — un fichier par mois, même convention que `tache_3/subjects/`.
- `sujets-2025.json` — index structuré complet.
- `sujets-2025.md` — document lisible, mois par mois.

**138 sujets sur 11 mois.** *Février 2025 : aucune page publiée sur la source.*

| Mois | Sujets | Mois | Sujets |
|---|---|---|---|
| Janvier | 15 | Août | 16 |
| Mars | 14 | Septembre | 6 |
| Avril | 20 | Octobre | 4 |
| Mai | 8 | Novembre | 12 |
| Juin | 5 | Décembre | 19 |
| Juillet | 19 | **Total** | **138** |

### Format d'un sujet

```json
{
  "id": 281,
  "combinaison": "Combinaison 1",
  "key": "ee-tache2:janvier:combinaison-1",
  "prompt": "consigne recopiée mot pour mot"
}
```

La clé `key` est l'identifiant stable du sujet. Mai 2025 publiant **deux** panneaux
« Combinaison 3 », le second porte le suffixe `-bis`
(`ee-tache2:mai:combinaison-3-bis`) ; la convention est partagée par les trois tâches,
et les Tâches 1, 2 et 3 d'une même combinaison portent donc la même clé au préfixe près.

## Thèmes et sujets équivalents

- `subject_themes.json` — 11 thèmes (`slug`, `name`, `icon`, `order`) et la table
  `content_key → thème` couvrant **les 138 sujets**.
- `equivalent_groups.json` — **33 groupes** (83 sujets) republiés sous la même
  consigne. Les seuls écarts admis sont des artefacts source audités : préfixe
  « Analysez le sujet… », ponctuation ou bloc accidentellement dupliqué. Le membre
  `canonical` est toujours le plus ancien du groupe ; un sujet n'appartient qu'à un
  seul groupe et tous les membres partagent son thème.
  **88 sujets distincts** subsistent une fois les doublons regroupés.

| Thème | Slug | Sujets |
|---|---|---|
| Voyages & découvertes | `voyages` | 22 |
| Vie de quartier & entraide | `vie-quartier` | 5 |
| Travail & vie professionnelle | `travail` | 12 |
| Études & langues | `etudes-langues` | 26 |
| Loisirs & culture | `loisirs-culture` | 28 |
| Sport & santé | `sport-sante` | 8 |
| Numérique & réseaux | `numerique` | 3 |
| Environnement & consommation | `environnement` | 12 |
| Rencontres & relations | `rencontres` | 4 |
| Fêtes & traditions | `fetes-traditions` | 13 |
| Logement & cadre de vie | `logement-ville` | 5 |

Chargement et validation : `load_ee_subject_themes(2)` et
`load_ee_equivalent_groups(2)` dans `study/content_loader.py`. Les règles sont celles
de l'Expression orale Tâche 2 : version 1, identifiants en `kebab-case` uniques, au
moins deux membres, `canonical` le plus ancien, aucun chevauchement entre groupes,
aucun franchissement de thème, et consigne normalisée réellement partagée.

## Reproduction

Les consignes ont été relevées sur les pages mensuelles publiques de la source, chaque
combinaison étant dépliée avant extraction. Le texte est repris **sans modification**
(ponctuation et typographie d'origine comprises).
