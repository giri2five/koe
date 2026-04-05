Dim shell
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "C:\Users\gopin\Downloads\Koe"
shell.Run """C:\Users\gopin\Downloads\Koe\.venv\Scripts\pythonw.exe"" ""C:\Users\gopin\Downloads\Koe\run_koe.py""", 0, False
