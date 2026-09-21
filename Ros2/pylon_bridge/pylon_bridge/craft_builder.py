"""Explicit part placement CLI; runnable with python -m pylon_bridge.craft_builder.

This module deliberately uses only the Python standard library. Positions and
quaternions are passed to the editor unchanged; no URDF conversion is involved.
"""

import argparse
import json
import math
import os
from pathlib import Path
import re
import time
import unicodedata
import uuid


MAX_JSON_BYTES = 1024 * 1024
HEARTBEAT_SECONDS = 5.0
POLL_SECONDS = 0.05
DEFAULT_KSP_DIR = Path.home() / '.local/share/Steam/steamapps/common/Kerbal Space Program'
PROTOCOL_DIR = Path('PluginData/PyLoN/CraftBuilder')
ID_PATTERN = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}', re.ASCII)
PART_PATTERN = re.compile(r'[A-Za-z0-9_.-]{1,128}', re.ASCII)
NODE_PATTERN = re.compile(r'[A-Za-z0-9_.-]{1,64}', re.ASCII)
SESSION_PATTERN = re.compile(r'[0-9a-f]{32}', re.ASCII)


class CraftBuilderError(ValueError):
    """Invalid input or an unsuccessful local transport operation."""


def _fail(message):
    raise CraftBuilderError(message)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail(f'Duplicate JSON field: {key}')
        result[key] = value
    return result


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _parse_float(value):
    number = float(value)
    if not math.isfinite(number):
        _fail('JSON numbers must be finite')
    return number


