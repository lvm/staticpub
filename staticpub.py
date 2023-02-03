#!/usr/bin/env python3
"""
A Static ActivityPub generator
"""

import argparse
import datetime
import json
import shutil
from configparser import ConfigParser, ExtendedInterpolation
from os.path import curdir
from pathlib import Path
from typing import Dict, Generator, List, NoReturn, TypeAlias, cast

GenericObjectTypeValues: TypeAlias = (
    List[str | Dict] | Dict | str | bool | None
)
GenericObjectType: TypeAlias = Dict[str, GenericObjectTypeValues]


# Helpers
def now() -> str:
    "Returns _now_ date in ActivityStreams2 format"
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")


def str_to_datetime(date_str: str) -> datetime.datetime:
    "Converts now() to datetime"
    return datetime.datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")


def get_config(cur_dir: Path, instance_config_file: str) -> ConfigParser:
    "reads Instance config"
    cfg = ConfigParser(interpolation=ExtendedInterpolation())
    cfg.read(str(cur_dir / instance_config_file))
    cfg.read_dict({"Paths": {"curdir": str(cur_dir.absolute())}})

    return cfg


def remove_newlines_strip(line: str) -> str:
    "Removes newlines and spaces"
    return line.replace("\n", "").strip()


def mkdir(path: Path) -> None:
    "Make dir"
    path.mkdir(parents=True, exist_ok=True)


def copy(orig: Path, dest: Path) -> None:
    "Copy files"
    assert orig.is_file()
    shutil.copy(str(orig.absolute()), str(dest.absolute()))


def media_mimetype(filename: str) -> str:
    "Simple mimetype guesser from file extension"
    _, ext = filename.rsplit(".", 1)
    if ext == "png":
        return "image/png"
    return "image/jpeg"


# ActivityPub funcs
def parse_notes(
    config: ConfigParser, /, pseudo_note_filename: str, pseudo_note: List[str]
) -> NoReturn | GenericObjectType:
    """
    Receives a filename + "pseudo note" and returns an Activity Object
    * It will fail if the header is badly formatted
    Expected:
    ---
    key: value
    ...
    ---
    this is content
    """
    try:
        headers_begin, headers_end = [
            index for index, line in enumerate(pseudo_note)
            if line.startswith("---")
        ]
    except ValueError as e:
        print(
            f"[!] Badly formatted headers: {pseudo_note_filename!r} -> {e}"
        )
        raise

    filename: str = pseudo_note_filename
    note_id, _ = filename.rsplit(".", 1)
    domain = config["Instance"].get("domain")
    object_note: GenericObjectType = {
        "@context": [
            "https://www.w3.org/ns/activitystreams",
            {"filename": {"@id": "http://schema.org/url", "@type": "@id"}},
        ],
        "id": f"{domain}/posts/{note_id}",
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "sensitive": False,
        "filename": pseudo_note_filename,
    }
    object_note.update(
        dict(
            [
                (key.strip(), value.strip())
                for key, value in [
                    remove_newlines_strip(key_value).split(": ")  # no-qa
                    for key_value in pseudo_note[headers_begin + 1:headers_end]
                ]
            ]
        )
    )
    object_note.update({"content": "".join(pseudo_note[headers_end + 1:])})

    if "published" not in list(object_note.keys()):
        object_note.update({"published": now()})

    return object_note


def generate_notes(
    config: ConfigParser,
    path: Path
) -> Generator[GenericObjectType, None, None]:
    "Walks the 'entry' directory and parses the 'pseudo notes'"
    pseudo_notes: Generator[Path, None, None] = path.glob("**/*")
    for pseudo_note in pseudo_notes:
        if pseudo_note.is_file() and pseudo_note.name != ".gitkeep":
            yield parse_notes(
                config,
                pseudo_note_filename=pseudo_note.name,
                pseudo_note=pseudo_note.open("r").readlines()
            )


def generate_create_activity(
    config: ConfigParser, /, note: GenericObjectType
) -> GenericObjectType:
    "Creates 'Create' Activity Type based on the 'Note' types"
    assert note.get("@context", None), "Note has no context?"
    del note["@context"]

    filename: str = cast(str, note.get("filename"))
    note_id, _ = filename.rsplit(".", 1)
    actor_id = config["Instance"].get("actor_id")
    domain = config["Instance"].get("domain")
    create_object: GenericObjectType = {
        "id": f"{domain}/posts/{note_id}",
        "type": "Create",
        "actor": actor_id,
        "published": note.get("published", now()),
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "object": note,
    }

    return create_object


