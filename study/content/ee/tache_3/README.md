# EE — Tâche 3 — 2025 (sujets, réponses, formulations)

Contenu d'entraînement pour l'**Expression écrite (EE), Tâche 3**.
Ce dossier regroupe les **sujets sources** et l'ensemble des **réponses modèles**,
**formulations**, ainsi que les **mémoires** historiques.

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
- Le titre fait partie de la réponse, de sa copie et du total **titre compris**,
  sans être ajouté au sous-total de la synthèse. Les 138 textes sont des
  contributions autonomes, pas des courriers ; une version personnelle sans
  titre ne reçoit jamais automatiquement celui du modèle.
- Les modèles suivent un squelette stable : « Les deux documents abordent…
  Le premier… De son côté / En revanche, le second… » selon la relation réelle,
  puis « Pour ma part… Tout d’abord… De plus… En conclusion… ». Chacun des deux
  arguments reçoit un appui immédiat : exemple, explication, conséquence,
  condition, comparaison ou preuve brève. Au moins un « Par exemple… » concret
  figure dans chaque Partie 2, sans imposer un second exemple artificiel. Les formulations
  ne remplacent pas l’analyse : un document absent, dupliqué ou hors sujet est
  signalé honnêtement, sans argument inventé.
- Les champs existants `heading` / `reformulation` portent le titre. Le chargeur valide
  40–60 / 80–120 mots séparément, puis 120–180 mots pour le texte complet.
  Les totaux des fichiers mensuels incluent eux aussi leur titre.
- L’affichage du titre et du total reste hors du bloc d’annotation existant :
  les offsets des documents, de la synthèse et du point de vue ne changent pas.
  Aucun identifiant, regroupement, texte personnel, calendrier de révision,
  achèvement, note, surlignage ou instantané historique n’est réécrit.
- `ai_examiner_prompt.md` — prompt d’évaluation propre à la Tâche 3, disponible
  depuis la vue d’ensemble avant de fournir le sujet et ses deux documents.
- Les formulations constituent le parcours principal pour apprendre à construire
  et adapter une réponse.

**Formulations** — `formulations.json`
- **152 fiches**, organisées en **10 fonctions de rédaction** et **11 thèmes** :
  titres, synthèse, affirmation, opposition, concession, conditions, arguments,
  exemples, conséquences et conclusions, puis les thèmes des sujets existants.
- **16 essentiels** enseignent le parcours complet avant l'enrichissement
  thématique. Il s'agit d'une boîte à outils : on ne copie pas toutes les
  formulations dans une seule réponse. Un titre reste un choix adapté au support,
  pas une exigence générale ; une conclusion reprend la position sans argument neuf.
- Le corpus étudié est celui des **78 réponses effectives** renvoyées par
  `parse_ee_tache_three_responses()`, avec les dix remplacements de l'auteur,
  et non les 138 variantes brutes. Chaque réponse fournit au moins un exemple
  substantiel ; la couverture ne repose pas sur des titres quasi identiques.
- Les champs `french`, `usage`, `grammar` et `transfer_prompt` sont rédigés pour
  apprendre à réutiliser un raisonnement. `french` est une formulation adaptée,
  parfois à compléter avec des `[emplacements nommés]`, **pas une citation**.
  `example` cite exactement un titre ou un extrait de synthèse ou de point de vue
  effectif ; `source_key` en conserve la provenance canonique. `english` et
  `example_english` traduisent séparément la formulation et son exemple.
- Les fiches distinguent documents opposés et complémentaires, synthèse neutre
  et avis personnel, exemple plausible et fait démontré. Elles signalent les
  documents absents, dupliqués ou hors sujet sans inventer de preuve. Les bénéfices
  de santé enseignés restent prudents ; les citations de modèles ne sont pas des
  prescriptions médicales. Connaître ces formulations ne garantit aucun score.

### Apprendre à adapter, plutôt qu'à réciter

1. Lire les deux documents et noter leur relation réelle ; sélectionner leur
   thème commun et leurs idées centrales sans ajouter son avis.
2. Choisir une position claire et deux raisons distinctes. Donner à chaque raison
   un appui immédiat : explication, conséquence, condition ou exemple concret.
