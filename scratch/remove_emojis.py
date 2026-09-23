import os
import re

# Match most common emojis
emoji_pattern = re.compile(
    '['
    '\U0001f600-\U0001f64f'  # emoticons
    '\U0001f300-\U0001f5ff'  # symbols & pictographs
    '\U0001f680-\U0001f6ff'  # transport & map symbols
    '\U0001f700-\U0001f77f'  # alchemical symbols
    '\U0001f780-\U0001f7ff'  # Geometric Shapes Extended
    '\U0001f800-\U0001f8ff'  # Supplemental Arrows-C
    '\U0001f900-\U0001f9ff'  # Supplemental Symbols and Pictographs
    '\U0001fa00-\U0001fa6f'  # Chess Symbols
    '\U0001fa70-\U0001faff'  # Symbols and Pictographs Extended-A
    '\U00002702-\U000027b0'  # Dingbats
    '\U000024c2-\U0001f251'
    ']+',
    re.UNICODE
)

def remove_emojis_from_dir(directory):
    for root, dirs, files in os.walk(directory):
        if 'node_modules' in root or '.git' in root or '__pycache__' in root:
            continue
        for file in files:
            if file.endswith(('.py', '.md', '.ts', '.tsx', '.js', '.jsx', '.json', '.html', '.css', '.bat', '.sh', '.ps1')):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    if emoji_pattern.search(content):
                        new_content = emoji_pattern.sub('', content)
                        if new_content != content:
                            with open(filepath, 'w', encoding='utf-8') as f:
                                f.write(new_content)
                            print(f'Removed emojis from {filepath}')
                except Exception as e:
                    pass

remove_emojis_from_dir('.')