# ActivityPub endpoints
def create_actor(config, /, has_featured_note: bool = False) -> None:
    "Creates 'Actor' endpoint"
    preferred_username = config["Actor"].get("preferredUsername")
    actor_id = config["Instance"].get("actor_id")
    domain = config["Instance"].get("domain")
    actor_object = {
        "@context": [
            "https://www.w3.org/ns/activitystreams",
            "https://w3id.org/security/v1"
        ],
        "id": actor_id,
        "type": "Person",
        "following": f"{domain}/following",
        "followers": f"{domain}/followers",
        "inbox": f"{domain}/inbox",
        "outbox": f"{domain}/outbox",
        "preferredUsername": preferred_username,
        "name": config["Actor"].get("name"),
        "summary": config["Actor"].get("summary"),
        "url": config["Instance"].get("domain"),
        "manuallyApprovesFollowers": True,
        "discoverable": config["Actor"].getboolean(
            "discoverable", fallback=True
        ),
        "published": "2023-02-09T00:00:00Z",
    }

    if has_featured_note:
        actor_object.update(
            {
                "featured": f"{domain}/featured",
            }
        )

    instance_files_path = Path(
        config["Paths"].get("instanceFiles")
    )
    banner_path = Path(config["Instance"].get("banner"))
    if banner_path.is_file():
        actor_object.update({
            "image": {
                "type": "Image",
                "mediaType": media_mimetype(banner_path.name),
                "url": f"{domain}/{banner_path.name}"
            }
        })
        copy(banner_path, instance_files_path)

    icon_path = Path(config["Instance"].get("icon"))
    if banner_path.is_file():
        actor_object.update({
            "icon": {
                "type": "Image",
                "mediaType": media_mimetype(icon_path.name),
                "url": f"{domain}/{icon_path.name}"
            }
        })
        copy(icon_path, instance_files_path)

    with (instance_files_path / f"{preferred_username}").open(
        "w", encoding="utf-8"
    ) as actor_fileobj:
        json.dump(actor_object, actor_fileobj, indent=2)


def create_webfinger(config) -> None:
    "Creates 'Webfinger' endpoint"
    host = config["Instance"].get("host")
    preferred_username = config["Actor"].get("preferredUsername")
    webfinger = {
        "subject": f"acct:{preferred_username}@{host}",
        "links": [
            {
                "rel": "self",
                "type": "application/activity+json",
                "href": config["Instance"].get("actor_id"),
            }
        ],
    }

    instance_files_path = Path(
        config["Paths"].get("instanceFiles")
    )
    well_known = instance_files_path / ".well-known"
    with (well_known / "webfinger").open(
        "w", encoding="utf-8"
    ) as webfinger_fileobj:
        json.dump(webfinger, webfinger_fileobj, indent=2)


def create_followers(config) -> None:
    "Creates 'Followers' endpoint"
    domain = config["Instance"].get("domain")
    followers_object = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{domain}/followers",
        "type": "OrderedCollection",
        "totalItems": config["Actor"].get("followers"),
        "first": [],
    }

    instance_files_path = Path(
        config["Paths"].get("instanceFiles")
    )
    with (instance_files_path / "followers").open(
        "w", encoding="utf-8"
    ) as followers_fileobj:
        json.dump(followers_object, followers_fileobj, indent=2)


def create_following(config) -> None:
    "Creates 'Following' endpoint"
    domain = config["Instance"].get("domain")
    following_object = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{domain}/followers",
        "type": "OrderedCollection",
        "totalItems": config["Actor"].get("following"),
        "first": [],
    }

    instance_files_path = Path(
        config["Paths"].get("instanceFiles")
    )
    with (instance_files_path / "following").open(
        "w", encoding="utf-8"
    ) as following_fileobj:
        json.dump(following_object, following_fileobj, indent=2)


def create_outbox(
    config: ConfigParser, /, notes: List[GenericObjectType]
) -> None:
    "Creates 'Outbox' endpoint"
    notes_sorted = sorted(
        notes,
        # We need to cast(str, published) to match str_to_datetime type
        # Also we need str_to_datetime because MyPy expects a key-func value
        # that supports cmp-lt and cmp-gt.
        key=lambda note: str_to_datetime(cast(str, note.get("published"))),
        reverse=True,
    )
    paginate_by = int(config["Outbox"].get("paginate_by", "0"))
    if paginate_by and len(notes_sorted) > paginate_by:
        notes_sorted = notes_sorted[:paginate_by]
    items_collection = [
        generate_create_activity(config, note=note) for note in notes_sorted
    ]

    domain = config["Instance"].get("domain")
    toots = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{domain}/toots",
        "type": "OrderedCollectionPage",
        "prev": f"{domain}/toots",
        "partOf": f"{domain}/toots",
        "totalItems": len(items_collection),
        "orderedItems": items_collection,
    }
    outbox = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{domain}/outbox",
        "type": "OrderedCollection",
        "totalItems": len(items_collection),
        "first": f"{domain}/toots"
    }

    instance_files_path = Path(
        config["Paths"].get("instanceFiles")
    )
    # Toots is used by Mastodon
    with (instance_files_path / "toots").open(
        "w", encoding="utf-8"
    ) as toots_fileobj:
        json.dump(toots, toots_fileobj, indent=2)
    # and Outbox to complain with the Spec
    with (instance_files_path / "outbox").open(
        "w", encoding="utf-8"
    ) as outbox_fileobj:
        json.dump(outbox, outbox_fileobj, indent=2)


