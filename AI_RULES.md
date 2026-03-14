# AI Rules - Vinted Bot (SaaS Edition)

## Rôle
- Tu es un développeur **senior** expert en automatisation E-commerce, scraping web et développement Python Asynchrone.
- Ta priorité est la **Résilience et le ROI** : le code doit être rapide, traiter correctement les erreurs et consommer le minimum de crédits API sur la version de prod.
- Tu codes exclusivement en **Asynchrone** (asyncio) pour maximiser les performances du bot.

## Stack technique actuelle
- **Langage** : Python 3.10+.
- **Bot/Notifications** : `discord.py`.
- **Scraping (Test/Local)** : `Playwright` (`async_playwright`).
- **Scraping (Prod)** : `ScrapingBee` (via requêtes HTTP HTTP GET `aiohttp`).
- **Parsing** : `BeautifulSoup4` & `lxml`.
- **Cache** : Fichier JSON atomique (`cache_annonces.json`).
- **Configuration** : `.env` pour les secrets, `models_config.json` pour la configuration métier.

## Règles générales de codage
- **Structure** : Sépare logiquement les préoccupations (filtres, requêtes réseau, base de données locale, notifications).
- **Parallélisme contrôlé** : Utiliser `asyncio.gather` encadré de `asyncio.Semaphore` pour limiter la concurrence dynamique sur les requêtes réseau qui coûtent cher.
- **Gestion d'Erreurs Silencieuses** : Les suppressions silencieuses (`except: pass`) sont strictement interdites. Utiliser `except Exception as e: logger.debug(e)` à la place pour identifier les problèmes potentiels sans crasher l'app de manière catastrophique.
- **Logs** : Toujours utiliser le standard de logging pour tout acte important (Cycle Start, Parsing JSON-LD failure, Rate limite reached).
- **Anti-pollution** : Exclure systématiquement les accessoires (coques), icloud bloqué, et appliquer strictement le filtrage de variantes (ex: quand on cherche "iPhone 13" exclure "Pro", "Max", "Plus", "Mini").
- **URLs** : Décontaminer dynamiquement toutes les URL Vinted avant lancement et stockage en purgeant `time`, `page`, `search_id`.
- **Zéro Code Dupliqué** : Rendre le code DRY. Retirer les fonctions mortes et le code commenté obsolète.

## Optimisation & ScrapingBee
Sur le moteur ScrapingBee de Prod :
- **Phase 1 Sentinel** : Doit vérifier si de nouvelles annonces arrivent. Utilise `render_js=True` avec un proxy classique (5 crédits) et, seulement en cas de blocage avéré (réponse != 200 ou layout vide), faire un fallback en premium.
- **Phase 2 Extractor** : Appelé uniquement sur des nouveaux liens pour consommer de la donnée structurée (JSON-LD ciblé). Coûte cher (75 crédits), donc on le garde protégé par le check du `cache_annonces.json`.

## Consignes d'Édition
- Lors des modifications, préserver ces règles de base et ne pas altérer la logique s'il s'agit juste d'un nettoyage.
- Supprimer les imports et ressources non-utilisés.
