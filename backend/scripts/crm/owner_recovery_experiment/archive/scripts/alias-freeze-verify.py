"""Verify frozen experiment dependencies without refreshing or reading live code."""
import hashlib
import json
from pathlib import Path
import aliases

ROOT = Path(__file__).parent

def main():
    manifest = json.loads((ROOT / 'alias-dependency-manifest.json').read_text())
    for relative, expected in manifest['files'].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    assert hashlib.sha256((ROOT / 'aliases.py').read_bytes()).hexdigest() == manifest['aliases_sha256']
    assert Path(aliases._geo.__file__).resolve() == ROOT / 'frozen_analytics/geography.py'
    result = {'check': 'PASS', 'frozen_files_verified': len(manifest['files']), 'loaded_geography': str(Path(aliases._geo.__file__).relative_to(ROOT)), 'geography_local_transitive_modules': manifest['geography_local_transitive_modules'], 'geography_data_files': manifest['geography_data_files'], 'aliases_sha256': manifest['aliases_sha256']}
    print(json.dumps(result, sort_keys=True))

if __name__ == '__main__':
    main()
