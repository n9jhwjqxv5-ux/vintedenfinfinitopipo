"""
BOT VINTED UNIFIÉ - Version Optimisée 24/7
Surveillance automatique d'annonces iPhone sur Vinted
- Cache persistant JSON
- Logs structurés avec rotation
- Gestion robuste des erreurs
- Optimisation data & performances
- Anti-ban intégré
"""

import discord
from discord.ext import tasks
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import asyncio
import random
import urllib.parse
import json
import os
from dotenv import load_dotenv
from collections import defaultdict
import time
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

# CONFIGURATION LOGGING
def setup_logging():
    """Configure le système de logging avec rotation de fichiers"""
    logger = logging.getLogger('vinted_bot')
    logger.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Fichier avec rotation (5 Mo max, 3 backups)
    file_handler = RotatingFileHandler(
        'vinted_bot.log',
        maxBytes=5*1024*1024,
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logging()

# CONFIGURATION ANTI-BAN
INTERVALLE_BASE_CYCLE = 117
RANDOMISATION_CYCLE = 30
DELAI_MIN_ENTRE_MODELES = 2
DELAI_MAX_ENTRE_MODELES = 4
SEUIL_ERREURS_CONSECUTIVES = 5
PAUSE_APRES_BLOCAGE = 1800

CACHE_FILE = Path("cache_annonces.json")

# NETTOYAGE URL ANTI-BAN
def clean_url(url: str) -> str:
    """
    Nettoie une URL Vinted en supprimant les paramètres de tracking/mouchards.
    Supprime: time, page, search_id (qui identifient une session/requête unique)
    Garde: search_text, price_from, price_to, status_ids (paramètres de recherche légitimes)
    """
    try:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        
        # Paramètres à supprimer (mouchards/tracking)
        params_to_remove = ['time', 'page', 'search_id']
        for param in params_to_remove:
            params.pop(param, None)
        
        # Reconstruire l'URL nettoyée
        clean_query = urllib.parse.urlencode(params, doseq=True)
        clean_url = urllib.parse.urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, clean_query, parsed.fragment
        ))
        
        return clean_url
    except Exception as e:
        logger.warning(f"Erreur nettoyage URL: {e}")
        return url  # Fallback: retourner l'URL originale

# PAUSE NOCTURNE ANTI-BAN
def is_night_hours() -> bool:
    """
    Vérifie si on est en période nocturne (3h-8h du matin).
    Aucun humain ne surveille Vinted à ces heures-là en continu.
    """
    current_hour = time.localtime().tm_hour
    return 3 <= current_hour < 8

# CHARGEMENT CONFIG
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
PROXY_URL = os.getenv("PROXY_URL")

if not DISCORD_TOKEN:
    logger.error("❌ Token Discord non configuré dans .env")
    sys.exit(1)

if PROXY_URL:
    logger.info("🔒 Proxy configuré: OUI")
else:
    logger.warning("⚠️ Aucun proxy configuré")

try:
    with open('models_config.json', 'r', encoding='utf-8') as f:
        MODELS_CONFIG = json.load(f)
    logger.info(f"✅ {len(MODELS_CONFIG)} modèles chargés")
except FileNotFoundError:
    logger.error("❌ models_config.json introuvable!")
    exit(1)

intents = discord.Intents.default()
client = discord.Client(intents=intents)

# GESTION CACHE PERSISTANT
def load_cache():
    """Charge le cache depuis le fichier JSON"""
    if not CACHE_FILE.exists():
        logger.info("Aucun cache existant, démarrage avec cache vide")
        return defaultdict(set)
    
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            cache = defaultdict(set)
            for model, links in data.items():
                cache[model] = set(links)
            logger.info(f"Cache chargé: {len(cache)} modèles, {sum(len(v) for v in cache.values())} liens")
            return cache
    except Exception as e:
        logger.error(f"Erreur chargement cache: {e}")
        return defaultdict(set)

def save_cache(cache):
    """Sauvegarde le cache dans le fichier JSON avec écriture atomique"""
    try:
        data = {model: list(links) for model, links in cache.items()}
        total_links = sum(len(links) for links in cache.values())
        
        temp_file = CACHE_FILE.with_suffix('.tmp')
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            import os
            os.fsync(f.fileno())  # Force l'écriture sur disque
        
        # Remplacement atomique (cross-platform)
        import os
        if os.name == 'nt':  # Windows
            if CACHE_FILE.exists():
                CACHE_FILE.unlink()
            temp_file.rename(CACHE_FILE)
        else:  # Linux/Mac
            temp_file.replace(CACHE_FILE)
        
        logger.info(f"💾 Cache sauvegardé: {len(cache)} modèles, {total_links} liens → {CACHE_FILE}")
    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde cache: {e}")
        # Nettoyage du fichier temporaire en cas d'erreur
        temp_file = CACHE_FILE.with_suffix('.tmp')
        if temp_file.exists():
            try:
                temp_file.unlink()
            except Exception as e:
                logger.debug(e)

