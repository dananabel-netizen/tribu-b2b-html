#!/usr/bin/env python3
import json, sys
from pathlib import Path
from datetime import datetime
from render_dashboard import build_html as _render_html

def main():
    data_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / 'data.json'
    with open(data_path, encoding='utf-8') as f:
        data = json.load(f)
    updated = datetime.now().strftime('%Y-%m-%d %H:%M')
    html = _render_html(data, updated)
    output = data_path.parent / 'okrs_dashboard.html'
    output.write_text(html, encoding='utf-8')
    print(f'Dashboard generado: {output}')

if __name__ == '__main__':
    main()
