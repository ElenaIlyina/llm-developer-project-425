"""Bundle Linux CPython 3.12 wheels so cloud builds require no PyPI access."""
import argparse
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=('poller', 'tickets'))
    parser.add_argument('archive')
    args = parser.parse_args()
    requirements = ROOT / ('src/requirements-poller.txt' if args.kind == 'poller'
                           else 'src/ydb_tickets/requirements.txt')
    wheels = ROOT / '.build' / 'wheels' / args.kind
    wheels.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-m', 'pip', 'download', '--only-binary=:all:',
               '--platform', 'manylinux2014_x86_64', '--platform', 'manylinux_2_17_x86_64',
               '--python-version', '3.12', '--implementation', 'cp', '--abi', 'cp312',
               '--timeout', '120', '--retries', '3', '-r', str(requirements),
               '--dest', str(wheels)]
    cached = subprocess.run(command + ['--no-index', '--find-links', str(wheels)],
                            capture_output=True, text=True)
    if cached.returncode:
        subprocess.run(command, check=True)
    else:
        print('Using cached wheels:', args.kind)
    files = [('src/helpdesk_common.py', 'helpdesk_common.py'), ('src/guardrails.py', 'guardrails.py')]
    if args.kind == 'poller':
        files += [(f'src/{name}', name) for name in
                  ('email_poller.py', 'mcp_client.py', 'rag.py', 'knowledge_sources.json')]
        files.append(('prompts/help-desk-system.md', 'help-desk-system.md'))
    else:
        files.append(('src/ydb_tickets/index.py', 'index.py'))
    with zipfile.ZipFile(args.archive, 'w', zipfile.ZIP_DEFLATED) as archive:
        for source, destination in files:
            archive.write(ROOT / source, destination)
        archive.writestr('requirements.txt', '--no-index\n--find-links /function/code/wheels\n'
                         + requirements.read_text())
        for wheel in sorted(wheels.glob('*.whl')):
            archive.write(wheel, 'wheels/' + wheel.name)
    print('Packaged offline wheels:', args.kind)


if __name__ == '__main__':
    main()
