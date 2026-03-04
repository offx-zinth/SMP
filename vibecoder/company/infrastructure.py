from __future__ import annotations

import atexit
import hashlib
import io
import logging
import tarfile
import threading
from collections.abc import Mapping

import docker
from docker.errors import BuildError, DockerException, NotFound
from docker.models.containers import Container
from docker.models.images import Image

logger = logging.getLogger(__name__)


class PersistentSandbox:
    """Build once, run one long-lived container, execute commands via exec_run."""

    def __init__(self, *, project_name: str = "vibecoder", tag_prefix: str = "vibecoder/autogen") -> None:
        self._project_name = project_name
        self._tag_prefix = tag_prefix
        self._client = docker.from_env()
        self._container: Container | None = None
        self._image: Image | None = None
        self._lock = threading.Lock()
        atexit.register(self.shutdown)

    def build_image_once(self, dockerfile_content: str) -> str:
        if not dockerfile_content.strip():
            raise ValueError("dockerfile_content cannot be empty")

        content_hash = hashlib.sha256(dockerfile_content.encode("utf-8")).hexdigest()[:12]
        tag = f"{self._tag_prefix}:{self._project_name}-{content_hash}"
        try:
            self._image = self._client.images.get(tag)
            return tag
        except NotFound:
            pass

        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tf:
            dockerfile_bytes = dockerfile_content.encode("utf-8")
            info = tarfile.TarInfo(name="Dockerfile")
            info.size = len(dockerfile_bytes)
            tf.addfile(info, io.BytesIO(dockerfile_bytes))
        tar_stream.seek(0)

        try:
            self._image, logs = self._client.images.build(fileobj=tar_stream, custom_context=True, tag=tag, rm=True)
            for chunk in logs:
                stream = chunk.get("stream")
                if stream:
                    logger.debug("docker-build: %s", stream.rstrip())
            return tag
        except BuildError as exc:
            logger.exception("Docker image build failed")
            raise RuntimeError(f"Image build failed: {exc}") from exc

    def start(self, image: str, *, working_dir: str = "/workspace", env: Mapping[str, str] | None = None) -> str:
        with self._lock:
            if self._container is not None:
                self._container.reload()
                if self._container.status == "running":
                    return self._container.id
                self.shutdown()
            try:
                self._container = self._client.containers.run(
                    image=image,
                    command=["sleep", "infinity"],
                    working_dir=working_dir,
                    detach=True,
                    tty=True,
                    environment=dict(env or {}),
                    auto_remove=False,
                )
            except DockerException as exc:
                raise RuntimeError(f"Unable to start persistent sandbox: {exc}") from exc
            return self._container.id

    def exec(self, command: str, *, workdir: str = "/workspace", timeout: int = 120) -> str:
        with self._lock:
            if self._container is None:
                raise RuntimeError("Sandbox container is not running.")
            self._container.reload()
            if self._container.status != "running":
                raise RuntimeError("Sandbox container is not running.")
            result = self._container.exec_run(
                ["/bin/sh", "-lc", command],
                workdir=workdir,
                stdout=True,
                stderr=True,
                demux=False,
                tty=False,
                stream=False,
                socket=False,
                environment=None,
                privileged=False,
                user="",
            )
        output = result.output.decode("utf-8", errors="replace") if isinstance(result.output, (bytes, bytearray)) else str(result.output)
        if result.exit_code != 0:
            raise RuntimeError(f"Sandbox command failed (exit {result.exit_code}): {output}")
        return output

    def shutdown(self) -> None:
        with self._lock:
            container = self._container
            self._container = None
        if container is None:
            return
        try:
            container.kill()
        except DockerException:
            logger.debug("Ignoring container kill failure", exc_info=True)
        try:
            container.remove(force=True)
        except DockerException:
            logger.debug("Ignoring container remove failure", exc_info=True)

    def __del__(self) -> None:
        try:
            self.shutdown()
        except Exception:
            logger.debug("Ignoring sandbox destructor failure", exc_info=True)


DockerOrchestrator = PersistentSandbox
