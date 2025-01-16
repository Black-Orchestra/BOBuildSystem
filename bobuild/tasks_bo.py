import asyncio
import traceback
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated
from typing import Iterator

import discord
from redis.asyncio import Redis
from taskiq import Context
from taskiq import TaskiqDepends

import bobuild.git
import bobuild.hg
import bobuild.run
import bobuild.workshop
from bobuild.bo_discord import send_webhook
from bobuild.config import DiscordConfig
from bobuild.config import GitConfig
from bobuild.config import MercurialConfig
from bobuild.config import RS2Config
from bobuild.log import logger
from bobuild.tasks import broker
from bobuild.utils import copy_tree
from bobuild.utils import utcnow
from bobuild.workshop import find_map_names
from bobuild.workshop import iter_maps

_repo_dir = Path(__file__).parent.resolve()


def redis_dep(context: Annotated[Context, TaskiqDepends()]) -> Redis:
    return Redis(connection_pool=context.state.redis, decode_responses=True)


def hg_config_dep(_: Annotated[Context, TaskiqDepends()]) -> MercurialConfig:
    return MercurialConfig()


def git_config_dep(_: Annotated[Context, TaskiqDepends()]) -> GitConfig:
    return GitConfig()


def rs2_config_dep(_: Annotated[Context, TaskiqDepends()]) -> RS2Config:
    return RS2Config()


def discord_config_dep(_: Annotated[Context, TaskiqDepends()]) -> DiscordConfig:
    return DiscordConfig()


async def dummy_hash_task() -> tuple[str, str]:
    return "", ""


def log_hash_diffs(hashes: tuple[str, str], name: str):
    if hashes[0] and hashes[1]:
        logger.info("{}: local hash: {}, remote hash: {}",
                    name, hashes[0], hashes[1])


def prepare_map_for_sws(
        publishedfileid: int,
        map_name: str,
        template_img: Path,
        template_vdf: Path,
        staging_dir: Path,
        content_folder: Path,
        git_hash: str,
        hg_pkg_hash: str,
        hg_maps_hash: str,
        changenote: str,
):
    preview_file = staging_dir / f"BOBetaMapImg_{map_name}.png"
    bobuild.workshop.draw_map_preview_file(
        map_name=map_name,
        template_file=template_img,
        output_file=preview_file,
    )

    map_vdf_file = staging_dir / f"{map_name}.vdf"

    bobuild.workshop.write_map_sws_config(
        out_file=map_vdf_file,
        template_file=template_vdf,
        map_name=map_name,
        publishedfileid=publishedfileid,
        content_folder=content_folder,
        preview_file=preview_file,
        git_hash=git_hash,
        hg_pkg_hash=hg_pkg_hash,
        hg_maps_hash=hg_maps_hash,
        changenote=changenote,
    )


@broker.task(
    timeout=10,
    task_name="bobuild.tasks_bo.bo_dummy_task",
)
async def bo_dummy_task():
    logger.info("running dummy task to do nothing")


def git_url(hash_: str) -> str:
    return f"[{hash_}](https://github.com/adriaNsteam/WW2/commit/{hash_})"


def hg_pkgs_url(hash_: str) -> str:
    return f"[{hash_}](https://repo.blackorchestra.net/hg/BO/rev/{hash_})"


def hg_maps_url(hash_: str) -> str:
    return f"[{hash_}](https://repo.blackorchestra.net/hg/BO_maps/rev/{hash_})"


class BuildState(StrEnum):
    SYNCING = "Syncing repos."
    COMPILING = "Compiling scripts."
    BREWING = "Brewing content."
    # PREPARING_UPLOAD = "Preparing Steam Workshop uploads."
    # UPLOADING = "Uploading to Steam Workshop."


@dataclass(slots=True)
class TaskBuildState:
    state: BuildState = BuildState.SYNCING

    @property
    def embed_str(self) -> str:
        strs = []
        for i, bs in enumerate(BuildState):
            if bs == self.state:
                strs.append(f"{i}. **{bs} <---**")
            else:
                strs.append(f"{i}. {bs}")

        return "\n".join(strs)


