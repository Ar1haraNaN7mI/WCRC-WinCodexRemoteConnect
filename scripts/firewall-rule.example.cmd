@echo off
setlocal

REM Run as Administrator. Edit localport to match the internal server port.
netsh advfirewall firewall add rule name="WCRC mTLS remote bridge" dir=in action=allow protocol=TCP localport=49606
