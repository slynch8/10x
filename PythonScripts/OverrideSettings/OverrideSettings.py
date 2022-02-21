import N10X
import os
import time

OVERRIDE_SETTINGS_UPDATE_INTERVAL = 3.0
override_settings_timer_start = 0
override_settings_filepath = None
override_settings_lasttime = 0

def _OverrideSettingsLoadFile(filepath):
    with open(filepath, 'rt') as f:
        lines = f.readlines()
        for line in lines:
            line = line.strip()
            if line.startswith('#'):
                continue

            key_val = line.split(':')
            if len(key_val) == 2:
                key = key_val[0].strip()
                value = key_val[1].strip()

                N10X.Editor.SetSetting(key, value)
                
                print('OverrideSetting: "' + key + '" = ' + value)

        f.close()

def _OverrideSettingsUpdate():
    global override_settings_timer_start
    global override_settings_lasttime
    global override_settings_filepath

    if override_settings_filepath != None:
        elapsed:float = time.time() - override_settings_timer_start 
        if elapsed >= OVERRIDE_SETTINGS_UPDATE_INTERVAL:
            override_settings_timer_start = time.time()
            cur_time = os.path.getmtime(override_settings_filepath)
            if  cur_time != override_settings_lasttime:
                override_settings_lasttime = cur_time
                if os.path.isfile(override_settings_filepath):
                    _OverrideSettingsLoadFile(override_settings_filepath)
                else:
                    override_settings_filepath = None


def _OverrideSettingsOnWorkspaceOpened():
    global override_settings_timer_start
    global override_settings_filepath
    global override_settings_lasttime

    settings_dir = os.path.normpath(os.path.dirname(N10X.Editor.GetWorkspaceFilename()))
    settings_filepath = os.path.join(settings_dir, 'Settings.10x_settings')
    if os.path.isfile(settings_filepath):
        override_settings_filepath = settings_filepath
        override_settings_lasttime = os.path.getmtime(override_settings_filepath)
        override_settings_timer_start = time.time()
        _OverrideSettingsLoadFile(settings_filepath)
    else:
        override_settings_filepath = None

N10X.Editor.AddUpdateFunction(_OverrideSettingsUpdate)
N10X.Editor.AddOnWorkspaceOpenedFunction(_OverrideSettingsOnWorkspaceOpened)
