#!/usr/bin/env bash
#
# Verify that every third-party Action used by the workflows is pinned to an
# immutable commit SHA, comes from an owner we trust, and carries a version
# comment that really does name the release that SHA was cut from.
#
#   ./scripts/check-action-pins.sh              # every check
#   ./scripts/check-action-pins.sh --offline    # skip the upstream tag lookups
#
# A git tag is a movable label, so `uses: actions/checkout@v7` runs whichever
# commit that label points at when the job starts, and the owner of the action
# can repoint it at any time. Pinning to a SHA fixes the code, but it also
# makes the reference unreadable to a human, and that is the weakness this
# guards. A pull request can swap the hash for one taken from an attacker's
# fork while leaving the reassuring `# v7.0.1` comment untouched, and the diff
# then looks exactly like a routine Dependabot bump. Forks share object storage
# with their parent, so such a commit is even reachable under the real
# repository's URL. Only resolving the tag tells the two apart.
#
# Version comments must name exact patch releases, never major tags. A major
# tag such as v7 moves with every release, so checking against it would turn CI
# red the moment upstream ships v7.0.2, for a pin that is still perfectly good.
# Patch tags never move, so this check stays quiet until something is wrong.

set -euo pipefail

cd "$(dirname "$0")/.."

# Only actions published by these owners may appear in a workflow. This is the
# check that carries the most weight: a SHA matching its own tag says nothing
# about whether the action belongs here at all, because `evil/action@<sha>
# # v1` verifies perfectly well against evil's own v1 tag.
#
# Each owner here is a deliberate decision, so adding one belongs in a pull
# request of its own rather than alongside the action that wanted it:
#
#   actions      GitHub's own checkout / setup-python / {up,down}load-artifact
#   astral-sh    setup-uv, the installer for the tool that drives every CI step
#   docker       buildx, login, metadata and build-push, for the published image
#   dorny        paths-filter, which decides whether the Docker jobs run at all
#   peter-evans  dockerhub-description, which syncs README.md to the Hub overview
#   pypa         gh-action-pypi-publish, the Trusted Publishing uploader
ALLOWED_OWNERS="actions astral-sh docker dorny peter-evans pypa"

offline=false
case "${1:-}" in
    --offline) offline=true ;;
    "") ;;
    *) echo "usage: $0 [--offline]" >&2; exit 2 ;;
esac

# Resolve a tag to the commit it names, following annotated tags through to
# their target. git ls-remote needs no token and is not rate limited, unlike
# the REST API, which matters because hosted runners share outbound addresses.
#
# Three outcomes have to stay distinguishable. A tag that resolves prints its
# SHA. A tag that does not exist prints nothing and returns 0, because
# ls-remote reports a missing ref as success. A lookup that could not be made
# at all, from a network failure or a repository that is not there, returns
# non-zero and writes the reason to stderr. Collapsing the last two would let
# an unreachable network read as a verified pin, and swallowing the error under
# set -e would kill the run with no file or line to point at.
resolve_tag() {
    out=$(git ls-remote "https://github.com/$1" "refs/tags/$2" "refs/tags/$2^{}" 2>&1) || {
        status=$?
        printf 'git ls-remote exit %s: %s\n' "$status" "$(printf '%s' "$out" | tr '\n' ' ')" >&2
        return "$status"
    }
    printf '%s\n' "$out" |
        awk '{ sha[$2] = $1 }
             END { print (("refs/tags/'"$2"'^{}") in sha) \
                          ? sha["refs/tags/'"$2"'^{}"] \
                          : sha["refs/tags/'"$2"'"] }'
}

failures=0
checked=0

fail() {
    echo "::error file=$1,line=$2::$3"
    echo "  $1:$2: $3" >&2
    failures=$((failures + 1))
}

