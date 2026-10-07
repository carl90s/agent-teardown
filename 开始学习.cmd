@echo off
chcp 65001 >nul
title Agent 拆机工坊 . 学习台
set "ROOT=%~dp0"
set "APP=%ROOT%agent-teardown\index.html"
set "PLAN=%ROOT%学习方案.md"
set "PY="

rem ============ 探测 Python 解释器 ============
if defined PYTHON_EXE if exist "%PYTHON_EXE%" set "PY=%PYTHON_EXE%"
if not defined PY if exist "%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" set "PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul ^| findstr /v /i "WindowsApps"') do if not defined PY set "PY=%%i"
if not defined PY for /f "delims=" %%i in ('where py 2^>nul ^| findstr /v /i "WindowsApps"') do if not defined PY set "PY=%%i"

:menu
cls
echo.
echo   ================================================================
echo       Agent 拆机工坊 . 学习台
echo       配套《深入理解 AI Agent》(306 页 / 10 章) 的拆机版
echo   ================================================================
echo.
echo     你只要按数字键，不需要敲任何命令。
echo.
echo     [1]  打开闯关应用   (主教材，会用你的默认浏览器打开)
echo     [2]  打开学习方案   (总纲：路线图、时间表、卡点)
echo.
echo     ------- 动手实验 (离线，不联网，不装任何东西) -------
echo     [3]  lab1  亲手跑一个 ReAct 循环
echo     [4]  lab2  上下文消融 (复现书中实验 1-1)
echo     [5]  lab3  前缀缓存账单
echo     [6]  lab4  四种上下文压缩策略
echo     [7]  lab5  从零实现 BM25 与混合检索
echo     [8]  lab6  评估、置信区间与裁判偏差
echo     [9]  全部依次跑一遍
echo     [0]  退出
echo.
if defined PY (echo     解释器：%PY%) else (echo     解释器：尚未找到，跑实验时会提示怎么装)
echo.
set "c="
set /p "c=  请输入数字后回车："

if "%c%"=="1" goto app
if "%c%"=="2" goto plan
if "%c%"=="3" goto l1
if "%c%"=="4" goto l2
if "%c%"=="5" goto l3
if "%c%"=="6" goto l4
if "%c%"=="7" goto l5
if "%c%"=="8" goto l6
if "%c%"=="9" goto all
if "%c%"=="0" exit /b
goto menu

:app
if not exist "%APP%" ( echo   找不到 %APP% & call :wait & goto menu )
start "" "%APP%"
goto menu

:plan
if not exist "%PLAN%" ( echo   找不到 %PLAN% & call :wait & goto menu )
start "" "%PLAN%"
goto menu

:l1
call :run lab1_react.py
goto menu
:l2
call :run lab2_ablation.py
goto menu
:l3
call :run lab3_prefix_cache.py
goto menu
:l4
call :run lab4_compress.py
goto menu
:l5
call :run lab5_bm25.py
goto menu
:l6
call :run lab6_eval.py
goto menu

:all
call :run lab1_react.py
call :run lab2_ablation.py
call :run lab3_prefix_cache.py
call :run lab4_compress.py
call :run lab5_bm25.py
call :run lab6_eval.py
goto menu

:run
cls
echo.
echo   ----------------------------------------------------------------
echo    正在运行  %~1
echo   ----------------------------------------------------------------
echo.
if not exist "%ROOT%labs\%~1" (
  echo   找不到 %ROOT%labs\%~1
  echo.
  call :wait
  exit /b
)
if not defined PY goto nopy
"%PY%" -c "import numpy" >nul 2>&1
if errorlevel 1 goto nonumpy
pushd "%ROOT%labs"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
"%PY%" "%~1"
echo.
echo   ----------------------------------------------------------------
echo    退出码：%ERRORLEVEL%     (0 表示一切正常)
echo   ----------------------------------------------------------------
popd
call :wait
exit /b

:nopy
echo   没有找到 Python 解释器。请任选一种办法：
echo.
echo     A. 去 https://www.python.org/downloads/ 装 Python，
echo        安装时务必勾选 "Add python.exe to PATH"，然后重开本窗口。
echo.
echo     B. 如果你已经有 python.exe，只要设置一个环境变量
echo        PYTHON_EXE = 你的 python.exe 完整路径，然后重开本窗口。
echo.
call :wait
exit /b

:nonumpy
echo   解释器找到了：%PY%
echo   但它缺少 numpy，实验跑不起来。请执行下面这一行：
echo.
echo       "%PY%" -m pip install numpy
echo.
echo   (国内网络慢的话，可以加上清华镜像：
echo       "%PY%" -m pip install numpy -i https://pypi.tuna.tsinghua.edu.cn/simple )
echo.
call :wait
exit /b

rem 自带中文提示的"按任意键继续"：直接 pause 在 chcp 65001 下会变英文
:wait
echo.
echo   按任意键继续 . . .
pause >nul
exit /b
