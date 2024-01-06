import N10X

# Close build panel if build succeeded
def OnBuildFinished(build_result):
    if build_result:
        N10X.Editor.ExecuteCommand("CloseBuildPanel")

N10X.Editor.AddBuildFinishedFunction(OnBuildFinished)
