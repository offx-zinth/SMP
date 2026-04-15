from __future__ import annotations

import docker

from smp.logging import get_logger

log = get_logger(__name__)


class DockerSandbox:
    def __init__(self) -> None:
        self._client = docker.from_env()
        self._container: docker.models.containers.Container | None = None
        self._network: docker.models.networks.Network | None = None

    def spawn(self, name: str, image: str, services: list[str]) -> str:
        self._network = self._client.networks.create(
            name=f"{name}_net",
            internal=True,
        )

        self._container = self._client.containers.run(
            image=image,
            name=name,
            detach=True,
            network=self._network.name,
            volumes={
                f"{name}_cow": {"bind": "/data", "mode": "rw"},
            },
            labels={"smp_sandbox": "true"},
        )

        log.info("docker_sandbox_spawned", container_id=str(self._container.id), name=name)
        return str(self._container.id)

    def execute(self, command: str, timeout: int) -> str:
        if not self._container:
            log.error("docker_sandbox_execute_failed", reason="no_container")
            raise RuntimeError("No container spawned")

        exit_code, output = self._container.exec_run(command, timeout=timeout)

        if exit_code != 0:
            log.warn("docker_sandbox_exec_nonzero", exit_code=exit_code, command=command)

        return str(output.decode("utf-8"))

    def destroy(self) -> None:
        if self._container:
            self._container.remove(force=True)
            log.info("docker_sandbox_container_removed", container_id=self._container.id)
            self._container = None

        if self._network:
            self._network.remove()
            log.info("docker_sandbox_network_removed", network_id=self._network.id)
            self._network = None
