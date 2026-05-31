from qqbot.models import MessageScope, RoleCard
from qqbot.roles import RoleStore


def test_role_store_active_scope_is_isolated(tmp_path) -> None:
    store = RoleStore(roles_dir=tmp_path / "roles", state_path=tmp_path / "state.yaml")
    role = RoleCard(id="maid", name="Maid", persona="Helpful", speaking_style="soft")
    store.save(role)

    private = MessageScope(message_type="private", user_id=1)
    group = MessageScope(message_type="group", user_id=1, group_id=2)

    store.set_active(private, "maid")

    assert store.get_active(private).id == "maid"
    assert store.get_active(group).id == "default"


def test_role_store_rejects_path_traversal_ids(tmp_path) -> None:
    store = RoleStore(roles_dir=tmp_path / "roles", state_path=tmp_path / "state.yaml")
    state = tmp_path / "state.yaml"
    state.write_text("active_roles: {}\n", encoding="utf-8")

    try:
        store.delete("../state")
    except KeyError:
        pass
    else:
        raise AssertionError("invalid role id should be rejected")

    assert state.exists()
