"""
Language Router — maps file extensions to tree-sitter parsers.

Responsibilities:
  1. Detect language from file extension
  2. Decide whether a file should be skipped (migrations, minified, vendor, etc.)
  3. Lazily initialize and cache tree-sitter parsers (one per language per process)

Usage:
    from apps.parsing.language_router import get_language, get_parser_for_file, should_skip

    language = get_language('src/auth/utils.py')       # → 'python'
    language, parser = get_parser_for_file('app.ts')   # → ('typescript', <Parser>)
    skip = should_skip('vendor/lodash.js')             # → True
"""

import re
import threading
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level parser cache — shared across tasks in the same worker process
# ---------------------------------------------------------------------------
_PARSERS: dict = {}
_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Extension → language name
# ---------------------------------------------------------------------------

EXTENSION_MAP: dict[str, str] = {
    # Python
    '.py': 'python',
    '.pyw': 'python',
    # JavaScript / JSX — both use the JS grammar
    '.js': 'javascript',
    '.jsx': 'javascript',
    '.mjs': 'javascript',
    '.cjs': 'javascript',
    # TypeScript / TSX — different parsers (TSX allows JSX syntax inside TS)
    '.ts': 'typescript',
    '.tsx': 'tsx',
    # Java
    '.java': 'java',
    # Go
    '.go': 'go',
    # Rust
    '.rs': 'rust',
    # C
    '.c': 'c',
    '.h': 'c',
    # C++
    '.cpp': 'cpp',
    '.cc': 'cpp',
    '.cxx': 'cpp',
    '.hpp': 'cpp',
    '.hxx': 'cpp',
    # Ruby
    '.rb': 'ruby',
    '.rake': 'ruby',
    # PHP
    '.php': 'php',
    '.php3': 'php',
    '.php4': 'php',
    '.php5': 'php',
    '.phtml': 'php',
}

# ---------------------------------------------------------------------------
# Skip list — directories always ignored
# ---------------------------------------------------------------------------

SKIP_DIRS: frozenset[str] = frozenset({
    'vendor',
    'node_modules',
    '.git',
    'dist',
    'build',
    '__pycache__',
    '.venv',
    'venv',
    'env',
    '.tox',
    'coverage',
    '.nyc_output',
    'target',       # Rust / Java build output
    'out',
    'bin',
    'obj',
    '.idea',
    '.vscode',
})

# ---------------------------------------------------------------------------
# Skip list — regex patterns matched against the full file path
# ---------------------------------------------------------------------------

_SKIP_PATTERNS: list[re.Pattern] = [
    re.compile(r'/migrations/\d+_.*\.py$'),      # Django migrations
    re.compile(r'(?:^|/)alembic/versions/.*\.py$'),  # Alembic migrations
    re.compile(r'_pb2\.py$'),                     # Protobuf Python
    re.compile(r'\.pb\.go$'),                     # Protobuf Go
    re.compile(r'\.pb\.ts$'),                     # Protobuf TypeScript
    re.compile(r'\.min\.js$'),                    # Minified JS
    re.compile(r'\.min\.css$'),                   # Minified CSS
    re.compile(r'\.generated\.[a-z]+$'),          # *.generated.*
    re.compile(r'\.auto\.[a-z]+$'),               # *.auto.*
    re.compile(r'package-lock\.json$'),
    re.compile(r'yarn\.lock$'),
    re.compile(r'Gemfile\.lock$'),
    re.compile(r'Cargo\.lock$'),
    # Test files — intentionally contain dangerous-looking fixture strings
    # (e.g. eval(user_input), SELECT queries, hardcoded passwords as test input).
    # Security detectors produce near-100% false positives on test code.
    re.compile(r'(?:^|/)tests?\.py$'),            # tests.py / test.py
    re.compile(r'(?:^|/)test_[^/]+\.py$'),        # test_*.py  (pytest style)
    re.compile(r'(?:^|/)[^/]+_tests?\.py$'),      # *_test.py / *_tests.py
    re.compile(r'(?:^|/)tests?/'),                # tests/ or test/ directory
    re.compile(r'(?:^|/)__tests__/'),             # __tests__/ (JS/TS Jest style)
    re.compile(r'\.test\.[jt]sx?$'),              # *.test.js/ts/jsx/tsx  (Jest)
    re.compile(r'\.spec\.[jt]sx?$'),              # *.spec.js/ts/jsx/tsx  (Jest/Jasmine)
]

