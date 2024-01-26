#------------------------------------------------------------------------
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
from os.path import exists
from os.path import split

import base64
'''
CMake build integration for 10x (10xeditor.com) 
Version: 0.1.0
Original Script author: https://github.com/andersama

To get started go to Settings.10x_settings, and enable the hooks, by adding these lines:
    CMake.HookBuild: true
    CMake.HookWorkspaceOpened: true
	
This script assumes CMake.exe is in your path! To change this modify CMake.Path

CMake_Options:
    - CMake.HookBuild: (default=False)           Hooks CMake into build commands, detects cmake projects and executes OnCMakeBuildStarted
    - CMake.HookWorkspaceOpened: (default=False) Hooks CMake into workspace opened commands, detects cmake project files inside the current workspace and writes 10x workspace files
    - CMake.Path:                                Path to a custom cmake executable or directory, default assumes CMake is on the path!
    - CMake.GuiPath:                             Path to cmake-gui executable or directory, default assumes cmake-gui is on the path!
    - CMake.Verbose: (default=False)             Turns on debugging print statements

History:
  0.1.2
      - Add cmake_gui function (use with the command window) ctrl+shift+x
      - Auto detect config and config / preset names for each workflow
  0.1.1
      - Fixed bugs and inheritance algorithm
  0.1.0
      - First Release
'''

def b64_encode(s):
    return base64.b64encode(s.encode()).decode()

def read_json_file(json_path, verbose=False):
    data = dict()
    with open(json_path, 'r', encoding='utf-8-sig') as json_data:
        json_text = json_data.read()
        if verbose:
            print(json_text)
        data = json.loads(json_text)
    return data
        
def write_json_file(json_path, json_obj):
    with open(json_path, 'w') as f:
        json.dump(json_obj, f)

def run_cmd(cmd_args, working_dir) -> str:
    process = subprocess.Popen(cmd_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=working_dir,
            encoding='utf8')
    returncode = process.wait()
    result = process.stdout.read()
    return result

#use \'s for paths, default window behavior
def norm_path_bslash(path)->str:
    return re.sub(r'[/]','\\',os.path.normpath(path))

#use /'s for paths, allows copy/pasting into explorer (default is \)
def norm_path_fslash(path)->str:
    return re.sub(r'[\\]','/',os.path.normpath(path))

def macro_expansion(target_string:str, macros) -> str:
    i = int(0)
    #target_string = input_string.encode('utf-8').decode('unicode_escape') #bytes(input_string,'utf-8').decode('unicode_escape') #TODO: unescape strings
    out_string = ""
    while i < len(target_string):
        em = i
        if target_string[i] == '$': #potential macro expansion
            while em < len(target_string) and target_string[em] != '}':
                em += 1
            macro_key = target_string[i:em+1]
            macro_value = macro_key
            if macro_key in macros and macros[macro_key] != None:
                macro_value = macros[macro_key]
            out_string += macro_value
            #jump past macro expansion
            i = em+1
        else:
            while em < len(target_string) and target_string[em] != '$':
                em += 1
            out_string += target_string[i:em]
            #jump past substring
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
    #otherwise just return the item as is
    return item

def cmake_inheirit(child_obj, parent_obj):
    expanded_obj = copy.deepcopy(parent_obj)
    
    keep_hidden = False
    if "hidden" in child_obj:
        keep_hidden = True

    for key in child_obj:
        expanded_obj[key] = child_obj[key]

    if not keep_hidden:
        expanded_obj.pop("hidden", None)

    return expanded_obj

def cmake_parse_args(cmd_args:list) -> dict:
    #see: https://cmake.org/cmake/help/latest/manual/cmake.1.html
    #-D <var>:<type>=<value>, -D <var>=<value>
    #-C <intial-cache> 
    #-G <generator-name>
    #returns a cache-v2 json like dictionary of cmake variables that got parsed over command-line, later entries have greater precedence
    cmake_cache = dict()
    cmake_cache["entries"] = []
    insert_point = 0
    skip_arg = False
    for i in range(0, len(cmd_args)):
        arg = cmd_args[i]
        if skip_arg:
            skip_arg = False
            continue
        if arg == "cmake":
            continue #presumably the start of the command line if someone forgot to strip the exe
        if arg.startswith("-D"):
            m = re.match("^-D([^:=]*)(:[^=]*)?=(.*)$")
            cmake_cache["entries"].append({"name":m.group(1),"type":m.group(2),"value":m.group(3)})
        
        elif arg == "-G" and i+1 < len(cmd_args):
            cmake_cache["entries"].append({
                "name" : "CMAKE_GENERATOR",
                "properties" : 
                [
                    {
                        "name" : "HELPSTRING",
                        "value" : "Name of generator."
                    }
                ],
                "type" : "INTERNAL",
                "value":cmd_args[i+1]
            })
            skip_arg = True
        elif arg == "-C" and i+1 < len(cmd_args):
            cached = read_json_file(cmd_args[i+1])
            if "entries" in cached and type(cached["entries"]) is list:
                count = len(cached["entries"])
                cmake_cache["entries"][insert_point:insert_point] = cached["entries"]
                insert_point += count
                skip_arg = True
        elif arg == "--config" and i+1 < len(cmd_args):
            cmake_cache["entries"].append({"name":"CMAKE_CONFIG_NAME","type":"INTERNAL","value":cmd_args[i+1]})
            skip_arg = True
        elif arg.startswith("--preset"):
            #--preset <preset>, --preset=<preset>
            if arg == "--preset" and i+1 < len(cmd_args):
                preset_name = cmd_args[i+1]
                cmake_cache["entries"].append({"name":"CMAKE_PRESET_NAME","type":"INTERNAL","value":preset_name})
                skip_arg = True
            else:
                m = re.match("^--preset=(.*)$")
                cmake_cache["entries"].append({"name":"CMAKE_PRESET_NAME","type":"INTERNAL","value":m.group(1)})
        elif arg == "-A" and i+1 < len(cmd_args):
            #-A <platform-name> Specify platform name if supported by generator.
            cmake_cache["entries"].append({
                "name" : "CMAKE_GENERATOR_PLATFORM",
                "properties" : 
                [
                    {
                        "name" : "HELPSTRING",
                        "value" : "Name of generator platform."
                    }
                ],
                "type" : "INTERNAL",
                "value" : cmd_args[i+1]
            })
            skip_arg = True
        elif arg == "-S" and i+1 < len(cmd_args):
            cmake_cache["entries"].append({
                "name" : "CMAKE_CURRENT_PROJECT_SOURCE_DIR",
                "properties" : 
                [
                    {
                        "name" : "HELPSTRING",
                        "value" : "Value Computed by 10xEditor"
                    }
                ],
                "type" : "STATIC",
                "value" : cmd_args[i+1]
            })
            skip_arg = True
        elif arg == "-B" and i+1 < len(cmd_args):
            cmake_cache["entries"].append({
                "name" : "CMAKE_CURRENT_PROJECT_BINARY_DIR",
                "properties" : 
                [
                    {
                        "name" : "HELPSTRING",
                        "value" : "Value Computed by 10xEditor"
                    }
                ],
                "type" : "STATIC",
                "value" : cmd_args[i+1]
            })
            skip_arg = True
        elif arg == "--install-prefix" and i+1 < len(cmd_args):
            cmake_cache["entries"].append({
                "name" : "CMAKE_INSTALL_PREFIX",
                "properties" : 
                [
                    {
                        "name" : "HELPSTRING",
                        "value" : "Specifies the installation directory. Must be an absolute path."
                    }
                ],
                "type" : "PATH",
                "value" : cmd_args[i+1]
            })
            skip_arg = True
        #TODO: parse more command line and make it available to python

    return cmake_cache

