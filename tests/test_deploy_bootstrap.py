"""Exercise first deployment, updates and access failure without cloud mutations."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EscalationBootstrapTests(unittest.TestCase):
    def run_deploy(self, existing=False, listing_error=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('scripts', 'src', '.venv/bin', 'bin'):
                (root / name).mkdir(parents=True)
            shutil.copy2(ROOT / 'scripts/deploy-escalation.sh', root / 'scripts/deploy-escalation.sh')
            shutil.copy2(ROOT / 'src/email_sender.py', root / 'src/email_sender.py')
            renderer = root / '.venv/bin/python'
            renderer.write_text('#!/bin/sh\nexit 0\n')
            renderer.chmod(0o755)
            cli = root / 'bin/yc'
            cli.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_LOG"
case "$*" in
  'iam service-account get'*) echo '{"id":"test-sa"}' ;;
  'config get folder-id') echo test-folder ;;
  'serverless workflow list'*)
    if [ "$LIST_ERROR" = 1 ]; then exit 1; fi
    if [ "$EXISTING" = 1 ]; then echo '[{"name":"daily-escalation"}]'; else echo '[]'; fi ;;
esac
''')
            cli.chmod(0o755)
            env = {**os.environ, 'PATH': str(root / 'bin') + ':' + os.environ['PATH'],
                   'FAKE_LOG': str(root / 'commands'), 'EXISTING': str(int(existing)),
                   'LIST_ERROR': str(int(listing_error)), 'OPERATOR_EMAIL': 'operator@example.org',
                   'HELPDESK_MAILBOX': 'help@example.org', 'EMAIL_CREDENTIALS_SECRET_ID': 'secret-id',
                   'EMAIL_CREDENTIALS_SECRET_VERSION_ID': 'version-id'}
            result = subprocess.run(['bash', str(root / 'scripts/deploy-escalation.sh')],
                                    env=env, text=True, capture_output=True)
            return result.returncode, (root / 'commands').read_text()

    def test_first_install_creates_workflow(self):
        code, calls = self.run_deploy()
        self.assertEqual(code, 0)
        self.assertIn('workflow create --name daily-escalation', calls)
        self.assertNotIn('workflow update', calls)

    def test_existing_install_updates_workflow(self):
        code, calls = self.run_deploy(existing=True)
        self.assertEqual(code, 0)
        self.assertIn('workflow update --name daily-escalation', calls)
        self.assertNotIn('workflow create', calls)

    def test_failed_listing_does_not_attempt_creation(self):
        code, calls = self.run_deploy(listing_error=True)
        self.assertNotEqual(code, 0)
        self.assertNotIn('workflow create', calls)
        self.assertNotIn('workflow update', calls)
