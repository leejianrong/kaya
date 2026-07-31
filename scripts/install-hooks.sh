#!/usr/bin/env bash
# Install the pre-push gate. Idempotent, and never clobbers a hook it didn't write
# without saying so.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

hook_dir="$(git rev-parse --git-path hooks)"
target="$hook_dir/pre-push"
marker='# kaya-managed hook'

mkdir -p "$hook_dir"

if [ -e "$target" ] && ! grep -q "$marker" "$target" 2>/dev/null; then
  echo "✗ $target already exists and was not written by this script."
  echo "  Move it aside, or add: exec \"\$(git rev-parse --show-toplevel)/scripts/pre-push\""
  exit 1
fi

cat > "$target" <<'EOF'
#!/usr/bin/env bash
# kaya-managed hook — regenerate with `make hooks`. Edit scripts/pre-push instead.
exec "$(git rev-parse --show-toplevel)/scripts/pre-push" "$@"
EOF
chmod +x "$target"

echo "✓ pre-push hook installed at $target"
echo "  It runs the checks in scripts/pre-push. Bypass once with: git push --no-verify"
