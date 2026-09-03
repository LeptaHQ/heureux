# EE — Tâche 3 — 2025 (sujets, réponses, vocabulaire, mémoires)

Contenu d'entraînement pour l'**Expression écrite (EE), Tâche 3**.
Ce dossier regroupe les **sujets sources** et l'ensemble des **réponses modèles**,
**vocabulaires** et **mémoires** générés à partir de ces sujets.

## Contenu

**Sources (sujets + documents, sans corrections)**
- `sujets-documents-2025.md` — document lisible : tous les sujets, mois par mois.
- `sujets-documents-2025.json` — index structuré complet (tous les mois).
- `subjects/<mois>.json` — un fichier par mois (même convention que `tache_2/subjects/`).

**Réponses modèles** — `responses/<mois>.md`
- Une réponse par combinaison : **Partie 1 — Synthèse (40–60 mots)** neutre (connecteur
  d'opposition) + **Partie 2 — Point de vue personnel (80–120 mots)** (avis + arguments +
  exemple + concession + conclusion). Total 120–180 mots, comptes étiquetés.

**Vocabulaire** — `vocabulary/<mois>.json`
- **30 entrées par réponse**, capturant la langue la plus réutilisable (connecteurs,
  formules d'avis/conclusion en `phrase-modele`, mots-clés/collocations/verbes thématiques).
  Chaque `example` reprend une phrase de la réponse. Clé : `ee-tache3:<mois>:combinaison-<n>`.

**Mémoires** — `memoires/memoire_<Q>.json`
- **4 mémoires trimestrielles** de formulations réutilisables, calquées sur la structure
  des mémoires de l'Expression orale Tâche 2 (`tache_2/master_question_bank*.json`) :
  Q1 = janvier+mars · Q2 = avril+mai+juin · Q3 = juillet+août+septembre · Q4 = octobre+novembre+décembre.

**138 sujets → 138 réponses → 4 140 entrées de vocabulaire → 4 mémoires (1 286 formulations).**
*Février 2025 : aucune page publiée sur la source.*

| Mois | Sujets/Réponses | Vocab (30×) |
|---|---|---|
| Janvier | 15 | 450 |
| Mars | 14 | 420 |
| Avril | 20 | 600 |
| Mai | 8 | 240 |
| Juin | 5 | 150 |
| Juillet | 19 | 570 |
| Août | 16 | 480 |
| Septembre | 6 | 180 |
| Octobre | 4 | 120 |
| Novembre | 12 | 360 |
| Décembre | 19 | 570 |
| **Total** | **138** | **4 140** |

## Format d'un sujet (JSON)

```json
{
  "id": 281,
  "combinaison": "Combinaison 1",
  "sujet": "titre-débat",
  "document1": "texte du document 1",
  "document2": "texte du document 2",
  "flags": {
    "title_missing": false,
    "document2_missing": false,
    "documents_identical": false,
    "deduced_theme": null
  }
}
```

Chaque sujet de Tâche 3 comprend un **titre-débat** et **deux documents** de points de
vue opposés. Le champ `opinion` (pour/contre) de la source, peu fiable, n'est pas repris :
la position ressort du texte.

## Notes sur la source (voir `flags`)

- **Titre absent** (documents présents) : Avril — Combinaisons 9, 11, 12, 13. Un
  `deduced_theme` est fourni, déduit des documents (éditorial), signalé comme tel.
- **Deuxième document absent** : Juin — Combinaisons 2, 3.
- **Documents identiques** (doublon source) : Mai — Combinaison 3.
- **Numéro de combinaison dupliqué** : Mai publie **deux** panneaux « Combinaison 3 ».
  Le second reçoit le suffixe `-bis` (`ee-tache3:mai:combinaison-3-bis`) pour rester
  identifiable ; la même convention vaut pour les Tâches 1 et 2.
- La numérotation des combinaisons reprend celle de la source (sauts possibles).

## Thèmes et sujets équivalents

- `subject_themes.json` — taxonomie de 11 thèmes (`slug`, `name`, `icon`, `order`) et
  table `content_key → thème` couvrant **les 138 sujets**.
- `equivalent_groups.json` — **26 groupes** de sujets que la source a republiés à
  l'identique. Pour la Tâche 3, l'identité d'un sujet est celle de ses **deux documents** :
  le titre est éditorial et varie d'un mois à l'autre (« Vivre en colocation » /
  « Vivre En Colocation : Pour Ou Contre ? »). Le membre `canonical` est toujours le
  plus ancien du groupe. Mêmes règles de validation que l'Expression orale Tâche 2.

Chargement et validation : `load_ee_subject_themes(3)` et
`load_ee_equivalent_groups(3)` dans `study/content_loader.py`.

## Conformité au texte source (audit 2026-09)

Les 138 sujets ont été re-scrapés puis comparés champ par champ à la source. Neuf
champs avaient été paraphrasés lors de la collecte initiale et ont été **remplacés par
le texte verbatim** :

| Sujet | Champ(s) corrigé(s) |
|---|---|
| Janvier — Combinaison 8 | `document1`, `document2` |
| Mars — Combinaison 6 | `document1`, `document2` |
| Août — Combinaison 15 | `document1`, `document2` |
| Août — Combinaison 17 | `document1`, `document2` |
| Novembre — Combinaison 2 | `sujet`, `document1`, `document2` |
| Novembre — Combinaison 3 | `document1`, `document2` |
| Novembre — Combinaison 8 | `document1`, `document2` |
| Décembre — Combinaison 6 | `document1`, `document2` |

Deux d'entre eux étaient de véritables défauts de données : Août C15 portait un
`document2` sur les caméras de surveillance scolaires sous un titre « La Restauration
Rapide », et Novembre C3 reprenait les documents de Janvier C1. Les **synthèses**
(Partie 1) de ces deux réponses ont été réécrites pour coller aux documents réels ;
leurs entrées de vocabulaire issues de la synthèse ont été régénérées. Novembre C2
retrouve son titre source (« Les bureaux électriques »).

## Reproduction

- Récupération des sujets : `eo/ee_scrape_2025/` (`extract.py`, `build.py`, `raw/`).
- Génération : specs `generation-spec.md`, `vocab-spec.md`, `memoire-spec.md` (dossier `eo/ee_scrape_2025/`),
  exécutées par des agents GPT-5.6 Sol (effort max pour réponses/mémoires).
- Validation : `validate_responses.py` (comptes de mots, étiquettes, connecteurs),
  `validate_vocab.py` (30/réponse, ids uniques, terme présent dans l'exemple),
  `validate_memoire.py` (règles du parseur `content_loader.py` : sections consécutives, phrases uniques).