#see: https://cmake.org/cmake/help/latest/manual/cmake-presets.7.html#macro-expansion
def cmake_prep(source_dir, build_dir, cmd_args, use_presets_if_available=True, use_settings_if_available=True):
    cmakelists_exists = IsCMakeDirectory(source_dir)
    presetpath = norm_path_fslash(os.path.join(source_dir, "CMakePresets.json")) #//source_dir + "\\CMakePresets.json"
    settingspath = norm_path_fslash(os.path.join(source_dir, "CMakeSettings.json")) #source_dir + "\\CMakeSettings.json"
    preset_exists = exists(presetpath)
    settings_exists = exists(settingspath)

    if not(cmakelists_exists):
        return dict()

    args = cmake_parse_args(cmd_args)
    
    #source_parent, source_name = split(source_dir)

    if os.path.isdir(source_dir):
        projectFile = norm_path_fslash(os.path.join(source_dir, "CMakeLists.txt"))
    else:
        projectFile = norm_path_fslash(source_dir)
    
    if settings_exists:
        thisFile = settingspath
        thisFileDir, thisFileName = split(thisFile)
    else:
        thisFile = None,
        thisFileDir = None

    #command line overrides
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

    hasher = hashlib.shake_256(bytes(src_dir, encoding='utf-8-sig'))
    workspaceHash = hasher.hexdigest(20)

    macros = {
        "${sourceDir}": src_dir,
        "${sourceParentDir}": src_parent,
        "${sourceDirName}": src_name,
        "${presetName}": preset_name, #like --Config
        "${generator}": generator,
        "${hostSystemName}": platform.system(),
        "${dollar}": "$",
        "${pathListSep}": ";", #TODO: this apparently changes given an OS? #a native character for separating lists of paths
        #old settings.json macros
        "${workspaceRoot}": src_dir,
        "${workspaceHash}": str(workspaceHash), #TODO: find out what hash functions typically get used here
        "${projectFile}": projectFile,
        "${projectDir}": src_dir,
        "${thisFile}": thisFile,
        "${thisFileDir}": thisFileDir,
        "${name}": config_name, #like --preset
    }
    #see: https://learn.microsoft.com/en-us/cpp/build/cmake-presets-json-reference?view=msvc-170
    #$env{<variable-name>} environment variable with name <variable-name>
    #$penv{<variable-name>} Similar to $env{<variable-name>}, except that the value only comes from the parent environment, and never
    #$vendor{<macro-name>} An extension point for vendors to insert their own macros. CMake will not be able to use presets which have a $vendor{<macro-name>} macro, and effectively ignores such presets. However, it will still be able to use other presets from the same file.
        #print(f'{key}: {value}')

    #see: https://learn.microsoft.com/en-us/cpp/build/cmakesettings-reference?view=msvc-170#macros
    #${macro}
    #${workspaceRoot}, ${workspaceHash}, ${projectFile}, ${projectDir}, ${thisFile}, ${thisFileDir}, ${name}, ${generator}, ${env.VARIABLE}
    #${env.<VARIABLE>} environment variable with name <variable-name>
    for key, value in os.environ.items():
        macros["$env{"+key+"}"] = value
        macros["${env."+key+"}"] = value
        
    if cmakelists_exists:
        if use_presets_if_available and len(presetpath) > 0:
            data = read_json_file(presetpath)
            configs = data["configurePresets"]
            depths = []
            #first pass to figure out inheiritance of configs
            for i in range(0, len(configs)): #config in configs:
                config = configs[i]
                if "inherits" in config:
                    new_config = dict()
                    for j in range(0, len(configs)):
                        c = configs[j]
                        if c["name"] == config["inherits"]:
                            #inheirit(config, c)
                            if "inheirits" in c:
                                depths.append({"config": config["name"], "parent": config["inherits"], "depth": 2, "self_index": i, "parent_index": j})
                            else:
                                depths.append({"config": config["name"], "parent": config["inherits"], "depth": 1, "self_index": i, "parent_index": j})
                            break
                else:
                    depths.append({"config": config["name"], "parent": None, "depth": 0, "self_index": i, "parent_index": 0})
           
            start_index = 0 #this counts the # of items with 0 depth
            while True:
                mx_depth = 0
                #this is to recurse through inheirited configs in a linear fashion
                start_loop = True
                for i in range(start_index, len(depths)):
                    item = depths[i]
                    if item["depth"] == 0 and start_loop:
                        start_index = start_index + 1 #continue the loop past this point in future
                        continue
                    if item["depth"] == 1:
                        child_index = item["self_index"]
                        parent_index = item["parent_index"]
                        #note: we only inheirit from parents w/ no parents*
                        configs[child_index] = cmake_inheirit(configs[child_index], configs[parent_index])
                        configs[child_index].pop("inheirits", None)
                        depths[child_index]["inheirits"] = None
                        depths[child_index]["depth"] = 0
                        if start_loop:
                            start_index = start_index + 1 #continue the loop past this point in future
                    else:
                        child_index = item["self_index"]
                        parent_index = item["parent_index"]
                        depth = depths[child_index]["depth"] + 1
                        if depth == 1:
                            child_index = item["self_index"]
                            parent_index = item["parent_index"]
                            configs[child_index] = cmake_inheirit(configs[child_index], configs[parent_index])
                            configs[child_index].pop("inheirits", None)
                            depths[child_index]["inheirits"] = None
                            depths[child_index]["depth"] = 0
                            if start_loop:
                                start_index = start_index + 1 #continue the loop past this point in future
                        else:
                            configs[child_index]["depth"] = depth
                            start_loop = False

                    if depths[i]["depth"] > mx_depth:
                        mx_depth = depths[i]["depth"]
                
                if not (mx_depth > 0):
                    break #finally we're done, everything has inheirited its parent properly
                #sort the array again
                #depths.sort(key=lambda x: x["depth"])
                #depths = sorted(depths, key=operator.attrgetter('depth'))
            data["configurePresets"] = configs
            
            unexpanded_configs = data["configurePresets"]
            for i in range(0, len(unexpanded_configs)):
                if generator == None and "generator" in unexpanded_configs[i]:
                    macros["${generator}"] = macro_expand_any(unexpanded_configs[i]["generator"], macros)
                elif generator == None and not "generator" in unexpanded_configs[i]:
                    macros["${generator}"] = None #will leave ${generator} unexpanded
                data["configurePresets"][i] = macro_expand_any(unexpanded_configs[i], macros)

            # add in the cmake variables over commandline (overrides)
            for i in range(0,len(data["configurePresets"])):
                if generator == None and "generator" in unexpanded_configs[i]:
                    macros["${generator}"] = macro_expand_any(unexpanded_configs[i]["generator"], macros)
                elif generator == None and not "generator" in unexpanded_configs[i]:
                    macros["${generator}"] = None
                for cmake_var in args["entries"]: #macro expand the variables?
                    k = macro_expand_any(cmake_var["name"], macros)
                    v = macro_expand_any(cmake_var["value"],macros)
                    data["configurePresets"][i]["cacheVariables"][k] = v

            builds = data["buildPresets"]
            data["buildPresets"] = macro_expand_any(builds, macros)
            if "entries" in args:
                data["entries"] = args["entries"]
            return data
        if use_settings_if_available and len(settingspath) > 0:
            data = read_json_file(settingspath)
            #settings don't do inheritance? but they definitely expand macros
            unexpanded_configs = data["configurations"]
            for i in range(0, len(unexpanded_configs)):
                if generator == None and "generator" in unexpanded_configs[i]:
                    macros["${generator}"] = macro_expand_any(unexpanded_configs[i]["generator"], macros)
                elif generator == None and not "generator" in unexpanded_configs[i]:
                    macros["${generator}"] = None #will leave ${generator} unexpanded
                
                for cmake_var in args["entries"]:
                    found = False
                    found_idx = 0
                    for v in range(0,len(data["configurations"][i]["variables"])):
                        config_var = data["configurations"][i]["variables"][v]
                        if config_var["name"] == cmake_var["name"]:
                            found = True
                            found_idx = v
                            break

                    cmake_var_copy = copy.deepcopy(cmake_var)
                    cmake_var_copy.pop("properties", None)
                    if found:
                        data["configurations"][i]["variables"][found_idx] = cmake_var_copy
                    else:
                        data["configurations"][i]["variables"].append(cmake_var_copy)

                data["configurations"][i] = macro_expand_any(unexpanded_configs[i], macros)
            data = macro_expand_any(data, macros)
            if "entries" in args:
                data["entries"] = args["entries"]
            return data
        #Handling of empty project
        if "entries" in args:
            data["entries"] = args["entries"]
        #failover use just cmake, no presets.json, no settings.json
    return dict()

