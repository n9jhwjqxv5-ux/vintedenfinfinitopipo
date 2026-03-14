#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
================================================================
BOT VINTED SCRAPINGBEE - OPTIMISÉ FINOPS <250K CRÉDITS/MOIS
================================================================
Architecture Cascade: Sentinel (1cr) → Extractor (75cr)
"""

import os
import json
import logging
import re
import asyncio
import aiohttp
import urllib.parse
from pathlib import Path
from datetime import datetime, timedelta
import random
from typing import List
from collections import defaultdict
from bs4 import BeautifulSoup
import discord
import pytz
from dotenv import load_dotenv

# CONFIGURATION & LOGGING
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# VARIABLES D'ENVIRONNEMENT
SCRAPINGBEE_KEY = os.getenv("SCRAPINGBEE_KEY")
if not SCRAPINGBEE_KEY:
    logger.error("❌ SCRAPINGBEE_KEY manquante dans .env")
    exit(1)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    logger.error("❌ DISCORD_TOKEN manquant dans .env")
    exit(1)

try:
    ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", 0))
except ValueError:
    ALERT_CHANNEL_ID = 0

SCRAPINGBEE_API_URL = "https://app.scrapingbee.com/api/v1/"

# DISCORD CLIENT
intents = discord.Intents.default()
client = discord.Client(intents=intents)

# GESTION CACHE
CACHE_FILE = Path(__file__).parent / "cache_annonces.json"

def load_cache() -> defaultdict:
    """Charge le cache depuis le fichier JSON"""
    if not CACHE_FILE.exists():
        logger.info("📦 Création d'un nouveau cache vide")
        return defaultdict(set)
    
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            cache = defaultdict(set)
            for model, links in data.items():
                cache[model] = set(links)
            total_links = sum(len(links) for links in cache.values())
            logger.info(f"📦 Cache chargé: {len(cache)} modèles, {total_links} liens")
            return cache
    except Exception as e:
        logger.error(f"❌ Erreur lecture cache: {e}, création nouveau cache")
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
            os.fsync(f.fileno())
        
        if os.name == 'nt':
            if CACHE_FILE.exists():
                CACHE_FILE.unlink()
            temp_file.rename(CACHE_FILE)
        else:
            temp_file.replace(CACHE_FILE)
        
        logger.debug(f"💾 Cache sauvegardé: {len(cache)} modèles, {total_links} liens")
    except Exception as e:
        logger.error(f"❌ Erreur sauvegarde cache: {e}")

derniers_items = load_cache()
erreurs_consecutives = 0
pause_jusqu_a = None
cycle_en_cours = False
channels_invalides = set()
dernier_cycle_complet = datetime.now()

# Statistiques FinOps
total_api_calls = 0
total_credits_used = 0

# SMART SLEEP - PAUSE NOCTURNE (PILIER 3)
def is_business_hours() -> bool:
    """
    ECO: Vérifie si on est en heures "business" (08:00-03:00 Paris time)
    Pause entre 03:00 et 08:00 = économie de ~20% des crédits API
    """
    try:
        paris_tz = pytz.timezone('Europe/Paris')
        now_paris = datetime.now(paris_tz)
        current_hour = now_paris.hour
        
        # Pause entre 3h et 8h du matin
        return not (3 <= current_hour < 8)
    except Exception as e:
        logger.warning(f"Erreur détection timezone: {e}, assume business hours")
        return True

# MOTS INTERDITS & FILTRES
MOTS_INTERDITS = [
    "coque", "coques", "etui", "etuis", "housse", "housses", "boîte", "boite", "boites", "boîtes", 
    "neuf", "neufs", "vitre", "vitres", "protection", "protections", 
    "chargeur", "chargeurs", "chassis", "châssis", "batterie", "batteries", "pile", "piles", 
    "icloud", "icloud bloqué", "bloqué", "verrouillé", "verrouillage", "accessoire", "accessoires", "origine",
    "case", "cases", "cover", "covers", "box", "boxes", "new", "glass", "screen protector", "protector", "protectors",
    "charger", "charging", "frame", "chassis", "body frame", "battery", "batteries", "icloud", "icloud locked", 
    "locked", "blocked", "activation lock", "accessory", "accessories", "origin",
    "funda", "fundas", "carcasa", "carcasas", "caja", "cajas", "nuevo", "nuevos", "vidrio", "vidrios", 
    "protector", "protectores",
    "cargador", "cargadores", "chasis", "bastidor", "bateria", "baterias", "pila", "pilas", "icloud", 
    "icloud bloqueado", "bloqueado", "bloqueada", "accesorio", "accesorios", "origen",
    "custodia", "custodie", "cover", "scatola", "scatole", "nuovo", "nuovi", "vetro", "vetri", 
    "protezione", "protezioni",
    "caricatore", "caricatori", "telaio", "scocca", "batteria", "batterie", "pila", "pile", "icloud", 
    "icloud bloccato", "bloccato", "bloccata", "accessorio", "accessori", "originale",
    "hülle", "hüllen", "etui", "schutzhülle", "schutzhüllen", "karton", "kartons", "neu", "neue", 
    "glas", "schutz", "schutzfolien",
    "ladegerät", "ladegeräte", "rahmen", "gehäuse", "akku", "akkus", "batterie", "batterien", "icloud", 
    "icloud gesperrt", "gesperrt", "gesperrte", "zubehör", "original",
    "hoesje", "hoesjes", "etui", "beschermhoes", "beschermhoezen", "doos", "dozen", "nieuw", "nieuwe", 
    "glas", "bescherming", "beschermingen",
    "oplader", "opladers", "frame", "behuizing", "batterij", "batterijen", "accu", "accus", "icloud", 
    "icloud vergrendeld", "vergrendeld", "vergrendelde", "accessoire", "accessoires", "origineel",
    "obudowa", "obudowy", "etui", "pokrowiec", "pokrowce", "pudełko", "pudełka", "nowy", "nowe", 
    "szkło", "ochrona", "zabezpieczenia",
    "ładowarka", "ładowarki", "rama", "obudowa", "bateria", "baterie", "akumulator", "akumulatory", "icloud", 
    "icloud zablokowany", "zablokowany", "zablokowana", "akcesoria", "oryginalny",
    "capa", "capas", "estojo", "estojos", "caixa", "caixas", "novo", "novos", "vidro", "vidros", 
    "proteção", "proteções",
    "carregador", "carregadores", "estrutura", "chassis", "bateria", "baterias", "pilha", "pilhas", "icloud", 
    "icloud bloqueado", "bloqueado", "bloqueada", "acessório", "acessórios", "original",
    "reparare", "repara", "reparatie", "reparer", "reparation", "repair", "repairs", "reparatur", "reparieren", 
    "riparare", "riparazione", "reparar", "reparação", "wymienić", "naprawa",
    "schimbare", "schimb", "schimba", "schimbare", "troca", "trocar", "trocar", "cambiar", "cambiare", 
    "tauschen", "uitwisselen", "change", "changes", "wymienić", "wymiana",
    "piesa", "piese", "pièce", "pièces", "piece", "pieces", "teil", "teile", "onderdeel", "onderdelen", 
    "pezzo", "pezzi", "pieza", "piezas",
    "trocar", "peça", "peca", "peças", 
    "wymiana", "czesc", "część", "części", "czesci",  
    "soft oled", "hard oled", "incell", "ltps", "tft", "amoled", "oled", "lcd", "ips", 
    "recherche", "cherche", "looking for", "busco", "cerco", "suche", "szukam", "procurar", 
    "vide", "empty", "vacia", "vuota", "leer", "pusta", "vazia", 
    "demo", "demonstration", "dummy", "factice", "fictif", "gaiol", "gaiolle", "gaiola", 
    "paipal", "paiipal", "paypal", "pay pal", "pay-pal", 
    "carte mere", "carte mère", "carte-mere", "carte-mère", "motherboard", "mother board", "mother-board", 
    "bumper", "bumpers", "bumper case", "bumper cases", 
    "quadlock", "quad lock", "quad-lock", "fake", "fakes", "factice", "factices", "falso", "falsos", 
    "falsa", "falsas", "gefälscht", "gefälschte", "fałszywy", "fałszywe", "falso", "falsos", 
    "antichock", "anti-chock", "antishock", "anti chock", "anti chocks", "antichoc", "anti choc", 
    "anti-choc", "antishoc", "anti shoc", "anti-shoc", 
    "burga", "bloquer", "transfert", "transferencia", "virement", "virement bancaire", 
    "carte abancaire", "carte bancaire", "bank transfer", "bank transfert", 
    "WathsApp", "Whats app", "Whats-app", "what s app", "what's app",
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
    """Normalise le texte pour le filtrage"""
    if not s:
        return ""
    return ' '.join(''.join(c for c in word.lower() if c.isalnum() or c in '-_') for word in s.split())

# PARSING PRIX AMÉLIORÉ (PILIER 4)
def parse_price(price_str: str) -> float:
    """
    Parse le prix depuis une string avec Regex améliorée
    Supporte: "150,00€", "150.00 eur", "150€", "150 EUR", etc.
    """
    if not price_str or price_str == 'N/A':
        return None
    
    try:
        match = re.search(r'(\d+(?:[.,]\d+)?)', price_str)
        if match:
            price_clean = match.group(1).replace(',', '.')
            return float(price_clean)
        return None
    except (ValueError, AttributeError):
        return None

# NETTOYAGE URL ANTI-BAN
def clean_url(url: str) -> str:
    """
    Nettoie une URL Vinted en supprimant les paramètres de tracking
    Supprime: time, page, search_id
    """
    try:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        
        params_to_remove = ['time', 'page', 'search_id']
        for param in params_to_remove:
            params.pop(param, None)
        
        clean_query = urllib.parse.urlencode(params, doseq=True)
        clean_url_result = urllib.parse.urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, clean_query, parsed.fragment
        ))
        
        return clean_url_result
    except Exception as e:
        logger.warning(f"Erreur nettoyage URL: {e}")
        return url

# PHASE 1 : SENTINEL (LOW-COST) - PILIER 1
async def fetch_catalog_links(url: str, model_name: str) -> List[str]:
    """
    ✅ PILIER 1 : CASCADE - Phase SENTINEL (1 crédit ou 75cr)
    Récupère les liens avec render_js=true selon contraintes
    """
    global total_api_calls, total_credits_used
    
    logger.info(f"🔍 [SENTINEL] Scraping catalogue {model_name}: {url}")
    
    try:
        # ESSAI 1: Standard proxy (1 crédit) mais avec render_js=true comme demandé
        params = {
            'api_key': SCRAPINGBEE_KEY,
            'url': url,
            'render_js': 'true',
            'premium_proxy': 'false',   # Standard proxy
            'country_code': 'fr'
        }
        
        logger.info(f"💰 [FINOPS] Tentative Standard Proxy pour {model_name}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(SCRAPINGBEE_API_URL, params=params, timeout=aiohttp.ClientTimeout(total=45)) as response:
                if response.status == 200:
                    html = await response.text()
                    total_api_calls += 1
                    total_credits_used += 5 # render_js coute 5cr sur standard
                    logger.info(f"✅ Standard Proxy réussi pour catalogue")
                else:
                    raise Exception(f"ScrapingBee HTTP {response.status}")
        
    except Exception as e_standard:
        logger.warning(f"⚠️ Standard Proxy bloqué pour {model_name}, FALLBACK Premium...")
        try:
            # ESSAI 2: Premium proxy (75 crédits)
            params = {
                'api_key': SCRAPINGBEE_KEY,
                'url': url,
                'render_js': 'true',
                'premium_proxy': 'true',  # Premium proxy
                'country_code': 'fr'
            }
            logger.info(f"💰 [FINOPS] Tentative Premium Proxy pour {model_name}")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(SCRAPINGBEE_API_URL, params=params, timeout=aiohttp.ClientTimeout(total=45)) as response:
                    if response.status == 200:
                        html = await response.text()
                        total_api_calls += 1
                        total_credits_used += 75
                        logger.info(f"✅ Premium Proxy réussi")
                    else:
                        raise Exception(f"ScrapingBee HTTP {response.status}")
        
        except Exception as e_premium:
            logger.error(f"❌ Échec Premium Proxy pour {model_name}: {e_premium}")
            return []
    
    # PARSING AVEC LOGIQUE VARIANTES ET EXTRACTION DIRECTE <a href>
    soup = BeautifulSoup(html, 'lxml')
    
    # Préparation de la logique de filtrage
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

    liens_trouves = set()
    a_tags = soup.find_all('a', href=True)
    
    for a_tag in a_tags:
        lien = a_tag['href']
        if lien.startswith('/'):
            lien = f"https://www.vinted.fr{lien}"
            
        if not lien or "vinted.fr" not in lien.lower() or "iphone" not in lien.lower():
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
        
        if any(normalize_text(mot) in normalize_text(lien_lower) for mot in mots_interdits_adaptes):
            continue
            
        liens_trouves.add(clean_url(lien))
    
    logger.info(f"✅ {len(liens_trouves)} liens trouvés pour {model_name}")
    return list(liens_trouves)

# PHASE 2 : EXTRACTOR (PREMIUM) - PILIER 1
async def extract_item_details(lien: str, model_name: str) -> dict:
    """
    ✅ PILIER 1 : CASCADE - Phase EXTRACTOR (75 crédits)
    UNIQUEMENT appelé pour les NOUVEAUX liens (non en cache)
    """
    global total_api_calls, total_credits_used
    
    logger.info(f"🔎 [EXTRACTOR] Extraction détails: {lien}")
    
    try:
        # Premium proxy + render_js = 75 crédits
        params = {
            'api_key': SCRAPINGBEE_KEY,
            'url': lien,
            'render_js': 'true',       # Nécessaire pour JSON-LD complet
            'premium_proxy': 'true',   # Premium obligatoire pour pages détails
            'country_code': 'fr'
        }
        
        logger.info(f"💰 [FINOPS] Extraction Premium (75 crédits) pour {model_name}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(SCRAPINGBEE_API_URL, params=params, timeout=aiohttp.ClientTimeout(total=45)) as response:
                if response.status != 200:
                    logger.error(f"❌ ScrapingBee HTTP {response.status} pour {lien}")
                    return None
                
                html = await response.text()
                total_api_calls += 1
                total_credits_used += 75
        
        soup = BeautifulSoup(html, 'lxml')
        
        # Extraction JSON-LD (prioritaire)
        json_ld_script = soup.find('script', {'type': 'application/ld+json'})
        titre, prix_str, image = None, None, None
        
        if json_ld_script:
            try:
                data = json.loads(json_ld_script.string)
                titre = data.get('name', 'N/A')
                
                offers = data.get('offers', {})
                prix_str = str(offers.get('price', 'N/A'))
                
                image = data.get('image', 'N/A')
            except json.JSONDecodeError:
                logger.warning(f"Erreur parsing JSON-LD pour {lien}")
        
        # Fallback si JSON-LD échoue
        if not titre or titre == 'N/A':
            titre_tag = soup.find('meta', {'property': 'og:title'})
            titre = titre_tag['content'] if titre_tag else 'N/A'
        
        if not prix_str or prix_str == 'N/A':
            prix_tag = soup.find('meta', {'property': 'product:price:amount'})
            prix_str = prix_tag['content'] if prix_tag else 'N/A'
        
        if not image or image == 'N/A':
            image_tag = soup.find('meta', {'property': 'og:image'})
            image = image_tag['content'] if image_tag else 'N/A'
        
        prix = parse_price(prix_str)
        
        return {
            'titre': titre,
            'prix': prix,
            'lien': lien,
            'image': image
        }
    
    except Exception as e:
        logger.error(f"❌ Erreur extraction {lien}: {e}")
        return None

# FILTRAGE ANNONCES
def filtrer_annonce(details: dict, config: dict) -> bool:
    """Filtre une annonce selon les critères configurés"""
    if not details or not details.get('titre'):
        return False
    
    titre = details['titre']
    titre.lower()
    titre_norm = normalize_text(titre)
    
    # Vérification mots interdits
    for mot in MOTS_INTERDITS:
        mot_norm = normalize_text(mot)
        if mot_norm in titre_norm:
            logger.debug(f"❌ Mot interdit '{mot}' détecté dans: {titre}")
            return False
    
    # Vérification iCloud bloqué
    for keyword in ICLOUD_BLOCKED_KEYWORDS:
        keyword_norm = normalize_text(keyword)
        if keyword_norm in titre_norm:
            logger.debug(f"❌ iCloud bloqué détecté dans: {titre}")
            return False
    
    # Vérification prix
    prix = details.get('prix')
    if prix is None:
        logger.debug(f"❌ Prix invalide pour: {titre}")
        return False
    
    prix_min = config.get('price_min', 0)
    prix_max = config.get('price_max', 99999)
    
    if not (prix_min <= prix <= prix_max):
        logger.debug(f"❌ Prix {prix}€ hors limites [{prix_min}-{prix_max}] pour: {titre}")
        return False
    
    logger.info(f"✅ Annonce valide: {titre} - {prix}€")
    return True

# ENVOI MESSAGE DISCORD
async def send_discord_message(channel_id: int, details: dict):
    """Envoie un message Discord formaté"""
    try:
        channel = client.get_channel(channel_id)
        if not channel:
            logger.error(f"❌ Channel {channel_id} introuvable")
            return
        
        embed = discord.Embed(
            title=details['titre'],
            url=details['lien'],
            color=discord.Color.green()
        )
        
        if details.get('prix'):
            embed.add_field(name="💰 Prix", value=f"{details['prix']}€", inline=True)
        
        if details.get('image') and details['image'] != 'N/A':
            embed.set_thumbnail(url=details['image'])
        
        embed.set_footer(text=f"🤖 Bot Vinted | {datetime.now().strftime('%H:%M:%S')}")
        
        await channel.send(embed=embed)
        logger.info(f"📨 Message Discord envoyé: {details['titre']}")
    
    except Exception as e:
        logger.error(f"❌ Erreur envoi Discord: {e}")

# CHECK VINTED POUR UN MODÈLE (PILIER 2 - ASYNC)
async def check_vinted_for_model(model_name: str, config: dict, semaphore_global: asyncio.Semaphore):
    """
    ✅ PILIER 2 : ASYNC PERFORMANCE
    Scrape avec architecture Cascade + concurrence contrôlée
    """
    global derniers_items, total_api_calls, total_credits_used
    
    url_catalog = config.get('url')
    channel_id = config.get('channel_id')
    
    if not url_catalog or not channel_id:
        logger.warning(f"⚠️ Config invalide pour {model_name}")
        return
    
    try:
        async with semaphore_global:
            # PHASE 1: Sentinel (Low-Cost)
            links = await fetch_catalog_links(url_catalog, model_name)
            
            if not links:
                logger.info(f"Aucun lien trouvé pour {model_name}")
                return
            
            # Filtrer les nouveaux liens
            cached_links = derniers_items[model_name]
            nouveaux_links = [l for l in links if l not in cached_links]
            
            logger.info(f"📊 {model_name}: {len(links)} liens totaux, {len(nouveaux_links)} nouveaux")
            
            if not nouveaux_links:
                logger.info(f"Aucune nouvelle annonce pour {model_name}")
                return
            
            # PHASE 2: Extractor (Premium) - Seulement pour nouveaux liens
            # Concurence locale pour ce modèle
            semaphore_details = asyncio.Semaphore(3)
            
            async def process_link(lien):
                async with semaphore_details:
                    details = await extract_item_details(lien, model_name)
                    if details and filtrer_annonce(details, config):
                        await send_discord_message(channel_id, details)
                    
                    # Ajouter au cache APRÈS traitement (même si échec)
                    derniers_items[model_name].add(lien)
                    
                    # Anti-ban: Sleep aléatoire entre liens
                    await asyncio.sleep(random.uniform(2, 5))
            
            # Traiter tous les nouveaux liens en parallèle
            await asyncio.gather(*[process_link(lien) for lien in nouveaux_links])
            
            # Sauvegarder le cache après chaque modèle
            save_cache(derniers_items)
            
            logger.info(f"✅ {model_name} traité - API calls: {total_api_calls}, Crédits: {total_credits_used}")
    
    except Exception as e:
        logger.error(f"❌ Erreur check_vinted_for_model {model_name}: {e}")

# SUPERSION CRASH MULTI-CYCLES
async def crash_monitor_loop():
    """
    Vérifie toutes les 2 minutes si un cycle s'est correctement terminé.
    S'il n'y a pas eu de cycle terminé depuis plus de 10 min, envoie une alerte.
    """
    await client.wait_until_ready()
    logger.info("🛡️ Crash Monitor démarré")
    
    while not client.is_closed():
        await asyncio.sleep(120)  # Check toutes les 2 minutes
        temps_ecoule = (datetime.now() - dernier_cycle_complet).total_seconds()
        
        # 10 minutes = 600 secondes
        if temps_ecoule > 600:
            msg = f"⚠️ **ALERTE CRASH BOT SCRAPINGBEE** ⚠️\nAucun cycle terminé depuis {int(temps_ecoule//60)} minutes. Le bot est peut-être bloqué !"
            logger.error(f"🛑 {msg}")
            
            if ALERT_CHANNEL_ID:
                try:
                    channel = client.get_channel(ALERT_CHANNEL_ID)
                    if channel:
                        await channel.send(msg)
                except Exception as e:
                    logger.error(f"Erreur envoi alerte crash Discord: {e}")

# BOUCLE PRINCIPALE (PILIER 3 - SMART SLEEP)
async def main_loop():
    """
    ✅ PILIER 3 : SMART SLEEP
    Boucle principale avec pause nocturne 03:00-08:00
    """
    global erreurs_consecutives, pause_jusqu_a, cycle_en_cours, dernier_cycle_complet
    
    await client.wait_until_ready()
    logger.info("🤖 Bot connecté à Discord")
    
    # Charger models_config.json
    config_path = Path(__file__).parent / "models_config.json"
    if not config_path.exists():
        logger.error("❌ models_config.json introuvable")
        return
    
    with open(config_path, 'r', encoding='utf-8') as f:
        models_config = json.load(f)
    
    logger.info(f"📋 {len(models_config)} modèles chargés")
    
    while True:
        try:
            if not is_business_hours():
                logger.info("😴 Pause nocturne (03:00-08:00), repos...")
                # Reset le compteur pour ne pas alerter pendant la nuit
                dernier_cycle_complet = datetime.now()
                await asyncio.sleep(600)  # 10 minutes
                continue
            
            if pause_jusqu_a and datetime.now() < pause_jusqu_a:
                wait_seconds = (pause_jusqu_a - datetime.now()).total_seconds()
                logger.warning(f"⏸️ Pause cooldown: {int(wait_seconds)}s restantes")
                # Reset temporaire pour tracker le vrai crash vs la pause volontaire
                dernier_cycle_complet = datetime.now() 
                await asyncio.sleep(min(wait_seconds, 60))
                continue
            
            cycle_en_cours = True
            logger.info("🔄 Démarrage cycle de scraping")
            
            # Semaphore global pour Gather (5 max)
            global_semaphore = asyncio.Semaphore(5)
            
            # Traiter tous les modèles en parallèle avec Gather
            await asyncio.gather(*[
                check_vinted_for_model(name, config, global_semaphore) 
                for name, config in models_config.items()
            ])
            
            # Réinitialiser compteur erreurs si cycle réussi
            erreurs_consecutives = 0
            cycle_en_cours = False
            dernier_cycle_complet = datetime.now()  # MAJ du timestamp pour le monitor
            
            # Sleep entre cycles (117s par défaut)
            sleep_time = random.uniform(110, 125)
            logger.info(f"✅ Cycle terminé, sleep {int(sleep_time)}s")
            await asyncio.sleep(sleep_time)
        
        except Exception as e:
            logger.error(f"❌ Erreur boucle principale: {e}")
            erreurs_consecutives += 1
            cycle_en_cours = False
            
            if erreurs_consecutives >= 5:
                cooldown_minutes = 10
                pause_jusqu_a = datetime.now() + timedelta(minutes=cooldown_minutes)
                logger.warning(f"⏸️ Trop d'erreurs ({erreurs_consecutives}), pause {cooldown_minutes} min")
            
            await asyncio.sleep(30)

# DÉMARRAGE BOT
@client.event
async def on_ready():
    """Événement Discord: Bot prêt"""
    logger.info(f"✅ Bot Discord connecté: {client.user}")
    client.loop.create_task(main_loop())
    client.loop.create_task(crash_monitor_loop())

if __name__ == "__main__":
    logger.info("🚀 Démarrage Bot Vinted ScrapingBee")
    client.run(DISCORD_TOKEN)
