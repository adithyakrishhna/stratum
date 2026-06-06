"""
Management command: backfill_raw_code

Populates raw_code for CodeChunk rows that have raw_code=NULL.
This happens when STORE_RAW_CODE was False during previous analyses and has
since been set to True. The incremental ingestion engine skips unchanged files,
so raw_code is never backfilled automatically on re-analysis.

This command reads each file from the current cloned repo on disk, extracts
the function text using stored start_line/end_line, and writes it back to the
CodeChunk row. It uses the current HEAD of the clone — not the exact historical
version — but for ongoing duplicate detection accuracy this is accurate enough
for functions that haven't changed.

Usage:
    python manage.py backfill_raw_code
    python manage.py backfill_raw_code --repo-id <uuid>
    python manage.py backfill_raw_code --dry-run
"""
import os
from collections import defaultdict

import structlog
from django.conf import settings
from django.core.management.base import BaseCommand

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = 'Backfill raw_code for CodeChunks that have raw_code=NULL'

    def add_arguments(self, parser):
        parser.add_argument(
            '--repo-id',
            type=str,
            default=None,
            help='Limit backfill to a specific repository UUID (default: all repos)',
        )
        parser.add_argument(
            '--source-dir',
            type=str,
            default=None,
            help=(
                'Override source directory for file lookups (used when the clone is '
                'missing but the code exists elsewhere). Example: --source-dir /app '
                'combined with --strip-prefix backend/ resolves backend/apps/foo.py '
                'to /app/apps/foo.py'
            ),
        )
        parser.add_argument(
            '--strip-prefix',
            type=str,
            default='',
            help='Strip this prefix from file_path before joining with --source-dir',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Print stats without writing to database',
        )

    def handle(self, *args, **options):
        from apps.parsing.models import CodeChunk

        repo_id = options['repo_id']
        dry_run = options['dry_run']
        source_dir = options.get('source_dir')
        strip_prefix = options.get('strip_prefix', '').lstrip('/')

        qs = CodeChunk.objects.filter(raw_code__isnull=True)
        if repo_id:
            qs = qs.filter(repo_id=repo_id)

        total_null = qs.count()
        if total_null == 0:
            self.stdout.write(self.style.SUCCESS('No chunks with NULL raw_code found.'))
            return

        self.stdout.write(f'Found {total_null} chunks with NULL raw_code.')
        if dry_run:
            self.stdout.write('Dry run — no changes written.')
            return

        from apps.repositories.models import Repository

        clone_base = getattr(settings, 'REPO_CLONE_BASE_DIR', '')

        # Build repo_id → clone_dir mapping  (clone path = base/owner/name)
        repo_clone_dirs: dict[str, str] = {}
        for repo in Repository.objects.all():
            repo_clone_dirs[str(repo.id)] = os.path.join(
                clone_base, repo.owner, repo.name
            )

        # Group by (repo_id, file_path) to read each file once
        rows = list(qs.values('id', 'repo_id', 'file_path', 'start_line', 'end_line'))
        by_repo_file: dict[tuple, list] = defaultdict(list)
        for row in rows:
            key = (str(row['repo_id']), row['file_path'])
            by_repo_file[key].append(row)

        updated = 0
        skipped_no_file = 0

        for (rid, file_path), chunks in by_repo_file.items():
            if source_dir:
                # Use explicit source directory with optional prefix stripping
                relative = file_path
                if strip_prefix and relative.startswith(strip_prefix):
                    relative = relative[len(strip_prefix):]
                full_path = os.path.join(source_dir, relative.lstrip('/'))
            else:
                clone_dir = repo_clone_dirs.get(rid, '')
                full_path = os.path.join(clone_dir, file_path)
            if not os.path.isfile(full_path):
                skipped_no_file += len(chunks)
                continue

            try:
                with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.readlines()
            except OSError:
                skipped_no_file += len(chunks)
                continue

            bulk: list[CodeChunk] = []
            for chunk in chunks:
                start = max(0, chunk['start_line'] - 1)  # 1-indexed → 0-indexed
                end = min(len(lines), chunk['end_line'])
                raw_code = ''.join(lines[start:end]).rstrip()
                if not raw_code.strip():
                    continue
                obj = CodeChunk(id=chunk['id'], raw_code=raw_code)
                bulk.append(obj)

            if bulk:
                CodeChunk.objects.bulk_update(bulk, ['raw_code'], batch_size=500)
                updated += len(bulk)

        self.stdout.write(
            self.style.SUCCESS(
                f'Done. Updated: {updated} | Skipped (file not in clone): {skipped_no_file}'
            )
        )
        logger.info(
            'backfill_raw_code_complete',
            updated=updated,
            skipped=skipped_no_file,
            repo_id=repo_id or 'all',
        )