derniers_items = load_cache()
erreurs_consecutives = 0
pause_jusqu_a = None
cycle_en_cours = False

# Variables Playwright
playwright_instance = None
browser = None

# Blacklist de channels Discord invalides (évite de spammer les erreurs)
channels_invalides = set()

# Compteur pour tracking ordre d'insertion dans le cache (pour tronquage correct)
cache_insertion_order = {}  # {model_name: {link: timestamp}}

# User-Agents rotatifs pour varier les empreintes
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

# MOTS INTERDITS & FILTRES
MOTS_INTERDITS = [
    "coque", "coques", "etui", "etuis", "housse", "housses", "boîte", "boite", "boites", "boîtes", "neuf", "neufs", "vitre", "vitres", "protection", "protections", 
    "chargeur", "chargeurs", "chassis", "châssis", "batterie", "batteries", "pile", "piles", "icloud", "icloud bloqué", "bloqué", "verrouillé", "verrouillage", "accessoire", "accessoires", "origine",
    "case", "cases", "cover", "covers", "box", "boxes", "new", "glass", "screen protector", "protector", "protectors",
    "charger", "charging", "frame", "chassis", "body frame", "battery", "batteries", "icloud", "icloud locked", "locked", "blocked", "activation lock", "accessory", "accessories", "origin",
    "funda", "fundas", "carcasa", "carcasas", "caja", "cajas", "nuevo", "nuevos", "vidrio", "vidrios", "protector", "protectores",
    "cargador", "cargadores", "chasis", "bastidor", "bateria", "baterias", "pila", "pilas", "icloud", "icloud bloqueado", "bloqueado", "bloqueada", "accesorio", "accesorios", "origen",
    "custodia", "custodie", "cover", "scatola", "scatole", "nuovo", "nuovi", "vetro", "vetri", "protezione", "protezioni",
    "caricatore", "caricabatterie", "telaio", "chassis", "scocca", "accessorio", "accessori", "origine",
    "hülle", "hullen", "handyhülle", "box", "karton", "verpackung", "neu", "glas", "schutzfolie", "schutzfolien", "schutz", "schutzgläser",
    "ladegerät", "netzteil", "rahmen", "gehäuse", "chassis", "zubehör", "zubehoer", "herkunft",
    "hoesje", "hoesjes", "doos", "dozen", "nieuw", "glas", "bescherming", "beschermglas", "beschermglazen",
    "oplader", "lader", "chassis", "frame", "behuizing", "accessoire", "accessoires", "oorsprong",
    "capa", "capas", "caixa", "caixas", "novo", "novos", "vidro", "vidros", "protetor", "protetores",
    "carregador", "carregadores", "chassis", "estrutura", "acessório", "acessorios", "origem",
    "etui_pl", "pudelko", "pudełko", "pudelka", "nowy", "szklo", "szkła", "ochrona", "ochronne",
    "ładowarka", "ładowarki", "obudowa", "chassis", "rama", "akcesoria", "akcesoriów", "pochodzenie",
    "låda", "kasse", "boks", "boks", "laatikko", "ny", "glas", "skydd", "skærmbeskytter", "skjermbeskytter",
    "laddare", "oplader", "chassis", "ramme", "kehys",
    "casecover", "phone case",
    "échanger", "echanger", "pro", "plus", "max", "pièce", "piece", "pièces", "pieces",
    "exchange", "part", "parts",
    "cambiar", "intercambio", "pieza", "piezas",
    "scambiare", "pezzo", "pezzi",
    "tauschen", "teil", "teile", 
    "ruilen", "stuk", "stukken", 
    "trocar", "peça", "peca", "peças", 
    "wymiana", "czesc", "część", "części", "czesci",  
    "soft oled", "hard oled", "incell", "ltps", "tft", "amoled", "oled", "lcd", "ips", 
    "recherche", "cherche", "looking for", "busco", "cerco", "suche", "szukam", "procurar", 
    "vide", "empty", "vacia", "vuota", "leer", "pusta", "vazia", 
    "demo", "demonstration", "dummy", "factice", "fictif", "gaiol", "gaiolle", "gaiola", 
    # Ajouts demandés (diverses langues et fautes de frappe)
    "paipal", "paiipal", "paypal", "pay pal", "pay-pal", 
    "carte mere", "carte mère", "carte-mere", "carte-mère", "motherboard", "mother board", "mother-board", 
    "bumper", "bumpers", "bumper case", "bumper cases", 
    "quadlock", "quad lock", "quad-lock", "fake", "fakes", "factice", "factices", "falso", "falsos", "falsa", "falsas", "gefälscht", "gefälschte", "fałszywy", "fałszywe", "falso", "falsos", 
    "antichock", "anti-chock", "antishock", "anti chock", "anti chocks", "antichoc", "anti choc", "anti-choc", "antishoc", "anti shoc", "anti-shoc", 
    "burga", "bloquer", "transfert", "transferencia", "virement", "virement bancaire", "carte abancaire", "carte bancaire", "bank transfer", "bank transfert", "WathsApp", "Whats app", "Whats-app", "what s app", "what's app",
]

