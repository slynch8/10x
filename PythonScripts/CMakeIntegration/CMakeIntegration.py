# ------------------------------------------------------------------------
import N10X
import subprocess
import json
import re
import xml.etree.ElementTree as ET
import os
import operator
import hashlib
import copy
import platform
import shutil
import shlex
from os.path import exists
from os.path import split
from threading import Thread

import base64

"""
CMake build integration for 10x (10xeditor.com)
Version: 0.1.6
Original Script author: https://github.com/andersama

To get started go to Settings.10x_settings, and enable the hooks, by adding these lines:
    CMake.HookBuild: true
    CMake.HookWorkspaceOpened: true

If cmake complains about not finding include directories or is "unable to compile a simple test program" find:
    vcvarsall.bat in MSVC's install directory (will likely be under /Common7/Tools) if it's not already detected

This script assumes CMake.exe is in your path! To change this modify CMake.Path

CMake_Options:
    - CMake.HookBuild: (default=False)           Hooks CMake into build commands, detects cmake projects and executes OnCMakeBuildStarted
    - CMake.HookWorkspaceOpened: (default=False) Hooks CMake into workspace opened commands, detects cmake project files inside the current workspace and writes 10x workspace files
    - CMake.Path:                                Path to a custom cmake executable or directory, default assumes CMake is on the path!
    - CMake.GuiPath:                             Path to cmake-gui executable or directory, default assumes cmake-gui is on the path!
    - CMake.Verbose: (default=False)             Turns on debugging print statements
    - CMake.vcvarsall:                           Path to vcvarsall.bat or directory, default assumes vcvarsall.bat is on the path

History:
  0.1.6
      - Make use of vcvarsall.bat to set environment variables
  0.1.5
      - Use workspace build and rebuild commands to pass cmake variables
  0.1.4
      - Use threads and use better guess for finding .sln file
  0.1.3
      - Add processing of CMakeUserPresets.json and includes
  0.1.2
      - Add cmake_gui function (use with the command window) ctrl+shift+x
      - Auto detect config and config / preset names for each workflow
  0.1.1
      - Fixed bugs and inheritance algorithm
  0.1.0
      - First Release
"""


# autopep8: off
def b64_encode(s):
    return base64.b64encode(s.encode()).decode()


def read_json_file(json_path, verbose=False):
    data = dict()
    with open(json_path, "r", encoding="utf-8-sig") as json_data:
        json_text = json_data.read()
        if verbose:
            print(json_text)
        data = json.loads(json_text)
    return data


def write_json_file(json_path, json_obj, pretty=True):
    with open(json_path, "w") as f:
        if pretty:
            json.dump(json_obj, f, indent=True)
        else:
            json.dump(json_obj, f)


def cmd(cmd_args, working_dir, env=None, verbose=False) -> dict:
    current_env = env if env != None else os.environ.copy()
    if verbose:
        print("Env:\n{0}".format(json.dumps(current_env, indent="\t")))
    process = subprocess.Popen(
        cmd_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # direct errors to stdout
        cwd=working_dir,
        env=current_env,
        encoding="utf8",
    )
    returncode = process.wait()
    result = process.stdout.read()
    # errs = process.stderr.read()
    return {"error_code": returncode, "stdout": result, "stderr": None}


def run_cmd(cmd_args, working_dir) -> str:
    return cmd(cmd_args, working_dir)["stdout"]


def get_10x_bool_setting(setting: str):
    str = N10X.Editor.GetSetting(setting)
    return str and str.lower() == "true"


def get_10x_cmdpath(setting: str, exe_name: str, ext: str):
    exe = N10X.Editor.GetSetting(setting).strip()
    if not exe:
        exe = shutil.which(exe_name)
    if not exe:
        return exe
    if os.path.isdir(exe):
        if exe_name.endswith(ext):
            exe = os.path.join(exe, exe_name)
        else:
            exe = os.path.join(exe, exe_name + ext)
    return exe


def get_10x_exe_path(setting: str, exe_name: str):
    return get_10x_cmdpath(setting, exe_name, ".exe")


# use \'s for paths, default window behavior
def norm_path_bslash(path) -> str:
    return re.sub(r"[/]", "\\", os.path.normpath(path))


# use /'s for paths, allows copy/pasting into explorer (default is \)
def norm_path_fslash(path) -> str:
    return re.sub(r"[\\]", "/", os.path.normpath(path))


def escape_bslash(input: str) -> str:
    return re.sub("\\\\", "\\\\\\\\", input)


def sub_bslash_fslash(input: str) -> str:
    return re.sub(r"[\\]", "/", input)


def cmake_paths(directory: str) -> dict:
    presetpath = norm_path_fslash(os.path.join(directory, "CMakePresets.json"))
    userpresetpath = presetpath[: -len("CMakePresets.json")] + "CMakeUserPresets.json"
    settingspath = presetpath[: -len("CMakePresets.json")] + "CMakeSettings.json"
    listspath = presetpath[: -len("CMakePresets.json")] + "CMakeLists.txt"
    return {
        "preset": presetpath,
        "userpreset": userpresetpath,
        "settings": settingspath,
        "lists": listspath,
    }


def cmake_verify_paths(paths: dict) -> dict:
    return {
        "preset": "preset" in paths and exists(paths["preset"]),
        "userpreset": "userpreset" in paths and exists(paths["userpreset"]),
        "settings": "settings" in paths and exists(paths["settings"]),
        "lists": "lists" in paths and exists(paths["lists"]),
    }


def macro_expansion(target_string: str, macros) -> str:
    i = int(0)
    # TODO: unescape strings
    out_string = ""
    while i < len(target_string):
        em = i
        if target_string[i] == "$":  # potential macro expansion
            while em < len(target_string) and target_string[em] != "}":
                em += 1
            macro_key = target_string[i : em + 1]
            macro_value = macro_key
            if macro_key in macros and macros[macro_key] != None:
                macro_value = macros[macro_key]
            out_string += macro_value
            # jump past macro expansion
            i = em + 1
        else:
            while em < len(target_string) and target_string[em] != "$":
                em += 1
            out_string += target_string[i:em]
            # jump past substring
            i = em

    return out_string


def macro_expansion_n10x(target_string: str, macros) -> str:
    i = int(0)
    # TODO: unescape strings
    out_string = ""
    while i < len(target_string):
        em = i
        if target_string[i] == "$":  # potential macro expansion
            while em < len(target_string) and target_string[em] != ")":
                em += 1
            macro_key = target_string[i : em + 1]
            macro_value = macro_key
            if macro_key in macros and macros[macro_key] != None:
                macro_value = macros[macro_key]
            out_string += macro_value
            # jump past macro expansion
            i = em + 1
        else:
            while em < len(target_string) and target_string[em] != "$":
                em += 1
            out_string += target_string[i:em]
            # jump past substring
            i = em

    return out_string


def macro_expand_any(item, macros):
    if type(item) is str:
        return macro_expansion(item, macros)
    elif type(item) is dict:
        for key in item:
            item[key] = macro_expand_any(item[key], macros)
        return item
    elif type(item) is list:
        for i in range(0, len(item)):
            item[i] = macro_expand_any(item[i], macros)
        return item
    # otherwise just return the item as is
    return item


def macro_expand_n10x(item, macros):
    if type(item) is str:
        return macro_expansion_n10x(item, macros)
    elif type(item) is dict:
        for key in item:
            item[key] = macro_expand_n10x(item[key], macros)
        return item
    elif type(item) is list:
        for i in range(0, len(item)):
            item[i] = macro_expand_n10x(item[i], macros)
        return item
    # otherwise just return the item as is
    return item


def cmake_inheirit(child_obj, parent_obj, top_level=True):
    expanded_obj = copy.deepcopy(parent_obj)

    # see: https://cmake.org/cmake/help/git-master/manual/cmake-presets.7.html#configure-preset
    if top_level:  # don't inheirit these
        expanded_obj.pop("name", None)
        expanded_obj.pop("description", None)
        expanded_obj.pop("displayName", None)
        expanded_obj.pop("hidden", None)

    for key in child_obj:
        if key in expanded_obj and type(child_obj[key]) == type(expanded_obj[key]):
            if type(child_obj[key]) is dict:
                expanded_obj[key] = cmake_inheirit(
                    child_obj[key], expanded_obj[key], False
                )
            elif type(child_obj[key]) is list:
                # inherit chain*
                expanded_obj[key].extend(child_obj[key])
            else:
                expanded_obj[key] = child_obj[key]
        else:
            expanded_obj[key] = child_obj[key]

    if top_level:  # we've successfully inherited the previous, remove this item
        expanded_obj.pop("inherits", None)

    return expanded_obj


def cmake_merge_userdata(child_data: dict, key: str, parent_data: dict = {}):
    configs = []
    if key in parent_data:  # we're expecting a to be a list!
        configs = copy.deepcopy(parent_data[key])

    parent_len = len(configs)
    # add child configs
    if key in child_data:
        configs.extend(child_data[key])

    depths = []
    # first passes to figure out inheiritance of configs
    # it's an error for any config object to have matching "name" keys, user data doesn't appear to "override" or "overwrite"
    seen = {}
    dup = []
    err_msg = ""
    dup_err = False
    for config in configs:
        if config["name"] not in seen:
            seen[config["name"]] = config
        else:
            dup_err = True
            dup.append(config)

    if dup_err:
        err_msg = "Error!: Duplicate presets\n"
        for config in dup:
            err_msg += json.dumps(config, indent="\t")
            err_msg += "\n"

    return {"configs": configs, "error": dup_err, "error_message": err_msg}


