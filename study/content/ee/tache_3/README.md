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
- Une réponse par combinaison : **Partie 1 — Synthèse (40–60 mots)** neutre
  des deux opinions + **Partie 2 — Point de vue personnel (80–120 mots)**.
  Ces plages figurent dans l’exemple d’épreuve officiel FEI ; le total officiel
  est de 120–180 mots. Les modèles ajoutent un titre pertinent comme choix
  éditorial ; FEI ne le présente pas comme une exigence générale.
- `ai_examiner_prompt.md` — prompt d’évaluation propre à la Tâche 3, disponible
  depuis la vue d’ensemble avant de fournir le sujet et ses deux documents.
- La vue d’ensemble donne accès au vocabulaire des sujets regroupé par thème ;
  chaque thème conserve les decks et la progression des réponses distinctes.

**Vocabulaire** — `vocabulary/<mois>.json`
- **30 entrées par réponse**, capturant la langue la plus réutilisable (connecteurs,
  formules d'avis/conclusion en `phrase-modele`, mots-clés/collocations/verbes thématiques).
  Chaque `example` contextualise exactement sa cible française ; après une correction
  de réponse, les exemples fondés sur une phrase retirée sont régénérés. Clé :
  `ee-tache3:<mois>:combinaison-<n>`.
  Les 138 blocs sont conservés, mais le parseur n'importe que les blocs `canonical`
  (voir « Thèmes et sujets équivalents ») : **84 × 30 = 2 520 entrées importées**.

**Mémoires** — `memoires/memoire_<Q>.json`
- **4 mémoires trimestrielles** de formulations réutilisables, calquées sur la structure
  des mémoires de l'Expression orale Tâche 2 (`tache_2/master_question_bank*.json`) :
  Q1 = janvier+mars · Q2 = avril+mai+juin · Q3 = juillet+août+septembre · Q4 = octobre+novembre+décembre.

**Archive source : 138 sujets → 138 blocs de réponse → 4 140 blocs de vocabulaire
→ 4 mémoires (1 286 formulations).**
*Février 2025 : aucune page publiée sur la source.*

Après regroupement des republications (`equivalent_groups.json`), l'application expose
**84 réponses distinctes** pour **138 sujets datés** et **2 520 entrées de vocabulaire**.

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
    "document1_invalid": false,
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
- **Premier document hors sujet** (`document1_invalid`) : Décembre — Combinaison 10. La
  source a publié à la place du premier document une consigne d'écriture de Tâche 1
  (« Vous avez étudié dans une université à l'étranger… »). Le texte source est conservé
  **verbatim** ; seule la réponse modèle a été réécrite pour ne s'appuyer que sur le
  document réellement valide.
- **Coquilles de la source conservées verbatim** (aucune correction du texte source) :
  Mai — Combinaison 6 (« je mange mos gras » pour « moins gras ») ; Décembre —
  Combinaison 16 (« la déforestation, qui augmente le végétaux qui retiennent le
  carbone », phrase incohérente dans la source). Les réponses modèles évitent de
  reprendre ces formulations défectueuses.
- **Numéro de combinaison dupliqué** : Mai publie **deux** panneaux « Combinaison 3 ».
  Le second reçoit le suffixe `-bis` (`ee-tache3:mai:combinaison-3-bis`) pour rester
  identifiable ; la même convention vaut pour les Tâches 1 et 2.
- La numérotation des combinaisons reprend celle de la source (sauts possibles).

## Thèmes et sujets équivalents

- `subject_themes.json` — taxonomie de 11 thèmes (`slug`, `name`, `icon`, `order`) et
  table `content_key → thème` couvrant **les 138 sujets**.
- `equivalent_groups.json` — **32 groupes** couvrant **86 sujets** que la source a
  republiés à l'identique ; les 138 sujets datés se ramènent donc à **84 réponses
  distinctes**. Pour la Tâche 3, l'identité d'un sujet est celle de ses **deux
  documents** : le titre est éditorial et varie d'un mois à l'autre (« Vivre en
  colocation » / « Vivre En Colocation : Pour Ou Contre ? »). La comparaison des
  documents est **insensible à leur ordre** (la source les intervertit parfois) et
  tolère une dérive typographique auditée (similarité ≥ 0,93). Le membre `canonical`
  est toujours le plus ancien du groupe. Mêmes règles de validation que l'Expression
  orale Tâche 2.
- `ee_tache_three_phrase_id_merges()` associe les **1 620 identifiants** de vocabulaire
  des publications devenues alias aux 30 fiches de leur réponse canonique. L'import
  conserve ainsi les calendriers de révision et les annotations déjà créés.
- `author_responses.json` — **10 réponses rédigées par l'auteur** qui remplacent le
  modèle fourni. Chaque `content_key` doit être un sujet `canonical` ; les entrées
  sont classées par ordre de publication. Elles proviennent de sa
  [banque personnelle EE](https://dot-ear-743.notion.site/2d82e3acbb10809eb5d2c44ed17bccbf?v=3d02e3acbb1080e5878b000c3c0edec0).

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

Le miroir lisible `sujets-documents-2025.md` est également comparé aux fichiers
mensuels ; cinq champs qui avaient dérivé ont été réalignés lors de l'audit final.

## Fidélité des réponses modèles (audit 2026-09, seconde passe)

Les 138 réponses ont été relues face à leurs documents sources. **Aucun texte source
n'a été modifié** ; seules les réponses, leurs comptes de mots et le vocabulaire
associé ont été corrigés.

| Réponse | Correction |
|---|---|
| Janvier — C8 | Synthèse recopiée d'un autre sujet (retards, stress, fatigue) : réécrite à partir des témoignages de Céline et d'Ahmed (temps, choix, 24 h / pollution des livraisons, isolement). |
| Janvier — C10 | Concession contradictoire sur le plastique remplacée par une formulation cohérente sur la mauvaise gestion des déchets. |
| Mars — C6 | Attribution erronée et éléments centraux omis : la synthèse reprend désormais la limite de quinze minutes, le lien familial, le stress, la fatigue et les inégalités. |
| Avril — C7 | Reformulation normative (« chacun doit pouvoir… ») remplacée par le constat factuel du document (accès des femmes aux métiers et postes de direction au Québec). |
| Avril — C10 | Les deux documents sont favorables : opposition (`En revanche`) remplacée par une addition nuancée (`Toutefois`) fidèle à la réserve du second document. |
| Avril — C13 | Suppression d'une fréquence de consommation absente des documents. |
| Mai — C3-bis | Documents identiques : la synthèse inventait un point de vue opposé ; elle signale désormais la duplication. `nécessitent` → `ont besoin d'`. |
| Juin — C2 | Deuxième document absent : la synthèse décrit honnêtement l'unique texte sur les règles de colocation. |
| Juin — C3 | Deuxième document absent : la synthèse inventait une position opposée ; elle résume désormais l'unique témoignage (solidarité ponctuelle et saisonnière). Sujet **non regroupé**. |
| Août — C13 | `de cambrioler` (transitif) → `de préparer un cambriolage`. |
| Novembre — C3 | Registre familier et déformation (`dépannent ceux qui sautent le petit déjeuner`) → `aident ceux qui ne peuvent pas déjeuner le matin`. |
| Novembre — C4 | `hygiène` non attestée : remplacée par les obligations réellement citées (local dédié, matériel adapté, égalité de traitement, prévention du harcèlement). |
| Novembre — C10 | Référent et collocation erronés : `donner aux propriétés` → `donner à leurs quartiers`. |
| Novembre — C12 | Titre normatif corrigé en « Objets connectés : utiles, mais à sécuriser ». |
| Décembre — C6 | Synthèse inventée (logement plus spacieux, loyer réduit) : réécrite à partir des documents réels (repas et jeux partagés, tâches, ouverture / calme perdu, invités subis, tours de ménage). |
| Décembre — C10 | `document1_invalid` : nouveau titre neutre et synthèse honnête fondée sur le seul document valide. |
| Décembre — C14 | `la qualité de programmes jeunesse qui deviennent bénéfiques` → `des programmes jeunesse de qualité, qui deviennent bénéfiques`. |

Étiquettes de comptes recalculées avec `study.content_loader._ee_word_count` : les
138 blocs respectent 40–60 / 80–120 / 120–180 mots. Trois étiquettes `Total` (ou
`Partie 2`) antérieures étaient fausses d'un ou deux mots (Janvier C10, Août C15,
Novembre C8) et ont été corrigées **sans toucher à la prose**.

`author_responses.json` : la réponse « vols à bas prix » était rattachée à Mars C8,
devenu alias ; elle est déplacée sur le sujet canonique Janvier C19. Janvier C3 perd
une concession auto-contradictoire et Janvier C17 ne prétend plus citer
« plusieurs experts » absents des documents.

Vocabulaire : chaque entrée dont l'`example` reprenait une phrase supprimée a été
régénérée à partir du texte corrigé. Les **300 entrées** des dix réponses de l'auteur
proviennent désormais toutes de leur synthèse ou de leur point de vue effectif
(30 entrées par réponse, identifiants inchangés).

## Reproduction

- Les sujets proviennent des pages mensuelles publiques 2025 ; chaque combinaison
  a été dépliée avant extraction et comparée champ par champ.
- `load_ee_tache_three_months`, `load_ee_subject_themes(3)`,
  `load_ee_equivalent_groups(3)`, `parse_ee_tache_three_responses` et
  `parse_ee_tache_three_subject_vocabulary` valident l'alignement, la couverture,
  les limites, les groupes et le vocabulaire avant tout import.
- `study/tests/test_ee_subject_themes.py` et
  `study/tests/test_ee_writing_feature.py` verrouillent les 138 occurrences,
  84 réponses canoniques, 32 groupes et 2 520 entrées importées.