ICLOUD_BLOCKED_KEYWORDS = [
    "icloudbloque", "icloudverrouille", "icloud bloqué", "icloud verrouillé",
    "icloudlocked", "icloud locked", "activationlock", "activation lock",
    "icloudbloqueado", "icloud bloqueado",
    "icloudbloccato", "icloud bloccato",
    "icloudgesperrt", "icloud gesperrt",
    "icloudvergrendeld", "icloud vergrendeld",
]

def normalize_text(s: str) -> str:
    """
    Normalise le texte en minuscules en gardant les espaces
    (nécessaire pour matcher "icloud bloqué", "screen protector", etc.)
    """
    if not s:
        return ""
    # Garder les espaces et caractères alphanumériques, enlever seulement la ponctuation
    return ' '.join(''.join(c for c in word.lower() if c.isalnum() or c in '-_') for word in s.split())

# DÉTECTION BLOCAGE
async def is_blocked_page(page) -> tuple:
    """
    Détecte si la page est bloquée/anti-bot
    Returns: (est_bloqué: bool, raison: str)
    """
    try:
        links_count = await page.locator("a").count()
        
        if links_count < 10:
            body_text = await page.text_content('body')
            if not body_text:
                return True, "Page vide"
            
            body_lower = body_text.lower()
            
            blocage_keywords = [
                "humain", "vérif", "robot", "cloudflare",
                "blocked", "access denied", "captcha",
                "verify you are human", "checking your browser",
                "attention required", "security check"
            ]
            
            if any(kw in body_lower for kw in blocage_keywords):
                return True, "Page de vérification anti-bot"
            
            if links_count == 0:
                return True, "Aucun lien trouvé"
        
        title = await page.title()
        if title and any(kw in title.lower() for kw in ["blocked", "denied", "captcha", "verify"]):
            return True, f"Titre suspect: {title}"
        
        return False, "OK"
        
    except Exception as e:
        logger.warning(f"Erreur détection blocage: {e}")
        return False, "Erreur détection"

# EXTRACTION DÉTAILS ANNONCE - OPTIMISÉE DATA
async def extract_item_details(context, lien: str, timeout: int = 7):
    """
    Extrait les détails d'une annonce - VERSION OPTIMISÉE avec retry
    Timeout réduit, extraction JSON-LD prioritaire sans fallbacks si complet
    """
    page = None
    max_retries = 2
    
    for attempt in range(max_retries):
        try:
            page = await context.new_page()
            await page.goto(lien, wait_until='domcontentloaded', timeout=timeout * 1000)
            await asyncio.sleep(0.8)  # Réduit de 1.5s à 0.8s
            break  # Succès, on sort de la boucle
        except PlaywrightTimeoutError:
            if page:
                await page.close()
                page = None
            if attempt < max_retries - 1:
                logger.debug(f"Timeout extraction (tentative {attempt + 1}/{max_retries}), retry...")
                await asyncio.sleep(1)
                continue
            else:
                logger.warning(f"Timeout extraction après {max_retries} tentatives: {lien}")
                return None
        except Exception as e:
            if page:
                await page.close()
                page = None
            if attempt < max_retries - 1:
                logger.debug(f"Erreur extraction (tentative {attempt + 1}/{max_retries}): {e}, retry...")
                await asyncio.sleep(1)
                continue
            else:
                logger.warning(f"Erreur extraction après {max_retries} tentatives {lien}: {e}")
                return None
    
    if not page:
        return None
    
    try:
        
        details = {
            'title': None,
            'description': None,
            'image_url': None,
            'price': 'N/A',
            'condition': 'Non spécifié'
        }
        
        # JSON-LD prioritaire
        json_ld_complete = False
        try:
            script_content = await page.eval_on_selector(
                'script[type="application/ld+json"]',
                'el => el.innerText'
            )
            if script_content:
                data = json.loads(script_content)
                
                # Prix
                if 'offers' in data:
                    price_val = data['offers'].get('price', '')
                    currency = data['offers'].get('priceCurrency', '€')
                    details['price'] = f"{price_val} {currency}"
                
                # Image
                if 'image' in data:
                    details['image_url'] = data['image'][0] if isinstance(data['image'], list) else data['image']
                
                # Titre
                if 'name' in data:
                    details['title'] = data['name']
                
                # Description
                if 'description' in data:
                    details['description'] = data['description']
                
                # Vérifier si JSON-LD est complet (title + price + image)
                if details['title'] and details['price'] != 'N/A' and details['image_url']:
                    json_ld_complete = True
                    logger.debug(f"JSON-LD complet, skip fallbacks")
        except Exception as e:
            logger.debug(e)
        
        # Fallbacks UNIQUEMENT si JSON-LD incomplet ou échoué
        if not json_ld_complete:
            if not details['title']:
                try:
                    meta_title = await page.query_selector("meta[property='og:title']")
                    if meta_title:
                        details['title'] = await meta_title.get_attribute('content')
                except Exception as e:
                    logger.debug(e)
            
            if not details['description']:
                try:
                    meta_desc = await page.query_selector("meta[property='og:description']")
                    if meta_desc:
                        details['description'] = await meta_desc.get_attribute('content')
                except Exception as e:
                    logger.debug(e)
            
            if not details['image_url']:
                try:
                    meta_img = await page.query_selector("meta[property='og:image']")
                    if meta_img:
                        details['image_url'] = await meta_img.get_attribute('content')
                except Exception as e:
                    logger.debug(e)
        
        # Condition (toujours vérifier car pas dans JSON-LD)
        try:
            details_list = await page.query_selector_all("div[class*='details-list__item']")
            for detail in details_list:
                text = await detail.inner_text()
                if "État" in text or "Condition" in text:
                    details['condition'] = text.split('\n')[-1].strip()
                    break
        except Exception as e:
            logger.debug(e)
        
        return details
        
    except PlaywrightTimeoutError:
        logger.warning(f"Timeout extraction: {lien}")
        return None
    except Exception as e:
        logger.warning(f"Erreur extraction {lien}: {e}")
        return None
    finally:
        if page:
            await page.close()