def cmake_inherit_algorithm(configs: list, parent_len):
    depths = []
    # first passes to figure out inheiritance of configs

    # first let the parent configs inherit from themselves
    for i in range(0, parent_len):  # config in configs:
        config = configs[i]
        if "inherits" in config:
            new_config = dict()
            inherits_list = []
            if type("inherits") is list:
                inherits_list = config["inherits"]
            else:  # should be a string
                inherits_list.append(config["inherits"])

            child_name = config["name"]
            for idx in range(0, len(inherits_list)):
                parent_name = inherits_list[idx]
                for j in range(0, parent_len):  # len(configs)
                    c = configs[j]
                    if c["name"] == parent_name:
                        if "inherits" in c:
                            depths.append(
                                {
                                    "config": child_name,
                                    "parent": parent_name,
                                    "depth": 2,
                                    "self_index": i,
                                    "parent_index": j,
                                }
                            )
                        else:
                            depths.append(
                                {
                                    "config": child_name,
                                    "parent": parent_name,
                                    "depth": 1,
                                    "self_index": i,
                                    "parent_index": j,
                                }
                            )
                        break
        else:
            depths.append(
                {
                    "config": config["name"],
                    "parent": None,
                    "depth": 0,
                    "self_index": i,
                    "parent_index": 0,
                }
            )
    # second let the child configs inherit from both the parents and themselves
    for i in range(parent_len, len(configs)):
        config = configs[i]
        if "inherits" in config:
            new_config = dict()
            inherits_list = []
            if type("inherits") is list:
                inherits_list = config["inherits"]
            else:  # should be a string
                inherits_list.append(config["inherits"])

            child_name = config["name"]
            for idx in range(0, len(configs)):
                parent_name = inherits_list[idx]
                for j in range(0, parent_len):  # len(configs)
                    c = configs[j]
                    if c["name"] == parent_name:
                        if "inherits" in c:
                            depths.append(
                                {
                                    "config": child_name,
                                    "parent": parent_name,
                                    "depth": 2,
                                    "self_index": i,
                                    "parent_index": j,
                                }
                            )
                        else:
                            depths.append(
                                {
                                    "config": child_name,
                                    "parent": parent_name,
                                    "depth": 1,
                                    "self_index": i,
                                    "parent_index": j,
                                }
                            )
                        break
        else:
            depths.append(
                {
                    "config": config["name"],
                    "parent": None,
                    "depth": 0,
                    "self_index": i,
                    "parent_index": 0,
                }
            )

    start_index = 0  # this counts the # of items with 0 depth
    while True:
        mx_depth = 0
        # this is to recurse through inheirited configs in a linear fashion
        start_loop = True  # len(depths)-start_index, 0, -1
        for i in reversed(
            range(0, len(depths) - start_index)
        ):  # reverse the loop to handle precedence of inheiritance (earliest > precedence)
            item = depths[i]
            if item["depth"] == 0 and start_loop:
                start_index = (
                    start_index + 1
                )  # continue the loop past this point in future
                continue
            child_index = item["self_index"]
            parent_index = item["parent_index"]
            depth = depths[parent_index]["depth"] + 1
            if (item["parent"] != None and depth == 1) or item["depth"] == 1:
                if i + 1 < len(depths):
                    prev_item = depths[i - 1]
                    prev_child_index = prev_item["self_index"]
                    prev_parent_index = prev_item["parent_index"]
                    prev_depth = prev_item["depth"]
                    child_index = item["self_index"]
                    parent_index = item["parent_index"]
                    if child_index == prev_child_index and prev_depth > 0:
                        # haven't finished inheriting something which comes first, wait to inherit
                        start_loop = False
                    else:
                        # note: we only inheirit from parents w/ no parents*
                        configs[child_index] = cmake_inheirit(
                            configs[child_index], configs[parent_index]
                        )
                        configs[child_index].pop("inherits", None)
                        depths[child_index]["parent"] = None
                        depths[child_index]["depth"] = 0
                        if start_loop:
                            start_index = (
                                start_index + 1
                            )  # continue the loop past this point in future
                else:
                    # note: we only inheirit from parents w/ no parents*
                    configs[child_index] = cmake_inheirit(
                        configs[child_index], configs[parent_index]
                    )
                    configs[child_index].pop("inherits", None)
                    depths[child_index]["parent"] = None
                    depths[child_index]["depth"] = 0
                    if start_loop:
                        start_index = (
                            start_index + 1
                        )  # continue the loop past this point in future
            else:
                configs[child_index][
                    "depth"
                ] = depth  # update this item's current depth (doesn't matter)
                start_loop = False

            if depths[i]["depth"] > mx_depth:
                mx_depth = depths[i]["depth"]

        if not (mx_depth > 0):
            break  # finally we're done, everything has inheirited its parent properly

    # data[key] = configs
    return configs


def cmake_merge_item(
    preset_data: dict, user_data: dict, args: dict, macros: dict, key: str
):
    data = dict()
    data[key] = []
    data["error"] = False
    data["error_message"] = ""

    if key in preset_data or key in user_data:
        merged = cmake_merge_userdata(preset_data, key, user_data)  # user_data,key,data
        parent_len = 0
        if key in preset_data:
            parent_len = len(preset_data[key])
        if merged["error"]:
            data[key] = merged["configs"]
            data["error"] = merged["error"]
            data["error_message"] = merged["error_message"]
            return data

        configs = cmake_inherit_algorithm(merged["configs"], parent_len)
        # unexpanded_configs = configs
        for i in range(0, len(configs)):
            if "generator" in configs[i]:
                macros["${generator}"] = macro_expand_any(
                    configs[i]["generator"], macros
                )
            else:
                macros["${generator}"] = None

            if "name" in configs[i]:
                macros["${presetName}"] = macro_expand_any(configs[i]["name"], macros)
                macros["${name}"] = macros["${presetName}"]
            else:
                macros["${presetName}"] = None
                macros["${name}"] = None

            configs[i] = macro_expand_any(configs[i], macros)
            # add in the cmake variables over commandline (overrides)
            for cmake_var in args["entries"]:  # macro expand the variables?
                k = macro_expand_any(cmake_var["name"], macros)
                v = macro_expand_any(cmake_var["value"], macros)
                if not "cacheVariables" in configs[i]:
                    configs[i]["cacheVariables"] = {}
                configs[i]["cacheVariables"][k] = v

        data[key] = configs
    return data


def cmake_parse_args(cmd_args: list) -> dict:
    # see: https://cmake.org/cmake/help/latest/manual/cmake.1.html
    # -D <var>:<type>=<value>, -D <var>=<value>
    # -C <intial-cache>
    # -G <generator-name>
    # returns a cache-v2 json like dictionary of cmake variables that got parsed over command-line, later entries have greater precedence
    cmake_cache = dict()
    cmake_cache["entries"] = []
    insert_point = 0
    skip_arg = False
    for i in range(0, len(cmd_args)):
        arg = cmd_args[i]
        if skip_arg:
            skip_arg = False
            continue
        if (
            arg == "&&" or arg == "|" or arg == ">"
        ):  # only parse one cmake command at a time
            break
        if arg == "cmake" or arg.endswith("cmake.exe"):
            continue  # presumably the start of the command line if someone forgot to strip the exe
        if arg.startswith("-D"):
            m = re.match("^-D([^:=]*)(:[^=]*)?=(.*)$", arg)
            cmake_cache["entries"].append(
                {"name": m.group(1), "type": m.group(2), "value": m.group(3)}
            )

        elif arg == "-G" and i + 1 < len(cmd_args):
            cmake_cache["entries"].append(
                {
                    "name": "CMAKE_GENERATOR",
                    "properties": [
                        {"name": "HELPSTRING", "value": "Name of generator."}
                    ],
                    "type": "INTERNAL",
                    "value": cmd_args[i + 1],
                }
            )
            skip_arg = True
        elif arg == "-C" and i + 1 < len(cmd_args):
            cached = read_json_file(cmd_args[i + 1])
            if "entries" in cached and type(cached["entries"]) is list:
                count = len(cached["entries"])
                cmake_cache["entries"][insert_point:insert_point] = cached["entries"]
                insert_point += count
                skip_arg = True
        elif arg == "--config" and i + 1 < len(cmd_args):
            cmake_cache["entries"].append(
                {
                    "name": "CMAKE_CONFIG_NAME",
                    "type": "INTERNAL",
                    "value": cmd_args[i + 1],
                }
            )
            skip_arg = True
        elif arg.startswith("--preset"):
            # --preset <preset>, --preset=<preset>
            if arg == "--preset" and i + 1 < len(cmd_args):
                preset_name = cmd_args[i + 1]
                cmake_cache["entries"].append(
                    {
                        "name": "CMAKE_PRESET_NAME",
                        "type": "INTERNAL",
                        "value": preset_name,
                    }
                )
                skip_arg = True
            else:
                m = re.match("^--preset=(.*)$", arg)
                cmake_cache["entries"].append(
                    {
                        "name": "CMAKE_PRESET_NAME",
                        "type": "INTERNAL",
                        "value": m.group(1),
                    }
                )
        elif arg == "-A" and i + 1 < len(cmd_args):
            # -A <platform-name> Specify platform name if supported by generator.
            cmake_cache["entries"].append(
                {
                    "name": "CMAKE_GENERATOR_PLATFORM",
                    "properties": [
                        {"name": "HELPSTRING", "value": "Name of generator platform."}
                    ],
                    "type": "INTERNAL",
                    "value": cmd_args[i + 1],
                }
            )
            skip_arg = True
        elif arg == "-S" and i + 1 < len(cmd_args):
            cmake_cache["entries"].append(
                {
                    "name": "CMAKE_CURRENT_PROJECT_SOURCE_DIR",
                    "properties": [
                        {"name": "HELPSTRING", "value": "Value Computed by 10xEditor"}
                    ],
                    "type": "STATIC",
                    "value": cmd_args[i + 1],
                }
            )
            skip_arg = True
        elif arg == "-B" and i + 1 < len(cmd_args):
            cmake_cache["entries"].append(
                {
                    "name": "CMAKE_CURRENT_PROJECT_BINARY_DIR",
                    "properties": [
                        {"name": "HELPSTRING", "value": "Value Computed by 10xEditor"}
                    ],
                    "type": "STATIC",
                    "value": cmd_args[i + 1],
                }
            )
            skip_arg = True
        elif arg == "--install-prefix" and i + 1 < len(cmd_args):
            cmake_cache["entries"].append(
                {
                    "name": "CMAKE_INSTALL_PREFIX",
                    "properties": [
                        {
                            "name": "HELPSTRING",
                            "value": "Specifies the installation directory. Must be an absolute path.",
                        }
                    ],
                    "type": "PATH",
                    "value": cmd_args[i + 1],
                }
            )
            skip_arg = True
        # TODO: parse more command line and make it available to python

    return cmake_cache