3. Compléter quelques formulations utiles en respectant les indications de
   grammaire. Vérifier les accords, les référents et le choix entre indicatif,
   subjonctif et infinitif ; supprimer les emplacements avant de terminer.
4. Rédiger un seul texte cohérent : titre éventuel et deux paragraphes, sans
   ajouter de rubriques « synthèse » ou « avis » dans la réponse finale.
   La structure pédagogique ne crée pas de nouveaux titres à copier.
5. Utiliser la consigne de transfert pour un **second contexte**, puis comparer
   son texte au raisonnement et aux précautions de la fiche. Il s'agit d'une
   auto-évaluation, pas d'une correction automatique.

### Format, chargement et identités stables

Le JSON version 1 contient `version`, `source_response_count`, `categories` et
`entries`. `study/ee_formulations.py` expose des dataclasses immuables
`FormulationCategory`, `FormulationEntry` et `FormulationCatalog`, un chargeur
non mis en cache `load_ee_formulations(path=FORMULATIONS_PATH)` et un accès
processus `get_ee_formulations()` avec `cache_clear()`. Le module n'accède ni
à l'ORM ni aux données des apprenants.

Le chargeur valide les types, champs, identifiants, doublons de formulations,
références thématiques, catégories, couverture des réponses et citations
effectives. Seuls les espaces sont normalisés pour comparer les citations :
apostrophes, accents et ponctuation ne sont pas réécrits. Ces contrôles prouvent
la **provenance textuelle**, pas la qualité sémantique d'un argument, d'une
traduction ou d'une consigne ; une relecture éditoriale reste nécessaire.

Une fiche utilise exclusivement la clé
`formulation:ee3:v1:<slug>` (96 caractères maximum). Sa progression peut être
enregistrée dans `MemoryQuestionProgress(memory_number=1, question_key=...)`,
sans migration ni conversion des anciennes fiches. Le numéro `1` ne désigne
pas une reprise du contenu du mémoire 1 : l'espace de clés est distinct.

Le slug identifie une **cible d'apprentissage stable**, pas sa position dans la
liste. Une correction de coquille, d'exemple ou de présentation ne transfère pas
la progression. Si la cible ou l'exercice change de sens, attribuer un **nouveau
slug**, retirer l'ancienne fiche du catalogue actif et ne jamais réutiliser sa
clé pour une autre cible. Les marques apprises et annotations historiques ne
sont ni copiées ni réattribuées. Modifier l'ordre ou la catégorie d'une même
cible n'exige pas une nouvelle clé.

Les réponses, documents sources et règles d'import restent indépendants de ce
nouveau catalogue. Les anciennes URL de mémoires redirigent vers les Formulations :
aucune interface d'archive ni prise en charge spéciale des anciennes notes ou des
surlignages n'est ajoutée.

**Mémoires** — `memoires/memoire_<Q>.json`
- **4 mémoires trimestrielles** de formulations réutilisables, calquées sur la structure
  des mémoires de l'Expression orale Tâche 2 (`tache_2/master_question_bank*.json`) :
  Q1 = janvier+mars · Q2 = avril+mai+juin · Q3 = juillet+août+septembre · Q4 = octobre+novembre+décembre.

**Archive source : 138 sujets → 138 blocs de réponse → 4 mémoires
(1 286 formulations).**
*Février 2025 : aucune page publiée sur la source.*

Après regroupement des republications (`equivalent_groups.json`), l'application expose
**78 réponses distinctes** pour **138 sujets datés**, accompagnées des **152
formulations**.

| Mois | Sujets/Réponses |
|---|---|
| Janvier | 15 |
| Mars | 14 |
| Avril | 20 |
| Mai | 8 |
| Juin | 5 |
| Juillet | 19 |
| Août | 16 |
| Septembre | 6 |
| Octobre | 4 |
| Novembre | 12 |
| Décembre | 19 |
| **Total** | **138** |

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