# Every `uses:` line in every workflow, carrying its file and line number so a
# failure points straight at the offending reference.
while IFS=: read -r file line body; do
    # `uses: owner/repo@ref  # comment`, with the step's leading "- " optional.
    spec=$(printf '%s\n' "$body" | sed -E 's/^[[:space:]]*(-[[:space:]]+)?uses:[[:space:]]*//; s/[[:space:]]*#.*$//; s/[[:space:]]*$//')
    comment=$(printf '%s\n' "$body" | sed -nE 's/.*#[[:space:]]*(v[0-9][^[:space:]]*).*/\1/p')

    # Actions living in this repository are covered by our own review.
    case "$spec" in
        ./*|.\\*) continue ;;
    esac

    checked=$((checked + 1))

    # A container action is third-party executable code exactly as a repository
    # action is, and an image tag such as :latest is every bit as movable as a
    # git tag, so one cannot simply be waved through for having no git ref to
    # resolve. A digest is what pins an image, and anything else is rejected.
    # Note the residual gap: a digest fixes which image runs without saying
    # whether it ought to run here, because there is no registry equivalent of
    # ALLOWED_OWNERS. Adding a container action stays a deliberate act.
    case "$spec" in
        docker://*)
            if ! printf '%s\n' "$spec" | grep -qE '^docker://[^@[:space:]]+@sha256:[0-9a-f]{64}$'; then
                fail "$file" "$line" "$spec is a container action that is not pinned by digest; write it as docker://image@sha256:<64 hex digits>"
            fi
            continue
            ;;
    esac

    repo=${spec%%@*}
    ref=${spec#*@}
    owner=${repo%%/*}

    # A subdirectory action such as owner/repo/path@ref still pins the whole
    # repository, so trim the path before resolving anything.
    repo=$(printf '%s\n' "$repo" | cut -d/ -f1,2)

    allowed=false
    for candidate in $ALLOWED_OWNERS; do
        [ "$owner" = "$candidate" ] && allowed=true
    done
    if [ "$allowed" = false ]; then
        fail "$file" "$line" "owner '$owner' is not in ALLOWED_OWNERS ($ALLOWED_OWNERS); add it deliberately in scripts/check-action-pins.sh if this action is meant to run here"
        continue
    fi

    if ! printf '%s\n' "$ref" | grep -qE '^[0-9a-f]{40}$'; then
        fail "$file" "$line" "$repo is pinned to '$ref', which is a movable tag; pin it to the 40-character commit SHA that tag points at"
        continue
    fi

    if [ -z "$comment" ]; then
        fail "$file" "$line" "$repo@${ref:0:8} has no version comment; append '# vX.Y.Z' naming the release this SHA was cut from"
        continue
    fi

    if ! printf '%s\n' "$comment" | grep -qE '^v[0-9]+\.[0-9]+\.[0-9]+$'; then
        fail "$file" "$line" "$repo carries the comment '# $comment'; name an exact patch release such as v7.0.1, because major tags move with every release and would fail this check for a good pin"
        continue
    fi

    [ "$offline" = true ] && continue

    # Folding stderr into the capture keeps the reason in $actual when the
    # lookup fails, and the condition context exempts this from set -e so one
    # unreachable repository cannot mask the findings on every later pin.
    if ! actual=$(resolve_tag "$repo" "$comment" 2>&1); then
        fail "$file" "$line" "could not resolve $repo $comment upstream: $actual"
    elif [ -z "$actual" ]; then
        fail "$file" "$line" "$repo has no tag $comment upstream"
    elif [ "$actual" != "$ref" ]; then
        fail "$file" "$line" "$repo $comment is upstream commit $actual, but the workflow pins $ref"
    fi
done < <(grep -rnE '^[[:space:]]*(-[[:space:]]+)?uses:' .github/workflows)

if [ "$failures" -gt 0 ]; then
    echo >&2
    echo "$failures of $checked action pin(s) failed verification" >&2
    exit 1
fi

echo "all $checked action pin(s) verified$([ "$offline" = true ] && echo " (offline: SHA and comment format only)")"