# see: https://cmake.org/cmake/help/latest/manual/cmake-presets.7.html#macro-expansion
def cmake_prep(
    source_dir,
    build_dir,
    cmd_args,
    use_presets_if_available=True,
    use_settings_if_available=True,
):
    cmakelists_exists = IsCMakeDirectory(source_dir)

    if not (cmakelists_exists):
        return dict()

    # preset, userpreset, settings, lists
    paths = cmake_paths(source_dir)
    paths_exist = cmake_verify_paths(paths)

    preset_exists = paths_exist["preset"]
    user_preset_exists = paths_exist["userpreset"]
    settings_exists = paths_exist["settings"]
    lists_exists = paths_exist["lists"]

    args = cmake_parse_args(cmd_args)
    projectFile = paths["lists"]

    if settings_exists:
        thisFile = paths["settings"]
        thisFileDir, thisFileName = split(thisFile)
    else:
        thisFile = None
        thisFileDir = None

    # command line overrides
    generator = None
    bin_dir = build_dir
    src_dir = source_dir
    config_name = None
    preset_name = None

    for cmake_var in args["entries"]:
        if cmake_var["name"] == "CMAKE_GENERATOR":
            generator = cmake_var["value"]
        elif cmake_var["name"] == "CMAKE_CURRENT_PROJECT_BINARY_DIR":
            bin_dir = cmake_var["value"]
        elif cmake_var["name"] == "CMAKE_CURRENT_PROJECT_SOURCE_DIR":
            src_dir = cmake_var["value"]
        elif cmake_var["name"] == "CMAKE_CONFIG_NAME":
            config_name = cmake_var["value"]
        elif cmake_var["name"] == "CMAKE_PRESET_NAME":
            preset_name = cmake_var["value"]

    src_parent, src_name = split(src_dir)

    bin_parent = None
    bin_name = None
    if bin_dir:
        bin_parent, bin_name = split(bin_dir)

    hasher = hashlib.shake_256(bytes(src_dir, encoding="utf-8-sig"))
    workspaceHash = hasher.hexdigest(20)

    macros = {
        "${sourceDir}": src_dir,
        "${sourceParentDir}": src_parent,
        "${sourceDirName}": src_name,
        "${presetName}": preset_name,  # like --Config
        "${generator}": generator,
        "${hostSystemName}": platform.system(),
        "${dollar}": "$",
        "${pathListSep}": ";",  # TODO: this apparently changes given an OS? #a native character for separating lists of paths
        # old settings.json macros
        "${workspaceRoot}": src_dir,
        "${workspaceHash}": str(
            workspaceHash
        ),  # TODO: find out what hash functions typically get used here
        "${projectFile}": projectFile,
        "${projectDir}": src_dir,
        "${thisFile}": thisFile,
        "${thisFileDir}": thisFileDir,
        "${name}": config_name,  # like --preset
    }
    # see: https://learn.microsoft.com/en-us/cpp/build/cmake-presets-json-reference?view=msvc-170
    # $env{<variable-name>} environment variable with name <variable-name>
    # $penv{<variable-name>} Similar to $env{<variable-name>}, except that the value only comes from the parent environment, and never
    # $vendor{<macro-name>} An extension point for vendors to insert their own macros. CMake will not be able to use presets which have a $vendor{<macro-name>} macro, and effectively ignores such presets. However, it will still be able to use other presets from the same file.
    # print(f'{key}: {value}')

    # see: https://learn.microsoft.com/en-us/cpp/build/cmakesettings-reference?view=msvc-170#macros
    # ${macro}
    # ${workspaceRoot}, ${workspaceHash}, ${projectFile}, ${projectDir}, ${thisFile}, ${thisFileDir}, ${name}, ${generator}, ${env.VARIABLE}
    # ${env.<VARIABLE>} environment variable with name <variable-name>
    for key, value in os.environ.items():
        macros["$env{" + key + "}"] = value
        macros["${env." + key + "}"] = value

    if cmakelists_exists:
        if use_presets_if_available and (preset_exists or user_preset_exists):
            includes = []
            include_objs = []
            if user_preset_exists:
                abs_userpreset_path = norm_path_fslash(
                    os.path.normpath(os.path.join(source_dir, paths["userpreset"]))
                )
                includes.append(abs_userpreset_path)
            if preset_exists:  # user presets implicitly include presets by default
                abs_preset_path = norm_path_fslash(
                    os.path.normpath(os.path.join(source_dir, paths["preset"]))
                )
                if not abs_preset_path in includes:
                    includes.append(abs_preset_path)

            i = 0
            while i < len(includes):
                preset_obj = read_json_file(includes[i])
                include_objs.append(preset_obj)
                if "include" in preset_obj:
                    current_includes = []
                    # construct an array to refer to all the loaded json objects later
                    preset_obj["include_idxs"] = []

                    if type(preset_obj["include"]) is str:
                        current_includes.append(
                            norm_path_fslash(
                                os.path.normpath(
                                    os.path.join(source_dir, preset_obj["include"])
                                )
                            )
                        )
                    elif type(preset_obj["include"]) is list:
                        for include in preset_obj["include"]:
                            current_includes.append(
                                norm_path_fslash(
                                    os.path.normpath(os.path.join(source_dir, include))
                                )
                            )

                    for include in current_includes:
                        already_loaded = False
                        for idx in range(0, len(includes)):
                            if includes[idx] == include:
                                preset_obj["include_idxs"].append(idx)
                                already_loaded = True
                                break
                        if (
                            not already_loaded
                        ):  # this might be an error because this could mean a garunteed overlap?
                            preset_obj["include_idxs"].append(len(includes))
                            includes.append(include)

                # next in queue
                i = i + 1

            data = dict()
            data["configurePresets"] = []
            data["buildPresets"] = []
            data["testPresets"] = []
            data["packagePresets"] = []
            data["workflowPresets"] = []
            data["version"] = 1

            # set the maximum version required
            for i in range(0, len(include_objs)):
                if (
                    "version" in include_objs[i]
                    and include_objs[i]["version"] > data["version"]
                ):
                    data["version"] = include_objs[i]["version"]

            # if "configurePresets" in preset_data or "configurePresets" in user_data:
            for i in range(0, len(include_objs)):
                if i == 0 and user_preset_exists:
                    continue
                if "configurePresets" in include_objs[i]:
                    data["configurePresets"].extend(include_objs[i]["configurePresets"])

            user_data = {}
            if user_preset_exists and "configurePresets" in include_objs[0]:
                user_data = include_objs[0]

            merged = cmake_merge_item(data, user_data, args, macros, "configurePresets")
            data["configurePresets"] = merged["configurePresets"]
            data["configure_error"] = merged["error"]
            data["configure_error_message"] = merged["error_message"]
            # if "buildPresets" in data or "buildPresets" in user_data:
            for i in range(0, len(include_objs)):
                if i == 0 and user_preset_exists:
                    continue
                if "buildPresets" in include_objs[i]:
                    data["buildPresets"].extend(include_objs[i]["buildPresets"])

            user_data = {}
            if user_preset_exists and "buildPresets" in include_objs[0]:
                user_data = include_objs[0]

            merged = cmake_merge_item(data, user_data, args, macros, "buildPresets")
            data["buildPresets"] = merged["buildPresets"]
            data["build_error"] = merged["error"]
            data["build_error_message"] = merged["error_message"]
            # if "testPresets" in data or "testPresets" in user_data:
            for i in range(0, len(include_objs)):
                if i == 0 and user_preset_exists:
                    continue
                if "testPresets" in include_objs[i]:
                    data["testPresets"].extend(include_objs[i]["testPresets"])

            user_data = {}
            if user_preset_exists and "testPresets" in include_objs[0]:
                user_data = include_objs[0]

            merged = cmake_merge_item(data, user_data, args, macros, "testPresets")
            data["testPresets"] = merged["testPresets"]
            data["test_error"] = merged["error"]
            data["test_error_message"] = merged["error_message"]
            # if "packagePresets" in data or "packagePresets" in user_data:
            for i in range(0, len(include_objs)):
                if i == 0 and user_preset_exists:
                    continue
                if "packagePresets" in include_objs[i]:
                    data["packagePresets"].extend(include_objs[i]["packagePresets"])

            user_data = {}
            if user_preset_exists and "packagePresets" in include_objs[0]:
                user_data = include_objs[0]

            merged = cmake_merge_item(data, user_data, args, macros, "packagePresets")
            data["packagePresets"] = merged["packagePresets"]
            data["package_error"] = merged["error"]
            data["package_error_message"] = merged["error_message"]
            # if "workflowPresets" in data or "workflowPresets" in user_data:
            for i in range(0, len(include_objs)):
                if i == 0 and user_preset_exists:
                    continue
                if "workflowPresets" in include_objs[i]:
                    data["workflowPresets"].extend(include_objs[i]["workflowPresets"])

            user_data = {}
            if user_preset_exists and "workflowPresets" in include_objs[0]:
                user_data = include_objs[0]

            merged = cmake_merge_item(data, user_data, args, macros, "workflowPresets")
            data["workflowPresets"] = merged["workflowPresets"]
            data["workflow_error"] = merged["error"]
            data["workflow_error_message"] = merged["error_message"]

            data["macros"] = macros
            data["error"] = (
                ("configure_error" in data and data["configure_error"])
                or ("build_error" in data and data["build_error"])
                or ("test_error" in data and data["test_error"])
                or ("package_error" in data and data["package_error"])
                or ("workflow_error" in data and data["workflow_error"])
            )

            if "entries" in args:
                data["entries"] = args["entries"]
            return data

        if use_settings_if_available and paths_exist["settings"]:
            data = read_json_file(paths["settings"])
            data["macros"] = macros
            # settings don't do inheritance? but they definitely expand macros
            unexpanded_configs = data["configurations"]
            for i in range(0, len(unexpanded_configs)):
                if "generator" in unexpanded_configs[i]:
                    macros["${generator}"] = macro_expand_any(
                        unexpanded_configs[i]["generator"], macros
                    )
                else:
                    macros["${generator}"] = (
                        generator  # will leave ${generator} unexpanded
                    )

                if "name" in unexpanded_configs[i]:
                    macros["${presetName}"] = macro_expand_any(
                        unexpanded_configs[i]["name"], macros
                    )
                    macros["${name}"] = macros["${presetName}"]
                else:
                    macros["${presetName}"] = None
                    macros["${name}"] = None

                for cmake_var in args["entries"]:
                    found = False
                    found_idx = 0
                    for v in range(0, len(data["configurations"][i]["variables"])):
                        config_var = data["configurations"][i]["variables"][v]
                        if config_var["name"] == cmake_var["name"]:
                            found = True
                            found_idx = v
                            break

                    cmake_var_copy = copy.deepcopy(cmake_var)
                    cmake_var_copy.pop("properties", None)
                    if found:
                        data["configurations"][i]["variables"][
                            found_idx
                        ] = cmake_var_copy
                    else:
                        data["configurations"][i]["variables"].append(cmake_var_copy)

                data["configurations"][i] = macro_expand_any(
                    unexpanded_configs[i], macros
                )
            data = macro_expand_any(data, macros)
            if "entries" in args:
                data["entries"] = args["entries"]
            return data
        # Handling of empty project
        data = {}
        if "entries" in args:
            data["entries"] = args["entries"]
        data["macros"] = macros
        return data
        # failover use just cmake, no presets.json, no settings.json
    return dict()


