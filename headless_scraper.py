#!/usr/bin/env python
import sys
import os
import json
import time
from playwright.sync_api import sync_playwright

def get_runes_headless(champion_name):
    """
    Optimized wrapper function that runs the scraper in headless mode with speed improvements
    """
    print(f"Fetching runes for {champion_name} in headless mode...")
    start_time = time.time()
    
    rune_data = {
        "champion": champion_name,
        "primary_path": "",
        "keystone": "",
        "primary_runes": [],
        "secondary_path": "",
        "secondary_runes": [],
        "stat_shards": []
    }
    
    # Check cache first (for champions scraped in the last 24 hours)
    cache_file = f"cache_{champion_name}.json"
    if os.path.exists(cache_file) and (time.time() - os.path.getmtime(cache_file) < 86400):  # 24 hours
        try:
            with open(cache_file, "r") as f:
                cached_data = json.load(f)
                print(f"Using cached data for {champion_name} (from {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(cache_file)))})")
                
                # Save to the standard output file as well
                with open("rune_data.json", "w") as out_f:
                    json.dump(cached_data, out_f, indent=4)
                    
                return cached_data
        except Exception as e:
            print(f"Cache read error: {e}, fetching fresh data")
    
    with sync_playwright() as p:
        # Launch browser with optimized settings for speed
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-extensions',
                '--disable-component-extensions-with-background-pages',
                '--disable-features=TranslateUI,BlinkGenPropertyTrees',
                '--disable-ipc-flooding-protection',
                '--disable-renderer-backgrounding',
                '--mute-audio'
            ]
        )
        
        # Create context with optimized settings
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            java_script_enabled=True,
            ignore_https_errors=True
        )
        
        page = context.new_page()
        
        # Set shorter timeouts
        page.set_default_timeout(10000)  # 10 seconds max for all operations
        
        # Enable faster navigation by ignoring non-essential resources
        page.route("**/*.{png,jpg,jpeg,gif,css,woff,woff2,svg}", lambda route: route.abort())
        
        # Open u.gg and search for the champion's runes page
        try:
            response = page.goto(f"https://u.gg/lol/champions/{champion_name}/build", wait_until="domcontentloaded")
            
            if response.status != 200:
                raise Exception(f"Failed to load page: {response.status}")
                
            # Handle cookie consent popup - reduced timeout
            try:
                consent_button = page.wait_for_selector("button:has-text('Consent')", timeout=2000)
                if consent_button:
                    consent_button.click()
            except:
                print("No cookie popup found or already accepted.")

            # Optimized selector wait - wait for the specific content we need
            # This is a more targeted approach than waiting for the entire container
            page.wait_for_selector(".rune-tree.primary-tree .rune-tree_header", timeout=8000)
            
            # Get primary path name
            try:
                primary_tree = page.locator(".rune-tree.primary-tree").first
                primary_header = primary_tree.locator(".rune-tree_header").first
                primary_path = primary_header.text_content().strip()
                rune_data["primary_path"] = primary_path
                print(f"PRIMARY PATH: {primary_path}")
            except Exception as e:
                print(f"PRIMARY PATH: Unable to determine - {str(e)}")
            
            # Get keystone
            try:
                keystone_row = page.locator(".perk-row.keystone-row").first
                active_keystone = keystone_row.locator(".perk.perk-active").first
                keystone_img = active_keystone.locator("img").first
                keystone_name = keystone_img.get_attribute("alt")
                # Clean up keystone name by removing "The Keystone" prefix if present
                keystone_name = keystone_name.replace("The Keystone ", "")
                rune_data["keystone"] = keystone_name
                print(f"KEYSTONE: {keystone_name}")
            except Exception as e:
                print(f"KEYSTONE: Unable to determine - {str(e)}")
            
            # Get primary runes from regular perk rows
            try:
                # Get regular perk rows (not keystone row)
                primary_perk_rows = primary_tree.locator(".perk-row:not(.keystone-row)").all()
                for row in primary_perk_rows:
                    active_perk = row.locator(".perk.perk-active").first
                    perk_img = active_perk.locator("img").first
                    perk_name = perk_img.get_attribute("alt")
                    # Clean up rune name by removing "The Rune" prefix if present
                    perk_name = perk_name.replace("The Rune ", "")
                    rune_data["primary_runes"].append(perk_name)
                    print(f"• {perk_name}")
            except Exception as e:
                print(f"PRIMARY RUNES: Unable to determine - {str(e)}")
                
            # Get secondary path and runes
            try:
                secondary_tree = page.locator(".secondary-tree").first
                secondary_header = secondary_tree.locator(".rune-tree_header").first
                secondary_path = secondary_header.text_content().strip()
                rune_data["secondary_path"] = secondary_path
                print(f"\nSECONDARY PATH: {secondary_path}")
                
                # Get secondary runes (active ones)
                secondary_active_perks = secondary_tree.locator(".perk.perk-active").all()
                for perk in secondary_active_perks:
                    perk_img = perk.locator("img").first
                    perk_name = perk_img.get_attribute("alt")
                    # Clean up rune name by removing "The Rune" prefix if present
                    perk_name = perk_name.replace("The Rune ", "")
                    rune_data["secondary_runes"].append(perk_name)
                    print(f"• {perk_name}")
            except Exception as e:
                print(f"SECONDARY PATH: Unable to determine - {str(e)}")
                
            # Get stat shards 
            try:
                # Find the stat shards container
                stat_container = page.locator(".rune-tree.stat-shards-container").first
                
                # Get all active shards directly
                active_shards = stat_container.locator(".shard.shard-active").all()
                
                # Extract shard names from the alt attribute of img elements
                for shard in active_shards:
                    shard_img = shard.locator("img").first
                    shard_name = shard_img.get_attribute("alt")
                    # Clean up shard name by removing "The" and "Shard" if present
                    shard_name = shard_name.replace("The ", "").replace(" Shard", "")
                    rune_data["stat_shards"].append(shard_name)
                    print(f"• {shard_name}")
            except Exception as e:
                print(f"STAT SHARDS: Unable to determine - {str(e)}")
                
        except Exception as e:
            print(f"Error during scraping: {e}")
        finally:
            context.close()
            browser.close()
    
    # Validate that we got some useful data before saving
    if rune_data["primary_path"] and rune_data["keystone"] and len(rune_data["primary_runes"]) > 0:
        # Save the rune data to both cache and output file
        with open(cache_file, "w") as f:
            json.dump(rune_data, f, indent=4)
            
        with open("rune_data.json", "w") as f:
            json.dump(rune_data, f, indent=4)
            
        elapsed_time = time.time() - start_time
        print(f"Rune data saved to rune_data.json (completed in {elapsed_time:.2f} seconds)")
    else:
        print("Failed to get complete rune data")
    
    return rune_data

if __name__ == "__main__":
    if len(sys.argv) > 1:
        champion_name = sys.argv[1].lower()
    else:
        champion_name = input("Enter champion name: ").lower()
        
    get_runes_headless(champion_name) 