#!/usr/bin/env python3
import json
import os
import sys
import requests

# Define output paths
CATEGORIES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'php')
PLUGINS_FULL_PATH = os.path.join(CATEGORIES_DIR, 'plugins-full.txt')
PLUGINS_VULN_PATH = os.path.join(CATEGORIES_DIR, 'plugins-vulnerable.txt')

def fetch_popular_plugins():
    """
    Fetches a list of popular WordPress plugins.
    Since WPScan API requires a token, we use a fallback method or a public list for demonstration.
     Ideally, you would use: https://enterprise-data.wpscan.com/plugins.json.gz (Auth required)
    
    Here we mock it by fetching a known large list or scraping a popular list if possible.
    For this script, we will use a static list combined with a fetch from a public wordlist repo.
    """
    print("Fetching popular plugins list...")
    plugins = set()
    
    # Try to fetch from a public SecLists or similar source
    try:
        url = "https://raw.githubusercontent.com/danielmiessler/SecLists/master/Discovery/Web-Content/CMS/wordpress-plugins.txt"
        response = requests.get(url)
        if response.status_code == 200:
            for line in response.text.splitlines():
                if line.strip():
                    plugins.add(line.strip())
            print(f"Fetched {len(plugins)} plugins from SecLists mirror.")
    except Exception as e:
        print(f"Failed to fetch public list: {e}")
        
    return list(plugins)

def generate_wordlists(plugins):
    print(f"Generating wordlists in {CATEGORIES_DIR}...")
    
    # Ensure directory exists
    os.makedirs(CATEGORIES_DIR, exist_ok=True)
    
    # Full plugins list
    with open(PLUGINS_FULL_PATH, 'w') as f:
        for plugin in plugins:
            plugin_path = f"wp-content/plugins/{plugin}/"
            f.write(plugin_path + "\n")
            
    # Vulnerable plugins (Mock logic: In reality, you'd check against a DB)
    # For now, we take a subset or just a placeholder list of historically vulnerable ones
    vulnerable_subset = [
        "akismet", "contact-form-7", "jetpack", "woocommerce", "wordpress-seo", 
        "elementor", "wordfence", "duplicator", "all-in-one-seo-pack"
    ]
    
    with open(PLUGINS_VULN_PATH, 'w') as f:
        for plugin in vulnerable_subset:
            plugin_path = f"wp-content/plugins/{plugin}/"
            f.write(plugin_path + "\n")

    print(f"Created {PLUGINS_FULL_PATH}")
    print(f"Created {PLUGINS_VULN_PATH}")

def main():
    plugins = fetch_popular_plugins()
    if not plugins:
        # Fallback if fetch fails
        plugins = ["akismet", "contact-form-7", "yoast-seo", "jetpack", "wordfence", "woocommerce"]
    
    generate_wordlists(plugins)

if __name__ == "__main__":
    main()
