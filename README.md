# Bot Vinted - SaaS Edition

Bienvenue dans le bot de surveillance Vinted haute performance. Ce bot est conçu pour envoyer des notifications Discord ultra-rapides pour de nouvelles annonces d'iPhone, en minimisant les coûts d'API et en maximisant la robustesse.

## Architecture

Le projet est divisé en deux moteurs d'exécution :
- **`main.py`** : Mode développement / Test. Utilise **Playwright** pour scraper le site Vinted localement. Totalement gratuit (pas de crédits API), idéal pour tester ses filtres et la logique Discord avant mise en production.
- **`main_scrapingbee.py`** : Mode Production. Utilise l'API **ScrapingBee** avec des proxy tournants pour éviter les bannissements de Vinted. Conçu pour tourner 24/7 de manière autonome sur un serveur.

## Pré-requis

- Python 3.10+
- Un Bot Discord configuré (avec le token)

## Installation

1. Cloner le repository
2. Installer les dépendances :
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```
3. Copier ou créer un fichier `.env` à la racine :
   ```env
   # .env
   DISCORD_TOKEN=ton_token_discord_ici
   SCRAPINGBEE_KEY=ta_cle_api_scrapingbee
   ALERT_CHANNEL_ID=id_du_salon_discord_pour_les_crashs
   ```
   *(Pour tester avec `main.py`, seul `DISCORD_TOKEN` est strictement nécessaire).*

4. Gérer votre configuration dans `models_config.json` :
   Assurez-vous que les URLs Vinted sont "propres" (sans paramètres `time`, `page`, ou `search_id`).
   Chaque modèle doit inclure : `url`, `channel_id` (où envoyer les notifications), `price_min`, et `price_max`.

## Tester en local (Playwright)

Pour lancer le bot en mode test :
```bash
python main.py
```
Le bot va lancer des navigateurs headless et commencer à scanner. Surveillez les logs console.

## Déploiement en Production (VPS Hetzner)

Il est recommandé de déployer le bot en production à l'aide de `main_scrapingbee.py` sur un petit VPS (par exemple un plan CPX11 de Hetzner).

**Sur le VPS :**
1. Installez Python, Git et `screen`/`tmux` ou `systemd`.
2. Clonez le repo et installez via `requirements.txt`.
3. Ajoutez le `.env` avec le `DISCORD_TOKEN`, `SCRAPINGBEE_KEY` et `ALERT_CHANNEL_ID`.
4. Lancez le processus en arrière-plan :
   ```bash
   # Avec nohup
   nohup python3 main_scrapingbee.py > vinted.log 2>&1 &
   
   # Ou avec systemd (recommandé pour relance auto)
   ```

## Points Clés
- **Système de Cache** : `cache_annonces.json` mémorise les liens d'annonces déjà notifiés pour éviter de spammer lors d'un crash ou redémarrage.
- **Auto-Healing et Heures Creuses** : Le bot fait une pause entre 03:00 et 08:00 (Smart Sleep) pour économiser des appels, et gère de manière autonome les rate-limits.