def cmake_version():
    CMake_EXE = N10X.Editor.GetSetting("CMake.Path").strip()
    if not CMake_EXE:
        CMake_EXE = "cmake"
    if os.path.isdir(CMake_EXE):
        CMake_EXE = os.path.join(CMake_EXE, "cmake.exe")

    txworkspace = N10X.Editor.GetWorkspaceFilename()
    directory, filename = split(txworkspace)  # os.path.split

    cmd_result = cmd([CMake_EXE, "--version"], directory)
    r = re.search(
        "^cmake\\s+version\\s+(\\d+).(\\d+).(\\d+)[-]?(\\w+)?", cmd_result["stdout"]
    )

    if r != None:
        result = {
            "major": int(r.group(1)),
            "minor": int(r.group(2)),
            "patch": int(r.group(3)),
            "tag": r.group(4),
        }
        result["preset_support"] = result["major"] >= 3 and result["minor"] >= 1
    else:
        result = {
            "major": 0,
            "minor": 0,
            "patch": 0,
            "tag": "",
            "preset_support": False,
        }

    print(result)
    return result


def cmake_gui(src_dir: str = ""):
    txworkspace = N10X.Editor.GetWorkspaceFilename()
    directory, filename = split(txworkspace)  # os.path.split

    if len(src_dir) == 0 or src_dir == ".":
        src_dir = directory

    cmakelists_exists = IsCMakeDirectory(src_dir)
    global CMake_GUI

    if cmakelists_exists:
        stdtxt = run_cmd([CMake_GUI, "-S", src_dir], src_dir)
        return stdtxt

    return ""


#
# Syntax:
#    vcvarsall.bat [arch] [platform_type] [winsdk_version] [-vcvars_ver=vc_version] [-vcvars_spectre_libs=spectre_mode]
# where :
#    [arch]: x86 | amd64 | x86_amd64 | x86_arm | x86_arm64 | amd64_x86 | amd64_arm | amd64_arm64
#    [platform_type]: {empty} | store | uwp
#    [winsdk_version] : full Windows 10 SDK number (e.g. 10.0.10240.0) or "8.1" to use the Windows 8.1 SDK.
#    [vc_version] : {none} for latest installed VC++ compiler toolset |
#                   "14.0" for VC++ 2015 Compiler Toolset |
#                   "14.xx" for the latest 14.xx.yyyyy toolset installed (e.g. "14.11") |
#                   "14.xx.yyyyy" for a specific full version number (e.g. "14.11.25503")
#    [spectre_mode] : {none} for libraries without spectre mitigations |
#                     "spectre" for libraries with spectre mitigations


def cmake_env(vcvarsall, directory, platform) -> dict:  # x64 etc...
    env_out = os.path.join(directory, "cmake_env.txt")
    args = [vcvarsall, platform, "&&", "set", ">", env_out]
    print(" ".join(args))
    r = cmd(args, directory)
    print("cmake_env")
    if r["stdout"]:
        print(r["stdout"])

    if r["error_code"] == 0:
        o = {}
        current_env = os.environ.copy()
        # clone existing env
        for k in current_env:
            o[k] = current_env[k]

        with open(env_out, "r", encoding="utf-8-sig") as env_data:
            env_txt = env_data.read()
            lines = env_txt.splitlines()
            for l in lines:
                if l.startswith("**") or l.startswith("[vcvarsall.bat]"):
                    continue
                env_line = re.match("^([^=]+)=(.*)$", l)
                if (
                    env_line
                    and len(env_line.group(1)) > 0
                    and len(env_line.group(2)) > 0
                ):
                    o[env_line.group(1)] = env_line.group(2)

        return o
    else:
        o = os.environ.copy()
        return o


def cmake_configure(cmd_args, working_dir, env=None) -> dict:
    # ["cmake", ...]
    cmdline = cmd(cmd_args, working_dir, env)
    # read the stdout to grab the build directory
    if "stdout" in cmdline:
        N10X.Editor.LogToBuildOutput(cmdline["stdout"])
        print(cmdline["stdout"])

    if (
        ("error_code" and cmdline["error_code"] != 0)
        and "stderr" in cmdline
        and cmdline["stderr"] != None
    ):
        N10X.Editor.LogToBuildOutput(cmdline["stderr"])
        print(cmdline["stderr"])

    # debugging
    # all we technically need as feedback is the build directory we can extract from
    # the command line later if needed so I'm writing a .json file behind
    result = {
        "stdout": cmdline["stdout"],
        "stderr": cmdline["stderr"],
        "error_code": cmdline["error_code"],
        "build_dir": None,
    }

    r = re.search("-- Build files have been written to:\\s+(.+)$", cmdline["stdout"])

    if r != None:
        result["build_dir"] = r.group(1)

    return result


def cmake_build(cmd_args, working_dir, build_dir, env=None) -> dict:
    # ["cmake", ...]
    # write file api query
    query_dir = norm_path_fslash(
        os.path.join(build_dir, ".cmake/api/v1/query/client-10xeditor")
    )
    reply_dir = norm_path_fslash(os.path.join(build_dir, ".cmake/api/v1/reply/"))
    query_file = query_dir + "/query.json"

    query_json = {
        "requests": [
            {"kind": "cache", "version": 2},
            {"kind": "cmakeFiles", "version": 1},
            {"kind": "codemodel", "version": 2},
            {"kind": "toolchains", "version": 1},
        ]
    }

    # ensure the folder exists before we attempt to write to it
    if not os.path.exists(query_dir):
        try:
            os.makedirs(query_dir)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise

    with open(query_file, "w") as f:
        json.dump(query_json, f)

    cmdline = cmd(cmd_args, working_dir, env)
    if "stdout" in cmdline and len(cmdline["stdout"]) > 0:
        N10X.Editor.LogToBuildOutput(cmdline["stdout"])
        print(cmdline["stdout"])

    result = {
        "stdout": cmdline["stdout"],
        "stderr": cmdline["stderr"],
        "error_code": cmdline["error_code"],
        "exe": None,
        "sln": None,
        "pdb": None,
    }

    index_json = None
    # read file api reply
    for root, dirs, files in os.walk(reply_dir):
        for file in files:
            # find the index file
            if re.match("^(index-.+[.]json)$", file):
                index_json = file
                break

    if index_json == None or len(index_json) <= 0:
        print(
            "No index.json file found in reply directory\n{0}!\nMake sure you're running an up to date version of CMake".format(
                reply_dir
            )
        )
        return result

    index_path = norm_path_fslash(os.path.join(reply_dir, index_json))
    index_data = read_json_file(index_path)
    generator_data = index_data["cmake"]["generator"]
    generator = generator_data["name"] if "name" in generator_data else None
    platform = generator_data["platform"] if "platform" in generator_data else None

    # Read "objects" which includes all the json file responses
    objects_data = index_data["objects"]

    cache_json_obj = dict()
    codemodel_json_obj = dict()
    cmakefiles_json_obj = dict()
    toolchains_json_obj = dict()

    for obj in objects_data:
        kind = obj["kind"]
        if kind.startswith("cache"):
            cache_json_obj = obj
        elif kind.startswith("codemodel"):
            codemodel_json_obj = obj
        elif kind.startswith("cmakeFiles"):
            cmakefile_json_obj = obj
        elif kind.startswith("toolchains"):
            toolchains_json_obj = obj

    potential_targets = []

    if len(codemodel_json_obj["jsonFile"]) > 0:
        codemodel_path = norm_path_fslash(
            os.path.join(reply_dir, codemodel_json_obj["jsonFile"])
        )
        codemodel_data = read_json_file(codemodel_path)
        source_dir = codemodel_data["paths"]["source"]
        configuration_data = codemodel_data["configurations"]
        for obj in configuration_data:
            config_name = obj["name"]  # Debug, Release, RelWithDebInfo, MinSizeRel
            targets_data = obj["targets"]
            main_project_data = obj["projects"][0]
            project_name = main_project_data["name"]
            target_obj = dict()

            for target in targets_data:
                if target["name"] == project_name:
                    target_obj = target
                    potential_targets.append(target)
                    break

    # find a target which has an .exe path which exists and matches
    # the internal project_name
    # assume the most recent is the actual build
    mtime = 0
    newest_target = None
    newest_pdb = None
    project_name = None
    for target in potential_targets:
        target_path = norm_path_fslash(os.path.join(reply_dir, target["jsonFile"]))
        target_data = read_json_file(target_path)
        artifacts = target_data["artifacts"]
        executable_obj = artifacts[0]
        pdb_obj = None
        if len(artifacts) > 1:
            pdb_obj = artifacts[1]
        exe = norm_path_fslash(os.path.join(build_dir, executable_obj["path"]))
        if pdb_obj != None:
            pdb = norm_path_fslash(os.path.join(build_dir, pdb_obj["path"]))
        if exists(exe):
            exe_mtime = os.path.getmtime(exe)
            if exe_mtime > mtime:
                mtime = exe_mtime
                newest_target = exe
                newest_pdb = pdb
                project_name = target["name"]

    project_exe = newest_target
    if newest_target and len(newest_target) > 0:
        N10X.Editor.SetWorkspaceSetting("RunCommand", project_exe)
        N10X.Editor.SetWorkspaceSetting("DebugCommand", project_exe)
        N10X.Editor.SetWorkspaceSetting("ExePath", project_exe)
    else:
        N10X.Editor.SetWorkspaceSetting("RunCommand", "")
        N10X.Editor.SetWorkspaceSetting("DebugCommand", "")
        N10X.Editor.SetWorkspaceSetting("ExePath", "")

    # find an sln if there is one, use the most recently changed
    newest_sln = None
    exact_sln = None
    mtime_sln = 0
    likely_sln_name = project_name + ".sln"

    for root, dirs, files in os.walk(build_dir):
        for file in files:
            if file.endswith(".sln"):
                sln_path = norm_path_fslash(os.path.join(root, file))
                file_mtime = os.path.getmtime(sln_path)
                if file_mtime > mtime_sln:
                    mtime_sln = file_mtime
                    newest_sln = sln_path
                if file.endswith(likely_sln_name):
                    exact_sln = sln_path
                    break

    if exact_sln != None:
        newest_sln = exact_sln

    if newest_sln and len(newest_sln) > 0:
        N10X.Editor.SetWorkspaceSetting("DebugSln", newest_sln)
    else:
        N10X.Editor.SetWorkspaceSetting("DebugSln", "")

    result["exe"] = newest_target
    result["sln"] = newest_sln
    result["pdb"] = newest_pdb
    return result


