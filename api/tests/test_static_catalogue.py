from uuid import UUID, uuid5

import pytest

from app.static_catalogue import StaticAlbum, StaticCatalogueError, create_user_journey, next_pending


def catalogue() -> list[StaticAlbum]:
    return [
        StaticAlbum(uuid5(UUID(int=0), str(rank)), rank, f"Album {rank}", f"Artist {rank}", 2000)
        for rank in range(1, 101)
    ]


def test_every_user_gets_one_stable_private_ordering_of_shared_albums() -> None:
    user = uuid5(UUID(int=0), "user-a")
    first = create_user_journey(user_id=user, catalogue=catalogue(), catalogue_version="okayafrica-v1")
    replay = create_user_journey(user_id=user, catalogue=catalogue(), catalogue_version="okayafrica-v1")

    assert [item.album_id for item in first] == [item.album_id for item in replay]
    assert [item.position for item in first] == list(range(1, 101))
    assert next_pending(first) == first[0]


def test_rejects_any_non_complete_static_catalogue() -> None:
    with pytest.raises(StaticCatalogueError, match="catalogue_must_have_100_albums"):
        create_user_journey(user_id=UUID(int=1), catalogue=catalogue()[:-1], catalogue_version="v1")