def create_posts(
    config: ConfigParser, /,
    notes: List[GenericObjectType],
    featured_note: Path
) -> None:
    "Creates 'Posts' endpoint for each Note"

    instance_files_path = Path(
        config["Paths"].get("instanceFiles")
    )
    posts = instance_files_path / "posts"
    for note in notes:
        filename: str = cast(str, note.get("filename"))
        note_id, _ = filename.rsplit(".", 1)
        with (posts / note_id).open(
            "w", encoding="utf-8"
        ) as note_fileobj:
            json.dump(note, note_fileobj, indent=2)

    # If there's one defined, also the featured endpoint (for Mastodon)
    if featured_note.is_file():
        create_featured(
            config,
            pseudo_featured_note_path=featured_note
        )


def create_featured(config, /, pseudo_featured_note_path: Path) -> None:
    "Creates 'Featured' endpoint"
    domain = config["Instance"].get("domain")
    note_object = parse_notes(
        config,
        pseudo_note_filename=pseudo_featured_note_path.name,
        pseudo_note=pseudo_featured_note_path.open("r").readlines(),
    )
    featured = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{domain}/featured",
        "type": "OrderedCollection",
        "totalItems": 1,
        "orderedItems": [note_object],
    }

    instance_files_path = Path(
        config["Paths"].get("instanceFiles")
    )
    with (instance_files_path / "featured").open(
        "w", encoding="utf-8"
    ) as featured_fileobj:
        json.dump(featured, featured_fileobj, indent=2)


def create_instance_files(config: ConfigParser) -> None:
    "Creates 'Index' endpoint"
    preferred_username = config["Actor"].get("preferredUsername")
    host = config["Instance"].get("host")
    template = f"""<!DOCTYPE html>
<html lang="en">
<head><title>StaticPub Instance</title></head>
<body>
    <p>This is the StaticPub Instance for
    <strong>@{preferred_username}@{host}</strong>.</p>
</body>
</html>"""
    instance_files_path = Path(
        config["Paths"].get("instanceFiles")
    )
    with (instance_files_path / "index.html").open(
        "w", encoding="utf-8"
    ) as index_fileobj:
        index_fileobj.write(template)

    if config["Instance"].getboolean(
        "github_instance",
        fallback=True
    ):
        # if it's a github hosted instance we'll need:
        with (instance_files_path / "CNAME").open(
            "w", encoding="utf-8"
        ) as cname_fileobj:
            cname_fileobj.write(host)
        # and a nojekyll to disable Jekyll sites
        # and allow the Webfinger endpoint
        with (instance_files_path / ".nojekyll").open(
            "w", encoding="utf-8"
        ) as nojekyll_fileobj:
            nojekyll_fileobj.write(".")


def run_staticpub(config: ConfigParser) -> None:
    "Main StaticPub func. Alpha and Omega"
    # dirs and featured
    current_dir_path = Path(config["Paths"].get("curdir"))
    entries_path = current_dir_path / config["Paths"].get("entries")
    featured_note = current_dir_path / config["Instance"].get(
        "featured_note"
    ).strip()
    # First we'll create the dir where we'll store everything
    users_endpoint_path = (
        current_dir_path / config["Paths"].get("instanceFiles")
    )
    mkdir(users_endpoint_path)
    mkdir(users_endpoint_path / "posts")
    mkdir(users_endpoint_path / ".well-known")
    # Just an index file (and .nojekyll if its github hosted)
    create_instance_files(config)
    # Create the user, its banner/icon (if any) and its webfinger endpoints
    create_actor(
        config,
        has_featured_note=featured_note.is_file()
    )
    create_webfinger(config)
    # Followers and following
    create_following(config)
    create_followers(config)
    # Finally posts and outbox
    notes_generator = list(generate_notes(config, entries_path))
    create_posts(
        config,
        notes=notes_generator,
        featured_note=featured_note
    )
    create_outbox(config, notes=notes_generator)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="StaticPub",
        description="A Static ActivityPub Instance Generator",
    )
    parser.add_argument('instance_filename', nargs="?", default="instance.cfg")
    args = parser.parse_args()

    if Path(args.instance_filename).is_file():
        instance_config = get_config(Path(curdir), args.instance_filename)
        run_staticpub(instance_config)
    else:
        parser.print_help()