def write10xWorkspace(
    outpath,
    build_cmd,
    rebuild_cmd,
    buildfile_cmd,
    clean_cmd,
    buildworkingdirectory_cmd,
    cancelbuild_cmd,
    runcommand_cmd,
    runcommandworkingdirectory_cmd,
    debug_cmd,
    exepath,
    debugsln,
    configlist=[],
    platformlist=[],
):

    root = ET.Element("N10X")
    doc = ET.SubElement(root, "Workspace")

    ET.SubElement(doc, "IncludeFilter").text = "*.*"
    ET.SubElement(doc, "ExcludeFilter").text = (
        "*.obj,*.lib,*.pch,*.dll,*.pdb,.vs,Debug,Release,x64,obj,*.user,Intermediate,*.vcxproj,*.vcxproj.filters"
    )
    ET.SubElement(doc, "SyncFiles").text = "true"
    ET.SubElement(doc, "Recursive").text = "true"
    ET.SubElement(doc, "ShowEmptyFolders").text = "true"
    ET.SubElement(doc, "IsVirtual").text = "false"
    ET.SubElement(doc, "IsFolder").text = "false"
    ET.SubElement(doc, "BuildCommand").text = build_cmd
    ET.SubElement(doc, "RebuildCommand").text = rebuild_cmd
    ET.SubElement(doc, "BuildFileCommand").text = buildfile_cmd
    ET.SubElement(doc, "CleanCommand").text = clean_cmd
    ET.SubElement(doc, "BuildWorkingDirectory").text = buildworkingdirectory_cmd
    ET.SubElement(doc, "CancelBuild").text = cancelbuild_cmd
    ET.SubElement(doc, "RunCommand").text = runcommand_cmd
    ET.SubElement(doc, "RunCommandWorkingDirectory").text = (
        runcommandworkingdirectory_cmd
    )
    ET.SubElement(doc, "DebugCommand").text = debug_cmd
    ET.SubElement(doc, "ExePathCommand").text = exepath
    ET.SubElement(doc, "DebugSln").text = debugsln
    ET.SubElement(doc, "UseVisualStudioEnvBat").text = "true"
    # A bit of extra XML
    ET.SubElement(doc, "UseCMake").text = "true"

    config_element = ET.SubElement(doc, "Configurations")
    for config in configlist:
        ET.SubElement(config_element, "Configuration").text = config

    platform_element = ET.SubElement(doc, "Platforms")
    for platform in platformlist:
        ET.SubElement(platform_element, "Platform").text = platform

    additional_include_paths = ET.SubElement(doc, "AdditionalIncludePaths")
    ET.SubElement(additional_include_paths, "AdditionalIncludePath")
    ET.SubElement(doc, "Defines")
    # TODO: pretty print
    tree = ET.ElementTree(root)
    xml_text = ET.tostring(root, xml_declaration=True).decode()

    f = None
    try:
        f = open(outpath, "x")
    except IOError:
        print(outpath + " already exists")
    else:
        print("Writing CMake Workspace: " + outpath)
        f.write(xml_text)
    finally:
        if f:
            f.close()


def IsCMakeDirectory(directory) -> bool:
    return exists(norm_path_fslash(os.path.join(directory, "CMakeLists.txt")))


def IsCMakeCacheDirectory(directory) -> bool:
    return exists(norm_path_fslash(os.path.join(directory, "CMakeCache.txt")))


def IsCMakePresetDirectory(directory) -> bool:
    return exists(norm_path_fslash(os.path.join(directory, "CMakePresets.json")))


def IsCMakeSettingsDirectory(directory) -> bool:
    return exists(norm_path_fslash(os.path.join(directory, "CMakeSettings.json")))