def cmake_version():
    CMake_EXE = N10X.Editor.GetSetting("CMake.Path").strip()
    if not CMake_EXE:
        CMake_EXE = 'cmake'
    if os.path.isdir(CMake_EXE):
        CMake_EXE = os.path.join(CMake_EXE, 'cmake.exe')

    txworkspace = N10X.Editor.GetWorkspaceFilename()
    directory, filename = split(txworkspace) #os.path.split

    stdtxt = run_cmd([CMake_EXE, "--version"], directory)
    r = re.search("^cmake version (\\d+).(\\d+).(\\d+)[-](\\w+)?", stdtxt)

    if r != None:
        result = {"major": int(r.group(1)), "minor": int(r.group(2)), "patch": int(r.group(3)), "tag": r.group(4)}
        result["preset_support"] = result["major"] >= 3 and result["minor"] >= 1
    else:
        result = {"major": 0, "minor": 0, "patch": 0, "tag": "", "preset_support": False}

    print(result)
    return result

def cmake_gui(src_dir:str=""):
    txworkspace = N10X.Editor.GetWorkspaceFilename()
    directory, filename = split(txworkspace) #os.path.split

    if len(src_dir) == 0 or src_dir==".":
        src_dir = directory

    cmakelists_exists = IsCMakeDirectory(src_dir)

    cmake_gui = N10X.Editor.GetSetting("CMake.GuiPath").strip()
    if not cmake_gui:
        cmake_gui = 'cmake-gui'
    if os.path.isdir(cmake_gui):
        cmake_gui = os.path.join(cmake_gui, 'cmake-gui.exe')

    if cmakelists_exists:
        stdtxt = run_cmd([cmake_gui, "-S", src_dir], src_dir)
        return stdtxt

    return ""

