#!/usr/bin/env python3
"""Select a random wisdom from the wisdom file."""

import json
import os
import random
import re
from datetime import datetime

DIRECTORY = os.path.dirname(os.path.abspath(__file__))
WISDOM_FILE = os.path.join(DIRECTORY, 'wisdom', 'wisdom.md')
OUTPUT_FILE = os.path.join(DIRECTORY, 'wisdom.json')


def parse_wisdom_file():
    """Parse the wisdom.md file and extract all wisdom entries with sources."""
    wisdoms = []

    with open(WISDOM_FILE, 'r', encoding='utf-8') as f:
        content = f.read()

    # Define sections and their sources
    sections = [
        ('## The Wisdom So Far', '## Kevin Kelly', "Merlin Mann's Wisdom Project"),
        ('## Kevin Kelly', '## Works Cited', "Kevin Kelly's Excellent Advice for Living"),
    ]

    for start_header, end_header, source in sections:
        start_match = re.search(re.escape(start_header) + r'.*?\n', content)
        if not start_match:
            continue

        end_match = re.search(re.escape(end_header), content)
        if end_match:
            section_content = content[start_match.end():end_match.start()]
        else:
            section_content = content[start_match.end():]

        # Extract bullet points (lines starting with "- ")
        for line in section_content.split('\n'):
            line = line.strip()
            if line.startswith('- '):
                wisdom = line[2:].strip()
                # Skip empty or very short entries
                if len(wisdom) > 10:
                    # Clean up markdown formatting
                    wisdom = re.sub(r'\*\*(.+?)\*\*', r'\1', wisdom)  # Bold
                    wisdom = re.sub(r'\*(.+?)\*', r'\1', wisdom)  # Italic
                    wisdom = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', wisdom)  # Links
                    wisdoms.append({'text': wisdom, 'source': source})

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

    selected = random.choice(wisdoms)

    data = {
        'wisdom': selected['text'],
        'source': selected['source'],
        'updated_at': now.strftime('%Y-%m-%d %H:%M:%S'),
        'total_wisdoms': len(wisdoms)
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

    print(f"Selected wisdom ({len(wisdoms)} total): {selected['text'][:80]}...")
    return selected['text']


if __name__ == '__main__':
    select_random_wisdom()