Chaque sujet de Tâche 3 comprend normalement un **titre-débat** et **deux documents**.
Leurs positions peuvent être opposées, complémentaires ou nuancées. Le champ
`opinion` (pour/contre) de la source, peu fiable, n'est pas repris : la relation
entre les textes ressort de leur contenu.

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
- `equivalent_groups.json` — **35 groupes** couvrant **95 sujets** que la source a
  republiés à l'identique ou paraphrasés ; les 138 sujets datés se ramènent donc à **78 réponses
  distinctes**. Pour la Tâche 3, l'identité d'un sujet est celle de ses **deux
  documents** : le titre est éditorial et varie d'un mois à l'autre (« Vivre en
  colocation » / « Vivre En Colocation : Pour Ou Contre ? »). La comparaison des
  documents est **insensible à leur ordre** (la source les intervertit parfois) et
  tolère une dérive typographique auditée (similarité ≥ 0,93). Les paraphrases plus
  importantes exigent un champ `audit` avec justification et empreintes SHA-256
  des signatures normalisées de chaque paire. Une modification de fond invalide
  ces empreintes et exige une nouvelle revue. Le membre `canonical`
  est toujours le plus ancien du groupe. Mêmes règles de validation que l'Expression
  orale Tâche 2.
- `author_responses.json` — **10 réponses rédigées par l'auteur** qui remplacent le
  modèle fourni. Chaque `content_key` doit être un sujet `canonical` ; les entrées
  sont classées par ordre de publication. Elles proviennent de sa
  [banque personnelle EE](https://dot-ear-743.notion.site/2d82e3acbb10809eb5d2c44ed17bccbf?v=3d02e3acbb1080e5878b000c3c0edec0).

L'audit d'équivalence de septembre 2026 porte sur les 138 sujets et leurs 276
champs documentaires, dont deux vides. Il ajoute trois groupes (restauration rapide
et obésité, bureaux réglables, objets connectés) et étend trois groupes (caméras
à l'école, réduction du temps de travail, restauration rapide et déchets plastiques).
Les fichiers sources, les 138 modèles archivés et les dix réponses de l'auteur
restent inchangés. Les 180 fiches supplémentaires devenues alias utilisent le
mécanisme existant de rapprochement des calendriers de révision.

Seules les paires complètes sont comparées : les sujets de livraison de repas
qui partagent un seul document restent indépendants. Les variantes dont les
statistiques, les arguments ou les réserves changent ne sont pas liées sur la
seule base d'un titre commun (jeux vidéo, sieste au travail, musées gratuits,
produits faits maison, etc.).

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
(Partie 1) de ces deux réponses ont été réécrites pour coller aux documents réels.
Novembre C2 retrouve son titre source (« Les bureaux électriques »).

Le miroir lisible `sujets-documents-2025.md` est également comparé aux fichiers
mensuels ; cinq champs qui avaient dérivé ont été réalignés lors de l'audit final.

## Fidélité des réponses modèles (audit 2026-09, seconde passe)

Les 138 réponses ont été relues face à leurs documents sources. **Aucun texte source
n'a été modifié** ; seules les réponses et leurs comptes de mots ont été corrigés.

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
« plusieurs experts » absents des documents. Les dix réponses effectives utilisent
désormais le même squelette à deux arguments soutenus que le reste du corpus,
tout en conservant leurs idées propres.

## Reproduction

- Les sujets proviennent des pages mensuelles publiques 2025 ; chaque combinaison
  a été dépliée avant extraction et comparée champ par champ.
- `load_ee_tache_three_months`, `load_ee_subject_themes(3)`,
  `load_ee_equivalent_groups(3)` et `parse_ee_tache_three_responses` valident
  l'alignement, la couverture, les limites et les groupes avant tout import.
- `study/tests/test_ee_subject_themes.py` et
  `study/tests/test_ee_writing_feature.py` verrouillent les 138 occurrences,
  78 réponses canoniques et 35 groupes.
- `study/tests/test_ee_tache_three_titles.py` vérifie le titre dans la réponse
  et sa copie, les totaux complets et la conservation des données à la réimportation.
- `study/tests/test_ee_formulations_loader.py` couvre le contrat immuable,
  le cache, les erreurs de schéma, les références et l'ancrage textuel effectif.
  `study/tests/test_ee_formulations_content.py` verrouille les 152 fiches,
  21 catégories, 16 essentiels, 78 sources effectives et les empreintes des quatre
  mémoires historiques. Ces tests structurels ne remplacent pas la relecture
  du français, des traductions ni de la pertinence pédagogique.
