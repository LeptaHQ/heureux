# EE — Tâche 2 — sujets 2025

Corpus **verbatim** des consignes d'**Expression écrite, Tâche 2** publiées en 2025
(article de blog, message sur un forum ou page d'un site : raconter une expérience,
la décrire et l'expliquer).

Ce dossier ne contient **que les sujets sources** : ni réponse modèle, ni correction,
ni vocabulaire. La tâche est déclarée `available: false` dans `sections.json` tant
qu'aucun contenu d'entraînement n'a été produit.

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
- `equivalent_groups.json` — **30 groupes** (76 sujets) republiés mot pour mot d'un
  mois à l'autre. Le membre `canonical` est toujours le plus ancien du groupe ; un
  sujet n'appartient qu'à un seul groupe et tous les membres partagent son thème.
  **92 sujets distincts** subsistent une fois les doublons regroupés.

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
aucun franchissement de thème, et wording réellement partagé.

## Reproduction

Les consignes ont été relevées sur les pages mensuelles publiques de la source, chaque
combinaison étant dépliée avant extraction. Le texte est repris **sans modification**
(ponctuation et typographie d'origine comprises).