def CMakeProjectName(cache_directory) -> str:
    project_name = None
    if len(cache_directory):
        process = subprocess.Popen(
            [
                "findstr",
                "CMAKE_PROJECT_NAME",
                norm_path_fslash(os.path.join(cache_directory, "CMakeCache.txt")),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            # cwd=cmakefolder,
            encoding="utf8",
        )
        returncode = process2.wait()
        result = process2.stdout.read()
        r = re.search(r"=(.*)$", result)
        if r != None:
            project_name = r.group(1)
    return project_name


def CMakeBuildThreaded(args: dict):
    print(json.dumps(args, indent="\t"))

    preset_exists = args["preset_exists"]
    user_preset_exists = args["user_preset_exists"]
    settings_exists = args["settings_exists"]
    directory = args["directory"]
    version = args["version"]
    n10x_config = args["config"]
    n10x_platform = args["platform"]
    verbose = args["verbose"]
    CMake_EXE = args["cmake"]
    vcvarsall = args["vcvarsall"]
    build_args = args["build_args"]
    rebuild_args = args["rebuild_args"]
    rebuild = args["rebuild"]

    print("CMake Build Detected: Using Python")

    n10x_macros = {"$(Configuration)": n10x_config, "$(Platform)": n10x_platform}

    extra_cmd_args = []
    if rebuild:
        extra_cmd_args = rebuild_args
    else:
        extra_cmd_args = build_args

    print("10x macro expansion:")
    extra_cmd_args = macro_expand_n10x(extra_cmd_args, n10x_macros)
    print(json.dumps(extra_cmd_args, indent="\t"))

    arg_json_path = os.path.join(directory, "cmake_build.json")
    with open(arg_json_path, "w") as arg_json:
        json.dump(args, arg_json, indent="\t")

    build_name = n10x_platform + "-" + n10x_config
    N10X.Editor.LogToBuildOutput(
        "----- Build {} {} -----\n".format(n10x_config, n10x_platform)
    )

    if (preset_exists or user_preset_exists) and version["preset_support"]:
        print("CMake Macro Expansion: ...")
        print("Preset Mode:")
        # TODO detect and parse command line to pass into this function
        data = cmake_prep(directory, None, extra_cmd_args, True, False)

        if "error" in data and data["error"]:
            if "error_message" in data:
                N10X.Editor.LogToBuildOutput("{0}\n".format(data["error_message"]))
            if "configure_error_message" in data:
                N10X.Editor.LogToBuildOutput(
                    "{0}\n".format(data["configure_error_message"])
                )
            if "build_error_message" in data:
                N10X.Editor.LogToBuildOutput(
                    "{0}\n".format(data["build_error_message"])
                )
            if "test_error_message" in data:
                N10X.Editor.LogToBuildOutput("{0}\n".format(data["test_error_message"]))
            if "package_error_message" in data:
                N10X.Editor.LogToBuildOutput(
                    "{0}\n".format(data["package_error_message"])
                )
            if "workflow_error_message" in data:
                N10X.Editor.LogToBuildOutput(
                    "{0}\n".format(data["workflow_error_message"])
                )
            N10X.Editor.LogToBuildOutput("----- CMake Build Failed -----\n")
            N10X.Editor.OnBuildFinished(False)
            return True

        builds = []
        configs = []

        if "buildPresets" in data:
            builds = data["buildPresets"]

        if "configurePresets" in data:
            configs = data["configurePresets"]

        if type(builds) != list:
            N10X.Editor.OnBuildFinished(False)
            return True
        # easy build, we'll automatically pick the configurePreset name to go with a buildPreset
        cmake_config_name = None
        cmake_build_name = None
        cmake_config_obj = {}

        for build in builds:
            if build["name"] == build_name:
                cmake_build_name = build["name"]
                cmake_config_name = build["configurePreset"]
                break
        # failed to find a matching $(Configuration)-$(Platform) build now look for just $(Configuration)
        if cmake_build_name == None:
            for build in builds:
                if build["name"] == n10x_config:
                    cmake_build_name = build["name"]
                    cmake_config_name = build["configurePreset"]
                    break
        # try to find case insensitive versions as fallback
        if cmake_build_name == None:
            low_build_name = build_name.lower()
            for build in builds:
                if build["name"].lower() == low_build_name:
                    cmake_build_name = build["name"]
                    cmake_config_name = build["configurePreset"]
                    break
        if cmake_build_name == None:
            low_n10x_config = n10x_config.lower()
            for build in builds:
                if build["name"].lower() == low_n10x_config:
                    cmake_build_name = build["name"]
                    cmake_config_name = build["configurePreset"]
                    break

        if cmake_config_name == None:
            for config in configs:
                if config["name"] == build_name:
                    cmake_config_name = config["name"]
                    cmake_config_obj = config
                    break
            if cmake_config_name == None:
                for config in configs:
                    if config["name"] == n10x_config:
                        cmake_config_name = config["name"]
                        cmake_config_obj = config
                        break
            # try to find case insensitive versions as fallback
            if cmake_config_name == None:
                low_build_name = build_name.lower()
                for config in configs:
                    if config["name"].lower() == low_build_name:
                        cmake_config_name = config["name"]
                        cmake_config_obj = config
                        break
            if cmake_config_name == None:
                low_n10x_config = n10x_config.lower()
                for config in configs:
                    if config["name"].lower() == low_n10x_config:
                        cmake_config_name = config["name"]
                        cmake_config_obj = config
                        break
        else:  # found a matching buildPreset, now find the configPreset
            for config in configs:
                if config["name"] == cmake_config_name:
                    cmake_config_obj = config
                    break
            # if we don't find a match here, strictly speaking this is a badly configured CMakePresets.json

        # TODO? Nearest config/preset name (did you mean) feedback?
        if cmake_config_name == None:
            N10X.Editor.LogToBuildOutput(
                "Failed to find a build or config preset in CMakePresets.json for: {0} and {1}\n".format(
                    build_name, n10x_config
                )
            )
            N10X.Editor.LogToBuildOutput("----- CMake Build Failed -----\n")
            N10X.Editor.OnBuildFinished(False)
            return True

        cmake_macros = {}
        if "macros" in data:
            cmake_macros = data["macros"]
            cmake_macros["${presetName}"] = cmake_config_name

        # update the config and update by expanding presetName
        cmake_config_obj = macro_expand_any(cmake_config_obj, cmake_macros)

        if verbose:
            print(json.dumps(cmake_config_obj, indent="\t"))

        # build_directory_path = norm_path_fslash(os.path.join(directory, "out\\build", cmake_build_name))
        build_directory_path = None
        if "binaryDir" in cmake_config_obj:
            build_directory_path = cmake_config_obj["binaryDir"]
        elif cmake_config_name != None:
            build_directory_path = norm_path_fslash(
                os.path.join(directory, "out\\build", cmake_config_name)
            )  # fallback if one wasn't defined in the preset

        config_args = [CMake_EXE, "-S", directory]
        if build_directory_path != None and len(build_directory_path) > 0:
            config_args.append("-B")
            config_args.append(build_directory_path)
        # see cmake ide integration guide
        if (
            "entries" in data and data["entries"] and len(data["entries"]) > 0
        ) or "cacheVariables" in cmake_config_obj:
            # initial_cache_path = norm_path_fslash(os.path.join(directory, "10x_initial_cache.json"))
            # write_json_file(initial_cache_path, data["entries"])

            initial_cache_script_path = norm_path_fslash(
                os.path.join(directory, "10x_initial_cache.cmake")
            )
            cmake_vars = {}

            # cacheVariables gets filled out with variables via cmake_prep from commandline
            # if "entries" in data and data["entries"] and len(data["entries"]) > 0:
            #    for cache_var in data["entries"]:
            #        cmake_vars[cache_var["name"]] = cache_var
            if "cacheVariables" in cmake_config_obj:
                for k in cmake_config_obj["cacheVariables"]:
                    cmake_vars[k] = {
                        "name": k,
                        "value": cmake_config_obj["cacheVariables"][k],
                    }

            with open(initial_cache_script_path, "w") as cache_script:
                for k in cmake_vars:
                    if "type" in cmake_vars[k] and cmake_vars[k]["type"] != None:
                        if type(cmake_vars[k]["value"]) == str:
                            cache_script.write(
                                'set({0} "{1}" CACHE {2} "")\n'.format(
                                    k,
                                    escape_bslash(cmake_vars[k]["value"]),
                                    cmake_vars[k]["type"],
                                )
                            )
                        elif type(cmake_vars[k]["value"]) == bool:
                            cache_script.write(
                                'set({0} "{1}" CACHE {2} "")\n'.format(
                                    k,
                                    "true" if cmake_vars[k]["value"] else "false",
                                    cmake_vars[k]["type"],
                                )
                            )
                    else:
                        if type(cmake_vars[k]["value"]) == str:
                            cache_script.write(
                                'set({0} "{1}" CACHE STRING "")\n'.format(
                                    k, escape_bslash(cmake_vars[k]["value"])
                                )
                            )
                        elif type(cmake_vars[k]["value"]) == bool:
                            cache_script.write(
                                'set({0} "{1}" CACHE STRING "")\n'.format(
                                    k, "true" if cmake_vars[k]["value"] else "false"
                                )
                            )

            config_args.append("-C")
            config_args.append(initial_cache_script_path)

        config_args.append("--preset")
        config_args.append(cmake_config_name)
        if rebuild:
            config_args.append("--fresh")

        N10X.Editor.LogToBuildOutput(" ".join(config_args))
        N10X.Editor.LogToBuildOutput("\n")

        arch = "x64"
        if (
            "architecture" in cmake_config_obj
            and "value" in cmake_config_obj["architecture"]
        ):
            arch = cmake_config_obj["architecture"]["value"]

        env = cmake_env(vcvarsall, directory, arch)

        config_result = cmake_configure(config_args, directory, env)
        build_dir = config_result["build_dir"]
        if config_result["error_code"] == 0 and build_dir and len(build_dir):
            if (
                cmake_build_name != None
            ):  # trust cmake's --preset command to build until we have full cmake parsing support
                build_args = [CMake_EXE, "--build", "--preset", cmake_build_name]
            else:
                build_args = [CMake_EXE, "--build", build_dir]

            N10X.Editor.LogToBuildOutput(" ".join(build_args))
            N10X.Editor.LogToBuildOutput("\n")
            exe_path = cmake_build(build_args, directory, build_dir, env)
            if exe_path["error_code"] != 0:
                N10X.Editor.LogToBuildOutput("----- CMake Build Failed -----\n")
                N10X.Editor.OnBuildFinished(False)
                return True
        else:
            N10X.Editor.LogToBuildOutput("----- CMake Build Failed -----\n")
            N10X.Editor.OnBuildFinished(False)
            return True
    elif settings_exists:
        print("CMake Macro Expansion: ...")
        print("Settings Mode:")
        # TODO detect and parse command line to pass into this function
        data = cmake_prep(directory, None, extra_cmd_args, False, True)

        cmake_config_name = None
        cmake_config_obj = {}

        configs = []
        if "configurations" in data:
            configs = data["configurations"]

        for config in configs:
            if config["name"] == build_name:
                cmake_config_name = config["name"]
                cmake_config_obj = config
                break
        if cmake_config_name == None:
            for config in configs:
                if config["name"] == n10x_config:
                    cmake_config_name = config["name"]
                    cmake_config_obj = config
                    break
        # try to find case insensitive versions as fallback
        if cmake_config_name == None:
            low_build_name = build_name.lower()
            for config in configs:
                if config["name"].lower() == low_build_name:
                    cmake_config_name = config["name"]
                    cmake_config_obj = config
                    break
        if cmake_config_name == None:
            low_n10x_config = n10x_config.lower()
            for config in configs:
                if config["name"].lower() == low_n10x_config:
                    cmake_config_name = config["name"]
                    cmake_config_obj = config
                    break

        # TODO? Nearest config/preset name (did you mean) feedback?
        if cmake_config_name == None:
            N10X.Editor.LogToBuildOutput(
                "Failed to find configuration in CMakeSettings.json for: {0} and {1}\n".format(
                    build_name, n10x_config
                )
            )
            N10X.Editor.OnBuildFinished(False)
            return True

        cmake_macros = {}
        if "macros" in data:
            cmake_macros = data["macros"]
            cmake_macros["${name}"] = cmake_config_name

        # update the config and update by expanding presetName
        cmake_config_obj = macro_expand_any(cmake_config_obj, cmake_macros)
        if verbose:
            print(json.dumps(cmake_config_obj, indent="\t"))

        build_directory_path = None
        if "buildRoot" in cmake_config_obj:
            build_directory_path = cmake_config_obj["buildRoot"]
        elif cmake_config_name != None:
            build_directory_path = norm_path_fslash(
                os.path.join(directory, "out\\build", cmake_config_name)
            )

        # TODO: read CMakeSettings.json? get --Config setting?
        # "-S", directory, "-B", build_directory_path,
        config_args = [CMake_EXE, "-S", directory, "-B", build_directory_path]
        if "generator" in cmake_config_obj:
            config_args.append("-G")
            config_args.append(cmake_config_obj["generator"])
        if (
            "entries" in data and data["entries"] and len(data["entries"]) > 0
        ) or "cacheVariables" in cmake_config_obj:
            initial_cache_script_path = norm_path_fslash(
                os.path.join(directory, "10x_initial_cache.cmake")
            )
            cmake_vars = {}

            if "entries" in data and data["entries"] and len(data["entries"]) > 0:
                for cache_var in data["entries"]:
                    cmake_vars[cache_var["name"]] = cache_var
            if "cacheVariables" in cmake_config_obj:
                for k in cmake_config_obj["cacheVariables"]:
                    cmake_vars[k] = cmake_config_obj["cacheVariables"][k]

            with open(initial_cache_script_path, "w") as cache_script:
                for k in cmake_vars:
                    if "type" in cmake_vars[k] and cmake_vars[k]["type"] != None:
                        if type(cmake_vars[k]["value"]) == str:
                            cache_script.write(
                                'set({0} "{1}" CACHE {2} "")\n'.format(
                                    k,
                                    escape_bslash(cmake_vars[k]["value"]),
                                    cmake_vars[k]["type"],
                                )
                            )
                        elif type(cmake_vars[k]["value"]) == bool:
                            cache_script.write(
                                'set({0} "{1}" CACHE {2} "")\n'.format(
                                    k,
                                    "true" if cmake_vars[k]["value"] else "false",
                                    cmake_vars[k]["type"],
                                )
                            )
                    else:
                        if type(cmake_vars[k]["value"]) == str:
                            cache_script.write(
                                'set({0} "{1}" CACHE STRING "")\n'.format(
                                    k, escape_bslash(cmake_vars[k]["value"])
                                )
                            )
                        elif type(cmake_vars[k]["value"]) == bool:
                            cache_script.write(
                                'set({0} "{1}" CACHE STRING "")\n'.format(
                                    k, "true" if cmake_vars[k]["value"] else "false"
                                )
                            )

            config_args.append("-C")  # see cmake ide integration guide
            config_args.append(initial_cache_script_path)
        if rebuild:
            config_args.append("--fresh")

        N10X.Editor.LogToBuildOutput(" ".join(config_args))
        N10X.Editor.LogToBuildOutput("\n")

        arch = "x64"
        if (
            "architecture" in cmake_config_obj
            and "value" in cmake_config_obj["architecture"]
        ):
            arch = cmake_config_obj["architecture"]["value"]

        env = cmake_env(vcvarsall, directory, arch)

        config_result = cmake_configure(config_args, directory, env)
        build_dir = config_result["build_dir"]
        if config_result["error_code"] == 0 and build_dir and len(build_dir):
            build_args = [
                CMake_EXE,
                "--build",
                build_dir,
                "--config",
                cmake_config_name,
            ]

            N10X.Editor.LogToBuildOutput(" ".join(build_args))
            N10X.Editor.LogToBuildOutput("\n")
            exe_path = cmake_build(build_args, directory, build_dir, env)
            if exe_path["error_code"] != 0:
                N10X.Editor.LogToBuildOutput("----- CMake Build Failed -----\n")
                N10X.Editor.OnBuildFinished(False)
                return True
        else:
            N10X.Editor.LogToBuildOutput("----- CMake Build Failed -----\n")
            N10X.Editor.OnBuildFinished(False)
            return True
    else:
        print("No Preset/Settings Mode:")
        # TODO detect and parse command line to pass into this function
        data = cmake_prep(directory, None, extra_cmd_args, False, False)
        if verbose:
            print(json.dumps(data, indent="\t"))

        build_directory_path = norm_path_fslash(
            os.path.join(directory, "out\\build", n10x_config)
        )

        config_args = [CMake_EXE, "-S", directory, "-B", build_directory_path]

        if "entries" in data and data["entries"] and len(data["entries"]) > 0:
            initial_cache_script_path = norm_path_fslash(
                os.path.join(directory, "10x_initial_cache.cmake")
            )
            cmake_vars = {}

            if "entries" in data and data["entries"] and len(data["entries"]) > 0:
                for cache_var in data["entries"]:
                    cmake_vars[cache_var["name"]] = cache_var

            with open(initial_cache_script_path, "w") as cache_script:
                for k in cmake_vars:
                    if "type" in cmake_vars[k] and cmake_vars[k]["type"] != None:
                        if type(cmake_vars[k]["value"]) == str:
                            cache_script.write(
                                'set({0} "{1}" CACHE {2} "")\n'.format(
                                    k,
                                    escape_bslash(cmake_vars[k]["value"]),
                                    cmake_vars[k]["type"],
                                )
                            )
                        elif type(cmake_vars[k]["value"]) == bool:
                            cache_script.write(
                                'set({0} "{1}" CACHE {2} "")\n'.format(
                                    k,
                                    "true" if cmake_vars[k]["value"] else "false",
                                    cmake_vars[k]["type"],
                                )
                            )
                    else:
                        if type(cmake_vars[k]["value"]) == str:
                            cache_script.write(
                                'set({0} "{1}" CACHE STRING "")\n'.format(
                                    k, escape_bslash(cmake_vars[k]["value"])
                                )
                            )
                        elif type(cmake_vars[k]["value"]) == bool:
                            cache_script.write(
                                'set({0} "{1}" CACHE STRING "")\n'.format(
                                    k, "true" if cmake_vars[k]["value"] else "false"
                                )
                            )

            config_args.append("-C")  # see cmake ide integration guide
            config_args.append(initial_cache_script_path)

        if rebuild:
            config_args.append("--fresh")

        N10X.Editor.LogToBuildOutput(" ".join(config_args))
        N10X.Editor.LogToBuildOutput("\n")

        arch = "x64"
        if (
            "architecture" in cmake_config_obj
            and "value" in cmake_config_obj["architecture"]
        ):
            arch = cmake_config_obj["architecture"]["value"]

        env = cmake_env(vcvarsall, directory, arch)

        config_result = cmake_configure(config_args, directory, env)
        build_dir = config_result["build_dir"]
        if config_result["error_code"] == 0 and build_dir and len(build_dir):
            build_args = [CMake_EXE, "--build", build_dir]
            N10X.Editor.LogToBuildOutput(" ".join(build_args))
            N10X.Editor.LogToBuildOutput("\n")
            exe_path = cmake_build(build_args, directory, build_dir)
            if exe_path["error_code"] != 0:
                N10X.Editor.LogToBuildOutput("----- CMake Build Failed -----\n")
                N10X.Editor.OnBuildFinished(False)
                return True
        else:
            N10X.Editor.LogToBuildOutput("----- CMake Build Failed -----\n")
            N10X.Editor.OnBuildFinished(False)
            return True

    N10X.Editor.LogToBuildOutput("----- CMake Build Complete -----\n")
    N10X.Editor.OnBuildFinished(True)
    return True  # intercept build command


def CMakeBuildStarted(filename: str, rebuild: bool = False):
    do_build = get_10x_bool_setting("CMake.HookBuild")
    if not do_build:
        print("CMake: ignoring build command (set CMake.HookBuild to true)")
        return False

    global CMake_EXE
    global vcvarsall
    global verbose
    global version

    txworkspace = N10X.Editor.GetWorkspaceFilename()
    directory, filename = split(txworkspace)  # os.path.split

    paths = cmake_paths(directory)
    paths_exist = cmake_verify_paths(paths)

    n10x_build_cmd = N10X.Editor.GetWorkspaceSetting("BuildCommand")
    n10x_rebuild_cmd = N10X.Editor.GetWorkspaceSetting("RebuildCommand")

    build_args = shlex.split(n10x_build_cmd)  # parse_cmd(n10x_build_cmd)
    rebuild_args = shlex.split(n10x_rebuild_cmd)  # parse_cmd(n10x_rebuild_cmd)

    build_dir = None
    print("Checking for CMake build...")
    if paths_exist["lists"]:
        use_threads = True
        parameters = {
            "directory": directory,
            "preset_exists": paths_exist["preset"],
            "user_preset_exists": paths_exist["userpreset"],
            "settings_exists": paths_exist["settings"],
            "version": version,
            "config": N10X.Editor.GetWorkspaceBuildConfig(),
            "platform": N10X.Editor.GetWorkspaceBuildPlatform(),
            "verbose": verbose,
            "cmake": CMake_EXE,
            "build_args": build_args,
            "rebuild_args": rebuild_args,
            "rebuild": rebuild,
            "vcvarsall": vcvarsall,
        }

        if use_threads:
            build_thread = Thread(
                target=CMakeBuildThreaded,
                args=[parameters],
            )
            build_thread.start()
        else:
            CMakeBuildThreaded(parameters)
        return True
    else:
        print("No CMake related files found...")
        N10X.Editor.OnBuildFinished(False)
        return False


def OnCMakeRebuildStarted(filename: str) -> bool:
    return CMakeBuildStarted(filename, True)


def OnCMakeBuildStarted(filename: str) -> bool:
    return CMakeBuildStarted(filename, False)


def OnCMakeBuildFinished(build_result: bool):
    N10X.Editor.LogToBuildOutput(
        "----- CMake OK  -----\n" if build_result else "----- CMake FAIL  -----\n"
    )
    return


def OnCMakeSettingsChanged():
    global verbose
    verbose = get_10x_bool_setting("CMake.Verbose")

    global CMake_EXE
    CMake_EXE = get_10x_exe_path("CMake.Path", "cmake")
    if verbose and CMake_EXE != None:
        print(CMake_EXE)

    global version
    version = cmake_version()

    txworkspace = N10X.Editor.GetWorkspaceFilename()
    directory, filename = split(txworkspace)  # os.path.split

    global vcvarsall
    vcvarsall = get_10x_cmdpath("CMake.vcvarsall", "vcvarsall.bat", ".bat")
    if vcvarsall == None or not (len(vcvarsall) > 0):
        vswhere_result = cmd(
            [
                "C:/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe",
                "-legacy",
                "-prerelease",
                "-format",
                "json",
            ],
            directory,
        )
        if vswhere_result["error_code"] == 0 and type(vswhere_result["stdout"]) == str:
            vswhere_json = json.loads(vswhere_result["stdout"])
            for vsinstall_obj in vswhere_json:
                vsinstall = vsinstall_obj["installationPath"]
                vcvarsall_check = norm_path_fslash(
                    os.path.join(vsinstall, "Common7\\Tools\\vcvarsall.bat")
                )
                print(vcvarsall_check)
                if exists(vcvarsall_check):
                    vcvarsall = vcvarsall_check
                    break
                vcvarsall_check = norm_path_fslash(
                    os.path.join(vsinstall, "VC\\Auxiliary\\Build\\vcvarsall.bat")
                )
                print(vcvarsall_check)
                if exists(vcvarsall_check):
                    vcvarsall = vcvarsall_check
                    break
    if verbose and vcvarsall != None:
        print(vcvarsall)

    global CMake_GUI
    CMake_GUI = get_10x_exe_path("CMake.GuiPath", "cmake-gui")
    if verbose and CMake_GUI != None:
        print(CMake_GUI)

    return


def IsOldWorkspace() -> bool:
    build_cmd = N10X.Editor.GetWorkspaceSetting("BuildCommand")
    rebuild_cmd = N10X.Editor.GetWorkspaceSetting("RebuildCommand")
    build_file_cmd = N10X.Editor.GetWorkspaceSetting("BuildFileCommand")
    clean_cmd = N10X.Editor.GetWorkspaceSetting("CleanCommand")
    build_working_dir_cmd = N10X.Editor.GetWorkspaceSetting("BuildWorkingDirectory")
    cancel_build_cmd = N10X.Editor.GetWorkspaceSetting("CancelBuild")
    run_command_cmd = N10X.Editor.GetWorkspaceSetting("RunCommand")
    run_working_directory_cmd = N10X.Editor.GetWorkspaceSetting("RunWorkingDirectory")
    debug_cmd = N10X.Editor.GetWorkspaceSetting("DebugCommand")
    exe_path_path = N10X.Editor.GetWorkspaceSetting("ExePath")
    debug_sln_path = N10X.Editor.GetWorkspaceSetting("DebugSln")

    return (
        len(build_cmd) > 0
        or len(rebuild_cmd) > 0
        or len(build_file_cmd) > 0
        or len(clean_cmd) > 0
        or len(build_working_dir_cmd) > 0
        or len(cancel_build_cmd) > 0
        or len(run_command_cmd) > 0
        or len(run_working_directory_cmd) > 0
        or len(debug_cmd) > 0
        or len(exe_path_path) > 0
        or len(debug_sln_path) > 0
    )


def cmake_condition(preset_configs: list) -> list:
    non_hidden_configs = []
    for preset in preset_configs:
        if "hidden" in preset and preset["hidden"] == "true":
            continue
        if "condition" in preset:
            condition = preset["condition"]
            if condition["type"] is str and condition["type"].lower() == "equals":
                if condition["lhs"] != condition["rhs"]:
                    continue
            if condition["type"] is str and condition["type"].lower() == "notEquals":
                if condition["lhs"] == condition["rhs"]:
                    continue
            # TODO: other conditions
        non_hidden_configs.append(preset)
    return non_hidden_configs


def ScanCMakeWorkspaces(args: dict):
    project_files = args["project_files"]
    cmake_preset_build = args["cmake_preset_build"]
    cmake_preset_rebuild = args["cmake_preset_rebuild"]
    cmake_preset_run = args["cmake_preset_run"]
    cmake_preset_debug = args["cmake_preset_debug"]

    cmake_settings_build = args["cmake_settings_build"]
    cmake_settings_rebuild = args["cmake_settings_rebuild"]
    cmake_settings_run = args["cmake_settings_run"]
    cmake_settings_debug = args["cmake_settings_debug"]

    cmake_empty_build = args["cmake_empty_build"]
    cmake_empty_rebuild = args["cmake_empty_rebuild"]
    cmake_empty_run = args["cmake_empty_run"]
    cmake_empty_debug = args["cmake_empty_debug"]
    version = args["version"]
    verbose = args["verbose"]

    for project_file in project_files:
        if project_file.endswith("CMakeLists.txt"):
            cmakelists_exists = True
            cmakefolder = project_file[: -len("CMakeLists.txt")]
            project_paths = cmake_paths(cmakefolder)
            project_paths_exist = cmake_verify_paths(project_paths)

            if (
                project_paths_exist["preset"] or project_paths_exist["userpreset"]
            ) and version["preset_support"]:
                data = cmake_prep(
                    cmakefolder,
                    "$(RootWorkspaceDirectory)/out/build/$(Platform)-$(Configuration)",
                    [],
                    True,
                    False,
                )
                if verbose:
                    print(data)
                # data = read_json_file(presetpath)

                preset_version = data["version"]
                preset_configs = data["configurePresets"]
                build_configs = data["buildPresets"]

                non_hidden_configs = cmake_condition(preset_configs)
                non_hidden_build_configs = cmake_condition(build_configs)

                build_list_results = []
                for build_preset in non_hidden_configs:
                    if not build_preset["name"] in build_list_results:
                        build_list_results.append(build_preset["name"])
                for build_preset in non_hidden_build_configs:
                    if not build_preset["name"] in build_list_results:
                        build_list_results.append(build_preset["name"])

                workspace_file = norm_path_fslash(
                    os.path.join(cmakefolder, "cmakepreset.10x")
                )
                write10xWorkspace(
                    workspace_file,
                    cmake_preset_build,
                    cmake_preset_rebuild,
                    "",
                    "",
                    "",
                    "",
                    cmake_preset_run,
                    "",
                    cmake_preset_debug,
                    cmake_preset_run,
                    "",
                    build_list_results,
                    [],
                )
            elif project_paths_exist["settings"]:
                # TODO: parse json from CMakeSettings.json
                # data = read_json_file(settingspath)
                data = cmake_prep(
                    cmakefolder,
                    "$(RootWorkspaceDirectory)/out/build/$(Configuration)",
                    [],
                    False,
                    True,
                )
                if verbose:
                    print(data)

                configuration_list = data["configurations"]
                configurations = []
                for json_object in configuration_list:
                    configurations.append(json_object["name"])

                # print("Writing "+cmakefolder+"cmakesettings.10x")
                workspace_file = norm_path_fslash(
                    os.path.join(cmakefolder, "cmakesettings.10x")
                )
                write10xWorkspace(
                    workspace_file,
                    cmake_settings_build,
                    cmake_settings_rebuild,
                    "",
                    "",
                    "",
                    "",
                    cmake_settings_run,
                    "",
                    cmake_settings_debug,
                    cmake_settings_run,
                    "",
                    configurations,
                    [],
                )
            else:
                # print("Writing "+cmakefolder+"cmake.10x")
                workspace_file = norm_path_fslash(
                    os.path.join(cmakefolder, "cmake.10x")
                )
                write10xWorkspace(
                    workspace_file,
                    cmake_empty_build,
                    cmake_empty_rebuild,
                    "",
                    "",
                    "",
                    "",
                    cmake_empty_run,
                    "",
                    cmake_empty_debug,
                    cmake_empty_run,
                    "",
                    [],
                    [],
                )


def OnCMakeWorkspaceOpened():
    do_workspace = get_10x_bool_setting("CMake.HookWorkspaceOpened")
    if not do_workspace:
        print(
            "CMake: ignoring workspace opened (set CMake.HookWorkspaceOpened == 'true')"
        )
        return False

    global verbose
    global version

    cmakelists_exists = False
    cmakepresets_exists = False
    cmakeuserpresets_exists = False
    cmakesettings_exists = False
    cmakeprojects = {}

    # working from current project
    txworkspace = N10X.Editor.GetWorkspaceFilename()
    directory, filename = split(txworkspace)  # os.path.split

    paths = cmake_paths(directory)
    paths_exist = cmake_verify_paths(paths)

    print("Working Directory uses CMake?: {0}".format(cmakelists_exists))
    print("CMakeLists.txt: {0}".format(paths_exist["lists"]))

    build_cmd = N10X.Editor.GetWorkspaceSetting("BuildCommand")
    rebuild_cmd = N10X.Editor.GetWorkspaceSetting("RebuildCommand")
    build_file_cmd = N10X.Editor.GetWorkspaceSetting("BuildFileCommand")
    clean_cmd = N10X.Editor.GetWorkspaceSetting("CleanCommand")
    build_working_dir_cmd = N10X.Editor.GetWorkspaceSetting("BuildWorkingDirectory")
    cancel_build_cmd = N10X.Editor.GetWorkspaceSetting("CancelBuild")
    run_command_cmd = N10X.Editor.GetWorkspaceSetting("RunCommand")
    run_working_directory_cmd = N10X.Editor.GetWorkspaceSetting("RunWorkingDirectory")
    debug_cmd = N10X.Editor.GetWorkspaceSetting("DebugCommand")
    exe_path_path = N10X.Editor.GetWorkspaceSetting("ExePath")
    debug_sln_path = N10X.Editor.GetWorkspaceSetting("DebugSln")
    platforms = N10X.Editor.GetWorkspaceSetting("Platforms")
    configurations = N10X.Editor.GetWorkspaceSetting("Configurations")

    cmake_preset_build = 'cmake --preset "$(Platform)-$(Configuration)" && cmake --build --preset "$(Platform)-$(Configuration)"'
    cmake_preset_rebuild = 'cmake --preset "$(Platform)-$(Configuration)" --fresh && cmake --build --preset "$(Platform)-$(Configuration)"'
    cmake_preset_run = "$(RootWorkspaceDirectory)/out/build/$(Platform)-$(Configuration)/project_name.exe"
    cmake_preset_debug = "$(RootWorkspaceDirectory)/out/build/$(Platform)-$(Configuration)/project_name.exe"

    cmake_settings_build = 'cmake -S "$(RootWorkspaceDirectory)" -B "$(RootWorkspaceDirectory)/out/build/$(Platform)-$(Configuration)" && cmake --build --config "$(Configuration)"'
    cmake_settings_rebuild = 'cmake -S "$(RootWorkspaceDirectory)" -B "$(RootWorkspaceDirectory)/out/build/$(Platform)-$(Configuration)" --fresh && cmake --build --config "$(Configuration)"'
    cmake_settings_run = "$(RootWorkspaceDirectory)/out/build/#(Platform)-$(Configuration)/project_name.exe"
    cmake_settings_debug = "$(RootWorkspaceDirectory)/out/build/#(Platform)-$(Configuration)/project_name.exe"

    cmake_empty_build = 'cmake -S "$(RootWorkspaceDirectory)" -B "$(RootWorkspaceDirectory)/out/build/$(Configuration)" && cmake --build -S "$(RootWorkspaceDirectory)" -B "$(RootWorkspaceDirectory)/out/build/$(Configuration)"'
    cmake_empty_rebuild = 'cmake -S "$(RootWorkspaceDirectory)" -B "$(RootWorkspaceDirectory)/out/build/$(Configuration)" --fresh && cmake --build -S "$(RootWorkspaceDirectory)" -B "$(RootWorkspaceDirectory)/out/build/$(Configuration)"'
    cmake_empty_run = (
        "$(RootWorkspaceDirectory)/out/build/$(Configuration)/project_name.exe"
    )
    cmake_empty_debug = (
        "$(RootWorkspaceDirectory)/out/build/$(Configuration)/project_name.exe"
    )

    old_workspace = IsOldWorkspace()

    if paths_exist["lists"]:
        # print("Configuring CMake Workspace...")
        if (paths_exist["preset"] or paths_exist["userpreset"]) and version[
            "preset_support"
        ]:
            if not old_workspace:
                N10X.Editor.SetWorkspaceSetting("BuildCommand", cmake_preset_build)
                N10X.Editor.SetWorkspaceSetting("RebuildCommand", cmake_preset_rebuild)
                N10X.Editor.SetWorkspaceSetting("RunCommand", cmake_preset_run)
                N10X.Editor.SetWorkspaceSetting("DebugCommand", cmake_preset_debug)
                N10X.Editor.SetWorkspaceSetting("ExePath", cmake_preset_run)

            data = cmake_prep(
                directory,
                "$(RootWorkspaceDirectory)/out/build/$(Platform)-$(Configuration)",
                [],
                True,
                False,
            )

            preset_configs = data["configurePresets"]
            build_configs = data["buildPresets"]

            non_hidden_configs = cmake_condition(preset_configs)
            non_hidden_build_configs = cmake_condition(build_configs)

            build_list_results = configurations.split(",")
            for build_preset in non_hidden_configs:
                if not build_preset["name"] in build_list_results:
                    build_list_results.append(build_preset["name"])
            for build_preset in non_hidden_build_configs:
                if not build_preset["name"] in build_list_results:
                    build_list_results.append(build_preset["name"])

            N10X.Editor.SetWorkspaceSetting(
                "Configurations", ",".join(build_list_results)
            )

        elif paths_exist["settings"]:
            if not old_workspace:
                N10X.Editor.SetWorkspaceSetting("BuildCommand", cmake_settings_build)
                N10X.Editor.SetWorkspaceSetting("RebuildCommand", cmake_settings_build)
                N10X.Editor.SetWorkspaceSetting("RunCommand", cmake_settings_run)
                N10X.Editor.SetWorkspaceSetting("DebugCommand", cmake_settings_debug)
                N10X.Editor.SetWorkspaceSetting("ExePath", cmake_settings_run)

            data = cmake_prep(
                directory,
                "$(RootWorkspaceDirectory)/out/build/$(Platform)-$(Configuration)",
                [],
                False,
                True,
            )

            configuration_list = data["configurations"]
            build_list_results = configurations.split(",")
            for build_setting in configuration_list:
                if not build_setting["name"] in build_list_results:
                    build_list_results.append(build_setting["name"])

            N10X.Editor.SetWorkspaceSetting(
                "Configurations", ",".join(build_list_results)
            )
        else:
            if not old_workspace:
                N10X.Editor.SetWorkspaceSetting("BuildCommand", cmake_empty_build)
                N10X.Editor.SetWorkspaceSetting("RebuildCommand", cmake_empty_rebuild)
                N10X.Editor.SetWorkspaceSetting("RunCommand", cmake_empty_run)
                N10X.Editor.SetWorkspaceSetting("DebugCommand", cmake_empty_debug)
                N10X.Editor.SetWorkspaceSetting("ExePath", cmake_empty_run)

    # scan through workspace files for other directories
    project_files = N10X.Editor.GetWorkspaceFiles()
    scan_project = Thread(
        target=ScanCMakeWorkspaces,
        args=[
            {
                "project_files": project_files,
                "cmake_preset_build": cmake_preset_build,
                "cmake_preset_rebuild": cmake_preset_rebuild,
                "cmake_preset_run": cmake_preset_run,
                "cmake_preset_debug": cmake_preset_debug,
                "cmake_settings_build": cmake_settings_build,
                "cmake_settings_rebuild": cmake_settings_rebuild,
                "cmake_settings_run": cmake_settings_run,
                "cmake_settings_debug": cmake_settings_debug,
                "cmake_empty_build": cmake_empty_build,
                "cmake_empty_rebuild": cmake_empty_rebuild,
                "cmake_empty_run": cmake_empty_run,
                "cmake_empty_debug": cmake_empty_debug,
                "version": version,
                "verbose": verbose,
            }
        ],
    )
    scan_project.start()


def InitializeCMake():
    N10X.Editor.AddOnSettingsChangedFunction(OnCMakeSettingsChanged)
    N10X.Editor.AddOnWorkspaceOpenedFunction(OnCMakeWorkspaceOpened)
    N10X.Editor.AddProjectBuildFunction(OnCMakeBuildStarted)
    N10X.Editor.AddProjectRebuildFunction(OnCMakeRebuildStarted)
    N10X.Editor.AddBuildFinishedFunction(OnCMakeBuildFinished)


N10X.Editor.CallOnMainThread(InitializeCMake)
