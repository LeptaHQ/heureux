# EE — Tâche 1 — sujets 2025

Corpus **verbatim** des consignes d'**Expression écrite, Tâche 1** publiées en 2025
(message court : inviter, répondre, décrire, demander ou donner une information).

Le parcours actif s'appuie sur le corpus source 2025 :

- `subjects/<mois>.json` + `sujets-2025.json` / `.md` — corpus **source** 2025,
  recopié tel quel depuis les combinaisons publiées.
- `responses/<theme>.json` — **104 versions** de **60 à 120 mots** pour les
  86 exercices distincts. Les versions `origin: author` viennent de la
  [banque personnelle de l'auteur](https://dot-ear-743.notion.site/2d82e3acbb10809eb5d2c44ed17bccbf?v=3d02e3acbb1080e5878b000c3c0edec0) ;
  les sujets restants ont reçu une réponse originale rédigée dans le même registre.
- `sujets.json` — ancienne banque éditoriale conservée comme référence historique ;
  elle n'alimente plus le parcours 2025.

`load_ee_writing_categories(1)` valide les limites, place les versions de l'auteur
en premier et fournit les 138 publications à l'importeur. Une publication équivalente
conserve sa date et sa consigne, mais partage réponse, personnalisation et progression
avec son sujet canonique.

### Méthodologie appliquée

La [méthodologie EE](https://www.formation-tcfcanada.com/epreuve/expression-ecrite/astuces)
recommande environ **10 minutes** : salutation et registre adaptés, objet et détails
essentiels dans un corps concis, puis formule de fermeture appropriée. Les réponses
respectent la limite 60–120 mots et visent 80–100 mots lorsque la consigne le permet.

## Corpus source 2025

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
  "key": "ee-tache1:janvier:combinaison-1",
  "prompt": "consigne recopiée mot pour mot"
}
```

La clé `key` est l'identifiant stable du sujet. Mai 2025 publiant **deux** panneaux
« Combinaison 3 », le second porte le suffixe `-bis`
(`ee-tache1:mai:combinaison-3-bis`) ; la convention est partagée par les trois tâches,
et les Tâches 1, 2 et 3 d'une même combinaison portent donc la même clé au préfixe près.

## Thèmes et sujets équivalents

- `subject_themes.json` — 11 thèmes (`slug`, `name`, `icon`, `order`) et la table
  `content_key → thème` couvrant **les 138 sujets**. La taxonomie reprend les
  catégories déjà utilisées par `sujets.json`.
- `equivalent_groups.json` — **34 groupes** (86 sujets) republiés d'un mois à
  l'autre sous la même consigne. Les écarts admis sont uniquement éditoriaux
  (`week-end`/`weekend`, abréviation `RDV`, singulier typographique, etc.). Le membre
  `canonical` est toujours le plus ancien du groupe ; un sujet n'appartient qu'à un
  seul groupe et tous les membres partagent son thème.
  **86 sujets distincts** subsistent une fois les doublons regroupés.

| Thème | Slug | Sujets |
|---|---|---|
| Invitations & fêtes | `invitations` | 20 |
| Sorties & visites | `sorties` | 16 |
| Accueillir un invité | `accueil` | 12 |
| Voyages & vacances | `voyages` | 24 |
| Ville & quartier | `ville` | 5 |
| Logement & déménagement | `logement` | 12 |
| Transports & orientation | `transport` | 7 |
| Travail & emploi | `travail` | 12 |
| École & langue | `ecole` | 7 |
| Sport & bien-être | `sport` | 19 |
| Annonces & réclamations | `annonces` | 4 |

Chargement et validation : `load_ee_subject_themes(1)` et
`load_ee_equivalent_groups(1)` dans `study/content_loader.py`. Les règles sont celles
de l'Expression orale Tâche 2 : version 1, identifiants en `kebab-case` uniques, au
moins deux membres, `canonical` le plus ancien, aucun chevauchement entre groupes,
aucun franchissement de thème, et consigne normalisée réellement partagée.

## Reproduction

Les consignes ont été relevées sur les pages mensuelles publiques de la source, chaque
combinaison étant dépliée avant extraction. Le texte est repris **sans modification**
(ponctuation et typographie d'origine comprises).
