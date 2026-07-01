# CheckIt.AI — Diagrammes de Séquence des Adaptateurs
**Livrable L2** | Méthode `extraire_données()` | Juin 2026

Les étapes communes à tous les adaptateurs sont marquées ✦

---

## Étapes communes à tous les adaptateurs

```
✦ START_ACTION (LogTool)
✦ Vérification disponibilité source
✦ Boucle traitement entrées
✦ Validation paire texte-image
✦ Mapping → entité Publication
✦ pub.est_valide()
✦ Compteurs valides / rejetées
✦ FINISH_ACTION (LogTool) + rapport statistiques
```

---

## 1. FeedparserAdapter — Flux RSS

```plantuml
@startuml feedparser_adapter
skinparam sequenceArrowThickness 2
skinparam roundcorner 10
skinparam sequenceGroupBorderColor #BA7517
skinparam sequenceGroupBackgroundColor #FEF3E2
skinparam noteBorderColor #185FA5
skinparam noteBackgroundColor #E6F1FB

actor       DAG          as dag
participant FeedparserAdapter as ada
participant "feedparser\n(lib)"   as fp
participant "Source RSS\nAFP·EUvsDisinfo\nHoaxbuster" as src
participant "Publication\n(domain)"  as pub

== ✦ Initialisation ==
dag -> ada : extraire_données(source_url)

== ✦ Vérification disponibilité ==
ada -> src : HEAD request
src --> ada : HTTP 200 / erreur
note right : est_disponible()\navant extraction

== Parsing du flux RSS ==
ada -> fp  : feedparser.parse(source_url)
fp  -> src : GET flux XML
src --> fp : XML RSS/Atom
fp  --> ada : flux.entries[]

== ✦ Boucle traitement entrées ==
loop pour chaque entrée RSS
    ada -> ada : _extraire_titre(entrée)
    ada -> ada : _extraire_contenu(entrée)
    ada -> ada : _extraire_image(entrée)\nmedia:content → enclosures → regex HTML

    == ✦ Validation paire texte-image ==
    alt image absente
        ada -> ada : rejetées += 1
    else image présente
        ada -> ada : _inférer_label(titre, tags)\nmots-clés FAUX/VRAI dans titre
        == ✦ Mapping → Publication ==
        ada -> pub : Publication(title, content,\nimage_url, label, lang)
        pub --> ada : instance
        == ✦ Validation domaine ==
        ada -> pub : est_valide()
        pub --> ada : True / False
        alt valide
            ada -> ada : publications.append(pub)
        else invalide
            ada -> ada : rejetées += 1
        end
    end
end

== ✦ Rapport final ==
ada --> dag : List[Publication]

@enduml
```

---

## 2. RequestsAdapter — API REST (NewsData.io + MBFC)

```plantuml
@startuml requests_adapter
skinparam sequenceArrowThickness 2
skinparam roundcorner 10
skinparam sequenceGroupBorderColor #BA7517
skinparam sequenceGroupBackgroundColor #FEF3E2
skinparam noteBorderColor #185FA5
skinparam noteBackgroundColor #E6F1FB

actor       DAG           as dag
participant RequestsAdapter as ada
participant "requests\n.Session"  as ses
participant "NewsData.io\nAPI"    as nd
participant "MBFC\n(interne)"     as mbfc
participant "Publication\n(domain)" as pub

== ✦ Initialisation ==
dag -> ada : extraire_données(source_url)
ada -> ada : vérifier NEWSDATA_API_KEY\n→ CRITICAL si absente

== ✦ Vérification disponibilité ==
ada -> ses : GET /news?size=1
ses -> nd  : HTTP GET
nd  --> ses : JSON 200 / erreur
ses --> ada : status_code

== Appel API NewsData.io ==
ada -> ses : GET source_url (params configurés)
ses -> nd  : HTTP GET + apikey
nd  --> ses : JSON {results: [...]}
ses --> ada : données.get("results")

== ✦ Boucle traitement articles ==
loop pour chaque article JSON
    ada -> ada : extraire titre, contenu,\nimage_url, source_id, langue

    == ✦ Validation paire texte-image ==
    alt titre ou image_url manquant
        ada -> ada : rejetées += 1
    else complet
        == Inférence label via MBFC ==
        ada -> mbfc : _évaluer_source_mbfc(source_id)
        note right : liste sources fiables/\nnon fiables en mémoire\nMBFC simplifié
        mbfc --> ada : LabelVéracité.REAL / FAKE

        == ✦ Mapping → Publication ==
        ada -> pub : Publication(title, content,\nimage_url, label, lang,\nmetadata)
        pub --> ada : instance

        == ✦ Validation domaine ==
        ada -> pub : est_valide()
        pub --> ada : True / False
        alt valide
            ada -> ada : publications.append(pub)
        else invalide
            ada -> ada : rejetées += 1
        end
    end
end

== ✦ Rapport final ==
ada --> dag : List[Publication]

@enduml
```

---

## 3. Bs4Adapter — HTML Statique (FullFact · Correctiv · Maldita)

