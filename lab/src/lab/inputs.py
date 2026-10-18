"""Precogly's code and images, for the jobs that scan them.

Most jobs need only the running instance's URL. Some need Precogly itself:
Semgrep scans the source, Trivy scans the Docker images, and the harness runs
inside the backend image. A job asks for these by name in `inputs`, and this
module produces them at the commit the instance runs: a checkout, and the
backend and frontend images, also saved as tar files. Each is built once per
commit and reused by later runs of the same commit.
"""

from __future__ import annotations

from pathlib import Path

from lab.command import CommandRunner, docker, fs, git
from lab.container import built_image_ref
from lab.job import Input

# Built the way Precogly's AWS guide builds them in its compose file: the
# backend from the repository root with backend/Dockerfile, the frontend from
# ./frontend, both at target `prod`.
_IMAGES = (
    ("precogly-backend", Path(), Path("backend/Dockerfile")),
    ("precogly-frontend", Path("frontend"), Path("frontend/Dockerfile")),
)


def prune(runner: CommandRunner, sha: str, root: Path) -> None:
    """Delete every other commit's checkout, images and image files.

    Each deployed commit adds a checkout and a backend and frontend build, about
    0.3 GB of files and more in images, and nothing else removes them. Only the
    commit being run is kept: a run builds everything it needs from the
    instance's commit (docs/design.md, D13), so an older commit's copies are
    used only by a rollback, which rebuilds them. Run directories are kept; they
    are the record of past runs, and small.
    """
    cached = root / "inputs"
    if cached.is_dir():
        for path in sorted(cached.iterdir()):
            if path.name != sha:
                runner.run(fs.remove_tree(path))
    for name, _, _ in _IMAGES:
        repository = built_image_ref(name, sha).rpartition(":")[0]
        listed = runner.run(docker.list_images(repository)).stdout.split()
        stale = [ref for ref in listed if ref != built_image_ref(name, sha)]
        if stale:
            runner.run(docker.remove_images(stale))


def prepare(
    runner: CommandRunner, wanted: frozenset[Input], sha: str, root: Path
) -> dict[Input, Path]:
    """Make each wanted input exist under `root`, skipping what already does.

    Everything is keyed by the full SHA, so a later commit never reuses an
    earlier commit's checkout or images.
    """
    if not wanted:
        return {}
    base = root / "inputs" / sha
    source = base / "precogly-source"
    paths: dict[Input, Path] = {}

    # The images are built from the source, so either input needs it.
    if not (source / ".git").exists():
        runner.run(fs.mkdir(source))
        for command in git.checkout(sha, source):
            runner.run(command)
    if Input.SOURCE in wanted:
        paths[Input.SOURCE] = source

    # A stack runs the backend image, so it needs the images built, not saved.
    if wanted & {Input.IMAGES, Input.STACK}:
        images = base / "precogly-images"
        runner.run(fs.mkdir(images))
        for name, context, dockerfile in _IMAGES:
            ref = built_image_ref(name, sha)
            if not docker.image_exists(runner, ref):
                runner.run(
                    docker.build(
                        source / context,
                        dockerfile=source / dockerfile,
                        target="prod",
                        tag=ref,
                    )
                )
            # Saved for jobs that scan images as files (trivy image --input).
            tar = images / f"{name.removeprefix('precogly-')}.tar"
            if Input.IMAGES in wanted and not tar.exists():
                runner.run(docker.save(ref, tar))
        if Input.IMAGES in wanted:
            paths[Input.IMAGES] = images

    return paths
