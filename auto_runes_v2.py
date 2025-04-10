#!/usr/bin/env python
import os
import sys
import json
import time
import base64
import psutil
import urllib3
import requests
import websocket
import threading
import logging
from typing import Dict, List, Any, Optional

# Setup logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("auto_runes_v2.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("AutoRunes")
success_logger = logging.getLogger("AutoRunesSuccess")
success_logger.setLevel(logging.INFO)
for handler in logger.handlers:
    success_logger.addHandler(handler)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class LCUConnection:
    """Handles connection to the League Client Update (LCU) API"""
    
    def __init__(self):
        self.auth_token = None
        self.port = None
        self.process = None
        self.headers = None
        self.base_url = None
        self.ws = None
        self.connected = False
        self.ws_connected = False
    
    def find_league_client(self) -> bool:
        """Find the League of Legends client process and extract connection info"""
        if self.connected and self.process and self.process.is_running():
            return True
            
        self.connected = False
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            if proc.info['name'] == 'LeagueClientUx.exe':
                self.process = proc
                cmdline = proc.cmdline()
                
                auth_token = next((x for x in cmdline if x.startswith('--remoting-auth-token=')), None)
                port = next((x for x in cmdline if x.startswith('--app-port=')), None)
                
                if auth_token and port:
                    self.auth_token = auth_token.split('=')[1]
                    self.port = port.split('=')[1]
                    
                    userpass = f'riot:{self.auth_token}'
                    encoded_credentials = base64.b64encode(userpass.encode('utf-8')).decode('utf-8')
                    self.headers = {
                        'Authorization': f'Basic {encoded_credentials}',
                        'Content-Type': 'application/json',
                        'Accept': 'application/json'
                    }
                    self.base_url = f'https://127.0.0.1:{self.port}'
                    self.connected = True
                    success_logger.info("Successfully connected to League Client")
                    return True
        
        return False
    
    def request(self, method: str, endpoint: str, data: Any = None) -> Optional[Dict]:
        """Send an HTTP request to the LCU API"""
        if not self.connected and not self.find_league_client():
            return None
                
        url = f'{self.base_url}{endpoint}'
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
                verify=False
            )
            
            if response.status_code == 404:
                return None
                
            response.raise_for_status()
            
            if response.text:
                return response.json()
            return {}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error connecting to LCU API: {e}")
            self.connected = False
            return None
    
    def establish_websocket(self, callback) -> bool:
        """Connect to the LCU websocket for real-time updates"""
        if self.ws_connected and self.ws:
            return True
            
        if not self.connected and not self.find_league_client():
            return False
        
        userpass = f'riot:{self.auth_token}'
        encoded_credentials = base64.b64encode(userpass.encode('utf-8')).decode('utf-8')
        
        ws_url = f"wss://127.0.0.1:{self.port}/"
        ws_headers = {
            "Authorization": f"Basic {encoded_credentials}"
        }
        
        def on_message(ws, message):
            try:
                callback(json.loads(message))
            except json.JSONDecodeError:
                pass
            
        def on_error(ws, error):
            logger.error(f"WebSocket error: {error}")
            self.ws_connected = False
            
        def on_close(ws, close_status_code, close_msg):
            logger.info("WebSocket connection closed")
            self.ws_connected = False
            
        def on_open(ws):
            success_logger.info("WebSocket connection established")
            ws.send(json.dumps([5, 'OnJsonApiEvent']))
            self.ws_connected = True
            
        websocket.enableTrace(False)
        self.ws = websocket.WebSocketApp(
            ws_url,
            header=ws_headers,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        
        wst = threading.Thread(target=self.ws.run_forever, kwargs={'sslopt': {"cert_reqs": 0}})
        wst.daemon = True
        wst.start()
        
        # Give a moment for the connection to establish
        time.sleep(1)
        return self.ws_connected

class RuneManager:
    """Manages rune page creation and updates through the LCU API"""
    
    def __init__(self, lcu_connection: LCUConnection):
        self.lcu = lcu_connection
        self.current_page_id = None
        self.rune_data = {}
        self.lock = threading.Lock()
        
        # Define mappings
        self.path_id_map = {
            "Precision": 8000,
            "Domination": 8100,
            "Sorcery": 8200,
            "Inspiration": 8300,
            "Resolve": 8400
        }
        
        # Simplified rune map
        self.rune_id_map = {
            # Precision
            "Press the Attack": 8005,
            "Lethal Tempo": 8008,
            "Fleet Footwork": 8021,
            "Conqueror": 8010,
            "Absorb Life": 9101,
            "Triumph": 9111,
            "Presence of Mind": 8009,
            "Legend: Alacrity": 9104,
            "Legend: Haste": 9105,
            "Legend: Bloodline": 9103,
            "Coup de Grace": 8014,
            "Cut Down": 8017,
            "Last Stand": 8299,
            
            # Domination
            "Electrocute": 8112,
            "Predator": 8124,
            "Dark Harvest": 8128,
            "Hail of Blades": 9923,
            "Cheap Shot": 8126,
            "Taste of Blood": 8139,
            "Sudden Impact": 8143,
            "Sixth Sense": 8137,
            "Grisly Mementos": 8140,
            "Deep Ward": 8141,
            "Treasure Hunter": 8135,
            "Relentless Hunter": 8105,
            "Ultimate Hunter": 8106,
            
            # Sorcery
            "Summon Aery": 8214,
            "Arcane Comet": 8229,
            "Phase Rush": 8230,
            "Axiom Arcanist": 8224,
            "Manaflow Band": 8226,
            "Nimbus Cloak": 8275,
            "Transcendence": 8210,
            "Celerity": 8234,
            "Absolute Focus": 8233,
            "Scorch": 8237,
            "Waterwalking": 8232,
            "Gathering Storm": 8236,
            
            # Resolve
            "Grasp of the Undying": 8437,
            "Aftershock": 8439,
            "Guardian": 8465,
            "Demolish": 8446,
            "Font of Life": 8463,
            "Shield Bash": 8401,
            "Conditioning": 8429,
            "Second Wind": 8444,
            "Bone Plating": 8473,
            "Overgrowth": 8451,
            "Revitalize": 8453,
            "Unflinching": 8242,
            
            # Inspiration
            "Glacial Augment": 8351,
            "Unsealed Spellbook": 8360,
            "First Strike": 8369,
            "Hextech Flashtraption": 8306,
            "Magical Footwear": 8304,
            "Cash Back": 8321,
            "Triple Tonic": 8313,
            "Time Warp Tonic": 8352,
            "Biscuit Delivery": 8345,
            "Cosmic Insight": 8347,
            "Approach Velocity": 8410,
            "Jack Of All Trades": 8316,
            
            # Stat shards
            "Adaptive Force": 5008,
            "Attack Speed": 5005,
            "Ability Haste": 5007,
            "Move Speed": 5010,
            "Tenacity and Slow Resist": 5013,
            "Health": 5011,
            "Health Scaling": 5001
        }
    
    def load_rune_data_from_file(self, champion_name: str) -> bool:
        """Load rune data for a specific champion from the rune_data.json file"""
        try:
            if not os.path.exists("rune_data.json"):
                return False
                
            with open("rune_data.json", "r") as f:
                scraped_data = json.load(f)
            
            if scraped_data.get("champion", "").lower() != champion_name.lower():
                return False
                
            # Get paths
            primary_path = scraped_data.get("primary_path")
            secondary_path = scraped_data.get("secondary_path")
            
            if not primary_path or not secondary_path:
                return False
                
            primary_style_id = self.path_id_map.get(primary_path, 8000)
            secondary_style_id = self.path_id_map.get(secondary_path, 8400)
            
            selected_perks = []
            
            # Process keystone
            keystone_name = scraped_data.get("keystone")
            if not keystone_name:
                return False
                
            keystone_id = self.find_rune_id(keystone_name)
            if not keystone_id:
                return False
                
            selected_perks.append(keystone_id)
            
            # Process primary runes
            for rune_name in scraped_data.get("primary_runes", []):
                rune_id = self.find_rune_id(rune_name)
                if rune_id:
                    selected_perks.append(rune_id)
            
            # Process secondary runes
            for rune_name in scraped_data.get("secondary_runes", []):
                rune_id = self.find_rune_id(rune_name)
                if rune_id:
                    selected_perks.append(rune_id)
            
            # Process stat shards
            for shard_name in scraped_data.get("stat_shards", []):
                shard_id = self.find_rune_id(shard_name)
                if shard_id:
                    selected_perks.append(shard_id)
            
            # Validate we have exactly 9 perks
            if len(selected_perks) != 9:
                logger.error(f"Invalid number of perks: {len(selected_perks)}. Expected 9.")
                return False
            
            # Store the processed data
            self.rune_data[champion_name] = {
                "auto": {
                    "primary_style": primary_style_id,
                    "sub_style": secondary_style_id,
                    "selected_perks": selected_perks
                }
            }
            
            success_logger.info(f"Successfully loaded rune data for {champion_name}")
            return True
        except Exception as e:
            logger.error(f"Error loading rune data: {e}")
            return False
    
    def find_rune_id(self, rune_name: str) -> Optional[int]:
        """Find a rune ID by name, with fuzzy matching if needed"""
        # Direct match
        if rune_name in self.rune_id_map:
            return self.rune_id_map[rune_name]
        
        # Fuzzy match
        for known_name, known_id in self.rune_id_map.items():
            if known_name.lower() in rune_name.lower() or rune_name.lower() in known_name.lower():
                return known_id
        
        return None
    
    def fetch_runes_for_champion(self, champion_name: str) -> bool:
        """Fetch runes for a champion using the headless scraper"""
        with self.lock:  # Prevent multiple simultaneous fetches for the same champion
            try:
                # Try headless scraper first
                try:
                    from headless_scraper import get_runes_headless
                    success_logger.info(f"Fetching runes for {champion_name} using headless scraper")
                    get_runes_headless(champion_name.lower())
                    return self.load_rune_data_from_file(champion_name)
                except ImportError:
                    # Fall back to app.py
                    from app import get_full_rune_tree # type: ignore
                    success_logger.info(f"Fetching runes for {champion_name} using app.py")
                    get_full_rune_tree(champion_name.lower())
                    return self.load_rune_data_from_file(champion_name)
            except ImportError:
                # Try subprocess as a last resort
                try:
                    import subprocess
                    # Try headless_scraper.py
                    try:
                        result = subprocess.run(
                            [sys.executable, "headless_scraper.py", champion_name.lower()],
                            capture_output=True, text=True
                        )
                        if result.returncode == 0:
                            return self.load_rune_data_from_file(champion_name)
                    except FileNotFoundError:
                        pass
                    
                    # Try app.py
                    result = subprocess.run(
                        [sys.executable, "app.py"],
                        input=champion_name.encode(),
                        capture_output=True, text=True
                    )
                    return self.load_rune_data_from_file(champion_name)
                except Exception as e:
                    logger.error(f"Error running scraper: {e}")
                    return False
    
    def apply_runes_for_champion(self, champion_name: str) -> bool:
        """Apply runes for a specific champion"""
        # Get rune data for champion
        if champion_name not in self.rune_data:
            if not self.fetch_runes_for_champion(champion_name):
                return False
                
        if champion_name not in self.rune_data:
            return False
            
        # Use the "auto" role by default
        role = "auto"
        rune_setup = self.rune_data[champion_name][role]
        
        # Validate rune setup
        if not rune_setup.get("primary_style") or not rune_setup.get("sub_style"):
            return False
            
        selected_perks = rune_setup.get("selected_perks", [])
        if len(selected_perks) != 9:
            return False
            
        # Get existing rune pages
        pages = self.lcu.request('GET', '/lol-perks/v1/pages') or []
        
        try:
            if pages:
                # Find auto page or use first available
                auto_rune_page = next((p for p in pages if p['name'].startswith('[AUTO]')), None)
                page_id = auto_rune_page['id'] if auto_rune_page else pages[0]['id']
                
                # Update the page
                result = self.lcu.request('PUT', f'/lol-perks/v1/pages/{page_id}', {
                    "name": f"[AUTO] {champion_name} - {role}",
                    "primaryStyleId": rune_setup['primary_style'],
                    "subStyleId": rune_setup['sub_style'],
                    "selectedPerkIds": rune_setup['selected_perks'],
                    "current": True
                })
                
                if result is not None:
                    success_logger.info(f"Successfully updated rune page for {champion_name}")
                    return True
            else:
                # Create a new page
                result = self.lcu.request('POST', '/lol-perks/v1/pages', {
                    "name": f"[AUTO] {champion_name} - {role}",
                    "primaryStyleId": rune_setup['primary_style'],
                    "subStyleId": rune_setup['sub_style'],
                    "selectedPerkIds": rune_setup['selected_perks'],
                    "current": True
                })
                
                if result and 'id' in result:
                    self.current_page_id = result['id']
                    success_logger.info(f"Successfully created rune page for {champion_name}")
                    return True
            
            return False
        except Exception as e:
            logger.error(f"Error applying runes: {e}")
            return False

class ChampionSelectMonitor:
    """Monitors champion selection phase and triggers rune updates"""
    
    def __init__(self, lcu_connection: LCUConnection, rune_manager: RuneManager):
        self.lcu = lcu_connection
        self.rune_manager = rune_manager
        self.current_champion = None
        self.current_phase = None
        self.running = False
        self.lock = threading.Lock()
        self.processed_action_ids = set()
    
    def on_champion_locked(self, champion_name: str, action_id: str):
        """Handle champion lock-in event"""
        # Skip already processed actions
        if action_id in self.processed_action_ids:
            return
            
        with self.lock:
            self.processed_action_ids.add(action_id)
            success_logger.info(f"Champion locked in: {champion_name}")
            
            try:
                start_time = time.time()
                
                # Apply runes, with retry on failure
                success = self.rune_manager.apply_runes_for_champion(champion_name)
                elapsed_time = time.time() - start_time
                
                if success:
                    success_logger.info(f"Applied runes for {champion_name} in {elapsed_time:.2f} seconds")
                else:
                    logger.info("Attempting to fetch and apply runes one more time...")
                    if self.rune_manager.fetch_runes_for_champion(champion_name):
                        success = self.rune_manager.apply_runes_for_champion(champion_name)
                        if success:
                            success_logger.info(f"Successfully applied runes on second attempt for {champion_name}")
            except Exception as e:
                logger.error(f"Error in champion lock-in handler: {e}")
    
    def start(self):
        """Start monitoring champion select"""
        self.running = True
        
        def handle_ws_message(message):
            # Only process champion select session events
            if len(message) < 3 or message[2].get('uri') != '/lol-champ-select/v1/session':
                return
                
            data = message[2].get('data', {})
            
            # Track phase changes
            phase = data.get('timer', {}).get('phase')
            if phase and phase != self.current_phase:
                self.current_phase = phase
                
                # Reset when exiting champion select
                if phase == "None":
                    self.current_champion = None
                    self.processed_action_ids.clear()
                    return
            
            # Skip if no data or not in champion select
            if not data or not self.current_phase:
                return
            
            # Get local player
            local_player = self.lcu.request('GET', '/lol-summoner/v1/current-summoner')
            if not local_player:
                return
                
            # Find local player's actions
            local_player_id = local_player.get('summonerId')
            local_cell = None
            
            for player in data.get('myTeam', []):
                if player.get('summonerId') == local_player_id:
                    local_cell = player.get('cellId')
                    break
            
            if local_cell is None:
                return
                
            # Find the player's actions
            for action_group in data.get('actions', []):
                for action in action_group:
                    if action.get('actorCellId') == local_cell:
                        champion_id = action.get('championId')
                        action_id = action.get('id')
                        
                        # Skip if no champion selected
                        if not champion_id or champion_id == 0:
                            continue
                            
                        # Get champion data
                        champion_data = self.lcu.request('GET', f'/lol-champions/v1/inventories/{local_player_id}/champions/{champion_id}')
                        if not champion_data:
                            continue
                            
                        champion_name = champion_data.get('name')
                        if not champion_name:
                            continue
                            
                        # Handle champion selection - clear processed actions if champion changes
                        if champion_name != self.current_champion:
                            self.current_champion = champion_name
                            # Clear processed action IDs when champion changes
                            self.processed_action_ids.clear()
                        
                        # If champion locked in and action not processed yet, apply runes
                        if action.get('completed') and action_id not in self.processed_action_ids:
                            self.on_champion_locked(champion_name, action_id)
        
        # Start WebSocket connection
        if self.lcu.establish_websocket(handle_ws_message):
            logger.info("Champion select monitor started")
            
            # Main loop to check for connection
            while self.running:
                if not self.lcu.connected or not self.lcu.ws_connected:
                    if self.lcu.find_league_client():
                        self.lcu.establish_websocket(handle_ws_message)
                
                time.sleep(5)
        else:
            logger.error("Failed to establish websocket connection")
    
    def stop(self):
        """Stop monitoring champion select"""
        self.running = False
        logger.info("Champion select monitor stopped")

class AutoRunesService:
    """Main service that runs in the background"""
    
    def __init__(self):
        self.lcu = LCUConnection()
        self.rune_manager = RuneManager(self.lcu)
        self.monitor = None
        self.running = False
    
    def start(self):
        """Start the auto runes service"""
        self.running = True
        logger.info("Auto Runes service starting")
        
        while self.running:
            if not self.lcu.connected:
                # Only try to connect if not already connected
                if self.lcu.find_league_client():
                    if not self.monitor:
                        # Start monitoring if connected and monitor not running
                        self.monitor = ChampionSelectMonitor(self.lcu, self.rune_manager)
                        monitor_thread = threading.Thread(target=self.monitor.start)
                        monitor_thread.daemon = True
                        monitor_thread.start()
                        logger.info("League client detected, monitoring started")
                else:
                    # Not connected and connection attempt failed
                    logger.info("Waiting for League client to start...")
            else:
                # Already connected, check if client is still running
                if not self.lcu.process or not self.lcu.process.is_running():
                    self.lcu.connected = False
                    self.lcu.ws_connected = False
                    if self.monitor:
                        self.monitor.stop()
                        self.monitor = None
                        logger.info("League client closed, monitoring stopped")
                
            time.sleep(10)
    
    def stop(self):
        """Stop the auto runes service"""
        self.running = False
        if self.monitor:
            self.monitor.stop()
        logger.info("Auto Runes service stopped")

def setup_auto_startup():
    """Set up the script to run automatically on system startup"""
    try:
        import winreg
        script_path = os.path.abspath(sys.argv[0])
        pythonw_path = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, 
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", 
            0, 
            winreg.KEY_SET_VALUE
        )
        
        winreg.SetValueEx(
            key, 
            "AutoRunes", 
            0, 
            winreg.REG_SZ, 
            f'"{pythonw_path}" "{script_path}"'
        )
        
        winreg.CloseKey(key)
        logger.info("Auto-startup configured successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to set up auto-startup: {e}")
        return False

if __name__ == "__main__":
    if not os.path.exists("auto_runes_configured.txt"):
        setup_auto_startup()
        with open("auto_runes_configured.txt", "w") as f:
            f.write("Auto Runes configured for startup")
            
    service = AutoRunesService()
    
    try:
        service.start()
    except KeyboardInterrupt:
        logger.info("Service interrupted by user")
        service.stop()
    except Exception as e:
        logger.error(f"Service error: {e}")
        service.stop() 