```plantuml
@startuml bs4_adapter
skinparam sequenceArrowThickness 2
skinparam roundcorner 10
skinparam sequenceGroupBorderColor #BA7517
skinparam sequenceGroupBackgroundColor #FEF3E2
skinparam noteBorderColor #185FA5
skinparam noteBackgroundColor #E6F1FB

actor       DAG          as dag
participant Bs4Adapter   as ada
participant "requests\n.Session" as ses
participant "Site HTML\nFullFact·Correctiv\nMaldita" as site
participant "BeautifulSoup\n(lib)" as bs4
participant "Publication\n(domain)" as pub

== ✦ Initialisation ==
dag -> ada : extraire_données(source_url)

== ✦ Vérification disponibilité ==
ada -> ses : HEAD source_url
ses -> site : HTTP HEAD
site --> ses : 200 / erreur
ses --> ada : disponible

== Téléchargement page liste ==
ada -> ses : GET source_url
ses -> site : HTTP GET
site --> ses : HTML page liste
ses --> ada : réponse.text
ada -> bs4  : BeautifulSoup(html, "html.parser")
bs4 --> ada : soupe DOM

== Extraction URLs articles ==
ada -> bs4  : soupe.select(sélecteur_articles)
bs4 --> ada : liste éléments
ada -> ada  : _extraire_urls_articles(soupe)\nurljoin → URLs absolues

== ✦ Boucle traitement articles ==
loop pour chaque URL article (max NB_ARTICLES_MAX)
    ada -> ada  : time.sleep(DÉLAI)
    ada -> ses  : GET url_article
    ses -> site : HTTP GET
    site --> ses : HTML article
    ses --> ada : réponse.text
    ada -> bs4  : BeautifulSoup(html)
    bs4 --> ada : soupe article

    ada -> ada : _extraire_titre(soupe)\nsélecteur_titre CSS
    ada -> ada : _extraire_contenu(soupe)\njoin paragraphes
    ada -> ada : _extraire_image(soupe)\nsrc / data-src / data-lazy-src
    ada -> ada : _extraire_label(soupe)\nmot-clé → LabelVéracité

    == ✦ Validation paire texte-image ==
    alt image absente
        ada -> ada : rejetées += 1
    else image présente
        == ✦ Mapping → Publication ==
        ada -> pub : Publication(title, content,\nimage_url, label, lang)
        pub --> ada : instance

        == ✦ Validation domaine ==
        ada -> pub : est_valide()
        pub --> ada : True / False
        alt valide
            ada -> ada : publications.append(pub)
        else invalide
            ada -> ada : rejetées += 1
        end
    end
end

== ✦ Rapport final ==
ada --> dag : List[Publication]

@enduml
```

---

## 4. ScrapyAdapter — Crawling Multi-pages (PolitiFact)

```plantuml
@startuml scrapy_adapter
skinparam sequenceArrowThickness 2
skinparam roundcorner 10
skinparam sequenceGroupBorderColor #BA7517
skinparam sequenceGroupBackgroundColor #FEF3E2
skinparam noteBorderColor #185FA5
skinparam noteBackgroundColor #E6F1FB

actor       DAG              as dag
participant ScrapyAdapter    as ada
participant CrawlerProcess   as cp
participant PolitiFactSpider as spider
participant "PolitiFact\n.com" as site
participant "Publication\n(domain)" as pub

== ✦ Initialisation ==
dag    -> ada    : extraire_données(source_url)
ada    -> ada    : résultats_bruts = []

== ✦ Vérification disponibilité ==
ada    -> site   : HEAD source_url
site   --> ada   : 200 / erreur

== Lancement du crawl (bloquant) ==
ada    -> cp     : CrawlerProcess(settings)
ada    -> cp     : crawl(PolitiFactSpider,\nrésultats=résultats_bruts)
cp     -> spider : start_urls = [source_url]

loop parse() — pages liste avec pagination
    spider -> site  : GET /factchecks/?page=N
    site   --> spider : HTML liste articles
    spider -> spider : css("article.m-statement")
    spider -> spider : extraire liens articles

    loop parse_article() — pour chaque article
        spider -> site  : GET /factchecks/article/
        site   --> spider : HTML article
        spider -> spider : extraire titre\nextraire label (truth-o-meter img alt)\nextraire image_url\nextraire contenu paragraphes
        spider -> spider : mapper label → LabelVéracité

        == ✦ Validation paire texte-image ==
        alt titre et image présents
            spider -> ada   : résultats_bruts.append(dict)
        else incomplet
            spider -> spider : ignorer
        end
    end

    alt page suivante existe et résultats < MAX
        spider -> spider : follow(page_suivante)
    else
        spider -> cp : arrêt crawl
    end
end

cp --> ada : processus terminé

== ✦ Boucle mapping résultats ==
loop pour chaque dict dans résultats_bruts
    == ✦ Mapping → Publication ==
    ada -> pub : Publication(title, content,\nimage_url, label, lang)
    pub --> ada : instance

    == ✦ Validation domaine ==
    ada -> pub : est_valide()
    pub --> ada : True / False
    alt valide
        ada -> ada : publications.append(pub)
    else invalide
        ada -> ada : rejetées += 1
    end
end

== ✦ Rapport final ==
ada --> dag : List[Publication]

@enduml
```