def cmake_configure(cmd_args, working_dir) -> dict:
    #["cmake", ...]
    stdtxt = run_cmd(cmd_args, working_dir)
    #read the stdout to grab the build directory
    #print(stdtxt)
    N10X.Editor.LogToBuildOutput(stdtxt)

    #debugging
    #all we technically need as feedback is the build directory we can extract from
    #the command line later if needed so I'm writing a .json file behind
    result = {
        "stdout": stdtxt,
        "build_dir": None
    }
    
    r = re.search("-- Build files have been written to:\\s+(.+)$", stdtxt)

    if r != None:
        result["build_dir"] = r.group(1)

    return result

def cmake_build(cmd_args, working_dir, build_dir) -> dict:
    #["cmake", ...]
    #write file api query
    query_dir  = norm_path_fslash(os.path.join(build_dir, ".cmake/api/v1/query/client-10xeditor")) #build_dir + "/.cmake/api/v1/query/client-10xeditor"
    reply_dir  = norm_path_fslash(os.path.join(build_dir, ".cmake/api/v1/reply/")) #build_dir + "/.cmake/api/v1/reply/"
    query_file = norm_path_fslash(os.path.join(query_dir, "query.json")) #query_dir + "/query.json"

    query_json = {
        "requests": [
            {
                "kind": "cache",
                "version": 2
            },
            {
                "kind": "cmakeFiles",
                "version": 1
            },
            {
                "kind": "codemodel",
                "version": 2
            },
            {
                "kind": "toolchains",
                "version": 1
            }
        ]
    }

    #ensure the folder exists before we attempt to write to it
    if not os.path.exists(query_dir):
        try:
            os.makedirs(query_dir)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise

    with open(query_file, 'w') as f:
        json.dump(query_json, f)
    
    stdtxt = run_cmd(cmd_args, working_dir)
    N10X.Editor.LogToBuildOutput(stdtxt)
    #print(stdtxt)
    result = {
        "stdout": stdtxt,
        "exe": None,
        "sln": None,
        "pdb": None
    }

    index_json = None
    #read file api reply
    for root, dirs, files in os.walk(reply_dir):
        for file in files:
            #find the index file
            if re.match("^(index-.+[.]json)$", file):
                index_json = file
                break

    if len(index_json) <= 0:
        print("No index.json file found in reply directory, make sure you're running an up to date version of CMake")
        return result

    index_path = norm_path_fslash(os.path.join(reply_dir,index_json))
    index_data = read_json_file(index_path)
    generator_data = index_data["cmake"]["generator"]
    generator = generator_data["name"]
    platform = generator_data["platform"]
    
    #Read "objects" which includes all the json file responses
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

    if (len(codemodel_json_obj["jsonFile"]) > 0):
        codemodel_path = norm_path_fslash(os.path.join(reply_dir,codemodel_json_obj["jsonFile"]))
        codemodel_data = read_json_file(codemodel_path)
        source_dir = codemodel_data["paths"]["source"]
        configuration_data = codemodel_data["configurations"]
        for obj in configuration_data:
            config_name = obj["name"] #Debug, Release, RelWithDebInfo, MinSizeRel
            targets_data = obj["targets"]
            main_project_data = obj["projects"][0]
            project_name = main_project_data["name"]
            target_obj = dict()

            for target in targets_data:
                if (target["name"] == project_name):
                    target_obj = target
                    potential_targets.append(target)
                    break

    #find a target which has an .exe path which exists and matches
    #the internal project_name
    #assume the most recent is the actual build
    mtime = 0
    newest_target = None
    newest_pdb = None
    for target in potential_targets:
        target_path = norm_path_fslash(os.path.join(reply_dir,target["jsonFile"]))
        target_data = read_json_file(target_path)
        artifacts = target_data["artifacts"]
        executable_obj = artifacts[0]
        pdb_obj = None
        if len(artifacts)>1:
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

    project_exe = newest_target
    if newest_target and len(newest_target) > 0:
        N10X.Editor.SetWorkspaceSetting("RunCommand", project_exe)
        N10X.Editor.SetWorkspaceSetting("DebugCommand", project_exe)
        N10X.Editor.SetWorkspaceSetting("ExePath", project_exe)
    else:
        N10X.Editor.SetWorkspaceSetting("RunCommand", "")
        N10X.Editor.SetWorkspaceSetting("DebugCommand", "")
        N10X.Editor.SetWorkspaceSetting("ExePath", "")

    #find an sln if there is one, use the most recently changed
    newest_sln = None
    mtime_sln = 0
    for root, dirs, files in os.walk(build_dir):
        for file in files:
            if file.endswith(".sln"):
                sln_path = norm_path_fslash(os.path.join(build_dir, file))
                file_mtime = os.path.getmtime(sln_path)
                if file_mtime > mtime_sln:
                    mtime_sln = file_mtime
                    newest_sln = sln_path
    
    N10X.Editor.SetWorkspaceSetting("DebugSln", newest_sln)   

    result["exe"] = newest_target
    result["sln"] = newest_sln
    result["pdb"] = newest_pdb
    return newest_target