async def send_build_state_update(
        url: str,
        build_id: str,
        build_state: TaskBuildState,
        fields: list[tuple[str, str, bool]] | None = None,
):
    await send_webhook(
        url=url,
        embed_title="Build state update! :information:",
        embed_color=discord.Color.light_embed(),
        embed_description=f"Build state:\n{build_state.embed_str}",
        embed_footer=build_id,
        embed_fields=fields,
    )


def find_files(path: Path, pattern: str, min_size: int = 100_000) -> Iterator[Path]:
    for file in path.rglob(pattern):
        if file.is_file() and file.stat().st_size >= min_size:
            yield file


# TODO: add custom logger that logs task IDs as extra!

# TODO: we can leave behind long-running garbage processes
#       such as from VNGame.exe brew and make. Do we make sure
#       in each module that they clean up their own processes?
#       Additionally, we need to make sure
# TODO: store PIDs of potentially problematic programs (VNGame.exe)
#       in Redis behind unique keys?
# TODO: return a result from this task?
# TODO: store hashes in metadata so we can retry a failed task for the hashes?
#       For tasks that begin successfully but then fail for some reason halfway?
@broker.task(
    schedule=[{"cron": "*/1 * * * *"}],
    timeout=120 * 60,
    task_name="bobuild.tasks_bo.check_for_updates",
)
async def check_for_updates(
        context: Annotated[Context, TaskiqDepends()],
        hg_config: MercurialConfig = TaskiqDepends(hg_config_dep),
        git_config: GitConfig = TaskiqDepends(git_config_dep),
        rs2_config: RS2Config = TaskiqDepends(rs2_config_dep),
        discord_config: DiscordConfig = TaskiqDepends(discord_config_dep),
) -> None:
    """NOTE: custom middleware and scheduler should ensure this task
    is "unique". Running multiple instances of this task in parallel
    is not supported and can break external dependencies such as
    git and hg repos!

    TODO: split this into more functions.
    TODO: perhaps even use a pipeline?
    """
    started_updating = False
    build_id = f"Build ID {context.message.task_id}"

    git_hash = ""
    hg_pkgs_hash = ""
    hg_maps_hash = ""
    build_state: TaskBuildState

    try:
        logger.info("checking for updates")

        # TODO: get running task status from Postgres?

        # TODO: custom scheduler should handle this!
        # if await update_is_running():
        #     logger.info("skip checking updates, update in-progress flag is already set")
        #     return

        # TODO: Get task ID here, store it in DB and set in-progress state?

        # TODO: do something with this?
        # old_update_timestamp = await set_update_in_progress(True)
        # if old_update_timestamp:
        #     logger.warning(
        #         "old update in-progress flag was set, "
        #         "cleanup was potentially skipped: {}", old_update_timestamp)

        bobuild.hg.ensure_config(hg_config)
        await bobuild.run.ensure_vneditor_modpackages_config(
            rs2_config=rs2_config,
            mod_packages=["WW2"],
        )
        await bobuild.run.ensure_roengine_config(
            rs2_config=rs2_config,
        )

        clone_tasks = []

        # TODO: should cloning be a part of this task? Should we just assume
        #  the build server is already set up properly with the repos in place?

        cloned_git = False
        if not await bobuild.git.repo_exists(git_config.repo_path):
            logger.info("git repo does not exist in '{}', cloning", git_config.repo_path)
            git_config.repo_path.mkdir(parents=True, exist_ok=True)
            clone_tasks.append(bobuild.git.clone_repo(git_config.repo_url, git_config.repo_path))
            cloned_git = True

        cloned_hg_pkgs = False
        if not await bobuild.hg.repo_exists(hg_config.pkg_repo_path):
            logger.info("hg repo does not exist in '{}', cloning", hg_config.pkg_repo_path)
            hg_config.pkg_repo_path.mkdir(parents=True, exist_ok=True)
            clone_tasks.append(bobuild.hg.clone_repo(hg_config.pkg_repo_url, hg_config.pkg_repo_path))
            cloned_hg_pkgs = True

        cloned_hg_maps = False
        if not await bobuild.hg.repo_exists(hg_config.maps_repo_path):
            logger.info("hg repo does not exist in '{}', cloning", hg_config.maps_repo_path)
            hg_config.pkg_repo_path.mkdir(parents=True, exist_ok=True)
            clone_tasks.append(bobuild.hg.clone_repo(hg_config.maps_repo_url, hg_config.maps_repo_path))
            cloned_hg_maps = True

        if clone_tasks:
            logger.info("running {} clone tasks", len(clone_tasks))
            await asyncio.gather(*clone_tasks)

        hg_pkgs_incoming_task = bobuild.hg.incoming(hg_config.pkg_repo_path)
        hg_maps_incoming_task = bobuild.hg.incoming(hg_config.maps_repo_path)
        git_has_update_task = bobuild.git.repo_has_update(git_config.repo_path, git_config.branch)

        # TODO: check here whether hg repos have missing items?
        # TODO: bobuild.hg.has_missing implementation!

        logger.info("running all repo update check tasks")
        hg_pkgs_inc, hg_maps_inc, git_has_update = await asyncio.gather(
            hg_pkgs_incoming_task,
            hg_maps_incoming_task,
            git_has_update_task,
        )

        logger.info("hg packages repo has update available: {}", hg_pkgs_inc)
        logger.info("hg maps repo has update available: {}", hg_maps_inc)
        logger.info("git repo has update available: {}", git_has_update)

        hash_diffs_tasks = []
        sync_tasks = []

        any_sync_task = any((hg_pkgs_inc, hg_maps_inc, git_has_update))

        # We add dummy hash diff tasks here to make sure the number of
        # tasks is always the same for the asyncio.await gather below.
        # TODO: there's a better way to do this, refactor later!
        if hg_pkgs_inc:
            hash_diffs_tasks.append(bobuild.hg.hash_diff(
                hg_config.pkg_repo_path, hg_config.pkg_repo_url))
            sync_tasks.append(bobuild.hg.sync(hg_config.pkg_repo_path))
        elif any_sync_task:
            hash_diffs_tasks.append(dummy_hash_task())

        if hg_maps_inc:
            hash_diffs_tasks.append(bobuild.hg.hash_diff(
                hg_config.maps_repo_path, hg_config.maps_repo_url))
            sync_tasks.append(bobuild.hg.sync(hg_config.maps_repo_path))
        elif any_sync_task:
            hash_diffs_tasks.append(dummy_hash_task())

        if git_has_update:
            hash_diffs_tasks.append(bobuild.git.hash_diff(
                git_config.repo_path, git_config.repo_url))
            sync_tasks.append(bobuild.git.sync_repo(git_config.repo_path, git_config.branch))
        elif any_sync_task:
            hash_diffs_tasks.append(dummy_hash_task())

        hg_pkg_hashes = ("", "")
        hg_maps_hashes = ("", "")
        git_hashes = ("", "")

        if hash_diffs_tasks:
            logger.info("running {} hash diff tasks", len(hash_diffs_tasks))
            hg_pkg_hashes, hg_maps_hashes, git_hashes = await asyncio.gather(*hash_diffs_tasks)
            log_hash_diffs(hg_pkg_hashes, "hg packages repo")
            log_hash_diffs(hg_maps_hashes, "hg maps repo")
            log_hash_diffs(git_hashes, "git repo")
        else:
            logger.info("no hash diff tasks, all up to date")

        if sync_tasks:
            logger.info("running {} repo sync tasks", len(sync_tasks))
            await asyncio.gather(*sync_tasks)
        else:
            logger.info("no repo sync tasks, all up to date")
            if any((cloned_git, cloned_hg_pkgs, cloned_hg_maps)):
                # TODO: do something here? Log?
                pass
            else:
                logger.info("no further work to be done")
                return

        started_updating = True
        start_time = utcnow()
        build_state = TaskBuildState(BuildState.SYNCING)

        # TODO: this is to be able to send cancel webhook.
        # TODO: this is getting kinda spaghetti-ey.
        if getattr(context.broker.state, "ids_", None) is None:
            context.broker.state.ids_ = {}
        context.broker.state.ids_[context.message.task_name] = context.message.task_id

        fields = []
        desc = "Detected changes in the following repos:"

        # TODO: improve handling of these hash tuples!
        if git_hashes[0] and git_hashes[1]:
            fields.append(
                ("Git update",
                 f"{git_url(git_hashes[0])} -> {git_url(git_hashes[1])}", False)
            )
        if hg_pkg_hashes[0] and hg_pkg_hashes[1]:
            fields.append(
                ("HG packages update",
                 f"{hg_pkgs_url(hg_pkg_hashes[0])} -> {hg_pkgs_url(hg_pkg_hashes[1])}", False)
            )
        if hg_maps_hashes[0] and hg_maps_hashes[1]:
            fields.append(
                ("HG maps update",
                 f"{hg_maps_url(hg_maps_hashes[0])} -> {hg_maps_url(hg_maps_hashes[1])}", False)
            )

        await send_webhook(
            url=discord_config.builds_webhook_url,
            embed_title="Build started! :tools:",
            embed_color=discord.Color.light_embed(),
            embed_description=f"{build_state.embed_str}\n\n{desc}",
            embed_footer=build_id,
            embed_fields=fields,
        )

        git_hash = await bobuild.git.get_local_hash(git_config.repo_path)
        hg_pkgs_hash = await bobuild.hg.get_local_hash(hg_config.pkg_repo_path)
        hg_maps_hash = await bobuild.hg.get_local_hash(hg_config.maps_repo_path)

        unpub_pkgs_dir: Path = rs2_config.unpublished_dir / "CookedPC/Packages/WW2"
        unpub_maps_dir: Path = rs2_config.unpublished_dir / "CookedPC/Maps/WW2"
        pub_pkgs_dir: Path = rs2_config.published_dir / "CookedPC/Packages/WW2"
        pub_maps_dir: Path = rs2_config.published_dir / "CookedPC/Maps/WW2"

        # Files from HG repos are only copied to Unpublished if their MD5
        # hash is different. Files in Unpublished that are also not found in
        # HG repos are then removed. Published files that cannot be found in
        # Unpublished are then proceeded to be removed. This should ensure a
        # clean workspace for every build without needing to re-brew everything
        # again every time, assuming no resonance cascades take place.
        logger.info("cleaning up Unpublished content")

        unpub_pkgs_dir.mkdir(parents=True, exist_ok=True)
        unpub_maps_dir.mkdir(parents=True, exist_ok=True)
        pub_pkgs_dir.mkdir(parents=True, exist_ok=True)
        pub_maps_dir.mkdir(parents=True, exist_ok=True)

        # Package names in UE are globally unique, only need to check file names.
        hg_source_upks_names = [file.name for file in find_files(hg_config.pkg_repo_path, "*.upk")]
        hg_source_roes_names = [file.name for file in find_files(hg_config.maps_repo_path, "*.roe")]
        for unpub_pkg in find_files(unpub_pkgs_dir, "*.upk"):
            if unpub_pkg.name not in hg_source_upks_names:
                logger.info("removing package '{}' from Unpublished", unpub_pkg)
                unpub_pkg.unlink(missing_ok=True)
        for unpub_roe in find_files(unpub_maps_dir, "*.roe"):
            if unpub_roe.name not in hg_source_roes_names:
                logger.info("removing map '{}' from Unpublished", unpub_roe)
                unpub_roe.unlink(missing_ok=True)

        copy_tree(hg_config.pkg_repo_path, unpub_pkgs_dir, "*.upk", check_md5=True)

        # TODO: this is done somewhat manually for now.
        # Determine directories for other maps automatically.
        map_to_unpub_dir = {
            "RRTE-Beach_Invasion_Sim": "BeachInvasionSim",
        }

        map_unpub_dirs: dict[str, Path] = {}
        for m in iter_maps(hg_config.maps_repo_path):
            mn = m.stem
            if mn in map_to_unpub_dir:
                map_unpub_dir = unpub_maps_dir / map_to_unpub_dir[mn]
            else:
                map_unpub_dir = unpub_maps_dir / m.parent.name

            map_unpub_dirs[mn] = map_unpub_dir

            logger.info("map '{}': Unpublished dir: '{}'", mn, map_unpub_dir)
            map_unpub_dir.mkdir(parents=True, exist_ok=True)
            copy_tree(m.parent, map_unpub_dir, "*.roe", check_md5=True)

        # TODO: use UE-Library to find references to required sublevels?

        ww2u = rs2_config.unpublished_dir / "CookedPC/WW2.u"
        logger.info("removing '{}'", ww2u)
        ww2u.unlink(missing_ok=True)

        build_state.state = BuildState.COMPILING
        await send_build_state_update(
            url=discord_config.builds_webhook_url,
            build_id=build_id,
            build_state=build_state,
        )
        make_warnings, make_errors = await bobuild.run.vneditor_make(
            rs2_config.rs2_documents_dir,
            rs2_config.vneditor_exe,
        )

        roe_content: list[str] = [
            file.stem for file in
            unpub_maps_dir.rglob("*.roe")
        ]

        upk_content: list[str] = [
            file.name for file in
            unpub_pkgs_dir.rglob("*.upk")
        ]

        logger.info(".roe files to brew: {}", len(roe_content))
        logger.info(".upk files to brew: {}", len(upk_content))

        total_content_to_brew = len(["WW2"]) + len(roe_content) + len(upk_content)
        # TODO: if we list all packages here, we exceed the command line
        #   length limit of VNEditor.exe. It should still brew them even if
        #   we don't list them explicitly?
        # TODO: maybe brew these in batches?
        content_to_brew = ["WW2"] + roe_content
        logger.info("total number of content to brew: {}", total_content_to_brew)

        pub_pkg: Path
        for pub_pkg in pub_pkgs_dir.rglob("*.upk"):
            if pub_pkg.name not in upk_content:
                logger.info("removing '{}' from Published content", pub_pkg)
                pub_pkg.unlink(missing_ok=True)

        pub_map: Path
        for pub_map in pub_maps_dir.rglob("*.roe"):
            if pub_map.stem not in roe_content:
                logger.info("removing '{}' from Published content", pub_map)
                pub_map.unlink(missing_ok=True)

        build_state.state = BuildState.BREWING
        await send_build_state_update(
            url=discord_config.builds_webhook_url,
            build_id=build_id,
            build_state=build_state,
            fields=[
                ("Total .upk files to brew", str(len(upk_content)), False),
                ("Total .roe files to brew", str(len(roe_content)), False),
            ]
        )
        brew_warnings, brew_errors = await bobuild.run.vneditor_brew(
            rs2_config.rs2_documents_dir,
            rs2_config.vneditor_exe,
            content_to_brew,
        )

        ww2u = rs2_config.published_dir / "CookedPC/WW2.u"
        logger.info("patching WW2.u file in: '{}'", ww2u)
        await bobuild.run.patch_shader_cache(
            ww2u,
            "SeekFreeShaderCache",
            "WW2GameInfo.DummyObject",
        )

        ww2u_staging_dir = _repo_dir / "workshop/generated/ww2u_staging/"
        logger.info("preparing main SWS item in '{}'", ww2u_staging_dir)
        ww2u_staging_dir.mkdir(parents=True, exist_ok=True)

        map_names = find_map_names(pub_maps_dir)
        logger.info("found {} maps for workshop uploads", len(map_names))

        fs: list[Future] = []
        with ThreadPoolExecutor() as executor:
            template_img = _repo_dir / "workshop/bo_beta_workshop_map.png"
            template_vdf = _repo_dir / "workshop/BOBetaMapTemplate.vdf"
            for map_name in map_names:
                staging_dir = _repo_dir / "workshop/generated/sws_map_staging/" / map_name
                staging_dir.mkdir(parents=True, exist_ok=True)

                changenote = fr"""
Git commit: {git_hash}.
Mercurial packages commit: {hg_pkgs_hash}.
Mercurial maps commit: {hg_maps_hash}.
                """

                try:
                    publishedfileid = rs2_config.bo_dev_beta_map_ids[map_name]
                except KeyError:
                    logger.warning("no SWS ID for map '{}', skipping", map_name)
                    continue

                try:
                    content_folder = map_unpub_dirs[map_name]
                except KeyError:
                    logger.error("failed to determine contentfolder for map '{}'", map_name)
                    continue

                executor.submit(
                    prepare_map_for_sws,
                    publishedfileid=publishedfileid,
                    map_name=map_name,
                    template_img=template_img,
                    template_vdf=template_vdf,
                    staging_dir=staging_dir,
                    git_hash=git_hash,
                    hg_pkg_hash=hg_pkgs_hash,
                    hg_maps_hash=hg_maps_hash,
                    changenote=changenote,
                    content_folder=content_folder,
                )

        exs: list[str] = []
        for f in fs:
            ex = f.exception()
            if ex:
                logger.error("future {} failed with error: {}: {}", f, type(ex).__name__, ex)
                exs.append(str(ex))
        if exs:
            ex_string = "\n".join(exs)
            raise RuntimeError("failed to render map preview files: {}", ex_string)

        # TODO: it's possible a new map is added to the repo, which is not listed
        #   in map_ids_factory(). Is there a nice way to automate creation of new
        #   workshop items? Probably not? At the very least, this task should post
        #   a notification when such a map is found.

        logger.info("task {} done", context.message)

        # TODO: move duplicated stuff into dedicated webhook funcs?
        success_fields = [
            ("Git commit", git_url(git_hash), False),
            ("HG packages commit", hg_pkgs_url(hg_pkgs_hash), False),
            ("HG maps commit", hg_maps_url(hg_maps_hash), False),
            ("BrewContent warnings", str(len(brew_warnings)), False),
            ("BrewContent errors", str(len(brew_errors)), False),
            ("UScript compilation warnings", str(len(make_warnings)), False),
            ("UScript compilation errors", str(len(make_errors)), False),
        ]

        stop_time = utcnow()
        delta = stop_time - start_time
        success_desc = f"Total duration: {delta}."

        await send_webhook(
            url=discord_config.builds_webhook_url,
            embed_title="Build success! :thumbsup:",
            embed_color=discord.Color.green(),
            embed_footer=build_id,
            embed_description=success_desc,
            embed_fields=success_fields,
        )

    except (Exception, asyncio.CancelledError, KeyboardInterrupt) as e:
        logger.error("error running task: {}: {}: {}",
                     context.message, type(e).__name__, e)

        # Don't report failures for tasks that had no actual work to do!
        if started_updating:
            failure_fields = [
                ("Git commit", git_url(git_hash), False),
                ("HG packages commit", hg_pkgs_url(hg_pkgs_hash), False),
                ("HG maps commit", hg_maps_url(hg_maps_hash), False),
            ]

            desc = (
                "```python-repl\n"
                f"Error: {type(e).__name__}\n"
                f"{traceback.format_exc()}\n"
                "```"
            )

            await send_webhook(
                url=discord_config.builds_webhook_url,
                embed_title="Build failure! :skull:",
                embed_color=discord.Color.red(),
                embed_description=desc,
                embed_footer=build_id,
                embed_fields=failure_fields,
            )

        raise
    finally:
        logger.info("broker.state: {}", context.broker.state)
        if ids := getattr(context.broker.state, "ids_", {}):
            try:
                # TODO: does this run on shutdown?
                logger.info("ids: {}", ids)
                del ids[context.message.task_name]
            except KeyError:
                pass

        if started_updating:
            pass
            # TODO: middleware should handle this:
            #     await set_update_in_progress(False)
