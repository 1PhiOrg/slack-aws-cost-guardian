# Contributing from a Fork

This guide documents the workflow for contributing changes from this fork back to the upstream repository.

## Repository Relationship

```
┌─────────────────────────────────────┐
│  upstream (original repo)           │
│  github.com/danjamk/slack-aws-...   │
└──────────────────┬──────────────────┘
                   │ fork
                   ▼
┌─────────────────────────────────────┐
│  origin (your fork)                 │
│  github.com/1PhiOrg/slack-aws-...   │
└─────────────────────────────────────┘
```

- **origin**: Your fork where you develop and deploy from
- **upstream**: The original repository you contribute back to

## Initial Setup (One Time)

### 1. Add the upstream remote

```bash
git remote add upstream git@github.com:danjamk/slack-aws-cost-guardian.git
```

### 2. Verify remotes

```bash
git remote -v
```

Expected output:
```
origin    git@github-1phi:1PhiOrg/slack-aws-cost-guardian.git (fetch)
origin    git@github-1phi:1PhiOrg/slack-aws-cost-guardian.git (push)
upstream  git@github.com:danjamk/slack-aws-cost-guardian.git (fetch)
upstream  git@github.com:danjamk/slack-aws-cost-guardian.git (push)
```

## Contributing a Bug Fix or Feature

### 1. Ensure you're on main and up to date

```bash
git checkout main
git fetch upstream
git status  # Check for uncommitted changes
```

### 2. Create a feature branch

Use a descriptive branch name with a prefix:
- `fix/` - Bug fixes
- `feat/` - New features
- `docs/` - Documentation changes
- `refactor/` - Code refactoring

```bash
git checkout -b fix/descriptive-name
```

### 3. Make your changes

Edit the files needed for the fix. Keep changes focused on a single issue.

### 4. Stage only the files for contribution

Be selective - don't include fork-specific config changes:

```bash
# Stage specific files
git add src/path/to/file.py

# Or interactively select changes
git add -p
```

**Do NOT stage these fork-specific files:**
- `config/config.yaml` (org-specific settings)
- `config/guardian-context.md` (org-specific context)
- `.envrc` (local AWS profile)
- `.env` (secrets)

### 5. Commit with a descriptive message

Follow conventional commit format:

```bash
git commit -m "fix: short description of the fix

Longer explanation of what was wrong and how this fixes it.
Include context that helps reviewers understand the change.

Fixes #123 (if there's a related issue)"
```

### 6. Push the branch to your fork

```bash
git push origin fix/descriptive-name
```

### 7. Create a Pull Request

1. Go to GitHub: `https://github.com/1PhiOrg/slack-aws-cost-guardian`
2. You'll see a prompt to create a PR for your recently pushed branch
3. Click **"Compare & pull request"**
4. Set the PR target:
   - **base repository**: `danjamk/slack-aws-cost-guardian`
   - **base**: `main`
   - **head repository**: `1PhiOrg/slack-aws-cost-guardian`
   - **compare**: `fix/descriptive-name`
5. Fill in the PR description with:
   - Summary of the change
   - Why it's needed
   - How to test it
6. Check **"Allow edits from maintainers"** (optional, lets maintainer make small tweaks)
7. Click **"Create pull request"**

## After PR is Merged

### Sync your fork with upstream

```bash
git checkout main
git fetch upstream
git merge upstream/main
git push origin main
```

### Clean up the feature branch

```bash
# Delete local branch
git branch -d fix/descriptive-name

# Delete remote branch
git push origin --delete fix/descriptive-name
```

## Managing Two Tracks of Changes

Your fork has two types of changes:

| Type | Examples | Where it lives |
|------|----------|----------------|
| **Fork-specific** | `config/config.yaml`, `config/guardian-context.md`, `.envrc` | `main` branch on fork only |
| **Contributions** | Bug fixes, features, docs | Feature branches → PRs to upstream |

### Keep them separate

1. **Fork-specific changes**: Commit directly to `main` on your fork
2. **Contributions**: Always use feature branches, never commit directly to `main`

### Handling conflicts

If upstream changes conflict with your fork-specific files:

```bash
git fetch upstream
git merge upstream/main

# If there are conflicts in config files, keep your version:
git checkout --ours config/config.yaml
git checkout --ours config/guardian-context.md
git add config/
git commit -m "merge: keep fork-specific config during upstream sync"
```

## Quick Reference

```bash
# Setup (one time)
git remote add upstream git@github.com:danjamk/slack-aws-cost-guardian.git

# Start a contribution
git checkout main
git fetch upstream
git checkout -b fix/my-fix

# Commit and push
git add src/specific/file.py
git commit -m "fix: description"
git push origin fix/my-fix
# Then create PR on GitHub

# After PR merged, sync fork
git checkout main
git fetch upstream
git merge upstream/main
git push origin main
git branch -d fix/my-fix
```

## Troubleshooting

### "Permission denied" when pushing to upstream

You should push to `origin` (your fork), not `upstream`. PRs handle the contribution to upstream.

### Accidentally committed fork-specific changes to a feature branch

```bash
# Undo the last commit but keep changes staged
git reset --soft HEAD~1

# Unstage the fork-specific files
git reset HEAD config/config.yaml config/guardian-context.md

# Re-commit without them
git commit -m "fix: description"
```

### Feature branch is behind upstream/main

```bash
git checkout fix/my-fix
git fetch upstream
git rebase upstream/main
git push origin fix/my-fix --force-with-lease
```