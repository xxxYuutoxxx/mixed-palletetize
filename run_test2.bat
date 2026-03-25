@echo off
cd /d C:\Users\onlyg\Documents\claude\palletize
C:\Users\onlyg\anaconda3\python.exe test_algorithm.py > C:\Users\onlyg\AppData\Local\Temp\testout.txt 2>&1
echo ExitCode=%ERRORLEVEL% >> C:\Users\onlyg\AppData\Local\Temp\testout.txt
