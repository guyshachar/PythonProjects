#!/bin/bash
# ScoutCut deploy script
#
# Builds the single Docker image used by both scoutcut-api and worker,
# then pushes to Docker Hub and AWS ECR.
#
# Usage:
#   ./deploy.sh                          # build + push (patch bump optional)
#   ./deploy.sh bump                     # bump patch, then build + push
#   ./deploy.sh bump minor               # bump minor, then build + push
#   ./deploy.sh bump major               # bump major, then build + push
#   SKIP_ECR=1 ./deploy.sh               # Docker Hub only, skip ECR
#   SKIP_DOCKERHUB=1 ./deploy.sh         # ECR only, skip Docker Hub
#   SCOUTCUT_PLATFORM=linux/arm64 ./deploy.sh   # override build platform
#
# Environment overrides:
#   VERSION                  explicit version tag
#   SCOUTCUT_PLATFORM        buildx platform   (default: linux/amd64 for EC2)
#   SCOUTCUT_DOCKERHUB_REPO  Docker Hub repo   (default: guyshacharacc/scoutcut)
#   SCOUTCUT_ECR_REPOSITORY  ECR repo path     (default: refereex-repo/scoutcut)
#   AWS_REGION               AWS region        (default: from aws configure)
#   SKIP_ECR=1               skip ECR push
#   SKIP_DOCKERHUB=1         skip Docker Hub push

set -euo pipefail

print_status() { echo "[***] $*"; }

# ── Version ───────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION_FILE="${SCRIPT_DIR}/VERSION"

if [ -n "${VERSION:-}" ]; then
  print_status "Using VERSION from env: $VERSION"
elif [ -f "$VERSION_FILE" ]; then
  VERSION=$(cat "$VERSION_FILE" | tr -d '[:space:]')
  print_status "Using VERSION from file: $VERSION"
else
  VERSION="1.0.0"
  print_status "Using default VERSION: $VERSION"
fi

bump_version() {
  local v="$1" bump_type="${2:-patch}"
  local major minor patch
  IFS='.' read -r major minor patch <<< "$v"
  major=${major:-1}; minor=${minor:-0}; patch=${patch:-0}
  case "$bump_type" in
    major) major=$((major + 1)); minor=0; patch=0 ;;
    minor) minor=$((minor + 1)); patch=0 ;;
    *)     patch=$((patch + 1)) ;;
  esac
  echo "${major}.${minor}.${patch}"
}

# Consume optional "bump [type]" args
if [ "${1:-}" = "bump" ]; then
  BUMP_TYPE="${2:-patch}"
  OLD="$VERSION"
  VERSION=$(bump_version "$VERSION" "$BUMP_TYPE")
  echo "$VERSION" > "$VERSION_FILE"
  print_status "Bumped ($BUMP_TYPE): $OLD → $VERSION"
  shift 1
  [[ "${1:-}" =~ ^(major|minor|patch)$ ]] && shift 1 || true
fi

if [[ "${1:-}" =~ ^(-h|--help|help)$ ]]; then
  sed -n '2,25p' "${BASH_SOURCE[0]}"   # print the header comment as usage
  exit 0
fi

# ── Config ────────────────────────────────────────────────────────────────────
# EC2 is x86_64; override with SCOUTCUT_PLATFORM=linux/arm64 for ARM hosts
PLATFORM="${SCOUTCUT_PLATFORM:-linux/amd64}"
DOCKERHUB_REPO="${SCOUTCUT_DOCKERHUB_REPO:-guyshacharacc/scoutcut}"
ECR_REPOSITORY="${SCOUTCUT_ECR_REPOSITORY:-refereex-repo/scoutcut}"
LOCAL_IMAGE="scoutcut"

print_status "Start $(date +%Y-%m-%d_%H:%M:%S)"
print_status "Version: $VERSION  |  Platform: $PLATFORM"

# ── Build ─────────────────────────────────────────────────────────────────────
print_status "Building ${LOCAL_IMAGE}:${VERSION} (${PLATFORM})..."
cd "$SCRIPT_DIR"
docker buildx build \
  --platform "$PLATFORM" \
  --pull \
  --rm \
  -f Dockerfile \
  --build-arg "VERSION=${VERSION}" \
  -t "${LOCAL_IMAGE}:${VERSION}" \
  -t "${LOCAL_IMAGE}:latest" \
  --load \
  .
