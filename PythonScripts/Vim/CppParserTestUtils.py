#------------------------------------------------------------------------
import N10X
import os
import stat
import shutil
import random
import time
import DevUtils
import inspect
import traceback
import sys
import subprocess

#------------------------------------------------------------------------
global g_RunningSingleTest
g_RunningSingleTest = False

#------------------------------------------------------------------------
def SelectSingleTest(tests, test_name):
    global g_RunningSingleTest
    g_RunningSingleTest = True

    for test in tests:
        if test[1].__name__ == test_name:
            return [test]

    Utils.Check(False)

#------------------------------------------------------------------------
def RepeatTests(tests, count):
    global g_RunningSingleTest
    g_RunningSingleTest = False
    repeated_tests = []
    for x in range(count):
        repeated_tests += tests
    return repeated_tests
    
#------------------------------------------------------------------------
def OpenWorkspace(workspace_path, target_dir):
    dir_path = workspace_path
    is_dir = os.path.isdir(workspace_path)
    if not is_dir:
        dir_path = os.path.dirname(workspace_path)

    copy_command = "robocopy -mir " + dir_path + " " + target_dir + " -XD .vs"
    print(copy_command)
    subprocess.run(copy_command, shell=True)

    if is_dir:
        open_result = N10X.Editor.OpenWorkspace(target_dir)
    else:
        target_workspace = os.path.join(target_dir, os.path.basename(workspace_path))
        open_result = N10X.Editor.OpenWorkspace(target_workspace)
        
    return open_result

#------------------------------------------------------------------------
class CppParserTest:
    #---------------------------------------
    def __init__(self, tests_dir, target_dir, tests, exit_on_success):
        self.m_TestsDir = tests_dir
        self.m_TargetDir = target_dir
        self.m_Tests = tests
        self.m_Index = 0
        self.m_TestObject = None
        self.m_ExitOnSuccess = exit_on_success
        self.Initialise()

    #---------------------------------------
    def Initialise(self):
        N10X.Editor.AddUpdateFunction(self.Update)
        N10X.Editor.SetParserCacheEnabled(False)

    #---------------------------------------
    def OnFinished(self, result):
        N10X.Editor.RemoveUpdateFunction(self.Update)
        N10X.Editor.SetParserCacheEnabled(True)
        if result:
            N10X.Editor.ShowMessageBox("CppParserTest", "SUCCESS!")
            if self.m_ExitOnSuccess:
                N10X.Editor.ExecuteCommand("Exit")
        else:
            N10X.Editor.ShowMessageBox("CppParserTest", "FAIL!")

    #---------------------------------------
    def Start(self):
        self.StartNextTest()

    #---------------------------------------
    def StartNextTest(self):
        if self.m_Index < len(self.m_Tests):
            
            test = self.m_Tests[self.m_Index]

            print("-------------------------------------------------------------------")
            print("Test " + test[0] + " " + test[1].__name__)

            workspace_filename = self.m_TestsDir + "/" + test[0] + "/" + test[0] + ".sln"

            if not os.path.exists(workspace_filename):
                workspace_filename = self.m_TestsDir + "/" + test[0]
            
            print("workspace_filename: " + workspace_filename)

            abs_target_dir = os.path.abspath(self.m_TargetDir)
            abs_target_dir = abs_target_dir.replace("\\", "/")

            self.m_TargetWorkspacePath = abs_target_dir + "/" + test[0] + "/"

            N10X.Editor.AddParsersFinishedFunction(self.OnParsersFinished)

            OpenWorkspace(workspace_filename, self.m_TargetWorkspacePath)

        else:
            self.OnFinished(True)

    #---------------------------------------
    def OnParsersFinished(self):
        N10X.Editor.RemoveParsersFinishedFunction(self.OnParsersFinished)

        test = self.m_Tests[self.m_Index][1]
        if inspect.isclass(test):
            self.m_TestObject = test()
        else:
            try:
                test()
            except Exception as e:
                print("EXEPTION: " + str(e))
                traceback.print_exception(*sys.exc_info())
                self.OnFinished(False)
                return

            self.OnTestFinished()

    #---------------------------------------
    def Update(self):
        try:
            if self.m_TestObject and N10X.Editor.GetWorkspaceOpenComplete():
                if self.m_TestObject.Update():
                    self.m_TestObject = None
                    self.OnTestFinished()

        except Exception as e:
            print("EXEPTION: " + str(e))
            traceback.print_exception(*sys.exc_info())
            self.OnFinished(False)

    #---------------------------------------
    def OnTestFinished(self):
        if not g_RunningSingleTest:
            N10X.Editor.DiscardAllUnsavedChanges()
            N10X.Editor.CloseWorkspace()
        self.m_Index += 1
        self.StartNextTest()