# Any line longer than this → treat file as minified, skip it
_MINIFIED_LINE_LENGTH = 500


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_language(file_path: str) -> Optional[str]:
    """
    Return the language name for a file path, or None if unsupported.

    Examples:
        get_language('src/auth/utils.py')   → 'python'
        get_language('components/App.tsx')  → 'tsx'
        get_language('README.md')           → None
    """
    suffix = Path(file_path).suffix.lower()
    return EXTENSION_MAP.get(suffix)


def should_skip(file_path: str, content: str = '') -> bool:
    """
    Return True if this file should be excluded from analysis.

    Checks (cheapest first):
      1. A path component is a known skip directory
      2. The path matches a skip regex (migrations, protobuf, minified, etc.)
      3. Content is provided and any line exceeds the minified threshold

    The skip list is configurable via stratum.yaml (Phase 2).
    """
    if _is_in_skip_dir(file_path):
        logger.debug("skip_dir_match", file_path=file_path)
        return True

    if _matches_skip_pattern(file_path):
        logger.debug("skip_pattern_match", file_path=file_path)
        return True

    if content and _is_minified(content):
        logger.debug("skip_minified", file_path=file_path)
        return True

    return False


def get_parser(language: str):
    """
    Return a cached tree-sitter Parser for the given language name.

    Parsers are created lazily on first call and cached for the process lifetime.
    Thread-safe via double-checked locking.

    Raises ValueError for unsupported language names.
    """
    if language not in _PARSERS:
        with _LOCK:
            if language not in _PARSERS:  # double-checked locking
                from tree_sitter import Parser
                lang_obj = _load_language(language)
                _PARSERS[language] = Parser(lang_obj)
                logger.info("parser_initialized", language=language)
    return _PARSERS[language]


def get_parser_for_file(file_path: str):
    """
    Convenience: return (language, parser) for a file path.
    Returns (None, None) if the file extension is not supported.

    Example:
        language, parser = get_parser_for_file('auth/views.py')
        # language = 'python', parser = <tree_sitter.Parser>
    """
    language = get_language(file_path)
    if not language:
        return None, None
    return language, get_parser(language)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_in_skip_dir(file_path: str) -> bool:
    """Return True if any component of the path is a known skip directory."""
    parts = Path(file_path.replace('\\', '/')).parts
    return any(part in SKIP_DIRS for part in parts)


def _matches_skip_pattern(file_path: str) -> bool:
    """Return True if the normalized path matches any skip regex."""
    normalized = file_path.replace('\\', '/')
    return any(pattern.search(normalized) for pattern in _SKIP_PATTERNS)


def _is_minified(content: str) -> bool:
    """Return True if any single line exceeds the minified threshold."""
    return any(len(line) > _MINIFIED_LINE_LENGTH for line in content.splitlines())


def _load_language(language: str):
    """
    Import the grammar package for the given language and return a Language object.

    Imports are deferred inside this function so that:
    - Startup is fast (no eager import of 10 grammar packages)
    - A missing grammar package fails only when that language is first requested
    """
    import tree_sitter_c as tsc
    import tree_sitter_cpp as tscpp
    import tree_sitter_go as tsgo
    import tree_sitter_java as tsjava
    import tree_sitter_javascript as tsjs
    import tree_sitter_php as tsphp
    import tree_sitter_python as tspython
    import tree_sitter_ruby as tsruby
    import tree_sitter_rust as tsrust
    import tree_sitter_typescript as tsts
    from tree_sitter import Language

    _LOADERS = {
        'python':     lambda: Language(tspython.language()),
        'javascript': lambda: Language(tsjs.language()),
        'typescript': lambda: Language(tsts.language_typescript()),
        'tsx':        lambda: Language(tsts.language_tsx()),
        'java':       lambda: Language(tsjava.language()),
        'go':         lambda: Language(tsgo.language()),
        'rust':       lambda: Language(tsrust.language()),
        'c':          lambda: Language(tsc.language()),
        'cpp':        lambda: Language(tscpp.language()),
        'ruby':       lambda: Language(tsruby.language()),
        'php':        lambda: Language(tsphp.language_php()),
    }

    if language not in _LOADERS:
        raise ValueError(
            f"No tree-sitter grammar for '{language}'. "
            f"Supported: {', '.join(sorted(_LOADERS))}"
        )

    return _LOADERS[language]()
