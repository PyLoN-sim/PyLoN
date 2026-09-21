import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from pylon_bridge import craft_builder as builder


SESSION = 'a' * 32


def placement():
    return {
        'version': 1, 'name': '月 Rover 01', 'facility': 'VAB',
        'parts': [
            {'id': 'root', 'part': 'probe.core-1', 'position': [0, 0, 0],
             'rotation': [0, 0, 0, 1]},
            {'id': 'tank', 'part': 'fuelTank', 'position': [0, -1, 0],
             'rotation': [0, 0, 0, 1], 'parent': 'root',
             'attach': {'mode': 'stack', 'node': 'top', 'parent_node': 'bottom'}},
        ],
    }


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data), encoding='utf-8')
    os.replace(temporary, path)


class SpecTests(unittest.TestCase):
    def test_normalizes_defaults_without_mutating_input_or_reordering_parts(self):
        spec = placement()
        spec['parts'].reverse()
        before = copy.deepcopy(spec)
        result = builder.validate_spec(spec)
        self.assertEqual(spec, before)
        self.assertEqual(result['parts'][0]['id'], 'tank')
        self.assertEqual(result['parts'][1]['parent'], '')
        self.assertEqual(result['parts'][1]['stage'], -1)
        self.assertNotIn('attach', result['parts'][1])
        result['parts'][0]['attach']['node'] = 'changed'
        result['parts'][1]['position'][0] = 10
        self.assertEqual(spec, before)

    def test_surface_and_boundary_values(self):
        spec = placement()
        spec['facility'] = 'SPH'
        child = spec['parts'][1]
        child.update(position=[-1000, 1000, 0], rotation=[0, 0, 1, 0], stage=99)
        child['attach'] = dict(mode='surface', node='srfAttach', parent_node='')
        self.assertEqual(builder.validate_spec(spec)['parts'][1], child)

    def test_build_options_preserve_explicit_zero_and_false_without_changing_defaults(self):
        spec = placement()
        spec['parts'][1].update(autostrut='grandparent', rigid_attachment=False,
                                separation_force_percent=0, role='satellite_separator')
        before = copy.deepcopy(spec)
        result = builder.validate_spec(spec)
        self.assertEqual(result['parts'][1], before['parts'][1] | {'stage': -1})
        self.assertEqual(spec, before)
        for field in ('autostrut', 'rigid_attachment', 'separation_force_percent', 'role'):
            self.assertNotIn(field, result['parts'][0])
        for mode in ('off', 'root', 'heaviest', 'grandparent'):
            spec['parts'][1].update(autostrut=mode, separation_force_percent=100,
                                    rigid_attachment=True)
            self.assertEqual(builder.validate_spec(spec)['parts'][1]['autostrut'], mode)

    def test_build_options_reject_invalid_types_ranges_and_roles(self):
        cases = {
            'autostrut': ('Off', 'forced_root', '', None, True, [], {}),
            'rigid_attachment': ('true', 0, 1, None, [], {}),
            'separation_force_percent': (-0.001, 100.001, float('nan'), float('inf'),
                                         True, '50', None, [], {}),
            'role': ('', 'return engine', '0engine', 'engine\n', 'a' * 65,
                     '帰還', True, None, [], {}),
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    spec = placement()
                    spec['parts'][1][field] = value
                    with self.assertRaises(builder.CraftBuilderError):
                        builder.validate_spec(spec)

    def test_schema_types_unknown_fields_and_names(self):
        cases = [
            ((), None), ((), []), (('extra',), 1), (('version',), True),
            (('version',), 1.0), (('version',), 2), (('facility',), 'vab'),
            (('facility',), []), (('parts',), []), (('parts',), {}),
        ]
        for name in ('', '   ', '.', '..', ' .. ', 'a/b', 'a\\b', 'a\n',
                     'a\x00', 'a\x7f', 'a\u202e', '\ud800', 'a' * 81, None, 4):
            cases.append((('name',), name))
        for path, value in cases:
            with self.subTest(path=path, value=value):
                spec = placement()
                if not path:
                    spec = value
                else:
                    spec[path[0]] = value
                with self.assertRaises(builder.CraftBuilderError):
                    builder.validate_spec(spec)
        for key in ('version', 'name', 'facility', 'parts'):
            spec = placement()
            del spec[key]
            with self.subTest(missing=key), self.assertRaises(builder.CraftBuilderError):
                builder.validate_spec(spec)

    def test_unhashable_version_facility_and_mode_raise_validation_errors(self):
        for value in ([], {}, ['VAB'], {'mode': 'stack'}):
            for field in ('version', 'facility', 'mode'):
                spec = placement()
                if field == 'mode':
                    spec['parts'][1]['attach']['mode'] = value
                else:
                    spec[field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaises(builder.CraftBuilderError):
                        builder.validate_spec(spec)

    def test_stack_siblings_cannot_reuse_parent_node_in_either_order(self):
        for reverse in (False, True):
            spec = placement()
            sibling = copy.deepcopy(spec['parts'][1])
            sibling['id'] = 'sibling'
            spec['parts'].append(sibling)
            if reverse:
                spec['parts'].reverse()
            with self.subTest(reverse=reverse):
                with self.assertRaisesRegex(builder.CraftBuilderError, 'occupied: root:bottom'):
                    builder.validate_spec(spec)

    def test_child_node_cannot_also_be_a_parent_node_in_either_order(self):
        for surface in (False, True):
            for reverse in (False, True):
                spec = placement()
                child = spec['parts'][1]
                if surface:
                    child['attach'] = dict(mode='surface', node='srfAttach', parent_node='')
                grandchild = copy.deepcopy(placement()['parts'][1])
                grandchild.update(id='grandchild', parent='tank')
                grandchild['attach']['parent_node'] = child['attach']['node']
                spec['parts'].append(grandchild)
                if reverse:
                    spec['parts'].reverse()
                node = 'srfAttach' if surface else 'top'
                with self.subTest(surface=surface, reverse=reverse):
                    with self.assertRaisesRegex(
                            builder.CraftBuilderError, f'occupied: tank:{node}'):
                        builder.validate_spec(spec)

    def test_distinct_nodes_and_multiple_surface_children_are_allowed(self):
        for surface in (False, True):
            spec = placement()
            sibling = copy.deepcopy(spec['parts'][1])
            sibling['id'] = 'sibling'
            sibling['attach']['parent_node'] = 'top'
            spec['parts'].append(sibling)
            if surface:
                for child in spec['parts'][1:]:
                    child['attach'] = dict(mode='surface', node='srfAttach', parent_node='')
            spec['parts'].reverse()
            with self.subTest(surface=surface):
                self.assertEqual(len(builder.validate_spec(spec)['parts']), 3)

    def test_repeated_surface_child_is_rejected(self):
        spec = placement()
        spec['parts'][1]['attach'] = dict(mode='surface', node='srfAttach', parent_node='')
        spec['parts'].append(copy.deepcopy(spec['parts'][1]))
        with self.assertRaisesRegex(builder.CraftBuilderError, 'Duplicate part id: tank'):
            builder.validate_spec(spec)

    def test_part_fields_tokens_stages_and_attachments(self):
        cases = [
            ('id', ''), ('id', '1root'), ('id', '日本'), ('id', 'a' * 65),
            ('id', 'a\n'), ('part', ''), ('part', 'a/b'), ('part', 'é'),
            ('part', 'a' * 129), ('parent', None), ('parent', 1),
            ('stage', True), ('stage', 1.0), ('stage', -2), ('stage', 100),
            ('unknown', 0), ('attach', None), ('attach', {}),
            ('attach', dict(mode='other', node='top', parent_node='bottom')),
            ('attach', dict(mode='stack', node='', parent_node='bottom')),
            ('attach', dict(mode='stack', node='top', parent_node='')),
            ('attach', dict(mode='stack', node='a b', parent_node='bottom')),
            ('attach', dict(mode='stack', node='a' * 65, parent_node='bottom')),
            ('attach', dict(mode='stack', node='top', parent_node='bottom', extra=1)),
            ('attach', dict(mode='surface', node='top', parent_node='')),
            ('attach', dict(mode='surface', node='srfAttach', parent_node='bottom')),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                spec = placement()
                spec['parts'][1][key] = value
                with self.assertRaises(builder.CraftBuilderError):
                    builder.validate_spec(spec)
        for key in ('id', 'part', 'position', 'rotation', 'attach'):
            spec = placement()
            del spec['parts'][1][key]
            with self.subTest(missing=key), self.assertRaises(builder.CraftBuilderError):
                builder.validate_spec(spec)
        for attach in (None, {}, dict(mode='stack', node='top', parent_node='bottom')):
            spec = placement()
            spec['parts'][0]['attach'] = attach
            with self.assertRaisesRegex(builder.CraftBuilderError, 'root attach'):
                builder.validate_spec(spec)

    def test_pose_numbers_and_quaternion_validation(self):
        for field, length in (('position', 3), ('rotation', 4)):
            for invalid in (None, '0', [], [0] * (length + 1)):
                spec = placement()
                spec['parts'][1][field] = invalid
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaises(builder.CraftBuilderError):
                        builder.validate_spec(spec)
            for invalid in (True, False, '1', None, float('nan'), float('inf'),
                            -float('inf'), 10 ** 400):
                spec = placement()
                spec['parts'][1][field][0] = invalid
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaises(builder.CraftBuilderError):
                        builder.validate_spec(spec)
        for field, value in (
            ('position', [1000.001, 0, 0]), ('position', [-1000.001, 0, 0]),
            ('rotation', [0, 0, 0, 0]), ('rotation', [0, 0, 0, 1.002]),
            ('rotation', [1e308, 1e308, 1e308, 1e308]),
        ):
            spec = placement()
            spec['parts'][1][field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaises(builder.CraftBuilderError):
                    builder.validate_spec(spec)

    def test_root_pose_tolerance_positive_identity_only(self):
        for field, value in (('position', [0, 0, 2e-6]),
                             ('rotation', [0, 0, 0, -1]),
                             ('rotation', [2e-6, 0, 0, 1])):
            spec = placement()
            spec['parts'][0][field] = value
            with self.assertRaises(builder.CraftBuilderError):
                builder.validate_spec(spec)
        spec = placement()
        spec['parts'][0].update(position=[1e-6, 0, 0], rotation=[0, 0, 1e-6, 1])
        builder.validate_spec(spec)

    def test_invalid_trees(self):
        for kind in ('duplicate', 'missing', 'self', 'no_root', 'two_roots', 'cycle'):
            spec = placement()
            root, child = spec['parts']
            if kind == 'duplicate':
                child['id'] = root['id']
            elif kind == 'missing':
                child['parent'] = 'absent'
            elif kind == 'self':
                child['parent'] = child['id']
            elif kind == 'no_root':
                root.update(parent='tank', attach=dict(child['attach']))
            elif kind == 'two_roots':
                child.update(parent='', position=[0, 0, 0])
                del child['attach']
            else:
                other = copy.deepcopy(child)
                other.update(id='other', parent='tank')
                child['parent'] = 'other'
                spec['parts'].append(other)
            with self.subTest(kind=kind), self.assertRaises(builder.CraftBuilderError):
                builder.validate_spec(spec)

    def test_maximum_chain_and_part_limit(self):
        spec = placement()
        for index in range(2, 256):
            child = copy.deepcopy(spec['parts'][1])
            child.update(id=f'p{index}', parent=spec['parts'][-1]['id'])
            spec['parts'].append(child)
        spec['parts'].reverse()
        self.assertEqual(len(builder.validate_spec(spec)['parts']), 256)
        spec['parts'].append(copy.deepcopy(spec['parts'][0]))
        with self.assertRaisesRegex(builder.CraftBuilderError, '1..256'):
            builder.validate_spec(spec)


class FilesAndCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'placement.json'

    def test_json_rejects_duplicates_nonfinite_encoding_and_oversize(self):
        for raw in (b'{"version":1,"version":1}', b'{"nested":{"x":1,"x":2}}',
                    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}',
                    b'{"x":1e999}', b'\xff', b'{',
                    b' ' * (builder.MAX_JSON_BYTES + 1)):
            self.path.write_bytes(raw)
            with self.subTest(raw=raw[:40]), self.assertRaises(builder.CraftBuilderError):
                builder.read_json(self.path)
        self.path.write_bytes(b'{}' + b' ' * (builder.MAX_JSON_BYTES - 2))
        self.assertEqual(builder.read_json(self.path), {})

    def run_cli(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = builder.main(args)
        return code, json.loads(output.getvalue())

    def test_validate_offline_and_failure_json(self):
        write_json(self.path, placement())
        with patch.object(builder, 'send_request', side_effect=AssertionError('offline')):
            code, result = self.run_cli(['--ksp-dir', '/nonexistent', 'validate', str(self.path)])
        self.assertEqual(code, 0)
        self.assertTrue(result['ok'])
        self.assertEqual(result['spec']['parts'][0]['stage'], -1)
        self.path.write_text('{}', encoding='utf-8')
        code, result = self.run_cli(['validate', str(self.path)])
        self.assertEqual(code, 1)
        self.assertIn('missing fields', result['error'])

    def test_cli_reports_unhashable_schema_values_as_json_errors(self):
        for field in ('version', 'facility', 'mode'):
            for value in ([], {}):
                spec = placement()
                if field == 'mode':
                    spec['parts'][1]['attach']['mode'] = value
                else:
                    spec[field] = value
                write_json(self.path, spec)
                with self.subTest(field=field, value=value):
                    code, result = self.run_cli(['validate', str(self.path)])
                    self.assertEqual(code, 1)
                    self.assertFalse(result['ok'])
                    self.assertIn(field, result['error'])

    def test_timeout_range_and_cli_parse_errors(self):
        for value in ('nan', 'inf', '-inf', '0', '0.99', '120.01', 'nonsense', True):
            with self.subTest(value=value), self.assertRaises(builder.CraftBuilderError):
                builder.validate_timeout(value)
        for value in ('nan', '0', '121'):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                builder.main(['--timeout', value, 'inspect'])
            self.assertEqual(exc.exception.code, 2)
        self.assertEqual(builder.validate_timeout(1), 1)
        self.assertEqual(builder.validate_timeout('120'), 120)

    def test_cli_build_options_env_and_server_failure_passthrough(self):
        write_json(self.path, placement())
        result = dict(version=1, id='b' * 32, ok=False, error='Editor must be empty',
                      craftPath='', loaded=False, parts=[])
        with patch.dict(os.environ, {'KSPDIR': '/from-env'}):
            with patch.object(builder, 'send_request', return_value=result) as send:
                code, printed = self.run_cli(
                    ['--timeout', '12', 'build', str(self.path), '--load'])
                self.assertEqual(printed, result)
                self.assertEqual(code, 1)
                self.assertEqual(send.call_args.args, ('/from-env', 'build'))
                self.assertTrue(send.call_args.kwargs['load'])
                self.assertEqual(send.call_args.kwargs['timeout'], 12)
                self.assertEqual(send.call_args.kwargs['spec']['parts'][0]['parent'], '')
            with patch.object(builder, 'send_request', return_value=dict(ok=True)) as send:
                self.run_cli(['--ksp-dir', '/explicit', 'parts', '--filter', 'tank'])
                self.assertEqual(send.call_args.args, ('/explicit', 'parts'))
                self.assertEqual(send.call_args.kwargs['filter_text'], 'tank')


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ksp = Path(self.temp.name)
        self.directory = self.ksp / builder.PROTOCOL_DIR
        self.requests = self.directory / 'requests'
        self.requests.mkdir(parents=True)
        self.status = dict(version=1, session=SESSION, updatedAt=time.time(),
                           ready=True, facility='VAB', save='test-save')
        self.write_status()

    def write_status(self):
        write_json(self.directory / 'status.json', self.status)

    def pending(self):
        return list(self.requests.glob('*.json'))

    def reply(self, request, **changes):
        result = dict(version=1, id=request['id'], ok=True, error='',
                      craftPath='saves/test-save/Ships/VAB/Moon.craft', loaded=False, parts=[])
        result.update(changes)
        write_json(self.directory / 'results' / f'{request["id"]}.json', result)
        return result

    def test_fresh_status_required_before_enqueue(self):
        cases = (('updatedAt', time.time() - 6), ('updatedAt', time.time() + 60),
                 ('updatedAt', True), ('updatedAt', float('nan')), ('ready', False),
                 ('ready', 1), ('session', 'A' * 32), ('session', 'abc'),
                 ('version', True), ('version', 2), ('facility', 'Flight'), ('save', None))
        original = self.status.copy()
        for key, value in cases:
            self.status = dict(original, **{key: value})
            self.write_status()
            with self.subTest(key=key, value=value), self.assertRaises(builder.CraftBuilderError):
                builder.send_request(self.ksp, 'inspect')
            self.assertEqual(list(self.requests.iterdir()), [])
        (self.directory / 'status.json').unlink()
        with self.assertRaises(FileNotFoundError):
            builder.send_request(self.ksp, 'inspect')

    def test_real_fake_server_atomic_handshake_and_build_payload(self):
        errors = []
        received = []
        stop = threading.Event()

        def server():
            try:
                until = time.monotonic() + 3
                while not stop.is_set() and time.monotonic() < until:
                    pending = self.pending()
                    if not pending:
                        stop.wait(0.005)
                        continue
                    request = builder.read_json(pending[0])
                    self.assertEqual(pending[0].stem, request['id'])
                    self.assertRegex(request['id'], r'^[0-9a-f]{32}$')
                    self.assertEqual(request['session'], SESSION)
                    self.assertGreater(request['expiresAt'], time.time())
                    self.assertLessEqual(request['expiresAt'], time.time() + 2)
                    self.assertEqual(request['version'], 1)
                    self.assertEqual(request['command'], 'build')
                    self.assertEqual(request['filter'], '')
                    self.assertTrue(request['load'])
                    self.assertEqual(request['spec'], builder.validate_spec(placement()))
                    self.assertFalse(pending[0].with_suffix('.tmp').exists())
                    received.append(request)
                    pending[0].unlink()  # Server claims the operation before returning its result.
                    self.reply(request, loaded=True, extra='preserved')
                    return
                raise AssertionError('No request arrived')
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=server)
        thread.start()
        try:
            result = builder.send_request(
                self.ksp, 'build', timeout=2, load=True, spec=placement())
        finally:
            stop.set()
            thread.join(timeout=4)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(received), 1)
        self.assertTrue(result['loaded'])
        self.assertEqual(result['extra'], 'preserved')
        self.assertEqual(list(self.requests.iterdir()), [])

    def test_parts_inspect_and_expired_error_results(self):
        for command in ('parts', 'inspect'):
            for error in ('', 'Request expired', 'Session mismatch', 'Editor must be empty'):
                seen = []

                def respond(_):
                    request = builder.read_json(self.pending()[0])
                    seen.append(request)
                    self.reply(request, ok=not bool(error), error=error,
                               parts=[dict(name='fuelTank', nodes=['top', 'bottom'])])

                with patch.object(builder.time, 'sleep', side_effect=respond):
                    result = builder.send_request(self.ksp, command, filter_text='fuel')
                self.assertEqual(result['error'], error)
                self.assertEqual(result['ok'], not bool(error))
                self.assertEqual(len(seen), 1)
                self.assertEqual(seen[0]['spec'], {})
                self.assertEqual(seen[0]['filter'], 'fuel')
                self.assertFalse(seen[0]['load'])
                self.assertEqual(self.pending(), [])

    def test_timeout_pending_and_claimed_no_retry_cleanup_only_own_request(self):
        other = self.requests / ('f' * 32 + '.json')
        other.write_text('{}', encoding='utf-8')
        for claimed in (False, True):
            ticks = [100.0]
            seen = []

            def advance(_):
                own = [path for path in self.pending() if path != other]
                self.assertEqual(len(own), 1)
                seen.append(builder.read_json(own[0]))
                if claimed:
                    own[0].unlink()
                ticks[0] += 2

            with patch.object(builder.time, 'monotonic', side_effect=lambda: ticks[0]):
                with patch.object(builder.time, 'sleep', side_effect=advance):
                    with self.assertRaisesRegex(
                            builder.CraftBuilderError, 'Outcome unknown') as exc:
                        builder.send_request(self.ksp, 'inspect', timeout=1)
            self.assertIn('Timed out', str(exc.exception))
            self.assertIn('No pending' if claimed else 'Removed own', str(exc.exception))
            self.assertIn('no automatic retry', str(exc.exception))
            self.assertEqual(len(seen), 1)
            self.assertEqual(self.pending(), [other])

    def test_session_change_while_waiting_cleans_pending(self):
        def restart(_):
            self.status.update(session='b' * 32, updatedAt=time.time())
            self.write_status()

        with patch.object(builder.time, 'sleep', side_effect=restart):
            with self.assertRaisesRegex(
                    builder.CraftBuilderError, 'session changed.*Outcome unknown'):
                builder.send_request(self.ksp, 'inspect')
        self.assertEqual(list(self.requests.iterdir()), [])

    def test_session_change_and_expiry_before_publish(self):
        original_replace = os.replace
        original_fsync = os.fsync
        for expire in (False, True):
            self.status.update(session=SESSION, updatedAt=time.time())
            self.write_status()
            ticks = [0]

            def during_write(fd):
                original_fsync(fd)
                if expire:
                    ticks[0] = 2
                else:
                    self.status['session'] = 'b' * 32
                    # Avoid request-rename observation for this status change.
                    path = self.directory / 'status.json'
                    temporary = path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(self.status), encoding='utf-8')
                    original_replace(temporary, path)

            with patch.object(builder.os, 'fsync', side_effect=during_write):
                with patch.object(builder.time, 'monotonic', side_effect=lambda: ticks[0]):
                    with patch.object(builder.os, 'replace') as replace:
                        with self.assertRaisesRegex(builder.CraftBuilderError,
                                                    'expired' if expire else 'session changed'):
                            builder.send_request(self.ksp, 'inspect', timeout=1)
                        replace.assert_not_called()
            self.assertEqual(list(self.requests.iterdir()), [])

    def test_bad_result_and_publish_failure_cleanup(self):
        for changes in ({'id': 'c' * 32}, {'version': True}, {'ok': 1},
                        {'parts': {}}, {'loaded': 'yes'}, {'error': None}, {'craftPath': None}):
            def respond(_):
                self.reply(builder.read_json(self.pending()[0]), **changes)

            with patch.object(builder.time, 'sleep', side_effect=respond):
                with self.assertRaisesRegex(builder.CraftBuilderError, 'mismatched editor result'):
                    builder.send_request(self.ksp, 'inspect')
            self.assertEqual(list(self.requests.iterdir()), [])
        with patch.object(builder.os, 'replace', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                builder.send_request(self.ksp, 'inspect')
        self.assertEqual(list(self.requests.iterdir()), [])

    def test_busy_after_claim_does_not_abort_and_interrupt_cleans_up(self):
        calls = []

        def respond(_):
            calls.append(True)
            self.status['ready'] = False
            self.write_status()
            if len(calls) == 2:
                self.reply(builder.read_json(self.pending()[0]))

        with patch.object(builder.time, 'sleep', side_effect=respond):
            self.assertTrue(builder.send_request(self.ksp, 'inspect')['ok'])
        self.assertEqual(len(calls), 2)
        self.status['ready'] = True
        self.write_status()
        with patch.object(builder.time, 'sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                builder.send_request(self.ksp, 'inspect')
        self.assertEqual(list(self.requests.iterdir()), [])

    def test_wall_clock_expiration_with_stale_heartbeat_after_enqueue(self):
        for step in (6, 31):
            clock = [time.time()]
            self.status['updatedAt'] = clock[0]
            self.write_status()

            def advance(_):
                clock[0] += step

            with patch.object(builder.time, 'time', side_effect=lambda: clock[0]):
                with patch.object(builder.time, 'sleep', side_effect=advance):
                    with self.assertRaisesRegex(builder.CraftBuilderError, 'Timed out'):
                        builder.send_request(self.ksp, 'inspect', timeout=30)
            self.assertEqual(list(self.requests.iterdir()), [])

    def test_claimed_build_outlives_heartbeat_but_stale_status_cannot_enqueue(self):
        clock = [time.time()]
        self.status['updatedAt'] = clock[0]
        self.write_status()
        received = []

        def server(_):
            if not received:
                pending = self.pending()[0]
                received.append(builder.read_json(pending))
                pending.unlink()
                clock[0] += 6
            else:
                # The intervening poll must accept the stale heartbeat for this
                # operation, while another command must still fail before enqueue.
                with self.assertRaisesRegex(builder.CraftBuilderError, 'heartbeat is stale'):
                    builder.send_request(self.ksp, 'inspect')
                self.assertEqual(self.pending(), [])
                self.reply(received[0])

        with patch.object(builder.time, 'time', side_effect=lambda: clock[0]):
            with patch.object(builder.time, 'sleep', side_effect=server):
                result = builder.send_request(self.ksp, 'build', spec=placement(), timeout=30)
        self.assertTrue(result['ok'])
        self.assertEqual(len(received), 1)
        self.assertEqual(list(self.requests.iterdir()), [])

    def test_stale_status_still_detects_changed_session(self):
        clock = [time.time()]
        self.status['updatedAt'] = clock[0]
        self.write_status()

        def restart(_):
            clock[0] += 6
            self.status['session'] = 'b' * 32
            self.write_status()

        with patch.object(builder.time, 'time', side_effect=lambda: clock[0]):
            with patch.object(builder.time, 'sleep', side_effect=restart):
                with self.assertRaisesRegex(builder.CraftBuilderError, 'session changed'):
                    builder.send_request(self.ksp, 'inspect', timeout=30)
        self.assertEqual(list(self.requests.iterdir()), [])

    def test_unreadable_status_after_claim_waits_for_result_or_deadline(self):
        for malformed in (False, True):
            for completes in (False, True):
                clock = [time.time()]
                self.status['updatedAt'] = clock[0]
                self.write_status()
                received = []

                def server(_):
                    if not received:
                        pending = self.pending()[0]
                        received.append(builder.read_json(pending))
                        pending.unlink()
                        status_path = self.directory / 'status.json'
                        if malformed:
                            status_path.write_text('{', encoding='utf-8')
                        else:
                            status_path.unlink()
                        clock[0] += 6
                    elif completes:
                        self.reply(received[0])
                    else:
                        clock[0] += 30

                with self.subTest(malformed=malformed, completes=completes):
                    with patch.object(builder.time, 'time', side_effect=lambda: clock[0]):
                        with patch.object(builder.time, 'sleep', side_effect=server):
                            if completes:
                                self.assertTrue(builder.send_request(self.ksp, 'inspect')['ok'])
                            else:
                                with self.assertRaisesRegex(
                                        builder.CraftBuilderError, 'Timed out.*Outcome unknown'):
                                    builder.send_request(self.ksp, 'inspect')
                self.assertEqual(len(received), 1)
                self.assertEqual(list(self.requests.iterdir()), [])

    def test_late_result_does_not_extend_own_deadline(self):
        ticks = [0]

        def server(_):
            pending = self.pending()[0]
            request = builder.read_json(pending)
            pending.unlink()
            self.reply(request)
            ticks[0] += 31

        with patch.object(builder.time, 'monotonic', side_effect=lambda: ticks[0]):
            with patch.object(builder.time, 'sleep', side_effect=server):
                with self.assertRaisesRegex(
                        builder.CraftBuilderError, 'Timed out.*Outcome unknown'):
                    builder.send_request(self.ksp, 'inspect', timeout=30)
        self.assertEqual(list(self.requests.iterdir()), [])

    def test_cleanup_failure_is_reported_without_retry(self):
        ticks = [0]
        original_unlink = Path.unlink
        seen = []

        def fail_pending_unlink(path, *args, **kwargs):
            if path.parent == self.requests and path.suffix == '.json':
                raise PermissionError('denied')
            return original_unlink(path, *args, **kwargs)

        def advance(_):
            seen.extend(self.pending())
            ticks[0] += 2

        with patch.object(builder.time, 'monotonic', side_effect=lambda: ticks[0]):
            with patch.object(builder.time, 'sleep', side_effect=advance):
                with patch.object(Path, 'unlink', new=fail_pending_unlink):
                    with self.assertRaisesRegex(builder.CraftBuilderError,
                                                'Could not remove.*Outcome unknown'):
                        builder.send_request(self.ksp, 'inspect', timeout=1)
        self.assertEqual(len(seen), 1)
        self.assertEqual(self.pending(), seen)

    def test_cli_missing_status_and_invalid_build_do_not_enqueue(self):
        (self.directory / 'status.json').unlink()
        for arguments in (['inspect'], ['build', str(self.ksp / 'missing.json')]):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = builder.main(['--ksp-dir', str(self.ksp)] + arguments)
            self.assertEqual(code, 1)
            self.assertFalse(json.loads(output.getvalue())['ok'])
            self.assertEqual(list(self.requests.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
