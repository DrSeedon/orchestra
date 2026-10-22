"""V-1050: archive publication checks; also runnable offline with stdlib unittest.

All repositories, mutation copies and temporary files stay under the task directory.
No real credentials, providers, production databases or external tools are used.
"""
from __future__ import annotations

import bz2
import gzip
import io
import lzma
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import forbidden_strings as guard, publication_secrets as secrets

LITERAL = 'archive-local-' + 'a1b2c3d4' * 4
RULES = [('forbidden-string test rule', LITERAL)]


def tar(entries, *, format=tarfile.PAX_FORMAT):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=format) as archive:
        for name, content in entries:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    return output.getvalue()


def zipped(entries, *, compression=zipfile.ZIP_DEFLATED):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=compression) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


def formats(content):
    plain_tar = tar([('logs/worker.log', content)])
    return {
        'tar.gz': gzip.compress(plain_tar),
        'tgz': gzip.compress(plain_tar),
        'gz': gzip.compress(content),
        'tar': plain_tar,
        'zip': zipped([('logs/worker.log', content)]),
        'nested': zipped([('inner.tar.gz', gzip.compress(plain_tar))]),
        'bz2': bz2.compress(content),
        'xz': lzma.compress(content),
        'tar.bz2': bz2.compress(plain_tar),
        'tar.xz': lzma.compress(plain_tar),
    }


