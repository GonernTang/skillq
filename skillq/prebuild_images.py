import argparse
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import tomlkit
import yaml

# Buildkit's parallel `auth.docker.io` oauth fetches overwhelm restricted
# networks (Tailscale/VPN egress, rate-limited NAT). Force the legacy
# builder for stability. Single-threaded buildkit works but is slower.
_LEGACY_BUILDER_ENV = {**os.environ, "DOCKER_BUILDKIT": "0"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cfg-path",
        type=Path,
        default=Path("experiments/configs/prebuild_tb2_claude.yaml"),
    )
    parser.add_argument(
        "--preinstall-dockerfile",
        type=Path,
        default=Path("docker/Dockerfile.claude"),
    )
    return parser.parse_args()


def get_dockerfile_for_agent(agent_name: str) -> Path:
    if "claude" in agent_name.lower():
        return Path("docker/Dockerfile.claude")
    return Path("docker/Dockerfile.claude")


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).parent.parent

    cfg_path = args.cfg_path
    if not cfg_path.is_absolute():
        cfg_path = repo_root / cfg_path
    cfg = yaml.safe_load(cfg_path.read_text())
    max_workers = int(cfg["max_workers"])
    datasets = list(cfg["datasets"])
    agent_versions = {
        str(agent["name"]): str(agent["version"]) for agent in cfg["agents"]
    }
    agent_build_args = []
    for agent_name, agent_version in agent_versions.items():
        build_arg_name = f"{agent_name.replace('-', '_').upper()}_VERSION"
        agent_build_args.extend(["--build-arg", f"{build_arg_name}={agent_version}"])

    if len(agent_versions) == 1:
        dockerfile = get_dockerfile_for_agent(list(agent_versions.keys())[0])
        if (
            args.preinstall_dockerfile == Path("docker/Dockerfile.claude")
            and dockerfile != args.preinstall_dockerfile
        ):
            print(f"Auto-detected Dockerfile: {dockerfile}")
    else:
        dockerfile = args.preinstall_dockerfile

    dependency_versions = {
        str(dependency["name"]): str(dependency["version"])
        for dependency in cfg["dependencies"]
    }

    for dataset_cfg in datasets:
        name = str(dataset_cfg["name"])
        version = str(dataset_cfg.get("version"))
        download_dir = repo_root / Path(dataset_cfg["download_dir"]).expanduser()
        registry_url: str | None = dataset_cfg.get("registry_url")
        registry_path: str | None = dataset_cfg.get("registry_path")
        task_names: list[str] = list(dataset_cfg.get("task_names"))
        exclude_task_names: set[str] = set(dataset_cfg.get("exclude_task_names"))
        image_registry = str(dataset_cfg.get("image_registry"))
        image_tag: str | None = dataset_cfg.get("image_tag")
        resolved_image_tag = image_tag or datetime.now().strftime("%Y%m%d")

        # Skip the harbor datasets download if every requested task already has
        # a local task.toml -- keeps the dev loop fast and avoids the slow
        # registry walk the `download` subcommand does on every invocation.
        if task_names and all(
            (download_dir / task_name / "task.toml").is_file()
            for task_name in task_names
        ):
            print(
                f"Skipping harbor download: {len(task_names)} task(s) already "
                f"present in {download_dir}"
            )
        else:
            dataset_full_name = f"{name}@{version}" if version else name
            download_cmd = [
                "uv",
                "run",
                "harbor",
                "datasets",
                "download",
                dataset_full_name,
                "--cache",
                "-o",
                str(download_dir),
            ]
            if registry_path:
                download_cmd.extend(
                    ["--registry-path", str(Path(registry_path).expanduser())]
                )
            elif registry_url:
                download_cmd.extend(["--registry-url", registry_url])

            subprocess.run(download_cmd, check=True)

        task_tomls = sorted(download_dir.glob("**/task.toml"))
        if task_names:
            task_name_set = set(task_names)
            task_tomls = [p for p in task_tomls if p.parent.name in task_name_set]
        if exclude_task_names:
            task_tomls = [
                p for p in task_tomls if p.parent.name not in exclude_task_names
            ]

        preinstall_tasks = []
        writeback_tasks = []
        for task_toml in task_tomls:
            task_name = task_toml.parent.name
            doc = tomlkit.parse(task_toml.read_text())
            target_image = f"{image_registry}/{task_name}:{resolved_image_tag}"
            writeback_tasks.append((task_toml, target_image))

            image_check = subprocess.run(
                ["docker", "image", "inspect", target_image],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if image_check.returncode == 0:
                print(f"Skipping preinstall: {target_image} already exists")
                continue

            source_image = doc["environment"].get("docker_image")
            source_build_cmd = None
            if source_image:
                source_image = str(source_image)
                source_image_check = subprocess.run(
                    ["docker", "image", "inspect", source_image],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if source_image_check.returncode != 0:
                    print(
                        f"Skipping {target_image}: source image "
                        f"{source_image} not found locally. Import it from "
                        f"the build machine via 'docker save/load' first."
                    )
                    continue
            else:
                source_image = f"local/{task_name}:{resolved_image_tag}"
                source_image_check = subprocess.run(
                    ["docker", "image", "inspect", source_image],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if source_image_check.returncode != 0:
                    # NOTE: --progress=plain is a buildkit-only flag; we drop
                    # it because the legacy builder is forced below.
                    source_build_cmd = [
                        "docker",
                        "build",
                        "-t",
                        source_image,
                        str(task_toml.parent / "environment"),
                    ]

            # Buildkit's parallel `auth.docker.io` oauth fetches overwhelm
            # restricted networks (Tailscale/VPN egress, rate-limited NAT).
            # Force the legacy builder via DOCKER_BUILDKIT=0 for stability.
            # Single-threaded buildkit works but is slower than legacy.
            preinstall_cmd = [
                "docker",
                "build",
                "-f",
                str(repo_root / dockerfile),
                "--build-arg",
                f"BASE_IMAGE={source_image}",
            ]

            if not any("claude" in name.lower() for name in agent_versions):
                preinstall_cmd.extend(
                    [
                        "--build-arg",
                        f"NVM_VERSION={dependency_versions['nvm']}",
                        "--build-arg",
                        f"NODE_VERSION={dependency_versions['node']}",
                    ]
                )

            preinstall_cmd.extend(
                [
                    *agent_build_args,
                    "-t",
                    target_image,
                    str(repo_root / "docker"),
                ]
            )
            preinstall_tasks.append(
                (task_toml, target_image, source_build_cmd, preinstall_cmd)
            )

        if len(preinstall_tasks) == 1 or max_workers <= 1:
            for _, _, source_build_cmd, preinstall_cmd in preinstall_tasks:
                if source_build_cmd:
                    print(f"Running source build: {' '.join(source_build_cmd)}")
                    subprocess.run(
                        source_build_cmd, check=True, env=_LEGACY_BUILDER_ENV
                    )
                print(f"Running preinstall: {' '.join(preinstall_cmd)}")
                subprocess.run(preinstall_cmd, check=True, env=_LEGACY_BUILDER_ENV)
        else:
            for _, _, source_build_cmd, preinstall_cmd in preinstall_tasks:
                if source_build_cmd:
                    print(f"Running source build: {' '.join(source_build_cmd)}")
                print(f"Running preinstall: {' '.join(preinstall_cmd)}")
            with ThreadPoolExecutor(max_workers=max_workers) as pool:

                def _run_with_log(item):
                    try:
                        if item[2]:
                            subprocess.run(item[2], check=True, env=_LEGACY_BUILDER_ENV)
                        subprocess.run(item[3], check=True, env=_LEGACY_BUILDER_ENV)
                    except subprocess.CalledProcessError as e:
                        stderr_tail = (
                            e.stderr.decode(errors="replace") if e.stderr else ""
                        )
                        print(
                            f"BUILD FAILED for {item[0]}: exit {e.returncode}\n"
                            f"  cmd: {' '.join(e.cmd[:6])}\n"
                            f"  stderr (tail): {stderr_tail[-500:]}"
                        )
                        return False
                    return True

                results = list(pool.map(_run_with_log, preinstall_tasks))
                n_failed = sum(1 for r in results if r is False)
                if n_failed:
                    print(
                        f"WARNING: {n_failed}/{len(preinstall_tasks)} preinstall builds failed; will need to be retried."
                    )

        for task_toml, target_image in writeback_tasks:
            doc = tomlkit.parse(task_toml.read_text())
            doc["environment"]["docker_image"] = target_image
            task_toml.write_text(tomlkit.dumps(doc))


if __name__ == "__main__":
    main()
