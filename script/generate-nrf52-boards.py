#!/usr/bin/env python3

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import os
import yaml

from esphome.components.nrf52 import PLATFORM_RECOMMENDED_SDK_VERSION
from esphome.helpers import write_file_if_changed

SUPPORTED_MCUS = [
    "nrf54h20",
    "nrf54l20",
    "nrf54l15",
    "nrf54l10",
    "nrf54l05",
    "nrf5340",
    "nrf52840",
    "nrf52833",
    "nrf52832",
    "nrf52820",
    "nrf52811", "nrf52810",
]

root = Path(__file__).parent.parent
boards_file_path = root / "esphome" / "components" / "esp32" / "boards.py"


def checkout_nrf_sdk_repo(version: str):
    tempdir = tempfile.mkdtemp()
    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            "-c",
            "advice.detachedHead=false",
            "--depth",
            "1",
            "--branch",
            version,
            "https://github.com/nrfconnect/sdk-nrf",
            tempdir,
        ],
        check=True,
    )
    return tempdir


def get_nrf_sdk(ncs_path: Path, version: str):
    nrf_sdk_path = ncs_path / version
    if not nrf_sdk_path.is_dir():
        print(f"NRF SDK not found at {nrf_sdk_path}. Cloning nRF SDK repository...")
        nrf_sdk_path = Path(checkout_nrf_sdk_repo(version))
    return nrf_sdk_path


def get_edtlib(nrf_sdk_path: Path):
    sys.path.insert(
        0,
        str(nrf_sdk_path / "zephyr" / "scripts" / "dts" / "python-devicetree" / "src"),
    )

    import devicetree.edtlib as edtlib

    return edtlib


def get_list_boards(nrf_sdk_path: Path):
    sys.path.insert(0, str(nrf_sdk_path / "zephyr" / "scripts"))
    import list_boards

    return list_boards


def preprocess_dts(dts_file, include_paths):
    """Preprocess a DTS file using gcc -E"""
    fd, preprocessed_file = tempfile.mkstemp(suffix=".dts.pre", text=True)
    os.close(fd)

    include_opts = [f"-I{str(path)}" for path in include_paths]

    cmd = (
        [
            "gcc",
            "-E",
            "-nostdinc",
            "-undef",
            "-x",
            "assembler-with-cpp",
            "-D__DTS__",
            "-P",
        ]
        + include_opts
        + ["-o", preprocessed_file, dts_file]
    )

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return preprocessed_file
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"DTS preprocessing failed: {e.stderr}")


def parse_dts(edtlib, board_dts_file, include_paths, bindings_dirs):
    include_paths.extend([board_dts_file.parent, board_dts_file.parent / "dts"])
    preprocessed_file = preprocess_dts(board_dts_file, include_paths)
    dt = edtlib.EDT(preprocessed_file, bindings_dirs=bindings_dirs)
    os.remove(preprocessed_file)
    return dt


def get_boards_from_yaml(board_yaml_file: Path) -> list[str]:
    with board_yaml_file.open("r") as f:
        board_yaml = yaml.safe_load(f)
    boards = []
    board = board_yaml["board"]
    if not "socs" in board:
        return []
    for soc in board["socs"]:
        name = soc["name"]
        if name not in SUPPORTED_MCUS:
            continue
        boards.append(name)
    if "boards" in board_yaml:
        for board in board_yaml["boards"]:
            if "name" in board:
                boards.append(board["name"])
    return boards


def get_board_dts_files(nrf_sdk_path: Path, supported_mcus: list[str]) -> list[Path]:
    board_dirs = [
        nrf_sdk_path / "nrf" / "boards",
        nrf_sdk_path / "zephyr" / "boards",
    ]
    board_yaml_files = []
    for d in board_dirs:
        if d.is_dir():
            board_yaml_files.extend(p for p in d.rglob("board.yaml") if p.is_file())

    board_dts_files: dict[str, Path] = {}
    for d in board_dirs:
        if d.is_dir():
            for p in d.rglob("*.dts"):
                if p.is_file():
                    mcu = p.stem.split("_")[0]
                    if mcu in supported_mcus:
                        board_dts_files[mcu] = p
    return board_dts_files


def qualifiers_to_dts_filename(board_name, qualifier, board_dir):
    segments = qualifier.replace("/", "_")

    # Check if this is a simple SoC name (no variants, just base)
    # This happens when qualifier matches board_name pattern but has no structure
    if "/" not in qualifier and "_" not in segments:
        if (board_dir / f"{board_name}.dts").is_file():
            return board_name
        else:
            return f"{board_name}_{segments}"
        # Single segment (just SoC name with no variants)
        return board_name
    else:
        # Has variants or cpucluster structure
        return f"{board_name}_{segments}"