# PARSING PRIX
def parse_price(price_str: str):
    """
    Parse le prix depuis une string (ex: "55 €", "55 EUR", "55.0 EUR", "55,50 €")
    Retourne un float ou None si parsing impossible
    """
    """
    Parse le prix depuis une string (ex: "55 €", "55 EUR", "55.0 EUR", "55,50 €")
    Retourne un float ou None si parsing impossible
    """
    if not price_str or price_str == 'N/A':
        return None
    
    try:
        # Enlever les espaces et convertir en minuscules
        price_clean = price_str.strip().lower()
        
        # Enlever la devise (€, eur, euros, etc.)
        price_clean = price_clean.replace('€', '').replace('eur', '').replace('euros', '').strip()
        
        # Remplacer la virgule par un point pour les décimales
        price_clean = price_clean.replace(',', '.')
        
        # Extraire uniquement les chiffres, points et espaces
        price_clean = ''.join(c for c in price_clean if c.isdigit() or c == '.' or c == ' ')
        price_clean = price_clean.strip()
        
        # Prendre le premier nombre trouvé
        if ' ' in price_clean:
            price_clean = price_clean.split()[0]
        
        return float(price_clean)
    except (ValueError, AttributeError):
        return None

# VÉRIFICATION MODÈLE VINTED - OPTIMISÉE DATA
async def check_vinted_for_model(model_name: str, model_config: dict, context):
    """Vérifie Vinted pour un modèle - VERSION OPTIMISÉE"""
    url = model_config['url']
    
    # CRITIQUE ANTI-BAN: Nettoyer l'URL (supprimer time, page, search_id)
    url = clean_url(url)
    
    channel_id = model_config['channel_id']
    price_min = model_config.get('price_min')  # Optionnel
    price_max = model_config.get('price_max')  # Optionnel
    
    parsed_url = urllib.parse.urlparse(url)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    search_text = query_params.get('search_text', [''])[0]
    modele_recherche = urllib.parse.unquote(search_text).lower()
    
    modele_variantes = [
        modele_recherche,
        modele_recherche.replace(" ", "-"),
        modele_recherche.replace(" ", "_"),
        modele_recherche.replace(" ", ""),
    ]
    model_name_lower = model_name.lower()
    
    # Filtrage dynamique variantes
    modeles_exclus = ["pro", "plus", "max", "mini", "se"]
    if "pro" in model_name_lower:
        modeles_exclus = [m for m in modeles_exclus if m != "pro"]
    if "plus" in model_name_lower:
        modeles_exclus = [m for m in modeles_exclus if m != "plus"]
    if "max" in model_name_lower:
        modeles_exclus = [m for m in modeles_exclus if m != "max"]
    
    mots_interdits_adaptes = MOTS_INTERDITS.copy()
    if "pro" in model_name_lower:
        mots_interdits_adaptes = [m for m in mots_interdits_adaptes if m != "pro"]
    if "plus" in model_name_lower:
        mots_interdits_adaptes = [m for m in mots_interdits_adaptes if m != "plus"]
    if "max" in model_name_lower:
        mots_interdits_adaptes = [m for m in mots_interdits_adaptes if m != "max"]
    
    page_catalogue = None
    try:
        page_catalogue = await context.new_page()
        # Timeout réduit de 30s à 20s
        await page_catalogue.goto(url, wait_until='domcontentloaded', timeout=20000)
        await asyncio.sleep(1)  # Réduit de 2s à 1s
        
        # Détection blocage
        is_blocked_result, raison = await is_blocked_page(page_catalogue)
        if is_blocked_result:
            logger.warning(f"{model_name}: BLOCAGE - {raison}")
            return {'status': 'BLOCKED', 'annonces_envoyees': 0, 'annonces_trouvees': 0}
        
        links = await page_catalogue.query_selector_all("a")
        liens_trouves = set()
        
        for link in links:
            lien = await link.get_attribute("href")
            if not lien or "vinted.fr" not in lien or "iphone" not in lien.lower():
                continue
            
            lien_lower = lien.lower()
            
            recherche_patterns = ["/catalog", "search_text=", "/search", "?search=", "page=", "/catalogue"]
            if any(p in lien_lower for p in recherche_patterns):
                continue
            
            contient_modele = any(variante in lien_lower for variante in modele_variantes)
            if not contient_modele:
                continue
            
            exclu_par_variante = False
            for variante in modele_variantes:
                if variante in lien_lower:
                    index_modele = lien_lower.find(variante)
                    suite = lien_lower[index_modele + len(variante):index_modele + len(variante) + 15]
                    for modele_exclu in modeles_exclus:
                        if f"-{modele_exclu}" in suite or f"_{modele_exclu}" in suite or f" {modele_exclu}" in suite:
                            exclu_par_variante = True
                            break
                    if exclu_par_variante:
                        break
            
            if exclu_par_variante:
                continue
            
            if any(mot in lien_lower for mot in mots_interdits_adaptes):
                continue
            
            liens_trouves.add(lien)
        
        logger.info(f"{model_name}: {len(liens_trouves)} annonces valides")
        
        if not liens_trouves:
            return {'status': 'OK', 'annonces_envoyees': 0, 'annonces_trouvees': 0}
        
        # Vérifier si le channel est blacklisté (invalide)
        if channel_id in channels_invalides:
            logger.debug(f"{model_name}: Channel {channel_id} blacklisté, skip")
            return {'status': 'ERROR', 'annonces_envoyees': 0, 'annonces_trouvees': len(liens_trouves)}
        
        channel = client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await client.fetch_channel(channel_id)
            except discord.errors.NotFound:
                logger.error(f"{model_name}: Channel {channel_id} introuvable - blacklisté")
                channels_invalides.add(channel_id)
                return {'status': 'ERROR', 'annonces_envoyees': 0, 'annonces_trouvees': len(liens_trouves)}
            except Exception as e:
                logger.error(f"{model_name}: Erreur récupération channel {channel_id} - {e}")
                return {'status': 'ERROR', 'annonces_envoyees': 0, 'annonces_trouvees': len(liens_trouves)}
        
        nouvelles_annonces = [lien for lien in liens_trouves if lien not in derniers_items[model_name]]
        
        if nouvelles_annonces:
            logger.info(f"{model_name}: {len(nouvelles_annonces)} nouvelles annonces")
        
        annonces_envoyees = 0
        
        for lien in nouvelles_annonces:
            # Timeout extraction réduit à 7s
            details = await extract_item_details(context, lien, timeout=7)
            
            if not details:
                # Masquer l'URL dans les logs
                lien_masked = lien[:50] + "..." if len(lien) > 50 else lien
                logger.debug(f"{model_name}: Impossible d'extraire {lien_masked}")
                # Ajouter au cache même si extraction échoue (évite de réessayer)
                derniers_items[model_name].add(lien)
                if model_name not in cache_insertion_order:
                    cache_insertion_order[model_name] = {}
                cache_insertion_order[model_name][lien] = time.time()
                continue
            
            title_norm = normalize_text(details.get('title') or "")
            desc_norm = normalize_text(details.get('description') or "")
            
            if 'paypal' in desc_norm or 'paypal' in title_norm:
                logger.debug(f"{model_name}: Ignoré (PayPal)")
                # Ajouter au cache pour ne pas réessayer
                derniers_items[model_name].add(lien)
                if model_name not in cache_insertion_order:
                    cache_insertion_order[model_name] = {}
                cache_insertion_order[model_name][lien] = time.time()
                continue
            
            if any(k in desc_norm or k in title_norm for k in ICLOUD_BLOCKED_KEYWORDS):
                logger.debug(f"{model_name}: Ignoré (iCloud bloqué)")
                # Ajouter au cache pour ne pas réessayer
                derniers_items[model_name].add(lien)
                if model_name not in cache_insertion_order:
                    cache_insertion_order[model_name] = {}
                cache_insertion_order[model_name][lien] = time.time()
                continue
            
            if any(m in title_norm or m in desc_norm for m in mots_interdits_adaptes):
                logger.debug(f"{model_name}: Ignoré (mot interdit)")
                # Ajouter au cache pour ne pas réessayer
                derniers_items[model_name].add(lien)
                if model_name not in cache_insertion_order:
                    cache_insertion_order[model_name] = {}
                cache_insertion_order[model_name][lien] = time.time()
                continue
            
            # Filtrage par prix (price_min / price_max)
            if price_min is not None or price_max is not None:
                price_value = parse_price(details.get('price', ''))
                
                if price_value is None:
                    # Si on ne peut pas parser le prix, on log mais on continue (peut être "N/A" ou format inattendu)
                    logger.debug(f"{model_name}: Prix non parsable: {details.get('price', 'N/A')}")
                else:
                    # Vérifier price_min
                    if price_min is not None and price_value < price_min:
                        logger.info(f"{model_name}: Ignoré - prix {price_value}€ < price_min {price_min}€")
                        # Ajouter au cache pour ne pas réessayer
                        derniers_items[model_name].add(lien)
                        if model_name not in cache_insertion_order:
                            cache_insertion_order[model_name] = {}
                        cache_insertion_order[model_name][lien] = time.time()
                        continue
                    
                    # Vérifier price_max
                    if price_max is not None and price_value > price_max:
                        logger.info(f"{model_name}: Ignoré - prix {price_value}€ > price_max {price_max}€")
                        # Ajouter au cache pour ne pas réessayer
                        derniers_items[model_name].add(lien)
                        if model_name not in cache_insertion_order:
                            cache_insertion_order[model_name] = {}
                        cache_insertion_order[model_name][lien] = time.time()
                        continue
            
            try:
                embed = discord.Embed(
                    title=f"{details.get('title') or model_name}",
                    url=lien,
                    color=0x09B1BA
                )
                
                embed.add_field(name="💶 Prix", value=f"**{details['price']}**", inline=True)
                embed.add_field(name="📦 État", value=f"{details['condition']}", inline=True)
                
                if details.get('description'):
                    desc_short = (details['description'][:150] + '...') if len(details['description']) > 150 else details['description']
                    embed.add_field(name="📝 Description", value=desc_short, inline=False)
                
                if details.get('image_url'):
                    embed.set_image(url=details['image_url'])
                
                embed.add_field(name="🔗 Lien", value=f"[👉 Voir l'annonce sur Vinted]({lien})", inline=False)
                embed.set_footer(text=f"Vinted Bot • {model_name} • {time.strftime('%H:%M')}")
                
                await channel.send(embed=embed)
                annonces_envoyees += 1
                # Masquer l'URL dans les logs (sécurité)
                lien_masked = lien[:50] + "..." if len(lien) > 50 else lien
                logger.info(f"{model_name}: ✅ Envoyé - {details.get('title', 'Sans titre')[:50]} - {details['price']} ({lien_masked})")
                
                # Ajouter au cache APRÈS envoi réussi
                derniers_items[model_name].add(lien)
                if model_name not in cache_insertion_order:
                    cache_insertion_order[model_name] = {}
                cache_insertion_order[model_name][lien] = time.time()
                
            except discord.errors.Forbidden:
                logger.error(f"{model_name}: Permission refusée pour le channel {channel_id} - blacklisté")
                channels_invalides.add(channel_id)
                break  # Arrêter d'essayer pour ce modèle
            except discord.errors.NotFound:
                logger.error(f"{model_name}: Channel {channel_id} introuvable - blacklisté")
                channels_invalides.add(channel_id)
                break
            except discord.errors.HTTPException as e:
                # Rate limit ou autre erreur HTTP
                if e.status == 429:  # Rate limit
                    retry_after = e.retry_after if hasattr(e, 'retry_after') else 2
                    logger.warning(f"{model_name}: Rate limit Discord, attente {retry_after}s")
                    await asyncio.sleep(retry_after)
                    continue  # Réessayer ce message
                else:
                    logger.error(f"{model_name}: Erreur HTTP Discord - {e}")
            except Exception as e:
                logger.error(f"{model_name}: Erreur envoi Discord - {e}")
            
            # Délai anti-spam Discord réduit de 0.5s à 0.2s
            await asyncio.sleep(0.2)
        
        # Tronquage du cache en gardant les plus récents (par timestamp d'insertion)
        if len(derniers_items[model_name]) > 1000:
            if model_name not in cache_insertion_order:
                cache_insertion_order[model_name] = {}
            
            # Trier par timestamp (plus récent en dernier)
            liens_avec_timestamp = [
                (lien, cache_insertion_order[model_name].get(lien, 0))
                for lien in derniers_items[model_name]
            ]
            liens_avec_timestamp.sort(key=lambda x: x[1])
            
            # Garder les 500 plus récents
            liens_a_garder = {lien for lien, _ in liens_avec_timestamp[-500:]}
            derniers_items[model_name] = liens_a_garder
            
            # Nettoyer aussi cache_insertion_order
            cache_insertion_order[model_name] = {
                lien: ts for lien, ts in cache_insertion_order[model_name].items()
                if lien in liens_a_garder
            }
            
            logger.debug(f"{model_name}: Cache tronqué à 500 éléments")
        
        # Sauvegarder le cache après chaque modèle (évite perte en cas de crash)
        save_cache(derniers_items)
        
        return {'status': 'OK', 'annonces_envoyees': annonces_envoyees, 'annonces_trouvees': len(liens_trouves)}
        
    except PlaywrightTimeoutError:
        logger.warning(f"{model_name}: Timeout navigation")
        return {'status': 'ERROR', 'annonces_envoyees': 0, 'annonces_trouvees': 0}
    except Exception as e:
        logger.error(f"{model_name}: Erreur - {e}")
        return {'status': 'ERROR', 'annonces_envoyees': 0, 'annonces_trouvees': 0}
    finally:
        # Garantir la fermeture de la page même en cas d'exception
        if page_catalogue:
            try:
                await page_catalogue.close()
            except Exception as e:
                logger.debug(e)

