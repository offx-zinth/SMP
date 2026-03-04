from __future__ import annotations

import hashlib
import io
import logging
import tarfile
import tempfile
from pathlib import Path

import docker
from docker.errors import BuildError, DockerException
from docker.models.containers import Container
from docker.models.images import Image

logger = logging.getLogger(__name__)


class DockerOrchestrator:
    """DevOps control plane for creating autonomous build sandboxes."""

    def __init__(self, *, project_name: str = "vibecoder", network_prefix: str = "vibecoder") -> None:
        self._project_name = project_name
        self._network_prefix = network_prefix
        self._client = docker.from_env()

    def create_network(self, name: str | None = None, *, driver: str = "bridge") -> str:
        network_name = name or f"{self._network_prefix}-net"
        existing = [net for net in self._client.networks.list(names=[network_name]) if net.name == network_name]
        if existing:
            return existing[0].id
        network = self._client.networks.create(name=network_name, driver=driver, check_duplicate=True)
        logger.info("Created docker network %s", network_name)
        return network.id

    def build_image(self, dockerfile_content: str, *, tag_prefix: str = "vibecoder/autogen") -> Image:
        if not dockerfile_content.strip():
            raise ValueError("dockerfile_content cannot be empty")

        content_hash = hashlib.sha256(dockerfile_content.encode("utf-8")).hexdigest()[:12]
        tag = f"{tag_prefix}:{self._project_name}-{content_hash}"

        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tf:
            dockerfile_bytes = dockerfile_content.encode("utf-8")
            info = tarfile.TarInfo(name="Dockerfile")
            info.size = len(dockerfile_bytes)
            tf.addfile(info, io.BytesIO(dockerfile_bytes))
        tar_stream.seek(0)

        try:
            image, logs = self._client.images.build(fileobj=tar_stream, custom_context=True, tag=tag, rm=True)
            for chunk in logs:
                stream = chunk.get("stream")
                if stream:
                    logger.debug("docker-build: %s", stream.rstrip())
            return image
        except BuildError as exc:
            logger.exception("Docker image build failed")
            raise RuntimeError(f"Image build failed: {exc}") from exc

    def run_container(
        self,
        image: str,
        command: str | list[str],
        *,
        network: str | None = None,
        working_dir: str = "/workspace",
        detach: bool = False,
    ) -> str:
        try:
            container: Container = self._client.containers.run(
                image=image,
                command=command,
                network=network,
                working_dir=working_dir,
                tty=detach,
                detach=detach,
                remove=not detach,
            )
        except DockerException as exc:
            raise RuntimeError(f"Unable to run container from image={image}: {exc}") from exc

        if detach:
            return container.id

        if isinstance(container, (bytes, bytearray)):
            return container.decode("utf-8", errors="replace")
        return str(container)

    def write_temp_dockerfile(self, dockerfile_content: str) -> Path:
        """Helper used by agents for auditability and troubleshooting."""
        with tempfile.NamedTemporaryFile("w", prefix="vibecoder-", suffix=".Dockerfile", delete=False) as handle:
            handle.write(dockerfile_content)
            return Path(handle.name)
