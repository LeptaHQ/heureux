/* Adaptive examiner for TCF Canada EO Tâche 1 practice: entretien dirigé, 2 minutes,
   sans préparation, with an examiner the candidate does not know. All questions are
   original. The engine is stateless: each decision is rebuilt from the turns passed in. */
(function (root, factory) {
  "use strict";
  var engine = factory();
  if (typeof module === "object" && module.exports) module.exports = engine;
  if (root) root.HeureuxEO1Engine = engine;
}(typeof window === "object" ? window : null, function () {
  "use strict";

  var CLOSING_SECONDS = 25;
  var LATE_SECONDS = 60;
  var SHORT_ANSWER_WORDS = 5;

  function q(text, simple, extra) {
    return Object.assign({ text: text, simple: simple }, extra || {});
  }

  // Wording avoids gendered agreement with « vous »: the examiner does not know the candidate.
  var OPENING_FRAMES = [
    "Bonjour. Nous allons commencer par un court entretien.",
    "Bonjour, installez-vous. Nous allons d'abord faire connaissance.",
    "Bonjour. Je vais vous poser quelques questions sur votre vie de tous les jours.",
    "Bonjour. Pour commencer, nous allons discuter un peu ensemble."
  ];

  var PRESENTATION = {
    id: "presentation",
    opening: [
      q("Pouvez-vous vous présenter, s'il vous plaît ?",
        "Dites-moi simplement qui vous êtes, où vous vivez et ce que vous faites."),
      q("Pourriez-vous vous présenter en quelques mots ?",
        "Présentez-vous simplement : votre prénom, votre ville, votre activité."),
      q("Parlez-moi un peu de vous, s'il vous plaît.",
        "Qui êtes-vous ? Parlez-moi de votre vie en quelques phrases.")
    ],
    follow: [
      q("Et qu'est-ce qui occupe la plus grande partie de vos journées en ce moment ?",
        "En ce moment, vous travaillez, vous étudiez, ou vous faites autre chose ?",
        { sense: "journees", covers: ["activite"] }),
      q("Comment vos proches vous décriraient-ils en quelques mots ?",
        "Si on demande à vos amis comment vous êtes, que disent-ils ?"),
      q("Qu'est-ce qui compte le plus pour vous dans la vie de tous les jours ?",
        "Dans votre vie de tous les jours, qu'est-ce qui est important pour vous ?")
    ]
  };

  var TOPICS = [
    { id: "lieu",
      primary: [
        q("Pouvez-vous me décrire l'endroit où vous habitez ?",
          "Vous habitez où ? C'est une grande ville, un village ? Comment est-ce ?"),
        q("Comment est la ville ou le quartier où vous vivez ?",
          "Votre ville ou votre quartier, c'est calme, animé, agréable ?")
      ],
      follow: [
        q("Qu'est-ce qui vous plaît le plus près de chez vous ?",
          "Près de chez vous, qu'est-ce que vous aimez : les commerces, les parcs, les voisins ?",
          { sense: "lieu-plaisir" }),
        q("Et s'il y avait une chose à changer dans votre quartier, ce serait laquelle ?",
          "Dans votre quartier, qu'est-ce qui ne vous plaît pas ?", { tense: "hypothese" }),
        q("Depuis combien de temps vivez-vous à cet endroit ?", "Vous habitez là depuis quand ?")
      ] },
    { id: "quotidien",
      primary: [
        q("À quoi ressemble une journée ordinaire pour vous ?",
          "Le matin, l'après-midi, le soir : que faites-vous pendant une journée normale ?"),
        q("Comment se passe une semaine habituelle pour vous ?",
          "Du lundi au dimanche, que faites-vous en général ?")
      ],
      follow: [
        q("Quel est votre moment préféré de la journée, et pourquoi ?",
          "À quel moment de la journée vous sentez-vous le mieux ?"),
        q("Et le week-end, votre rythme change-t-il beaucoup ?",
          "Le week-end, que faites-vous de différent ?", { sense: "weekend" }),
        q("Comment vous déplacez-vous au quotidien ?",
          "Pour vos trajets, vous prenez le bus, la voiture, le vélo, ou vous marchez ?",
          { sense: "trajets" })
      ] },
    { id: "activite",
      primary: [
        q("Que faites-vous dans la vie en ce moment ?",
          "En ce moment, vous avez un travail, vous suivez des études, ou autre chose ?"),
        q("Pouvez-vous me parler de votre activité principale : travail, études ou autre ?",
          "Qu'est-ce que vous faites la plupart du temps : un travail, des études, autre chose ?")
      ],
      follow: [
        q("Qu'est-ce qui vous plaît le plus dans cette activité ?",
          "Dans ce que vous faites, qu'est-ce que vous aimez ?", { sense: "activite-plaisir" }),
        q("Et qu'est-ce qui est le plus difficile dans ce que vous faites ?",
          "Dans votre activité, qu'est-ce qui n'est pas facile ?"),
        q("Dans quelques années, aimeriez-vous continuer ainsi ou changer quelque chose ?",
          "Dans quelques années, vous voulez faire la même chose ou changer ?", { tense: "futur" })
      ] },
    { id: "entourage",
      primary: [
        q("Avec qui passez-vous le plus de temps en général ?",
          "Vous passez votre temps avec qui : votre famille, des amis, des collègues ?"),
        q("Pouvez-vous me parler des personnes qui comptent pour vous ?",
          "Qui sont les personnes importantes dans votre vie ?")
      ],
      follow: [
        q("Qu'est-ce que vous aimez faire ensemble ?",
          "Avec ces personnes, que faites-vous ensemble ?", { sense: "ensemble" }),
        q("Comment restez-vous en contact avec vos proches au quotidien ?",
          "Vous parlez avec vos proches comment : par téléphone, par messages, en personne ?")
      ] },
    { id: "loisirs",
      primary: [
        q("Que faites-vous pendant votre temps libre ?",
          "Quand vous avez du temps pour vous, qu'est-ce que vous aimez faire ?"),
        q("Comment aimez-vous vous détendre après une longue journée ?",
          "Après une journée fatigante, que faites-vous pour vous reposer ?"),
        q("Avez-vous une passion ou un passe-temps qui compte beaucoup pour vous ?",
          "Qu'est-ce que vous aimez beaucoup faire : du sport, de la musique, de la cuisine, autre chose ?")
      ],
      follow: [
        q("Partagez-vous ces moments avec d'autres personnes ?",
          "Vous faites cela de votre côté ou avec d'autres personnes ?"),
        q("Si vous aviez une journée entièrement libre demain, que feriez-vous ?",
          "Imaginez : demain, vous êtes libre toute la journée. Qu'est-ce que vous faites ?",
          { tense: "hypothese" }),
        q("Y a-t-il une activité que vous aimeriez essayer un jour ?",
          "Quelle nouvelle activité voudriez-vous commencer ?")
      ] },
    { id: "langues",
      primary: [
        q("Quelles langues parlez-vous, et dans quelles situations ?",
          "Vous parlez quelles langues ? Avec qui, et où ?"),
        q("Comment le français est-il entré dans votre vie ?",
          "Quand et comment avez-vous commencé à apprendre le français ?", { tense: "passe" })
      ],
      follow: [
        q("Qu'est-ce qui vous semble le plus difficile en français ?",
          "En français, qu'est-ce qui est difficile pour vous : la prononciation, la grammaire, le vocabulaire ?",
          { sense: "francais-difficile" }),
        q("Dans quelles situations utilisez-vous le français en ce moment ?",
          "En ce moment, vous parlez français où, et avec qui ?"),
        q("Comment faites-vous pour retenir le nouveau vocabulaire ?",
          "Quand vous apprenez un nouveau mot, comment faites-vous pour vous en souvenir ?")
      ] },
    { id: "cuisine",
      primary: [
        q("Quelle place la cuisine a-t-elle dans votre quotidien ?",
          "Vous cuisinez souvent ? Qu'est-ce que vous préparez ?"),
        q("Quel est votre plat préféré, et à quelle occasion le mangez-vous ?",
          "Quel plat aimez-vous beaucoup ? Quand est-ce que vous le mangez ?")
      ],
      follow: [
        q("Préférez-vous manger chez vous ou à l'extérieur ? Pourquoi ?",
          "Vous mangez plutôt à la maison ou au restaurant ?"),
        q("Y a-t-il un repas qui vous rappelle un bon souvenir ?",
          "Quel repas vous fait penser à un moment heureux ?", { tense: "passe" })
      ] },
    { id: "voyages",
      primary: [
        q("Quel endroit avez-vous aimé découvrir, en voyage ou près de chez vous ?",
          "Quel lieu avez-vous visité et beaucoup aimé ?", { tense: "passe" }),
        q("Où aimez-vous aller quand vous avez quelques jours de congé ?",
          "Pendant les vacances, où aimez-vous aller ?")
      ],
      follow: [
        q("Quel souvenir gardez-vous de cet endroit ?",
          "De cet endroit, de quoi vous souvenez-vous ?", { tense: "passe" }),
        q("Comment aimez-vous voyager : avec un programme précis ou au jour le jour ?",
          "En voyage, vous préparez tout à l'avance, ou vous décidez sur place ?")
      ] },
    { id: "projets", late: true,
      primary: [
        q("Quels sont vos projets pour les prochains mois ?",
          "Qu'est-ce que vous voulez faire dans les prochains mois ?", { tense: "futur" }),
        q("Qu'aimeriez-vous réaliser dans les prochaines années ?",
          "Dans quelques années, qu'est-ce que vous voulez faire ?", { tense: "futur" })
      ],
      follow: [
        q("Et dans les prochaines semaines, avez-vous quelque chose de prévu ?",
          "Qu'est-ce que vous allez faire ces prochaines semaines ?", { tense: "futur" }),
        q("Qu'est-ce que vous aimeriez apprendre de nouveau ?",
          "Quelle chose nouvelle voulez-vous apprendre ?")
      ] },
    { id: "souvenirs",
      primary: [
        q("Pouvez-vous me parler de l'endroit où vous avez grandi ?",
          "Où avez-vous passé votre enfance ? C'était comment ?", { tense: "passe" }),
        q("Quel bon souvenir d'enfance vous revient souvent ?",
          "Racontez-moi un bon souvenir de votre enfance.", { tense: "passe" })
      ],
      follow: [
        q("Qu'est-ce qui a le plus changé dans votre vie depuis cette époque ?",
          "Entre votre enfance et aujourd'hui, qu'est-ce qui est différent ?", { tense: "passe" }),
        q("Gardez-vous des habitudes de cette période ?",
          "Est-ce que vous faites encore des choses comme quand vous étiez enfant ?")
      ] }
  ];

  // Patterns run on folded text (lowercase, no accents, straight apostrophes).
  var HOOKS = [
    { id: "nuit", topic: "activite", specific: true,
      pattern: /\bje travaille (?:souvent |surtout )?(?:de nuit|la nuit)\b/,
      questions: [
        q("Comment organisez-vous votre journée après une nuit de travail ?",
          "Quand vous rentrez du travail le matin, que faites-vous ?")
      ] },
    { id: "retour-a-pied", topic: "quotidien", specific: true,
      pattern: /\bje rentre (?:souvent |toujours )?a pied\b/,
      questions: [
        q("Quand vous rentrez à pied, par où aimez-vous passer ?",
          "Quel chemin prenez-vous à pied pour rentrer ?", {sense:"trajets"})
      ] },
    { id: "trajet-velo", topic: "quotidien", specific: true,
      pattern: /\b(?:je vais (?:au travail|au bureau|en cours) (?:a|en) velo|je (?:prends|fais) (?:mon|du) velo pour (?:aller|me rendre) (?:au travail|au bureau|en cours))\b/,
      questions: [
        q("Comment se passe votre trajet à vélo ?",
          "À vélo, quel chemin prenez-vous d’habitude ?", {sense:"trajets"})
      ] },
    { id: "debut-poste", topic: "activite", specific: true,
      pattern: /\bje viens (?:de commencer|de prendre) (?:un|mon) (?:nouveau )?(?:poste|emploi|travail)\b/,
      questions: [
        q("Qu’est-ce qui vous a surpris pendant vos premiers jours à ce poste ?",
          "Au début, qu’est-ce qui était nouveau pour vous dans ce travail ?")
      ] },
    { id: "apprentissage-seul", topic: "langues", specific: true,
      pattern: /\bj[' ](?:apprends|ai appris) le francais (?:tout[e]? seul[e]?|en autodidacte|par moi-meme)\b/,
      questions: [
        q("Sans professeur, comment choisissez-vous ce que vous allez travailler ?",
          "Quand vous étudiez de votre côté, comment choisissez-vous un exercice ?")
      ] },
    { id: "famille", topic: "entourage",
      pattern: /\b(mon|ma|mes|notre|nos) (mari|femme|epouse|epoux|conjoint|conjointe|partenaire|enfants?|fils|filles?|bebe|parents|pere|mere|freres?|s(?:oe|œ)urs?|famille|grands-parents|grand-mere|grand-pere|petits-enfants)\b/,
      questions: [
        q("Et votre famille, qu'aimez-vous faire ensemble quand vous en avez l'occasion ?",
          "Avec votre famille, que faites-vous ensemble, par exemple le week-end ?", { sense: "ensemble" }),
        q("À quelle fréquence voyez-vous votre famille, et à quelles occasions ?",
          "Vous voyez votre famille souvent ? Quand ?")
      ] },
    { id: "amis", topic: "entourage",
      pattern: /\b(mes|des|nos|entre) (amis|amies|copains|copines)\b|\bmeilleure? amie?\b/,
      questions: [
        q("Comment avez-vous rencontré vos amis les plus proches ?",
          "Où avez-vous connu vos amis : à l'école, au travail, ailleurs ?", { tense: "passe" }),
        q("Qu'est-ce que vous aimez faire avec vos amis ?",
          "Avec vos amis, que faites-vous ensemble ?", { sense: "ensemble" })
      ] },
    { id: "travail", topic: "activite",
      pattern: /\b(je travaille|mon travail|mon boulot|mon emploi|mon poste|mon metier|mes collegues|mon entreprise|mon employeur|je suis (employee?|salariee?|fonctionnaire|enseignante?|professeure?|infirmiere?|infirmier|ingenieure?|medecin|developpeur|developpeuse|comptable|technicienne?|vendeur|vendeuse|chauffeur|cuisiniere?|cuisinier|serveur|serveuse|avocate?|architecte|pharmacienne?|informaticienne?|commercante?|caissiere?|caissier|secretaire|consultante?|analyste|journaliste|electricienne?|plombier|mecanicienne?|aide-soignante?|educateur|educatrice|gestionnaire|directeur|directrice|ouvriere?|ouvrier|designer|chercheur|chercheuse|traducteur|traductrice|coiffeur|coiffeuse|boulangere?|boulanger))\b/,
      questions: [
        q("Et dans votre travail, qu'est-ce qui vous plaît le plus ?",
          "Qu'est-ce que vous aimez dans votre travail : les collègues, les tâches, autre chose ?",
          { sense: "activite-plaisir" }),
        q("Pouvez-vous me décrire une journée de travail habituelle ?",
          "Que faites-vous pendant une journée de travail, du matin au soir ?")
      ] },
    { id: "occupation", topic: "quotidien", negatable: false,
      pattern: /\b(a la retraite|retraitee?|au chomage|sans emploi|je cherche (du|un) (travail|emploi|job|poste)|en recherche d'emploi|je ne travaille (pas|plus)|je reste a la maison|au foyer)\b/,
      questions: [
        q("Comment organisez-vous vos journées en ce moment ?",
          "En ce moment, que faites-vous pendant une journée normale ?",
          { sense: "journees", covers: ["activite"] }),
        q("Quelles activités vous tiennent à cœur en ce moment ?",
          "En ce moment, qu'est-ce que vous aimez faire ?", { covers: ["activite"] })
      ] },
    { id: "etudes", topic: "activite",
      pattern: /\b(j'etudie|je suis etudiante?|mes etudes|l'universite|la fac|mon diplome|ma formation|mon master|ma licence|mon doctorat|le cegep|au cegep|je fais des etudes)\b/,
      questions: [
        q("Qu'est-ce qui a motivé votre choix d'études ?",
          "Pourquoi avez-vous choisi ces études ?", { tense: "passe" }),
        q("Qu'est-ce que ces études vous ont apporté jusqu'ici ?",
          "Qu'avez-vous appris d'important pendant ces études ?", { tense: "passe" })
      ] },
    { id: "francais", topic: "langues",
      pattern: /\b(cours de francais|apprends le francais|apprendre le francais|appris le francais|ameliorer mon francais|pratiquer (le|mon) francais|j'etudie le francais|mon francais|parler francais)\b/,
      questions: [
        q("Qu'est-ce qui vous aide le plus à progresser en français ?",
          "Comment apprenez-vous le français : avec des cours, des films, des amis ?"),
        q("En français, qu'est-ce qui vous donne le plus de mal ?",
          "Qu'est-ce qui est compliqué pour vous en français ?", { sense: "francais-difficile" })
      ] },
    { id: "sport", topic: "loisirs",
      pattern: /\b(le sport|du sport|un sport|sportif|sportive|football|foot|soccer|basket|basketball|volley|tennis|badminton|natation|je nage|nager|courir|je cours|course a pied|jogging|footing|gym|salle de sport|musculation|yoga|pilates|boxe|karate|judo|danse|je danse|danser|du velo|hockey|ski|patinage|rugby|cricket|marathon)\b/,
      questions: [
        q("Et cette activité physique, quelle place a-t-elle dans votre semaine ?",
          "Vous faites cette activité combien de fois par semaine, et où ?"),
        q("Qu'est-ce que cette activité vous apporte au quotidien ?",
          "Pourquoi aimez-vous cette activité ? Qu'est-ce qu'elle vous apporte ?")
      ] },
    { id: "lecture", topic: "loisirs",
      pattern: /\b(lire|je lis|lecture|livres?|romans?|bandes? dessinees?|mangas?|poesie|bibliotheque)\b/,
      questions: [
        q("Y a-t-il un livre qui vous a particulièrement marqué ?",
          "Quel livre avez-vous beaucoup aimé, et pourquoi ?", { tense: "passe" }),
        q("À quel moment de la journée aimez-vous lire ?",
          "Vous lisez plutôt le matin, le soir, dans les transports ?")
      ] },
    { id: "musique", topic: "loisirs",
      pattern: /\b(musique|musicien|musicienne|chanter|je chante|chansons?|chorale|guitare|piano|violon|concerts?|instrument)\b/,
      questions: [
        q("Quelle place la musique a-t-elle dans votre quotidien ?",
          "Quand écoutez-vous ou faites-vous de la musique dans la journée ?"),
        q("Quel genre de musique vous accompagne en ce moment ?",
          "En ce moment, quelle musique écoutez-vous ?")
      ] },
    { id: "ecrans", topic: "loisirs",
      pattern: /\b(films?|series?|cinema|netflix|television|tele|documentaires?)\b/,
      questions: [
        q("Quel est le dernier film ou la dernière série qui vous a plu ?",
          "Récemment, quel film ou quelle série vous a plu ?", { tense: "passe" }),
        q("Préférez-vous regarder des films chez vous ou au cinéma ?",
          "Vous regardez des films à la maison ou au cinéma ?")
      ] },
    { id: "cuisiner", topic: "cuisine",
      pattern: /\b(cuisiner|je cuisine|la cuisine|faire a manger|recettes?|patisseries?|gateaux?)\b/,
      questions: [
        q("Quel plat préparez-vous le plus volontiers ?", "Qu'est-ce que vous aimez cuisiner ?"),
        q("Qui vous a appris à cuisiner ?", "Avec qui avez-vous appris à cuisiner ?", { tense: "passe" })
      ] },
    { id: "voyage", topic: "voyages",
      pattern: /\b(voyager|voyages?|je voyage|visiter|tourisme)\b/,
      questions: [
        q("Quel voyage vous a laissé le meilleur souvenir ?",
          "Quel est votre meilleur souvenir de voyage ?", { tense: "passe" }),
        q("Où aimeriez-vous partir lors de votre prochain voyage ?",
          "Quel pays ou quelle ville voulez-vous visiter bientôt ?", { tense: "hypothese" })
      ] },
    { id: "nature", topic: "loisirs",
      pattern: /\b(la nature|en nature|randonnees?|montagne|la plage|la mer|foret|a la campagne|camping|jardin|jardiner|jardinage|peche|parcs?)\b/,
      questions: [
        q("Qu'est-ce que vous aimez faire quand vous êtes au grand air ?",
          "Dehors, dans la nature, que faites-vous : marcher, vous reposer, autre chose ?"),
        q("Y a-t-il un endroit en plein air où vous aimez aller souvent ?",
          "Quel endroit dehors aimez-vous beaucoup : un parc, une plage, une forêt ?")
      ] },
    { id: "animaux", topic: "quotidien",
      pattern: /\b(mon|ma|mes|notre|nos) (chien|chienne|chiens|chat|chatte|chats|animal|animaux|lapin|oiseau|perroquet|poissons?|cheval)\b/,
      questions: [
        q("Qu'est-ce qu'un animal apporte dans votre quotidien ?",
          "Pourquoi aimez-vous avoir un animal ?")
      ] },
    { id: "benevolat", topic: "loisirs",
      pattern: /\b(benevoles?|benevolat)\b/,
      questions: [
        q("Qu'est-ce que cet engagement bénévole vous apporte ?",
          "Pourquoi aimez-vous aider comme bénévole ?"),
        q("Comment avez-vous commencé à faire du bénévolat ?",
          "Le bénévolat, vous avez commencé comment ?", { tense: "passe" })
      ] },
    { id: "arrivee", topic: "lieu",
      pattern: /\b(demenagee?s?|je suis arrivee?|nous sommes arrives|on est arrives|immigree?|me suis installee?|nous nous sommes installes|depuis mon arrivee)\b/,
      questions: [
        q("Quelle a été votre première impression à votre arrivée ?",
          "Au début, comment avez-vous trouvé votre nouvelle vie ?", { tense: "passe" }),
        q("Qu'est-ce qui a été le plus difficile au moment de changer de cadre de vie ?",
          "Au début, qu'est-ce qui était difficile pour vous ?", { tense: "passe" })
      ] },
    { id: "changement", topic: "projets",
      pattern: /\b(demenager|immigrer|emigrer|m'installer|partir vivre|aller vivre|m'expatrier)\b/,
      questions: [
        q("Pourquoi avez-vous envie de ce changement ?",
          "Qu'est-ce qui vous attire dans ce projet ?"),
        q("Comment vous préparez-vous à ce changement ?",
          "Qu'est-ce que vous faites pour préparer ce changement ?")
      ] },
    { id: "logement", topic: "lieu",
      pattern: /\b(mon appartement|mon appart|ma maison|mon logement|mon studio|une colocation|en colocation|mes colocataires)\b/,
      questions: [
        q("Comment décririez-vous votre logement ?",
          "Votre logement est comment : grand, petit, calme, lumineux ?"),
        q("Qu'est-ce que vous appréciez le plus chez vous ?",
          "Chez vous, quelle est votre pièce préférée ?")
      ] },
    { id: "quartier", topic: "lieu",
      pattern: /\b(mon quartier|le quartier|mes voisins|mes voisines|ma rue)\b/,
      questions: [
        q("Qu'est-ce qui vous plaît le plus dans votre quartier ?",
          "Dans votre quartier, qu'est-ce que vous aimez ?", { sense: "lieu-plaisir" }),
        q("Comment sont vos relations avec vos voisins ?",
          "Vous parlez souvent avec vos voisins ?")
      ] },
    { id: "transports", topic: "quotidien",
      pattern: /\b(en bus|le bus|l'autobus|en metro|le metro|en train|le train|en tramway|le tram|en voiture|ma voiture|a velo|en velo|a pied|les transports|en transport|covoiturage)\b/,
      questions: [
        q("Comment se passent vos trajets au quotidien ?",
          "Chaque jour, vous vous déplacez comment, et combien de temps ça prend ?",
          { sense: "trajets" })
      ] }
  ];

  var QUICK = [
    q("Êtes-vous plutôt du matin ou du soir ?", "Vous préférez le matin ou le soir ?"),
    q("Quelle est votre saison préférée, et pourquoi ?", "Vous aimez quelle saison ?"),
    q("Préférez-vous la ville ou la campagne ?", "Pour vivre, vous aimez mieux la ville ou la campagne ?"),
    q("Qu'est-ce qui vous fait sourire dans une journée ordinaire ?",
      "Dans votre journée, qu'est-ce qui vous fait plaisir ?"),
    q("Le matin, vous prenez plutôt du thé ou du café ?", "Vous buvez du thé, du café, ou autre chose ?"),
    q("Quel est le dernier moment agréable que vous avez vécu ?",
      "Récemment, qu'est-ce qui vous a fait plaisir ?", { tense: "passe" }),
    q("Qu'est-ce que vous aimez faire le dimanche ?", "Le dimanche, que faites-vous ?", { sense: "weekend" })
  ];

  var ELABORATE = [
    q("Pouvez-vous m'en dire un peu plus ?", "Pouvez-vous donner plus de détails ?"),
    q("Pouvez-vous développer un peu votre réponse ?", "Expliquez un peu plus, s'il vous plaît."),
    q("Ah oui ? Racontez-moi un peu.", "Vous pouvez raconter un peu plus ?")
  ];

  var PROBES = [
    q("Vous pouvez me raconter un moment où vous avez ressenti cela ?",
      "Vous pensez à quel moment, par exemple ?", {cue: /\b(?:ca me plait|j'apprecie|ce que j'aime|j'adore|je me sens)\b/}),
    q("Et concrètement, qu’est-ce qui est différent pour vous maintenant ?",
      "Qu’est-ce qui a changé dans votre journée ?", {cue: /\b(?:avant je|contrairement a avant|depuis ce changement|maintenant je|auparavant)\b/}),
    q("Quel exemple vous vient à l’esprit ?",
      "Vous avez un exemple ?", {cue: /\b(?:parce qu|ce qui|car |puisque|c'est pour)/}),
  ];

  var FALLBACK = [
    q("Y a-t-il autre chose que vous aimeriez me dire sur vous ?",
      "Voulez-vous ajouter quelque chose sur vous ?")
  ];

  var ACK = ["D'accord.", "Très bien.", "Je vois.", "Merci.", "Entendu."];
  var TRANSITION = ["Changeons de sujet.", "Parlons d'autre chose.", "Passons à un autre thème.",
    "J'aimerais vous poser une autre question."];
  var CALLBACK = ["Revenons à ce que vous disiez tout à l'heure.",
    "Vous en avez parlé tout à l'heure."];
  var PREFIX = {
    repeat: ["Bien sûr.", "Oui, bien sûr.", "Je répète la question."],
    rephrase: ["Je reformule.", "Je vais le dire autrement.", "Je pose la question autrement."],
    dontknow: ["Ce n'est pas grave.", "Ce n'est pas un problème.", "Prenez un exemple simple."],
    moveOn: ["Ce n'est pas grave, passons à autre chose.", "Aucun problème, changeons de sujet."],
    switch: ["Bien sûr, parlons d'autre chose.", "D'accord, changeons de sujet.",
      "Pas de problème, passons à un autre thème."]
  };

  // Learner requests are only recognised in short answers, so content that merely
  // contains « répéter » or « comprendre » keeps its normal follow-up.
  var META = [
    { kind: "switch", maxWords: 20, patterns: [
      /\b(changer|change|changeons|changez) (de|d') ?(sujet|question|theme)\b/,
      /\bparler d'autre chose\b|\bune autre question\b|\bautre sujet\b/,
      /\b(prefere|prefererais|aimerais mieux|voudrais|souhaite|souhaiterais) (ne )?pas (en )?(parler|repondre)\b/,
      /\b(veux|souhaite|peux) pas (en )?parler\b|\bpas envie d'en parler\b/,
      /\bc'est (trop |un peu |assez )?(personnel|prive)\b/,
      /\b(next question|another question|change the subject|rather not)\b/] },
    { kind: "unclear", maxWords: 14, patterns: [
      /\b(pas|mal) (bien |tres bien |tout )?compris\b/,
      /\bcomprends pas\b|\bpas sure? de (bien )?comprendre\b/,
      /\bqu'est-ce que (ca|cela|ce mot) veut dire\b|\bque (voulez|veut)[- ]vous dire\b/,
      /\bc'est[- ]a[- ]dire\b|\bc'est quoi\b/,
      /\b(i don't understand|i didn't understand|what do you mean)\b/] },
    { kind: "repeat", maxWords: 14, patterns: [
      /\b(pouvez|pourriez|peux|pourrais|voulez|voudriez)[- ]?(vous|tu)? ?(la |le )?(repeter|redire)\b/,
      /\b(repetez|redites)\b|\brepeter\b.*\b(question|s'il vous plait|svp|encore)\b/,
      /\bencore une fois\b|\bplus lentement\b/,
      /^(euh |oh )?(pardon|comment|quoi|hein|excusez[- ]moi|desolee?)( (madame|monsieur))?[\s?!.,]*$/,
      /\b(sorry|repeat|come again|say that again)\b/] },
    { kind: "dontknow", maxWords: 6, patterns: [
      /\bsais (pas|rien)( (trop|vraiment|du tout|encore))?[\s.!?,…]*$/,
      /\baucune idee\b|\bj'en sais rien\b|^(euh,? )?bof\b|\bi don't know\b/] }
  ];
  var HELP_KINDS = { repeat: true, unclear: true, dontknow: true };
  var BARE_NEGATIVE = /^(non|pas vraiment|pas du tout|pas trop|jamais|non,? pas vraiment|non,? jamais)[\s.!]*$/;
  var NEGATION = /\b(ne|n|pas|jamais|aucun|aucune|ni|sans|rien)\b/;

  var CONNECTORS = [
    ["parce que", /\bparce qu/], ["car", /\bcar\b/], ["mais", /\bmais\b/],
    ["par exemple", /\bpar exemple\b/], ["donc", /\bdonc\b/], ["pourtant", /\bpourtant\b/],
    ["cependant", /\bcependant\b/], ["d'abord", /\bd'abord\b/], ["ensuite", /\bensuite\b/],
    ["en plus", /\ben plus\b/], ["alors", /\balors\b/], ["grâce à", /\bgrace a(ux?)?\b/], ["c'est pourquoi", /\bc'est pourquoi\b/]
  ];
  var OVERUSED = {
    tres: ["très", "« vraiment », « particulièrement » ou une précision concrète"],
    beaucoup: ["beaucoup", "« énormément », « souvent » ou une fréquence précise"],
    vraiment: ["vraiment", "« tout à fait », « réellement » ou un exemple"],
    donc: ["donc", "« alors », « c'est pour cela que » ou une phrase plus courte"],
    aussi: ["aussi", "« également », « en plus » ou « de plus »"],
    euh: ["euh", "« en fait… », « disons… » ou une courte pause silencieuse"],
    voila: ["voilà", "une phrase de conclusion, par exemple « c'est ce qui compte pour moi »"]
  };
  var TENSES = {
    passe: ["le passé", "le passé composé pour les événements et l'imparfait pour les descriptions"],
    futur: ["l'avenir", "le futur proche (« je vais… ») ou le futur simple (« je ferai… »)"],
    hypothese: ["une situation imaginaire", "le conditionnel (« je ferais », « j'irais »)"]
  };

  // ---- Text helpers --------------------------------------------------------------

  function foldChar(ch) {
    if (ch === "\u2019" || ch === "\u2018" || ch === "\u02bc") return "'";
    var folded = ch.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    return folded.length === 1 ? folded : ch;
  }
  // Index-preserving fold, so matches can be quoted from the learner's original text.
  function fold(text) { return String(text || "").split("").map(foldChar).join(""); }
  function key(text) { return fold(text).replace(/\s+/g, " ").trim(); }
  function words(text) { return key(text).match(/[a-z0-9œæ'-]+/g) || []; }
  // French typography for engine wording; learner quotes are never passed through it.
  function typography(text) {
    return text.replace(/\s+/g, " ").replace(/'/g, "\u2019")
      .replace(/ ([?!:;»])/g, "\u00a0$1").replace(/« /g, "«\u00a0");
  }
  function typeset(line) { return typography(line).trim(); }

  // ---- Question registry ---------------------------------------------------------

  var entries = [];
  function register(list, kind, topic, hook) {
    return list.map(function (question, index) {
      var entry = Object.assign({ id: (hook || topic) + "-" + kind + "-" + index,
        kind: kind, topic: topic, hook: hook || null, covers: [] }, question);
      entry.sense = entry.sense || entry.id;
      entry.keys = [key(entry.text), key(entry.simple)];
      entries.push(entry);
      return entry;
    });
  }
  PRESENTATION.opening = register(PRESENTATION.opening, "opening", "presentation");
  PRESENTATION.follow = register(PRESENTATION.follow, "follow", "presentation");
  TOPICS.forEach(function (topic) {
    topic.primary = register(topic.primary, "primary", topic.id);
    topic.follow = register(topic.follow, "follow", topic.id);
  });
  HOOKS.forEach(function (hook) {
    hook.questions = register(hook.questions, "hook", hook.topic, hook.id);
  });
  QUICK = register(QUICK, "quick", "quick");
  ELABORATE = register(ELABORATE, "elaborate", null);
  PROBES = register(PROBES, "probe", null);
  FALLBACK = register(FALLBACK, "fallback", "fallback");
  var TOPIC_BY_ID = { presentation: PRESENTATION };
  TOPICS.forEach(function (topic) { TOPIC_BY_ID[topic.id] = topic; });

  // The longest registered question contained in an examiner line identifies it.
  function identify(line) {
    var folded = key(line), best = null;
    entries.forEach(function (entry) {
      entry.keys.forEach(function (candidate, index) {
        if (candidate && folded.indexOf(candidate) >= 0 &&
            (!best || candidate.length > best.length)) {
          best = { entry: entry, form: index ? "simple" : "text", length: candidate.length };
        }
      });
    });
    return best;
  }

  function classify(answer) {
    var folded = key(answer);
    if (!/[a-z0-9]/.test(folded)) return "empty";
    var count = words(answer).length;
    for (var i = 0; i < META.length; i++) {
      var group = META[i];
      if (count <= group.maxWords && group.patterns.some(function (p) { return p.test(folded); })) {
        return group.kind;
      }
    }
    return "content";
  }

  function negated(folded, start, end) {
    var before = folded.slice(0, start);
    var clauseStart = Math.max(before.search(/[.;!?,][^.;!?,]*$/), before.lastIndexOf(" mais "),
      before.lastIndexOf(" et "));
    var lead = before.slice(clauseStart + 1).split(/[\s']+/).filter(Boolean).slice(-5).join(" ");
    var tail = folded.slice(end).split(/[.;!?,]/)[0].split(/\s+/).filter(Boolean).slice(0, 2).join(" ");
    return NEGATION.test(lead) || /\b(pas|jamais)\b/.test(tail);
  }

  function hooksIn(answer) {
    var folded = fold(answer);
    return HOOKS.filter(function (hook) {
      var pattern = new RegExp(hook.pattern.source, "g"), match;
      while ((match = pattern.exec(folded))) {
        if (hook.negatable === false || !negated(folded, match.index, match.index + match[0].length)) {
          return true;
        }
      }
      return false;
    });
  }

  // ---- Interview state, rebuilt from turns --------------------------------------

  function analyse(turns) {
    var history = (Array.isArray(turns) ? turns : []).filter(Boolean).map(function (turn) {
      var match = identify(turn.question);
      var answer = typeof turn.answer === "string" ? turn.answer.trim() : "";
      return { question: String(turn.question || ""), answer: answer, kind: classify(answer),
        entry: match ? match.entry : null, form: match ? match.form : null };
    });
    var asked = {}, senses = {}, touched = {}, hooksUsed = {}, topic = null;
    history.forEach(function (step) {
      var entry = step.entry;
      if (!entry) { topic = null; step.topic = null; return; }
      asked[entry.id] = true;
      senses[entry.sense] = true;
      if (entry.hook) hooksUsed[entry.hook] = true;
      if (entry.topic) topic = entry.topic;
      step.topic = topic;
      touched[topic] = true;
      entry.covers.forEach(function (id) { touched[id] = true; });
    });
    var last = history[history.length - 1] || null;
    var depth = 0, elaborated = false, seen = {};
    for (var i = history.length - 1; i >= 0 && last && history[i].topic === last.topic &&
        history[i].entry; i--) {
      if (!seen[history[i].entry.id]) depth++;
      seen[history[i].entry.id] = true;
      if (history[i].entry.kind === "elaborate") elaborated = true;
    }
    var current = {};
    if (last && last.topic) {
      current[last.topic] = true;
      last.entry.covers.forEach(function (id) { current[id] = true; });
    }
    return { history: history, last: last, asked: asked, senses: senses, touched: touched,
      hooksUsed: hooksUsed, current: current, depth: depth, elaborated: elaborated };
  }

  // ---- Engine --------------------------------------------------------------------

  function create(options) {
    var random = options && typeof options.random === "function" ? options.random : Math.random;

    function pick(list) {
      return list.length ? list[Math.min(list.length - 1, Math.floor(random() * list.length))] : null;
    }
    function fresh(state, list) {
      return list.filter(function (entry) { return !state.asked[entry.id] && !state.senses[entry.sense]; });
    }
    function recent(state) {
      return state.history.slice(-2).map(function (step) { return key(step.question); }).join(" | ");
    }
    // Avoids reusing the acknowledgement or transition heard in the last two lines.
    function phrase(state, list, chance) {
      if (chance !== undefined && random() >= chance) return "";
      var heard = recent(state);
      var unused = list.filter(function (option) { return heard.indexOf(key(option)) < 0; });
      return pick(unused.length ? unused : list);
    }
    function line() {
      return typeset(Array.prototype.slice.call(arguments).filter(Boolean).join(" "));
    }

    function hookQuestion(state, answer, allowTopic) {
      var options = [], precise = [];
      var matches = hooksIn(answer);
      matches.forEach(function (hook) {
        if (state.hooksUsed[hook.id] || !allowTopic(hook.topic)) return;
        if (hook.specific) precise = precise.concat(fresh(state, hook.questions));
        else options = options.concat(fresh(state, hook.questions));
      });
      return pick(precise.length ? precise : options);
    }
    function liveHook(state) {
      if (state.last.kind !== "content") return null;
      return hookQuestion(state, state.last.answer, function (topic) {
        return state.current[topic] ? state.depth < 3 : !state.touched[topic];
      });
    }
    function earlierHook(state) {
      var earlier = state.history.slice(0, -1).filter(function (step) { return step.kind === "content"; });
      for (var i = earlier.length - 1; i >= 0; i--) {
        var found = hookQuestion(state, earlier[i].answer, function (topic) { return !state.touched[topic]; });
        if (found) return found;
      }
      return null;
    }
    function newTopic(state, remaining) {
      var open = TOPICS.filter(function (topic) {
        return !state.touched[topic.id] && fresh(state, topic.primary).length;
      });
      var timely = open.filter(function (topic) { return !topic.late || remaining <= LATE_SECONDS; });
      var topic = pick(timely.length ? timely : open);
      return topic ? pick(fresh(state, topic.primary)) : null;
    }
    function anyQuestion(state, remaining) {
      return newTopic(state, remaining) || pick(fresh(state, QUICK)) || pick(fresh(state, FALLBACK)) ||
        FALLBACK[0];
    }
    function closingQuestion(state, remaining) {
      return pick(fresh(state, QUICK)) || anyQuestion(state, remaining);
    }

    function help(state, remaining) {
      var last = state.last, target = last.entry;
      if (!target) return line(pick(PREFIX.moveOn), anyQuestion(state, remaining).text);
      var streak = [];
      for (var i = state.history.length - 1; i >= 0; i--) {
        var step = state.history[i];
        if (step.entry !== target || !HELP_KINDS[step.kind]) break;
        streak.push(step);
      }
      var simplified = streak.some(function (step) { return step.form === "simple"; });
      if (last.kind === "repeat" && streak.length === 1 && last.form === "text") {
        return line(pick(PREFIX.repeat), target.text);
      }
      if (!simplified && !(target.kind === "elaborate" && last.kind === "dontknow")) {
        var prefix = last.kind === "dontknow" ? PREFIX.dontknow : PREFIX.rephrase;
        return line(pick(prefix), target.simple);
      }
      var next = remaining <= CLOSING_SECONDS ? closingQuestion(state, remaining) : anyQuestion(state, remaining);
      return line(pick(PREFIX.moveOn), next.text);
    }

    function opening() {
      return line(pick(OPENING_FRAMES), pick(PRESENTATION.opening).text);
    }

    function next(turns, remainingSeconds) {
      var state = analyse(turns);
      if (!state.last) return opening();
      var remaining = Number(remainingSeconds);
      if (!isFinite(remaining)) remaining = 120;
      var closing = remaining <= CLOSING_SECONDS;
      var last = state.last;

      if (HELP_KINDS[last.kind]) return help(state, remaining);
      if (last.kind === "switch") {
        return line(pick(PREFIX.switch),
          (closing ? closingQuestion(state, remaining) : anyQuestion(state, remaining)).text);
      }

      var ack = phrase(state, ACK, 0.6);
      var hook = liveHook(state);
      if (hook && (!closing || words(hook.text).length <= 10)) return line(ack, hook.text);
      if (last.kind === "content" && state.depth < 3 && last.entry && last.entry.kind !== "probe") {
        var probes = fresh(state, PROBES).filter(function (p) {
          return p.cue.test(key(last.answer)) && (!closing || words(p.simple).length <= 9);
        });
        var probe = pick(probes);
        if (probe) return line(closing ? probe.simple : probe.text);
      }
      if (closing) return line(ack, closingQuestion(state, remaining).text);

      var words_ = words(last.answer);
      var kind = last.entry && last.entry.kind;
      if (last.kind === "content" && words_.length <= SHORT_ANSWER_WORDS &&
          !BARE_NEGATIVE.test(key(last.answer)) && !state.elaborated &&
          kind !== "quick" && kind !== "elaborate") {
        var elaborate = pick(fresh(state, ELABORATE));
        if (elaborate) return line(elaborate.text);
      }

      var topic = last.topic && TOPIC_BY_ID[last.topic];
      if (topic && state.depth < 2) {
        var follow = pick(fresh(state, topic.follow));
        if (follow) return line(ack, follow.text);
      }

      var callback = earlierHook(state);
      if (callback) return line(ack, pick(CALLBACK), callback.text);
      var primary = newTopic(state, remaining);
      if (primary) return line(ack, phrase(state, TRANSITION, 0.5), primary.text);
      return line(ack, anyQuestion(state, remaining).text);
    }

    return { opening: opening, next: next, feedback: feedback, create: create };
  }

  // ---- Debrief -------------------------------------------------------------------

  function excerpt(text, maxWords) {
    var clean = String(text).replace(/\s+/g, " ").trim();
    var parts = clean.split(" ");
    return parts.length <= maxWords ? clean : parts.slice(0, maxWords).join(" ") + "…";
  }
  // Quotes a window of the learner's own words around a match, within its sentence,
  // marking any cut.
  function excerptAround(text, start, end) {
    var spans = [], pattern = /\S+/g, match;
    while ((match = pattern.exec(text))) spans.push([match.index, match.index + match[0].length]);
    var boundary = text.slice(0, start).search(/[.!?…]\s+[^.!?…]*$/);
    var after = /[.!?…](\s|$)/.exec(text.slice(end));
    var sentenceStart = boundary < 0 ? 0 : boundary + 1;
    var sentenceEnd = after ? end + after.index + 1 : text.length;
    var head = spans.findIndex(function (span) { return span[0] >= sentenceStart; });
    var tail = spans.length - 1;
    while (tail > 0 && spans[tail][1] > sentenceEnd) tail--;
    var first = spans.findIndex(function (span) { return span[1] > start; });
    var lastWord = Math.max(first, spans.findIndex(function (span) { return span[1] >= end; }));
    var from = Math.max(head, first - 6), to = Math.min(tail, lastWord + 8);
    return (from > head ? "…" : "") + text.slice(spans[from][0], spans[to][1]) + (to < tail ? "…" : "");
  }
  function quote(text) { return "« " + text + " »"; }
  // Learner words are marked so that note() keeps them exactly as transcribed.
  function said(text) {
    return quote("\u0001" + text.replace(/\s+/g, " ").trim().replace(/[\s.,;:]+$/, "") + "\u0002");
  }
  function asked(step) {
    if (!step.entry) return step.question;
    return step.form === "simple" ? step.entry.simple : step.entry.text;
  }
  function note(title, detail) {
    return { title: typeset(title), detail: detail.split(/\u0001([^\u0002]*)\u0002/)
      .map(function (part, index) { return index % 2 ? part : typography(part); }).join("").trim() };
  }

  function linkingNote(content) {
    for (var c = 0; c < CONNECTORS.length; c++) {
      for (var i = 0; i < content.length; i++) {
        var match = CONNECTORS[c][1].exec(fold(content[i].answer));
        if (match) {
          return note("Ce qui fonctionne",
            "Vous reliez vos idées avec « " + CONNECTORS[c][0] + " » : " +
            said(excerptAround(content[i].answer, match.index, match.index + match[0].length)) +
            ". Gardez ce réflexe dans chaque réponse : une idée, puis une raison ou un exemple.");
        }
      }
    }
    var longest = content.slice().sort(function (a, b) {
      return words(b.answer).length - words(a.answer).length;
    })[0];
    var total = content.reduce(function (sum, step) { return sum + words(step.answer).length; }, 0);
    if (total < 12) return null;
    return note("Relier vos idées",
      "Vos réponses transcrites utilisent peu de mots de liaison, par exemple " +
      said(excerpt(longest.answer, 18)) + ". Ajoutez « parce que », « mais » ou « par exemple » " +
      "pour expliquer ou illustrer.");
  }

  function developNote(content) {
    var short = content.filter(function (step) { return words(step.answer).length <= 6; });
    if (!short.length) return null;
    short.sort(function (a, b) {
      var quickA = a.entry && a.entry.kind === "quick", quickB = b.entry && b.entry.kind === "quick";
      return (quickA - quickB) || (words(a.answer).length - words(b.answer).length);
    });
    var step = short[0];
    return note("Développer une réponse courte",
      "À la question " + quote(asked(step)) + ", vous avez répondu " + said(excerpt(step.answer, 6)) +
      ". Reprenez-la à voix haute en ajoutant un détail concret (quand, où, avec qui) et une raison " +
      "(« parce que… »).");
  }

  function metaNote(history) {
    var byKind = function (kind) { return history.filter(function (step) { return step.kind === kind; }); };
    var dontknow = byKind("dontknow"), switched = byKind("switch");
    var helped = history.filter(function (step) { return step.kind === "repeat" || step.kind === "unclear"; });
    if (dontknow.length) {
      return note("Trouver une idée rapidement",
        "À la question " + quote(asked(dontknow[0])) + ", vous avez répondu " +
        said(excerpt(dontknow[0].answer, 8)) + ". Il n'y a pas de bonne ou de mauvaise réponse ici : " +
        "partez d'une habitude ou d'un souvenir réel, même simple, et décrivez-le.");
    }
    if (switched.length) {
      return note("Changer de sujet poliment",
        "Vous avez demandé à changer de sujet (" + said(excerpt(switched[0].answer, 12)) + "). " +
        "C'est possible : une phrase courte suffit, puis répondez pleinement à la question suivante.");
    }
    if (helped.length) {
      return note("Demander une reformulation",
        (helped.length > 1 ? "Vous avez demandé de l'aide " + helped.length + " fois, par exemple "
          : "Vous avez dit ") + said(excerpt(helped[0].answer, 12)) +
        ". C'est naturel dans un échange. Vous pouvez aussi vérifier votre compréhension en " +
        "reformulant : « Vous voulez savoir si… ? »");
    }
    return null;
  }

  function repetitionNote(content) {
    var counts = {};
    content.forEach(function (step) {
      words(step.answer).forEach(function (word) {
        if (OVERUSED[word]) counts[word] = (counts[word] || 0) + 1;
      });
    });
    var top = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; })[0];
    if (!top || counts[top] < 4) return null;
    return note("Varier le vocabulaire",
      "Le mot « " + OVERUSED[top][0] + " » revient " + counts[top] + " fois dans vos réponses " +
      "transcrites. Essayez " + OVERUSED[top][1] + ".");
  }

  function tenseNote(history) {
    var step = history.find(function (item) { return item.entry && item.entry.tense; });
    if (!step) return null;
    var tense = TENSES[step.entry.tense];
    return note("Vérifier les temps",
      "La question " + quote(asked(step)) + " portait sur " + tense[0] + ". Vérifiez que vous avez " +
      "utilisé " + tense[1] + ".");
  }

  function revisitNote(history) {
    var known = history.filter(function (step) { return step.entry; });
    var later = known.filter(function (step) { return step.entry.kind !== "opening"; });
    var step = later[later.length - 1] || known[0];
    return note("Reprendre une question",
      "Choisissez une question de l'entretien" + (step ? ", par exemple " + quote(asked(step)) + "," : "") +
      " et répondez-y de nouveau à voix haute : une réponse directe, un détail concret, puis une " +
      "raison ou un exemple.");
  }

  function checklistNote() {
    return note("Faire le point",
      "Pour chaque échange, demandez-vous : ai-je répondu directement à la question ? " +
      "Ai-je ajouté un détail personnel ? Ai-je gardé la parole sans long silence ?");
  }

  function feedback(turns) {
    var history = analyse(turns).history;
    if (!history.length) return [];
    var content = history.filter(function (step) { return step.kind === "content"; });
    var notes;
    if (content.length) {
      notes = [linkingNote(content), developNote(content), metaNote(history), repetitionNote(content)];
      notes = notes.filter(Boolean);
      if (notes.length < 3) notes.push(tenseNote(history));
      if (notes.filter(Boolean).length < 2) notes.push(revisitNote(history));
    } else if (history.some(function (step) { return step.kind !== "empty"; })) {
      notes = [metaNote(history), revisitNote(history), tenseNote(history), checklistNote()];
    } else {
      notes = [revisitNote(history), tenseNote(history), checklistNote()];
    }
    return notes.filter(Boolean).slice(0, 3);
  }

  return create();
}));