# BOT DISCORD
@client.event
async def on_ready():
    global playwright_instance, browser
    
    logger.info(f"✅ Bot connecté: {client.user}")
    logger.info("🎭 Initialisation Playwright...")
    
    try:
        playwright_instance = await async_playwright().start()
        
        launch_args = [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-blink-features=AutomationControlled'
        ]
        
        proxy_config = None
        if PROXY_URL:
            # Masquer user:pass dans les logs si présent
            proxy_masked = PROXY_URL
            if '@' in PROXY_URL:
                parts = PROXY_URL.split('@')
                if len(parts) == 2:
                    proxy_masked = f"***@{parts[1]}"
            logger.info(f"🌍 Proxy activé: {proxy_masked}")
            proxy_config = {"server": PROXY_URL}
        else:
            logger.warning("⚠️ Aucun proxy configuré")
        
        browser = await playwright_instance.chromium.launch(
            headless=True,
            proxy=proxy_config,
            args=launch_args
        )
        
        logger.info("✅ Playwright prêt")
        check_all_models.start()
    except Exception as e:
        logger.error(f"❌ Erreur initialisation Playwright: {e}")
        raise

@tasks.loop(seconds=INTERVALLE_BASE_CYCLE)
async def check_all_models():
    """Vérifie tous les modèles - VERSION OPTIMISÉE DATA"""
    global erreurs_consecutives, pause_jusqu_a, browser, cycle_en_cours
    
    if cycle_en_cours:
        logger.warning("⚠️ Cycle en cours, skip")
        return
    
    cycle_en_cours = True
    
    try:
        # VÉRIFICATION PAUSE NOCTURNE (3h-8h) - DÉSACTIVÉE (24/7)
        # if is_night_hours():
        #     logger.info("🌙 Pause nocturne (3h-8h) - Skip cycle")
        #     return  # On reprend au prochain cycle
        
        if pause_jusqu_a and time.time() < pause_jusqu_a:
            temps_restant = int(pause_jusqu_a - time.time())
            logger.info(f"⏸️ Pause ({temps_restant//60}min {temps_restant%60}s)")
            return  # cycle_en_cours sera remis à False dans le finally
        elif pause_jusqu_a:
            logger.info("✅ Fin pause")
            pause_jusqu_a = None
            erreurs_consecutives = 0
        
        logger.info("="*60)
        logger.info(f"🔄 CYCLE - {time.strftime('%H:%M:%S')}")
        logger.info("="*60)
        
        stats = {
            'total_modeles': len(MODELS_CONFIG),
            'modeles_verifies': 0,
            'annonces_envoyees': 0,
            'annonces_trouvees': 0,
            'blocages': 0,
            'erreurs': 0
        }
        
        # Vérifier que le browser est toujours valide
        if not browser or not browser.is_connected():
            logger.error("Browser Playwright invalide, tentative de recréation...")
            try:
                if browser:
                    try:
                        await browser.close()
                    except Exception as e:
                        logger.debug(e)
                if playwright_instance:
                    try:
                        await playwright_instance.stop()
                    except Exception as e:
                        logger.debug(e)
                
                playwright_instance = await async_playwright().start()
                proxy_config = None
                if PROXY_URL:
                    proxy_config = {"server": PROXY_URL}
                browser = await playwright_instance.chromium.launch(
                    headless=True,
                    proxy=proxy_config,
                    args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-blink-features=AutomationControlled']
                )
                logger.info("✅ Browser recréé")
            except Exception as e:
                logger.error(f"❌ Impossible de recréer le browser: {e}")
                return  # cycle_en_cours sera remis à False dans le finally
        
        # User-Agent rotatif pour varier les empreintes
        user_agent = random.choice(USER_AGENTS)
        context = None
        try:
            context = await browser.new_context(
                user_agent=user_agent,
                viewport={'width': 1920, 'height': 1080},
                locale='fr-FR'
            )
        
            # BLOCAGE AGRESSIF DE TOUTES LES RESSOURCES INUTILES
            # Images: économie massive de bande passante (Discord charge les images, pas le bot)
            # CSS/Fonts: pas besoin pour scraper du JSON-LD et des URLs
            # Media: vidéos/audio jamais utilisés
            await context.route("**/*.{png,jpg,jpeg,gif,svg,webp,ico,bmp}", lambda route: route.abort())
            await context.route("**/*.{css,woff,woff2,ttf,eot}", lambda route: route.abort())
            await context.route("**/*.{mp4,webm,mp3,wav,ogg,avi}", lambda route: route.abort())
            for index, (model_name, model_config) in enumerate(MODELS_CONFIG.items()):
                try:
                    resultat = await check_vinted_for_model(model_name, model_config, context)
                    stats['modeles_verifies'] += 1
                    
                    if resultat['status'] == "BLOCKED":
                        stats['blocages'] += 1
                        erreurs_consecutives += 1
                        logger.warning(f"⚠️ Blocage ({erreurs_consecutives}/{SEUIL_ERREURS_CONSECUTIVES})")
                        
                        if erreurs_consecutives >= SEUIL_ERREURS_CONSECUTIVES:
                            pause_jusqu_a = time.time() + PAUSE_APRES_BLOCAGE
                            logger.error(f"🛑 Pause {PAUSE_APRES_BLOCAGE//60}min")
                            break
                    
                    elif resultat['status'] == "ERROR":
                        stats['erreurs'] += 1
                        erreurs_consecutives += 1
                    
                    elif resultat['status'] == "OK":
                        stats['annonces_envoyees'] += resultat['annonces_envoyees']
                        stats['annonces_trouvees'] += resultat['annonces_trouvees']
                        erreurs_consecutives = 0
                    
                except Exception as e:
                    logger.error(f"❌ Erreur {model_name}: {e}")
                    stats['erreurs'] += 1
                    erreurs_consecutives += 1
                
                # Délai anti-ban INCHANGÉ (2-4s entre modèles)
                if index < len(MODELS_CONFIG) - 1:
                    await asyncio.sleep(random.uniform(DELAI_MIN_ENTRE_MODELES, DELAI_MAX_ENTRE_MODELES))
        
        finally:
            # Garantir la fermeture du context même en cas d'exception
            if context:
                try:
                    await context.close()
                except Exception as e:
                    logger.debug(e)
        
        save_cache(derniers_items)
        
        logger.info("="*60)
        logger.info("✅ FIN CYCLE")
        logger.info(f"📊 Modèles: {stats['modeles_verifies']}/{stats['total_modeles']}")
        logger.info(f"📊 Envoyées: {stats['annonces_envoyees']} (trouvées: {stats['annonces_trouvees']})")
        logger.info(f"📊 Blocages: {stats['blocages']} | Erreurs: {stats['erreurs']}")
        logger.info(f"📊 Erreurs consécutives: {erreurs_consecutives}")
        
        prochain = INTERVALLE_BASE_CYCLE + random.randint(-RANDOMISATION_CYCLE, RANDOMISATION_CYCLE)
        logger.info(f"⏱️ Prochain: ~{prochain}s")
        logger.info("="*60)
        
    finally:
        cycle_en_cours = False

@check_all_models.before_loop
async def before_check():
    await client.wait_until_ready()

async def cleanup():
    """Fermeture propre"""
    global browser, playwright_instance
    if browser:
        await browser.close()
    if playwright_instance:
        await playwright_instance.stop()

def signal_handler(signum, frame):
    """Gestion propre des signaux (Ctrl+C, etc.)"""
    logger.info("Signal d'arrêt reçu, fermeture propre...")
    if browser or playwright_instance:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(cleanup())
            else:
                asyncio.run(cleanup())
        except Exception as e:
            logger.debug(e)
    sys.exit(0)

if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("🚀 Démarrage bot Vinted optimisé")
    logger.info("📁 Config: models_config.json")
    
    try:
        client.run(DISCORD_TOKEN)
    except KeyboardInterrupt:
        logger.info("Interruption clavier")
    except Exception as e:
        logger.error(f"Erreur fatale: {e}", exc_info=True)
    finally:
        # Nettoyage si le client.run s'est terminé proprement
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(cleanup())
            else:
                asyncio.run(cleanup())
        except RuntimeError:
            # Pas de loop en cours, on peut en créer un
            try:
                asyncio.run(cleanup())
            except Exception as e:
                logger.debug(e)
        except Exception as e:
            logger.debug(e)
