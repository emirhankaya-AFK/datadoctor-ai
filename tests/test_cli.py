import subprocess
import sys


def _call(*args):
    return subprocess.run([sys.executable, '-m', 'datadoctor.cli', *map(str, args)], capture_output=True, text=True)


def test_cli_preserves_original_on_clean(tmp_path):
    original = tmp_path / 'original.csv'
    initial = b'product,price\n001,20\n001,20\n'
    original.write_bytes(initial)
    result = _call('clean', original, '-o', original)
    assert result.returncode == 2
    assert original.read_bytes() == initial
    assert 'different' in result.stderr


def test_cli_preserves_original_on_report(tmp_path):
    original = tmp_path / 'original.csv'
    initial = b'a,b\n1,2\n'
    original.write_bytes(initial)
    result = _call('analyze', original, '--report', original)
    assert result.returncode == 2
    assert original.read_bytes() == initial


def test_cli_prevents_overwrite_via_hardlink(tmp_path):
    original = tmp_path / 'original.csv'
    alias = tmp_path / 'alias.csv'
    original.write_bytes(b'id\n001\n')
    import os
    os.link(original, alias)
    result = _call('clean', original, '-o', alias)
    assert result.returncode == 2
    assert alias.read_bytes() == b'id\n001\n'


def test_cli_works_and_writes_new_copy(tmp_path):
    original = tmp_path / 'original.csv'
    output = tmp_path / 'clean.csv'
    original.write_bytes(b'id,value\n001,10\n001,10\n002,20\n')
    result = _call('clean', original, '-o', output)
    assert result.returncode == 0, result.stderr
    assert original.read_bytes() == b'id,value\n001,10\n001,10\n002,20\n'
    assert '001,10' in output.read_text(encoding='utf-8-sig')