def read_json(path):
    """Read bounded UTF-8 JSON, rejecting duplicate keys and nonfinite numbers."""
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        _fail('JSON exceeds the 1 MiB limit')
    try:
        return json.loads(
            raw.decode('utf-8'), object_pairs_hook=_unique_object,
            parse_float=_parse_float,
            parse_constant=lambda value: _fail(f'Invalid JSON constant: {value}'),
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise CraftBuilderError(f'Invalid JSON in {path}: {exc}') from exc


def _fields(value, required, optional, label):
    if not isinstance(value, dict):
        _fail(f'{label} must be an object')
    missing = set(required) - value.keys()
    unknown = value.keys() - set(required) - set(optional)
    if missing:
        _fail(f'{label} missing fields: {", ".join(sorted(missing))}')
    if unknown:
        _fail(f'{label} unknown fields: {", ".join(sorted(unknown))}')


def _token(value, pattern, label):
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        _fail(f'{label} is not a valid ASCII token')


def _vector(value, length, label, limit=None):
    if not isinstance(value, list) or len(value) != length:
        _fail(f'{label} must be an array of {length} numbers')
    if not all(_finite_number(number) for number in value):
        _fail(f'{label} must contain finite numbers (not booleans)')
    if limit is not None and any(abs(number) > limit for number in value):
        _fail(f'{label} components must be within +/-{limit}')
    return list(value)


def validate_spec(spec):
    """Validate and copy a placement spec, filling root parent and stage defaults."""
    _fields(spec, ('version', 'name', 'facility', 'parts'), (), 'spec')
    if type(spec['version']) is not int or spec['version'] != 1:
        _fail('spec.version must be integer 1')
    name = spec['name']
    if (not isinstance(name, str) or not name.strip() or len(name) > 80
            or name.strip() in ('.', '..') or '/' in name or '\\' in name
            or any(unicodedata.category(char) in ('Cc', 'Cf', 'Cs') for char in name)):
        _fail('spec.name must be a safe nonblank name of at most 80 characters')
    if spec['facility'] not in ('VAB', 'SPH'):
        _fail('spec.facility must be VAB or SPH')
    if not isinstance(spec['parts'], list) or not 1 <= len(spec['parts']) <= 256:
        _fail('spec.parts must contain 1..256 parts')

    parts = []
    by_id = {}
    occupied_nodes = set()
    for index, part in enumerate(spec['parts']):
        label = f'parts[{index}]'
        _fields(part, ('id', 'part', 'position', 'rotation'),
                ('parent', 'attach', 'stage', 'autostrut', 'rigid_attachment',
                 'separation_force_percent', 'role'), label)
        _token(part['id'], ID_PATTERN, f'{label}.id')
        _token(part['part'], PART_PATTERN, f'{label}.part')
        if part['id'] in by_id:
            _fail(f'Duplicate part id: {part["id"]}')
        position = _vector(part['position'], 3, f'{label}.position', 1000)
        rotation = _vector(part['rotation'], 4, f'{label}.rotation')
        if abs(math.hypot(*rotation) - 1.0) > 0.001:
            _fail(f'{label}.rotation quaternion norm must be within 0.001 of 1')
        parent = part.get('parent', '')
        if parent != '':
            _token(parent, ID_PATTERN, f'{label}.parent')
        stage = part.get('stage', -1)
        if type(stage) is not int or not -1 <= stage <= 99:
            _fail(f'{label}.stage must be an integer in -1..99')
        normalized = dict(id=part['id'], part=part['part'], position=position,
                          rotation=rotation, parent=parent, stage=stage)
        if 'autostrut' in part:
            if part['autostrut'] not in ('off', 'root', 'heaviest', 'grandparent'):
                _fail(f'{label}.autostrut must be off, root, heaviest or grandparent')
            normalized['autostrut'] = part['autostrut']
        if 'rigid_attachment' in part:
            if type(part['rigid_attachment']) is not bool:
                _fail(f'{label}.rigid_attachment must be a boolean')
            normalized['rigid_attachment'] = part['rigid_attachment']
        if 'separation_force_percent' in part:
            force = part['separation_force_percent']
            if not _finite_number(force) or not 0 <= force <= 100:
                _fail(f'{label}.separation_force_percent must be a finite number in 0..100')
            normalized['separation_force_percent'] = force
        if 'role' in part:
            _token(part['role'], ID_PATTERN, f'{label}.role')
            normalized['role'] = part['role']
        if parent == '':
            if 'attach' in part:
                _fail(f'{label}: root attach must be omitted')
            if any(abs(number) > 1e-6 for number in position):
                _fail('Root position must be [0,0,0] within 1e-6')
            if any(abs(a - b) > 1e-6 for a, b in zip(rotation, (0, 0, 0, 1))):
                _fail('Root rotation must be positive identity [0,0,0,1] within 1e-6')
        else:
            attach = part.get('attach')
            _fields(attach, ('mode', 'node', 'parent_node'), (), f'{label}.attach')
            if attach['mode'] == 'surface':
                if attach['node'] != 'srfAttach' or attach['parent_node'] != '':
                    _fail('Surface attach requires node srfAttach and empty parent_node')
            elif attach['mode'] == 'stack':
                _token(attach['node'], NODE_PATTERN, f'{label}.attach.node')
                _token(attach['parent_node'], NODE_PATTERN, f'{label}.attach.parent_node')
            else:
                _fail(f'{label}.attach.mode must be stack or surface')
            # Both ends share one occupancy namespace, regardless of input order.
            # Surface attachments consume only the child's srfAttach node.
            endpoints = [(part['id'], attach['node'])]
            if attach['mode'] == 'stack':
                endpoints.append((parent, attach['parent_node']))
            for part_id, node in endpoints:
                key = f'{part_id}:{node}'
                if key in occupied_nodes:
                    _fail(f'Attachment node already occupied: {key}')
                occupied_nodes.add(key)
            normalized['attach'] = dict(attach)
        by_id[part['id']] = normalized
        parts.append(normalized)

    roots = [part['id'] for part in parts if part['parent'] == '']
    if len(roots) != 1:
        _fail('Exactly one root part is required')
    # Iterative traversal accepts forward references without recursion limits.
    connected = {roots[0]}
    for part in parts:
        chain = set()
        current = part['id']
        while current not in connected:
            if current in chain:
                _fail(f'Parent cycle involving {current}')
            if current not in by_id:
                _fail(f'Unknown parent id: {current}')
            chain.add(current)
            current = by_id[current]['parent']
        connected.update(chain)
    return dict(version=1, name=name, facility=spec['facility'], parts=parts)


def validate_timeout(value):
    try:
        timeout = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise CraftBuilderError('timeout must be finite and in 1..120 seconds') from exc
    if isinstance(value, bool) or not math.isfinite(timeout) or not 1 <= timeout <= 120:
        _fail('timeout must be finite and in 1..120 seconds')
    return timeout


def _status(directory, require_ready):
    status = read_json(directory / 'status.json')
    if (not isinstance(status, dict) or type(status.get('version')) is not int
            or status['version'] != 1):
        _fail('Invalid editor status version')
    _token(status.get('session'), SESSION_PATTERN, 'status.session')
    updated = status.get('updatedAt')
    if not _finite_number(updated) or not 0 <= time.time() - updated <= HEARTBEAT_SECONDS:
        _fail('Editor status heartbeat is stale or invalid (maximum age 5 seconds)')
    if (type(status.get('ready')) is not bool or status.get('facility') not in ('VAB', 'SPH')
            or not isinstance(status.get('save'), str)):
        _fail('Invalid editor status fields')
    if require_ready and not status['ready']:
        _fail('Editor is not ready')
    return status


def _result(path, request_id):
    result = read_json(path)
    if (not isinstance(result, dict) or type(result.get('version')) is not int
            or result['version'] != 1 or result.get('id') != request_id
            or type(result.get('ok')) is not bool
            or not isinstance(result.get('error'), str)
            or not isinstance(result.get('craftPath'), str)
            or type(result.get('loaded')) is not bool
            or not isinstance(result.get('parts'), list)):
        _fail('Invalid or mismatched editor result')
    return result


def _remove_pending(path):
    try:
        path.unlink()
        return 'removed'
    except FileNotFoundError:
        return 'absent'
    except OSError:
        return 'failed'


def send_request(ksp_dir, command, *, timeout=30, filter_text='', load=False, spec=None):
    """Perform one session-bound request. Never retry an uncertain operation."""
    timeout = validate_timeout(timeout)
    if command not in ('parts', 'build', 'inspect'):
        _fail('Unknown editor command')
    if not isinstance(filter_text, str) or type(load) is not bool:
        _fail('filter must be text and load must be boolean')
    if load and command != 'build':
        _fail('load is only supported for build')
    normalized = validate_spec(spec) if command == 'build' else {}
    directory = Path(ksp_dir).expanduser() / PROTOCOL_DIR
    status = _status(directory, require_ready=True)
    request_id = uuid.uuid4().hex
    pending = directory / 'requests' / f'{request_id}.json'
    temporary = pending.with_suffix('.tmp')
    result_path = directory / 'results' / f'{request_id}.json'
    pending.parent.mkdir(parents=True, exist_ok=True)
    published = False
    try:
        now = time.time()
        deadline = time.monotonic() + timeout
        request = dict(version=1, id=request_id, session=status['session'],
                       expiresAt=now + timeout, command=command, filter=filter_text,
                       load=load, spec=normalized)
        payload = json.dumps(request, ensure_ascii=True, allow_nan=False).encode('utf-8')
        if len(payload) > MAX_JSON_BYTES:
            _fail('Request JSON exceeds the 1 MiB limit')
        with temporary.open('xb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Recheck after preparing the payload; a restart must not bind it to a new session.
        if _status(directory, require_ready=True)['session'] != status['session']:
            _fail('Editor session changed before enqueue')
        if time.time() >= request['expiresAt'] or time.monotonic() >= deadline:
            _fail('Request expired before enqueue')
        os.replace(temporary, pending)
        published = True
        while True:
            remaining = min(deadline - time.monotonic(), request['expiresAt'] - time.time())
            if remaining <= 0:
                _fail('Timed out waiting for editor result')
            try:
                return _result(result_path, request_id)
            except FileNotFoundError:
                pass
            # Synchronous editor work can block Update and its heartbeat. Once
            # enqueued, use our deadline and watch for restarts when status is readable.
            try:
                current_status = read_json(directory / 'status.json')
            except (OSError, CraftBuilderError):
                current_status = None
            if (isinstance(current_status, dict)
                    and isinstance(current_status.get('session'), str)
                    and current_status['session'] != status['session']):
                _fail('Editor session changed while waiting for result')
            time.sleep(min(POLL_SECONDS, remaining))
    except (OSError, ValueError) as exc:
        if published:
            cleanup = _remove_pending(pending)
            detail = {
                'absent': 'No pending request remains; it may have been claimed.',
                'removed': 'Removed own pending request; execution may have raced cleanup.',
                'failed': 'Could not remove own pending request.',
            }[cleanup]
            raise CraftBuilderError(
                f'{exc}. Request {request_id}: {detail} Outcome unknown; no automatic retry.'
            ) from exc
        raise
    finally:
        _remove_pending(temporary)
        if published:
            _remove_pending(pending)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ksp-dir', default=os.environ.get('KSPDIR') or str(DEFAULT_KSP_DIR))
    parser.add_argument('--timeout', type=validate_timeout, default=30,
                        help='request timeout in seconds (1..120; default 30)')
    commands = parser.add_subparsers(dest='command', required=True)
    validate = commands.add_parser('validate', help='validate a placement file offline')
    validate.add_argument('file', metavar='FILE')
    parts = commands.add_parser('parts', help='list editor parts')
    parts.add_argument('--filter', default='')
    build = commands.add_parser('build', help='build a craft from explicit part placements')
    build.add_argument('file', metavar='FILE')
    build.add_argument('--load', action='store_true',
                       help='load into an empty editor (enforced by the server)')
    commands.add_parser('inspect', help='inspect the editor craft')
    args = parser.parse_args(argv)
    try:
        spec = None
        if args.command in ('validate', 'build'):
            spec = validate_spec(read_json(args.file))
        if args.command == 'validate':
            result = dict(version=1, ok=True, spec=spec)
        else:
            result = send_request(args.ksp_dir, args.command, timeout=args.timeout,
                                  filter_text=getattr(args, 'filter', ''),
                                  load=getattr(args, 'load', False), spec=spec)
    except (OSError, ValueError) as exc:
        result = dict(version=1, ok=False, error=str(exc))
    except KeyboardInterrupt:
        print(json.dumps(dict(
            version=1, ok=False,
            error='Interrupted; outcome unknown if enqueued. No automatic retry.',
        )))
        return 130
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
