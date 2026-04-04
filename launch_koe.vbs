Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set startup = wmi.Get("Win32_ProcessStartup").SpawnInstance_
startup.ShowWindow = 1
command = """C:\Users\gopin\Downloads\Koe\.venv\Scripts\pythonw.exe"" ""C:\Users\gopin\Downloads\Koe\run_koe.py"""
workingDir = "C:\Users\gopin\Downloads\Koe"
wmi.Get("Win32_Process").Create command, workingDir, startup, processId
