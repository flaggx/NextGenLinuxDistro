from director.stage.dock import plan

SCREEN = {"x": 0, "y": 0, "width": 1000, "height": 800}
WS1 = {"name": "1", "focused": True, "rect": SCREEN, "output": "OUT"}


def tree(*windows, ws="1", others_ws=()):
    workspaces = [{"type": "workspace", "name": ws, "nodes": [w for w in windows if w["type"] == "con"],
                   "floating_nodes": [w for w in windows if w["type"] == "floating_con"]}]
    for name, wins in others_ws:
        workspaces.append({"type": "workspace", "name": name, "nodes": wins, "floating_nodes": []})
    return {"type": "root", "nodes": [{"type": "output", "nodes": workspaces}]}


def win(id, app, floating=False, rect=None):
    return {"id": id, "pid": id, "app_id": app, "type": "floating_con" if floating else "con", "rect": rect or {}}


def test_alone_and_full_screen_needs_nothing():
    assert plan(tree(win(1, "director")), WS1, SCREEN, 0) == []


def test_a_new_window_docks_the_director_at_the_bottom():
    assert plan(tree(win(1, "director"), win(2, "zathura")), WS1, SCREEN, 0) == [
        "[con_id=1] floating enable, sticky enable",
        "gaps bottom all set 240",
        "[con_id=1] resize set width 1000 px height 240 px, move absolute position 0 px 560 px",
    ]


def test_docked_and_in_place_needs_nothing():
    docked = win(1, "director", floating=True, rect={"width": 1000, "height": 240})
    assert plan(tree(docked, win(2, "zathura")), WS1, SCREEN, 240) == []


def test_last_other_window_closing_undocks():
    docked = win(1, "director", floating=True, rect={"width": 1000, "height": 240})
    assert plan(tree(docked), WS1, SCREEN, 240) == [
        "[con_id=1] sticky disable, floating disable",
        "gaps bottom all set 0",
    ]


def test_follows_to_an_empty_workspace_and_fills_it():
    docked = win(1, "director", floating=True, rect={"width": 1000, "height": 240})
    ws2 = {"name": "2", "focused": True, "rect": SCREEN, "output": "OUT"}
    t = tree(win(2, "zathura"), ws="1", others_ws=[("2", [])])
    t["nodes"][0]["nodes"][0]["floating_nodes"] = [docked]
    assert plan(t, ws2, SCREEN, 240) == [
        "[con_id=1] sticky disable, floating disable",
        '[con_id=1] move container to workspace "2"',
        "gaps bottom all set 0",
    ]


def test_no_director_window_no_commands():
    assert plan(tree(win(2, "zathura")), WS1, SCREEN, 0) == []
