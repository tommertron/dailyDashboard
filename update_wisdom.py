#!/usr/bin/env python3
"""Select a random wisdom from Merlin Mann's Wisdom Project."""

import json
import os
import random
import re
from datetime import datetime

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
WISDOM_FILE = os.path.join(DIRECTORY, 'wisdom', 'wisdom.md')
OUTPUT_FILE = os.path.join(DIRECTORY, 'wisdom.json')


def parse_wisdom_file():
    """Parse the wisdom.md file and extract all wisdom entries."""
    wisdoms = []

    with open(WISDOM_FILE, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find the "The Wisdom So Far" section
    match = re.search(r'## The Wisdom So Far\s*\n', content)
    if not match:
        print("Could not find wisdom section")
        return []

    # Get content after the header
    wisdom_section = content[match.end():]

    # Extract bullet points (lines starting with "- ")
    for line in wisdom_section.split('\n'):
        line = line.strip()
        if line.startswith('- '):
            wisdom = line[2:].strip()
            # Skip empty or very short entries
            if len(wisdom) > 10:
                # Clean up markdown formatting
                wisdom = re.sub(r'\*\*(.+?)\*\*', r'\1', wisdom)  # Bold
                wisdom = re.sub(r'\*(.+?)\*', r'\1', wisdom)  # Italic
                wisdom = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', wisdom)  # Links
                wisdoms.append(wisdom)

    return wisdoms


def select_random_wisdom():
    """Select a random wisdom and save it to JSON."""
    wisdoms = parse_wisdom_file()

    if not wisdoms:
        print("No wisdoms found!")
        return None

    # Use hour-based seed for consistent wisdom within the hour
    now = datetime.now()
    hour_seed = int(now.strftime('%Y%m%d%H'))
    random.seed(hour_seed)

    wisdom = random.choice(wisdoms)

    data = {
        'wisdom': wisdom,
        'source': 'Merlin Mann\'s Wisdom Project',
        'updated_at': now.strftime('%Y-%m-%d %H:%M:%S'),
        'total_wisdoms': len(wisdoms)
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

    print(f"Selected wisdom ({len(wisdoms)} total): {wisdom[:80]}...")
    return wisdom


if __name__ == '__main__':
    select_random_wisdom()
