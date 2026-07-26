#!/usr/bin/env python3
"""
Generate a CHANGELOG from git history.
Outputs a Keep a Changelog formatted changelog to stdout or to CHANGELOG.md.
Usage:
  python generate_changelog.py [--since TAG] [--output CHANGELOG.md]
"""
import subprocess
import sys
import re
import argparse
from datetime import datetime

def run_git(cmd):
    try:
        return subprocess.check_output(['git'] + cmd, stderr=subprocess.DEVNULL, text=True).strip()
    except subprocess.CalledProcessError:
        return ''

def get_tags():
    tags = run_git(['tag', '--sort=-creatordate']).split('\n')
    return [t for t in tags if t]

def get_commits(since=None):
    if since:
        cmd = ['log', f'{since}..HEAD', '--pretty=format:%h %s', '--no-merges']
    else:
        # get all commits
        cmd = ['log', '--pretty=format:%h %s', '--no-merges']
    output = run_git(cmd)
    if not output:
        return []
    commits = []
    for line in output.split('\n'):
        if not line:
            continue
        # split first space: hash and subject
        parts = line.split(' ', 1)
        if len(parts) == 2:
            commit_hash, subject = parts
            commits.append((commit_hash, subject))
    return commits

def categorize(subject):
    subject_lower = subject.lower()
    if subject_lower.startswith('feat') or 'feature' in subject_lower:
        return 'Added'
    if subject_lower.startswith('fix') or 'bug' in subject_lower:
        return 'Fixed'
    if subject_lower.startswith('docs') or 'doc' in subject_lower:
        return 'Documentation'
    if subject_lower.startswith('style') or 'format' in subject_lower or 'lint' in subject_lower:
        return 'Changed'
    if subject_lower.startswith('refactor'):
        return 'Refactored'
    if subject_lower.startswith('perf') or 'performance' in subject_lower:
        return 'Performance'
    if subject_lower.startswith('test') or 'test' in subject_lower:
        return 'Tests'
    if subject_lower.startswith('chore') or 'build' in subject_lower or 'ci' in subject_lower:
        return 'Other'
    return 'Other'

def generate_changelog(since_tag=None):
    commits = get_commits(since=since_tag)
    if not commits:
        return "# Changelog\n\nAll notable changes to this project will be documented in this file.\n\n## [Unreleased]\n\n### Added\n- No changes yet.\n"
    changes = {}
    for hash_, subj in commits:
        cat = categorize(subj)
        changes.setdefault(cat, []).append(f"- {subj} (`{hash_}`)")
    # Order
    order = ['Added', 'Changed', 'Fixed', 'Deprecated', 'Removed', 'Security', 'Other']
    sections = []
    for cat in order:
        if cat in changes:
            sections.append(f"### {cat}\n" + "\n".join(changes[cat]) + "\n")
    # Add any remaining categories not in order
    for cat in changes:
        if cat not in order:
            sections.append(f"### {cat}\n" + "\n".join(changes[cat]) + "\n")
    # Determine version: if since_tag exists, use that as version; else Unreleased
    version = since_tag if since_tag else "Unreleased"
    date = datetime.now().strftime("%Y-%m-%d")
    header = f"# Changelog\n\nAll notable changes to this project will be documented in this file.\n\n## [{version}] - {date}\n"
    body = "".join(sections)
    return header + body

def main():
    parser = argparse.ArgumentParser(description='Generate CHANGELOG from git history')
    parser.add_argument('--since', help='Tag or commit to start from (exclusive)')
    parser.add_argument('--output', help='Write to file instead of stdout')
    args = parser.parse_args()
    changelog = generate_changelog(since_tag=args.since)
    if args.output:
        with open(args.output, 'w') as f:
            f.write(changelog)
        print(f"Changelog written to {args.output}")
    else:
        print(changelog)

if __name__ == '__main__':
    main()