def write10xWorkspace(outpath,
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
    platformlist=[]):

    root = ET.Element("N10X")
    doc = ET.SubElement(root, "Workspace")

    ET.SubElement(doc, "IncludeFilter").text = "*.*"
    ET.SubElement(doc, "ExcludeFilter").text = "*.obj,*.lib,*.pch,*.dll,*.pdb,.vs,Debug,Release,x64,obj,*.user,Intermediate,*.vcxproj,*.vcxproj.filters"
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
    ET.SubElement(doc, "RunCommandWorkingDirectory").text = runcommandworkingdirectory_cmd
    ET.SubElement(doc, "DebugCommand").text = debug_cmd
    ET.SubElement(doc, "ExePathCommand").text = exepath
    ET.SubElement(doc, "DebugSln").text = debugsln
    ET.SubElement(doc, "UseVisualStudioEnvBat").text = "true"
    #A bit of extra XML
    ET.SubElement(doc, "UseCMake").text = "true"

    config_element = ET.SubElement(doc, "Configurations")
    for config in configlist:
        ET.SubElement(config_element, "Configuration").text=config
    
    platform_element = ET.SubElement(doc, "Platforms")
    for platform in platformlist:
        ET.SubElement(platform_element, "Platform").text=platform

    additional_include_paths = ET.SubElement(doc, "AdditionalIncludePaths")
    ET.SubElement(additional_include_paths, "AdditionalIncludePath")
    ET.SubElement(doc, "Defines")
    #TODO: pretty print
    tree = ET.ElementTree(root)
    xml_text = ET.tostring(root, xml_declaration=True).decode()

    f = None
    try:
        f = open(outpath, "x")
    except IOError:
        print(outpath+" already exists")
    else:
        print("Writing CMake Workspace: "+outpath)
        f.write(xml_text)
    finally:
        if f:
            f.close()

def IsCMakeDirectory(directory) -> bool:
    return exists(norm_path_fslash(os.path.join(directory,"CMakeLists.txt"))) #os.path.join(os.path.dirname(directory),"CMakeLists.txt")

def IsCMakeCacheDirectory(directory) -> bool:
    return exists(norm_path_fslash(os.path.join(directory,"CMakeCache.txt")))

def IsCMakePresetDirectory(directory) -> bool:
    return exists(norm_path_fslash(os.path.join(directory,"CMakePresets.json")))

def IsCMakeSettingsDirectory(directory) -> bool:
    return exists(norm_path_fslash(os.path.join(directory,"CMakeSettings.json")))

def CMakeProjectName(cache_directory) -> str:
    project_name = None
    if (len(cache_directory)):
        process = subprocess.Popen(["findstr", "CMAKE_PROJECT_NAME", norm_path_fslash(os.path.join(cache_directory,"CMakeCache.txt"))],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                #cwd=cmakefolder,
                encoding='utf8')
        returncode = process2.wait()
        result = process2.stdout.read()
        r = re.search(r"=(.*)$", result)
        if r != None:
            project_name = r.group(1)
    return project_name

