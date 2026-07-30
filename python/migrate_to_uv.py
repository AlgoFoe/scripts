#!/usr/bin/env python3

import re
import sys
from pathlib import Path

WORKFLOW_PATH  = Path(sys.argv[1])
PYPROJECT_PATH = Path(sys.argv[2])


def has_separate_napari_extra(pyproject: str):
    m = re.search(r'\[project\.optional-dependencies\](.*?)(?=\n\[|\Z)',
                  pyproject, re.DOTALL)
    if not m:
        return False
    return bool(re.search(r'^napari\s*=\s*\[', m.group(1), re.MULTILINE))


def workflow_uses_headless(workflow: str):
    return (
        'pyvista/setup-headless-display-action' in workflow
        or 'use-xvfb' in workflow
        or 'headless-gui' in workflow
    )


def get_install_extras(pyproject: str, napari_extra: bool):
    if not napari_extra:
        return 'dev'
    # check if tox testenv used the napari extra
    m = re.search(r'\[testenv\](.*?)(?=\n\[|\Z)', pyproject, re.DOTALL)
    if m and re.search(r'\bnapari\b', m.group(1)):
        return 'dev,napari'
    return 'dev'



def find_step_blocks(lines: list):
    blocks      = []
    in_steps    = False
    step_indent = None
    block_start = None

    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        ind = len(line) - len(line.lstrip())

        # Enter a steps: block
        if re.match(r'\s*steps\s*:', line):
            if block_start is not None:# close previous open block
                blocks.append((block_start, i))
                block_start = None
            in_steps    = True
            step_indent = None
            continue

        if in_steps:
            if s.startswith('- ') or s == '-':
                if step_indent is None:
                    step_indent = ind
                if ind == step_indent:# new sibling step
                    if block_start is not None:
                        blocks.append((block_start, i))
                    block_start = i
            elif step_indent is not None and ind <= step_indent and not s.startswith('-'):
                # left the steps block
                if block_start is not None:
                    blocks.append((block_start, i))
                    block_start = None
                in_steps    = False
                step_indent = None

    if block_start is not None:
        blocks.append((block_start, len(lines)))
    return blocks


def step_base_indent(lines: list, start: int):
    for i in range(start, min(start + 5, len(lines))):
        if lines[i].strip().startswith('-'):
            return ' ' * (len(lines[i]) - len(lines[i].lstrip()))
    return '      '


def extract_kv(block: str, key: str, default: str = ''):
    m = re.search(
        rf'^\s*{re.escape(key)}:\s*["\']?([^\n"\']+)["\']?',
        block, re.MULTILINE
    )
    return m.group(1).strip() if m else default


def test_uv_block(
    ind: str,
    python_version: str,
    install_extras: str,
    use_headless: bool,
    codecov_flags:      str = '',
    install_main_branch: str = '',
    name:      str = 'Run tests',
    condition: str = '',
):
    p = ind + '  '   # property indent  (uses:, with:, if:)
    w = ind + '    ' # with-value indent
    lines = [f'{ind}- name: {name}']
    if condition:
        lines.append(f'{p}if: {condition}')
    lines.append(f'{p}uses: neuroinformatics-unit/actions/test-uv@main')
    lines.append(f'{p}with:')
    lines.append(f'{w}python-version: {python_version}')
    lines.append(f'{w}secret-codecov-token: ${{{{ secrets.CODECOV_TOKEN }}}}')
    if install_extras and install_extras != 'dev':
        lines.append(f"{w}install-extras: '{install_extras}'")
    if use_headless:
        lines.append(f"{w}use-headless: 'true'")
    if codecov_flags:
        lines.append(f'{w}codecov-flags: "{codecov_flags}"')
    if install_main_branch:
        lines.append(f"{w}install-main-branch: '{install_main_branch}'")
    lines.append('')
    return '\n'.join(lines) + '\n'

def remove_headless_setup(lines: list):
    changes = []
    blocks = find_step_blocks(lines)

    for i, (start, end) in enumerate(blocks):
        block = ''.join(lines[start:end])

        if (
            'pyvista/setup-headless-display-action' in block
            or 'use-xvfb' in block
            or 'headless-gui' in block
        ):
            changes.append((start, end, None))
            print('  [REMOVE] Headless display setup')

            if i > 0:
                prev_start, prev_end = blocks[i - 1]
                prev_block = ''.join(lines[prev_start:prev_end])

                if 'tlambert03/setup-qt-libs' in prev_block:
                    changes.append((prev_start, prev_end, None))
                    print('  [REMOVE] setup-qt-libs')

    for start, end, _ in sorted(changes, key=lambda x: x[0], reverse=True):
        del lines[start:end]

    return bool(changes)

def setup_uv_block(ind: str, python_version: str):
    p = ind + '  '
    w = ind + '    '
    return (
        f'{ind}- name: Install uv\n'
        f'{p}uses: astral-sh/setup-uv@fac544c07dec837d0ccb6301d7b5580bf5edae39 # v8.2.0\n'
        f'{p}with:\n'
        f'{w}enable-cache: true\n'
        f'{w}python-version: "{python_version}"\n'
        f'{w}cache-dependency-glob: "**/pyproject.toml"\n'
        f'{w}activate-environment: true\n'
    )