---

## 5. SeleniumAdapter — SPA JavaScript (Logically · Decodex)

```plantuml
@startuml selenium_adapter
skinparam sequenceArrowThickness 2
skinparam roundcorner 10
skinparam sequenceGroupBorderColor #BA7517
skinparam sequenceGroupBackgroundColor #FEF3E2
skinparam noteBorderColor #185FA5
skinparam noteBackgroundColor #E6F1FB

actor       DAG             as dag
participant SeleniumAdapter as ada
participant "Chrome\nHeadless" as chrome
participant "WebDriverWait"  as wait
participant "Site SPA\nLogically·Decodex" as site
participant "Publication\n(domain)" as pub

== ✦ Initialisation ==
dag  -> ada    : extraire_données(source_url)

== ✦ Vérification disponibilité ==
ada  -> site   : HEAD source_url (requests — pas Chrome)
site --> ada   : 200 / erreur

== Démarrage Chrome headless ==
ada  -> chrome : Options(headless, no-sandbox,\ndisable-gpu, window-size)
ada  -> chrome : shutil.which() → binary_location\n(google-chrome > chromium)
ada  -> chrome : webdriver.Chrome(service, options)
chrome --> ada : driver prêt

== Extraction URLs articles ==
ada    -> chrome : driver.get(source_url)
chrome -> site   : HTTP GET + exécution JS
site   --> chrome : DOM rendu (React/Vue)
ada    -> wait   : WebDriverWait(driver, TIMEOUT)\nuntil presence_of_element(attente_élément)
note right : attente_élément = "div.fact-check-card"\nou "article.article"\nsignal que le JS a fini
wait   --> ada   : DOM stable
ada    -> chrome : find_elements(CSS, sélecteur_articles)
chrome --> ada   : liste éléments
ada    -> ada    : extraire href → urls_articles

== ✦ Boucle traitement articles ==
loop pour chaque URL article (max NB_ARTICLES_MAX)
    ada    -> ada    : time.sleep(DÉLAI_ENTRE_ARTICLES)
    ada    -> chrome : driver.get(url_article)
    chrome -> site   : HTTP GET + exécution JS
    site   --> chrome : DOM article rendu
    ada    -> chrome : time.sleep(DÉLAI_CHARGEMENT)

    ada    -> chrome : _extraire_texte(sélecteur_titre)
    chrome --> ada   : titre

    ada    -> chrome : _extraire_texte(sélecteur_contenu)
    chrome --> ada   : contenu

    ada    -> chrome : _extraire_attribut(sélecteur_image, "src")
    chrome --> ada   : image_url

    ada    -> chrome : _extraire_texte(sélecteur_label)
    chrome --> ada   : texte_label
    ada    -> ada    : mapper mot-clé → LabelVéracité

    == ✦ Validation paire texte-image ==
    alt titre ou image absents
        ada -> ada : rejetées += 1
    else complets
        == ✦ Mapping → Publication ==
        ada -> pub : Publication(title, content,\nimage_url, label, lang)
        pub --> ada : instance

        == ✦ Validation domaine ==
        ada -> pub : est_valide()
        pub --> ada : True / False
        alt valide
            ada -> ada : publications.append(pub)
        else invalide
            ada -> ada : rejetées += 1
        end
    end
end

== Fermeture driver ==
ada    -> chrome : driver.quit()
chrome --> ada   : fermé

== ✦ Rapport final ==
ada --> dag : List[Publication]

@enduml
```

---

## Résumé — Pipeline commun ✦

```plantuml
@startuml pipeline_commun
skinparam roundcorner 10
skinparam activityBorderColor #185FA5
skinparam activityBackgroundColor #E6F1FB
skinparam activityDiamondBorderColor #BA7517
skinparam activityDiamondBackgroundColor #FEF3E2

|Tous les adaptateurs|
start
:✦ START_ACTION (LogTool);
:✦ Vérification disponibilité source\n(HEAD request);

if (Source disponible ?) then (non)
    :LEVEL_4_ERROR;
    stop
else (oui)
endif

:Extraction spécifique\n(RSS / API / HTML / Scrapy / Selenium);

repeat
    :✦ Traitement d'une entrée;
    if (✦ Paire texte-image complète ?) then (non)
        :rejetées += 1\nLEVEL_5_WARNING;
    else (oui)
        :✦ Mapping → Publication(domain);
        if (✦ pub.est_valide() ?) then (non)
            :rejetées += 1;
        else (oui)
            :publications.append(pub)\nLEVEL_7_INFO;
        endif
    endif
repeat while (entrées restantes ?) is (oui)
-> non;

:✦ FINISH_ACTION\nRapport : valides / rejetées / taux;
stop

@enduml
```