def CMakeBuildStarted(filename:str,rebuild:bool=False):
    cmake_hook_build_setting = N10X.Editor.GetSetting("CMake.HookBuild")
    if cmake_hook_build_setting and cmake_hook_build_setting.lower() == 'true':
        pass
    else:
        print("CMake: ignoring build command (set CMake.HookBuild to true)")
        return False

    verbose_setting = N10X.Editor.GetSetting("CMake.Verbose")
    verbose = verbose_setting and verbose_setting.lower()
    
    CMake_EXE = N10X.Editor.GetSetting("CMake.Path").strip()
    if not CMake_EXE:
        CMake_EXE = 'cmake'
    if os.path.isdir(CMake_EXE):
        CMake_EXE = os.path.join(CMake_EXE, 'cmake.exe')

    txworkspace = N10X.Editor.GetWorkspaceFilename()
    directory, filename = split(txworkspace) #os.path.split
    
    cmakelists_exists = IsCMakeDirectory(directory)
    presetpath = norm_path_fslash(os.path.join(directory, "CMakePresets.json")) #//directory + "\\CMakePresets.json"
    settingspath = norm_path_fslash(os.path.join(directory, "CMakeSettings.json")) #directory + "\\CMakeSettings.json"

    preset_exists = exists(presetpath)
    settings_exists = exists(settingspath)
    
    build_dir = None
    print("Checking for CMake build...")
    if (cmakelists_exists):
        version = cmake_version()

        print("CMake Build Detected: Using Python")
        n10x_config = N10X.Editor.GetWorkspaceBuildConfig()
        n10x_platform = N10X.Editor.GetWorkspaceBuildPlatform() 
        build_name = n10x_platform+"-"+n10x_config
        N10X.Editor.LogToBuildOutput('----- Build {} {} -----\n'.format(n10x_config,n10x_platform))
        build_directory_path = norm_path_fslash(os.path.join(directory, "out\\build", build_name))
        if (preset_exists and version["preset_support"]):
            print("CMake Macro Expansion: ...")
            #TODO detect and parse command line to pass into this function
            data = cmake_prep(directory, None, [], True, False)
            if verbose:
                print(json.dumps(data, indent="\t"))#json.loads(json.dumps(data))

            configs = data["configurePresets"]
            builds = data["buildPresets"]

            #easy build, we'll automatically pick the configurePreset name to go with a buildPreset
            cmake_config_name = None
            cmake_build_name = None
            cmake_config_obj = {}

            for build in builds:
                if build["name"] == build_name:
                    cmake_build_name = build_name
                    cmake_config_name = build["configurePreset"]
                    break
            #failed to find a matching $(Configuration)-$(Platform) build now look for just $(Configuration)
            if cmake_build_name == None:
                for build in builds:
                    if build["name"] == n10x_config:
                        cmake_build_name = n10x_config
                        cmake_config_name = build["configurePreset"]
                        break

            if cmake_config_name == None:
                for config in configs:
                    if config["name"] == build_name:
                        cmake_config_name = build_name
                        cmake_config_obj = config
                        break
                if cmake_config_name == None:
                    for config in configs:
                        if config["name"] == n10x_config:
                            cmake_config_name = n10x_config
                            cmake_config_obj = config
                            break
            else: #found a matching buildPreset, now find the configPreset
                for config in configs:
                    if config["name"] == cmake_config_name:
                        cmake_config_obj = config
                        break
            
            #TODO? Nearest config/preset name (did you mean) feedback?
            if cmake_config_name == None:
                N10X.Editor.LogToBuildOutput('Failed to find a build or config preset in CMakePresets.json for: {0} and {1}'.format(build_name, n10x_config))
                return True
            
            build_directory_path = norm_path_fslash(os.path.join(directory, "out\\build", cmake_build_name))

            config_args = [CMake_EXE, "-S", directory, "-B", build_directory_path, "--preset", cmake_config_name]
            if rebuild:
                config_args.append("--fresh")

            N10X.Editor.LogToBuildOutput(' '.join(config_args))
            N10X.Editor.LogToBuildOutput('\n')
            config_result = cmake_configure(config_args, directory)
            build_dir = config_result["build_dir"]
            if (build_dir and len(build_dir)):
                #TODO: generate cmake command from preset.json
                if cmake_build_name != None:
                    build_args = [CMake_EXE, "--build", "--preset", cmake_build_name]
                    if "entries" in data and data["entries"] and len(data["entries"]) > 0:
                        initial_cache_path = norm_path_fslash(os.path.join(build_directory_path, "10x_initial_cache.json"))
                        write_json_file(initial_cache_path, data)
                        build_args.append("-C") #see cmake ide integration guide
                        build_args.append(initial_cache_path)
                else:
                    build_args = [CMake_EXE, "--build", "-S", directory]
                    if "binaryDir" in cmake_config_obj:
                        build_args.append("-B")
                        build_args.append(cmake_config_obj["binaryDir"])
                    if "generator" in cmake_config_obj:
                        build_args.append("-G")
                        build_args.append(cmake_config_obj["generator"])
                    if data["entries"] and len(data["entries"]) > 0:
                        initial_cache_path = norm_path_fslash(os.path.join(build_directory_path, "10x_initial_cache.json"))
                        write_json_file(initial_cache_path, data)
                        build_args.append("-C") #see cmake ide integration guide
                        build_args.append(initial_cache_path)
                    #for cmake_var in cmake_config_obj["cacheVariables"]:
                    #    #build_args.append('-D{}:{}={}'.format())
                    #    build_args.append('-D{}={}'.format(cmake_var,cmake_config_obj["cacheVariables"][cmake_var]))

                N10X.Editor.LogToBuildOutput(' '.join(build_args))
                N10X.Editor.LogToBuildOutput('\n')
                exe_path = cmake_build(build_args, directory, build_dir)
        elif (settings_exists):
            print("CMake Macro Expansion: ...")
            #TODO detect and parse command line to pass into this function
            data = cmake_prep(directory, None, [], False, True)
            if verbose:
                print(json.dumps(data, indent="\t"))#json.loads(json.dumps(data))
            
            cmake_config_name = None
            cmake_config_obj = {}
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
            
            #TODO? Nearest config/preset name (did you mean) feedback?
            if cmake_config_name == None:
                N10X.Editor.LogToBuildOutput('Failed to find configuration in CMakeSettings.json for: {0} and {1}'.format(build_name, n10x_config))
                return True

            build_directory_path = norm_path_fslash(os.path.join(directory, "out\\build", cmake_build_name))

            #TODO: read CMakeSettings.json? get --Config setting?
            #"-S", directory, "-B", build_directory_path,
            config_args = [CMake_EXE, "-S", directory, "-B", build_directory_path]
            if rebuild:
                config_args.append("--fresh")

            N10X.Editor.LogToBuildOutput(' '.join(config_args))
            N10X.Editor.LogToBuildOutput('\n')
            build_dir = cmake_configure(config_args, directory) #--Config
            if (build_dir and len(build_dir)):
                build_args = [CMake_EXE, "--build", "-S", "directory", "-B", build_dir, "--config", cmake_config_name]
                if "entries" in data and data["entries"] and len(data["entries"]) > 0:
                    initial_cache_path = norm_path_fslash(os.path.join(build_directory_path, "10x_initial_cache.json"))
                    write_json_file(initial_cache_path, data)
                    build_args.append("-C") #see cmake ide integration guide
                    build_args.append(initial_cache_path)

                N10X.Editor.LogToBuildOutput(' '.join(build_args))
                N10X.Editor.LogToBuildOutput('\n')
                exe_path = cmake_build(build_args, directory, build_dir)
        else:
            #TODO detect and parse command line to pass into this function
            data = cmake_prep(directory, None, [], False, False)
            if verbose:
                print(json.dumps(data, indent="\t"))
            
            config_args = [CMake_EXE, "-S", directory, "-B", build_directory_path]
            if rebuild:
                config_args.append("--fresh")

            N10X.Editor.LogToBuildOutput(' '.join(config_args))
            N10X.Editor.LogToBuildOutput('\n')
            build_dir = cmake_configure(config_args, directory)
            if (build_dir and len(build_dir)):
                build_args = [CMake_EXE, "--build", "."]
                if "entries" in data and data["entries"] and len(data["entries"]) > 0:
                    initial_cache_path = norm_path_fslash(os.path.join(build_directory_path, "10x_initial_cache.json"))
                    write_json_file(initial_cache_path, data)
                    build_args.append("-C") #see cmake ide integration guide
                    build_args.append(initial_cache_path)
                N10X.Editor.LogToBuildOutput(' '.join(build_args))
                N10X.Editor.LogToBuildOutput('\n')
                exe_path = cmake_build(build_args, directory, build_dir)

        N10X.Editor.LogToBuildOutput("----- CMake Build Complete -----\n")       
        return True #intercept build command
    else:
        print("No CMake related files found...")
        return False

def OnCMakeRebuildStarted(filename:str) -> bool:
    return CMakeBuildStarted(filename, True)

