# PRD – Bot Vinted (SaaS Edition)

## 1. Vision du Produit
**Objectif** : Fournir une solution de monitoring ultra-rapide et automatisée pour l'achat-revente d'iPhones sur Vinted. Le système doit garantir un avantage concurrentiel (vitesse) tout en restant rentable grâce à une gestion optimisée des crédits API.

**Modèle Économique** :
- Prix : 9,99€/mois par client
- Rentabilité : 11 clients minimum pour être rentable
- Infrastructure ScrapingBee : Plan à 100€/mois (1M crédits/mois)
- Serveur : VPS Hetzner CPX11 (~5€/mois)

## 2. Spécifications Fonctionnelles
### 2.1 Architecture Hybride (Test / Prod)
Le projet utilise deux moteurs selon l'environnement :
- **Environnement de Test (main.py)** : Utilise Playwright avec navigateur headless. Idéal pour tester localement les sélecteurs, la logique de filtrage et scraper gratuitement sans consommer de crédits.
- **Environnement de Prod (main_scrapingbee.py)** : Utilise ScrapingBee via requêtes HTTP asynchrones. Optimisé pour la résilience, le contournement des blocages et la haute disponibilité sur serveur Hetzner.

### 2.2 Architecture de Scan en "Cascade" (Prod)
Pour maximiser la rentabilité sur ScrapingBee, le bot utilise une architecture en deux phases :

**Phase 1 : Sentinelle**
- Scan de la liste catalogue
- Configuration : `render_js=true` + `premium_proxy=false` (5 crédits/appel) ou fallback `premium_proxy=true` (75 crédits)
- Objectif : Lister rapidement les annonces disponibles via extraction directe des liens `<a href>`

**Phase 2 : Extracteur (Premium)**
- Analyse détaillée uniquement pour les NOUVELLES annonces (non en cache)
- Configuration : `render_js=true` + `premium_proxy=true` (75 crédits/appel)
- Extraction JSON-LD complète (titre, prix, image)

### 2.3 Gestion des Modèles & Concurrency (Prod)
- Surveillance des modèles d'iPhone définis dans `models_config.json`
- **asyncio.gather** + **Semaphore** global pour traiter les modèles en parallèle sans surcharge
- Intervalle de scan de base avec randomisation pour éviter les patterns fixes
- Sleep aléatoire entre modèles et requêtes

### 2.4 Filtrage de Précision (Anti-Pollution)
**Exclusion stricte** :
- Accessoires (coques, chargeurs, housses, bumpers)
- Pièces détachées (écrans LCD/OLED, batteries, châssis)
- iCloud bloqué (toutes variantes multilingues)
- Modèles factices (dummy, demo, fake)
- Arnaques (PayPal, virement bancaire)
- Exclusions logiques (un iPhone 12 Pro ne doit pas matcher quand on cherche un iPhone 12)

**Filtrage de prix** : Comparaison avec `price_min` et `price_max` définis dans `models_config.json`.

## 3. Spécifications Techniques

| Composant | Détails |
|-----------|---------|
| **Langage** | Python 3.10+ (Asynchrone) |
| **Moteur Test** | Playwright (async_playwright) |
| **Moteur Prod** | ScrapingBee API (HTTP REST) via aiohttp |
| **Parsing** | BeautifulSoup4 + lxml |
| **Stockage** | Cache local JSON (cache_annonces.json) |

## 4. Expérience Utilisateur (UX)
**Format Push** : Notifications Discord instantanées avec Embeds via client Discord natif (`discord.py`).

**Contenu Embed Discord** :
- Titre de l'annonce
- Prix
- Image miniature
- Lien direct cliquable
- Timestamp

**Smart Sleep** :
Pause automatique du bot en heures creuses (**03:00 à 08:00** heure locale) pour économiser des crédits API, car aucun humain ne surveille Vinted à ces heures et la publication est très faible.

## 5. Résilience & Sécurité
- **Auto-Healing** : Si multiples erreurs consécutives, pause temporaire progressive. Crash monitor loop qui avertit sur `ALERT_CHANNEL_ID` si le bot plante silencieusement.
- **Cache JSON Atomique** : Le cache enregistre les URLs traitées pour ne pas spammer le Discord après un redémarrage.
- **Zéro Hardcoding** : Les tokens (DISCORD_TOKEN, SCRAPINGBEE_KEY, ALERT_CHANNEL_ID) sont chargés via environnement (`.env`).
