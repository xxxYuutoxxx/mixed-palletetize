@echo off
cd /d C:\Users\onlyg\Documents\claude\palletize
"C:\Users\onlyg\anaconda3\python.exe" -c "print('python ok')" > C:\Users\onlyg\AppData\Local\Temp\pytest.txt 2>&1
"C:\Users\onlyg\anaconda3\python.exe" test_algorithm.py >> C:\Users\onlyg\AppData\Local\Temp\pytest.txt 2>&1
echo Exit: %ERRORLEVEL% >> C:\Users\onlyg\AppData\Local\Temp\pytest.txt