def OnCMakeBuildStarted(filename:str) -> bool:
    return CMakeBuildStarted(filename, False)

def IsOldWorkspace() -> bool:
    build_cmd                   = N10X.Editor.GetWorkspaceSetting("BuildCommand")
    rebuild_cmd                 = N10X.Editor.GetWorkspaceSetting("RebuildCommand")
    build_file_cmd              = N10X.Editor.GetWorkspaceSetting("BuildFileCommand")
    clean_cmd                   = N10X.Editor.GetWorkspaceSetting("CleanCommand")
    build_working_dir_cmd       = N10X.Editor.GetWorkspaceSetting("BuildWorkingDirectory")
    cancel_build_cmd            = N10X.Editor.GetWorkspaceSetting("CancelBuild")
    run_command_cmd             = N10X.Editor.GetWorkspaceSetting("RunCommand")
    run_working_directory_cmd   = N10X.Editor.GetWorkspaceSetting("RunWorkingDirectory")
    debug_cmd                   = N10X.Editor.GetWorkspaceSetting("DebugCommand")
    exe_path_path               = N10X.Editor.GetWorkspaceSetting("ExePath")
    debug_sln_path              = N10X.Editor.GetWorkspaceSetting("DebugSln")

    return (len(build_cmd)>0  or                
        len(rebuild_cmd)>0  or              
        len(build_file_cmd)>0  or           
        len(clean_cmd)>0  or
        len(build_working_dir_cmd)>0  or    
        len(cancel_build_cmd)>0  or         
        len(run_command_cmd)>0    or
        len(run_working_directory_cmd)>0 or
        len(debug_cmd)>0 or
        len(exe_path_path)>0 or
        len(debug_sln_path)>0)