def load_board_files(board, list_boards_module):
    qualifiers = list_boards_module.board_v2_qualifiers(board)
    for q in qualifiers:
        filename = qualifiers_to_dts_filename(board.name, q, board.dir)
        dts_file = board.dir / f"{filename}.dts"
        yaml_file = board.dir / f"{filename}.yaml"
        if not dts_file.is_file() or not yaml_file.is_file():
            print(
                f"  DTS file {dts_file} or YAML file {yaml_file} does not exist, skipping..."
            )
            return None
        return {
            "board": board,
            "dts": dts_file,
            "yaml": yaml_file,
        }

def get_board_info(dt):
    soc = dt.get_node("/soc")
    if len(soc.compats) < 2:
        return None
    mcu = soc.compats[1].split(",")[-1]
    if mcu not in SUPPORTED_MCUS:
        #print(mcu)
        return None
    qspi = dt.compat2nodes["nordic,nrf-qspi"]
    if len(qspi) > 0:
        print(str(qspi[0].children))
    #print(qspi.children)
    #print(soc.get_node("qspi"))
    return {"aa": "bb"}

def get_boards_info(boards, nrf_sdk_path):
    zephyr_base = nrf_sdk_path / "zephyr"
    include_paths = [
        zephyr_base / "include",
        zephyr_base / "include" / "zephyr",
        zephyr_base / "dts" / "common",
        zephyr_base / "dts",
        zephyr_base / "dts" / "arm",
        zephyr_base / "dts" / "riscv",  # For nrf54
        nrf_sdk_path / "nrf" / "dts",
    ]
    bindings_dirs = [
        str(zephyr_base / "dts" / "bindings"),
        str(nrf_sdk_path / "nrf" / "dts" / "bindings"),
    ]
    edtlib = get_edtlib(nrf_sdk_path)
    out = []
    for board in boards:
        dt = parse_dts(edtlib, board["dts"], include_paths, bindings_dirs)
        #print(f"Board: {board['board'].name}")
        info = get_board_info(dt)
        if info is not None:
            print(f"Processed board: {board['board'].name}")
            out.append({
                "board": board["board"],
                "info": get_board_info(dt),
            })
    return out


def main(check: bool, ncs_path: Path, version: str | None = None):
    if not version:
        version = f"v{PLATFORM_RECOMMENDED_SDK_VERSION}"
    nrf_sdk_path = get_nrf_sdk(ncs_path, version)
    board_dirs = [
        nrf_sdk_path / "nrf" / "boards",
        nrf_sdk_path / "zephyr" / "boards",
    ]
    list_boards_module = get_list_boards(nrf_sdk_path)
    list_args = argparse.Namespace(
        arch_roots=[],
        soc_roots=[nrf_sdk_path / "zephyr"],
        board_roots=[nrf_sdk_path / "zephyr", nrf_sdk_path / "nrf"],
        board=None,
        #board="adafruit_feather_nrf52840",
        board_dir=[],
    )
    all_boards = list_boards_module.find_v2_boards(list_args)
    boards = []
    for board in all_boards.values():
        # print(set([soc.name for soc in board.socs]))
        if set([soc.name for soc in board.socs]).isdisjoint(SUPPORTED_MCUS):
            continue
        board = load_board_files(board, list_boards_module)
        if board:
            boards.append(board)
    get_boards_info(boards, nrf_sdk_path)

    #print("\n".join(str(board) for board in boards))
    # print(board_name)
    # print(len(supported_boards))
    return
    board_dts_files: list[Path] = []
    for d in board_dirs:
        if d.is_dir():
            board_dts_files.extend(p for p in d.rglob("*.dts") if p.is_file())
    # Optionally, ensure deterministic order
    board_dts_files.sort()
    include_paths = [
        zephyr_base / "include",
        zephyr_base / "include" / "zephyr",
        zephyr_base / "dts" / "common",
        zephyr_base / "dts",
        zephyr_base / "dts" / "arm",
        nrf_sdk_path / "nrf" / "dts",
    ]
    bindings_dirs = [
        str(zephyr_base / "dts" / "bindings"),
        str(nrf_sdk_path / "nrf" / "dts" / "bindings"),
    ]
    edtlib = get_edtlib(nrf_sdk_path)
    for p in board_dts_files:
        # print(f"Processing {p}...")
        try:
            get_board_info(edtlib, p, include_paths, bindings_dirs)
        except Exception as e:
            print(f"Error processing {p}: {e}")

    print("\n".join(str(p) for p in board_dts_files))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        help="Check if the boards_generated.py file is up to date.",
        action="store_true",
    )
    parser.add_argument(
        "--ncs-path",
        help="Path to a local checkout of the ncs repository. If not provided, the ~/.platformio checkout will be used or the repository will be cloned.",
        default=f"{Path.home()}/.platformio/packages/framework-zephyr/nrfutil_sdk",
        type=str,
    )
    parser.add_argument(
        "--ncs-version",
        help="Version of the ncs SDK to use (e.g., 'v2.9.2'). If not provided, the recommended version will be used.",
        default="recommended",
        type=str,
    )
    args = parser.parse_args()
    main(args.check, Path(args.ncs_path), args.ncs_version)