class ArchiveTests(unittest.TestCase):
    def assert_blocked(self, found, *, member=None, reason=None, value=LITERAL):
        self.assertTrue(found, 'archive must be refused')
        message = guard.block_message(found)
        self.assertIn('payload.bin', message)
        if member:
            self.assertIn('!' + member, message)
        if reason:
            self.assertIn(reason, message)
        self.assertNotIn(value, message)

    def test_magic_detected_formats_and_nested_paths(self):
        for kind, payload in formats(('before\n' + LITERAL + '\n').encode()).items():
            with self.subTest(kind=kind):
                found = guard.scan_archive(payload, 'payload.bin', RULES)
                member = {'gz': '<gzip>', 'bz2': '<bzip2>', 'xz': '<xz>'}.get(kind, 'logs/worker.log')
                self.assert_blocked(found, member=member, reason='forbidden-string test rule')
                if kind == 'nested':
                    self.assertIn('payload.bin!inner.tar.gz!<gzip>!logs/worker.log:2', '\n'.join(found))

    def test_clean_archives_pass(self):
        for kind, payload in formats(b'clean\n').items():
            with self.subTest(kind=kind):
                self.assertEqual(guard.scan_archive(payload, 'payload.bin', RULES), [])
        self.assertEqual(guard.scan_archive(zipped([]), 'payload.bin', RULES), [])
        self.assertEqual(guard.scan_archive(tar([]), 'payload.bin', RULES), [])
        self.assertEqual(guard.scan_archive(zipped([('zeros.bin', bytes(512))]), 'payload.bin', RULES), [])

    def test_plaintext_policy_is_unchanged(self):
        shape = 'gh' + 'p_' + 'a1B2' * 9
        self.assertEqual(guard.scan_archive(shape.encode(), 'plain.txt', []), [])
        self.assertEqual(guard.scan_text(shape, 'plain.txt', []), [])
        self.assertTrue(guard.scan_patch('+++ b/plain.txt\n@@ -0,0 +1 @@\n+' + LITERAL, RULES))
        self.assertEqual(guard.scan_patch('+++ b/plain.txt\n@@ -1 +0,0 @@\n-' + LITERAL, RULES), [])

    def test_literal_and_all_shared_shapes_in_archive_payload(self):
        shapes = [
            ('private key', '-----BEGIN ' + 'PRIVATE KEY-----\n' + 'A' * 40),
            ('GitHub token', 'gh' + 'p_' + 'A1b2' * 9),
            ('GitHub fine-grained token', 'github_' + 'pat_' + 'ab3_' * 12),
            ('provider API key', 'sk-' + 'ant-' + 'aB12' * 8),
            ('AWS access key', 'AK' + 'IA' + 'A1' * 8),
            ('Slack token', 'xox' + 'b-' + 'a1b2-' * 5),
            ('Google API key', 'AI' + 'za' + 'a' * 35),
            ('Telegram bot token', '123456789' + ':' + 'a' * 35),
            ('JWT', 'ey' + 'J' + 'a' * 12 + '.ey' + 'J' + 'b' * 12 + '.' + 'c' * 12),
            ('GitLab token', 'gl' + 'pat-' + 'aB12' * 6),
            ('Hugging Face token', 'h' + 'f_' + 'aB12' * 8),
        ]
        self.assertEqual({name for name, _ in shapes}, {name for name, _ in secrets.HUB_SECRET_SHAPES})
        for name, value in [('local literal', LITERAL), *shapes]:
            with self.subTest(shape=name):
                found = guard.scan_archive(zipped([('notes.log', value.encode())]), 'payload.bin', RULES)
                self.assert_blocked(found, member='notes.log', value=value)
                self.assertIn('forbidden-string test rule' if name == 'local literal' else name, '\n'.join(found))

    def test_secret_member_names_are_redacted(self):
        shape = 'gh' + 'p_' + 'aB12' * 9
        for value in (LITERAL, shape):
            for payload in (tar([(value + '.log', b'clean')]), zipped([(value + '.log', b'clean')])):
                found = guard.scan_archive(payload, 'payload.bin', RULES)
                self.assert_blocked(found, member='[redacted].log', value=value)

    def test_gzip_filename_metadata_and_concatenated_headers_are_scanned(self):
        output = io.BytesIO()
        with gzip.GzipFile(filename=LITERAL + '.log', fileobj=output, mode='wb') as stream:
            stream.write(b'clean')
        payload = gzip.compress(b'clean') + output.getvalue()
        self.assert_blocked(guard.scan_archive(payload, 'payload.bin', RULES), member='<gzip>', reason='forbidden-string')

    def test_unknown_tar_member_type_payload_is_scanned(self):
        payload = bytearray(tar([('notes.dat', gzip.compress(LITERAL.encode()))]))
        payload[156] = ord('Z')
        payload[148:156] = b'        '
        payload[148:156] = ('%06o\0 ' % sum(payload[:512])).encode()
        self.assert_blocked(guard.scan_archive(bytes(payload), 'payload.bin', RULES), member='notes.dat!<gzip>')

    def test_decompression_limit_and_exact_boundary(self):
        for pack in (gzip.compress, bz2.compress, lzma.compress):
            with self.subTest(pack=pack.__module__), patch.object(guard, 'ARCHIVE_MAX_BYTES', 1024):
                self.assertEqual(guard.scan_archive(pack(b'a' * 1024), 'payload.bin', RULES), [])
                self.assert_blocked(guard.scan_archive(pack(b'a' * 2048 + LITERAL.encode()), 'payload.bin', RULES),
                                    reason='decompressed byte limit exceeded')

    def test_total_budget_shared_by_members_and_layers(self):
        with patch.object(guard, 'ARCHIVE_MAX_BYTES', 1000):
            payload = zipped([(f'{index}.txt', b'a' * 400) for index in range(3)])
            self.assert_blocked(guard.scan_archive(payload, 'payload.bin', RULES),
                                reason='decompressed byte limit exceeded')
            payload = gzip.compress(gzip.compress(b'a' * 1000))
            self.assert_blocked(guard.scan_archive(payload, 'payload.bin', RULES),
                                reason='decompressed byte limit exceeded')

    def test_zip_bzip2_and_forged_sizes_cannot_bypass_decompression_cap(self):
        for method in (zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_STORED):
            with self.subTest(method=method):
                self.assertEqual(guard.scan_archive(zipped([('notes.log', b'clean')], compression=method),
                                                    'payload.bin', RULES), [])
                payload = bytearray(zipped([('notes.log', b'a' * 5000 + LITERAL.encode())], compression=method))
                central = payload.index(b'PK\x01\x02')
                # Advertise one byte and forge its CRC. ZipExtFile truncates at
                # that size; the guard must decode the actual stream instead.
                struct.pack_into('<L', payload, central + 24, 1)
                struct.pack_into('<L', payload, central + 16, zlib.crc32(b'a'))
                struct.pack_into('<L', payload, 22, 1)
                struct.pack_into('<L', payload, 14, zlib.crc32(b'a'))
                with patch.object(guard, 'ARCHIVE_MAX_BYTES', 1024):
                    self.assert_blocked(guard.scan_archive(bytes(payload), 'payload.bin', RULES),
                                        reason='decompressed byte limit exceeded')

    def test_member_limits_include_empty_entries_and_streams(self):
        with patch.object(guard, 'ARCHIVE_MAX_MEMBERS', 2):
            for payload in (zipped([(str(i), b'') for i in range(3)]),
                            tar([(str(i), b'') for i in range(3)]),
                            gzip.compress(b'') * 3):
                self.assert_blocked(guard.scan_archive(payload, 'payload.bin', RULES),
                                    reason='member limit exceeded')

    def test_zip_member_limit_checked_before_directory_allocation(self):
        with patch.object(guard, 'ARCHIVE_MAX_MEMBERS', 2), patch.object(zipfile, 'ZipFile') as constructor:
            payload = self.many_entries
            self.assert_blocked(guard.scan_archive(payload, 'payload.bin', RULES), reason='member limit exceeded')
            constructor.assert_not_called()

    @classmethod
    def setUpClass(cls):
        cls.many_entries = zipped([(str(i), b'') for i in range(3)])

    def test_depth_limit_and_allowed_nesting(self):
        payload = gzip.compress(b'clean')
        with patch.object(guard, 'ARCHIVE_MAX_DEPTH', 2):
            self.assertEqual(guard.scan_archive(gzip.compress(payload), 'payload.bin', RULES), [])
            self.assert_blocked(guard.scan_archive(gzip.compress(gzip.compress(payload)), 'payload.bin', RULES),
                                reason='nesting depth limit exceeded')

    def test_corrupt_archives_and_crc_fail_closed(self):
        for kind, payload in formats(b'clean').items():
            with self.subTest(kind=kind):
                # Removing only tar's optional trailing padding is still a valid
                # archive. Cut within its first member instead.
                corrupt = payload[:900] if kind == 'tar' else payload[:len(payload) // 2]
                self.assert_blocked(guard.scan_archive(corrupt, 'payload.bin', RULES),
                                    reason='corrupt')
        payload = bytearray(zipped([('notes.log', b'clean')]))
        central = payload.index(b'PK\x01\x02')
        struct.pack_into('<L', payload, central + 16, 0)  # CRC mismatch at EOF.
        self.assert_blocked(guard.scan_archive(bytes(payload), 'payload.bin', RULES), reason='corrupt')

    def test_encrypted_and_unsupported_zip_fail_closed(self):
        payload = bytearray(zipped([('notes.log', b'clean')]))
        struct.pack_into('<H', payload, 6, 1)
        struct.pack_into('<H', payload, payload.index(b'PK\x01\x02') + 8, 1)
        self.assert_blocked(guard.scan_archive(bytes(payload), 'payload.bin', RULES),
                            member='notes.log', reason='encrypted')
        payload = zipped([('notes.log', b'clean')], compression=zipfile.ZIP_LZMA)
        self.assert_blocked(guard.scan_archive(payload, 'payload.bin', RULES), reason='unsupported zip compression')

    def test_xz_dictionary_allocation_is_bounded(self):
        payload = lzma.compress(b'clean', filters=[{'id': lzma.FILTER_LZMA2, 'dict_size': 64 * 1024 * 1024}])
        self.assert_blocked(guard.scan_archive(payload, 'payload.bin', RULES), reason='unreadable')

    def test_concatenated_streams_scan_across_boundaries(self):
        raw = LITERAL.encode()
        for pack in (gzip.compress, bz2.compress, lzma.compress):
            payload = pack(raw[:10]) + pack(raw[10:])
            self.assert_blocked(guard.scan_archive(payload, 'payload.bin', RULES), reason='forbidden-string')

    def test_legacy_tar_and_pax_long_names(self):
        for format in (tarfile.USTAR_FORMAT, tarfile.GNU_FORMAT, tarfile.PAX_FORMAT):
            name = 'directory/' * 14 + 'notes.log'
            payload = tar([(name, LITERAL.encode())], format=format)
            self.assert_blocked(guard.scan_archive(payload, 'payload.bin', RULES), member=name)
        payload = bytearray(tar([('notes.log', LITERAL.encode())]))
        payload[257:265] = bytes(8)  # Old v7 tar, with no ustar magic.
        payload[148:156] = b'        '
        payload[148:156] = ('%06o\0 ' % sum(payload[:512])).encode()
        self.assert_blocked(guard.scan_archive(bytes(payload), 'payload.bin', RULES), member='notes.log')

    def test_corrupt_later_tar_header_is_not_silently_ignored(self):
        payload = bytearray(tar([('first', b''), ('second', b'')]))
        payload[512] ^= 1
        self.assert_blocked(guard.scan_archive(bytes(payload), 'payload.bin', RULES), reason='corrupt tar header')

    def test_tar_metadata_and_hidden_headers_are_bounded(self):
        payload = tar([('long/' * 40 + str(i), b'') for i in range(2)])
        with patch.object(guard, 'ARCHIVE_MAX_MEMBERS', 3):
            self.assert_blocked(guard.scan_archive(payload, 'payload.bin', RULES), reason='member limit exceeded')
        payload = tar([('a' * 70000, b'')])
        self.assert_blocked(guard.scan_archive(payload, 'payload.bin', RULES), reason='metadata byte limit')
        payload = tar([('a' * 1000 + str(i), b'') for i in range(3)])
        with patch.object(guard, 'ARCHIVE_MAX_BYTES', 1200):
            self.assert_blocked(guard.scan_archive(payload, 'payload.bin', RULES), reason='decompressed byte limit')

    def test_failure_messages_never_include_exception_payload(self):
        payload = zipped([('notes.log', b'clean')])
        with patch.object(zipfile.ZipFile, 'open', side_effect=RuntimeError(LITERAL)):
            self.assert_blocked(guard.scan_archive(payload, 'payload.bin', RULES), reason='unreadable')


class GitArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='offline-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.repo = self.directory / 'repo'
        self.repo.mkdir()
        environment = patch.dict(os.environ, {
            'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(self.directory),
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
            'GIT_AUTHOR_NAME': 'test', 'GIT_AUTHOR_EMAIL': 'test@example.invalid',
            'GIT_COMMITTER_NAME': 'test', 'GIT_COMMITTER_EMAIL': 'test@example.invalid',
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        platform = patch.object(secrets, 'PLATFORM_ROOT', self.directory / 'empty-platform')
        platform.start()
        self.addCleanup(platform.stop)
        self.git('init', '-q', '-b', 'main')
        (self.repo / 'base.txt').write_text('base\n')
        self.base = self.snapshot()

    def git(self, *args, data=None):
        done = subprocess.run(['git', '-C', str(self.repo), *args], input=data,
                              text=True, capture_output=True)
        self.assertEqual(done.returncode, 0, 'fixture git operation failed (diagnostic suppressed)')
        return done.stdout.strip()

    def snapshot(self):
        self.git('add', '--all')
        tree = self.git('write-tree')
        parent = subprocess.run(['git', '-C', str(self.repo), 'rev-parse', '--verify', 'HEAD'],
                                capture_output=True, text=True)
        args = ('-p', parent.stdout.strip()) if parent.returncode == 0 else ()
        head = self.git('commit-tree', tree, *args, data='test snapshot\n')
        self.git('update-ref', 'HEAD', head)
        return head

    def test_scan_range_reads_original_blob_for_all_formats(self):
        for kind in formats(LITERAL.encode()):
            with self.subTest(kind=kind):
                payload = formats((LITERAL + '\n' + kind).encode())[kind]
                (self.repo / 'payload.bin').write_bytes(payload)
                head = self.snapshot()
                found = guard.scan_range(self.repo, self.base, head, RULES)
                self.assertTrue(any('payload.bin!' in row for row in found))
                self.assertNotIn(LITERAL, guard.block_message(found))
                self.base = head

    def test_clean_archive_and_deletion_of_old_leak_pass(self):
        (self.repo / 'payload.bin').write_bytes(gzip.compress(LITERAL.encode()))
        leaked = self.snapshot()
        (self.repo / 'payload.bin').unlink()
        deleted = self.snapshot()
        self.assertEqual(guard.scan_range(self.repo, leaked, deleted, RULES), [])
        (self.repo / 'payload.bin').write_bytes(zipped([('clean', b'clean')]))
        clean = self.snapshot()
        self.assertEqual(guard.scan_range(self.repo, deleted, clean, RULES), [])
        found = guard.scan_range(self.repo, self.base, clean, RULES)
        self.assertTrue(any('payload.bin!<gzip>' in row for row in found), 'later deletion cannot clean history')

    def test_modification_and_root_commit_are_scanned(self):
        (self.repo / 'payload.bin').write_bytes(gzip.compress(b'clean'))
        clean = self.snapshot()
        self.assertEqual(guard.scan_range(self.repo, self.base, clean, RULES), [])
        (self.repo / 'payload.bin').write_bytes(gzip.compress(LITERAL.encode()))
        leaked = self.snapshot()
        self.assertTrue(guard.scan_range(self.repo, clean, leaked, RULES))
        self.assertTrue(guard.scan_range(self.repo, '4b825dc642cb6eb9a060e54bf8d69288fbee4904', leaked, RULES))

    def test_local_env_literal_and_shape_in_archives(self):
        (self.repo / '.env').write_text('DEEPGRAM_API_KEY=' + LITERAL + '\n')
        # Keep the inventory private; only the compressed log is published.
        (self.repo / '.gitignore').write_text('.env\n')
        (self.repo / 'payload.bin').write_bytes(gzip.compress(LITERAL.encode()))
        found = guard.scan_range(self.repo, self.base, self.snapshot(), [])
        self.assertTrue(any('DEEPGRAM_API_KEY' in row and 'payload.bin!' in row for row in found))
        self.assertNotIn(LITERAL, guard.block_message(found))

    def test_oversized_archive_input_refused_without_reading_all(self):
        (self.repo / 'payload.bin').write_bytes(gzip.compress(b'clean') + bytes(4096))
        head = self.snapshot()
        run = subprocess.run

        def no_binary_diff(args, **kwargs):
            self.assertNotIn('--text', args, 'refused archives must not materialize a binary text diff')
            return run(args, **kwargs)

        with patch.object(guard, 'ARCHIVE_MAX_INPUT_BYTES', 1024), patch.object(subprocess, 'run', no_binary_diff):
            found = guard.scan_range(self.repo, self.base, head, RULES)
        self.assertTrue(any('payload.bin: archive input byte limit' in row for row in found))

    def test_hook_import_and_archive_scan_are_stdlib_only(self):
        probe = (
            'import sys, gzip\n'
            'sys.path.insert(0, sys.argv[1])\n'
            'from app import forbidden_strings as guard\n'
            'assert guard.scan_archive(gzip.compress(b"synthetic literal"), "file.bin", [("rule", "synthetic literal")])\n'
            'assert {x for x in sys.modules if x.startswith("app.")} == '
            '{"app.forbidden_strings", "app.publication_secrets"}\n'
        )
        run = subprocess.run([sys.executable, '-I', '-S', '-c', probe, str(ROOT)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)

    @unittest.skipUnless((ROOT / 'scripts' / 'secret_scan.py').is_file(),
                         'canonical secret_scan.py excluded from worker copy')
    def test_actual_pre_push_hook_scans_archives(self):
        from scripts import install_git_hooks

        stop_list = self.directory / 'forbidden.txt'
        stop_list.write_text(LITERAL + '\n')
        install_git_hooks.install_hooks(self.repo, ROOT)
        hook = self.repo / '.git' / 'hooks' / 'pre-push'
        with patch.dict(os.environ, {guard.ENV_VAR: str(stop_list)}):
            (self.repo / 'payload.bin').write_bytes(gzip.compress(b'clean'))
            clean = self.snapshot()
            run = subprocess.run([str(hook)], cwd=self.repo, capture_output=True, text=True,
                                 input=f'refs/heads/main {clean} refs/heads/main {self.base}\n', timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.base = clean
            for kind in ('tar.gz', 'gz', 'zip', 'nested'):
                with self.subTest(kind=kind):
                    (self.repo / 'payload.bin').write_bytes(formats((LITERAL + kind).encode())[kind])
                    head = self.snapshot()
                    run = subprocess.run([str(hook)], cwd=self.repo, capture_output=True, text=True,
                                         input=f'refs/heads/main {head} refs/heads/main {self.base}\n', timeout=60)
                    self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                    self.assertIn('payload.bin!', run.stdout + run.stderr)
                    self.assertNotIn(LITERAL, run.stdout + run.stderr)
                    self.base = head

    @unittest.skipUnless((ROOT / 'app' / 'workspace.py').is_file(),
                         'merge_worker workspace implementation excluded from worker copy')
    def test_actual_merge_gate_refuses_archives_without_changing_refs(self):
        from app import workspace

        stop_list = self.directory / 'forbidden.txt'
        stop_list.write_text(LITERAL + '\n')
        worker = self.directory / 'worker'
        self.git('worktree', 'add', '-q', '-b', 'worker', str(worker))
        main = self.repo
        with patch.dict(os.environ, {guard.ENV_VAR: str(stop_list)}):
            for kind in ('tar.gz', 'gz', 'zip', 'nested'):
                with self.subTest(kind=kind):
                    (worker / 'payload.bin').write_bytes(formats((LITERAL + kind).encode())[kind])
                    self.repo = worker
                    head = self.snapshot()
                    self.repo = main
                    result = workspace.merge_worktree_to_main(str(worker), str(main), target_branch='main')
                    self.assertFalse(result['ok'])
                    self.assertEqual(result['code'], 'FORBIDDEN_STRING')
                    self.assertIn('payload.bin!', result['error'])
                    self.assertNotIn(LITERAL, result['error'])
                    self.assertEqual(self.git('rev-parse', 'main'), self.base)
                    self.assertEqual(self.git('rev-parse', 'worker'), head)
                    self.assertFalse((main / 'payload.bin').exists())


class ArchiveMutationTests(unittest.TestCase):
    def test_removing_archive_scan_reddens_same_git_acceptance_test(self):
        with tempfile.TemporaryDirectory(prefix='mutation-') as temporary:
            directory = Path(temporary)
            (directory / 'app').mkdir()
            (directory / 'tests').mkdir()
            for name in ('forbidden_strings.py', 'publication_secrets.py'):
                shutil.copyfile(ROOT / 'app' / name, directory / 'app' / name)
            test = directory / 'tests' / Path(__file__).name
            shutil.copyfile(__file__, test)
            source = directory / 'app' / 'forbidden_strings.py'
            target = '                archive_found = _scan_archive_blob(repo, commit, path, rules)'
            original = source.read_text()
            self.assertEqual(original.count(target), 1, 'mutation must remove the archive integration')
            source.write_text(original.replace(target, '                archive_found = []  # mutation: archive scanning removed'))
            probe = (
                'import importlib.util, sys, unittest\n'
                'spec = importlib.util.spec_from_file_location("archive_tests", sys.argv[1])\n'
                'module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)\n'
                'suite = unittest.defaultTestLoader.loadTestsFromName('
                '"GitArchiveTests.test_scan_range_reads_original_blob_for_all_formats", module)\n'
                'result = unittest.TextTestRunner().run(suite)\n'
                'raise SystemExit(not result.wasSuccessful())\n'
            )
            run = subprocess.run([sys.executable, '-I', '-S', '-c', probe, str(test)],
                                 cwd=directory, capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
            self.assertIn('FAIL:', run.stderr, 'must fail assertions, not imports or setup')
            self.assertIn('payload.bin!', run.stderr)
            self.assertIn('failures=10', run.stderr)


if __name__ == '__main__':
    unittest.main()