def migrate_workflow(
    path: Path,
    install_extras: str,
    use_headless: bool,
):
    if not path.exists():
        print(f'  [SKIP] Workflow not found: {path}')
        return False

    text = path.read_text(encoding='utf-8')
    original = text

    if 'test-uv@main' in text and 'actions/test@v2' not in text:
        print('  [SKIP] Workflow already migrated.')
        return False

    lines   = text.splitlines(keepends=True)
    changes = [] # (start, end, new_str | None)
    remove_headless_setup(lines)

    for start, end in find_step_blocks(lines):
        block = ''.join(lines[start:end])
        ind   = step_base_indent(lines, start)

        if 'actions/setup-python' in block:
            pyver = extract_kv(block, 'python-version', '3.12').strip('"\'')
            if '${{' in pyver:
                # matrix job - composite action installs via uv
                changes.append((start, end, None))
                print('  [REMOVE] setup-python (matrix - uv handles Python)')
            else:
                new = setup_uv_block(ind, pyver)
                changes.append((start, end, new))
                print(f'  [REPLACE] setup-python - setup-uv (py{pyver})')

        elif 'python -m pip install' in block and 'run:' in block:
            new = block
            # drop the pip-upgrade line
            new = re.sub(r'[ \t]*python -m pip install --upgrade pip.*\n', '', new)
            new = new.replace('python -m pip install', 'uv pip install')
            new = new.replace('python -m pytest', 'pytest')
            if 'shell:' not in new:
                new = re.sub(r'(\s+run:\s)', r'\n        shell: bash\1', new, count=1)
            if new != block:
                changes.append((start, end, new))
                print('  [REPLACE] pip - uv pip in install step')

        elif (
            'neuroinformatics-unit/actions/test@v2' in block
            and 'napari-dev' in block
        ):
            pyver = extract_kv(
                block, 'python-version', '${{ matrix.python-version }}'
            )
            new = test_uv_block(
                ind, pyver, install_extras, use_headless,
                install_main_branch='napari/napari',
                name='Run tests on napari main',
                condition=(
                    "github.event_name == 'schedule' "
                    "|| github.event_name == 'workflow_dispatch'"
                ),
            )
            changes.append((start, end, new))
            print('  [REPLACE] napari-dev test@v2 - test-uv@main + install-main-branch')

        elif 'neuroinformatics-unit/actions/test@v2' in block:
            pyver = extract_kv(
                block, 'python-version', '${{ matrix.python-version }}'
            )
            flags = extract_kv(block, 'codecov-flags')
            name  = extract_kv(block, 'name', 'Run tests')
            new   = test_uv_block(
                ind, pyver, install_extras, use_headless,
                codecov_flags=flags,
                name=name if name else 'Run tests',
            )
            changes.append((start, end, new))
            print(f'  [REPLACE] test@v2 - test-uv@main (name="{name or "Run tests"}")')

    for start, end, new in sorted(changes, key=lambda x: x[0], reverse=True):
        if new is None:
            del lines[start:end]
        else:
            lines[start:end] = [new]

    lines = [ln.replace('actions/cache@v3', 'actions/cache@1bd1e32a3bdc45362d1e726936510720a7c30a57') for ln in lines]

    text = ''.join(lines)
    if text == original:
        print('  [SKIP] No workflow changes detected.')
        return False

    path.write_text(text, encoding='utf-8')
    print('  [OK] Workflow migrated.')
    return True


def migrate_pyproject(path: Path):
    if not path.exists():
        print(f'  [SKIP] pyproject.toml not found: {path}')
        return False

    text = path.read_text(encoding='utf-8')
    original = text

    #1. remove tox and tox-* packages from any extras
    text = re.sub(r'[ \t]*"tox(?:-[a-z-]+)?",?\n', '', text)

    #2. remove entire [tool.tox] section
    text = re.sub(
        r'\[tool\.tox\]\s*legacy_tox_ini\s*=\s*""".*?"""[\r\n]*',
        '',
        text,
        flags=re.DOTALL,
    )

    #3. update [tool.pytest.ini_options] addopts
    def update_addopts(m: re.Match):
        inner = m.group(1).strip('"\'')
        for flag in ('--cov-report=xml', '--color=yes'):
            if flag not in inner:
                inner += f' {flag}'
        inner = re.sub(r'(?<![v\-])-v\b(?!v)', '-vv', inner)
        if '-vv' not in inner:
            inner += ' -vv'
        return f'addopts = "{inner.strip()}"'

    text = re.sub(r'addopts\s*=\s*(["\'].*?["\'])', update_addopts, text)

    text = re.sub(r'\n{3,}', '\n\n', text)

    if text == original:
        print('  [SKIP] pyproject.toml already up to date.')
        return False

    path.write_text(text, encoding='utf-8')
    print('  [OK] pyproject.toml migrated.')
    return True


pyproject_text = PYPROJECT_PATH.read_text(encoding='utf-8') if PYPROJECT_PATH.exists() else ''
workflow_text  = WORKFLOW_PATH.read_text(encoding='utf-8')  if WORKFLOW_PATH.exists() else ''

napari_extra   = has_separate_napari_extra(pyproject_text)
headless       = workflow_uses_headless(workflow_text)
install_extras = get_install_extras(pyproject_text, napari_extra)

print(
    f'  [DETECT] napari_extra={napari_extra}  '
    f'headless={headless}  '
    f'install_extras={install_extras}'
)

wf_changed = migrate_workflow(WORKFLOW_PATH, install_extras, headless)
py_changed = migrate_pyproject(PYPROJECT_PATH)

if not wf_changed and not py_changed:
    sys.exit(2)