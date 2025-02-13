from Utilities import *

def Test_Compare(TestName: str, A, B):
    if A == B:
        print(f'Test {TestName} PASSED')
    else:
        print(f'Test {TestName} FAILED\n {A} != {B}')

def _TestSourceCodeLine():
    Line = SourceCodeLine("const ENGINE_API ENGINE_API int* const ENGINE_API ComplexFunc(FVector a = (4.f, 2.f), int b = 42);",
                   0)
    Test_Compare("Initial len is 1", Line.PartsCount(), 1)

    # Test Split
    Line.Split(",")

    Test_Compare("Split result is 3 parts", Line.PartsCount(), 3)

    # Test each part is correctly splitted
    Test_Compare("Test each part is correctly splitted No. 0", str(Line.Head),
                 "const ENGINE_API ENGINE_API int* const ENGINE_API ComplexFunc(FVector a = (4.f")
    Test_Compare("Test each part is correctly splitted No. 1", str(Line.Head.Next),
                 " 2.f)")
    Test_Compare("Test each part is correctly splitted No. 2", str(Line.Head.Next.Next),
                 " int b = 42);")

    Test_Compare("Joined str of all parts is correct", str(Line),
                 "const ENGINE_API ENGINE_API int* const ENGINE_API ComplexFunc(FVector a = (4.f 2.f) int b = 42);")

    SubLine = SourceCodeLine("FVector a = (4.f, 2.f), int b = 42",
                   0, 62)

    SubLine.Split(",")

    Test_Compare("Split result is 3 parts", SubLine.PartsCount(), 3)

    # Test each part is correctly splitted
    Test_Compare("Test each part is correctly splitted No. 0", str(SubLine.Head),
                 "FVector a = (4.f")
    Test_Compare("Test each part is correctly splitted No. 1", str(SubLine.Head.Next),
                 " 2.f)")
    Test_Compare("Test each part is correctly splitted No. 2", str(SubLine.Head.Next.Next),
                 " int b = 42")

    Test_Compare("Joined str of all parts is correct", str(SubLine),
                 "FVector a = (4.f 2.f) int b = 42")


def RunTests():
    _TestSourceCodeLine()

# Run tests on startup may fail it we test N10X specific editor functionality
# RunTests()