def OnCMakeWorkspaceOpened():
    cmake_hook_workspace_opened_setting = N10X.Editor.GetSetting("CMake.HookWorkspaceOpened")
    if cmake_hook_workspace_opened_setting and cmake_hook_workspace_opened_setting.lower() == 'true':
        pass
    else:
        print("CMake: ignoring workspace opened (set CMake.HookWorkspaceOpened == 'true'")
        return False

    verbose_setting = N10X.Editor.GetSetting("CMake.Verbose")
    verbose = verbose_setting and verbose_setting.lower()

    cmakelists_exists = False
    cmakepresets_exists = False
    cmakesettings_exists = False
    cmakeprojects = {}

    #working from current project
    txworkspace = N10X.Editor.GetWorkspaceFilename()
    directory, filename = split(txworkspace) #os.path.split
    
    cmakelists_exists = IsCMakeDirectory(directory)
    presetpath = norm_path_fslash(os.path.join(directory,"CMakePresets.json"))
    settingspath = norm_path_fslash(os.path.join(directory,"CMakeSettings.json"))
    listspath = norm_path_fslash(os.path.join(directory,"CMakeLists.txt"))

    print('Working Directory uses CMake?: {0}'.format(cmakelists_exists))
    print('CMakeLists.txt: {0}'.format(listspath))

    preset_exists = exists(presetpath)
    settings_exists = exists(settingspath)

    build_cmd                   = N10X.Editor.GetWorkspaceSetting("BuildCommand")
    rebuild_cmd                 = N10X.Editor.GetWorkspaceSetting("RebuildCommand")
    build_file_cmd              = N10X.Editor.GetWorkspaceSetting("BuildFileCommand")
    clean_cmd                   = N10X.Editor.GetWorkspaceSetting("CleanCommand")
    build_working_dir_cmd       = N10X.Editor.GetWorkspaceSetting("BuildWorkingDirectory")
    cancel_build_cmd            = N10X.Editor.GetWorkspaceSetting("CancelBuild")
    run_command_cmd             = N10X.Editor.GetWorkspaceSetting("RunCommand")
    run_working_directory_cmd   = N10X.Editor.GetWorkspaceSetting("RunWorkingDirectory")
    debug_cmd                   = N10X.Editor.GetWorkspaceSetting("DebugCommand")
    exe_path_path               = N10X.Editor.GetWorkspaceSetting("ExePath")
    debug_sln_path              = N10X.Editor.GetWorkspaceSetting("DebugSln")

    cmake_preset_build     = "cmake --preset \"$(Platform)-$(Configuration)\" && cmake --build --preset \"$(Platform)-$(Configuration)\""
    cmake_preset_rebuild   = "cmake --preset \"$(Platform)-$(Configuration)\" --fresh && cmake --build --preset \"$(Platform)-$(Configuration)\""
    cmake_preset_run       = "$(RootWorkspaceDirectory)/out/build/$(Platform)-$(Configuration)/project_name.exe"
    cmake_preset_debug     = "$(RootWorkspaceDirectory)/out/build/$(Platform)-$(Configuration)/project_name.exe"

    cmake_settings_build   = "cmake -S \"$(RootWorkspaceDirectory)\" -B \"$(RootWorkspaceDirectory)/out/build/$(Platform)-$(Configuration)\" && cmake --build --config \"$(Configuration)\""
    cmake_settings_rebuild = "cmake -S \"$(RootWorkspaceDirectory)\" -B \"$(RootWorkspaceDirectory)/out/build/$(Platform)-$(Configuration)\" --fresh && cmake --build --config \"$(Configuration)\""
    cmake_settings_run     = "$(RootWorkspaceDirectory)/out/build/#(Platform)-$(Configuration)/project_name.exe"
    cmake_settings_debug   = "$(RootWorkspaceDirectory)/out/build/#(Platform)-$(Configuration)/project_name.exe"

    cmake_empty_build      = "cmake -S \"$(RootWorkspaceDirectory)\" -B \"$(RootWorkspaceDirectory)/out/build/$(Configuration)\" && cmake --build -S \"$(RootWorkspaceDirectory)\" -B \"$(RootWorkspaceDirectory)/out/build/$(Configuration)\""
    cmake_empty_rebuild    = "cmake -S \"$(RootWorkspaceDirectory)\" -B \"$(RootWorkspaceDirectory)/out/build/$(Configuration)\" --fresh && cmake --build -S \"$(RootWorkspaceDirectory)\" -B \"$(RootWorkspaceDirectory)/out/build/$(Configuration)\"",
    cmake_empty_run        = "$(RootWorkspaceDirectory)/out/build/$(Configuration)/project_name.exe"
    cmake_empty_debug      = "$(RootWorkspaceDirectory)/out/build/$(Configuration)/project_name.exe"

    if(IsOldWorkspace()):
        #do nothing
        #if (cmakelists_exists):
            #project_name = CMakeProjectName()
            #print('CMake Project Name: {0}'.format(project_name))
        #if cmakelists_exists:
            #json_prep = cmake_prep(directory, "./out/build", [])
            #print(json_prep)
        pass
    else:
        if (cmakelists_exists):
            #print("Configuring CMake Workspace...")
            #project_name = CMakeProjectName()
            if (preset_exists):
                N10X.Editor.SetWorkspaceSetting("BuildCommand", cmake_preset_build)
                N10X.Editor.SetWorkspaceSetting("RebuildCommand", cmake_preset_rebuild)
                N10X.Editor.SetWorkspaceSetting("RunCommand", cmake_preset_run)
                N10X.Editor.SetWorkspaceSetting("DebugCommand", cmake_preset_debug)
                N10X.Editor.SetWorkspaceSetting("ExePath", cmake_preset_run)
            elif (settings_exists):
                data = read_json_file(settingspath)
                
                configuration_list = data["configurations"]
                configurations = []
                for json_object in configuration_list:
                    configurations.append(json_object["name"])

                N10X.Editor.SetWorkspaceSetting("BuildCommand", cmake_settings_build)
                N10X.Editor.SetWorkspaceSetting("RebuildCommand", cmake_settings_build)
                N10X.Editor.SetWorkspaceSetting("RunCommand", cmake_settings_run)
                N10X.Editor.SetWorkspaceSetting("DebugCommand", cmake_settings_debug)
                N10X.Editor.SetWorkspaceSetting("ExePath", cmake_settings_run)
            else:
                N10X.Editor.SetWorkspaceSetting("BuildCommand", cmake_empty_build)
                N10X.Editor.SetWorkspaceSetting("RebuildCommand", cmake_empty_rebuild)
                N10X.Editor.SetWorkspaceSetting("RunCommand", cmake_empty_run)
                N10X.Editor.SetWorkspaceSetting("DebugCommand", cmake_empty_debug)
                N10X.Editor.SetWorkspaceSetting("ExePath", cmake_empty_run)


    #scan through workspace files for other directories
    project_files = N10X.Editor.GetWorkspaceFiles()
    for project_file in project_files:
        if (project_file.endswith("CMakeLists.txt")):
            cmakelists_exists = True
            cmakefolder = project_file[:-len("CMakeLists.txt")]

            presetpath = cmakefolder + "CMakePresets.json"
            settingspath = cmakefolder + "CMakeSettings.json"
            
            preset_exists = exists(presetpath)
            settings_exists = exists(settingspath)

            cmakepresets_exists = cmakepresets_exists or preset_exists
            cmakesettings_exists = cmakesettings_exists or settings_exists
            
            cmakeprojects[project_file] = {preset_exists, cmakesettings_exists}
            
            if (preset_exists):
                data = cmake_prep(cmakefolder, "$(RootWorkspaceDirectory)/out/build/$(Platform)-$(Configuration)", [], True, False)
                if verbose:
                    print(data)
                #data = read_json_file(presetpath)
                
                preset_version = data["version"]
                preset_configs = data["configurePresets"]
                build_configs = data["buildPresets"]

                non_hidden_configs = []
                non_hidden_build_configs = []
                #${hostSystemName} = Windows, Darwin, Linux
                for preset in preset_configs:
                    if "hidden" in preset and preset["hidden"] == "true":
                        continue
                    if "condition" in preset:
                        condition = preset["condition"]
                        if condition["type"] is str and condition["type"].lower() == "equals":
                            if condition["lhs"] != condition["rhs"]:
                                continue
                        #TODO: other conditions        
                    non_hidden_configs.append(preset)
                
                config_list_results = []
                build_list_results = []
                for build_preset in build_configs:
                    if build_preset["hidden"] == "true":
                        continue
                    build_list_results.append(build_preset["name"])

                workspace_file = norm_path_fslash(os.path.join(cmakefolder,"cmakepreset.10x"))
                write10xWorkspace(workspace_file,
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
                []
                )
            elif (settings_exists):
                #TODO: parse json from CMakeSettings.json
                #data = read_json_file(settingspath)
                data = cmake_prep(cmakefolder, "$(RootWorkspaceDirectory)/out/build/$(Configuration)", [], False, True)
                if verbose:
                    print(data)

                configuration_list = data["configurations"]
                configurations = []
                for json_object in configuration_list:
                    configurations.append(json_object["name"])

                #print("Writing "+cmakefolder+"cmakesettings.10x")
                workspace_file = norm_path_fslash(os.path.join(cmakefolder,"cmakesettings.10x"))
                write10xWorkspace(workspace_file,
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
                []
                )
            else:
                #print("Writing "+cmakefolder+"cmake.10x")
                workspace_file = norm_path_fslash(os.path.join(cmakefolder,"cmake.10x"))
                write10xWorkspace(workspace_file,
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
                []
                )

def InitializeCMake():
    N10X.Editor.AddOnWorkspaceOpenedFunction(OnCMakeWorkspaceOpened)
    N10X.Editor.AddProjectBuildFunction(OnCMakeBuildStarted)
    N10X.Editor.AddProjectRebuildFunction(OnCMakeRebuildStarted)

N10X.Editor.CallOnMainThread(InitializeCMake)