print_status "Build done — ${LOCAL_IMAGE}:${VERSION}"

# ── Push to Docker Hub ────────────────────────────────────────────────────────
push_dockerhub() {
  if [ -n "${SKIP_DOCKERHUB:-}" ]; then
    print_status "Skipping Docker Hub (SKIP_DOCKERHUB is set)"
    return 0
  fi
  print_status "Pushing to Docker Hub (${DOCKERHUB_REPO})..."
  docker tag "${LOCAL_IMAGE}:${VERSION}" "${DOCKERHUB_REPO}:${VERSION}"
  docker tag "${LOCAL_IMAGE}:latest"     "${DOCKERHUB_REPO}:latest"
  docker push "${DOCKERHUB_REPO}:${VERSION}"
  docker push "${DOCKERHUB_REPO}:latest"
  print_status "Docker Hub done — ${DOCKERHUB_REPO}:${VERSION} and :latest"
}

# ── Push to AWS ECR ───────────────────────────────────────────────────────────
push_ecr() {
  if [ -n "${SKIP_ECR:-}" ]; then
    print_status "Skipping ECR (SKIP_ECR is set)"
    return 0
  fi
  command -v aws >/dev/null 2>&1 || {
    print_status "ERROR: aws CLI not found — install it or set SKIP_ECR=1"
    return 1
  }
  local reg="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
  [ -z "$reg" ] && reg="$(aws configure get region 2>/dev/null || true)"
  reg="${reg:-us-east-1}"

  local account_id
  account_id="$(aws sts get-caller-identity --query Account --output text)" || {
    print_status "ERROR: aws sts get-caller-identity failed — check AWS credentials"
    return 1
  }

  local ecr_registry="${account_id}.dkr.ecr.${reg}.amazonaws.com"
  local ecr_uri="${ecr_registry}/${ECR_REPOSITORY}"

  print_status "ECR login ${ecr_registry} (region ${reg})"
  aws ecr get-login-password --region "${reg}" \
    | docker login --username AWS --password-stdin "${ecr_registry}" || {
    print_status "ERROR: docker login to ECR failed"
    return 1
  }

  # Ensure the repository exists (no-op if it already does)
  aws ecr describe-repositories --repository-names "${ECR_REPOSITORY}" \
      --region "${reg}" >/dev/null 2>&1 \
    || aws ecr create-repository --repository-name "${ECR_REPOSITORY}" \
         --region "${reg}" >/dev/null \
    && print_status "ECR repository ensured: ${ECR_REPOSITORY}"

  docker tag "${LOCAL_IMAGE}:${VERSION}" "${ecr_uri}:${VERSION}"
  docker tag "${LOCAL_IMAGE}:latest"     "${ecr_uri}:latest"
  docker push "${ecr_uri}:${VERSION}"
  docker push "${ecr_uri}:latest"
  print_status "ECR done — ${ecr_uri}:${VERSION} and :latest"
}

# ── Git tag ───────────────────────────────────────────────────────────────────
create_git_tag() {
  cd "$SCRIPT_DIR" || return
  git rev-parse --git-dir >/dev/null 2>&1 || { print_status "Not a git repo; skipping tag"; return; }
  local tag="v${VERSION}"
  if git rev-parse --verify --quiet "refs/tags/${tag}" >/dev/null 2>&1; then
    print_status "Git tag ${tag} already exists; skipping"
    return
  fi
  git tag -a "${tag}" -m "scoutcut deploy ${VERSION}"
  print_status "Created git tag ${tag}"
  if git remote get-url origin >/dev/null 2>&1; then
    git push origin "${tag}" \
      && print_status "Pushed ${tag} to origin" \
      || print_status "Warning: could not push ${tag}; run: git push origin ${tag}"
  fi
}

# ── Run ───────────────────────────────────────────────────────────────────────
push_dockerhub
push_ecr
create_git_tag

print_status "Done $(date +%Y-%m-%d_%H:%M:%S) — scoutcut $VERSION"
