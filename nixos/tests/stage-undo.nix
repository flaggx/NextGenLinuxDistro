# Boots the stage and undo modules headless and checks they work together with
# the director's own code: snapper snapshots /home for the user (no root),
# undo restores exactly what an action changed, and the director can see and
# arrange Sway's windows.  nix build .#checks.x86_64-linux.stage-undo
{ pkgs, modules }:

let
  python = pkgs.python3;
  director = "PYTHONPATH=${pkgs.director}/${python.sitePackages} ${python}/bin/python3";
  undoCheck = pkgs.writeText "undo-check.py" ''
    from pathlib import Path
    from director.undo import Snapshots

    home = Path.home()
    todo, new = home / "todo.txt", home / "new.txt"
    todo.write_text("1. Renew passport\n")
    s = Snapshots()
    assert s.available(), "snapper isn't usable by this user"

    pre = s.before("rewrite the todo list")
    todo.write_text("buy milk\n")  # the mistake: overwrote instead of appending
    new.write_text("made by the action\n")
    s.after(pre)
    todo.write_text(todo.read_text() + "edited by the user afterwards\n")

    from director.undo import last_request
    changes = last_request(s.changes())
    assert [c.description for c in changes] == ["rewrite the todo list"], changes
    files = s.changed_files(changes)
    assert str(todo) in files and str(new) in files, files
    s.undo(changes)

    assert todo.read_text() == "1. Renew passport\n", todo.read_text()
    assert not new.exists()
    assert s.changes() == [], "undone change still listed"
    print("undo ok")

    # Two changes for one request are undone together.
    (home / "a").write_text("a")
    for step in ("first", "second"):
        pre = s.before(f"{step} change", "request-1")
        (home / "a").write_text((home / "a").read_text() + step)
        s.after(pre)
        # Something else writes between the two actions (a log, a browser...).
        (home / "between.log").write_text((home / "between.log").read_text() + step if step == "second" else step)
    group = last_request(s.changes())
    assert [c.description for c in group] == ["first change", "second change"], group
    s.undo(group)
    assert (home / "a").read_text() == "a", (home / "a").read_text()
    assert (home / "between.log").read_text() == "firstsecond", "undo reverted a file it didn't change"
    print("grouped undo ok")

    from director.system import os_context
    assert "install_program" in os_context(), "director doesn't see NixOS"
    print("nixos context ok")
  '';
  stageCheck = pkgs.writeText "stage-check.py" ''
    from director.stage import current_stage
    import json, subprocess, time
    from director.tools.stage import ListWindows, ArrangeWindow, OpenShell, Zoom
    stage = current_stage()
    before = ListWindows(stage).run({})
    OpenShell(stage).run({})
    for _ in range(50):
        out = ListWindows(stage).run({})
        if out.count("foot") > before.count("foot"):
            break
        time.sleep(0.2)
    else:
        raise AssertionError("open_shell opened no terminal: " + out)
    print(out)
    window = int(out.split()[1])

    # director-dock (started by the sway config): another window is open, so the
    # director is a strip along the bottom, and tiled windows keep clear of it.
    def director_node():
        tree = json.loads(subprocess.check_output(["swaymsg", "-t", "get_tree", "-r"]))
        stack = [tree]
        while stack:
            node = stack.pop()
            if node.get("app_id") == "director":
                return node
            stack += node.get("nodes", []) + node.get("floating_nodes", [])
    screen = json.loads(subprocess.check_output(["swaymsg", "-t", "get_outputs", "-r"]))[0]["rect"]
    for _ in range(50):
        node = director_node()
        if (node and node["type"] == "floating_con"
                and node["rect"]["y"] + node["rect"]["height"] == screen["y"] + screen["height"]
                and node["rect"]["width"] == screen["width"]):
            break
        time.sleep(0.2)
    else:
        raise AssertionError(f"director not docked along the bottom: {node and node['rect']} on {screen}")
    print("docked ok", node["rect"])

    ArrangeWindow(stage).run({"window_id": window, "layout": "tabbed"})
    Zoom(stage).run({"scale": 1.5})
    outputs = json.loads(subprocess.check_output(["swaymsg", "-t", "get_outputs", "-r"]))
    assert outputs and all(o["scale"] == 1.5 for o in outputs), outputs
    print("stage ok")

    from director.backstage import Backstage
    from director.tools import RunCommand
    from director.tools.stage import show_backstage
    backstage = Backstage()
    run = RunCommand(backstage=backstage, show=lambda w: show_backstage(stage, backstage, w))
    out = run.run({"command": "echo from-backstage; exit 4", "purpose": "test"})
    assert "from-backstage" in out and out.endswith("[exit 4]"), out
    print(run.run({"command": "echo shown", "purpose": "test", "show": True}))
    for _ in range(50):
        if any(p.app == "backstage" for p in stage.list_panes()):
            break
        time.sleep(0.2)
    else:
        raise AssertionError("show=True put no backstage window on screen")
    print("backstage ok")
  '';
in
pkgs.testers.runNixOSTest {
  name = "stage-undo";
  # base.nix sets nixpkgs.config (unfree packages) and the overlay.
  node.pkgsReadOnly = false;
  nodes.machine = { ... }: {
    imports = modules;
    virtualisation = {
      memorySize = 2048;
      emptyDiskImages = [{ size = 2048; driveConfig.deviceExtraOpts.serial = "home"; }];
      fileSystems."/home" = {
        device = "/dev/disk/by-id/virtio-home";
        fsType = "btrfs";
        autoFormat = true;
        neededForBoot = true;
      };
    };
    boot.initrd.supportedFilesystems = [ "btrfs" ];
  };

  testScript = ''
    machine.wait_for_unit("multi-user.target")
    machine.succeed("findmnt -no FSTYPE /home | grep -x btrfs")
    machine.succeed("btrfs subvolume show /home/.snapshots")
    machine.succeed("test \"$(stat -c %U /home/baldur)\" = baldur")
    machine.succeed("grep -rq 'timestamp_timeout=0' /etc/sudoers")

    with subtest("undo restores exactly what an approved action changed"):
        print(machine.succeed("su - baldur -c '${director} ${undoCheck}'"))
        # Not usable by other users.
        machine.succeed("useradd -m intruder")
        machine.fail("su - intruder -c 'snapper -c home list'")

    with subtest("the sway config is valid and the director can arrange windows"):
        env = "XDG_RUNTIME_DIR=/tmp/rt WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1"
        machine.succeed("su - baldur -c 'mkdir -p /tmp/rt && chmod 700 /tmp/rt'")
        status, out = machine.execute(f"su - baldur -c '{env} sway --validate 2>&1'")
        print(out)
        assert status == 0, "invalid sway config"
        machine.succeed(f"su - baldur -c '{env} sway > /tmp/sway.log 2>&1 &'")
        machine.wait_until_succeeds("su - baldur -c 'ls /tmp/rt/sway-ipc.*'")
        print(machine.succeed("su - baldur -c 'export SWAYSOCK=$(ls /tmp/rt/sway-ipc.*); ${director} ${stageCheck}'"))
        # The conversation window opened at startup stays open even though the
        # director can't reach a model here.
        machine.succeed("su - baldur -c 'export SWAYSOCK=$(ls /tmp/rt/sway-ipc.*); swaymsg -t get_tree | grep -q \"\\\"app_id\\\": \\\"director\\\"\"'")
  '';
}
