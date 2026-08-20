#!/usr/bin/env python3
"""
Standardize a single .pre-commit-config.yaml in place:
  - bump pre-commit-hooks / ruff-pre-commit / mypy / check-manifest / codespell revs
  - drop the black hook entirely
  - make sure ruff-pre-commit has both `ruff` and `ruff-format`, each with
    args: [--config=pyproject.toml]
Everything else (napari-plugin-checks, exclude:, ci:, extra mypy deps, etc.)
is left untouched.
"""
import sys
from ruamel.yaml import YAML

yaml = YAML()
yaml.preserve_quotes = True
yaml.width = 4096
yaml.indent(mapping=4, sequence=4, offset=2)

REVS = {
    "https://github.com/pre-commit/pre-commit-hooks": "v6.0.0",
    "https://github.com/astral-sh/ruff-pre-commit": "v0.16.1",
    "https://github.com/pre-commit/mirrors-mypy": "v1.13.0",
    "https://github.com/mgedmin/check-manifest": "0.50",
    "https://github.com/codespell-project/codespell": "v2.4.3",
}
BLACK_REPO = "https://github.com/psf/black-pre-commit-mirror"
RUFF_REPO = "https://github.com/astral-sh/ruff-pre-commit"
RUFF_ARGS = ["--config=pyproject.toml"]


def fix_ruff_hooks(entry):
    ids = {h["id"] for h in entry["hooks"]}
    for h in entry["hooks"]:
        h["args"] = list(RUFF_ARGS)
    if "ruff-format" not in ids:
        fmt = type(entry["hooks"][0])()
        fmt["id"] = "ruff-format"
        fmt["args"] = list(RUFF_ARGS)
        entry["hooks"].append(fmt)


def standardize(path):
    with open(path) as f:
        data = yaml.load(f)

    new_repos = []
    for entry in data["repos"]:
        url = entry["repo"]
        if url == BLACK_REPO:
            continue  # drop black entirely
        if url in REVS:
            entry["rev"] = REVS[url]
        if url == RUFF_REPO:
            fix_ruff_hooks(entry)
        new_repos.append(entry)
    data["repos"] = new_repos

    with open(path, "w") as f:
        yaml.dump(data, f)


standardize(sys.argv[1] if len(sys.argv) > 1 else ".pre-commit-config.yaml")
print(f"standardized {sys.argv[1] if len(sys.argv) > 1 else '.pre-commit-config.yaml'}")